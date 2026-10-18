"""Validate value-free analysis workflow measurements against the versioned catalog.

This offline tool never calls a model, a Miniserver or a write operation. Captures
contain counters and independently adjudicated outcomes, never private prompts,
tool arguments, response text, identities or credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "tests/fixtures/analysis/scenarios.json"
MAX_BYTES = 8 * 1024 * 1024
MAX_CALLS = 1000
METRICS = (
    "duration_ms",
    "authorization_ms",
    "download_count",
    "sqlite_ms",
    "calculation_ms",
    "peak_bytes",
    "output_bytes",
    "tool_result_tokens",
    "input_tokens",
    "output_tokens",
)
IDENTITY_FIELDS = (
    "client",
    "client_version",
    "model",
    "tokenizer",
    "tokenizer_version",
    "guide_revision",
    "tool_catalog_sha256",
    "catalog_sha256",
    "environment",
)


def read_json(path: Path) -> dict:
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("capture_size_limit")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("capture_object_required")
    return value


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _number(value: object, *, maximum: float = 10**12) -> bool:
    return type(value) in (int, float) and 0 <= value <= maximum and math.isfinite(value)


def validate_capture(document: dict, catalog: dict) -> list[dict]:
    if document.get("version") == 2:
        return validate_capture_v2(document, catalog)
    if set(document) != {"version", "identity", "runs"} or document["version"] != 1:
        raise ValueError("capture_contract_invalid")
    identity = document["identity"]
    if not isinstance(identity, dict) or set(identity) != set(IDENTITY_FIELDS):
        raise ValueError("capture_identity_invalid")
    if any(not isinstance(value, str) or not 1 <= len(value) <= 256 for value in identity.values()):
        raise ValueError("capture_identity_invalid")
    if identity["catalog_sha256"] != digest(catalog):
        raise ValueError("capture_catalog_mismatch")
    if any(
        len(identity[key]) != 64 or any(char not in "0123456789abcdef" for char in identity[key])
        for key in ("catalog_sha256", "tool_catalog_sha256")
    ):
        raise ValueError("capture_digest_invalid")
    runs = document["runs"]
    max_runs = len(catalog["cases"]) * catalog["runs_per_case"] * 2
    if not isinstance(runs, list) or len(runs) > max_runs:
        raise ValueError("capture_run_limit")
    known = {case["id"] for case in catalog["cases"]}
    seen = set()
    allowed = {"case_id", "run", "phase", "outcome", "calls", "guide_sections", *METRICS}
    for run in runs:
        if not isinstance(run, dict) or set(run) != allowed:
            raise ValueError("capture_run_invalid")
        if (
            run["case_id"] not in known
            or type(run["run"]) is not int
            or run["run"] not in (1, 2, 3)
        ):
            raise ValueError("capture_case_invalid")
        if run["phase"] not in ("cold", "warm"):
            raise ValueError("capture_phase_invalid")
        key = (run["case_id"], run["run"], run["phase"])
        if key in seen:
            raise ValueError("capture_duplicate_run")
        seen.add(key)
        if run["outcome"] not in ("pass", "fail", "incomplete"):
            raise ValueError("capture_outcome_invalid")
        for metric in METRICS:
            value = run[metric]
            if value is not None and not _number(value):
                raise ValueError("capture_metric_invalid")
            if (
                metric.endswith(("count", "bytes", "tokens"))
                and value is not None
                and type(value) is not int
            ):
                raise ValueError("capture_counter_invalid")
        for name in ("calls", "guide_sections"):
            value = run[name]
            if (
                not isinstance(value, list)
                or len(value) > MAX_CALLS
                or any(
                    not isinstance(item, str)
                    or not 1 <= len(item) <= 128
                    or not all(c.isascii() and (c.isalnum() or c in "_.:-") for c in item)
                    for item in value
                )
            ):
                raise ValueError("capture_labels_invalid")
        read_calls = {call for case in catalog["cases"] for call in case["baseline_workflow"]}
        read_calls.update(
            call
            for case in catalog["cases"]
            for call in case.get("final_acceptance", {}).get("workflow", [])
        )
        read_calls.update(
            {"loxone_get_skill_guide", "loxone_get_installation_profile", "loxone_analyze_history"}
        )
        if any(call not in read_calls for call in run["calls"]):
            raise ValueError("capture_read_workflow_required")
    return runs


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def summarize(document: dict, catalog: dict) -> dict:
    if document.get("version") == 2:
        return summarize_v2(document, catalog)
    runs = validate_capture(document, catalog)
    missing = []
    results = []
    for case in catalog["cases"]:
        for phase in ("cold", "warm"):
            selected = [r for r in runs if r["case_id"] == case["id"] and r["phase"] == phase]
            if len(selected) != catalog["runs_per_case"]:
                missing.append({"case_id": case["id"], "phase": phase})
            metrics = {}
            for name in METRICS:
                values = [float(r[name]) for r in selected if r[name] is not None]
                metrics[name] = {
                    "measured": len(values),
                    "p50": statistics.median(values) if values else None,
                    "p95": percentile(values, 0.95),
                }
            results.append({"case_id": case["id"], "phase": phase, "metrics": metrics})
    failed = any(run["outcome"] == "fail" for run in runs)
    unavailable = any(value is None for run in runs for value in (run[m] for m in METRICS))
    identity_missing = any(
        value.casefold() in {"unavailable", "unknown", "unverified"}
        for value in document["identity"].values()
    )
    incomplete = (
        missing
        or unavailable
        or identity_missing
        or any(run["outcome"] == "incomplete" for run in runs)
    )
    return {
        "version": 1,
        "status": "fail" if failed else "incomplete" if incomplete else "pass",
        "catalog_sha256": digest(catalog),
        "identity_sha256": digest(document["identity"]),
        "identity_complete": not identity_missing,
        "runs": len(runs),
        "missing_runs": missing,
        "unavailable_metrics": sorted({m for r in runs for m in METRICS if r[m] is None}),
        "results": results,
    }


def compare(reference: dict, observed: dict, catalog: dict) -> dict:
    if reference.get("version") == 2 or observed.get("version") == 2:
        return compare_v2(reference, observed, catalog)
    left = summarize(reference, catalog)
    right = summarize(observed, catalog)
    # Code/guide contracts change intentionally; execution environment must match.
    comparable = (
        "client",
        "client_version",
        "model",
        "tokenizer",
        "tokenizer_version",
        "environment",
    )
    if any(reference["identity"][key] != observed["identity"][key] for key in comparable):
        raise ValueError("capture_environment_mismatch")
    pairs = []
    for before, after in zip(left["results"], right["results"], strict=True):
        item = {"case_id": after["case_id"], "phase": after["phase"]}
        for name in ("duration_ms", "tool_result_tokens"):
            base = before["metrics"][name]["p50"]
            current = after["metrics"][name]["p50"]
            item[name + "_change_percent"] = (
                (current / base - 1) * 100 if base and current is not None else None
            )
        pairs.append(item)
    return {
        "status": "fail"
        if "fail" in (left["status"], right["status"])
        else "incomplete"
        if "incomplete" in (left["status"], right["status"])
        else "measured",
        "reference": left,
        "observed": right,
        "comparisons": pairs,
        "automatic_performance_acceptance": False,
    }


V2_IDENTITY_FIELDS = (
    *IDENTITY_FIELDS,
    "runtime",
    "workload_sha256",
    "serialization",
    "measurement_boundary",
    "cold_conditions",
    "warm_conditions",
)
V2_OPTIONAL_METRICS = tuple(m for m in METRICS if m not in {"duration_ms", "output_bytes"})
V2_CALL_FIELDS = {
    "tool",
    "status",
    "duration_ms",
    "response_bytes",
    "guide_section",
    "guide_module_bytes",
    "page",
    "retry",
    "fallback_reason",
}
FALLBACK_REASONS = {
    "source_unavailable",
    "unsupported",
    "permission_denied",
    "rate_limit",
    "incomplete_coverage",
    "tool_error",
    "other",
}


def _capture_labels(value: object, *, maximum: int = 128) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and all(c.isascii() and (c.isalnum() or c in "_.:-") for c in value)
    )


@cache
def _v2_read_calls() -> frozenset[str]:
    from mcpserver.schema_reference import tool_schema_catalog

    return frozenset(
        {
            t["name"]
            for t in tool_schema_catalog("acceptance")["tools"]
            if t.get("annotations", {}).get("readOnlyHint") is True
        }
        | {"prompts.list", "prompts.get"}
    )


def validate_capture_v2(document: dict, catalog: dict) -> list[dict]:
    if type(document.get("version")) is not int or document["version"] != 2:
        raise ValueError("capture_contract_invalid")
    if set(document) != {"version", "identity", "plan", "catalog_reads", "runs"}:
        raise ValueError("capture_contract_invalid")
    identity, plan = document["identity"], document["plan"]
    if (
        not isinstance(identity, dict)
        or set(identity) != set(V2_IDENTITY_FIELDS)
        or any(not isinstance(v, str) or not 1 <= len(v) <= 256 for v in identity.values())
    ):
        raise ValueError("capture_identity_invalid")
    for key in ("catalog_sha256", "tool_catalog_sha256", "workload_sha256"):
        if len(identity[key]) != 64 or any(c not in "0123456789abcdef" for c in identity[key]):
            raise ValueError("capture_digest_invalid")
    if identity["catalog_sha256"] != digest(catalog):
        raise ValueError("capture_catalog_mismatch")
    if identity["serialization"] != "canonical_json_utf8_v1":
        raise ValueError("capture_serialization_invalid")
    known = {c["id"] for c in catalog["cases"]}
    if (
        not isinstance(plan, dict)
        or set(plan) != {"case_ids", "runs_per_case", "record_limit"}
        or not isinstance(plan["case_ids"], list)
        or not plan["case_ids"]
        or any(not isinstance(c, str) or c not in known for c in plan["case_ids"])
        or len(set(plan["case_ids"])) != len(plan["case_ids"])
        or type(plan["runs_per_case"]) is not int
        or plan["runs_per_case"] not in (1, 2, 3)
        or type(plan["record_limit"]) is not int
        or not 1 <= plan["record_limit"] <= 50
        or len(plan["case_ids"]) * plan["runs_per_case"] * 2 > plan["record_limit"]
    ):
        raise ValueError("capture_plan_invalid")
    reads = document["catalog_reads"]
    if not isinstance(reads, list) or len(reads) > MAX_CALLS:
        raise ValueError("capture_catalog_reads_invalid")
    for read in reads:
        if not isinstance(read, dict) or set(read) != {
            "response_bytes",
            "description_bytes",
            "schema_bytes",
        }:
            raise ValueError("capture_catalog_reads_invalid")
        if any(v is not None and (type(v) is not int or not _number(v)) for v in read.values()):
            raise ValueError("capture_counter_invalid")
    runs = document["runs"]
    if not isinstance(runs, list) or len(runs) > plan["record_limit"]:
        raise ValueError("capture_run_limit")
    seen = set()
    read_calls = _v2_read_calls()
    for run in runs:
        if not isinstance(run, dict) or set(run) != {
            "case_id",
            "run",
            "phase",
            "outcome",
            "calls",
            "optional_metrics",
        }:
            raise ValueError("capture_run_invalid")
        if (
            run["case_id"] not in plan["case_ids"]
            or type(run["run"]) is not int
            or run["run"] not in range(1, plan["runs_per_case"] + 1)
            or run["phase"] not in ("cold", "warm")
        ):
            raise ValueError("capture_case_invalid")
        key = (run["case_id"], run["run"], run["phase"])
        if key in seen:
            raise ValueError("capture_duplicate_run")
        seen.add(key)
        if run["outcome"] not in ("pass", "fail", "incomplete"):
            raise ValueError("capture_outcome_invalid")
        optional = run["optional_metrics"]
        if not isinstance(optional, dict) or set(optional) != set(V2_OPTIONAL_METRICS):
            raise ValueError("capture_metric_invalid")
        for name, value in optional.items():
            if value is not None and (
                not _number(value)
                or (name.endswith(("count", "bytes", "tokens")) and type(value) is not int)
            ):
                raise ValueError("capture_metric_invalid")
        if not isinstance(run["calls"], list) or len(run["calls"]) > MAX_CALLS:
            raise ValueError("capture_calls_invalid")
        for call in run["calls"]:
            if not isinstance(call, dict) or set(call) != V2_CALL_FIELDS:
                raise ValueError("capture_call_invalid")
            if call["tool"] not in read_calls:
                raise ValueError("capture_read_workflow_required")
            if call["status"] not in ("ok", "error", "timeout"):
                raise ValueError("capture_call_status_invalid")
            for name in ("duration_ms", "response_bytes", "guide_module_bytes"):
                v = call[name]
                if v is not None and (
                    not _number(v) or (name.endswith("bytes") and type(v) is not int)
                ):
                    raise ValueError("capture_metric_invalid")
            if any(type(call[n]) is not bool for n in ("page", "retry")):
                raise ValueError("capture_counter_invalid")
            if (
                call["fallback_reason"] is not None
                and call["fallback_reason"] not in FALLBACK_REASONS
            ):
                raise ValueError("capture_fallback_invalid")
            if call["tool"] == "loxone_get_skill_guide":
                if call["guide_section"] is not None and not _capture_labels(call["guide_section"]):
                    raise ValueError("capture_labels_invalid")
                if (
                    call["guide_module_bytes"] is not None
                    and call["response_bytes"] is not None
                    and call["guide_module_bytes"] > call["response_bytes"]
                ):
                    raise ValueError("capture_guide_bytes_invalid")
            elif call["guide_section"] is not None or call["guide_module_bytes"] is not None:
                raise ValueError("capture_guide_bytes_invalid")
    return runs


def _v2_totals(run: dict) -> dict:
    calls = run["calls"]

    def total(selected: list[dict], key: str) -> int | float | None:
        return None if any(c[key] is None for c in selected) else sum(c[key] for c in selected)

    guides = [c for c in calls if c["tool"] == "loxone_get_skill_guide"]
    other = [c for c in calls if c["tool"] != "loxone_get_skill_guide"]
    return {
        "mcp_sum_ms": total(calls, "duration_ms"),
        "response_bytes": total(calls, "response_bytes"),
        "guide_response_bytes": total(guides, "response_bytes"),
        "guide_module_bytes": total(guides, "guide_module_bytes"),
        "other_response_bytes": total(other, "response_bytes"),
        "call_count": len(calls),
        "guide_fetch_count": len(guides),
        "page_count": sum(c["page"] for c in calls),
        "retry_count": sum(c["retry"] for c in calls),
        "fallback_count": sum(c["fallback_reason"] is not None for c in calls),
        "error_count": sum(c["status"] == "error" for c in calls),
        "timeout_count": sum(c["status"] == "timeout" for c in calls),
        "failure_rate": sum(c["status"] != "ok" for c in calls) / len(calls) if calls else None,
        "timeout_rate": sum(c["status"] == "timeout" for c in calls) / len(calls)
        if calls
        else None,
    }


def summarize_v2(document: dict, catalog: dict) -> dict:
    runs = validate_capture_v2(document, catalog)
    plan = document["plan"]
    expected = {
        (c, n, p)
        for c in plan["case_ids"]
        for n in range(1, plan["runs_per_case"] + 1)
        for p in ("cold", "warm")
    }
    seen = {(r["case_id"], r["run"], r["phase"]) for r in runs}
    missing = [{"case_id": c, "run": n, "phase": p} for c, n, p in sorted(expected - seen)]
    original = {c["id"] for c in catalog["cases"] if c["group"] != "knx"}
    missing_cases = sorted(original - set(plan["case_ids"]))
    unavailable = set()
    for key in (
        "environment",
        "runtime",
        "measurement_boundary",
        "cold_conditions",
        "warm_conditions",
    ):
        if document["identity"][key].casefold() in {"unknown", "unavailable", "unverified"}:
            unavailable.add("identity." + key)
    rows = []
    for run in runs:
        totals = _v2_totals(run)
        unavailable.update(k for k, v in totals.items() if v is None)
        if not run["calls"]:
            unavailable.add("task_call_evidence")
        if any(
            c["tool"] == "loxone_get_skill_guide" and c["guide_section"] is None
            for c in run["calls"]
        ):
            unavailable.add("guide_section")
        rows.append(
            {
                "case_id": run["case_id"],
                "run": run["run"],
                "phase": run["phase"],
                "outcome": run["outcome"],
                "optional_metrics": run["optional_metrics"],
                "calls": run["calls"],
                **totals,
            }
        )
    if not document["catalog_reads"] or any(
        v is None for r in document["catalog_reads"] for v in r.values()
    ):
        unavailable.add("catalog_bytes")
    failed = any(r["outcome"] == "fail" for r in runs)
    incomplete = (
        missing or missing_cases or unavailable or any(r["outcome"] == "incomplete" for r in runs)
    )
    distributions = []
    for case_id in plan["case_ids"]:
        for phase in ("cold", "warm"):
            selected = [r for r in rows if r["case_id"] == case_id and r["phase"] == phase]
            values = [r["mcp_sum_ms"] for r in selected if r["mcp_sum_ms"] is not None]
            distributions.append(
                {
                    "case_id": case_id,
                    "phase": phase,
                    "samples": len(values),
                    "p50_ms": statistics.median(values) if values else None,
                    "p95_ms": percentile(values, 0.95),
                    "min_ms": min(values) if values else None,
                    "max_ms": max(values) if values else None,
                    "p95_kind": "descriptive_only_no_stability_claim",
                }
            )
    return {
        "version": 2,
        "status": "fail" if failed else "incomplete" if incomplete else "pass",
        "identity_sha256": digest(document["identity"]),
        "catalog_sha256": digest(catalog),
        "runs": len(runs),
        "record_limit": plan["record_limit"],
        "missing_runs": missing,
        "missing_original_cases": missing_cases,
        "unavailable_mandatory_metrics": sorted(unavailable),
        "timing_mode": "sum_of_call_durations_not_elapsed_wall_time",
        "catalog_retrieval_count": len(document["catalog_reads"]),
        "catalog_reads": document["catalog_reads"],
        "results": rows,
        "distributions": distributions,
        "acceptance": "requires_independent_review",
        "optional_unavailable_metrics": sorted(
            {m for r in runs for m, v in r["optional_metrics"].items() if v is None}
        ),
    }


def compare_v2(reference: dict, observed: dict, catalog: dict) -> dict:
    if reference.get("version") != 2 or observed.get("version") != 2:
        raise ValueError("capture_version_mismatch")
    left, right = summarize_v2(reference, catalog), summarize_v2(observed, catalog)
    fields = (
        "client",
        "client_version",
        "model",
        "environment",
        "runtime",
        "workload_sha256",
        "serialization",
        "measurement_boundary",
        "cold_conditions",
        "warm_conditions",
    )
    if reference["plan"] != observed["plan"] or any(
        reference["identity"][k] != observed["identity"][k] for k in fields
    ):
        raise ValueError("capture_environment_mismatch")
    before = {(r["case_id"], r["run"], r["phase"]): r for r in left["results"]}
    pairs = []
    for after in right["results"]:
        key = (after["case_id"], after["run"], after["phase"])
        base = before.get(key)
        row = {k: after[k] for k in ("case_id", "run", "phase")}
        row["quality_review_required"] = True
        row["both_outcomes_pass"] = (
            base is not None and base["outcome"] == after["outcome"] == "pass"
        )
        for name in (
            "response_bytes",
            "mcp_sum_ms",
            "call_count",
            "page_count",
            "retry_count",
            "fallback_count",
            "guide_response_bytes",
            "guide_module_bytes",
            "other_response_bytes",
            "guide_fetch_count",
        ):
            old, new = base[name] if base else None, after[name]
            row[name] = {
                "baseline": old,
                "final": new,
                "change_percent": (new / old - 1) * 100 if old and new is not None else None,
            }
        pairs.append(row)
    catalog_comparison = {}
    for name in ("response_bytes", "description_bytes", "schema_bytes"):
        totals = []
        for capture in (reference, observed):
            reads = capture["catalog_reads"]
            totals.append(
                sum(r[name] for r in reads)
                if reads and all(r[name] is not None for r in reads)
                else None
            )
        old, new = totals
        catalog_comparison[name] = {
            "baseline": old,
            "final": new,
            "change_percent": (new / old - 1) * 100 if old and new is not None else None,
        }
    return {
        "status": "fail"
        if "fail" in (left["status"], right["status"])
        else "incomplete"
        if "incomplete" in (left["status"], right["status"])
        else "measured",
        "reference": left,
        "observed": right,
        "pairs": pairs,
        "catalog_comparison": catalog_comparison,
        "acceptance": "requires_independent_quality_equivalence_and_performance_review",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    try:
        catalog = read_json(args.catalog)
        if args.capture is None:
            if args.baseline is not None:
                raise ValueError("capture_required")
            result = {
                "status": "incomplete",
                "cases": len(catalog["cases"]),
                "catalog_sha256": digest(catalog),
                "reason": "workflow_capture_required",
            }
        else:
            capture = read_json(args.capture)
            result = (
                compare(read_json(args.baseline), capture, catalog)
                if args.baseline
                else summarize(capture, catalog)
            )
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print(json.dumps({"status": "invalid", "error": "acceptance_capture_invalid"}))
        return 2
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["status"] in ("pass", "measured") else 1 if result["status"] == "fail" else 2


if __name__ == "__main__":
    sys.exit(main())
