"""Compare project search against a Git baseline using synthetic data only."""

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
from types import SimpleNamespace

from mcpserver.loxone.project import query
from mcpserver.loxone.project.graph import build_snapshot
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.source import unpack_project
from tools.benchmark_project_families import synthetic_project


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--samples", type=int, choices=range(1, 101), default=15)
    parser.add_argument("--nodes", type=int, choices=range(1, 10001), default=10000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = subprocess.run(
        ["git", "show", f"{args.baseline_ref}:src/mcpserver/loxone/project/query.py"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout
    before = types.ModuleType("mcpserver.loxone.project._search_baseline")
    before.__package__ = "mcpserver.loxone.project"
    sys.modules[before.__name__] = before
    exec(compile(source, "baseline/query.py", "exec"), before.__dict__)
    snapshot = build_snapshot(unpack_project(synthetic_project(args.nodes)))
    view = ProjectView(
        snapshot, map_runtime(snapshot, SimpleNamespace(controls=(), last_modified="v1"))
    )
    queries = {"before": before.ProjectQuery(view, {}), "after": query.ProjectQuery(view, {})}
    rows = []
    filters = dict(kind=None, block_type=None, source_id=None, runtime_control_uuid=None)
    for mode, text in (
        ("all", None),
        ("absent", "no-match"),
        ("selective", f"{args.nodes - 1:08x}"),
    ):
        expected = queries["before"].find(query=text, **filters)
        for index in range(args.samples):
            order = ("before", "after") if index % 2 == 0 else ("after", "before")
            for label in order:
                start = time.perf_counter()
                result = queries[label].find(query=text, **filters)
                elapsed = (time.perf_counter() - start) * 1000
                assert result == expected
                rows.append(
                    {"mode": mode, "revision": label, "ms": elapsed, "matches": len(result)}
                )
    summary = [
        {
            "mode": mode,
            "revision": label,
            "median_ms": statistics.median(
                r["ms"] for r in rows if r["mode"] == mode and r["revision"] == label
            ),
        }
        for mode in ("all", "absent", "selective")
        for label in ("before", "after")
    ]
    report = {
        "evidence": "synthetic_only_query_phase_exact_result_equivalence",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "baseline_ref": args.baseline_ref,
        "nodes": args.nodes,
        "samples": rows,
        "summary": summary,
    }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
