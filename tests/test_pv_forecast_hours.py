from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from test_native_efm import ACTION, TARGET, access, fixture_runtime

import mcpserver.loxone.client as client_module
from mcpserver.loxone.client import LoxoneWebSocketSession
from mcpserver.loxone.models import Freshness
from mcpserver.loxone.pv_forecast_hours import PvForecastError, decode_forecast
from mcpserver.loxone.runtime import ControlOperationError, RuntimeSnapshot
from mcpserver.loxone.source_time import LOXONE_EPOCH_UNIX as LOXONE_EPOCH
from mcpserver.loxone.state_semantics import StateSemanticsResolver
from mcpserver.pv_forecast_runtime import read_pv_forecast

NOW = 1_792_320_000
STATES = {"ready": 1, "timestamp": NOW - LOXONE_EPOCH, "errorInfo": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("secure", [False, True])
async def test_transport_encryption_and_fixed_read_command(monkeypatch, secure):
    session = object.__new__(LoxoneWebSocketSession)
    session._websocket = session._encryptor = object()
    session._secure_transport = secure
    session._timeout, session._max_payload = 25, 1_000_000
    command = AsyncMock(return_value="{}")
    monkeypatch.setattr(client_module, "_websocket_command", command)
    await session.pv_forecast(TARGET)
    assert command.call_args.args[-1] == f"jdev/sps/io/{TARGET}/getForecasts"
    assert command.call_args.kwargs == {
        "encrypted": not secure,
        "timeout_seconds": 10,
        "max_payload_bytes": 32768,
    }
    with pytest.raises(ValueError):
        await session.pv_forecast("../other")
    assert command.await_count == 1


def decode(raw=None, states=None):
    return decode_forecast(
        raw if raw is not None else json.dumps({"tomorrow": [{"t": NOW + 3600, "v": 1.2}]}),
        STATES if states is None else states,
        control_uuid=TARGET,
        retrieved_at="2026-10-18T10:00:00+00:00",
        now=NOW,
    )


def test_hourly_energy_and_distinct_timestamp_epochs():
    result = decode()
    assert result.status == "available" and result.prediction_at == NOW
    assert result.hours[0].energy_wh == 1200
    assert result.hours[0].end - result.hours[0].start == 3600


@pytest.mark.parametrize(
    "states,status",
    [
        ({**STATES, "ready": 0}, "not_ready"),
        ({**STATES, "timestamp": 0}, "incomplete"),
        ({**STATES, "timestamp": 1.5}, "incomplete"),
        ({**STATES, "timestamp": 4_000_000_001}, "incomplete"),
        ({**STATES, "errorInfo": 4}, "incomplete"),
        ({**STATES, "timestamp": NOW - LOXONE_EPOCH - 10801}, "stale"),
        ({**STATES, "timestamp": NOW - LOXONE_EPOCH + 301}, "stale"),
        ({**STATES, "errorInfo": 2}, "incomplete"),
        ({}, "incomplete"),
    ],
)
def test_source_availability(states, status):
    assert decode(states=states).status == status


@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        '{"tomorrow":[{"t":1792323600,"v":-1}]}',
        '{"tomorrow":[],"tomorrow":[]}',
        '{"today":null}',
        '{"today":[{"t":true,"v":1}]}',
        '{"today":[{"t":1792323600,"v":NaN}]}',
        '{"today":[{"t":1792323600,"v":1},{"t":1792323600,"v":1}]}',
        '{"today":[{"t":1792323600,"v":1},{"t":1792323700,"v":1}]}',
        "x" * 32769,
        "\ud800",
    ],
    ids=lambda raw: str(len(raw)),
)
def test_invalid_source_never_becomes_usable_energy(raw):
    if raw == "{}":
        assert decode(raw).status == "incomplete"
    else:
        with pytest.raises(PvForecastError):
            decode(raw)


def test_hour_gaps_are_preserved():
    result = decode(json.dumps({"today": [{"t": NOW, "v": 0}, {"t": NOW + 7200, "v": 1}]}))
    assert len(result.hours) == 2 and result.hours[0].end < result.hours[1].start


def test_missing_error_status_is_not_complete_and_old_hour_is_rejected():
    states = {key: value for key, value in STATES.items() if key != "errorInfo"}
    assert not decode(states=states).field_delivery_complete
    with pytest.raises(PvForecastError, match="outside_horizon"):
        decode('{"today":[{"t":1,"v":1}]}')


def test_unavailable_aggregate_is_not_negative_energy():
    result = decode(states={**STATES, "today": -1, "tomorrow": 1.25})
    assert result.aggregates_kwh["today"] is None
    assert result.aggregates_kwh["tomorrow"] == 1.25


@pytest.mark.parametrize("value", [-2, -0.5, -1, 0, 1.25])
def test_aggregate_semantics_only_accept_documented_negative_sentinel(value):
    _, structure, _, _ = fixture_runtime()
    control = replace(structure.controls[0], control_type="PvProductionForecast")
    metadata, decoded = StateSemanticsResolver().resolve(structure, control, "today", value, {})
    if value < 0 and value != -1:
        assert metadata.interpretation_status == "invalid" and decoded is None
    elif value == -1:
        assert metadata.interpretation_status == "known"
    else:
        assert metadata.interpretation_status == "partial"
        assert decoded["energy_kwh"] is None


@pytest.mark.asyncio
async def test_invalid_target_returns_stable_error():
    runtime, _, session, _ = fixture_runtime()
    with pytest.raises(ControlOperationError) as exc:
        await read_pv_forecast(runtime, access(), "invalid")
    assert exc.value.code == "invalid_input"
    session.native_efm_result.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke", [False, True])
@pytest.mark.parametrize(
    "ready,freshness,calls",
    [(0, Freshness.CURRENT, 0), (1, Freshness.CURRENT, 1), (0, Freshness.STALE, 1)],
)
async def test_native_read_once_with_visibility_recheck_and_cleanup(
    revoke, ready, freshness, calls
):
    runtime, structure, session, token = fixture_runtime()
    control = replace(
        structure.controls[0],
        control_type="PvProductionForecast",
        state_uuids=(("ready", "ready"),),
    )
    structure = replace(structure, controls=(control,), caller_is_admin=False)

    @asynccontextmanager
    async def snapshot_context(_access):
        yield RuntimeSnapshot("family", structure, True)

    runtime.snapshot_context = snapshot_context
    runtime.token_health = SimpleNamespace(record_successful_authentication=Mock())
    runtime.cache = SimpleNamespace(
        get=Mock(return_value=SimpleNamespace(value=ready, freshness=freshness))
    )
    session.pv_forecast = AsyncMock(return_value="{}")
    session.load_structure = AsyncMock(
        return_value=replace(structure, controls=()) if revoke else structure
    )
    if revoke:
        with pytest.raises(ControlOperationError, match="not accessible"):
            await read_pv_forecast(runtime, access(), TARGET)
    else:
        _, _, result = await read_pv_forecast(runtime, access(), TARGET)
        assert result.status == (
            "not_ready" if ready == 0 and freshness is Freshness.CURRENT else "incomplete"
        )
    assert session.pv_forecast.await_count == calls
    if calls:
        session.pv_forecast.assert_awaited_once_with(ACTION)
    session.close.assert_awaited_once()
    token.destroy.assert_called_once()
    runtime.token_health.record_successful_authentication.assert_called_once_with("family")
