from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP

import mcpserver.tools as tools_module
from mcpserver.auth.provider import CONTROL_SCOPE, READ_SCOPE, StoredAccessToken
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import RuntimeSnapshot
from mcpserver.skill_delivery import read_skill_markdown
from mcpserver.tools import (
    _CursorCodec,
    _page,
    register_control_tool,
    register_read_tools,
    register_skill_tool,
)


def test_opaque_cursor_paginates_without_exposing_offset() -> None:
    codec = _CursorCodec()
    first = _page(codec, "rooms", list(range(75)), None, 50)

    assert first["items"] == list(range(50))
    assert isinstance(first["next_cursor"], str)
    assert "50" not in first["next_cursor"]
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
    assert result.data.revision == 2  # type: ignore[union-attr]
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
            "cursor",
            "limit",
        },
        "loxone_describe_control": {"control_uuid"},
        "loxone_get_states": {"state_uuids"},
        "loxone_operate_control": {
            "control_uuid",
            "action",
            "level",
            "mood_id",
            "position",
            "slat_position",
        },
    }
    for tool_name, field_names in expected_fields.items():
        properties = published[tool_name].parameters["properties"]
        assert set(properties) == field_names
        assert all(properties[name].get("description") for name in field_names)

    find_properties = published["loxone_find_controls"].parameters["properties"]
    assert find_properties["query"]["maxLength"] == 200
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

    access.scopes.append(CONTROL_SCOPE)
    controlled = await tool.fn("control-1")
    assert controlled.data.capabilities.allowed_actions == [  # type: ignore[union-attr]
        "on",
        "off",
    ]


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
