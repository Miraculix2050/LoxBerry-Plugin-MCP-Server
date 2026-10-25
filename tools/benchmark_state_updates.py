"""Compare one-event state-cache updates; synthetic identities and values only."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
import types
from pathlib import Path

from mcpserver.loxone.cache import UserStateCache
from mcpserver.loxone.events import StateEvent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = subprocess.run(
        ["git", "show", f"{args.baseline_ref}:src/mcpserver/loxone/cache.py"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout
    before = types.ModuleType("_state_update_baseline")
    sys.modules[before.__name__] = before
    exec(compile(source, "baseline/cache.py", "exec"), before.__dict__)
    rows = []
    event = (StateEvent("0", 2.0), StateEvent("denied", 3.0))
    for count in (100, 1000, 10000, 20000):
        for mode in ("immutable", "mutable"):
            allowed = (
                frozenset(str(i) for i in range(count))
                if mode == "immutable"
                else {str(i) for i in range(count)}
            )
            caches = {
                "before": before.UserStateCache(max_states_per_user=count),
                "after": UserStateCache(max_states_per_user=count),
            }
            for cache in caches.values():
                cache.apply(
                    "synthetic",
                    (StateEvent(str(i), 1.0) for i in range(count)),
                    allowed_uuids=allowed,
                )
            for index in range(101):
                for label in ("before", "after") if index % 2 == 0 else ("after", "before"):
                    start = time.perf_counter()
                    caches[label].apply("synthetic", event, allowed_uuids=allowed)
                    elapsed = (time.perf_counter() - start) * 1000
                    assert caches[label].get("synthetic", "0").value == 2.0
                    assert caches[label].get("synthetic", "denied").value is None
                    rows.append({"states": count, "mode": mode, "revision": label, "ms": elapsed})
    summary = [
        {
            "states": count,
            "mode": mode,
            "revision": label,
            "median_ms": statistics.median(
                r["ms"]
                for r in rows
                if r["states"] == count and r["mode"] == mode and r["revision"] == label
            ),
        }
        for count in (100, 1000, 10000, 20000)
        for mode in ("immutable", "mutable")
        for label in ("before", "after")
    ]
    report = {
        "evidence": "synthetic_only_cache_phase_setup_excluded_101_alternating_samples",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "baseline_ref": args.baseline_ref,
        "samples": rows,
        "summary": summary,
    }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
