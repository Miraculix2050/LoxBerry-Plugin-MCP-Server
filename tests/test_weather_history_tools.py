"""History scopes, current source authorization, cursor scope and worker publication."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP

from mcpserver.auth.provider import HISTORY_SCOPE, READ_SCOPE, StoredAccessToken
from mcpserver.config import PluginConfig
from mcpserver.installation_profile import installation_identity
from mcpserver.loxone.endpoint import MiniserverEndpoint
from mcpserver.loxone.event_history import EventHistoryStore
from mcpserver.loxone.models import GlobalMetadata, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import ControlOperationError, LoxoneRuntime, RuntimeAuthorizationError
from mcpserver.loxone.weather_history import (
    LOXONE_EPOCH,
    WeatherHistory,
    WeatherHistorySource,
    source_fingerprint,
)
from mcpserver.tools import _CursorCodec, register_read_tools
from mcpserver.weather_history_tools import WeatherHistoryOptions, WeatherHistoryReader

UUID = "00000001-0000-0000-0000000000000001"


def access(scopes=None, family="family"):
    return StoredAccessToken(
        token="opaque",
        client_id="synthetic",
        scopes=scopes if scopes is not None else [READ_SCOPE, HISTORY_SCOPE],
        expires_at=2_000_000_000,
        resource="http://synthetic.local/mcp",
        subject="identity",
        claims={},
        family_id=family,
        identity_id="identity",
        miniserver_id="miniserver",
    )


@pytest.fixture
def context(tmp_path):
    source = WeatherHistorySource(UUID, "forecast", ("solar_radiation",))
    structure = LoxoneStructure(
        LoxoneIdentity("caller", "serial"),
        "1",
        (),
        (),
        (),
        global_metadata=(GlobalMetadata("weather_state", "forecast", "Forecast", state_uuid=UUID),),
    )
    validator = AsyncMock(return_value=True)
    runtime = LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        SimpleNamespace(),
        history_enabled=True,
        validate_access=validator,
        history_requests_per_minute=1000,
    )
    runtime.snapshot = AsyncMock(return_value=SimpleNamespace(structure=structure))
    config = PluginConfig(
        loxone_endpoint=runtime.endpoint.origin,
        loxone_history_enabled=True,
        weather_history_sources=(source,),
    )
    config_store = SimpleNamespace(load=lambda: config)
    path = tmp_path / "state-events.sqlite3"
    store = EventHistoryStore(path, retention_days=90, maximum_mib=16)
    store.initialize()
    weather = WeatherHistory(store)
    now = time.time()
    fp = source_fingerprint(
        source, structure, installation_identity(runtime.endpoint.origin, structure)
    )
    capture = weather.begin(source, fp, now - 10)
    weather.record(
        capture,
        source,
        {
            "last_update": int(now - LOXONE_EPOCH),
            "entries": [
                {"timestamp": int(now - LOXONE_EPOCH) + 3600 * i, "solar_radiation": i}
                for i in range(5)
            ],
        },
        now - 1,
    )
    options = WeatherHistoryOptions(
        state_uuid=UUID,
        stored_mode="forecast",
        start=datetime.fromtimestamp(now - 20, UTC).isoformat(),
        end=datetime.fromtimestamp(now, UTC).isoformat(),
    )
    return (
        runtime,
        validator,
        config_store,
        WeatherHistoryReader(runtime, config_store, path),
        options,
        store,
    )


@pytest.mark.asyncio
async def test_read_fresh_visibility_raw_opt_in_and_bound_cursor(context):
    runtime, validator, _config, reader, options, _store = context
    codec = _CursorCodec()
    first = await reader.read(access(), options, None, 2, codec)
    assert first.mode == "history" and first.unit is None
    assert len(first.items) == 2 and all(p.fields is None for p in first.items)
    assert not first.recording_enabled  # Retained history remains readable when recording is off.
    runtime.snapshot.assert_awaited_with(access(), fresh_visibility=True)
    assert validator.await_count >= 2
    second = await reader.read(access(), options, first.next_cursor, 2, codec)
    assert not ({p.point_at for p in first.items} & {p.point_at for p in second.items})
    for changed_access, changed_options in [
        (access(family="other"), options),
        (access(), options.model_copy(update={"include_raw": True})),
    ]:
        with pytest.raises(ValueError, match="cursor"):
            await reader.read(changed_access, changed_options, first.next_cursor, 2, codec)
    raw = await reader.read(
        access(), options.model_copy(update={"include_raw": True}), None, 96, codec
    )
    assert all(set(p.fields) == {"solar_radiation"} for p in raw.items)


@pytest.mark.asyncio
@pytest.mark.parametrize("scopes", [[READ_SCOPE], [HISTORY_SCOPE], []])
async def test_history_scope_gate_before_source_or_sql(context, scopes):
    runtime, _v, _c, reader, options, _s = context
    with pytest.raises(ControlOperationError, match="history"):
        await reader.read(access(scopes), options, None, 2, _CursorCodec())
    runtime.snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_current_exact_weather_visibility_no_control_fallback(context):
    runtime, _v, _c, reader, options, _s = context
    runtime.snapshot.return_value = SimpleNamespace(
        structure=LoxoneStructure(LoxoneIdentity("caller", "serial"), "2", (), (), ())
    )
    with pytest.raises(ControlOperationError, match="visible"):
        await reader.read(access(), options, None, 2, _CursorCodec())


@pytest.mark.asyncio
async def test_revocation_during_worker_blocks_publication(context, monkeypatch):
    runtime, validator, _c, reader, options, _s = context
    original = WeatherHistory.page

    def revoked(*args, **kwargs):
        page = original(*args, **kwargs)
        validator.return_value = False
        return page

    monkeypatch.setattr(WeatherHistory, "page", revoked)
    with pytest.raises(RuntimeAuthorizationError):
        await reader.read(access(), options, None, 2, _CursorCodec())
    assert runtime._parallel._value == 4


@pytest.mark.asyncio
async def test_source_removed_during_worker_blocks_publication(context, monkeypatch):
    _r, _v, config_store, reader, options, _s = context
    original = WeatherHistory.page

    def removed(*args, **kwargs):
        page = original(*args, **kwargs)
        config_store.load = lambda: PluginConfig(loxone_history_enabled=True)
        return page

    monkeypatch.setattr(WeatherHistory, "page", removed)
    with pytest.raises(ControlOperationError, match="changed"):
        await reader.read(access(), options, None, 2, _CursorCodec())


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["endpoint", "retention"])
async def test_policy_change_during_worker_blocks_publication(context, monkeypatch, change):
    from dataclasses import replace

    _runtime, _validator, config_store, reader, options, _source = context
    original_config = config_store.load()
    original_page = WeatherHistory.page

    def changed(*args, **kwargs):
        page = original_page(*args, **kwargs)
        replacement = replace(
            original_config,
            **(
                {"loxone_endpoint": "http://192.168.1.11"}
                if change == "endpoint"
                else {"event_history_retention_days": 1}
            ),
        )
        config_store.load = lambda: replacement
        return page

    monkeypatch.setattr(WeatherHistory, "page", changed)
    with pytest.raises(ControlOperationError, match="configuration changed"):
        await reader.read(access(), options, None, 2, _CursorCodec())


@pytest.mark.asyncio
async def test_stale_runtime_endpoint_rejected_before_snapshot(context):
    from dataclasses import replace

    runtime, _v, config_store, reader, options, _s = context
    config = replace(config_store.load(), loxone_endpoint="http://192.168.1.11")
    config_store.load = lambda: config
    with pytest.raises(ControlOperationError, match="endpoint configuration changed"):
        await reader.read(access(), options, None, 2, _CursorCodec())
    runtime.snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_admission_limit_does_not_deadlock(context):
    runtime, _v, _c, reader, options, _s = context
    runtime._parallel = asyncio.Semaphore(1)
    result = await asyncio.wait_for(reader.read(access(), options, None, 2, _CursorCodec()), 2)
    assert len(result.items) == 2
    assert runtime._parallel._value == 1


@pytest.mark.asyncio
async def test_whole_weather_history_envelope_size_uses_released_error(context, monkeypatch):
    import mcpserver.tools as tools

    runtime, _v, _c, reader, options, _s = context
    result = await reader.read(access(), options, None, 2, _CursorCodec())
    reader.read = AsyncMock(return_value=result.model_copy(update={"limitations": ["x" * 65536]}))
    monkeypatch.setattr(tools, "_access", access)
    server = FastMCP("bounded-weather")
    register_read_tools(server, runtime, weather_history_reader=reader)
    envelope = await server._tool_manager.get_tool("loxone_get_weather").fn(
        mode="history", history_options=options
    )
    assert not envelope.ok and envelope.data.error == "response_too_large"


@pytest.mark.asyncio
async def test_schema_is_additive_and_legacy_does_not_touch_reader(context, monkeypatch):
    import mcpserver.tools as tools

    runtime, _v, _c, reader, _o, _s = context
    called = AsyncMock(side_effect=AssertionError("legacy must not read local history"))
    reader.read = called
    server = FastMCP("weather-contract")
    register_read_tools(server, runtime, weather_history_reader=reader)
    tool = server._tool_manager.get_tool("loxone_get_weather")
    schema = next(
        t for t in await server.list_tools() if t.name == "loxone_get_weather"
    ).inputSchema
    assert schema["properties"]["mode"]["enum"] == ["actual", "forecast", "history"]
    assert "history_options" in schema["properties"]
    monkeypatch.setattr(
        tools, "_snapshot", AsyncMock(return_value=(access(), runtime.snapshot.return_value))
    )
    result = await tool.fn(mode="actual")
    assert not result.ok and result.data.error == "not_found"
    called.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancelled_worker_retains_admission_until_done(context, monkeypatch):
    import threading

    runtime, _v, _c, reader, options, _s = context
    started = threading.Event()
    finished = threading.Event()
    original = WeatherHistory.page

    def wait(*args, **kwargs):
        started.set()
        assert finished.wait(2)
        return original(*args, **kwargs)

    monkeypatch.setattr(WeatherHistory, "page", wait)
    task = asyncio.create_task(reader.read(access(), options, None, 2, _CursorCodec()))
    await asyncio.to_thread(started.wait, 2)
    task.cancel()
    await asyncio.sleep(0.01)
    assert runtime._parallel._value == 3  # The existing history admission remains held.
    finished.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime._parallel._value == 4
