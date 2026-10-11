from __future__ import annotations

import copy
import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "analysis_acceptance", ROOT / "tools/analysis_acceptance.py"
)
assert spec is not None and spec.loader is not None
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)
CATALOG = acceptance.read_json(acceptance.CATALOG)


def capture() -> dict:
    return {
        "version": 1,
        "identity": {
            key: acceptance.digest(CATALOG)
            if key == "catalog_sha256"
            else "0" * 64
            if key == "tool_catalog_sha256"
            else "synthetic"
            for key in acceptance.IDENTITY_FIELDS
        },
        "runs": [
            {
                "case_id": case["id"],
                "run": run,
                "phase": phase,
                "outcome": "pass",
                "calls": case["baseline_workflow"],
                "guide_sections": ["full"],
                **{metric: 100 for metric in acceptance.METRICS},
            }
            for case in CATALOG["cases"]
            for run in (1, 2, 3)
            for phase in ("cold", "warm")
        ],
    }


def test_catalog_preserves_all_questions_and_acceptance_boundaries() -> None:
    assert Counter(case["group"] for case in CATALOG["cases"]) == {
        "lighting": 6,
        "basic": 7,
        "solar": 12,
        "knx": 2,
    }
    assert len({case["id"] for case in CATALOG["cases"]}) == 27
    for case in CATALOG["cases"]:
        assert case["required_sources"] and case["completeness"]
        assert case["valid_insufficient_evidence"] and len(case["prohibited_claims"]) >= 2
    fixtures = acceptance.read_json(ROOT / "tests/fixtures/analysis/reference.json")
    assert fixtures["synthetic"] is True
    assert fixtures["datasets"]["temperature_samples"]["expected"]["time_weighted_mean"] is None


def test_missing_runs_and_missing_metrics_never_pass() -> None:
    data = capture()
    data["runs"].pop()
    data["runs"][0]["input_tokens"] = None
    result = acceptance.summarize(data, CATALOG)
    assert result["status"] == "incomplete"
    assert result["unavailable_metrics"] == ["input_tokens"]
    assert result["missing_runs"]


def test_failed_workflow_is_not_hidden_by_missing_metrics() -> None:
    data = capture()
    data["runs"][0]["outcome"] = "fail"
    data["runs"][0]["input_tokens"] = None
    assert acceptance.summarize(data, CATALOG)["status"] == "fail"


def test_duplicate_runs_and_write_calls_are_rejected() -> None:
    data = capture()
    data["runs"][-1] = copy.deepcopy(data["runs"][0])
    with pytest.raises(ValueError, match="duplicate"):
        acceptance.validate_capture(data, CATALOG)
    for call in ("loxberry_save_installation_profile", "loxone_control", "loxone_operate_control"):
        data = capture()
        data["runs"][0]["calls"] = [call]
        with pytest.raises(ValueError, match="read_workflow"):
            acceptance.validate_capture(data, CATALOG)


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), "10", 10**400])
def test_invalid_metrics_are_rejected(value: object) -> None:
    data = capture()
    data["runs"][0]["duration_ms"] = value
    with pytest.raises(ValueError, match="metric"):
        acceptance.validate_capture(data, CATALOG)


def test_payload_fields_are_rejected_and_identity_is_not_echoed() -> None:
    data = capture()
    data["runs"][0]["arguments"] = {"private": "value"}
    with pytest.raises(ValueError, match="run_invalid"):
        acceptance.validate_capture(data, CATALOG)
    result = acceptance.summarize(capture(), CATALOG)
    assert "synthetic" not in json.dumps(result)
    assert result["status"] == "pass"


def test_comparison_requires_same_environment_and_does_not_auto_accept_performance() -> None:
    reference = capture()
    observed = copy.deepcopy(reference)
    for run in observed["runs"]:
        run["tool_result_tokens"] = 70
    result = acceptance.compare(reference, observed, CATALOG)
    assert result["status"] == "measured"
    assert result["automatic_performance_acceptance"] is False
    assert result["comparisons"][0]["tool_result_tokens_change_percent"] == pytest.approx(-30)
    observed["identity"]["model"] = "other"
    with pytest.raises(ValueError, match="environment_mismatch"):
        acceptance.compare(reference, observed, CATALOG)


def test_unknown_model_identity_cannot_establish_matching_benchmark() -> None:
    reference = capture()
    reference["identity"]["model"] = "unavailable"
    result = acceptance.compare(reference, copy.deepcopy(reference), CATALOG)
    assert result["status"] == "incomplete"
    assert result["reference"]["identity_complete"] is False
    assert result["comparisons"][0]["duration_ms_change_percent"] == 0
