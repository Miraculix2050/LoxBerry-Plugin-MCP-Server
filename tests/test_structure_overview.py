from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP

import mcpserver.tools as tools_module
from mcpserver.auth.provider import READ_SCOPE, StoredAccessToken
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure, NamedGroup, Room
from mcpserver.loxone.presentation import structure_overview, visible_controls
from mcpserver.loxone.runtime import RuntimeSnapshot, RuntimeUnavailable
from mcpserver.tools import STRUCTURE_OVERVIEW_MAX_BYTES, register_read_tools


def _access() -> StoredAccessToken:
    return StoredAccessToken(
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


def _control(
    uuid: str,
    name: str,
    control_type: str,
    room_uuid: str | None,
    category_uuid: str | None,
    *,
    subcontrols: tuple[Control, ...] = (),
    hidden: bool = False,
) -> Control:
    return Control(
        uuid,
        name,
        control_type,
        room_uuid,
        category_uuid,
        f"action-{uuid}",
        (),
        subcontrols=subcontrols,
        is_hidden=hidden,
    )


def test_structure_overview_uses_visible_discovery_corpus_and_deterministic_breakdowns() -> None:
    child = _control("child", "Child", "Switch", None, None)
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="42",
        rooms=(Room("room-b", "Beta"), Room("room-a", "Alpha"), Room("room-empty", "Empty")),
        categories=(NamedGroup("cat-b", "Beta"), NamedGroup("cat-a", "Alpha")),
        controls=(
            _control("two", "Two", "Switch", "room-b", "cat-b", subcontrols=(child,)),
            _control("one", "One", "Dimmer", "room-a", "cat-a"),
            _control("three", "Three", "Switch", "room-b", "cat-b"),
        ),
        hidden_controls=(_control("hidden", "Hidden", "Switch", "hidden-room", None, hidden=True),),
        hidden_rooms=(NamedGroup("hidden-room", "Hidden"),),
    )

    result = structure_overview(structure, max_items=50)

    assert [item.uuid for item in visible_controls(structure)] == ["two", "child", "one", "three"]
    assert result["counts"] == {"controls": 4, "rooms": 3, "categories": 2, "control_types": 2}
    assert result["rooms"]["items"] == [
        {"assignment": "assigned", "uuid": "room-b", "name": "Beta", "control_count": 2},
        {"assignment": "unassigned", "uuid": None, "name": None, "control_count": 1},
        {"assignment": "assigned", "uuid": "room-a", "name": "Alpha", "control_count": 1},
        {"assignment": "assigned", "uuid": "room-empty", "name": "Empty", "control_count": 0},
    ]
    assert result["categories"]["items"][1] == {
        "assignment": "unassigned",
        "uuid": None,
        "name": None,
        "control_count": 1,
    }
    assert result["control_types"]["items"] == [
        {"type": "Switch", "control_count": 3},
        {"type": "Dimmer", "control_count": 1},
    ]


def test_structure_overview_applies_per_breakdown_limit() -> None:
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="1",
        rooms=tuple(Room(f"room-{index}", f"Room {index}") for index in range(60)),
        categories=(),
        controls=(),
    )

    result = structure_overview(structure, max_items=50)

    assert result["counts"]["rooms"] == 60
    assert result["rooms"]["returned"] == 50
    assert result["rooms"]["total"] == 60
    assert result["rooms"]["truncated"] is True
    assert result["rooms"]["complete"] is False


@pytest.mark.asyncio
async def test_structure_overview_tool_is_bounded_stale_and_uses_one_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    long_name = "x" * 2_000
    rooms = tuple(Room(f"room-{index}", f"{long_name}-{index}") for index in range(50))
    categories = tuple(NamedGroup(f"category-{index}", f"Category {index}") for index in range(50))
    controls = tuple(
        _control(
            f"control-{index}",
            f"Control {index}",
            f"Type {index}",
            rooms[index].uuid,
            categories[index].uuid,
        )
        for index in range(50)
    )
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="99",
        rooms=rooms,
        categories=categories,
        controls=controls,
    )

    async def snapshot(_runtime: object) -> tuple[StoredAccessToken, RuntimeSnapshot]:
        nonlocal calls
        calls += 1
        return _access(), RuntimeSnapshot("family", structure, False, 7)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("structure-overview")
    register_read_tools(server, None)
    tool = server._tool_manager.get_tool("loxone_get_structure_overview")
    assert tool is not None

    result = await tool.fn()

    assert calls == 1
    assert result.ok is True
    assert result.stale is True
    assert result.data.scope == "authorized_visible_structure"  # type: ignore[union-attr]
    assert result.data.structure_generation == 7  # type: ignore[union-attr]
    assert result.data.counts.controls == 50  # type: ignore[union-attr]
    assert result.data.rooms.truncated is True  # type: ignore[union-attr]
    assert result.data.categories.complete is True  # type: ignore[union-attr]
    assert result.data.control_types.complete is True  # type: ignore[union-attr]
    assert len(result.model_dump_json().encode("utf-8")) <= STRUCTURE_OVERVIEW_MAX_BYTES


@pytest.mark.asyncio
async def test_structure_overview_matches_default_control_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _control("child", "Child", "Switch", None, None)
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="1",
        rooms=(),
        categories=(),
        controls=(_control("parent", "Parent", "Switch", None, None, subcontrols=(child,)),),
        hidden_controls=(_control("hidden", "Hidden", "Switch", None, None, hidden=True),),
    )

    async def snapshot(_runtime: object) -> tuple[StoredAccessToken, RuntimeSnapshot]:
        return _access(), RuntimeSnapshot("family", structure, True)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("structure-overview-corpus")
    register_read_tools(server, None)

    overview = await server._tool_manager.get_tool("loxone_get_structure_overview").fn()  # type: ignore[union-attr]
    discovery = await server._tool_manager.get_tool("loxone_find_controls").fn()  # type: ignore[union-attr]

    assert overview.data.counts.controls == len(discovery.data.items) == 2  # type: ignore[union-attr]
    assert [item.uuid for item in discovery.data.items] == ["parent", "child"]  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_structure_overview_distinguishes_empty_from_oversized_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="",
        rooms=(),
        categories=(),
        controls=(),
    )

    async def snapshot(_runtime: object) -> tuple[StoredAccessToken, RuntimeSnapshot]:
        return _access(), RuntimeSnapshot("family", structure, True)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("structure-overview-empty")
    register_read_tools(server, None)
    tool = server._tool_manager.get_tool("loxone_get_structure_overview")
    assert tool is not None

    empty = await tool.fn()
    assert empty.ok is True
    assert empty.data.counts.controls == 0  # type: ignore[union-attr]
    assert empty.data.rooms.complete is True  # type: ignore[union-attr]

    object.__setattr__(structure, "last_modified", "x" * STRUCTURE_OVERVIEW_MAX_BYTES)
    oversized = await tool.fn()
    assert oversized.ok is False
    assert oversized.data.error == "temporarily_unavailable"  # type: ignore[union-attr]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (PermissionError(), "unauthenticated"),
        (RuntimeUnavailable("offline"), "temporarily_unavailable"),
    ],
)
async def test_structure_overview_tool_preserves_standard_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    code: str,
) -> None:
    async def snapshot(_runtime: object) -> tuple[StoredAccessToken, RuntimeSnapshot]:
        raise error

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("structure-overview-errors")
    register_read_tools(server, None)

    result = await server._tool_manager.get_tool("loxone_get_structure_overview").fn()  # type: ignore[union-attr]

    assert result.ok is False
    assert result.data.error == code  # type: ignore[union-attr]
