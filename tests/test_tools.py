from __future__ import annotations

import logging

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
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure, StatisticSeries
from mcpserver.loxone.runtime import RuntimeSnapshot
from mcpserver.skill_delivery import read_skill_markdown
from mcpserver.tools import (
    LoxBerryOperateRuntime,
    LoxBerryReadRuntime,
    SystemStatusEnvelope,
    _CursorCodec,
    _error,
    _page,
    _result,
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
    }
    for tool in published.values():
        assert tool.parameters["properties"] == {}
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


@pytest.mark.parametrize("limit", [0, 101])
def test_page_limit_is_bounded(limit: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 100"):
        _page(_CursorCodec(), "rooms", [], None, limit)


def test_control_tool_contract_is_explicitly_mutating_and_idempotent() -> None:
    server = FastMCP("control-contract")
    register_control_tool(server, None)

    tool = server._tool_manager.list_tools()[0]

    assert tool.name == "loxone_operate_control"
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is True
    assert tool.annotations.idempotentHint is True
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
    assert result.data.revision == 8  # type: ignore[union-attr]
    assert result.data.media_type == "text/markdown"  # type: ignore[union-attr]
    assert result.data.content == read_skill_markdown()  # type: ignore[union-attr]


def test_tool_input_schemas_explain_every_argument() -> None:
    server = FastMCP("documented-contract")
    register_read_tools(server, None, control_enabled=True)
    register_control_tool(server, None)
    published = {tool.name: tool for tool in server._tool_manager.list_tools()}

    expected_fields = {
        "loxone_list_rooms": {"cursor", "limit"},
        "loxone_list_categories": {"cursor", "limit"},
        "loxone_find_controls": {
            "query",
            "room_uuid",
            "category_uuid",
            "control_type",
            "has_statistics",
            "has_history",
            "cursor",
            "limit",
        },
        "loxone_describe_control": {"control_uuid"},
        "loxone_get_control_notes": {"control_uuid"},
        "loxone_get_states": {"state_uuids"},
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
        },
    }
    for tool_name, field_names in expected_fields.items():
        properties = published[tool_name].parameters["properties"]
        assert set(properties) == field_names
        assert all(properties[name].get("description") for name in field_names)

    find_properties = published["loxone_find_controls"].parameters["properties"]
    assert find_properties["query"]["maxLength"] == 200
    assert find_properties["has_statistics"]["default"] is False
    assert find_properties["has_history"]["default"] is False
    assert find_properties["limit"]["minimum"] == 1
    assert find_properties["limit"]["maximum"] == 100
    assert (
        published["loxone_operate_control"].parameters["properties"]["mood_id"]["maxLength"] == 10
    )
    state_uuids = published["loxone_get_states"].parameters["properties"]["state_uuids"]
    assert state_uuids["minItems"] == 1
    assert state_uuids["maxItems"] == 100
    operation = published["loxone_operate_control"].parameters["properties"]
    for name in ("level", "position", "slat_position"):
        assert operation[name]["minimum"] == 0
        assert operation[name]["maximum"] == 100


def test_phase_four_tool_contracts_are_narrow_and_correctly_annotated() -> None:
    server = FastMCP("phase-four-contract")
    register_history_tools(server, None)
    register_loxberry_operate_tool(server, LoxBerryOperateRuntime(object(), object(), object()))
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
        "cursor",
        "limit",
    }
    assert statistics.parameters["properties"]["start"]["format"] == "date-time"
    assert statistics.parameters["properties"]["end"]["format"] == "date-time"
    assert statistics.parameters["properties"]["limit"]["minimum"] == 1
    assert statistics.parameters["properties"]["limit"]["maximum"] == 500
    history = published["loxone_get_control_history"]
    assert history.annotations is not None
    assert history.annotations.readOnlyHint is True
    cache = published["loxberry_clear_statistics_cache"]
    assert cache.annotations is not None
    assert cache.annotations.readOnlyHint is False
    assert cache.annotations.destructiveHint is True
    assert cache.parameters["properties"] == {}


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
async def test_cache_clear_denial_and_timeout_are_audited(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    access = _loxberry_access(READ_SCOPE, HISTORY_SCOPE, LOXBERRY_OPERATE_SCOPE)

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

    class TimedOutRuntime:
        async def clear_statistics_cache(self, _access: StoredAccessToken) -> object:
            raise TimeoutError

    timeout_server = FastMCP("cache-clear-timeout")
    register_loxberry_operate_tool(timeout_server, TimedOutRuntime())  # type: ignore[arg-type]
    timed_out = await timeout_server._tool_manager.call_tool("loxberry_clear_statistics_cache", {})

    assert timed_out.ok is False
    assert timed_out.data.error == "temporarily_unavailable"  # type: ignore[union-attr]
    assert "outcome=timed_out_unknown" in caplog.text


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

    access.scopes.append(CONTROL_SCOPE)
    controlled = await tool.fn("control-1")
    assert controlled.data.capabilities.allowed_actions == [  # type: ignore[union-attr]
        "on",
        "off",
    ]


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
