from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

import mcpserver.tools as tools_module
from mcpserver.auth.provider import (
    CONTROL_SCOPE,
    HISTORY_SCOPE,
    LOXBERRY_OPERATE_SCOPE,
    LOXBERRY_READ_SCOPE,
    READ_SCOPE,
    StoredAccessToken,
)
from mcpserver.config import PluginConfig
from mcpserver.loxone.models import (
    Control,
    Freshness,
    GlobalMetadata,
    LoxoneIdentity,
    LoxoneStructure,
    NamedGroup,
    NamedOption,
    Room,
    StateRecord,
    StatisticSeries,
    StatusMonitorInput,
    StatusMonitorStatus,
    WeatherMetadata,
    WindowMonitorItem,
)
from mcpserver.loxone.runtime import ControlHistoryEntry, RuntimeSnapshot
from mcpserver.loxone.statistics import StatisticPoint
from mcpserver.skill_delivery import read_skill_markdown
from mcpserver.tools import (
    LoxBerryOperateRuntime,
    LoxBerryReadRuntime,
    SystemStatusEnvelope,
    _CursorCodec,
    _error,
    _page,
    _result,
    _rfc3339,
    register_control_tool,
    register_history_tools,
    register_loxberry_operate_tool,
    register_loxberry_read_tools,
    register_read_tools,
    register_skill_tool,
)


def _loxberry_access(*scopes: str) -> StoredAccessToken:
    return StoredAccessToken(
        token="opaque",
        client_id="client",
        scopes=list(scopes),
        expires_at=2_000_000_000,
        resource="https://loxberry.local/plugins/mcpserver/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="miniserver",
    )


def test_loxberry_runtime_requires_live_binding_and_enforces_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConfigStore:
        config = PluginConfig(loxberry_read_enabled=True, loxberry_requests_per_minute=1)

        def load(self) -> PluginConfig:
            return self.config

    class AuthStore:
        def pseudonym(self, *parts: str) -> str:
            assert parts[0] == "loxberry-read-binding-v1"
            return "binding"

    config_store = ConfigStore()
    config_store.config = PluginConfig(
        loxberry_read_enabled=True,
        loxberry_requests_per_minute=1,
        loxberry_read_bindings=("binding",),
    )
    runtime = LoxBerryReadRuntime(object(), config_store, AuthStore())  # type: ignore[arg-type]
    access = _loxberry_access(READ_SCOPE, LOXBERRY_READ_SCOPE)
    monkeypatch.setattr(tools_module.time, "monotonic", lambda: 100.0)

    assert runtime._allowed(access).loxberry_read_enabled is True
    with pytest.raises(tools_module.DiagnosticsUnavailable):
        runtime._allowed(access)
    with pytest.raises(PermissionError):
        runtime._allowed(_loxberry_access(READ_SCOPE))
    config_store.config = PluginConfig(
        loxberry_read_enabled=False, loxberry_read_bindings=("binding",)
    )
    with pytest.raises(PermissionError):
        runtime._allowed(access)


def test_loxberry_tool_contracts_have_closed_output_schemas() -> None:
    class Runtime:
        async def system_status(self, access: object) -> dict[str, object]:
            return {}

        async def plugin_status(self, access: object) -> dict[str, object]:
            return {}

        async def service_health(self, access: object) -> dict[str, object]:
            return {}

    server = FastMCP("loxberry-contract")
    register_loxberry_read_tools(server, Runtime())  # type: ignore[arg-type]
    published = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(published) == {
        "loxberry_get_system_status",
        "loxberry_get_plugin_status",
        "loxberry_get_service_health",
        "loxberry_list_service_events",
    }
    for name, tool in published.items():
        assert set(tool.parameters["properties"]) == (
            {"limit"} if name == "loxberry_list_service_events" else set()
        )
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.openWorldHint is False
        assert tool.output_schema["additionalProperties"] is False
        data_names = {
            item["$ref"].rsplit("/", 1)[-1]
            for item in tool.output_schema["properties"]["data"]["anyOf"]
        }
        assert all(
            tool.output_schema["$defs"][name]["additionalProperties"] is False
            for name in data_names
        )


def test_read_results_and_expected_errors_are_debug_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="mcpserver.tools")

    _result(
        SystemStatusEnvelope,
        {
            "reachable": True,
            "miniserver_serial": "masked",
            "structure_last_modified": "",
            "cache_freshness": "current",
            "structure_generation": 1,
        },
    )
    _error(SystemStatusEnvelope, "invalid_input", "invalid")

    assert [record.levelno for record in caplog.records] == [logging.DEBUG, logging.DEBUG]


def test_repeated_runtime_warning_is_suppressed(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools_module._ERROR_LAST.clear()
    monkeypatch.setattr(tools_module.time, "monotonic", lambda: 100.0)
    caplog.set_level(logging.WARNING, logger="mcpserver.tools")

    _error(SystemStatusEnvelope, "temporarily_unavailable", "unavailable")
    _error(SystemStatusEnvelope, "temporarily_unavailable", "unavailable")

    assert len(caplog.records) == 1


def test_opaque_cursor_paginates_without_exposing_offset() -> None:
    codec = _CursorCodec()
    first = _page(codec, "rooms", list(range(75)), None, 50)

    assert first["items"] == list(range(50))
    assert isinstance(first["next_cursor"], str)
    assert not first["next_cursor"].startswith("50")
    second = _page(codec, "rooms", list(range(75)), first["next_cursor"], 50)
    assert second == {"items": list(range(50, 75)), "next_cursor": None}


def test_cursor_cannot_cross_scope_or_be_modified() -> None:
    codec = _CursorCodec()
    cursor = codec.encode("rooms", 2)

    with pytest.raises(ValueError, match="cursor is invalid"):
        codec.decode("categories", cursor)
    with pytest.raises(ValueError, match="cursor is invalid"):
        codec.decode("rooms", cursor[:-1] + ("A" if cursor[-1] != "A" else "B"))


def test_rfc3339_rejects_timezone_normalization_overflow() -> None:
    with pytest.raises(ValueError, match="timestamp must be RFC 3339"):
        _rfc3339("9999-12-31T23:59:59-23:59")


@pytest.mark.asyncio
async def test_statistics_rounds_fractional_start_upward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: tuple[int, int] | None = None

    class Runtime:
        async def get_statistics(
            self,
            _access: object,
            _control: str,
            _series: str,
            start: int,
            end: int,
            _granularity: str,
        ) -> tuple[object, StatisticSeries, tuple[object, ...]]:
            nonlocal observed
            observed = (start, end)
            return (
                object(),
                StatisticSeries("series", "statistic_v2", "group", "output", "Series", ""),
                (),
            )

    server = FastMCP("statistics-fractional-start")
    register_history_tools(server, Runtime())  # type: ignore[arg-type]
    monkeypatch.setattr(
        tools_module, "_access", lambda: _loxberry_access(READ_SCOPE, HISTORY_SCOPE)
    )
    result = await server._tool_manager.call_tool(
        "loxone_get_statistics",
        {
            "control_uuid": "control",
            "series_id": "series",
            "start": "2026-01-01T00:00:00.500Z",
            "end": "2026-01-01T00:00:01.500Z",
            "granularity": "raw",
        },
    )

    assert result.ok is True
    assert observed == (
        int(datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC).timestamp()),
        int(datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC).timestamp()),
    )


@pytest.mark.asyncio
async def test_history_cursor_uses_a_stable_entry_anchor(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = tuple(ControlHistoryEntry(index, str(index), "", "", ()) for index in range(75))
    calls = 0

    class Runtime:
        async def get_control_history(
            self, _access: object, _control: str
        ) -> tuple[object, tuple[ControlHistoryEntry, ...]]:
            nonlocal calls
            calls += 1
            return (
                object(),
                entries if calls == 1 else (ControlHistoryEntry(75, "new", "", "", ()), *entries),
            )

    server = FastMCP("history-snapshot")
    register_history_tools(server, Runtime())  # type: ignore[arg-type]
    monkeypatch.setattr(
        tools_module, "_access", lambda: _loxberry_access(READ_SCOPE, HISTORY_SCOPE)
    )

    first = await server._tool_manager.call_tool(
        "loxone_get_control_history", {"control_uuid": "control", "limit": 50}
    )
    second = await server._tool_manager.call_tool(
        "loxone_get_control_history",
        {"control_uuid": "control", "cursor": first.data.next_cursor, "limit": 50},
    )

    assert calls == 2
    assert [entry.what for entry in first.data.entries] == [
        str(index) for index in range(74, 24, -1)
    ]
    assert [entry.what for entry in second.data.entries] == [
        str(index) for index in range(24, -1, -1)
    ]
    assert second.data.next_cursor is None


@pytest.mark.asyncio
async def test_history_cursor_preserves_identical_entries_across_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = tuple(ControlHistoryEntry(100, "same", "", "", ()) for _ in range(51))

    class Runtime:
        async def get_control_history(
            self, _access: object, _control: str
        ) -> tuple[object, tuple[ControlHistoryEntry, ...]]:
            return object(), entries

    server = FastMCP("history-identical-entries")
    register_history_tools(server, Runtime())  # type: ignore[arg-type]
    monkeypatch.setattr(
        tools_module, "_access", lambda: _loxberry_access(READ_SCOPE, HISTORY_SCOPE)
    )

    first = await server._tool_manager.call_tool(
        "loxone_get_control_history", {"control_uuid": "control", "limit": 50}
    )
    second = await server._tool_manager.call_tool(
        "loxone_get_control_history",
        {"control_uuid": "control", "cursor": first.data.next_cursor, "limit": 50},
    )

    assert len(first.data.entries) == 50
    assert len(second.data.entries) == 1
    assert second.data.next_cursor is None


@pytest.mark.asyncio
async def test_statistics_cursor_uses_a_timestamp_anchor(monkeypatch: pytest.MonkeyPatch) -> None:
    points = tuple(StatisticPoint(index, float(index)) for index in range(1, 4))
    calls = 0

    class Runtime:
        async def get_statistics(
            self, *_: object
        ) -> tuple[object, StatisticSeries, tuple[StatisticPoint, ...]]:
            nonlocal calls
            calls += 1
            values = points if calls == 1 else (StatisticPoint(0, 0.0), *points)
            return (
                object(),
                StatisticSeries("series", "statistic_v2", "group", "output", "Series", ""),
                values,
            )

    server = FastMCP("statistics-anchor")
    register_history_tools(server, Runtime())  # type: ignore[arg-type]
    monkeypatch.setattr(
        tools_module, "_access", lambda: _loxberry_access(READ_SCOPE, HISTORY_SCOPE)
    )
    arguments = {
        "control_uuid": "control",
        "series_id": "series",
        "start": "1970-01-01T00:00:00Z",
        "end": "1970-01-01T00:00:03Z",
        "granularity": "raw",
        "limit": 2,
    }

    first = await server._tool_manager.call_tool("loxone_get_statistics", arguments)
    second = await server._tool_manager.call_tool(
        "loxone_get_statistics", {**arguments, "cursor": first.data.next_cursor}
    )

    assert calls == 2
    assert [point.value for point in first.data.points] == [1.0, 2.0]
    assert [point.value for point in second.data.points] == [3.0]
    assert second.data.next_cursor is None


@pytest.mark.asyncio
async def test_statistics_cursor_preserves_same_timestamp_points_across_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    points = (
        StatisticPoint(1, 1.0),
        StatisticPoint(1, 1.0),
        StatisticPoint(1, 2.0),
    )

    class Runtime:
        async def get_statistics(
            self, *_: object
        ) -> tuple[object, StatisticSeries, tuple[StatisticPoint, ...]]:
            return (
                object(),
                StatisticSeries("series", "statistic_v2", "group", "output", "Series", ""),
                points,
            )

    server = FastMCP("statistics-same-timestamp")
    register_history_tools(server, Runtime())  # type: ignore[arg-type]
    monkeypatch.setattr(
        tools_module, "_access", lambda: _loxberry_access(READ_SCOPE, HISTORY_SCOPE)
    )
    arguments = {
        "control_uuid": "control",
        "series_id": "series",
        "start": "1970-01-01T00:00:01Z",
        "end": "1970-01-01T00:00:01Z",
        "granularity": "raw",
        "limit": 2,
    }

    first = await server._tool_manager.call_tool("loxone_get_statistics", arguments)
    second = await server._tool_manager.call_tool(
        "loxone_get_statistics", {**arguments, "cursor": first.data.next_cursor}
    )

    assert len(first.data.points) == 2
    assert len(second.data.points) == 1
    assert sorted(point.value for point in (*first.data.points, *second.data.points)) == [
        1.0,
        1.0,
        2.0,
    ]
    assert second.data.next_cursor is None


@pytest.mark.parametrize("limit", [0, 101])
def test_page_limit_is_bounded(limit: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 100"):
        _page(_CursorCodec(), "rooms", [], None, limit)


def test_control_tool_contract_is_explicitly_mutating_and_non_idempotent() -> None:
    server = FastMCP("control-contract")
    register_control_tool(server, None)

    tool = server._tool_manager.list_tools()[0]

    assert tool.name == "loxone_operate_control"
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is True
    assert tool.annotations.idempotentHint is False
    assert set(tool.parameters["properties"]["action"]["enum"]) == {
        "on",
        "off",
        "set_level",
        "set_mood",
        "open",
        "close",
        "shade",
        "stop",
        "enable_auto",
        "disable_auto",
        "set_position",
        "set_slat_position",
        "set_position_and_slats",
        "pulse",
        "select_output",
        "reset",
        "set_scene",
        "set_color_hsv",
        "set_color_temperature",
        "set_value",
        "start_override",
        "stop_override",
        "start_fan_override",
        "stop_fan_override",
        "start_mode_override",
        "stop_mode_override",
    }


def test_skill_guide_tool_is_read_only_and_matches_resource_content() -> None:
    server = FastMCP("skill-contract")
    register_skill_tool(server)

    tool = server._tool_manager.list_tools()[0]
    result = tool.fn()

    assert tool.name == "loxone_get_skill_guide"
    assert tool.parameters == {
        "properties": {},
        "title": "get_skill_guideArguments",
        "type": "object",
    }
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False
    assert result.data.name == "using-loxberry-mcp"  # type: ignore[union-attr]
    assert result.data.revision == 22  # type: ignore[union-attr]
    assert result.data.media_type == "text/markdown"  # type: ignore[union-attr]
    assert result.data.content == read_skill_markdown()  # type: ignore[union-attr]
    assert "For a `StatusMonitor`, use its `inputStates` state UUID." in result.data.content  # type: ignore[union-attr]
    assert "`room_group`" in result.data.content  # type: ignore[union-attr]
    assert "`loxone_get_room_snapshot`" in result.data.content  # type: ignore[union-attr]
    assert "`loxone_get_weather" in result.data.content  # type: ignore[union-attr]


def test_tool_input_schemas_explain_every_argument() -> None:
    server = FastMCP("documented-contract")
    register_read_tools(server, None, control_enabled=True)
    register_control_tool(server, None)
    published = {tool.name: tool for tool in server._tool_manager.list_tools()}

    expected_fields = {
        "loxone_list_rooms": {"cursor", "limit"},
        "loxone_get_room_snapshot": {"room_uuid", "cursor", "limit"},
        "loxone_list_categories": {"cursor", "limit"},
        "loxone_get_weather": {"mode", "cursor", "limit"},
        "loxone_find_controls": {
            "query",
            "room_uuid",
            "category_uuid",
            "control_type",
            "has_statistics",
            "has_history",
            "include_hidden",
            "cursor",
            "limit",
        },
        "loxone_describe_control": {"control_uuid", "include_hidden"},
        "loxone_get_control_notes": {"control_uuid", "include_hidden"},
        "loxone_get_states": {"state_uuids", "include_hidden"},
        "loxone_operate_control": {
            "control_uuid",
            "action",
            "level",
            "mood_id",
            "position",
            "slat_position",
            "scene_id",
            "output_id",
            "hue",
            "saturation",
            "brightness",
            "kelvin",
            "value",
            "duration_seconds",
        },
    }
    for tool_name, field_names in expected_fields.items():
        properties = published[tool_name].parameters["properties"]
        assert set(properties) == field_names
        assert all(properties[name].get("description") for name in field_names)

    find_properties = published["loxone_find_controls"].parameters["properties"]
    assert find_properties["query"]["maxLength"] == 200
    assert find_properties["has_statistics"]["default"] is False
    assert "legacy" in find_properties["has_statistics"]["description"]
    assert find_properties["has_history"]["default"] is False
    assert find_properties["limit"]["minimum"] == 1
    assert find_properties["limit"]["maximum"] == 100
    operation = published["loxone_operate_control"].parameters["properties"]
    assert operation["mood_id"]["maxLength"] == 10
    assert operation["scene_id"]["maxLength"] == 10
    assert operation["output_id"]["maxLength"] == 2
    state_uuids = published["loxone_get_states"].parameters["properties"]["state_uuids"]
    assert state_uuids["minItems"] == 1
    assert state_uuids["maxItems"] == 100
    weather = published["loxone_get_weather"].parameters["properties"]
    assert weather["mode"]["default"] == "forecast"
    assert weather["limit"]["maximum"] == 96
    for name in ("level", "position", "slat_position"):
        assert operation[name]["minimum"] == 0
        assert operation[name]["maximum"] == 100


def test_phase_four_tool_contracts_are_narrow_and_correctly_annotated() -> None:
    server = FastMCP("phase-four-contract")
    register_history_tools(server, None)
    register_loxberry_operate_tool(server, LoxBerryOperateRuntime(object(), object(), object()))
    register_control_tool(server, None)
    published = {tool.name: tool for tool in server._tool_manager.list_tools()}

    statistics = published["loxone_get_statistics"]
    assert statistics.annotations is not None
    assert statistics.annotations.readOnlyHint is True
    assert set(statistics.parameters["properties"]) == {
        "control_uuid",
        "series_id",
        "start",
        "end",
        "granularity",
        "include_hidden",
        "cursor",
        "limit",
    }
    assert statistics.parameters["properties"]["start"]["format"] == "date-time"
    assert statistics.parameters["properties"]["end"]["format"] == "date-time"
    assert statistics.parameters["properties"]["series_id"]["maxLength"] == 128
    assert statistics.parameters["properties"]["limit"]["minimum"] == 1
    assert statistics.parameters["properties"]["limit"]["maximum"] == 500
    assert statistics.parameters["properties"]["include_hidden"]["default"] is False
    history = published["loxone_get_control_history"]
    assert history.annotations is not None
    assert history.annotations.readOnlyHint is True
    assert history.parameters["properties"]["include_hidden"]["default"] is False
    cache = published["loxberry_clear_statistics_cache"]
    assert cache.annotations is not None
    assert cache.annotations.readOnlyHint is False
    assert cache.annotations.destructiveHint is True
    assert cache.parameters["properties"] == {}
    assert cache.output_schema["$defs"]["CacheClearData"]["properties"] == {
        "memory_entries_removed": {"title": "Memory Entries Removed", "type": "integer"}
    }
    operation = published["loxone_operate_control"]
    for control_type in (
        "TimedSwitch",
        "Radio",
        "LightsceneRGB",
        "ColorPicker V1/V2",
        "Pushbutton",
        "UpDownAnalog",
    ):
        assert control_type in operation.description


@pytest.mark.asyncio
async def test_statistics_limit_is_enforced_at_runtime() -> None:
    class Runtime:
        async def get_statistics(
            self, *_: object
        ) -> tuple[object, StatisticSeries, tuple[object, ...]]:
            raise AssertionError("invalid limit must be rejected before runtime access")

    server = FastMCP("statistics-limit")
    register_history_tools(server, Runtime())  # type: ignore[arg-type]

    with pytest.raises(ToolError, match="less than or equal to 500"):
        await server._tool_manager.call_tool(
            "loxone_get_statistics",
            {
                "control_uuid": "control",
                "series_id": "series",
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-01-02T00:00:00Z",
                "granularity": "raw",
                "limit": 501,
            },
        )


@pytest.mark.asyncio
async def test_statistic_series_id_length_is_enforced_at_runtime() -> None:
    class Runtime:
        async def get_statistics(
            self, *_: object
        ) -> tuple[object, StatisticSeries, tuple[object, ...]]:
            raise AssertionError("invalid series ID must be rejected before runtime access")

    server = FastMCP("statistics-series-id")
    register_history_tools(server, Runtime())  # type: ignore[arg-type]

    with pytest.raises(ToolError, match="at most 128 characters"):
        await server._tool_manager.call_tool(
            "loxone_get_statistics",
            {
                "control_uuid": "control",
                "series_id": "x" * 129,
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-01-02T00:00:00Z",
                "granularity": "raw",
            },
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "identifier", "value"),
    [
        ("set_mood", "mood_id", "x" * 11),
        ("set_scene", "scene_id", "x" * 11),
        ("select_output", "output_id", "x" * 3),
    ],
)
async def test_control_identifier_lengths_are_enforced_at_runtime(
    action: str, identifier: str, value: str
) -> None:
    server = FastMCP("control-identifier-length")
    register_control_tool(server, None)

    with pytest.raises(ToolError, match="at most"):
        await server._tool_manager.call_tool(
            "loxone_operate_control",
            {"control_uuid": "control", "action": action, identifier: value},
        )


@pytest.mark.asyncio
async def test_history_limit_is_enforced_at_runtime() -> None:
    server = FastMCP("history-limit")
    register_history_tools(server, None)

    with pytest.raises(ToolError, match="less than or equal to 100"):
        await server._tool_manager.call_tool(
            "loxone_get_control_history",
            {"control_uuid": "control", "limit": 101},
        )


@pytest.mark.asyncio
async def test_loxberry_operate_runtime_requires_exact_live_binding() -> None:
    class Cache:
        def clear(self) -> object:
            return object()

    class ConfigStore:
        def load(self) -> PluginConfig:
            return PluginConfig(
                loxone_history_enabled=True,
                loxberry_operate_enabled=True,
                loxberry_operate_bindings=("binding",),
            )

    class AuthStore:
        def pseudonym(self, *parts: str) -> str:
            assert parts[0] == "loxberry-operate-binding-v1"
            return "binding"

    runtime = LoxBerryOperateRuntime(Cache(), ConfigStore(), AuthStore())
    allowed = _loxberry_access(READ_SCOPE, HISTORY_SCOPE, LOXBERRY_OPERATE_SCOPE)
    await runtime.clear_statistics_cache(allowed)

    with pytest.raises(PermissionError):
        await runtime.clear_statistics_cache(_loxberry_access(READ_SCOPE, HISTORY_SCOPE))


@pytest.mark.asyncio
async def test_loxberry_operate_rate_limits_denied_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConfigStore:
        def load(self) -> PluginConfig:
            return PluginConfig(
                loxone_history_enabled=True,
                loxberry_operate_enabled=True,
                loxberry_operate_requests_per_minute=1,
            )

    class AuthStore:
        def pseudonym(self, *_parts: str) -> str:
            return "not-approved"

    runtime = LoxBerryOperateRuntime(object(), ConfigStore(), AuthStore())
    access = _loxberry_access(READ_SCOPE, HISTORY_SCOPE, LOXBERRY_OPERATE_SCOPE)
    monkeypatch.setattr(tools_module.time, "monotonic", lambda: 100.0)

    with pytest.raises(PermissionError):
        await runtime.clear_statistics_cache(access)
    with pytest.raises(tools_module.DiagnosticsUnavailable):
        await runtime.clear_statistics_cache(access)


@pytest.mark.asyncio
async def test_cache_clear_denial_and_timeout_are_audited(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    access = _loxberry_access(READ_SCOPE, HISTORY_SCOPE, LOXBERRY_OPERATE_SCOPE).model_copy(
        update={"client_id": "private-client-id", "identity_id": "private-identity-id"}
    )

    class DeniedRuntime:
        async def clear_statistics_cache(self, _access: StoredAccessToken) -> object:
            raise PermissionError

    server = FastMCP("cache-clear-audit")
    register_loxberry_operate_tool(server, DeniedRuntime())  # type: ignore[arg-type]
    monkeypatch.setattr(tools_module, "_access", lambda: access)
    caplog.set_level(logging.WARNING, logger="mcpserver.tools")

    denied = await server._tool_manager.call_tool("loxberry_clear_statistics_cache", {})

    assert denied.ok is False
    assert denied.data.error == "permission_denied"  # type: ignore[union-attr]
    assert "outcome=permission_denied" in caplog.text
    assert f"client={tools_module._audit_identity(str(access.client_id))}" in caplog.text
    assert f"identity={tools_module._audit_identity(access.identity_id)}" in caplog.text
    assert str(access.client_id) not in caplog.text
    assert access.identity_id not in caplog.text

    class TimedOutRuntime:
        async def clear_statistics_cache(self, _access: StoredAccessToken) -> object:
            raise TimeoutError

    timeout_server = FastMCP("cache-clear-timeout")
    register_loxberry_operate_tool(timeout_server, TimedOutRuntime())  # type: ignore[arg-type]
    timed_out = await timeout_server._tool_manager.call_tool("loxberry_clear_statistics_cache", {})

    assert timed_out.ok is False
    assert timed_out.data.error == "temporarily_unavailable"  # type: ignore[union-attr]
    assert "outcome=timed_out_unknown" in caplog.text

    class CancelledRuntime:
        async def clear_statistics_cache(self, _access: StoredAccessToken) -> object:
            raise asyncio.CancelledError

    cancelled_server = FastMCP("cache-clear-cancelled")
    register_loxberry_operate_tool(cancelled_server, CancelledRuntime())  # type: ignore[arg-type]
    tool = cancelled_server._tool_manager.get_tool("loxberry_clear_statistics_cache")
    assert tool is not None

    with pytest.raises(asyncio.CancelledError):
        await tool.fn()
    assert "outcome=cancelled_unknown" in caplog.text


@pytest.mark.asyncio
async def test_schema_metadata_keeps_structured_invalid_input_envelope() -> None:
    server = FastMCP("structured-validation")
    register_read_tools(server, None)

    result = await server._tool_manager.call_tool("loxone_find_controls", {"query": "x" * 201})

    assert result.ok is False
    assert result.data.error == "invalid_input"  # type: ignore[union-attr]
    assert result.trace_id


@pytest.mark.asyncio
async def test_describe_control_only_advertises_actions_to_control_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FastMCP("capability-contract")
    register_read_tools(server, None, control_enabled=True)
    scopes = [READ_SCOPE]
    access = StoredAccessToken(
        token="opaque",
        client_id="client",
        scopes=scopes,
        expires_at=2_000_000_000,
        resource="https://loxberry.local/plugins/mcpserver/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="miniserver",
    )
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="1",
        rooms=(),
        categories=(),
        controls=(
            Control(
                uuid="control-1",
                name="Light",
                control_type="Switch",
                room_uuid=None,
                category_uuid=None,
                action_uuid="action-1",
                state_uuids=(("active", "state-1"),),
                rating=4,
                secured=True,
                has_notes=True,
                subcontrols=(
                    Control(
                        uuid="subcontrol-1",
                        name="Linked status",
                        control_type="InfoOnlyAnalog",
                        room_uuid=None,
                        category_uuid=None,
                        action_uuid=None,
                        state_uuids=(("value", "subcontrol-state-1"),),
                    ),
                ),
                linked_control_uuids=("linked-control-1",),
            ),
            Control(
                uuid="linked-control-1",
                name="User-linked control",
                control_type="UpDownAnalog",
                room_uuid=None,
                category_uuid=None,
                action_uuid="linked-action-1",
                state_uuids=(("value", "linked-state-1"),),
                restrictions=17,
                minimum=0.0,
                maximum=3.0,
                step=1.0,
                is_user_linked=True,
            ),
        ),
    )

    async def snapshot(_runtime: object) -> tuple[StoredAccessToken, RuntimeSnapshot]:
        return access, RuntimeSnapshot("family", structure, True)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    tool = next(
        item for item in server._tool_manager.list_tools() if item.name == "loxone_describe_control"
    )

    read_only = await tool.fn("control-1")
    assert read_only.data.capabilities.allowed_actions == []  # type: ignore[union-attr]
    assert read_only.data.presentation.rating == 4  # type: ignore[union-attr]
    assert read_only.data.presentation.secured is True  # type: ignore[union-attr]
    assert read_only.data.presentation.read_only is False  # type: ignore[union-attr]
    assert read_only.data.presentation.has_notes is True  # type: ignore[union-attr]
    assert read_only.data.visibility == "direct"  # type: ignore[union-attr]
    assert read_only.data.relationships.parent is None  # type: ignore[union-attr]
    assert read_only.data.relationships.subcontrols[0].uuid == "subcontrol-1"  # type: ignore[union-attr]

    linked = await tool.fn("subcontrol-1")
    assert linked.data.relationships.parent.uuid == "control-1"  # type: ignore[union-attr]
    assert linked.data.relationships.subcontrols == []  # type: ignore[union-attr]
    assert linked.data.visibility == "direct"  # type: ignore[union-attr]

    user_linked = await tool.fn("linked-control-1")
    assert user_linked.data.visibility == "linked"  # type: ignore[union-attr]
    assert user_linked.data.relationships.linked_by[0].uuid == "control-1"  # type: ignore[union-attr]
    assert read_only.data.relationships.linked_controls[0].uuid == "linked-control-1"  # type: ignore[union-attr]

    access.scopes.append(CONTROL_SCOPE)
    controlled = await tool.fn("control-1")
    assert controlled.data.capabilities.allowed_actions == [  # type: ignore[union-attr]
        "on",
        "off",
    ]
    linked_controlled = await tool.fn("linked-control-1")
    assert linked_controlled.data.capabilities.allowed_actions == ["set_value"]  # type: ignore[union-attr]
    assert linked_controlled.data.capabilities.analog_range.minimum == 0.0  # type: ignore[union-attr]
    assert linked_controlled.data.capabilities.analog_range.maximum == 3.0  # type: ignore[union-attr]
    assert linked_controlled.data.capabilities.analog_range.step == 1.0  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_list_rooms_includes_an_unambiguous_room_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = _loxberry_access(READ_SCOPE)
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="1",
        rooms=(Room("room-1", "Office", "group-1"), Room("room-2", "Attic")),
        categories=(),
        controls=(),
        room_groups=(NamedGroup("group-1", "Ground floor"),),
    )

    async def snapshot(_runtime: object) -> tuple[StoredAccessToken, RuntimeSnapshot]:
        return access, RuntimeSnapshot("family", structure, True)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("room-groups-contract")
    register_read_tools(server, None)
    tool = server._tool_manager.get_tool("loxone_list_rooms")
    assert tool is not None

    result = await tool.fn()

    assert result.ok is True
    assert result.data.items[0].room_group.uuid == "group-1"  # type: ignore[union-attr]
    assert result.data.items[0].room_group.name == "Ground floor"  # type: ignore[union-attr]
    assert result.data.items[1].room_group is None  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_describe_control_exposes_status_monitor_input_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = _loxberry_access(READ_SCOPE)
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="1",
        rooms=(Room("room-1", "Office"),),
        categories=(),
        controls=(
            Control(
                uuid="monitor-1",
                name="Network status",
                control_type="StatusMonitor",
                room_uuid=None,
                category_uuid=None,
                action_uuid=None,
                state_uuids=(("inputStates", "states-1"),),
                status_monitor_inputs=(
                    StatusMonitorInput(0, "Printer", "Office", "printer", "room-1"),
                ),
                status_monitor_statuses=(StatusMonitorStatus(1, "Offline", 0, "#E4354A"),),
            ),
        ),
    )

    async def snapshot(_runtime: object) -> tuple[StoredAccessToken, RuntimeSnapshot]:
        return access, RuntimeSnapshot("family", structure, True)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("status-monitor-contract")
    register_read_tools(server, None)
    tool = server._tool_manager.get_tool("loxone_describe_control")
    assert tool is not None

    result = await tool.fn("monitor-1")

    assert result.ok is True
    mapping = result.data.capabilities.status_monitor  # type: ignore[union-attr]
    assert mapping.inputs[0].index == 0
    assert mapping.inputs[0].name == "Printer"
    assert mapping.inputs[0].room.uuid == "room-1"
    assert mapping.inputs[0].room.name == "Office"
    assert mapping.statuses[0].status_id == 1
    assert mapping.statuses[0].name == "Offline"


@pytest.mark.asyncio
async def test_describe_control_resolves_window_monitor_item_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = _loxberry_access(READ_SCOPE)
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="1",
        rooms=(Room("room-1", "Office"),),
        categories=(),
        controls=(
            Control(
                uuid="monitor-1",
                name="Windows",
                control_type="WindowMonitor",
                room_uuid=None,
                category_uuid=None,
                action_uuid=None,
                state_uuids=(("windowStates", "states-1"),),
                window_monitor_items=(
                    WindowMonitorItem(0, "Office window", "room-1", "window-1", "Office"),
                ),
            ),
            Control(
                uuid="window-1",
                name="Office window",
                control_type="Window",
                room_uuid="room-1",
                category_uuid=None,
                action_uuid=None,
                state_uuids=(),
            ),
        ),
    )

    async def snapshot(_runtime: object) -> tuple[StoredAccessToken, RuntimeSnapshot]:
        return access, RuntimeSnapshot("family", structure, True)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("window-monitor-contract")
    register_read_tools(server, None)
    tool = server._tool_manager.get_tool("loxone_describe_control")
    assert tool is not None

    result = await tool.fn("monitor-1")

    assert result.ok is True
    item = result.data.capabilities.model.window_monitor_items[0]  # type: ignore[union-attr]
    assert item.room.uuid == "room-1"
    assert item.control.uuid == "window-1"
    assert item.control.name == "Office window"


@pytest.mark.asyncio
async def test_get_states_accepts_advertised_global_metadata_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = _loxberry_access(READ_SCOPE)
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="1",
        rooms=(),
        categories=(),
        controls=(),
        global_metadata=(GlobalMetadata("global_state", "ready", "ready", state_uuid="state-1"),),
    )

    class Runtime:
        def state(self, _snapshot: RuntimeSnapshot, uuid: str) -> StateRecord:
            assert uuid == "state-1"
            return StateRecord(uuid, 1.0, Freshness.CURRENT, 1_700_000_000.0)

    async def snapshot(_runtime: object) -> tuple[StoredAccessToken, RuntimeSnapshot]:
        return access, RuntimeSnapshot("family", structure, True)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("global-states")
    register_read_tools(server, Runtime())  # type: ignore[arg-type]
    tool = server._tool_manager.get_tool("loxone_get_states")
    assert tool is not None

    result = await tool.fn(["state-1"])

    assert result.ok is True
    assert result.data.states[0].value == 1.0  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_room_snapshot_matches_additive_irrigation_state_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = _loxberry_access(READ_SCOPE)
    zones = (
        '[{"id":0,"name":"Front","duration":600,"setByLogic":false,"futureField":{"ignored":true}}]'
    )
    irrigation = Control(
        uuid="irrigation",
        name="Irrigation",
        control_type="Irrigation",
        room_uuid="room-1",
        category_uuid=None,
        action_uuid="action",
        state_uuids=(
            ("zones", "zones-state"),
            ("currentZone", "current-state"),
            ("rainActive", "rain-state"),
        ),
    )
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="1",
        rooms=(Room("room-1", "Garden"), Room("room-2", "Empty")),
        categories=(),
        controls=(irrigation,),
        hidden_controls=(
            Control(
                uuid="hidden",
                name="Hidden",
                control_type="InfoOnlyAnalog",
                room_uuid="room-1",
                category_uuid=None,
                action_uuid=None,
                state_uuids=(("value", "hidden-state"),),
                is_hidden=True,
            ),
        ),
    )
    records = {
        "zones-state": StateRecord("zones-state", zones, Freshness.CURRENT, 1_700_000_000.0),
        "current-state": StateRecord("current-state", 0.0, Freshness.CURRENT, 1_700_000_001.0),
        "rain-state": StateRecord("rain-state", 1.0, Freshness.STALE, 1_700_000_002.0),
        "hidden-state": StateRecord("hidden-state", 1.0, Freshness.CURRENT, 1_700_000_003.0),
    }

    class Runtime:
        def state(self, _snapshot: RuntimeSnapshot, uuid: str) -> StateRecord:
            return records[uuid]

    async def snapshot(_runtime: object) -> tuple[StoredAccessToken, RuntimeSnapshot]:
        return access, RuntimeSnapshot("family", structure, True)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("room-snapshot")
    register_read_tools(server, Runtime())  # type: ignore[arg-type]
    room_tool = server._tool_manager.get_tool("loxone_get_room_snapshot")
    states_tool = server._tool_manager.get_tool("loxone_get_states")
    describe_tool = server._tool_manager.get_tool("loxone_describe_control")
    assert room_tool is not None and states_tool is not None and describe_tool is not None

    first = await room_tool.fn("room-1", limit=2)
    second = await room_tool.fn("room-1", cursor=first.data.next_cursor, limit=2)  # type: ignore[union-attr]
    wrong_cursor = await room_tool.fn("room-2", cursor=first.data.next_cursor, limit=2)  # type: ignore[union-attr]
    missing = await room_tool.fn("missing")
    states = await states_tool.fn(["zones-state", "current-state", "rain-state"])
    description = await describe_tool.fn("irrigation")

    assert first.ok is True and second.ok is True
    assert [item.state.name for item in first.data.items] == ["zones", "currentZone"]  # type: ignore[union-attr]
    assert [item.state.name for item in second.data.items] == ["rainActive"]  # type: ignore[union-attr]
    assert second.stale is True
    assert first.data.items[0].state.value == zones  # type: ignore[union-attr]
    assert first.data.items[0].state.semantic_value == states.data.states[0].semantic_value  # type: ignore[union-attr]
    assert states.data.states[1].semantic_value == {  # type: ignore[union-attr]
        "status": "zone",
        "zone_id": 0,
        "zone_name": "Front",
    }
    assert states.data.states[2].semantic_value is True  # type: ignore[union-attr]
    assert description.data.capabilities.allowed_actions == []  # type: ignore[union-attr]
    assert description.data.capabilities.model.irrigation.all_zones_id == 8  # type: ignore[union-attr]
    assert wrong_cursor.data.error == "invalid_input"  # type: ignore[union-attr]
    assert missing.data.error == "not_found"  # type: ignore[union-attr]

    records["zones-state"] = StateRecord("zones-state", zones, Freshness.STALE, 1_700_000_004.0)
    current_zone_without_fresh_zones = await states_tool.fn(["current-state"])
    assert current_zone_without_fresh_zones.stale is False
    assert current_zone_without_fresh_zones.data.states[0].semantic_value == {  # type: ignore[union-attr]
        "status": "zone",
        "zone_id": 0,
    }

    incomplete = '[{"id":0,"name":"Front"}]'
    records["zones-state"] = StateRecord(
        "zones-state", incomplete, Freshness.CURRENT, 1_700_000_005.0
    )
    incomplete_result = await states_tool.fn(["zones-state"])
    assert incomplete_result.data.states[0].value == incomplete  # type: ignore[union-attr]
    assert incomplete_result.data.states[0].semantic_value is None  # type: ignore[union-attr]
    assert incomplete_result.warnings

    too_many = json.dumps(
        [{"id": index, "name": "Zone", "duration": 1, "setByLogic": False} for index in range(101)]
    )
    records["zones-state"] = StateRecord(
        "zones-state", too_many, Freshness.CURRENT, 1_700_000_006.0
    )
    bounded_result = await states_tool.fn(["zones-state"])
    assert bounded_result.data.states[0].value == too_many  # type: ignore[union-attr]
    assert bounded_result.data.states[0].semantic_value is None  # type: ignore[union-attr]
    assert bounded_result.warnings

    overflowing = '[{"id":0,"name":"Zone","duration":' + "9" * 400 + ',"setByLogic":false}]'
    records["zones-state"] = StateRecord(
        "zones-state", overflowing, Freshness.CURRENT, 1_700_000_007.0
    )
    overflowing_result = await states_tool.fn(["zones-state"])
    assert overflowing_result.data.states[0].value == overflowing  # type: ignore[union-attr]
    assert overflowing_result.data.states[0].semantic_value is None  # type: ignore[union-attr]
    assert overflowing_result.warnings


@pytest.mark.asyncio
async def test_weather_tool_pages_actual_and_forecast_without_state_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = _loxberry_access(READ_SCOPE)
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="1",
        rooms=(),
        categories=(),
        controls=(),
        global_metadata=(
            GlobalMetadata("weather_state", "actual", "actual", state_uuid="actual-state"),
            GlobalMetadata("weather_state", "forecast", "forecast", state_uuid="forecast-state"),
        ),
        weather=WeatherMetadata(formats=(("temperature", "%.1f °C"),), type_texts=((1, "Clear"),)),
    )

    def point(timestamp: int, temperature: float) -> dict[str, object]:
        return {
            "timestamp": timestamp,
            "weather_type": 1,
            "wind_direction": 180,
            "solar_radiation": 100,
            "relative_humidity": 50,
            "temperature": temperature,
            "perceived_temperature": temperature - 1,
            "dew_point": 5.0,
            "precipitation": 0.0,
            "wind_speed": 3.0,
            "barometric_pressure": 1013.0,
        }

    records = {
        "actual-state": StateRecord(
            "actual-state",
            {"last_update": 1, "entries": [point(0, 20.0)]},
            Freshness.CURRENT,
            1_700_000_000.0,
        ),
        "forecast-state": StateRecord(
            "forecast-state",
            {"last_update": 1, "entries": [point(3600, 21.0), point(7200, 22.0)]},
            Freshness.STALE,
            1_700_000_000.0,
        ),
    }

    class Runtime:
        def state(self, _snapshot: RuntimeSnapshot, uuid: str) -> StateRecord:
            return records[uuid]

    async def snapshot(_runtime: object) -> tuple[StoredAccessToken, RuntimeSnapshot]:
        return access, RuntimeSnapshot("family", structure, True)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("weather")
    register_read_tools(server, Runtime())  # type: ignore[arg-type]
    tool = server._tool_manager.get_tool("loxone_get_weather")
    assert tool is not None

    first = await tool.fn(limit=1)
    second = await tool.fn(cursor=first.data.next_cursor, limit=1)  # type: ignore[union-attr]
    actual = await tool.fn("actual")
    wrong_cursor = await tool.fn("actual", cursor=first.data.next_cursor)  # type: ignore[union-attr]
    records["forecast-state"] = StateRecord("forecast-state", None, Freshness.UNKNOWN, None)
    unavailable = await tool.fn()

    assert first.data.mode == "forecast"  # type: ignore[union-attr]
    assert first.data.items[0].at == "2009-01-01T01:00:00Z"  # type: ignore[union-attr]
    assert first.data.items[0].weather_type_text == "Clear"  # type: ignore[union-attr]
    assert first.data.formats == {"temperature": "%.1f °C"}  # type: ignore[union-attr]
    assert first.stale is True and second.data.next_cursor is None  # type: ignore[union-attr]
    assert len(actual.data.items) == 1  # type: ignore[union-attr]
    assert wrong_cursor.ok is False
    assert wrong_cursor.data.error == "invalid_input"  # type: ignore[union-attr]
    assert unavailable.data.error == "temporarily_unavailable"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_alarm_clock_model_and_semantics_remain_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = _loxberry_access(READ_SCOPE, CONTROL_SCOPE)
    entries = (
        '{"3":{"name":"Morning","isActive":true,"alarmTime":25200,'
        '"modes":[1,2],"nightLight":false,"daily":false,'
        '"futureField":{"ignored":true}}}'
    )
    alarm = Control(
        uuid="alarm",
        name="Alarm",
        control_type="AlarmClock",
        room_uuid=None,
        category_uuid=None,
        action_uuid="action",
        state_uuids=(
            ("entryList", "entries"),
            ("nextEntry", "next"),
            ("nextEntryTime", "time"),
            ("isEnabled", "enabled"),
            ("deviceState", "device"),
            ("deviceSettings", "settings"),
        ),
        alarm_clock_has_night_light=True,
        alarm_clock_wake_alarm_sounds=(NamedOption(3, "Tone"),),
    )
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="1",
        rooms=(),
        categories=(),
        controls=(alarm,),
    )
    records = {
        "entries": StateRecord("entries", entries, Freshness.CURRENT, 1.0),
        "next": StateRecord("next", 3.0, Freshness.CURRENT, 1.0),
        "time": StateRecord("time", 3600.0, Freshness.CURRENT, 1.0),
        "enabled": StateRecord("enabled", 1.0, Freshness.CURRENT, 1.0),
        "device": StateRecord("device", 2.0, Freshness.CURRENT, 1.0),
        "settings": StateRecord("settings", "{", Freshness.CURRENT, 1.0),
    }

    class Runtime:
        def state(self, _snapshot: RuntimeSnapshot, uuid: str) -> StateRecord:
            return records[uuid]

    async def snapshot(_runtime: object) -> tuple[StoredAccessToken, RuntimeSnapshot]:
        return access, RuntimeSnapshot("family", structure, True)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("alarm-clock")
    register_read_tools(server, Runtime(), control_enabled=True)  # type: ignore[arg-type]
    describe = server._tool_manager.get_tool("loxone_describe_control")
    states_tool = server._tool_manager.get_tool("loxone_get_states")
    assert describe is not None and states_tool is not None

    description = await describe.fn("alarm")
    states = await states_tool.fn(["entries", "next", "time", "enabled", "device", "settings"])

    assert description.data.capabilities.allowed_actions == []  # type: ignore[union-attr]
    model = description.data.capabilities.model.alarm_clock  # type: ignore[union-attr]
    assert model.has_night_light is True
    assert model.wake_alarm_sounds[0].name == "Tone"
    assert states.data.states[0].value == entries  # type: ignore[union-attr]
    assert states.data.states[0].semantic_value[0]["alarm_time"] == "07:00:00"  # type: ignore[index,union-attr]
    assert states.data.states[1].semantic_value["entry"]["id"] == 3  # type: ignore[index,union-attr]
    assert states.data.states[2].semantic_value["at"] == "2009-01-01T01:00:00Z"  # type: ignore[index,union-attr]
    assert states.data.states[3].semantic_value is True  # type: ignore[union-attr]
    assert states.data.states[4].semantic_value == {"status": "online"}  # type: ignore[union-attr]
    assert states.data.states[5].semantic_value is None  # type: ignore[union-attr]
    assert states.warnings

    records["entries"] = StateRecord("entries", entries, Freshness.STALE, 2.0)
    next_without_fresh_entries = await states_tool.fn(["next"])
    assert next_without_fresh_entries.stale is False
    assert next_without_fresh_entries.data.states[0].semantic_value == {  # type: ignore[union-attr]
        "status": "entry",
        "entry_id": 3,
    }

    records["entries"] = StateRecord("entries", None, Freshness.UNKNOWN, None)
    unknown_entries = await states_tool.fn(["entries"])
    assert unknown_entries.stale is True
    assert unknown_entries.data.states[0].semantic_value is None  # type: ignore[union-attr]
    assert unknown_entries.warnings == []

    invalid_time = 4_000_000_001.0
    records["time"] = StateRecord("time", invalid_time, Freshness.CURRENT, 2.0)
    invalid_time_result = await states_tool.fn(["time"])
    assert invalid_time_result.data.states[0].value == invalid_time  # type: ignore[union-attr]
    assert invalid_time_result.data.states[0].semantic_value is None  # type: ignore[union-attr]
    assert invalid_time_result.warnings

    malicious_entries = '{"__proto__":{"name":"ignored"}}'
    records["entries"] = StateRecord("entries", malicious_entries, Freshness.CURRENT, 3.0)
    malicious_result = await states_tool.fn(["entries"])
    assert malicious_result.data.states[0].value == malicious_entries  # type: ignore[union-attr]
    assert malicious_result.data.states[0].semantic_value is None  # type: ignore[union-attr]
    assert malicious_result.warnings


@pytest.mark.asyncio
async def test_get_control_notes_returns_only_runtime_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = _loxberry_access(READ_SCOPE)

    class Runtime:
        async def get_control_notes(
            self, received_access: StoredAccessToken, control_uuid: str
        ) -> tuple[Control, str]:
            assert received_access is access
            assert control_uuid == "control-1"
            return (
                Control(
                    uuid="control-1",
                    name="Light",
                    control_type="Switch",
                    room_uuid=None,
                    category_uuid=None,
                    action_uuid="action-1",
                    state_uuids=(),
                    has_notes=True,
                ),
                "User-authored note",
            )

    server = FastMCP("control-notes")
    register_read_tools(server, Runtime(), control_enabled=True)  # type: ignore[arg-type]
    monkeypatch.setattr(tools_module, "_access", lambda: access)
    tool = next(
        item
        for item in server._tool_manager.list_tools()
        if item.name == "loxone_get_control_notes"
    )

    result = await tool.fn("control-1")

    assert result.ok is True
    assert result.data.control_uuid == "control-1"  # type: ignore[union-attr]
    assert result.data.text == "User-authored note"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_find_controls_matches_control_type_case_insensitively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = StoredAccessToken(
        token="opaque",
        client_id="client",
        scopes=[READ_SCOPE],
        expires_at=2_000_000_000,
        resource="https://loxberry.local/plugins/mcpserver/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="miniserver",
    )
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="1",
        rooms=(),
        categories=(),
        controls=(
            Control(
                uuid="control-1",
                name="Light",
                control_type="Switch",
                room_uuid=None,
                category_uuid=None,
                action_uuid="action-1",
                state_uuids=(("active", "state-1"),),
            ),
        ),
    )

    async def snapshot(_runtime: object) -> tuple[StoredAccessToken, RuntimeSnapshot]:
        return access, RuntimeSnapshot("family", structure, True)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("case-insensitive-control-types")
    register_read_tools(server, None)
    tool = next(
        item for item in server._tool_manager.list_tools() if item.name == "loxone_find_controls"
    )

    result = await tool.fn(control_type="switch")

    assert result.ok is True
    assert [item.type for item in result.data.items] == ["Switch"]  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_find_controls_matches_a_radio_output_name(monkeypatch: pytest.MonkeyPatch) -> None:
    access = _loxberry_access(READ_SCOPE)
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="1",
        rooms=(),
        categories=(),
        controls=(
            Control(
                uuid="radio-1",
                name="Radio buttons",
                control_type="Radio",
                room_uuid=None,
                category_uuid=None,
                action_uuid="radio-action-1",
                state_uuids=(),
                radio_output_ids=("1",),
                radio_outputs=(("1", "Linked output"),),
            ),
        ),
    )

    async def snapshot(_runtime: object) -> tuple[StoredAccessToken, RuntimeSnapshot]:
        return access, RuntimeSnapshot("family", structure, True)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("radio-output-search")
    register_read_tools(server, None)
    tool = server._tool_manager.get_tool("loxone_find_controls")
    assert tool is not None

    result = await tool.fn(query="linked output")

    assert [item.uuid for item in result.data.items] == ["radio-1"]  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_hidden_controls_require_explicit_diagnosis_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = _loxberry_access(READ_SCOPE, CONTROL_SCOPE)
    hidden = Control(
        uuid="hidden-1",
        name="Hidden diagnostic value",
        control_type="UpDownAnalog",
        room_uuid=None,
        category_uuid=None,
        action_uuid="hidden-action-1",
        state_uuids=(("value", "hidden-state-1"),),
        restrictions=17,
        minimum=0.0,
        maximum=3.0,
        step=1.0,
        is_hidden=True,
    )
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="1",
        rooms=(),
        categories=(),
        controls=(),
        hidden_controls=(hidden,),
    )

    async def snapshot(_runtime: object) -> tuple[StoredAccessToken, RuntimeSnapshot]:
        return access, RuntimeSnapshot("family", structure, True)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("hidden-control-diagnosis")
    register_read_tools(server, None, control_enabled=True)
    find = server._tool_manager.get_tool("loxone_find_controls")
    describe = server._tool_manager.get_tool("loxone_describe_control")
    assert find is not None
    assert describe is not None

    assert (await find.fn(query="hidden")).data.items == []  # type: ignore[union-attr]
    found = await find.fn(query="hidden", include_hidden=True)
    assert found.data.items[0].visibility == "hidden"  # type: ignore[union-attr]
    assert (await describe.fn("hidden-1")).data.error == "not_found"  # type: ignore[union-attr]
    described = await describe.fn("hidden-1", include_hidden=True)
    assert described.data.visibility == "hidden"  # type: ignore[union-attr]
    assert described.data.capabilities.allowed_actions == []  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_find_controls_combines_history_and_statistics_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = _loxberry_access(READ_SCOPE)
    series = StatisticSeries("1", "control", "1", "value", "Energy", "kWh")
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="1",
        rooms=(),
        categories=(),
        controls=(
            Control(
                "both",
                "Both",
                "Meter",
                None,
                None,
                "a1",
                (),
                has_history=True,
                statistic_series=(series,),
            ),
            Control("history", "History", "Switch", None, None, "a2", (), has_history=True),
            Control(
                "statistics",
                "Statistics",
                "Meter",
                None,
                None,
                "a3",
                (),
                statistic_series=(series,),
            ),
        ),
    )

    async def snapshot(_runtime: object) -> tuple[StoredAccessToken, RuntimeSnapshot]:
        return access, RuntimeSnapshot("family", structure, True)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("history-capability-filters")
    register_read_tools(server, None)
    tool = next(
        item for item in server._tool_manager.list_tools() if item.name == "loxone_find_controls"
    )

    history = await tool.fn(has_history=True)
    statistics = await tool.fn(has_statistics=True)
    both = await tool.fn(has_history=True, has_statistics=True)

    assert [item.uuid for item in history.data.items] == ["both", "history"]  # type: ignore[union-attr]
    assert [item.uuid for item in statistics.data.items] == ["both", "statistics"]  # type: ignore[union-attr]
    assert [item.uuid for item in both.data.items] == ["both"]  # type: ignore[union-attr]
