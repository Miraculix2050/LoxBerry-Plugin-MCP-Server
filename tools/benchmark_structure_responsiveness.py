"""Compare synthetic load_structure wall time and event-loop lag against a Git ref."""

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
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from mcpserver.loxone import client
from mcpserver.loxone.events import MessageHeader, MessageType


def baseline(ref: str) -> types.ModuleType:
    source = subprocess.run(
        ["git", "show", f"{ref}:src/mcpserver/loxone/client.py"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout
    module = types.ModuleType("_structure_benchmark_baseline")
    sys.modules[module.__name__] = module
    exec(compile(source, f"{ref}/client.py", "exec"), module.__dict__)
    return module


async def sample(module: types.ModuleType, payload: str, mode: str) -> dict[str, float]:
    owners: dict[str, object] = {}
    session = module.LoxoneWebSocketSession(
        SimpleNamespace(send=AsyncMock()),
        public_key="unused",
        token=module.LoxoneToken("synthetic", "reader", "key", "SHA256", 100),
        timeout_seconds=10,
        max_payload_bytes=8 * 1024 * 1024,
        structure_lookup=SimpleNamespace(
            _has_received_structure=lambda _: bool(owners),
            _find_received_structure=owners.get,
        ),
    )
    receive = AsyncMock(
        return_value=(MessageHeader(MessageType.TEXT, False, len(payload)), payload)
    )
    session._receive = receive
    if mode != "cold":
        seed = await session.load_structure()
        owners[seed.parse_identity] = seed
        if mode == "changed":
            changed = payload.replace('"lastModified": "v1"', '"lastModified": "v2"')
            assert changed != payload
            receive.return_value = (MessageHeader(MessageType.TEXT, False, len(changed)), changed)
    lags = []

    async def heartbeat() -> None:
        while True:
            start = time.perf_counter()
            await asyncio.sleep(0.005)
            lags.append(max(0.0, time.perf_counter() - start - 0.005) * 1000)

    ticker = asyncio.create_task(heartbeat())
    await asyncio.sleep(0)
    start = time.perf_counter()
    try:
        result = await session.load_structure()
        wall = (time.perf_counter() - start) * 1000
        await asyncio.sleep(0.01)
    finally:
        ticker.cancel()
        with suppress(asyncio.CancelledError):
            await ticker
    assert len(result.controls) > 0
    return {"wall_ms": wall, "max_heartbeat_lag_ms": max(lags, default=0)}


async def measure(args: argparse.Namespace) -> dict[str, object]:
    before = baseline(args.baseline_ref)
    document = {
        "msInfo": {"serialNr": "synthetic"},
        "lastModified": "v1",
        "controls": {
            f"{i:08x}-0000-0000-0000000000000000": {
                "name": f"Switch {i}",
                "type": "Switch",
                "uuidAction": f"{i:08x}-0000-0000-0000000000000000",
                "states": {"active": f"{i:08x}-0001-0000-0000000000000000"},
            }
            for i in range(args.controls)
        },
    }
    payload = json.dumps(document)
    rows = []
    for mode in ("cold", "changed", "warm"):
        for index in range(args.samples):
            pair = (("before", before), ("after", client))
            for label, module in pair if index % 2 == 0 else reversed(pair):
                rows.append(
                    {"mode": mode, "revision": label, **await sample(module, payload, mode)}
                )
    summary = []
    for mode in ("cold", "changed", "warm"):
        for label in ("before", "after"):
            selected = [r for r in rows if r["mode"] == mode and r["revision"] == label]
            summary.append(
                {
                    "mode": mode,
                    "revision": label,
                    **{
                        key: statistics.median(r[key] for r in selected)
                        for key in ("wall_ms", "max_heartbeat_lag_ms")
                    },
                }
            )
    return {
        "evidence": "synthetic_only_mocked_transport_no_target_or_RSS_claim",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "baseline_ref": args.baseline_ref,
        "controls": args.controls,
        "samples_per_revision_mode": args.samples,
        "payload_bytes": len(payload.encode()),
        "summary_medians": summary,
        "samples": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--controls", type=int, choices=range(1, 20_001), default=20_000)
    parser.add_argument("--samples", type=int, choices=range(1, 31), default=7)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(measure(args))
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary_medians"], indent=2))


if __name__ == "__main__":
    main()
