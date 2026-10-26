"""Compare warm snapshot latency during synthetic cold-family connection I/O."""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import subprocess
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace

from mcpserver.auth.provider import READ_SCOPE, StoredAccessToken
from mcpserver.loxone import runtime
from mcpserver.loxone.client import MiniserverEndpoint
from mcpserver.loxone.models import LoxoneIdentity, LoxoneStructure


def baseline(ref: str) -> types.ModuleType:
    source = subprocess.run(
        ["git", "show", f"{ref}:src/mcpserver/loxone/runtime.py"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout
    module = types.ModuleType("_warm_snapshot_baseline")
    sys.modules[module.__name__] = module
    exec(compile(source, f"{ref}/runtime.py", "exec"), module.__dict__)
    return module


def access(family: str) -> StoredAccessToken:
    return StoredAccessToken(
        token="synthetic",
        client_id="synthetic",
        scopes=[READ_SCOPE],
        expires_at=2_000_000_000,
        resource="https://example.test/mcp",
        subject="synthetic",
        claims={},
        family_id=family,
        identity_id="synthetic",
        miniserver_id="synthetic",
    )


async def sample(
    module: types.ModuleType, delay: float, contended: bool, handoff: bool = False
) -> dict[str, float]:
    owner = module.LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        SimpleNamespace(),
        max_active_sessions=2,
        structure_refresh_seconds=10**12,
    )
    entered = asyncio.Event()

    def record():
        return module._ConnectionRecord(
            LoxoneStructure(LoxoneIdentity("synthetic", "synthetic"), "v1", (), (), ()),
            frozenset(),
            SimpleNamespace(),
            asyncio.create_task(asyncio.Event().wait()),
            last_structure_check=time.monotonic(),
            last_used=time.monotonic(),
        )

    async def connect(_access):
        entered.set()
        await asyncio.sleep(delay)
        return record()

    owner._records["warm"] = record()
    owner._connect = connect
    if handoff:
        await owner._admission_lock.acquire()
    cold = asyncio.create_task(owner.snapshot(access("cold"))) if contended else None
    try:
        if handoff:
            await asyncio.sleep(0)
            owner._admission_lock.release()
            assert not owner._admission_lock.locked()
        elif cold is not None:
            await entered.wait()
        started = time.perf_counter()
        result = await owner.snapshot(access("warm"))
        elapsed = (time.perf_counter() - started) * 1000
        assert result.connected
        cold_pending = cold is not None and not cold.done()
        if cold is not None:
            await cold
        return {"warm_wall_ms": elapsed, "cold_still_pending_at_warm_return": cold_pending}
    finally:
        if cold is not None:
            await asyncio.gather(cold, return_exceptions=True)
        await owner.close()


async def measure(args: argparse.Namespace) -> dict[str, object]:
    before = baseline(args.baseline_ref)
    rows = []
    for contended, handoff in ((False, False), (True, False), (True, True)):
        for index in range(args.samples):
            pair = (("before", before), ("after", runtime))
            for label, module in pair if index % 2 == 0 else reversed(pair):
                rows.append(
                    {
                        "contended": contended,
                        "handoff": handoff,
                        "revision": label,
                        **await sample(module, args.delay_ms / 1000, contended, handoff),
                    }
                )
    summaries = []
    for contended, handoff in ((False, False), (True, False), (True, True)):
        for label in ("before", "after"):
            selected = [
                r
                for r in rows
                if r["contended"] == contended
                and r["handoff"] == handoff
                and r["revision"] == label
            ]
            summaries.append(
                {
                    "contended": contended,
                    "handoff": handoff,
                    "revision": label,
                    "median_warm_wall_ms": statistics.median(r["warm_wall_ms"] for r in selected),
                    "warm_returns_before_cold_finishes": sum(
                        r["cold_still_pending_at_warm_return"] for r in selected
                    ),
                }
            )
    return {
        "evidence": "synthetic_only_mocked_authorization_and_connection_I/O",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "baseline_ref": args.baseline_ref,
        "cold_delay_ms": args.delay_ms,
        "samples_per_revision_mode": args.samples,
        "summary": summaries,
        "samples": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--samples", type=int, choices=range(1, 101), default=15)
    parser.add_argument("--delay-ms", type=int, choices=range(1, 1001), default=250)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(measure(args))
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
