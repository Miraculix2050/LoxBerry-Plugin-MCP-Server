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
    tools = {tool["name"]: tool for tool in tool_schema_catalog("synthetic")["tools"]}
    names = set(tools)
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
            assert all(tools[name]["annotations"]["readOnlyHint"] for name in result["workflow"])
            assert result["scope_" + language] in matrix and f"| {case['id']} |" in matrix
            assert result["ai_three_independent_runs"] == "incomplete"
            assert case["reference"] and case["completeness"] and case["prohibited_claims"]


def test_original_numeric_references_against_delivered_core() -> None:
    datasets = acceptance.read_json(ROOT / "tests/fixtures/analysis/reference.json")["datasets"]
    tolerances = {
        case["reference"]["fixture"]: case["reference"]["absolute_tolerance"]
        for case in CATALOG["cases"]
        if case["reference"]["fixture"] != "scenario_contract"
    }

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
        temperatures["expected"]["sample_mean"], rel=0, abs=tolerances["temperature_samples"]
    )
    assert "sample_mean_is_not_time_weighted" in result.limitations
    counter = datasets["energy_counter"]
    assert source(counter["points"], meaning="cumulative_counter").summary.metrics[
        "energy"
    ] == pytest.approx(counter["expected"]["delta_kwh"], rel=0, abs=tolerances["energy_counter"])
    ranked = datasets["ranked_intervals"]
    assert all(b - a == 3600 for records in ranked["series"].values() for a, b, _v in records)
    sources = [
        source([(a, v) for a, _b, v in records], role="consumer", boundary=name)
        for name, records in ranked["series"].items()
    ]
    ranking = comparison("consumer_ranking", sources, end=3600)
    assert [item["binding_id"] for item in ranking.items] == ranked["expected"]["rank"]
    assert [item["energy"] / 1000 for item in ranking.items] == pytest.approx(
        ranked["expected"]["energy_kwh"], rel=0, abs=tolerances["ranked_intervals"]
    )

    # Fixtures explicitly evidence held power intervals; only the test converts whole hours.
    mixed = datasets["mixed_overlap"]
    assert all(b - a == 3600 for a, b, _watts in mixed["power_intervals"])
    production = source(
        [(a, watts) for a, _b, watts in mixed["power_intervals"]], unit="Wh", role="production"
    )
    load = source([(0, 1000), (3600, 1000)], unit="Wh", role="consumer")
    initial = mixed["event_baseline"]
    begin, finish = mixed["capture"][0][0], mixed["capture"][-1][1]
    phases = tuple(
        (
            a,
            b,
            initial["value"] if initial["at"] == a else None,
            tuple((at, new) for at, _old, new in mixed["transitions"] if a <= at < b),
        )
        for a, b in mixed["capture"]
    )
    segments = reconstruct_segments(phases, start=begin, end=finish)
    state = ComparisonInput(
        duration_summary(
            segments, start=begin, end=finish, control_uuid="synthetic", source_id="state"
        ),
        segments=segments,
    )
    overlap = comparison("pv_load_overlap", [production, load, state], end=finish)
    assert (
        overlap.metrics["positive_production_and_load_seconds"]
        == mixed["expected"]["overlap_seconds"]
    )
    assert overlap.metrics["exact_solar_attribution_fraction"] is None
    night = datasets["night_intervals"]
    assert all(a % 3600 == b % 3600 == 0 and b > a for a, b, _watts in night["intervals"])
    hours = [(hour, watts) for a, b, watts in night["intervals"] for hour in range(a, b, 3600)]
    baseline = comparison("baseload", [source(hours, unit="Wh")])
    assert baseline.metrics["nighttime_median_power"] == pytest.approx(
        night["expected"]["weighted_median_w"], rel=0, abs=tolerances["night_intervals"]
    )
    assert baseline.metrics["estimated_24_hour_energy_Wh"] / 1000 == pytest.approx(
        night["expected"]["extrapolated_24h_kwh"], rel=0, abs=tolerances["night_intervals"]
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


def test_capture_accepts_delivered_read_workflows_and_rejects_writes() -> None:
    data = capture()
    for run in data["runs"]:
        case = next(case for case in CATALOG["cases"] if case["id"] == run["case_id"])
        run["calls"] = case.get("final_acceptance", {}).get("workflow", case["baseline_workflow"])
    assert acceptance.validate_capture(data, CATALOG)
    data["runs"][0]["calls"] = ["loxberry_save_installation_profile"]
    with pytest.raises(ValueError, match="read_workflow"):
        acceptance.validate_capture(data, CATALOG)


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


def capture_v2() -> dict:
    identity = capture()["identity"]
    identity.update(
        {
            "runtime": "synthetic",
            "workload_sha256": "1" * 64,
            "serialization": "canonical_json_utf8_v1",
            "measurement_boundary": "synthetic",
            "cold_conditions": "new_runtime_fresh_authorization",
            "warm_conditions": "primed_runtime_fresh_authorization",
        }
    )
    identity["tokenizer"] = identity["tokenizer_version"] = "unavailable"
    cases = [c["id"] for c in CATALOG["cases"] if c["group"] != "knx"]
    return {
        "version": 2,
        "identity": identity,
        "plan": {"case_ids": cases, "runs_per_case": 1, "record_limit": 50},
        "catalog_reads": [
            {
                "response_bytes": 1000,
                "description_bytes": 100,
                "schema_bytes": 500,
                "duration_ms": 5,
                "status": "ok",
                "page": False,
                "retry": False,
                "fallback_reason": None,
                "task": None,
            }
        ],
        "runs": [
            {
                "case_id": c,
                "run": 1,
                "phase": p,
                "outcome": "pass",
                "optional_metrics": {m: None for m in acceptance.V2_OPTIONAL_METRICS},
                "calls": [
                    {
                        "tool": name,
                        "status": "ok",
                        "duration_ms": 10,
                        "response_bytes": size,
                        "page": False,
                        "retry": False,
                        "fallback_reason": None,
                        "guide_section": section,
                        "guide_module_bytes": module,
                    }
                    for name, size, section, module in [
                        ("loxone_get_skill_guide", 100, "core", 60),
                        ("loxone_get_structure_overview", 200, None, None),
                    ]
                ],
            }
            for c in cases
            for p in ("cold", "warm")
        ],
    }


def test_v2_optional_tokens_identity_and_phase_metrics_do_not_block() -> None:
    report = acceptance.summarize(capture_v2(), CATALOG)
    assert report["status"] == "pass"
    assert report["runs"] == report["record_limit"] == 50
    assert not report["unavailable_mandatory_metrics"]
    assert "tool_result_tokens" in report["optional_unavailable_metrics"]
    assert report["unavailable_identity_fields"] == ["tokenizer", "tokenizer_version"]
    row = report["results"][0]
    assert row["response_bytes"] == row["guide_response_bytes"] + row["other_response_bytes"] == 300
    assert row["guide_module_bytes"] == 60
    assert row["mcp_sum_ms"] == 20
    assert report["distributions"][0]["samples"] == 1
    assert report["distributions"][0]["p95_kind"] == "descriptive_only_no_stability_claim"
    assert report["acceptance"] == "requires_independent_review"
    assert "synthetic" not in json.dumps(report)


@pytest.mark.parametrize("metric", ["duration_ms", "response_bytes", "guide_module_bytes"])
def test_v2_missing_mandatory_call_metrics_are_incomplete_not_zero(metric) -> None:
    data = capture_v2()
    data["runs"][0]["calls"][0][metric] = None
    report = acceptance.summarize(data, CATALOG)
    assert report["status"] == "incomplete"
    assert report["unavailable_mandatory_metrics"]
    assert any(v is None for v in report["results"][0].values())


def test_v2_counts_all_pages_retries_fallbacks_failures_and_repeated_guides() -> None:
    data = capture_v2()
    calls = data["runs"][0]["calls"]
    retry = copy.deepcopy(calls[1])
    retry.update(
        status="timeout",
        response_bytes=0,
        duration_ms=50,
        retry=True,
        page=True,
        fallback_reason="source_unavailable",
    )
    calls.extend([retry, copy.deepcopy(calls[0])])
    row = acceptance.summarize(data, CATALOG)["results"][0]
    assert row["call_count"] == 4
    assert row["guide_fetch_count"] == 2
    assert row["response_bytes"] == 400
    assert row["guide_module_bytes"] == 120
    assert row["page_count"] == row["retry_count"] == row["fallback_count"] == 1
    assert row["failure_rate"] == row["timeout_rate"] == 0.25
    assert row["mcp_sum_ms"] == 80


def test_v2_enforces_50_record_plan_and_reports_original_question_gaps() -> None:
    data = capture_v2()
    data["plan"]["runs_per_case"] = 3
    with pytest.raises(ValueError, match="plan_invalid"):
        acceptance.validate_capture(data, CATALOG)
    data = capture_v2()
    data["runs"].append(copy.deepcopy(data["runs"][0]))
    with pytest.raises(ValueError, match="run_limit"):
        acceptance.validate_capture(data, CATALOG)
    data = capture_v2()
    dropped = data["plan"]["case_ids"].pop()
    data["runs"] = [r for r in data["runs"] if r["case_id"] != dropped]
    report = acceptance.summarize(data, CATALOG)
    assert report["status"] == "incomplete"
    assert report["missing_original_cases"] == [dropped]
    data = capture_v2()
    data["runs"].pop()
    assert acceptance.summarize(data, CATALOG)["missing_runs"]


def test_v2_catalog_sizes_and_conditions_are_mandatory() -> None:
    data = capture_v2()
    data["catalog_reads"][0]["schema_bytes"] = None
    assert acceptance.summarize(data, CATALOG)["status"] == "incomplete"
    data = capture_v2()
    data["identity"]["cold_conditions"] = "unavailable"
    assert (
        "identity.cold_conditions"
        in acceptance.summarize(data, CATALOG)["unavailable_mandatory_metrics"]
    )


@pytest.mark.parametrize("field", ["client", "client_version", "model", "guide_revision"])
@pytest.mark.parametrize("label", ["unavailable", "unknown", "unverified"])
def test_v2_missing_execution_identity_does_not_certify_a_matched_run(field, label) -> None:
    data = capture_v2()
    data["identity"][field] = label
    report = acceptance.summarize(data, CATALOG)
    assert report["status"] == "incomplete"
    assert "identity." + field in report["unavailable_mandatory_metrics"]
    assert field in report["unavailable_identity_fields"]
    assert acceptance.compare(data, copy.deepcopy(data), CATALOG)["status"] == "incomplete"


def test_v2_comparison_reports_bytes_counts_and_quality_without_threshold() -> None:
    before = capture_v2()
    after = copy.deepcopy(before)
    after["identity"]["tokenizer_version"] = "other_optional_version"
    after["catalog_reads"][0]["response_bytes"] = 1200
    after["runs"][0]["calls"][1]["response_bytes"] = 100
    report = acceptance.compare(before, after, CATALOG)
    assert report["status"] == "measured"
    assert report["pairs"][0]["response_bytes"]["change_percent"] == pytest.approx(-100 / 3)
    assert report["catalog_comparison"]["response_bytes"]["change_percent"] == pytest.approx(20)
    assert report["acceptance"] == "requires_independent_quality_equivalence_and_performance_review"
    after["runs"][0]["outcome"] = "incomplete"
    assert acceptance.compare(before, after, CATALOG)["status"] == "incomplete"
    after["runs"][0]["outcome"] = "fail"
    after["runs"][0]["calls"][0]["response_bytes"] = None
    assert acceptance.compare(before, after, CATALOG)["status"] == "fail"


@pytest.mark.parametrize("field", ["model", "runtime", "workload_sha256", "cold_conditions"])
def test_v2_rejects_unmatched_workload_and_environment(field) -> None:
    before, after = capture_v2(), capture_v2()
    after["identity"][field] = "2" * 64 if field.endswith("sha256") else "other"
    with pytest.raises(ValueError, match="environment_mismatch"):
        acceptance.compare(before, after, CATALOG)


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), "10", 10**400])
def test_v2_rejects_invalid_counters(value) -> None:
    data = capture_v2()
    data["runs"][0]["calls"][0]["response_bytes"] = value
    with pytest.raises(ValueError, match="metric"):
        acceptance.validate_capture(data, CATALOG)


def test_v2_rejects_private_payloads_writes_and_mixed_versions() -> None:
    data = capture_v2()
    data["runs"][0]["calls"][0]["arguments"] = {"secret": "not-public"}
    with pytest.raises(ValueError, match="call_invalid"):
        acceptance.validate_capture(data, CATALOG)
    data = capture_v2()
    data["runs"][0]["calls"][0]["tool"] = "loxone_operate_control"
    with pytest.raises(ValueError, match="read_workflow"):
        acceptance.validate_capture(data, CATALOG)
    with pytest.raises(ValueError, match="version_mismatch"):
        acceptance.compare(capture(), capture_v2(), CATALOG)


def test_v2_catalog_calls_keep_task_timing_retries_pages_and_failures_separate() -> None:
    data = capture_v2()
    row = data["runs"][0]
    data["catalog_reads"][0]["task"] = {k: row[k] for k in ("case_id", "run", "phase")}
    retry = copy.deepcopy(data["catalog_reads"][0])
    retry.update(
        duration_ms=15,
        status="timeout",
        page=True,
        retry=True,
        fallback_reason="tool_error",
        response_bytes=0,
        description_bytes=0,
        schema_bytes=0,
    )
    data["catalog_reads"].append(retry)
    report = acceptance.summarize(data, CATALOG)
    totals = report["results"][0]
    assert totals["mcp_sum_ms"] == 40
    assert totals["result_mcp_sum_ms"] == 20
    assert totals["catalog_call_count"] == 2
    assert totals["call_count"] == 4
    assert totals["page_count"] == totals["retry_count"] == totals["fallback_count"] == 1
    assert totals["timeout_rate"] == 0.25
    assert totals["catalog_response_bytes"] == 1000
    assert totals["response_bytes"] == 300  # Result traffic excludes the catalog.
    assert totals["total_response_bytes"] == 1300
    assert report["catalog_call_totals"]["mcp_sum_ms"] == 20
    assert report["setup_catalog_call_totals"]["call_count"] == 0
    assert report["results"][1]["mcp_sum_ms"] == 20


def test_v2_setup_catalog_calls_and_missing_catalog_timings_are_visible() -> None:
    data = capture_v2()
    report = acceptance.summarize(data, CATALOG)
    assert report["setup_catalog_call_totals"]["mcp_sum_ms"] == 5
    data["catalog_reads"][0]["duration_ms"] = None
    assert acceptance.summarize(data, CATALOG)["status"] == "incomplete"
    data = capture_v2()
    data["catalog_reads"][0]["task"] = {"case_id": "unknown", "run": 1, "phase": "cold"}
    with pytest.raises(ValueError, match="catalog_task_invalid"):
        acceptance.validate_capture(data, CATALOG)


def test_v2_published_guide_resources_share_byte_and_call_accounting():
    data = capture_v2()
    row = data["runs"][0]
    row["calls"][0]["tool"] = "resources.read"
    report = acceptance.summarize(data, CATALOG)
    assert report["status"] == "pass"
    assert report["results"][0]["guide_fetch_count"] == 1
    assert report["results"][0]["guide_module_bytes"] == 60
    assert report["results"][0]["guide_response_bytes"] == 100
    row["calls"][0]["guide_section"] = None
    assert acceptance.summarize(data, CATALOG)["status"] == "incomplete"
    row["calls"][0]["guide_section"] = "../../unpublished"
    with pytest.raises(ValueError, match="labels"):
        acceptance.validate_capture(data, CATALOG)


def test_current_lighting_matrix_uses_bounded_released_analyzer_beside_historical_baseline() -> (
    None
):
    tools = {tool["name"]: tool for tool in tool_schema_catalog("synthetic")["tools"]}
    analyzer = tools["loxone_analyze_project"]
    assert analyzer["annotations"]["readOnlyHint"]
    assert "lighting" in analyzer["inputSchema"]["properties"]["scope"]["enum"]
    checks = {
        "lighting-01": ("inventory", "scene_roles"),
        "lighting-02": ("naming_consistency",),
        "lighting-03": ("presence_relationships",),
        "lighting-04": ("planning_context",),
        "lighting-05": ("scene_roles", "naming_consistency"),
        "lighting-06": ("inventory", "planning_context"),
    }
    for language in ("de", "en"):
        matrix = (ROOT / f"docs/user/analysis-support.{language}.md").read_text(encoding="utf-8")
        for case_id, expected in checks.items():
            current = next(
                line for line in matrix.splitlines() if line.startswith(f"| {case_id} |")
            )
            assert 'loxone_analyze_project(scope="lighting"' in current
            assert all(check in current for check in expected)
        assert "#485" in matrix
