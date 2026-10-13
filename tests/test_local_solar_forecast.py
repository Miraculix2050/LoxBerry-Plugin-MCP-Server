from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP

from mcpserver.auth.provider import LOXBERRY_READ_SCOPE, READ_SCOPE, StoredAccessToken
from mcpserver.config import ConfigError, PluginConfig
from mcpserver.local_solar_forecast import LocalSolarForecastRuntime, read_forecast
from mcpserver.loxone.endpoint import MiniserverEndpoint
from mcpserver.loxone.runtime import ControlOperationError, LoxoneRuntime
from mcpserver.solar_forecast import ForecastEvidenceError, SolarWindowOptions
from mcpserver.tools import LoxBerryReadRuntime, register_read_tools


def access():
    return StoredAccessToken(
        token="opaque",
        client_id="client",
        scopes=[READ_SCOPE, LOXBERRY_READ_SCOPE],
        expires_at=2_000_000_000,
        resource="http://synthetic.local/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="miniserver",
    )


@pytest.fixture
def context(tmp_path):
    now = int(time.time())
    start = now + 3600
    document = {
        "location": {"timezone": "UTC", "latitude": 48.0, "longitude": 10.0},
        "visualcrossing": {"schemaVersion": "v1.0", "grabberScript": "grabber_visualcrossing.pl"},
        "hourlyforecast": [
            {
                "time": {
                    "datetime": datetime.fromtimestamp(start + i * 3600, UTC).isoformat(),
                    "epoch": start + i * 3600,
                },
                "solarRadiation": v,
            }
            for i, v in enumerate((100, -1, 500, 0))
        ],
    }
    path = tmp_path / "hourlyforecast.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    config = PluginConfig(
        loxone_endpoint="http://192.168.1.10",
        loxberry_read_enabled=True,
        loxberry_read_bindings=("binding",),
        solar_forecast_enabled=True,
    )
    forecast = read_forecast(config, deadline=time.monotonic() + 5, path=path)
    config = replace(config, solar_forecast_fingerprint=forecast.fingerprint)
    store = SimpleNamespace(config=config)
    store.load = lambda: store.config
    auth_store = SimpleNamespace(pseudonym=lambda *args: "binding")
    local = LoxBerryReadRuntime(SimpleNamespace(), store, auth_store)
    runtime = LoxoneRuntime(
        MiniserverEndpoint.parse_gen1(config.loxone_endpoint),
        SimpleNamespace(),
        validate_access=AsyncMock(return_value=True),
    )
    adapter = LocalSolarForecastRuntime(runtime, local, path=path)
    options = SolarWindowOptions(
        start=datetime.fromtimestamp(start, UTC).isoformat(),
        end=datetime.fromtimestamp(start + 4 * 3600, UTC).isoformat(),
        timezone="UTC",
        include_samples=True,
    )
    return adapter, store, path, options


@pytest.mark.asyncio
async def test_independent_local_approval_cannot_be_inferred_from_loxone(context):
    adapter, store, path, options = context
    store.config = replace(store.config, loxberry_read_bindings=())
    path.unlink()
    result = await adapter.read(access(), None, limit=16, trace_id="trace")
    assert result.status == "local_read_not_authorized"
    with pytest.raises(ControlOperationError, match="independent"):
        await adapter.read(access(), options, limit=16, trace_id="trace")


@pytest.mark.asyncio
async def test_disabled_source_is_not_probed(context):
    adapter, store, path, _ = context
    store.config = replace(store.config, solar_forecast_enabled=False)
    path.unlink()
    assert (
        await adapter.read(access(), None, limit=16, trace_id="trace")
    ).status == "disabled_not_probed"


@pytest.mark.asyncio
async def test_available_source_keeps_invalid_values_visible_and_logs_safely(context, caplog):
    adapter, _, path, options = context
    before = path.read_bytes()
    result = await adapter.read(access(), options, limit=16, trace_id="trace-123")
    assert result.windows[0].mean_sample_irradiance_w_m2 == 500
    assert result.invalid_point_count == 1 and result.diagnostics[0].raw_number == -1
    assert result.planning_status == "weather_guidance_only"
    assert path.read_bytes() == before
    assert "trace-123" in caplog.text and "negative_irradiance" in caplog.text
    assert str(path) not in caplog.text and "48.0" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,status",
    [
        ({"solar_forecast_fingerprint": "0" * 64}, "changed"),
        ({"solar_forecast_fingerprint": ""}, "unconfirmed"),
    ],
)
async def test_source_association_is_never_automatically_retargeted(context, change, status):
    adapter, store, _, _ = context
    store.config = replace(store.config, **change)
    assert (await adapter.read(access(), None, limit=16, trace_id="trace")).status == status


@pytest.mark.asyncio
async def test_stale_publication_and_missing_source_have_distinct_guidance(context):
    adapter, _, path, _ = context
    os.utime(path, (time.time() - 20000, time.time() - 20000))
    assert (await adapter.read(access(), None, limit=16, trace_id="trace")).status == "stale"
    path.unlink()
    assert (await adapter.read(access(), None, limit=16, trace_id="trace")).status == "missing"


@pytest.mark.asyncio
async def test_grant_revoked_before_publication_is_checked_again(context, monkeypatch):
    import mcpserver.local_solar_forecast as module

    adapter, store, _, options = context
    original = module.sampled_solar_windows

    def calculate(*args, **kwargs):
        result = original(*args, **kwargs)
        store.config = replace(store.config, loxberry_read_bindings=())
        return result

    monkeypatch.setattr(module, "sampled_solar_windows", calculate)
    with pytest.raises(PermissionError):
        await adapter.read(access(), options, limit=16, trace_id="trace")
    assert adapter._pending == 0


@pytest.mark.asyncio
async def test_source_changes_before_publication_require_current_evidence(context, monkeypatch):
    import mcpserver.local_solar_forecast as module

    adapter, _, path, options = context
    original = module.sampled_solar_windows

    def calculate(*args, **kwargs):
        result = original(*args, **kwargs)
        path.write_bytes(path.read_bytes().replace(b"500", b"700"))
        return result

    monkeypatch.setattr(module, "sampled_solar_windows", calculate)
    with pytest.raises(ControlOperationError, match="changed"):
        await adapter.read(access(), options, limit=16, trace_id="trace")


@pytest.mark.asyncio
async def test_publication_crossing_age_limit_during_calculation_is_not_published(
    context, monkeypatch
):
    import mcpserver.local_solar_forecast as module

    adapter, store, _, options = context
    store.config = replace(store.config, solar_forecast_maximum_age_minutes=1)
    actual_clock = time.time
    advanced = False
    original = module.sampled_solar_windows

    def calculate(*args, **kwargs):
        nonlocal advanced
        result = original(*args, **kwargs)
        advanced = True
        return result

    monkeypatch.setattr(module, "sampled_solar_windows", calculate)
    monkeypatch.setattr(module.time, "time", lambda: actual_clock() + (120 if advanced else 0))
    with pytest.raises(ControlOperationError, match="unavailable"):
        await adapter.read(access(), options, limit=16, trace_id="trace")


@pytest.mark.asyncio
async def test_worker_admission_retained_until_cancelled_thread_stops(context, monkeypatch):
    import threading

    import mcpserver.local_solar_forecast as module

    adapter, _, _, options = context
    entered, release = threading.Event(), threading.Event()
    original = module.read_forecast

    def blocking(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "read_forecast", blocking)
    task = asyncio.create_task(adapter.read(access(), options, limit=16, trace_id="trace"))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0.02)
        assert adapter._pending == 1 and not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert adapter._pending == 0


def test_bounded_reader_rejects_symlink_and_large_file(context):
    adapter, store, path, _ = context
    path.write_bytes(b" " * (4 * 1024 * 1024 + 1))
    with pytest.raises(ForecastEvidenceError, match="too_large"):
        read_forecast(store.config, deadline=time.monotonic() + 5, path=path)


def test_config_default_off_bounds_and_private_confirmation_round_trip():
    config = PluginConfig.defaults()
    assert not config.solar_forecast_enabled and not config.solar_forecast_fingerprint
    config = replace(config, solar_forecast_fingerprint="a" * 64)
    assert PluginConfig.from_document(config.to_document()).solar_forecast_fingerprint == "a" * 64
    for block in ({"maximum_age_minutes": 0}, {"fingerprint": "foreign"}, {"enabled": "true"}):
        document = config.to_document()
        document["solar_forecast"] = block
        with pytest.raises(ConfigError):
            PluginConfig.from_document(document)


def test_admin_confirmation_cannot_use_a_caller_supplied_fingerprint(context, monkeypatch):
    import mcpserver.local_solar_forecast as module
    from mcpserver.admin import AdminError, _confirmed_solar_config

    _, store, path, _ = context
    previous = replace(store.config, solar_forecast_enabled=False, solar_forecast_fingerprint="")
    requested = replace(previous, solar_forecast_enabled=True, solar_forecast_fingerprint="0" * 64)
    with pytest.raises(AdminError, match="explicit"):
        _confirmed_solar_config(previous, requested, {})
    actual = read_forecast(store.config, deadline=time.monotonic() + 5, path=path)
    monkeypatch.setattr(module, "read_forecast", lambda *args, **kwargs: actual)
    confirmed = _confirmed_solar_config(
        previous, requested, {"confirm_solar_forecast_source": True}
    )
    assert confirmed.solar_forecast_fingerprint == actual.fingerprint
    assert confirmed.solar_forecast_fingerprint != requested.solar_forecast_fingerprint


def test_failed_admin_source_confirmation_preserves_original_configuration(context, monkeypatch):
    import mcpserver.local_solar_forecast as module
    from mcpserver.admin import AdminError, _confirmed_solar_config

    _, store, _, _ = context
    original = store.config

    def unavailable(*args, **kwargs):
        raise ForecastEvidenceError("forecast_file_missing")

    monkeypatch.setattr(module, "read_forecast", unavailable)
    with pytest.raises(AdminError, match="cannot be confirmed"):
        _confirmed_solar_config(original, original, {"confirm_solar_forecast_source": True})
    assert store.config is original


@pytest.mark.asyncio
async def test_registered_weather_outputs_are_typed_and_correlated(context, monkeypatch):
    import mcpserver.tools as tools

    adapter, _, _, options = context
    monkeypatch.setattr(tools, "_access", access)
    server = FastMCP("solar")
    register_read_tools(server, adapter.runtime, solar_forecast_runtime=adapter)
    tool = server._tool_manager.get_tool("loxone_get_weather")
    for arguments in (
        {"mode": "forecast_sources"},
        {"mode": "solar_windows", "future_options": options.model_dump()},
    ):
        result = await tool.run(arguments)
        assert result.ok and result.warnings and result.trace_id
        assert result.data.invalid_point_count == 1
        assert result.data.diagnostics[0].issue == "negative_irradiance"


@pytest.mark.asyncio
async def test_new_weather_modes_reject_cross_mode_inputs(context, monkeypatch):
    import mcpserver.tools as tools

    adapter, _, _, options = context
    monkeypatch.setattr(tools, "_access", access)
    server = FastMCP("solar")
    register_read_tools(server, adapter.runtime, solar_forecast_runtime=adapter)
    tool = server._tool_manager.get_tool("loxone_get_weather")
    for arguments in (
        {"mode": "forecast_sources", "future_options": options.model_dump()},
        {"mode": "solar_windows"},
        {"mode": "solar_windows", "future_options": options.model_dump(), "cursor": "foreign"},
    ):
        result = await tool.run(arguments)
        assert result.data.error == "invalid_input"
