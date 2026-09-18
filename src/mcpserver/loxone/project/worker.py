"""Disposable processing subprocess: no tokens, no source files, bounded IPC."""

import asyncio
import json
import os
import pickle
import sys
from dataclasses import asdict

from .graph import ProjectSnapshot, build_snapshot
from .models import DEFAULT_LIMITS, ProjectBundle, ProjectError, ProjectLimits
from .source import unpack_project

MAX_RESULT = 64 * 1024 * 1024


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
        stderr=asyncio.subprocess.DEVNULL,
        env=environment,
    )
    assert process.stdin is not None and process.stdout is not None

    async def send() -> None:
        assert process.stdin is not None
        process.stdin.write(data)
        await process.stdin.drain()
        process.stdin.close()

    sender = asyncio.create_task(send())
    try:
        async with asyncio.timeout(limits.timeout_seconds):
            chunks = bytearray()
            while chunk := await process.stdout.read(65536):
                chunks.extend(chunk)
                if len(chunks) > MAX_RESULT:
                    raise ProjectError("project_worker_limit")
            await sender
            code = await process.wait()
            if code != 0:
                raise ProjectError("project_worker_failed")
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
        await asyncio.gather(sender, return_exceptions=True)


def main() -> None:
    try:
        if sys.platform == "linux":
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        limits = ProjectLimits(**json.loads(sys.argv[2]))
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
