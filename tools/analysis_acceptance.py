"""Validate value-free analysis workflow measurements against the 25-question catalog.

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
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= maximum


def validate_capture(document: dict, catalog: dict) -> list[dict]:
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
    if not isinstance(runs, list) or len(runs) > 150:
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
    incomplete = missing or unavailable or any(run["outcome"] == "incomplete" for run in runs)
    return {
        "version": 1,
        "status": "fail" if failed else "incomplete" if incomplete else "pass",
        "catalog_sha256": digest(catalog),
        "identity_sha256": digest(document["identity"]),
        "runs": len(runs),
        "missing_runs": missing,
        "unavailable_metrics": sorted({m for r in runs for m in METRICS if r[m] is None}),
        "results": results,
    }


def compare(reference: dict, observed: dict, catalog: dict) -> dict:
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
