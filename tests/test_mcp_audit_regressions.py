"""Actual SDK-boundary regressions for the five command-audit findings (#597)."""

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcpserver import installation_profile_tools, load_planning_tools, tools
from mcpserver.availability import AvailabilityPhase, AvailabilityReason
from mcpserver.loxone.models import (
    Control,
    Freshness,
    LoxoneIdentity,
    LoxoneStructure,
    Room,
    StateRecord,
)
from mcpserver.loxone.runtime import ControlOperationError, RuntimeSnapshot, RuntimeUnavailable


@pytest.fixture
def access(monkeypatch: pytest.MonkeyPatch) -> Any:
    value = SimpleNamespace(
        client_id="client",
        identity_id="user",
        family_id="family",
        miniserver_id="server",
        scopes=["loxone:read", "loxone:control"],
    )
    monkeypatch.setattr(tools, "_access", lambda: value)
    monkeypatch.setattr(load_planning_tools, "_access", lambda: value)
    return value


class StateRuntime:
    connected = True
    text = "safe"
    dispatched = 0
    control = Control("control", "Text", "TextState", "room", None, None, (("text", "state"),))
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "server"),
        last_modified="1",
        controls=(control,),
        rooms=(Room("room", "Test"),),
        categories=(),
    )

    @asynccontextmanager
    async def call_slot(self, _access: Any) -> Any:
        yield

    async def snapshot(self, _access: Any, **_kwargs: Any) -> RuntimeSnapshot:
        return RuntimeSnapshot("family", self.structure, self.connected)

    def state(self, _snapshot: Any, uuid: str) -> StateRecord:
        return StateRecord(uuid, self.text, Freshness.CURRENT, 1.0)

    async def operate_control(self, *args: Any, **kwargs: Any) -> Any:
        self.dispatched += 1
        return SimpleNamespace(
            control_uuid="control",
            control_type="Slider",
            action="set_value",
            accepted=True,
            confirmed=True,
            observed_state="confirmed",
            observed_values={"value": kwargs.get("value")},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        (field, value)
        for field in (
            "level",
            "position",
            "slat_position",
            "hue",
            "saturation",
            "brightness",
            "value",
            "kelvin",
            "duration_seconds",
        )
        for value in (True, "1", float("nan"), float("inf"))
    ]
    + [
        ("level", -1),
        ("level", 101),
        ("hue", 361),
        ("kelvin", 999),
        ("kelvin", 20001),
        ("kelvin", 1200.5),
        ("duration_seconds", 0),
        ("duration_seconds", 86401),
        ("duration_seconds", 1.5),
    ],
)
async def test_numeric_arguments_rejected_before_dispatch(
    access: Any, field: str, value: Any
) -> None:
    runtime = StateRuntime()
    server = FastMCP("strict-control")
    tools.register_control_tool(server, runtime)  # type: ignore[arg-type]
    with pytest.raises(ToolError):
        await server._tool_manager.call_tool(
            "loxone_operate_control",
            {"control_uuid": "control", "action": "set_value", field: value},
        )
    assert runtime.dispatched == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [0, 1, 1.5])
async def test_real_json_numbers_reach_runtime(access: Any, value: float) -> None:
    runtime = StateRuntime()
    server = FastMCP("strict-control-valid")
    tools.register_control_tool(server, runtime)  # type: ignore[arg-type]
    result = await server._tool_manager.call_tool(
        "loxone_operate_control", {"control_uuid": "control", "action": "set_value", "value": value}
    )
    assert result.ok
    assert runtime.dispatched == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args",
    [
        ("loxone_get_states", {"state_uuids": ["state"]}),
        ("loxone_get_state_semantics", {"control_uuid": "control"}),
        ("loxone_get_room_snapshot", {"room_uuid": "room"}),
    ],
)
async def test_utf8_state_envelope_guard(access: Any, name: str, args: dict[str, Any]) -> None:
    runtime = StateRuntime()
    server = FastMCP("bounded-state")
    tools.register_read_tools(server, runtime)  # type: ignore[arg-type]
    runtime.text = "ä" * 30000
    result = await server._tool_manager.call_tool(name, args)
    assert result.ok and len(result.model_dump_json().encode("utf-8")) <= 65536
    runtime.text = "ä" * 35000
    result = await server._tool_manager.call_tool(name, args)
    assert not result.ok and result.data.error == "response_too_large"
    assert runtime.text == "ä" * 35000
    assert len(result.model_dump_json().encode("utf-8")) < 1024


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args",
    [
        ("loxone_list_rooms", {}),
        ("loxone_list_categories", {}),
        ("loxone_list_global_metadata", {}),
        ("loxone_find_controls", {}),
        *[
            ("loxone_describe_control", {"control_uuid": "control", "view": view})
            for view in ("full", "state_refs", "operation_targets", "history_targets")
        ],
        ("loxone_get_room_snapshot", {"room_uuid": "room"}),
    ],
)
async def test_disconnected_metadata_is_stale(access: Any, name: str, args: dict[str, Any]) -> None:
    runtime = StateRuntime()
    server = FastMCP("metadata-freshness")
    tools.register_read_tools(server, runtime)  # type: ignore[arg-type]
    for connected in (True, False):
        runtime.connected = connected
        result = await server._tool_manager.call_tool(name, args)
        assert result.ok
        assert result.stale is (not connected)


class EventRuntime:
    allowed = True
    calls = 0

    def __init__(self) -> None:
        self.events = [
            {
                "timestamp": f"2026-10-26T10:00:0{i}Z",
                "component": "mcpserver.tools",
                "severity": "info",
                "outcome": str(i),
            }
            for i in range(4)
        ]

    async def service_events(self, _access: Any, **kwargs: Any) -> list[dict[str, str]]:
        self.calls += 1
        if not self.allowed:
            raise PermissionError
        return list(self.events)


@pytest.mark.asyncio
async def test_event_pages_survive_append_rotation_and_bind_caller(access: Any) -> None:
    runtime = EventRuntime()
    server = FastMCP("event-pages")
    tools.register_loxberry_read_tools(server, runtime)  # type: ignore[arg-type]

    async def call(**kwargs: Any) -> Any:
        return await server._tool_manager.call_tool("loxberry_list_service_events", kwargs)

    first = await call(limit=2)
    assert [row.outcome for row in first.data.events] == ["2", "3"]
    cursor = first.data.next_cursor
    runtime.events = [dict(runtime.events[-1], outcome="new")]
    second = await call(limit=2, cursor=cursor)
    assert [row.outcome for row in second.data.events] == ["0", "1"]
    assert second.data.next_cursor is None
    for attr in ("client_id", "identity_id", "family_id", "miniserver_id"):
        old = getattr(access, attr)
        setattr(access, attr, "other")
        assert (await call(cursor=cursor)).data.error == "invalid_input"
        setattr(access, attr, old)
    assert (await call(cursor=cursor, severity="error")).data.error == "invalid_input"
    runtime.allowed = False
    assert (await call(cursor=cursor)).data.error == "permission_denied"
    assert runtime.calls == 8


def test_event_snapshot_expiry_and_memory_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 100.0
    monkeypatch.setattr(tools.time, "monotonic", lambda: now)
    pages = tools._ServiceEventPages()
    events = [{"outcome": "old"}, {"outcome": "new"}]
    cursor = pages.page("caller", events, None, 1)["next_cursor"]
    events[0]["outcome"] = "mutated"
    assert pages.page("caller", events, cursor, 1)["events"] == [{"outcome": "old"}]
    now += 120
    with pytest.raises(ValueError, match="expired"):
        pages.page("caller", events, cursor, 1)
    for _ in range(30):
        pages.page("caller", events, None, 1)
    assert len(pages._pages) == 16
    with pytest.raises(tools.DiagnosticsUnavailable):
        pages.page("caller", [{"outcome": "x" * (4 * 1024 * 1024)}], None, 1)


@pytest.mark.asyncio
async def test_real_log_over_100_records_is_fully_pageable(access: Any, tmp_path: Path) -> None:
    path = tmp_path / "log/plugins/mcpserver/service.log"
    path.parent.mkdir(parents=True)
    path.write_text(
        "".join(
            f"2026-10-26T10:00:00Z component=mcpserver.tools severity=INFO outcome=event{i}\n"
            for i in range(201)
        ),
        encoding="utf-8",
    )
    diagnostics = tools.LoxBerryDiagnostics(tmp_path.resolve())

    class Runtime:
        async def service_events(self, _access: Any, **kwargs: Any) -> Any:
            return diagnostics.service_events(**kwargs)

    server = FastMCP("large-real-log")
    tools.register_loxberry_read_tools(server, Runtime())  # type: ignore[arg-type]
    cursor = None
    results = []
    while True:
        page = await server._tool_manager.call_tool(
            "loxberry_list_service_events", {"cursor": cursor, "limit": 100}
        )
        assert page.ok
        results.extend(row.outcome for row in page.data.events)
        cursor = page.data.next_cursor
        if cursor is None:
            break
        path.write_text("", encoding="utf-8")  # Simulate rotation between pages.
    assert len(results) == len(set(results)) == 201


def test_event_cursor_eviction_honors_shared_byte_budget() -> None:
    pages = tools._ServiceEventPages()
    events = [{"outcome": "x" * 1500000}, {"outcome": "last"}]
    first = pages.page("caller", events, None, 1)["next_cursor"]
    for _ in range(3):
        pages.page("caller", events, None, 1)
    assert len(pages._pages) == 2
    assert sum(row[4] for row in pages._pages.values()) <= 4 * 1024 * 1024
    with pytest.raises(ValueError):
        pages.page("caller", events, first, 1)


@pytest.mark.asyncio
async def test_weather_preserves_adapter_trace(access: Any) -> None:
    traces = []

    class Forecast:
        async def read(self, *args: Any, trace_id: str, **kwargs: Any) -> Any:
            traces.append(trace_id)
            raise unavailable()

    server = FastMCP("weather-diagnostic-trace")
    tools.register_read_tools(server, StateRuntime(), solar_forecast_runtime=Forecast())  # type: ignore[arg-type]
    result = await server._tool_manager.call_tool(
        "loxone_get_weather", {"mode": "forecast_sources"}
    )
    assert result.trace_id == traces[0]
    assert result.data.diagnostic_code == "structure_refresh_protocol"


def unavailable() -> RuntimeUnavailable:
    return RuntimeUnavailable(
        "private untrusted exception text",
        reason=AvailabilityReason.REFRESH_PROTOCOL,
        phase=AvailabilityPhase.LOAD,
    )


@pytest.mark.asyncio
async def test_typed_diagnostics_survive_profile_plan_and_mutation(access: Any) -> None:
    class Runtime:
        @asynccontextmanager
        async def snapshot_context(self, *args: Any, **kwargs: Any) -> Any:
            raise unavailable()
            yield  # pragma: no cover

        async def add_event_history_source(self, *args: Any, **kwargs: Any) -> Any:
            raise ControlOperationError(
                "temporarily_unavailable", "safe", trace_id="source-trace"
            ) from unavailable()

        async def operate_control(self, *args: Any, **kwargs: Any) -> Any:
            raise ControlOperationError(
                "temporarily_unavailable", "safe", trace_id="control-trace"
            ) from unavailable()

    async def fail(*args: Any, **kwargs: Any) -> Any:
        raise unavailable()

    runtime = Runtime()
    server = FastMCP("diagnostic-adapters")
    installation_profile_tools.register_profile_read_tool(server, runtime, Path("unused"))  # type: ignore[arg-type]
    tools.register_loxberry_operate_tool(server, runtime)  # type: ignore[arg-type]
    tools.register_control_tool(server, runtime)  # type: ignore[arg-type]
    original = load_planning_tools.calculate_load_plan
    load_planning_tools.calculate_load_plan = fail
    try:
        load_planning_tools.register_load_planning_tool(server, runtime, None, Path("unused"))  # type: ignore[arg-type]
        calls = [
            ("loxone_get_installation_profile", {}),
            (
                "loxberry_add_event_history_source",
                {
                    "control_uuid": "00000000-0000-0000-0000000000000000",
                    "state_uuid": "00000000-0000-0000-0000000000000000",
                },
            ),
            ("loxone_operate_control", {"control_uuid": "control", "action": "on"}),
            (
                "loxone_plan_loads",
                {
                    "options": {
                        "forecast_control_uuid": "synthetic",
                        "consumer_binding_ids": ["synthetic"],
                        "start": "2026-10-26T08:00:00+01:00",
                        "end": "2026-10-26T18:00:00+01:00",
                        "timezone": "Europe/Berlin",
                        "baseload": {"origin": "user_estimate", "constant_w": 0},
                        "storage_reserve": {"origin": "user_estimate", "constant_w": 0},
                    }
                },
            ),
        ]
        for name, args in calls:
            result = await server._tool_manager.call_tool(name, args)
            assert not result.ok
            assert result.data.diagnostic_code == "structure_refresh_protocol"
            assert result.data.availability_phase == AvailabilityPhase.LOAD
            assert "private" not in result.model_dump_json()
            if name == "loxone_operate_control":
                assert result.trace_id == "control-trace"
            if name == "loxberry_add_event_history_source":
                assert result.trace_id == "source-trace"
    finally:
        load_planning_tools.calculate_load_plan = original


def test_uncertain_write_never_reclassified_as_availability(access: Any) -> None:
    try:
        raise ControlOperationError(
            "write_outcome_uncertain", "Do not retry", trace_id="uncertain"
        ) from unavailable()
    except ControlOperationError as exc:
        result = tools._control_envelope(access, "control", "on", error=exc)
    assert result.data.error == "write_outcome_uncertain"
    assert result.data.diagnostic_code is None
    assert result.trace_id == "uncertain"
