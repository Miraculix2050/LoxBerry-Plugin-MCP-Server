"""Compare synthetic connected-graph query latency and index construction costs."""

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

from mcpserver.loxone.project import query
from mcpserver.loxone.project.graph import GraphEdge, GraphNode, ProjectGraph, ProjectSnapshot
from mcpserver.loxone.project.mapping import ProjectView, RuntimeMapping


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = subprocess.run(
        ["git", "show", f"{args.baseline_ref}:src/mcpserver/loxone/project/query.py"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout
    before = types.ModuleType("mcpserver.loxone.project._graph_baseline")
    before.__package__ = "mcpserver.loxone.project"
    sys.modules[before.__name__] = before
    exec(compile(source, "baseline/query.py", "exec"), before.__dict__)
    rows, memory = [], []
    for count in (1000, 10000, 50000):
        nodes = tuple(
            GraphNode(str(i), "p", i, "block", str(i), "Switch", ()) for i in range(count)
        )
        edges = tuple(GraphEdge(str(i), str(i + 1), "signal") for i in range(count - 1))
        graph = ProjectGraph(nodes, edges, ())
        view = ProjectView(
            ProjectSnapshot("synthetic", 15, (), graph), RuntimeMapping("synthetic", "v1", ())
        )
        modules = {"before": before, "after": query}
        queries = {}
        for index in range(5):
            for label in ("before", "after") if index % 2 == 0 else ("after", "before"):
                start = time.perf_counter()
                queries[label] = modules[label].ProjectQuery(view, {})
                rows.append(
                    {
                        "nodes": count,
                        "revision": label,
                        "operation": "build_index",
                        "ms": (time.perf_counter() - start) * 1000,
                    }
                )
        for label in modules:
            memory.append(
                {
                    "nodes": count,
                    "revision": label,
                    "index_accounted_bytes": queries[label].graph_index.container_bytes,
                }
            )
        node = nodes[count // 2]
        for operation in ("describe", "trace_downstream", "trace_upstream"):

            def run(label, queries=queries, operation=operation, node=node):
                selected = queries[label]
                if operation == "describe":
                    return selected.describe(node, limit=20)
                return selected.trace(
                    node, direction=operation.removeprefix("trace_"), max_depth=2, max_nodes=20
                )

            expected = run("before")
            for index in range(15):
                for label in ("before", "after") if index % 2 == 0 else ("after", "before"):
                    start = time.perf_counter()
                    result = run(label)
                    elapsed = (time.perf_counter() - start) * 1000
                    assert result == expected
                    rows.append(
                        {"nodes": count, "revision": label, "operation": operation, "ms": elapsed}
                    )
    summary = [
        {
            "nodes": count,
            "revision": label,
            "operation": operation,
            "median_ms": statistics.median(
                r["ms"]
                for r in rows
                if r["nodes"] == count and r["revision"] == label and r["operation"] == operation
            ),
        }
        for count in (1000, 10000, 50000)
        for operation in ("build_index", "describe", "trace_downstream", "trace_upstream")
        for label in ("before", "after")
    ]
    report = {
        "evidence": "synthetic_chain_exact_equivalence; index_accounting_not_RSS",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "baseline_ref": args.baseline_ref,
        "summary": summary,
        "samples": rows,
        "index_memory": memory,
    }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "index_memory": memory}, indent=2))


if __name__ == "__main__":
    main()
