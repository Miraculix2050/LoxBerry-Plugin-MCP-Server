from __future__ import annotations

import json
from collections import Counter

import pytest
from mcp.server.fastmcp import FastMCP

import mcpserver.tools as tools_module
from mcpserver.auth.provider import READ_SCOPE, StoredAccessToken
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure, NamedGroup, Room
from mcpserver.loxone.presentation import structure_overview, visible_controls
from mcpserver.loxone.runtime import RuntimeSnapshot, RuntimeUnavailable
from mcpserver.loxone.structure import normalize_structure
from mcpserver.schema_reference import schema_reference_json
from mcpserver.tools import STRUCTURE_OVERVIEW_MAX_BYTES, register_read_tools


@pytest.mark.asyncio
async def test_overview_published_schema_explains_counts_without_new_fields() -> None:
    server = FastMCP("overview-schema")
    register_read_tools(server, None)
    published = next(
        t for t in await server.list_tools() if t.name == "loxone_get_structure_overview"
    )
    reference = next(
        t for t in json.loads(schema_reference_json("test"))["tools"] if t["name"] == published.name
    )
    assert published.outputSchema == reference["outputSchema"]
    definitions = published.outputSchema["$defs"]
    expected = {
        "StructureOverviewCountsData": {"controls", "rooms", "categories", "control_types"},
        "StructureOverviewGroupItemData": {"assignment", "uuid", "name", "control_count"},
        "StructureOverviewTypeItemData": {"type", "control_count"},
        "StructureOverviewGroupBreakdownData": {
            "items",
            "returned",
            "total",
            "truncated",
            "complete",
        },
        "StructureOverviewTypeBreakdownData": {
            "items",
            "returned",
            "total",
            "truncated",
            "complete",
        },
    }
    for model, fields in expected.items():
        properties = definitions[model]["properties"]
        assert set(properties) == fields
        assert all(properties[field]["description"] for field in fields)
    counts = definitions["StructureOverviewCountsData"]["properties"]
    for field in ("rooms", "categories"):
        assert "excludes the synthetic unassigned bucket" in counts[field]["description"]
        assert f"{field}.total" in counts[field]["description"]
    assert (
        "even if it is not delivered"
        in definitions["StructureOverviewGroupBreakdownData"]["properties"]["total"]["description"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "assignments",
    [
        ("assigned",),
        ("missing",),
        ("unresolved",),
        ("assigned", "missing", "unresolved", "room_only", "category_only"),
    ],
)
async def test_normalized_overview_matches_paginated_discovery(monkeypatch, assignments) -> None:
    controls = {}
    references = {
        "assigned": {"room": "room", "cat": "cat"},
        "missing": {},
        "unresolved": {"room": "unknown-room", "cat": "unknown-cat"},
        "room_only": {"room": "room"},
        "category_only": {"cat": "cat"},
    }
    for index, assignment in enumerate(assignments):
        controls[f"control-{index}"] = {
            "name": f"Control {index}",
            "type": "Switch",
            **references[assignment],
        }
    controls["parent"] = {
        "name": "Parent",
        "type": "Dimmer",
        "subControls": {"child": {"name": "Child", "type": "Switch", "room": "room", "cat": "cat"}},
    }
    controls["secret-control"] = {
        "name": "Secret",
        "type": "Switch",
        "room": "secret-room",
        "cat": "secret-cat",
        "restrictions": 1,
    }
    structure = normalize_structure(
        {
            "msInfo": {"serialNr": "serial"},
            "rooms": {key: {"name": key} for key in ("room", "empty-room", "secret-room")},
            "cats": {key: {"name": key} for key in ("cat", "empty-cat", "secret-cat")},
            "controls": controls,
        },
        username="reader",
    )

    async def snapshot(_runtime):
        return _access(), RuntimeSnapshot("family", structure, True)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("overview-normalized")
    register_read_tools(server, None)
    result = await server._tool_manager.get_tool("loxone_get_structure_overview").fn()
    discovery = server._tool_manager.get_tool("loxone_find_controls")
    items = []
    cursor = None
    while True:
        page = await discovery.fn(limit=1, cursor=cursor)
        items.extend(page.data.items)
        cursor = page.data.next_cursor
        if cursor is None:
            break
    assert {item.uuid for item in items} == {item.uuid for item in visible_controls(structure)}
    assert result.data.counts.controls == len(items)
    assert "child" in {item.uuid for item in items}
    encoded = result.model_dump_json()
    assert "secret" not in encoded and "empty-room" not in encoded and "empty-cat" not in encoded
    for field, reference_field, groups in (
        ("rooms", "room_uuid", structure.rooms),
        ("categories", "category_uuid", structure.categories),
    ):
        breakdown = getattr(result.data, field)
        known = {group.uuid for group in groups}
        expected = Counter(
            getattr(item, reference_field) if getattr(item, reference_field) in known else None
            for item in visible_controls(structure)
        )
        assert {item.uuid: item.control_count for item in breakdown.items} == dict(expected)
        assert breakdown.total == getattr(result.data.counts, field) + int(None in expected)
        assert sum(item.control_count for item in breakdown.items) == len(items)
    assert {item.type: item.control_count for item in result.data.control_types.items} == dict(
        Counter(item.control_type for item in visible_controls(structure))
    )


@pytest.mark.parametrize(
    "room_ref,category_ref",
    [("room", "cat"), (None, None), ("unknown-room", "unknown-cat"), ("room", None), (None, "cat")],
)
def test_overview_assigned_and_unassigned_totals(room_ref, category_ref) -> None:
    raw = {
        "msInfo": {"serialNr": "serial"},
        "rooms": {"room": {"name": "Room"}},
        "cats": {"cat": {"name": "Category"}},
        "controls": {
            "control": {"name": "Control", "type": "Switch", "room": room_ref, "cat": category_ref}
        },
    }
    result = structure_overview(normalize_structure(raw, username="reader"), max_items=50)
    for field, assigned in (("rooms", room_ref == "room"), ("categories", category_ref == "cat")):
        assert result["counts"][field] == int(assigned)
        assert result[field]["total"] == 1
        assert result[field]["items"][0]["assignment"] == ("assigned" if assigned else "unassigned")


@pytest.mark.asyncio
@pytest.mark.parametrize("byte_limit", [False, True])
async def test_truncation_can_omit_unassigned_without_changing_totals(
    monkeypatch, byte_limit
) -> None:
    count = 4 if byte_limit else 51
    controls = (
        *(
            _control(f"c{i}-{j}", "Control", "Switch", f"r{i}", f"k{i}")
            for i in range(count)
            for j in range(2)
        ),
        _control("unassigned", "Unassigned", "Switch", None, None),
    )
    structure = LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="1",
        rooms=tuple(Room(f"r{i}", f"Room {i}") for i in range(count)),
        categories=tuple(NamedGroup(f"k{i}", f"Category {i}") for i in range(count)),
        controls=controls,
    )

    async def snapshot(_runtime):
        return _access(), RuntimeSnapshot("family", structure, True)

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("overview-truncation")
    register_read_tools(server, None)
    tool = server._tool_manager.get_tool("loxone_get_structure_overview")
    if byte_limit:
        full = await tool.fn()
        monkeypatch.setattr(
            tools_module,
            "STRUCTURE_OVERVIEW_MAX_BYTES",
            len(full.model_dump_json().encode("utf-8")) - 200,
        )
    result = await tool.fn()
    assert result.ok
    assert result.data.counts.controls == len(controls)
    assert result.data.counts.rooms == result.data.counts.categories == count
    assert (
        len(result.model_dump_json().encode("utf-8")) <= tools_module.STRUCTURE_OVERVIEW_MAX_BYTES
    )
    omitted = []
    for breakdown in (result.data.rooms, result.data.categories):
        assert breakdown.total == count + 1
        assert breakdown.returned == len(breakdown.items)
        assert breakdown.truncated == (breakdown.returned < breakdown.total)
        assert breakdown.complete == (breakdown.returned == breakdown.total)
        if breakdown.truncated:
            assert all(item.assignment == "assigned" for item in breakdown.items)
            assert sum(item.control_count for item in breakdown.items) < len(controls)
            omitted.append(breakdown)
    assert omitted


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
