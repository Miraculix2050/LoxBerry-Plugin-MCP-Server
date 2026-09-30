"""Disposable processing subprocess: no tokens, no source files, bounded IPC."""

import asyncio
import json
import os
import pickle
import struct
import sys
from contextlib import suppress
from dataclasses import asdict
from io import BytesIO
from time import perf_counter

from .analysis import analyze_knx
from .graph import GraphEdge, GraphNode, ProjectSnapshot, SemanticEdge, build_snapshot
from .mapping import ProjectView
from .models import DEFAULT_LIMITS, ProjectBundle, ProjectError, ProjectLimits
from .source import unpack_project
from .taxonomy import AddressTaxonomyEntry

MAX_RESULT = 64 * 1024 * 1024
MAX_ANALYSIS_INPUT = 64 * 1024 * 1024
_ANALYSIS_TIMINGS = struct.Struct("!4d")


def _reduce_graph_node(node: GraphNode) -> tuple[type[GraphNode], tuple[object, ...]]:
    return GraphNode, (
        node.key,
        node.project,
        node.source_index,
        node.kind,
        node.source_id,
        node.block_type,
        node.attributes,
        node.knx,
    )


def _reduce_graph_edge(edge: GraphEdge) -> tuple[type[GraphEdge], tuple[object, ...]]:
    return GraphEdge, (edge.source, edge.target, edge.kind)


def _reduce_semantic_edge(edge: SemanticEdge) -> tuple[type[SemanticEdge], tuple[object, ...]]:
    return SemanticEdge, (edge.source, edge.target, edge.rule_id, edge.interpretation, edge.effect)


def _analysis_payload(
    view: ProjectView, analyses: frozenset[str], taxonomy: tuple[AddressTaxonomyEntry, ...]
) -> bytes:
    """Avoid per-object frozen-slot field introspection; retain every graph field.

    The dispatch table is local to this pickler, never a global copyreg mutation.
    Constructors restore the same immutable types in the isolated child.
    """
    stream = BytesIO()
    pickler = pickle.Pickler(stream, protocol=5)
    pickler.dispatch_table = {
        GraphNode: _reduce_graph_node,
        GraphEdge: _reduce_graph_edge,
        SemanticEdge: _reduce_semantic_edge,
    }
    pickler.dump((view, analyses, taxonomy))
    return stream.getvalue()


async def process_project(
    data: bytes, limits: ProjectLimits = DEFAULT_LIMITS, *, bundle_only: bool = False
) -> tuple[ProjectBundle | ProjectSnapshot, int]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("MCPSERVER_")
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mcpserver.loxone.project.worker",
        "bundle" if bundle_only else "snapshot",
        json.dumps(asdict(limits)),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    stderr_task = asyncio.create_task(process.stderr.read())

    async def send() -> None:
        assert process.stdin is not None
        with suppress(BrokenPipeError, ConnectionResetError):
            process.stdin.write(data)
            await process.stdin.drain()
            process.stdin.close()

    sender = asyncio.create_task(send())
    try:
        async with asyncio.timeout(limits.processing_timeout_seconds):
            chunks = bytearray()
            while chunk := await process.stdout.read(65536):
                chunks.extend(chunk)
                if len(chunks) > MAX_RESULT:
                    raise ProjectError("project_worker_limit")
            await sender
            code = await process.wait()
            if code != 0:
                category = "project_worker_resource_limit" if code < 0 else "project_worker_failed"
                raise ProjectError(category)
            # Only this local worker serializes these bytes; never deserialize
            # network payloads. The worker creates closed, immutable model types.
            result = pickle.loads(chunks)
            if isinstance(result, ProjectError):
                raise result
            if not isinstance(result, ProjectBundle | ProjectSnapshot):
                raise ProjectError("project_worker_invalid")
            return result, len(chunks)
    except TimeoutError:
        raise ProjectError("project_worker_timeout") from None
    finally:
        sender.cancel()
        if process.returncode is None:
            process.kill()
        await process.wait()
        # Discard diagnostics so child exception text never reaches logs or callers.
        await stderr_task
        await asyncio.gather(sender, return_exceptions=True)


async def process_analysis(
    view: ProjectView,
    analyses: frozenset[str],
    taxonomy: tuple[AddressTaxonomyEntry, ...] = (),
    *,
    timings: dict[str, float | int] | None = None,
) -> dict[str, object]:
    """Run analysis; optional private diagnostics contain only durations and byte counts.

    stdin includes child startup/backpressure. Waiting ends at the first stdout
    byte; stdout measures the remaining stream through EOF, including child exit.
    Child durations overlap these parent intervals and must not be added to them.
    """
    started = perf_counter()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mcpserver.loxone.project.worker",
        "analysis-profile" if timings is not None else "analysis",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={key: value for key, value in os.environ.items() if not key.startswith("MCPSERVER_")},
    )
    spawned = perf_counter()
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    stderr_task = asyncio.create_task(process.stderr.read())
    payload = _analysis_payload(view, analyses, taxonomy)
    serialized = perf_counter()
    if len(payload) > MAX_ANALYSIS_INPUT:
        process.kill()
        await process.wait()
        await stderr_task
        raise ProjectError("project_worker_limit")
    try:
        async with asyncio.timeout(45):
            process.stdin.write(payload)
            await process.stdin.drain()
            process.stdin.close()
            sent = perf_counter()
            result = bytearray(await process.stdout.read(1))
            first_output = perf_counter()
            while chunk := await process.stdout.read(65536):
                result.extend(chunk)
                if len(result) > MAX_RESULT:
                    raise ProjectError("project_worker_limit")
            received = perf_counter()
            if (code := await process.wait()) != 0:
                raise ProjectError(
                    "project_worker_resource_limit" if code < 0 else "project_worker_failed"
                )
            exited = perf_counter()
            value = pickle.loads(result)
            deserialized = perf_counter()
            if isinstance(value, ProjectError):
                raise value
            if not isinstance(value, dict):
                raise ProjectError("project_worker_invalid")
            if timings is not None:
                timings.update(
                    process_start_seconds=spawned - started,
                    pickle_dumps_seconds=serialized - spawned,
                    stdin_transfer_seconds=sent - serialized,
                    child_wait_seconds=first_output - sent,
                    stdout_transfer_seconds=received - first_output,
                    process_exit_seconds=exited - received,
                    pickle_loads_seconds=deserialized - exited,
                    total_seconds=deserialized - started,
                    input_bytes=len(payload),
                    output_bytes=len(result),
                )
                child_timings = await stderr_task
                if len(child_timings) == _ANALYSIS_TIMINGS.size:
                    timings.update(
                        zip(
                            (
                                "child_stdin_seconds",
                                "child_pickle_loads_seconds",
                                "child_analysis_seconds",
                                "child_pickle_dumps_seconds",
                            ),
                            _ANALYSIS_TIMINGS.unpack(child_timings),
                            strict=True,
                        )
                    )
            return value
    except TimeoutError:
        raise ProjectError("project_worker_timeout") from None
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()
        await stderr_task


def main() -> None:
    try:
        if sys.argv[1] in {"analysis", "analysis-profile"}:
            if sys.platform == "linux":
                import resource

                resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
                resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            started = perf_counter()
            raw = sys.stdin.buffer.read(MAX_ANALYSIS_INPUT + 1)
            received = perf_counter()
            if len(raw) > MAX_ANALYSIS_INPUT:
                raise ProjectError("project_worker_limit")
            view, analyses, taxonomy = pickle.loads(raw)
            deserialized = perf_counter()
            if (
                not isinstance(view, ProjectView)
                or not isinstance(analyses, frozenset)
                or not isinstance(taxonomy, tuple)
                or any(not isinstance(item, AddressTaxonomyEntry) for item in taxonomy)
            ):
                raise ProjectError("project_worker_invalid")
            analysis_result = analyze_knx(view, analyses, taxonomy)
            analyzed = perf_counter()
            payload = pickle.dumps(analysis_result, protocol=5)
            serialized = perf_counter()
            if len(payload) > MAX_RESULT:
                raise ProjectError("project_worker_limit")
            if sys.argv[1] == "analysis-profile":
                sys.stderr.buffer.write(
                    _ANALYSIS_TIMINGS.pack(
                        received - started,
                        deserialized - received,
                        analyzed - deserialized,
                        serialized - analyzed,
                    )
                )
            sys.stdout.buffer.write(payload)
            return
        limits = ProjectLimits(**json.loads(sys.argv[2]))
        if sys.platform == "linux":
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
            cpu_seconds = max(1, int(limits.processing_timeout_seconds))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        data = sys.stdin.buffer.read(limits.download_bytes + 1)
        bundle = unpack_project(data, limits)
        result: ProjectBundle | ProjectSnapshot | ProjectError = (
            bundle if sys.argv[1] == "bundle" else build_snapshot(bundle, limits)
        )
        payload = pickle.dumps(result, protocol=5)
        if len(payload) > MAX_RESULT:
            raise ProjectError("project_worker_limit")
    except ProjectError as exc:
        payload = pickle.dumps(exc)
    except Exception:
        payload = pickle.dumps(ProjectError("project_worker_failed"))
    sys.stdout.buffer.write(payload)


if __name__ == "__main__":
    main()
