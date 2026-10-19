import asyncio
import hashlib
import json
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError
from test_history_analysis_tools import configured
from test_solar_recording import C, S, control, source

from mcpserver.comparable_days_models import NumericalComparableDayOptions
from mcpserver.config import PluginConfig
from mcpserver.history_analysis_tools import AnalysisSource, register_history_analysis_tool
from mcpserver.installation_profile import BindingInput, ProfileStore, installation_identity
from mcpserver.loxone.event_history import EventHistoryStore
from mcpserver.loxone.models import StatisticSeries
from mcpserver.loxone.runtime import RuntimeAuthorizationError
from mcpserver.loxone.state_semantics import StateSemanticsResolver
from mcpserver.loxone.statistics import StatisticPoint
from mcpserver.numerical_day_tools import SolarAnalysisSource, _calculate, _forecast_context
from mcpserver.solar_recording import SolarHistory

T = "12345678-1234-1234-1234567890123458"
P = "12345678-1234-1234-1234567890123459"


def day_context_document():
    return {
        "scope": {
            "kind": "scenario",
            "description": "One selected supply",
            "common_supply_origin": "user_confirmed",
        },
        "associations": [
            {
                "association_id": "radiation",
                "source_index": 0,
                "role": "weather_context",
                "origin": "user_confirmed",
            },
            {
                "association_id": "temperature",
                "source_index": 1,
                "role": "weather_context",
                "origin": "user_confirmed",
            },
            {
                "association_id": "pv",
                "source_index": 2,
                "role": "production",
                "origin": "user_confirmed",
            },
        ],
        "day_context": {
            "site": {"site_id": "site", "timezone": "UTC", "association_origin": "user_confirmed"},
            "weather": [
                {"quantity": "radiation", "source_index": 0},
                {"quantity": "temperature", "source_index": 1},
            ],
            "assets": ["roof"],
            "production": [
                {"source_index": 2, "asset_ids": ["roof"], "coverage_origin": "user_confirmed"}
            ],
            "radiation_independence_origin": "user_confirmed",
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["complete", "gap", "unqualified"])
async def test_context_disjoint_production_uses_complete_common_hours(monkeypatch, tmp_path, mode):
    from unittest.mock import AsyncMock

    from mcpserver.analysis_context import HistoryAnalysisContext

    runtime, tool, args, _ = setup(monkeypatch, tmp_path)
    meter, series, points = runtime.authorized_statistics.return_value
    other = replace(meter, uuid="12345678-1234-1234-1234567890123460")
    runtime.structure = replace(runtime.structure, controls=(*runtime.structure.controls, other))
    runtime._history_visible_structure = AsyncMock(return_value=runtime.structure)

    async def read(*positional, **kwargs):
        chosen = other if positional[1].uuid == other.uuid else meter
        return chosen, series, (() if mode == "gap" and chosen is other else points)

    resolve = StateSemanticsResolver.resolve_series

    def semantics(self, selected, *positional, **kwargs):
        value = resolve(self, selected, *positional, **kwargs)
        if mode == "unqualified" and selected.uuid == other.uuid:
            return replace(value, measurement_quantity="power")
        return value

    monkeypatch.setattr(StateSemanticsResolver, "resolve_series", semantics)

    runtime.authorized_statistics.side_effect = read
    args["sources"][2] = AnalysisSource(control_uuid=P, series_id="pv", granularity="hour")
    args["sources"].append(
        AnalysisSource(control_uuid=other.uuid, series_id="pv", granularity="hour")
    )
    doc = day_context_document()
    doc["associations"].append(
        {
            "association_id": "pv2",
            "source_index": 3,
            "role": "production",
            "origin": "user_confirmed",
        }
    )
    doc["day_context"]["assets"].append("garage")
    doc["day_context"]["production"].append(
        {"source_index": 3, "asset_ids": ["garage"], "coverage_origin": "user_confirmed"}
    )
    args["analysis_context"] = HistoryAnalysisContext.model_validate(doc)
    result = await tool.fn(**args)
    assert result.ok, result
    days = result.data.comparable_days
    assert len(days.production_sources) == 2
    assert runtime.authorized_statistics.await_count == 2
    assert days.reference.pv_wh == (5600 if mode == "complete" else None)
    assert (
        days.reference.pv_evidence
        == {
            "complete": "qualified",
            "gap": "intervals_incomplete",
            "unqualified": "rule_unverified",
        }[mode]
    )
    assert all(row.binding_id is None for row in days.production_sources)


@pytest.mark.parametrize("role", ["self_consumption", "grid_export"])
def test_context_scenario_auxiliary_balance_is_rejected(role):
    from mcpserver.analysis_context import HistoryAnalysisContext, resolve_history_associations

    doc = day_context_document()
    doc["associations"][2].update(role=role, origin="scenario_assumption")
    doc["day_context"].update(assets=[], production=[])
    ctx = HistoryAnalysisContext.model_validate(doc)
    meter = replace(
        control(),
        uuid=P,
        statistic_series=(StatisticSeries("pv", "statistic_v2", "2", "total", "PV", "kWh"),),
    )
    temperature = replace(control(), uuid=T, state_uuids=(("value", T),))
    with pytest.raises(ValueError, match="explicit confirmation"):
        resolve_history_associations(
            ctx,
            [
                {"control_uuid": C, "state_uuid": S},
                {"control_uuid": T, "state_uuid": T},
                {"control_uuid": P, "series_id": "pv"},
            ],
            {c.uuid: c for c in (control(), temperature, meter)},
            {},
            timezone_name="UTC",
        )


@pytest.mark.parametrize("mutation", ["overlap", "timezone", "independence", "common_supply"])
def test_day_context_contradictions_are_rejected(mutation):
    from mcpserver.analysis_context import HistoryAnalysisContext

    doc = day_context_document()
    if mutation == "overlap":
        doc["associations"].append(
            {"association_id": "pv2", "source_index": 3, "origin": "user_confirmed"}
        )
        doc["day_context"]["production"].append(
            {"source_index": 3, "asset_ids": ["roof"], "coverage_origin": "user_confirmed"}
        )
    elif mutation == "timezone":
        doc["day_context"]["site"].update(latitude=50.0)
    elif mutation == "independence":
        doc["day_context"].pop("radiation_independence_origin")
    else:
        doc["scope"]["common_supply_origin"] = "scenario_assumption"
        doc["associations"].append(
            {"association_id": "pv2", "source_index": 3, "origin": "user_confirmed"}
        )
        doc["day_context"]["assets"].append("garage")
        doc["day_context"]["production"].append(
            {"source_index": 3, "asset_ids": ["garage"], "coverage_origin": "user_confirmed"}
        )
    with pytest.raises(ValidationError):
        HistoryAnalysisContext.model_validate(doc)


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_context_reads_only_selected_weather_and_rechecks_sources(
    monkeypatch, tmp_path, changed
):
    from unittest.mock import AsyncMock

    from mcpserver.analysis_context import HistoryAnalysisContext

    runtime, tool, args, current = setup(monkeypatch, tmp_path)
    second = replace(control(), uuid="12345678-1234-1234-1234567890123461")
    runtime.structure = replace(runtime.structure, controls=(*runtime.structure.controls, second))
    extra = source(control_uuid=second.uuid)
    current[0] = replace(
        current[0], solar_history_sources=(*current[0].solar_history_sources, extra)
    )
    fresh = runtime.structure
    if changed:
        fresh = replace(
            fresh,
            controls=tuple(
                replace(c, name="Changed") if c.uuid == C else c for c in fresh.controls
            ),
        )
    runtime._history_visible_structure = AsyncMock(return_value=fresh)
    args["sources"].append(
        SolarAnalysisSource(source_kind="solar_observation", control_uuid=second.uuid, state_uuid=S)
    )
    doc = day_context_document()
    doc["associations"].append(
        {
            "association_id": "other-radiation",
            "source_index": 3,
            "role": "weather_context",
            "origin": "user_confirmed",
        }
    )
    args["analysis_context"] = HistoryAnalysisContext.model_validate(doc)
    original = SolarHistory.read
    calls = []

    def read(self, selected, *positional, **kwargs):
        calls.append(selected.key)
        return original(self, selected, *positional, **kwargs)

    monkeypatch.setattr(SolarHistory, "read", read)
    result = await tool.fn(**args)
    assert result.ok is not changed, result
    if changed:
        assert result.data.error == "temporarily_unavailable"
    else:
        assert result.data.comparable_days.reference.pv_wh == 2800
    assert len(calls) == 2 and extra.key not in calls


def fixture_data():
    first = datetime.combine(datetime.now(UTC).date() - timedelta(days=4), datetime.min.time(), UTC)
    temperature = source(control_uuid=T, state_uuid=T, kind="temperature", unit="°C")
    local = []
    for s in (source(), temperature):
        rows = []
        for day in range(4):
            begin = (first + timedelta(days=day, hours=10)).timestamp()
            if s.kind == "irradiance":
                rows.extend((begin + i, {"value": 100}) for i in range(0, 4 * 3600 + 1, 60))
            else:
                rows.extend((begin + i + 10, {"value": 20}) for i in range(0, 4 * 3600, 3600))
        local.append((s, s.kind, rows))
    pv = {
        (first + timedelta(days=d, hours=h)).timestamp(): 700 if d == 0 else 1000
        for d in range(4)
        for h in range(10, 14)
    }
    return first, local, pv


def calculate(local=None, energies=None, options=None, **kwargs):
    first, defaults, pv = fixture_data()
    return _calculate(
        local if local is not None else defaults,
        energies if energies is not None else {"production": pv},
        begin=first.timestamp(),
        finish=(first + timedelta(days=4)).timestamp(),
        zone_name="UTC",
        options=options
        or NumericalComparableDayOptions(
            method="numerical", reference_day=first.date().isoformat(), start_hour=10, end_hour=14
        ),
        installation="plant",
        balance_matches=kwargs.pop("balance_matches", False),
        deadline=time.monotonic() + 5,
        now=kwargs.pop("now", datetime.now(UTC)),
        **kwargs,
    )


def test_real_adapter_model_is_distinct_from_observed_interval_energy():
    result = calculate()
    assert result.group.count == 3 and result.group.check_candidate
    assert result.reference.pv_wh == 2800
    assert result.reference.radiation_wh_m2 == 400
    assert result.radiation_origin == "estimated_from_source_samples"
    assert result.solar_sources[1].maximum_sample_offset_seconds == 10
    assert result.weather_adjustment == "peer_selection_only"
    assert len(result.ranked_deviations) == 3
    assert result.self_consumption.method == "unavailable"


def test_missing_hour_excludes_candidate_without_shrinking_reference():
    first, local, _ = fixture_data()
    missing = (first + timedelta(days=1, hours=12)).timestamp()
    s, f, rows = local[0]
    local[0] = (s, f, [(t, p) for t, p in rows if not missing <= t < missing + 3600])
    result = calculate(local=local)
    assert result.common_hour_positions == [10, 11, 12, 13]
    assert len(result.candidates) == 2 and result.group is None
    assert result.exclusions[0].reason == "radiation_intervals_incomplete"


def test_missing_data_gives_configuration_guidance_not_zero_yield():
    result = calculate(local=[], energies={})
    assert result.status == "insufficient_evidence" and result.reference is None
    assert len(result.configuration_guidance) == 3


@pytest.mark.parametrize(
    "confirmed,matches,expected",
    [(False, True, "unavailable"), (True, False, "unavailable"), (True, True, "pv_minus_export")],
)
def test_export_requires_explicit_matching_balance(confirmed, matches, expected):
    first, _, pv = fixture_data()
    options = NumericalComparableDayOptions(
        method="numerical",
        reference_day=first.date().isoformat(),
        start_hour=10,
        end_hour=14,
        pv_export_balance_confirmed=confirmed,
    )
    result = calculate(
        energies={"production": pv, "grid_export": {t: 100 for t in pv}},
        options=options,
        balance_matches=matches,
    )
    assert result.self_consumption.method == expected
    if confirmed and matches:
        assert result.self_consumption.reference_wh == 2400
        assert result.self_consumption.group.count == 3


def test_direct_self_consumption_preferred_and_negative_balance_not_clamped():
    _, _, pv = fixture_data()
    result = calculate(
        energies={"production": pv, "self_consumption": {t: 50 for t in pv}, "grid_export": pv}
    )
    assert result.self_consumption.method == "direct_observed"
    assert result.self_consumption.reference_wh == 200
    options = NumericalComparableDayOptions(
        method="numerical",
        reference_day=result.reference_day,
        start_hour=10,
        end_hour=14,
        pv_export_balance_confirmed=True,
    )
    result = calculate(
        energies={"production": pv, "grid_export": {t: v + 1 for t, v in pv.items()}},
        options=options,
        balance_matches=True,
    )
    assert result.self_consumption.reference_wh is None
    assert result.self_consumption.pairs == []


def test_forecast_cycles_never_establish_period_bounds_or_actual_comparisons():
    epoch = datetime(2009, 1, 1, tzinfo=UTC).timestamp()
    begin = datetime(2026, 7, 1, 10, tzinfo=UTC).timestamp()
    states = dict(
        period=4,
        today=24,
        tomorrow=24,
        after=24,
        inputperiod=4,
        ready=1,
        errorInfo=0,
        timestamp=begin - epoch - 120,
        cycleFrom=begin - epoch - 3600,
        cycleUntil=begin - epoch,
    )
    rows = [(begin - 60, {"states": states}), (begin - 30, {"states": states | {"period": 5}})]
    contexts = _forecast_context(rows)
    assert len(contexts) == 2 and contexts[1]["period_kwh"] == 5
    assert contexts[0]["cycle_until"] is not None
    first, local, _ = fixture_data()
    forecast = source(control_uuid=P, kind="pv_forecast", state_uuid=None, unit="kWh")
    result = calculate(local=[*local, (forecast, "forecast", rows)])
    assert result.group.count == 3
    assert all(
        c.comparison_status == "native_period_bounds_unverified" for c in result.forecast_context
    )
    assert (
        "native_period_bounds_unverified_cycle_times_describe_current_prediction_hour"
        in result.forecast_limitations
    )
    unavailable = _forecast_context([(begin - 60, {"states": states | {"ready": 0}})])
    assert unavailable[0]["status"] == "unavailable" and unavailable[0]["period_kwh"] is None


def test_forecast_context_respects_half_open_capture_interval():
    first, local, _ = fixture_data()
    begin, finish = first.timestamp(), (first + timedelta(days=4)).timestamp()
    forecast = source(control_uuid=P, kind="pv_forecast", state_uuid=None, unit="kWh")
    payload = {
        "states": dict(
            period=-1,
            today=-1,
            tomorrow=-1,
            after=-1,
            inputperiod=24,
            ready=0,
            errorInfo=2,
            timestamp=0,
            cycleFrom=0,
            cycleUntil=0,
        )
    }
    rows = [(at, payload) for at in (begin - 60, begin, finish - 60, finish, finish + 60)]
    result = calculate(local=[*local, (forecast, "forecast", rows)])
    assert [datetime.fromisoformat(c.captured_at).timestamp() for c in result.forecast_context] == [
        begin,
        finish - 60,
    ]


@pytest.mark.asyncio
async def test_numerical_structured_weather_selector_is_invalid_input(monkeypatch, tmp_path):
    from mcpserver.comparable_days_tools import WeatherAnalysisSource

    runtime, tool, args, _ = setup(monkeypatch, tmp_path)
    args["sources"] = [WeatherAnalysisSource(source_kind="structured_weather", state_uuid=S)]
    result = await tool.fn(**args)
    assert not result.ok and result.data.error == "invalid_input"
    runtime.authorized_statistics.assert_not_awaited()


def setup(monkeypatch, tmp_path, role="production"):
    runtime, _ = configured(monkeypatch)
    runtime.endpoint = SimpleNamespace(origin="http://192.168.255.254")
    first, local, pv = fixture_data()
    series = StatisticSeries("pv", "statistic_v2", "2", "total", "PV", "0,000kWh", accumulated=True)
    meter = replace(control(), uuid=P, control_type="Meter", statistic_series=(series,))
    temp = replace(control(), uuid=T, state_uuids=(("value", T),), format="%.1f°C")
    runtime.structure = replace(runtime.structure, controls=(control(), temp, meter))
    runtime.authorized_statistics.return_value = (
        meter,
        series,
        tuple(StatisticPoint(int(t), v / 1000) for t, v in pv.items()),
    )
    config = PluginConfig(
        loxone_endpoint=runtime.endpoint.origin,
        loxone_history_enabled=True,
        solar_history_sources=tuple(s for s, _, _ in local),
    )
    current = [config]
    store = EventHistoryStore(tmp_path / "history.sqlite3", retention_days=30, maximum_mib=16)
    store.initialize()
    identity = installation_identity(runtime.endpoint.origin, runtime.structure)
    for s, _, rows in local:
        ctrl = control() if s.kind == "irradiance" else temp
        fingerprint = s.fingerprint(ctrl, identity)
        records = [(s.key, fingerprint, t, json.dumps(payload)) for t, payload in rows]
        for i in range(0, len(records), 16):
            SolarHistory(store).record(records[i : i + 16])
    path = tmp_path / "profile.json"
    ProfileStore(path).put(
        identity,
        0,
        BindingInput(
            binding_id="production",
            role=role,
            control_uuid=P,
            source_kind="statistic",
            series_id="pv",
            confirmed=True,
        ),
        meter,
        origin="local_admin",
        actor_ref=hashlib.sha256(b"fixture").hexdigest(),
    )
    server = FastMCP("numeric-fixture")
    register_history_analysis_tool(
        server,
        runtime,
        SimpleNamespace(
            _config_store=SimpleNamespace(load=lambda: current[0]), _store_path=store.path
        ),
        path,
    )
    args = dict(
        operation="comparable_days",
        sources=[
            SolarAnalysisSource(
                source_kind="solar_observation",
                control_uuid=s.control_uuid,
                state_uuid=s.state_uuid,
            )
            for s, _, _ in local
        ]
        + [AnalysisSource(binding_id="production", granularity="hour")],
        start=first.isoformat(),
        end=(first + timedelta(days=4)).isoformat(),
        timezone="UTC",
        comparable_day_options=NumericalComparableDayOptions(
            method="numerical", reference_day=first.date().isoformat(), start_hour=10, end_hour=14
        ),
    )
    return runtime, server._tool_manager.get_tool("loxone_analyze_history"), args, current


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["production", "self_consumption", "grid_export"])
@pytest.mark.parametrize("qualified", [False, True])
async def test_energy_role_does_not_qualify_semantics_and_empty_qualified_data_stays_incomplete(
    monkeypatch, tmp_path, role, qualified
):
    runtime, tool, args, _ = setup(monkeypatch, tmp_path, role=role)
    meter, series, _ = runtime.authorized_statistics.return_value
    runtime.authorized_statistics.return_value = meter, series, ()
    resolve = StateSemanticsResolver.resolve_series

    def semantics(self, *args, **kwargs):
        value = resolve(self, *args, **kwargs)
        return value if qualified else replace(value, measurement_quantity="power")

    monkeypatch.setattr(StateSemanticsResolver, "resolve_series", semantics)
    result = await tool.fn(**args)
    assert result.ok, result
    comparison = result.data.comparable_days
    assert comparison.reference.pv_evidence == (
        "intervals_incomplete" if role == "production" and qualified else "rule_unverified"
    )
    assert comparison.self_consumption.method == (
        "direct_observed" if role == "self_consumption" and qualified else "unavailable"
    )


def test_running_reference_respects_earlier_requested_end():
    first, local, pv = fixture_data()
    first += timedelta(days=1)
    local = [(s, f, [(t + 86400, p) for t, p in rows]) for s, f, rows in local]
    pv = {t + 86400: v for t, v in pv.items()}
    today = first + timedelta(days=3)
    result = _calculate(
        local,
        {"production": pv},
        begin=first.timestamp(),
        finish=(today + timedelta(hours=12, minutes=30)).timestamp(),
        zone_name="UTC",
        options=NumericalComparableDayOptions(
            method="numerical", reference_day=today.date().isoformat(), start_hour=10, end_hour=14
        ),
        installation="plant",
        balance_matches=False,
        deadline=time.monotonic() + 5,
        now=today + timedelta(hours=18),
    )
    assert result.common_hour_positions == [10, 11]
    assert result.reference.pv_wh == 2000
    assert result.group.count == 3


@pytest.mark.asyncio
async def test_one_authorized_context_and_one_read_per_source_and_range(monkeypatch, tmp_path):
    runtime, tool, args, current = setup(monkeypatch, tmp_path)
    original = SolarHistory.read
    calls = []

    def read(self, source, *args, **kwargs):
        calls.append(source.key)
        return original(self, source, *args, **kwargs)

    monkeypatch.setattr(SolarHistory, "read", read)
    result = await asyncio.wait_for(tool.fn(**(args | {"sources": args["sources"] * 2})), 5)
    assert result.ok, result
    assert result.data.comparable_days.group.count == 3
    assert runtime.contexts == 1 and runtime.authorized_statistics.await_count == 1
    assert len(calls) == 2 and result.data.input_points == 996
    assert len(result.model_dump_json().encode()) < 64 * 1024
    assert "source_reference" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_revocation_and_configuration_change_prevent_output(monkeypatch, tmp_path):
    runtime, tool, args, current = setup(monkeypatch, tmp_path)

    async def revoke(_access):
        if runtime._require_access.await_count == 3:
            raise RuntimeAuthorizationError("private-revocation")

    runtime._require_access.side_effect = revoke
    result = await tool.fn(**args)
    assert not result.ok and result.data.error == "permission_denied"
    assert "private-revocation" not in result.model_dump_json()
    runtime._require_access.reset_mock(side_effect=True)

    async def change(_access):
        if runtime._require_access.await_count == 3:
            current[0] = replace(current[0], solar_history_sources=())

    runtime._require_access.side_effect = change
    result = await tool.fn(**args)
    assert not result.ok and result.data.error == "permission_denied"


@pytest.mark.asyncio
async def test_hidden_and_unregistered_solar_sources_are_not_read(monkeypatch, tmp_path):
    runtime, tool, args, current = setup(monkeypatch, tmp_path)
    current[0] = replace(current[0], solar_history_sources=())
    result = await tool.fn(**args)
    assert not result.ok and result.data.error == "not_found"
    runtime.authorized_statistics.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_source", [False, True])
async def test_stale_energy_binding_returns_not_found_without_statistic_read(
    monkeypatch, tmp_path, missing_source
):
    runtime, tool, args, _ = setup(monkeypatch, tmp_path)
    if missing_source:
        runtime.structure = replace(
            runtime.structure,
            controls=tuple(c for c in runtime.structure.controls if c.uuid != P),
        )
    else:
        args["sources"][-1] = AnalysisSource(binding_id="deleted-production", granularity="hour")
    result = await tool.fn(**args)
    assert not result.ok and result.data.error == "not_found"
    runtime.authorized_statistics.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [{"is_hidden": True}, {"format": "%.0flux"}, {"state_uuids": ()}, {"control_type": "Slider"}],
)
async def test_stale_registered_source_is_unavailable_not_invalid_input(
    monkeypatch, tmp_path, change
):
    runtime, tool, args, _ = setup(monkeypatch, tmp_path)
    runtime.structure = replace(
        runtime.structure, controls=(replace(control(), **change), *runtime.structure.controls[1:])
    )
    result = await tool.fn(**args)
    assert not result.ok and result.data.error == "not_found"
    runtime.authorized_statistics.assert_not_awaited()


@pytest.mark.parametrize(
    "format,unit",
    [
        ("0,000kWh", "kWh"),
        ("0.00Wh", "Wh"),
        ("%.3fkWh", "kWh"),
        ("1,000kWh", None),
        ("0,000lux", None),
    ],
)
def test_native_meter_decimal_format_has_narrow_units_and_own_rule(format, unit):
    resolver = StateSemanticsResolver()
    series = StatisticSeries("pv", "statistic_v2", "2", "total", "PV", format, accumulated=True)
    meter = replace(control(), control_type="Meter", statistic_series=(series,))
    assert resolver.resolve_series(meter, series, granularity="hour").unit == unit
    if format == "0,000kWh":
        assert "native_numeric_format" in resolver.source_reference(meter, series=series)
    assert (
        resolver.resolve_series(
            replace(meter, control_type="InfoOnlyAnalog"), series, granularity="hour"
        ).unit
        is None
    )


def test_callers_cannot_supply_observation_contract_or_expand_tolerances():
    with pytest.raises(ValidationError):
        SolarAnalysisSource(
            source_kind="solar_observation", control_uuid=C, state_uuid=S, unit="W/m²"
        )
    with pytest.raises(ValidationError):
        NumericalComparableDayOptions(
            method="numerical", reference_day="2026-07-01", radiation_relative_tolerance=0.16
        )


@pytest.mark.asyncio
async def test_published_explorer_union_preserves_qualitative_default(monkeypatch, tmp_path):
    _, tool, args, _ = setup(monkeypatch, tmp_path)
    arguments = tool.fn_metadata.arg_model
    numeric = arguments.model_validate(args)
    assert numeric.comparable_day_options.method == "numerical"
    old = arguments.model_validate(
        args
        | {
            "comparable_day_options": {
                "reference_day": args["comparable_day_options"].reference_day
            }
        }
    )
    assert old.comparable_day_options.method == "radiation_classes"
    schema = arguments.model_json_schema()
    assert (
        schema["$defs"]["NumericalComparableDayOptions"]["properties"]["method"]["const"]
        == "numerical"
    )
    assert schema["$defs"]["SolarAnalysisSource"]["additionalProperties"] is False
