import time
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from mcpserver.history_analysis import HistoryAnalysisDeadline, StateSegment, statistic_summary
from mcpserver.history_comparison import ComparisonInput, compare_history
from mcpserver.loxone.state_semantics import SeriesSemantics
from mcpserver.loxone.statistics import StatisticPoint


def energy(
    values, *, role=None, boundary=None, start=0, end=10_800, meaning="interval_difference_sum"
):
    semantics = SeriesSemantics(
        "partial",
        meaning,
        unit="Wh",
        measurement_quantity="energy",
        timestamp_basis="unix_utc",
        timestamp_position="interval_start"
        if meaning == "interval_difference_sum"
        else "observation",
    )
    points = tuple(StatisticPoint(t, v) for t, v in values)
    summary = statistic_summary(
        "energy", semantics, points, start=start, end=end, control_uuid="c", source_id="s"
    )
    summary.binding_id = role
    return ComparisonInput(
        summary, semantics, points, profile_role=role, declared_boundary=boundary
    )


def compare(operation, inputs, *, start=0, end=10_800, confirmed=False, night_start=0, night_end=5):
    return compare_history(
        operation,
        tuple(inputs),
        start=start,
        end=end,
        timezone_name="Europe/Berlin",
        comparable_boundaries_confirmed=confirmed,
        night_start_hour=night_start,
        night_end_hour=night_end,
        deadline=time.monotonic() + 10,
    )


@pytest.mark.parametrize(
    "role", [None, "production", "consumer", "house_consumption", "grid_export", "self_consumption"]
)
def test_native_self_consumption_role_is_enforced_at_shared_input(role):
    source = energy([(0, 100)], role=role)
    semantics = replace(source.semantics, measurement_role="native_self_consumption_channel")
    if role == "self_consumption":
        assert replace(source, semantics=semantics).profile_role == role
    else:
        with pytest.raises(ValueError, match="requires the self_consumption role"):
            replace(source, semantics=semantics)


def history_context(*, observed=False, loads=1):
    from mcpserver.analysis_context import HistoryAnalysisContext

    cycle = {
        "timezone": "UTC",
        "windows": [{"weekdays": list(range(7)), "start": "00:00", "end": "23:59"}],
        "latest_completion": "23:59",
        "duration_seconds": 3600,
        "interruptible": False,
        "minimum_run_seconds": 0,
        "minimum_off_seconds": 0,
        "cycle_energy_wh": 1000.0,
        "origin": "scenario_assumption",
        "rationale": "Explicit hypothetical model",
    }
    declarations = [
        {
            "association_id": "export",
            "source_index": 0,
            "role": "grid_export",
            "measurement_boundary": "main",
            "declared_direction": "export",
            "origin": "user_confirmed",
        }
    ]
    models = [{"load_id": f"hyp{n}", "kind": "hypothetical", "cycle": cycle} for n in range(loads)]
    if observed:
        declarations += [
            {
                "association_id": "consumer",
                "source_index": 1,
                "role": "consumer",
                "measurement_boundary": "main",
                "origin": "user_confirmed",
            },
            {
                "association_id": "active",
                "source_index": 2,
                "role": "operating_state",
                "origin": "user_confirmed",
            },
        ]
        models.append(
            {
                "load_id": "measured",
                "kind": "observed",
                "consumer_id": "consumer",
                "operating_id": "active",
            }
        )
    return HistoryAnalysisContext.model_validate(
        {
            "scope": {
                "kind": "scenario",
                "description": "One historical supply",
                "common_supply_origin": "user_confirmed",
            },
            "associations": declarations,
            "loads": models,
        }
    )


def contextual_compare(ctx, *, observed=False, hours=None):
    from test_retrospective_shift import END, START, load

    from mcpserver.history_analysis import SourceAnalysis

    hours = hours if hours is not None else [(START + 36000, 600.0), (START + 39600, 800.0)]
    export = energy(hours, role="grid_export", boundary="main", start=START, end=END)
    export.summary.binding_id = None
    inputs = [replace(export, association_id="export", declared_direction="export")]
    if observed:
        original = load("measured")
        consumer = energy(
            [(START + 3600, 1000.0), (START + 7200, 500.0)],
            role="consumer",
            boundary="main",
            start=START,
            end=END,
        )
        consumer.summary.binding_id = None
        inputs += [
            replace(consumer, association_id="consumer", load_flexibility=original.flexibility),
            ComparisonInput(
                SourceAnalysis(
                    control_uuid="state-control",
                    source_id="state",
                    source_kind="event_history",
                    status="partial",
                    method="binary_state_duration",
                ),
                segments=original.segments,
                profile_role="operating_state",
                association_id="active",
            ),
        ]
    result = compare_history(
        "retrospective_shift",
        tuple(inputs),
        start=START,
        end=END,
        timezone_name="UTC",
        comparable_boundaries_confirmed=True,
        night_start_hour=0,
        night_end_hour=5,
        deadline=time.monotonic() + 10,
        analysis_context=ctx,
    )
    assert all(source.summary.binding_id is None for source in inputs)
    return result


def test_hypothetical_cycles_share_one_budget_without_an_observed_baseline():
    ctx = history_context(loads=2)
    first = contextual_compare(ctx)
    second = contextual_compare(ctx.model_copy(update={"loads": list(reversed(ctx.loads))}))
    assert first == second
    assert first.status == "partial"
    evidence = first.context_analysis
    assert evidence.conditional_export_absorption_upper_bound_wh == 1400
    assert len(evidence.allocations) == 2
    assert all(a.observed_start is None and a.observed_end is None for a in evidence.allocations)
    assert first.retrospective_shift is None and first.load_cycles is None
    assert all(a.energy_origin == "user_declared_uniform" for a in evidence.allocations)


def test_observed_and_declared_models_compete_without_rewriting_measured_energy():
    result = contextual_compare(history_context(observed=True), observed=True)
    evidence = result.context_analysis
    assert result.status == "partial" and len(evidence.allocations) == 2
    assert evidence.conditional_export_absorption_upper_bound_wh == 1400
    assert evidence.cycles[0].episodes[0].observed_energy_wh == 1500
    actual = next(a for a in evidence.allocations if a.kind == "observed")
    hypothetical = next(a for a in evidence.allocations if a.kind == "hypothetical")
    assert actual.observed_start is not None and hypothetical.observed_start is None


def test_declared_subhour_demand_never_backfills_a_missing_supply_hour():
    from test_retrospective_shift import START

    ctx = history_context()
    ctx.loads[0].cycle.duration_seconds = 5400
    assert not contextual_compare(ctx, hours=[(START + 36000, 600.0)]).context_analysis.allocations
    result = contextual_compare(ctx)
    assert result.context_analysis.allocations[0].observed_start is None
    assert result.context_analysis.conditional_export_absorption_upper_bound_wh <= 1000


def test_declared_search_exhaustion_does_not_publish_partial_allocations():
    from test_retrospective_shift import START

    end = START + 31 * 86400
    source = energy(
        [(START + i * 3600, 1000.0) for i in range(744)],
        role="grid_export",
        boundary="main",
        start=START,
        end=end,
    )
    source.summary.binding_id = None
    source = replace(source, association_id="export", declared_direction="export")
    result = compare_history(
        "retrospective_shift",
        (source,),
        start=START,
        end=end,
        timezone_name="UTC",
        comparable_boundaries_confirmed=True,
        night_start_hour=0,
        night_end_hour=5,
        deadline=time.monotonic() + 10,
        analysis_context=history_context(loads=16),
    )
    assert result.context_analysis.evaluated_alternatives == 4096
    assert not result.context_analysis.allocations
    assert result.context_analysis.conditional_export_absorption_upper_bound_wh == 0
    assert "alternative_search_budget_exceeded_no_partial_allocation" in result.limitations


@pytest.mark.parametrize("feedback", [False, True])
def test_declared_real_model_does_not_promote_available_activity_to_a_baseline(feedback):
    from mcpserver.analysis_context import HistoryAnalysisContext

    doc = history_context(observed=True, loads=0).model_dump()
    cycle = history_context().loads[0].cycle.model_dump()
    cycle["origin"] = "user_confirmed"
    doc["loads"] = [
        {
            "load_id": "real-model",
            "kind": "declared_real",
            "consumer_id": "consumer",
            "cycle": cycle,
        }
    ]
    if feedback:
        doc["loads"][0]["operating_id"] = "active"
    result = contextual_compare(HistoryAnalysisContext.model_validate(doc), observed=True)
    evidence = result.context_analysis
    assert evidence.allocations and not evidence.cycles
    assert evidence.allocations[0].kind == "declared_real"
    assert evidence.allocations[0].observed_start is None
    assert evidence.allocations[0].energy_origin == "user_declared_uniform"
    assert (
        any("declared_cycles_without_feedback" in reason for reason in evidence.limitations)
        is not feedback
    )


def test_context_export_assumption_cannot_establish_measured_budget():
    ctx = history_context(loads=2)
    ctx.associations[0].origin = "scenario_assumption"
    result = contextual_compare(ctx)
    assert not result.context_analysis.allocations
    assert result.limitations == ["one_confirmed_export_boundary_and_explicit_load_models_required"]


def test_observed_only_analysis_does_not_claim_declared_feedback_missing():
    result = contextual_compare(history_context(observed=True, loads=0), observed=True)
    assert result.context_analysis.allocations
    assert not any(
        "declared_cycles_without_feedback" in reason
        for reason in result.context_analysis.limitations
    )


def test_pv_overlap_is_upper_bound_and_not_attribution():
    production = energy([(0, 1000), (3600, 0), (7200, 500)], role="production")
    load = energy([(0, 500), (3600, 200), (7200, 200)], role="house_consumption")
    result = compare("pv_load_overlap", [production, load])
    assert result.status == "partial"
    assert result.metrics["coincident_energy_upper_bound"] == 700
    assert result.metrics["positive_production_and_load_seconds"] == 7200
    assert result.metrics["exact_solar_attribution_fraction"] is None
    assert "upper_bound_is_not_measured_self_consumption" in result.limitations


def test_zero_generation_denominator_is_undefined():
    result = compare(
        "pv_load_overlap", [energy([(0, 0)], role="production"), energy([(0, 10)], role="consumer")]
    )
    assert result.metrics["production_denominator"] == 0
    assert result.metrics["exact_solar_attribution_fraction"] is None
    assert "no_generation_denominator_attribution_undefined" in result.limitations


def test_unmatched_and_partial_hours_are_never_divided():
    pv = energy([(0, 100), (3600, 200), (7200, 300)], role="production")
    load = energy([(0, 50), (7200, 70)], role="consumer")
    result = compare("pv_load_overlap", [pv, load], start=100, end=10_800)
    assert result.metrics["production_energy"] == 300
    assert result.metrics["load_energy"] == 70
    assert result.metrics["aligned_seconds"] == 3600


def test_counter_totals_cannot_be_allocated_to_pv_overlap():
    pv = energy([(0, 10), (500, 20)], role="production", meaning="cumulative_counter")
    load = energy([(0, 10)], role="consumer")
    assert compare("pv_load_overlap", [pv, load]).status == "insufficient_evidence"


def test_ranking_requires_confirmation_boundaries_and_identical_windows():
    first = energy(
        [(0, 10), (500, 12)], role="consumer", boundary="pump", meaning="cumulative_counter"
    )
    second = energy(
        [(0, 10), (500, 15)], role="consumer", boundary="heater", meaning="cumulative_counter"
    )
    second.summary.binding_id = "heater"
    first.summary.binding_id = "pump"
    assert compare("consumer_ranking", [first, second]).status == "insufficient_evidence"
    result = compare("consumer_ranking", [first, second], confirmed=True)
    assert result.status == "partial"
    assert result.items == [
        {"binding_id": "heater", "energy": 5},
        {"binding_id": "pump", "energy": 2},
    ]
    assert "total" not in result.metrics
    assert (
        compare(
            "consumer_ranking", [first, replace(second, declared_boundary="pump")], confirmed=True
        ).status
        == "insufficient_evidence"
    )
    second.summary.usable_intervals = []
    assert (
        compare("consumer_ranking", [first, second], confirmed=True).status
        == "insufficient_evidence"
    )


def state(segments):
    from mcpserver.history_analysis import duration_summary

    segments = tuple(segments)
    summary = duration_summary(
        segments, start=0, end=10_800, control_uuid="state", source_id="active"
    )
    return ComparisonInput(summary, segments=segments)


def test_ranking_uses_complete_interval_evidence_beyond_metadata_cap():
    values = [(i * 3600, 10) for i in range(150)]
    first = energy(values, role="consumer", boundary="first", end=151 * 3600)
    second = energy(values, role="consumer", boundary="second", end=151 * 3600)
    first.summary.binding_id, second.summary.binding_id = "first", "second"
    assert first.summary.usable_intervals_truncated
    result = compare("consumer_ranking", [first, second], confirmed=True, end=151 * 3600)
    assert result.status == "partial" and result.usable_intervals_truncated
    assert len(result.usable_intervals) == 128
    assert result.items[0]["energy"] == 1500
    changed = replace(second, points=second.points[:-1])
    assert (
        compare("consumer_ranking", [first, changed], confirmed=True, end=151 * 3600).status
        == "insufficient_evidence"
    )


def test_mixed_pv_load_enable_signal_uses_only_whole_active_hours():
    pv = energy([(0, 100), (3600, 200), (7200, 300)], role="production")
    load = energy([(0, 50), (3600, 50), (7200, 50)], role="consumer")
    enabled = state([StateSegment(100, 7200, True)])
    result = compare("pv_load_overlap", [pv, load, enabled])
    assert result.metrics["production_energy"] == 200
    assert result.metrics["load_energy"] == 50
    assert result.metrics["aligned_seconds"] == 3600
    assert compare("pv_load_overlap", [pv, load, state([])]).status == "insufficient_evidence"


def test_operating_energy_never_uses_unknown_or_partial_state_windows():
    values = energy([(0, 10), (3600, 20), (7200, 30)])
    enabled = state([StateSegment(100, 7200, True), StateSegment(7200, 10_800, False)])
    result = compare("operating_phases", [values, enabled])
    assert result.metrics["energy_in_complete_active_intervals_Wh"] == 20
    assert result.metrics["active_seconds"] == 7100
    assert "state_duration_is_not_measured_energy" in result.limitations


def test_operating_temperature_is_sample_mean_with_exclusive_state_endpoint():
    semantics = SeriesSemantics(
        "partial",
        "sample",
        unit="°C",
        measurement_quantity="temperature",
        timestamp_basis="unix_utc",
    )
    points = tuple(StatisticPoint(t, v) for t, v in [(2, 10), (4, 100), (7, 30)])
    summary = statistic_summary(
        "temperature_summary", semantics, points, start=0, end=10, control_uuid="c", source_id="s"
    )
    values = ComparisonInput(summary, semantics, points)
    enabled = state([StateSegment(0, 4, True), StateSegment(6, 10, True)])
    result = compare("operating_phases", [values, enabled], end=10)
    assert result.metrics["temperature_active_sample_mean"] == 20
    assert result.metrics["temperature_sample_count"] == 2
    assert result.metric_units["temperature_active_sample_mean"] == "°C"


@pytest.mark.parametrize(
    "start,end,hours",
    [
        ("2026-03-28T23:00:00", "2026-03-29T03:00:00", 4),
        ("2026-10-24T22:00:00", "2026-10-25T04:00:00", 6),
    ],
)
def test_baseload_weights_real_dst_hours_and_labels_daily_estimate(start, end, hours):
    begin = datetime.fromisoformat(start).replace(tzinfo=UTC).timestamp()
    finish = datetime.fromisoformat(end).replace(tzinfo=UTC).timestamp()
    values = energy([(begin + i * 3600, 100) for i in range(hours)], start=begin, end=finish)
    result = compare("baseload", [values], start=begin, end=finish)
    assert result.metrics["nighttime_median_power"] == 100
    assert result.metrics["usable_night_seconds"] == hours * 3600
    assert result.metrics["estimated_24_hour_energy_Wh"] == 2400
    assert result.status == "partial"
    assert "24_hour_extrapolation_is_an_estimate" in result.limitations


def test_ambiguous_custom_night_boundary_rejected():
    begin = datetime(2026, 10, 24, 22, tzinfo=UTC).timestamp()
    with pytest.raises(ValueError, match="ambiguous"):
        compare(
            "baseload",
            [energy([(begin, 100)], start=begin, end=begin + 6 * 3600)],
            start=begin,
            end=begin + 6 * 3600,
            night_start=2,
            night_end=3,
        )


def test_exclusive_end_midnight_does_not_validate_following_dst_day():
    begin = datetime(2026, 10, 23, 22, tzinfo=UTC).timestamp()
    finish = begin + 24 * 3600
    values = energy([(begin + 2 * 3600, 100)], start=begin, end=finish)
    result = compare("baseload", [values], start=begin, end=finish, night_start=2, night_end=3)
    assert result.metrics["nighttime_median_power"] == 100
    assert result.metrics["usable_night_seconds"] == 3600


def test_operating_temperature_preserves_duplicate_sample_rejection():
    semantics = SeriesSemantics(
        "partial",
        "sample",
        unit="C",
        measurement_quantity="temperature",
        timestamp_basis="unix_utc",
    )
    points = (StatisticPoint(2, 10), StatisticPoint(2, 100))
    summary = statistic_summary(
        "temperature_summary",
        semantics,
        points,
        start=0,
        end=10,
        control_uuid="c",
        source_id="s",
    )
    assert summary.status == "insufficient_evidence"
    result = compare(
        "operating_phases",
        [ComparisonInput(summary, semantics, points), state([StateSegment(0, 10, True)])],
        end=10,
    )
    assert result.status == "insufficient_evidence"
    assert "temperature_active_sample_mean" not in result.metrics


def test_deadline_and_unverified_power_samples_are_not_estimates():
    source = energy([(0, 100)])
    source = replace(
        source,
        semantics=replace(source.semantics, measurement_quantity="power", value_meaning="sample"),
    )
    assert compare("baseload", [source]).status == "insufficient_evidence"
    with pytest.raises(HistoryAnalysisDeadline):
        compare_history(
            "baseload",
            (source,),
            start=0,
            end=10_800,
            timezone_name="Europe/Berlin",
            comparable_boundaries_confirmed=False,
            night_start_hour=0,
            night_end_hour=5,
            deadline=0,
        )
