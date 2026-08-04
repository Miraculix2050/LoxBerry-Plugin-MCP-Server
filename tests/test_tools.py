from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP

import mcpserver.tools as tools_module
from mcpserver.auth.provider import CONTROL_SCOPE, READ_SCOPE, StoredAccessToken
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import RuntimeSnapshot
from mcpserver.tools import _CursorCodec, _page, register_control_tool, register_read_tools


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
    assert set(tool.parameters["properties"]["action"]["enum"]) == {"on", "off"}


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
