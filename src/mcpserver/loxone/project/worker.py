"""Disposable processing subprocess: no tokens, no source files, bounded IPC."""

import asyncio
import json
import os
import pickle
import sys
from contextlib import suppress
from dataclasses import asdict

from .analysis import analyze_knx
from .graph import ProjectSnapshot, build_snapshot
from .mapping import ProjectView
from .models import DEFAULT_LIMITS, ProjectBundle, ProjectError, ProjectLimits
from .source import unpack_project

MAX_RESULT = 64 * 1024 * 1024
MAX_ANALYSIS_INPUT = 64 * 1024 * 1024


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


async def process_analysis(view: ProjectView, analyses: frozenset[str]) -> dict[str, object]:
    """Run CPU-bound aggregate analysis in the same restricted worker boundary."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mcpserver.loxone.project.worker",
        "analysis",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={key: value for key, value in os.environ.items() if not key.startswith("MCPSERVER_")},
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    stderr_task = asyncio.create_task(process.stderr.read())
    payload = pickle.dumps((view, analyses), protocol=5)
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
            result = bytearray()
            while chunk := await process.stdout.read(65536):
                result.extend(chunk)
                if len(result) > MAX_RESULT:
                    raise ProjectError("project_worker_limit")
            if (code := await process.wait()) != 0:
                raise ProjectError(
                    "project_worker_resource_limit" if code < 0 else "project_worker_failed"
                )
            value = pickle.loads(result)
            if isinstance(value, ProjectError):
                raise value
            if not isinstance(value, dict):
                raise ProjectError("project_worker_invalid")
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
        if sys.argv[1] == "analysis":
            if sys.platform == "linux":
                import resource

                resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
                resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            raw = sys.stdin.buffer.read(MAX_ANALYSIS_INPUT + 1)
            if len(raw) > MAX_ANALYSIS_INPUT:
                raise ProjectError("project_worker_limit")
            view, analyses = pickle.loads(raw)
            if not isinstance(view, ProjectView) or not isinstance(analyses, frozenset):
                raise ProjectError("project_worker_invalid")
            analysis_result = analyze_knx(view, analyses)
            payload = pickle.dumps(analysis_result, protocol=5)
            if len(payload) > MAX_RESULT:
                raise ProjectError("project_worker_limit")
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
