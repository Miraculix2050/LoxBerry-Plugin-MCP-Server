from __future__ import annotations

import copy
import importlib.util
import json
import time
from collections import Counter
from pathlib import Path

import pytest

from mcpserver.history_analysis import duration_summary, reconstruct_segments, statistic_summary
from mcpserver.history_comparison import ComparisonInput, compare_history
from mcpserver.loxone.state_semantics import SeriesSemantics
from mcpserver.loxone.statistics import StatisticPoint
from mcpserver.schema_reference import tool_schema_catalog

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "analysis_acceptance", ROOT / "tools/analysis_acceptance.py"
)
assert spec is not None and spec.loader is not None
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)
CATALOG = acceptance.read_json(acceptance.CATALOG)


def test_final_matrix_preserves_original_questions_and_matches_released_tools() -> None:
    names = {tool["name"] for tool in tool_schema_catalog("synthetic")["tools"]}
    original = [case for case in CATALOG["cases"] if case["group"] != "knx"]
    assert len(original) == 25
    baseline_rows = [
        {key: value for key, value in case.items() if key != "final_acceptance"}
        for case in original
    ]
    assert (
        acceptance.digest(baseline_rows)
        == "34b571991da29aa1fbf3d6fc1c4d9f8e479fe408a447694d80496d028a2fdf89"
    )
    for language in ("de", "en"):
        matrix = (ROOT / f"docs/user/analysis-support.{language}.md").read_text(encoding="utf-8")
        for case in original:
            result = case["final_acceptance"]
            assert result["support"] in {"supported", "conditional", "unavailable", "experimental"}
            assert set(result["workflow"]) <= names
            assert result["scope_" + language] in matrix and f"| {case['id']} |" in matrix
            assert result["ai_three_independent_runs"] == "incomplete"
            assert case["reference"] and case["completeness"] and case["prohibited_claims"]


def test_original_numeric_references_against_delivered_core() -> None:
    datasets = acceptance.read_json(ROOT / "tests/fixtures/analysis/reference.json")["datasets"]

    def source(values, meaning="interval_difference_sum", unit="kWh", role=None, boundary=None):
        semantics = SeriesSemantics(
            "partial",
            meaning,
            unit=unit,
            measurement_quantity="energy",
            timestamp_basis="unix_utc",
            timestamp_position="interval_start"
            if meaning == "interval_difference_sum"
            else "observation",
        )
        points = tuple(StatisticPoint(t, value) for t, value in values)
        result = statistic_summary(
            "energy",
            semantics,
            points,
            start=0,
            end=18000,
            control_uuid="synthetic",
            source_id="synthetic",
        )
        result.binding_id = boundary or role
        return ComparisonInput(
            result, semantics, points, profile_role=role, declared_boundary=boundary
        )

    def comparison(operation, inputs, end=18000):
        return compare_history(
            operation,
            tuple(inputs),
            start=0,
            end=end,
            timezone_name="UTC",
            comparable_boundaries_confirmed=True,
            night_start_hour=0,
            night_end_hour=5,
            deadline=time.monotonic() + 10,
        )

    temperatures = datasets["temperature_samples"]
    semantic = SeriesSemantics(
        "partial",
        "sample",
        unit="degC",
        measurement_quantity="temperature",
        timestamp_basis="unix_utc",
    )
    result = statistic_summary(
        "temperature_summary",
        semantic,
        tuple(StatisticPoint(t, v) for t, v in temperatures["points"]),
        start=0,
        end=18000,
        control_uuid="synthetic",
        source_id="synthetic",
    )
    assert result.metrics["mean"] == pytest.approx(
        temperatures["expected"]["sample_mean"], abs=1e-9
    )
    assert "sample_mean_is_not_time_weighted" in result.limitations
    counter = datasets["energy_counter"]
    assert source(counter["points"], meaning="cumulative_counter").summary.metrics[
        "energy"
    ] == pytest.approx(counter["expected"]["delta_kwh"], abs=1e-9)
    ranked = datasets["ranked_intervals"]
    sources = [
        source([(a, v) for a, _b, v in records], role="consumer", boundary=name)
        for name, records in ranked["series"].items()
    ]
    ranking = comparison("consumer_ranking", sources, end=3600)
    assert [item["binding_id"] for item in ranking.items] == ranked["expected"]["rank"]
    assert [item["energy"] / 1000 for item in ranking.items] == pytest.approx(
        ranked["expected"]["energy_kwh"]
    )

    # Fixtures explicitly evidence held power intervals; only the test converts whole hours.
    mixed = datasets["mixed_overlap"]
    production = source(
        [(a, watts) for a, _b, watts in mixed["power_intervals"]], unit="Wh", role="production"
    )
    load = source([(0, 1000), (3600, 1000)], unit="Wh", role="consumer")
    segments = reconstruct_segments(((0, 7200, True, ((5400, False),)),), start=0, end=7200)
    state = ComparisonInput(
        duration_summary(segments, start=0, end=7200, control_uuid="synthetic", source_id="state"),
        segments=segments,
    )
    overlap = comparison("pv_load_overlap", [production, load, state], end=7200)
    assert (
        overlap.metrics["positive_production_and_load_seconds"]
        == mixed["expected"]["overlap_seconds"]
    )
    assert overlap.metrics["exact_solar_attribution_fraction"] is None
    night = datasets["night_intervals"]
    hours = [(hour, watts) for a, b, watts in night["intervals"] for hour in range(a, b, 3600)]
    baseline = comparison("baseload", [source(hours, unit="Wh")])
    assert baseline.metrics["nighttime_median_power"] == pytest.approx(
        night["expected"]["weighted_median_w"]
    )
    assert baseline.metrics["estimated_24_hour_energy_Wh"] / 1000 == pytest.approx(
        night["expected"]["extrapolated_24h_kwh"]
    )


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
