"""Offline OAuth-family content-reuse benchmark; synthetic input only."""

from __future__ import annotations

import argparse
import asyncio
import gc
import hashlib
import json
import statistics
import struct
import time
import tracemalloc
import zlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import mcpserver.loxone.project.service as service_module
from mcpserver.loxone.project.graph import build_snapshot
from mcpserver.loxone.project.service import ProjectService
from mcpserver.loxone.project.source import unpack_project
from mcpserver.loxone.project.worker import process_project


def synthetic_project(nodes: int) -> bytes:
    """Generate a literal-only LoxCC envelope without installation data."""
    if not 1 <= nodes <= 10_000:
        raise ValueError("nodes must be between 1 and 10000")
    plain = (
        "<Root>"
        + "".join(f'<C U="{index:08x}" Type="Switch"/>' for index in range(nodes))
        + "</Root>"
    ).encode("ascii")
    extra = len(plain) - 15
    extension = bytes([255]) * (extra // 255) + bytes([extra % 255])
    packed = b"\xf0" + extension + plain
    return struct.pack("<IIII", 0xAABBCCEE, len(packed), len(plain), zlib.crc32(plain)) + packed


def parser_baseline(data: bytes, samples: int) -> dict[str, int | float]:
    """Measure parser CPU/allocations in this process, outside transport and IPC."""
    wall: list[float] = []
    cpu: list[float] = []
    peaks: list[int] = []
    retained: list[int] = []
    for _ in range(samples):
        gc.collect()
        tracemalloc.start()
        start_wall = time.perf_counter()
        start_cpu = time.process_time()
        snapshot = build_snapshot(unpack_project(data))
        cpu.append((time.process_time() - start_cpu) * 1000)
        wall.append((time.perf_counter() - start_wall) * 1000)
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        retained.append(current)
        peaks.append(peak)
        del snapshot
    return {
        "samples": samples,
        "wall_median_ms": statistics.median(wall),
        "cpu_median_ms": statistics.median(cpu),
        "python_peak_max_bytes": max(peaks),
        "python_retained_median_bytes": statistics.median(retained),
    }


async def family_baseline(data: bytes, families: int, warm_calls: int) -> dict[str, object]:
    """Exercise the service with fake authorization and real worker IPC."""
    client = SimpleNamespace(
        download_project=AsyncMock(return_value=data),
        project_marker=AsyncMock(return_value="synthetic-version"),
    )
    service = ProjectService(
        client,
        SimpleNamespace(get=Mock(side_effect=lambda *_: Mock())),
        SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=False)),
        AsyncMock(return_value=True),
    )
    worker_calls = 0
    worker_ms = 0.0

    async def timed_worker(*args, **kwargs):
        nonlocal worker_calls, worker_ms
        start = time.perf_counter()
        try:
            return await process_project(*args, **kwargs)
        finally:
            worker_calls += 1
            worker_ms += (time.perf_counter() - start) * 1000

    phases: list[dict[str, int | float | str]] = []
    tracemalloc.start()
    try:
        with patch.object(service_module, "process_project", timed_worker):
            for family in range(families):
                access = SimpleNamespace(
                    scopes=["loxone:read"],
                    family_id=f"synthetic-{family}",
                    miniserver_id="synthetic-miniserver",
                    identity_id="synthetic-user",
                )
                for phase, calls in (("cold", 1), ("warm", warm_calls)):
                    downloads_before = client.download_project.await_count
                    markers_before = client.project_marker.await_count
                    workers_before, worker_before_ms = worker_calls, worker_ms
                    start = time.perf_counter()
                    for _ in range(calls):
                        await service.load_snapshot(access)
                    elapsed = (time.perf_counter() - start) * 1000
                    downloads = client.download_project.await_count - downloads_before
                    phases.append(
                        {
                            "family_index": family,
                            "phase": phase,
                            "calls": calls,
                            "download_count": downloads,
                            "download_bytes": downloads * len(data),
                            "marker_count": client.project_marker.await_count - markers_before,
                            "worker_count": worker_calls - workers_before,
                            "worker_wall_ms": worker_ms - worker_before_ms,
                            "load_wall_ms": elapsed,
                        }
                    )
        current, peak = tracemalloc.get_traced_memory()
        return {
            "phases": phases,
            "cache_entries": len(service._cache),
            "cache_accounted_bytes": service._cache_bytes(),
            "content_entries": len({id(entry[1]) for entry in service._cache.values()}),
            "parent_python_retained_bytes": current,
            "parent_python_peak_bytes": peak,
        }
    finally:
        tracemalloc.stop()
        await service.close()


def bounded_count(value: str) -> int:
    count = int(value)
    if not 1 <= count <= 100:
        raise argparse.ArgumentTypeError("count must be between 1 and 100")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--nodes", type=int, choices=range(1, 10_001), default=1000, metavar="1..10000"
    )
    parser.add_argument("--families", type=int, choices=range(1, 9), default=2, metavar="1..8")
    parser.add_argument("--samples", type=bounded_count, default=3)
    parser.add_argument("--warm-calls", type=bounded_count, default=3)
    args = parser.parse_args()
    data = synthetic_project(args.nodes)
    report = {
        "schema_version": 1,
        "evidence": "synthetic_only",
        "nodes": args.nodes,
        "input_bytes": len(data),
        "synthetic_sha256": hashlib.sha256(data).hexdigest(),
        "parser_in_process": parser_baseline(data, args.samples),
        "service_baseline": asyncio.run(family_baseline(data, args.families, args.warm_calls)),
        "unmeasured": [
            "network",
            "fresh_visible_structure",
            "mapping",
            "query",
            "cursors",
            "worker_peak_rss",
            "service_peak_rss",
            "target_end_to_end",
        ],
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
