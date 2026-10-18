from datetime import UTC, datetime

import pytest

from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.pv_forecast import decode
from mcpserver.loxone.source_time import LOXONE_EPOCH_UNIX, loxone_time
from mcpserver.loxone.state_semantics import StateSemanticsResolver, decode_state_value


def companions(**overrides):
    at = datetime(2026, 10, 18, 10, tzinfo=UTC).timestamp() - LOXONE_EPOCH_UNIX
    return (
        dict(
            ready=1,
            errorInfo=0,
            timestamp=at,
            cycleFrom=at,
            cycleUntil=at + 3600,
            inputperiod=24,
        )
        | overrides
    )


@pytest.mark.parametrize("name", ["today", "tomorrow", "after", "period"])
def test_native_energy_and_time_axes_are_separate(name):
    result = decode(name, 12.5, companions())
    assert result["status"] == "available"
    assert result["energy_kwh"] == 12.5
    assert result["times"]["predicted_at"] == "2026-10-18T10:00:00Z"
    assert result["value_origin"] == "forecast"
    assert result["period_hours"] == (24 if name == "period" else None)


def test_real_unavailable_shape_does_not_become_negative_energy():
    result = decode("today", -1, companions(ready=0, errorInfo=2, timestamp=0))
    assert result["status"] == "unavailable"
    assert result["energy_kwh"] is None
    assert result["times"] is None
    assert decode("errorInfo", 2, {})["weather_service_error"] is True
    assert decode("errorInfo", 2, {})["internet_error"] is False


@pytest.mark.parametrize("name", ["ready", "errorInfo", "timestamp", "cycleFrom", "cycleUntil"])
def test_missing_current_companions_prevent_available_forecast(name):
    values = companions()
    values.pop(name)
    assert decode("today", 5, values)["status"] == "incomplete"


@pytest.mark.parametrize("overrides", [{"ready": 0}, {"errorInfo": 1}, {"errorInfo": 2}])
def test_unavailable_companions_block_positive_energy(overrides):
    assert decode("today", 5, companions(**overrides))["energy_kwh"] is None


@pytest.mark.parametrize("value", [-2, True, float("nan"), float("inf"), "12"])
def test_invalid_energy_is_not_accepted(value):
    with pytest.raises(ValueError):
        decode("today", value, companions())


@pytest.mark.parametrize("value", [-1, 0.5, True, float("inf"), 10**400])
def test_timestamp_bounds(value):
    with pytest.raises(ValueError):
        loxone_time(value)


def test_zero_time_and_unknown_error_bits_remain_explicit():
    assert decode("timestamp", 0, {})["at"] is None
    with pytest.raises(ValueError):
        decode("errorInfo", 4, {})
    assert decode("today", 1, companions(cycleUntil=1))["status"] == "incomplete"


def test_existing_state_readers_share_pvpf_decoder():
    control = Control("control", "not a role", "PvProductionForecast", None, None, None, ())
    structure = LoxoneStructure(LoxoneIdentity("reader", "serial"), "17.2", (), (), (control,))
    descriptor, value = StateSemanticsResolver().resolve(
        structure, control, "today", 5, companions()
    )
    raw_value, invalid = decode_state_value(structure, control, "today", 5, companions())
    assert descriptor.measurement_quantity == "energy"
    assert descriptor.measurement_role == "predicted_pv_energy"
    assert descriptor.unit == "kWh"
    assert descriptor.interpretation_status == "known"
    assert raw_value == value and invalid is False


def test_unknown_types_are_not_decoded_by_name():
    control = Control("control", "PV forecast", "InfoOnlyAnalog", None, None, None, ())
    structure = LoxoneStructure(LoxoneIdentity("reader", "serial"), "17.2", (), (), (control,))
    descriptor, value = StateSemanticsResolver().resolve(
        structure, control, "today", 5, companions()
    )
    assert descriptor.interpretation_status == "unknown"
    assert value is None


@pytest.mark.asyncio
async def test_compact_reader_uses_current_companions_once(monkeypatch):
    from dataclasses import replace

    from test_state_semantics import Runtime, read_tool

    from mcpserver.loxone.models import Freshness, StateRecord
    from mcpserver.tools import ControlReadTarget

    values = companions() | {"today": 5}
    c = Control(
        "control",
        "PV forecast",
        "PvProductionForecast",
        None,
        None,
        None,
        tuple((n, n) for n in values),
    )
    runtime = Runtime(c)
    runtime.records = {
        n: StateRecord(n, v, Freshness.CURRENT, 1_700_000_000) for n, v in values.items()
    }
    server, read = read_tool(monkeypatch, runtime)
    result = await read.fn([ControlReadTarget(control_uuid="control", state_names=["today"])], True)
    assert result.ok
    assert result.data.items[0].semantics[0].semantic_value["energy_kwh"] == 5
    assert len(runtime.reads) == len(set(runtime.reads)) == 7
    runtime.records["ready"] = replace(runtime.records["ready"], freshness=Freshness.STALE)
    result = await read.fn([ControlReadTarget(control_uuid="control", state_names=["today"])], True)
    assert result.data.items[0].semantics[0].semantic_value["energy_kwh"] is None
    described = await server._tool_manager.get_tool("loxone_describe_control").fn("control")
    assert described.ok
    metadata = described.data.capabilities.model.pv_forecast
    assert metadata.energy_unit == "kWh" and metadata.value_origin == "forecast"
    assert set(metadata.missing_states) == {"period", "tomorrow", "after"}
