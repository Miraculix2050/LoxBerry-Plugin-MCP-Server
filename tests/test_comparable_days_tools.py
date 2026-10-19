import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError
from test_history_analysis_tools import configured

from mcpserver.comparable_class_days import ClassRule
from mcpserver.comparable_days_models import ClassComparableDayOptions
from mcpserver.comparable_days_tools import WeatherAnalysisSource
from mcpserver.config import PluginConfig
from mcpserver.history_analysis_tools import AnalysisSource, register_history_analysis_tool
from mcpserver.installation_profile import installation_identity
from mcpserver.loxone.event_history import EventHistoryStore
from mcpserver.loxone.models import GlobalMetadata
from mcpserver.loxone.runtime import RuntimeAuthorizationError
from mcpserver.loxone.weather_history import (
    LOXONE_EPOCH,
    WeatherHistory,
    WeatherHistorySource,
    source_fingerprint,
)

UUID = "00000001-0000-0000-0000000000000001"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "weather", "revision"])
async def test_context_class_source_is_explicit_and_revalidated(monkeypatch, tmp_path, change):
    from unittest.mock import AsyncMock

    from mcpserver.analysis_context import HistoryAnalysisContext

    runtime, tool, args, _, _ = setup(monkeypatch, tmp_path)
    fresh = runtime.structure
    if change == "weather":
        fresh = replace(fresh, global_metadata=())
    runtime._history_visible_structure = AsyncMock(return_value=fresh)
    args["analysis_context"] = HistoryAnalysisContext.model_validate(
        {
            "scope": {
                "kind": "scenario",
                "description": "One site",
                "common_supply_origin": "user_confirmed",
            },
            "associations": [
                {
                    "association_id": "weather",
                    "source_index": 0,
                    "role": "weather_context",
                    "origin": "user_confirmed",
                }
            ],
            "day_context": {
                "site": {
                    "site_id": "site",
                    "timezone": "UTC",
                    "association_origin": "user_confirmed",
                },
                "weather": [{"quantity": "radiation", "source_index": 0}],
            },
        }
    )
    if change == "revision":
        monkeypatch.setattr(
            "mcpserver.history_analysis_tools.read_profile_bindings",
            AsyncMock(side_effect=[({}, 1), ({}, 2)]),
        )
    result = await tool.fn(**args)
    assert result.ok == (change == "none"), result
    if result.ok:
        assert result.data.day_context.site.site_id == "site"
        assert result.data.context_associations[0].control_uuid is None
        assert result.data.context_associations[0].binding_id is None
        assert result.data.weather_sources[0].state_uuid == UUID
        assert (
            "site_and_coverage_are_owner_confirmed_not_independently_verified"
            in result.data.comparable_days.limitations
        )
    else:
        assert result.data.error == "temporarily_unavailable"
    runtime.authorized_statistics.assert_not_awaited()


def setup(monkeypatch, tmp_path):
    runtime, _old = configured(monkeypatch)
    runtime.endpoint = SimpleNamespace(origin="http://192.168.255.254")
    runtime.structure = replace(
        runtime.structure,
        global_metadata=(GlobalMetadata("weather_state", "actual", "Actual", state_uuid=UUID),),
    )
    source = WeatherHistorySource(UUID, "actual", ("solar_radiation",))
    config = PluginConfig(
        loxone_endpoint=runtime.endpoint.origin,
        loxone_history_enabled=True,
        weather_history_sources=(source,),
    )
    current = [config]
    store = EventHistoryStore(
        tmp_path / "history.sqlite3",
        retention_days=config.event_history_retention_days,
        maximum_mib=config.event_history_maximum_mib,
    )
    store.initialize()
    weather = WeatherHistory(store)
    fingerprint = source_fingerprint(
        source, runtime.structure, installation_identity(runtime.endpoint.origin, runtime.structure)
    )
    first = datetime.combine(datetime.now(UTC).date() - timedelta(days=4), datetime.min.time(), UTC)
    capture = weather.begin(source, fingerprint, first.timestamp() - 1)
    for offset in range(4):
        for hour, value in zip(range(10, 14), (0, 1, 2, 3), strict=True):
            at = (first + timedelta(days=offset, hours=hour)).timestamp()
            weather.record(
                capture,
                source,
                {
                    "last_update": int(at - LOXONE_EPOCH),
                    "entries": [{"timestamp": int(at - LOXONE_EPOCH), "solar_radiation": value}],
                },
                at + 1,
            )
    event = SimpleNamespace(
        _config_store=SimpleNamespace(load=lambda: current[0]), _store_path=store.path
    )
    server = FastMCP("class-analysis-fixture")
    register_history_analysis_tool(server, runtime, event, None)
    tool = server._tool_manager.get_tool("loxone_analyze_history")
    args = dict(
        operation="comparable_days",
        sources=[WeatherAnalysisSource(source_kind="structured_weather", state_uuid=UUID)],
        start=first.isoformat(),
        end=(first + timedelta(days=4)).isoformat(),
        timezone="UTC",
        comparable_day_options=ClassComparableDayOptions(
            reference_day=first.date().isoformat(), start_hour=10, end_hour=14
        ),
    )
    return runtime, tool, args, current, weather


@pytest.mark.asyncio
async def test_class_adapter_uses_one_context_and_one_deduplicated_source_read(
    monkeypatch, tmp_path
):
    runtime, tool, args, current, weather = setup(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "mcpserver.comparable_days_tools.NATIVE_CLASS_RULE", ClassRule.REVIEWED_RISK_CLASS
    )
    original = WeatherHistory.analysis_points
    calls = []

    def read(self, *values, **kwargs):
        calls.append(1)
        return original(self, *values, **kwargs)

    monkeypatch.setattr(WeatherHistory, "analysis_points", read)
    result = await asyncio.wait_for(tool.fn(**{**args, "sources": args["sources"] * 2}), 3)
    assert result.ok
    assert len(result.data.comparable_days.candidates) == 3
    assert result.data.sources == []
    assert result.data.weather_sources[0].state_uuid == UUID
    assert result.data.input_points == 16
    assert calls == [1]
    assert runtime.contexts == 1
    assert runtime._require_access.await_count == 2
    runtime.authorized_statistics.assert_not_awaited()


@pytest.mark.asyncio
async def test_unqualified_native_mapping_is_explicit_not_invented(monkeypatch, tmp_path):
    runtime, tool, args, current, weather = setup(monkeypatch, tmp_path)
    monkeypatch.setattr("mcpserver.comparable_days_tools.NATIVE_CLASS_RULE", None)
    result = await tool.fn(**args)
    assert result.ok
    assert result.data.comparable_days.status == "insufficient_evidence"
    assert "radiation_class_mapping_unverified" in result.data.comparable_days.limitations


@pytest.mark.asyncio
async def test_foreign_or_unconfigured_sources_are_not_read(monkeypatch, tmp_path):
    runtime, tool, args, current, weather = setup(monkeypatch, tmp_path)
    current[0] = replace(current[0], weather_history_sources=())
    result = await tool.fn(**args)
    assert not result.ok
    assert result.data.error == "not_found"


@pytest.mark.asyncio
async def test_visibility_and_final_authorization_remain_required(monkeypatch, tmp_path):
    runtime, tool, args, current, weather = setup(monkeypatch, tmp_path)
    runtime.structure = replace(runtime.structure, global_metadata=())
    result = await tool.fn(**args)
    assert not result.ok and result.data.error == "not_found"
    runtime.structure = replace(
        runtime.structure,
        global_metadata=(GlobalMetadata("weather_state", "actual", "Actual", state_uuid=UUID),),
    )
    runtime._require_access.side_effect = [None, RuntimeAuthorizationError("fixture revocation")]
    result = await tool.fn(**args)
    assert not result.ok and result.data.error == "permission_denied"


@pytest.mark.asyncio
async def test_source_configuration_changes_before_output_are_denied(monkeypatch, tmp_path):
    runtime, tool, args, current, weather = setup(monkeypatch, tmp_path)

    async def access(_token):
        if runtime._require_access.await_count == 2:
            current[0] = replace(current[0], weather_history_sources=())

    runtime._require_access.side_effect = access
    result = await tool.fn(**args)
    assert not result.ok and result.data.error == "permission_denied"


@pytest.mark.asyncio
async def test_class_options_raw_requests_and_scalar_misuse_fail_before_context(
    monkeypatch, tmp_path
):
    runtime, tool, args, current, weather = setup(monkeypatch, tmp_path)
    for update in (
        {"include_raw": True},
        {"comparable_day_options": None},
        {"operation": "energy"},
    ):
        result = await tool.fn(**{**args, **update})
        assert not result.ok and result.data.error == "invalid_input"
    assert runtime.contexts == 0


def test_weather_selector_does_not_relax_scalar_exact_source_contract():
    with pytest.raises(ValidationError):
        AnalysisSource(state_uuid=UUID)
    with pytest.raises(ValidationError):
        WeatherAnalysisSource(
            source_kind="structured_weather", state_uuid=UUID, stored_mode="forecast"
        )
    with pytest.raises(ValidationError):
        WeatherAnalysisSource(
            source_kind="structured_weather", state_uuid=UUID, control_uuid="fake"
        )


@pytest.mark.asyncio
async def test_confirmed_weather_binding_resolves_without_invented_control_uuid(
    monkeypatch, tmp_path
):
    import hashlib

    from mcpserver.installation_profile import ProfileSources, ProfileStore, WeatherBindingInput

    runtime, _tool, args, current, weather = setup(monkeypatch, tmp_path)
    identity = installation_identity(runtime.endpoint.origin, runtime.structure)
    profile = tmp_path / "profile.json"
    binding = WeatherBindingInput(
        binding_id="weather",
        role="weather_context",
        source_kind="weather",
        weather_state_uuid=UUID,
        mode="actual",
        field="solar_radiation",
        confirmed=True,
    )
    ProfileStore(profile).put(
        identity,
        0,
        binding,
        ProfileSources.from_structure(identity, runtime.structure),
        origin="local_admin",
        actor_ref=hashlib.sha256(b"fixture-actor").hexdigest(),
    )
    event = SimpleNamespace(
        _config_store=SimpleNamespace(load=lambda: current[0]), _store_path=weather.store.path
    )
    server = FastMCP("class-bound-fixture")
    register_history_analysis_tool(server, runtime, event, profile)
    tool = server._tool_manager.get_tool("loxone_analyze_history")
    result = await tool.fn(**{**args, "sources": [AnalysisSource(binding_id="weather")]})
    assert result.ok
    assert len(result.data.comparable_days.candidates) == 3
    assert result.data.sources == []
    assert result.data.weather_sources[0].state_uuid == UUID


@pytest.mark.asyncio
async def test_invalid_reference_and_scalar_selector_fail_before_context(monkeypatch, tmp_path):
    runtime, tool, args, current, weather = setup(monkeypatch, tmp_path)
    for update in (
        {"sources": [AnalysisSource(control_uuid="control", series_id="series")]},
        {"comparable_day_options": ClassComparableDayOptions(reference_day="1970-01-01")},
    ):
        result = await tool.fn(**{**args, **update})
        assert not result.ok and result.data.error == "invalid_input"
    assert runtime.contexts == 0


@pytest.mark.asyncio
async def test_invalid_values_survive_archive_and_warn_ai_with_sanitized_trace_log(
    monkeypatch, tmp_path, caplog
):
    import logging

    runtime, tool, args, current, weather = setup(monkeypatch, tmp_path)
    start = datetime.fromisoformat(args["start"]).timestamp()
    at = start + 10 * 3600
    with weather.store._opened() as db:
        capture = db.execute("SELECT id FROM weather_captures LIMIT 1").fetchone()[0]
    source = current[0].weather_history_sources[0]
    weather.record(
        capture,
        source,
        {
            "last_update": int(at - LOXONE_EPOCH),
            "entries": [{"timestamp": int(at - LOXONE_EPOCH), "solar_radiation": 5}],
        },
        at + 120,
    )
    caplog.set_level(logging.WARNING, logger="mcpserver.history_analysis")
    result = await tool.fn(**args)
    assert result.ok
    assert result.warnings
    assert result.data.comparable_days.invalid_source_point_count == 1
    diagnostic = result.data.comparable_days.invalid_points[0]
    assert diagnostic.raw_value == 5
    assert diagnostic.point_at == at
    assert diagnostic.classification_origin == "owner_assumed_risk_class_0_3"
    with weather.store._opened() as db:
        assert db.execute("SELECT COUNT(*) FROM weather_points").fetchone()[0] == 17
    records = [r.getMessage() for r in caplog.records if r.name == "mcpserver.history_analysis"]
    assert len(records) == 1
    assert result.trace_id in records[0]
    assert "outcome=unexpected_class_values" in records[0]
    assert UUID not in records[0]
    assert "solar_radiation" not in records[0]
