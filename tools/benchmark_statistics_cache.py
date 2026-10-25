"""Compare bounded statistics-cache fills against a Git ref, without target I/O."""

from __future__ import annotations

import argparse
import gc
import json
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
import types
from pathlib import Path

from mcpserver.loxone import statistics as current


def fill(module, count, mixed):
    cache = module.StatisticsCache(clock=lambda: 0.0)
    point = (module.StatisticPoint(100, 1.0),)
    for i in range(count):
        cache.put(f"synthetic-{i}", point if mixed and i % 2 else ())
    return cache


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = subprocess.run(
        ["git", "show", f"{args.baseline_ref}:src/mcpserver/loxone/statistics.py"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout
    before = types.ModuleType("_statistics_baseline")
    sys.modules[before.__name__] = before
    exec(compile(source, "baseline/statistics.py", "exec"), before.__dict__)
    modules = {"before": before, "after": current}
    rows = []
    for count in (1000, 5000):
        for mixed in (False, True):
            for index in range(3):
                for label in ("before", "after") if index % 2 == 0 else ("after", "before"):
                    gc.collect()
                    start = time.perf_counter()
                    cache = fill(modules[label], count, mixed)
                    elapsed = (time.perf_counter() - start) * 1000
                    rows.append(
                        {
                            "puts": count,
                            "mixed": mixed,
                            "revision": label,
                            "ms": elapsed,
                            "retained_entries": len(cache._memory),
                        }
                    )
                    del cache
    memory = []
    for label, module in modules.items():
        gc.collect()
        tracemalloc.start()
        cache = fill(module, 5000, False)
        retained, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        memory.append(
            {
                "revision": label,
                "retained_entries": len(cache._memory),
                "traced_retained_bytes": retained,
                "traced_peak_bytes": peak,
                "accounted_bytes": getattr(cache, "_accounted_bytes", None),
            }
        )
        del cache
    summary = [
        {
            "puts": count,
            "mixed": mixed,
            "revision": label,
            "median_fill_ms": statistics.median(
                r["ms"]
                for r in rows
                if r["puts"] == count and r["mixed"] == mixed and r["revision"] == label
            ),
        }
        for count in (1000, 5000)
        for mixed in (False, True)
        for label in ("before", "after")
    ]
    report = {
        "evidence": "synthetic_fixed_clock_fill; not_request_rate; memory_separate_from_timing",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "baseline_ref": args.baseline_ref,
        "summary": summary,
        "samples": rows,
        "memory": memory,
    }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "memory": memory}, indent=2))


if __name__ == "__main__":
    main()
