"""Exact runtime suffix identities across local history boundaries (#553)."""

import time
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

import mcpserver.tools as tools
from mcpserver import admin, event_history_admin
from mcpserver.auth.provider import HISTORY_SCOPE, READ_SCOPE, StoredAccessToken
from mcpserver.config import AtomicConfigStore, ConfigError, PluginConfig
from mcpserver.loxone.event_history import EventHistoryStore
from mcpserver.loxone.structure import normalize_structure
from mcpserver.loxone.uuid import normalize_history_control_id, normalize_loxone_uuid

PARENT = "00000000-0000-0000-0000000000000001"
CHILD = PARENT + "/AI1"
SIBLING = PARENT + "/AI2"
STATE = "00000000-0000-0000-0000000000000002"
OTHER_STATE = "00000000-0000-0000-0000000000000003"


def access(*scopes):
    return StoredAccessToken(
        token="synthetic",
        client_id="client",
        family_id="family",
        identity_id="identity",
        miniserver_id="miniserver",
        scopes=list(scopes),
        expires_at=2_000_000_000,
    )


@pytest.mark.parametrize(
    "suffix",
    ["AI1", "ai1", "generated-key", "AI1/channel:2", "zone 1", "../AI1", "", "/AI1", "AI1\n"],
)
def test_suffix_identity_is_opaque_and_exact(suffix):
    value = PARENT + "/" + suffix
    assert normalize_history_control_id(value) == value
    with pytest.raises(ValueError):
        normalize_loxone_uuid(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        1,
        "",
        "bad/AI1",
        PARENT + "/" + "x" * 128,
    ],
)
def test_malformed_history_control_ids_are_rejected(value):
    with pytest.raises(ValueError):
        normalize_history_control_id(value)


def test_plain_uuid_compatibility_and_config_round_trip(tmp_path):
    assert normalize_history_control_id("00000000-0000-0000-0000-000000000001") == PARENT
    path = (tmp_path / "config.json").resolve()
    store = AtomicConfigStore(path)
    config = PluginConfig(
        loxone_history_enabled=True,
        event_history_enabled=True,
        event_history_sources=(
            (CHILD, STATE),
            (SIBLING, STATE),
            (PARENT + "/zone 1", STATE),
            (PARENT + "/../AI1", STATE),
        ),
    )
    store.save(config)
    assert store.load().event_history_sources == config.event_history_sources
    for sources in (((CHILD, STATE + "/AI1"),), ((CHILD, STATE), (CHILD, STATE))):
        with pytest.raises(ConfigError):
            PluginConfig.from_document(replace(config, event_history_sources=sources).to_document())


@pytest.fixture
def history(tmp_path, monkeypatch):
    structure = normalize_structure(
        {
            "msInfo": {"serialNr": "synthetic"},
            "controls": {
                PARENT: {
                    "name": "Parent",
                    "type": "LightControllerV2",
                    "states": {"active": STATE},
                    "subControls": {
                        CHILD: {"name": "Child", "type": "Switch", "states": {"active": STATE}},
                        SIBLING: {"name": "Sibling", "type": "Switch", "states": {"active": STATE}},
                    },
                }
            },
        },
        username="reader",
    )
    config = AtomicConfigStore((tmp_path / "config.json").resolve())
    config.save(
        PluginConfig(
            loxone_history_enabled=True,
            event_history_enabled=True,
            event_history_sources=((CHILD, STATE),),
        )
    )
    store = EventHistoryStore(
        (tmp_path / "history.sqlite3").resolve(), retention_days=90, maximum_mib=16
    )
    store.initialize()
    now = time.time()
    for control, values in ((PARENT, (90, 91)), (SIBLING, (80, 81)), (CHILD, (10, 11))):
        store.begin_coverage(((control, STATE),), started_at=now - 120)
        for index, value in enumerate(values):
            store.record_transition(
                control, STATE, observed_at=now - 30 + index, old_value=value - 1, new_value=value
            )

    @asynccontextmanager
    async def slot(_access=None):
        yield

    class Runtime:
        history_call_slot = staticmethod(slot)
        worker_slot = staticmethod(slot)
        visible = True

        async def snapshot(self, _access, *, fresh_visibility=False):
            assert fresh_visibility
            current = (
                structure
                if self.visible
                else replace(structure, controls=(replace(structure.controls[0], subcontrols=()),))
            )
            return SimpleNamespace(structure=current)

    native = Runtime()
    runtime = tools.EventHistoryRuntime(native, config, store.path)
    server = FastMCP("suffix-history")
    tools.register_event_history_tools(server, runtime)
    monkeypatch.setattr(tools, "_access", lambda: access(READ_SCOPE, HISTORY_SCOPE))
    args = {
        "control_uuid": CHILD,
        "state_uuid": STATE,
        "start": datetime.fromtimestamp(now - 60, UTC).isoformat(),
        "end": datetime.fromtimestamp(now, UTC).isoformat(),
        "limit": 1,
    }
    return server, runtime, native, config, store, args


@pytest.mark.asyncio
async def test_real_reader_keeps_child_storage_coverage_and_cursors_separate(history, monkeypatch):
    server, runtime, native, config, store, args = history

    async def call(arguments):
        return await server._tool_manager.call_tool("loxone_get_event_history", arguments)

    first = await call(args)
    assert first.ok and first.data.control_uuid == CHILD
    assert first.data.coverage == "complete"
    assert [entry.new_value for entry in first.data.entries] == [11]
    assert first.data.next_cursor
    second = await call(dict(args, cursor=first.data.next_cursor))
    assert second.ok and [entry.new_value for entry in second.data.entries] == [10]
    assert second.data.next_cursor is None
    for changed in ({"control_uuid": SIBLING}, {"state_uuid": OTHER_STATE}):
        rejected = await call(dict(args, cursor=first.data.next_cursor, **changed))
        assert not rejected.ok and rejected.data.error == "invalid_input"
    monkeypatch.setattr(
        tools,
        "_access",
        lambda: access(READ_SCOPE, HISTORY_SCOPE).model_copy(update={"family_id": "another"}),
    )
    assert not (await call(dict(args, cursor=first.data.next_cursor))).ok
    monkeypatch.setattr(tools, "_access", lambda: access(READ_SCOPE, HISTORY_SCOPE))
    native.visible = False
    hidden = await call(args)
    assert not hidden.ok and hidden.data.error == "not_found"


@pytest.mark.asyncio
async def test_no_parent_or_state_fallback_and_scope_gates(history, monkeypatch):
    server, runtime, native, config, store, args = history

    async def call(**changes):
        return await server._tool_manager.call_tool(
            "loxone_get_event_history", dict(args, **changes)
        )

    unknown = await call(control_uuid=PARENT + "/ai1")
    assert not unknown.ok and unknown.data.error == "not_found"
    wrong_state = await call(state_uuid=OTHER_STATE)
    assert not wrong_state.ok and wrong_state.data.error == "not_found"
    invalid_state = await call(state_uuid=STATE + "/AI1")
    assert not invalid_state.ok and invalid_state.data.error == "invalid_input"
    monkeypatch.setattr(tools, "_access", lambda: access(READ_SCOPE))
    denied = await call()
    assert not denied.ok and denied.data.error == "permission_denied"
    monkeypatch.setattr(tools, "_access", lambda: access(READ_SCOPE, HISTORY_SCOPE))
    config.save(replace(config.load(), event_history_enabled=False))
    disabled = await call()
    assert not disabled.ok and disabled.data.error == "feature_disabled"


@pytest.mark.asyncio
async def test_removed_child_evidence_requires_fresh_exact_visibility(history):
    server, runtime, native, config, store, args = history
    store.end_coverage(((CHILD, STATE),), ended_at=time.time(), outcome="stopped")
    store.mark_removed(CHILD, STATE, removed_at=time.time())
    config.save(replace(config.load(), event_history_sources=()))
    result = await server._tool_manager.call_tool("loxone_get_event_history", args)
    assert result.ok and result.data.recording_status == "removed"
    assert result.data.entries[0].new_value == 11
    native.visible = False
    result = await server._tool_manager.call_tool("loxone_get_event_history", args)
    assert not result.ok and result.data.error == "not_found"


@pytest.mark.asyncio
async def test_visible_unrecorded_child_returns_not_found(history):
    server, runtime, native, config, store, args = history
    store.purge_source(CHILD, STATE)
    config.save(replace(config.load(), event_history_sources=()))
    result = await server._tool_manager.call_tool("loxone_get_event_history", args)
    assert not result.ok and result.data.error == "not_found"


def test_admin_source_and_state_discovery_keep_child_identity(history, monkeypatch):
    server, runtime, native, config, store, args = history
    monkeypatch.setattr(admin, "_config_store", lambda: config)
    child = SimpleNamespace(
        uuid=CHILD, name="Child", control_type="Switch", state_uuids=(("active", STATE),)
    )
    monkeypatch.setattr(event_history_admin, "_controls", lambda _config: (child,))
    assert event_history_admin._source(args) == (CHILD, STATE)
    assert event_history_admin.discover_states({"control_uuid": CHILD})["states"] == [
        {"name": "active", "uuid": STATE}
    ]
    with pytest.raises(admin.AdminError):
        event_history_admin._source(dict(args, state_uuid=STATE + "/AI1"))


@pytest.mark.asyncio
async def test_existing_source_tool_boundaries_preserve_suffix(history, monkeypatch):
    server, runtime, native, config, store, args = history
    received = []

    class Operations:
        async def add_event_history_source(self, _access, control, state):
            received.append(("add", control, state))
            return True, ("Child", "Switch", "active")

        async def remove_event_history_source(self, _access, control, state):
            received.append(("remove", control, state))
            return True

        async def purge_event_history_source(self, _access, control, state):
            received.append(("purge", control, state))
            return 2, 1

    tools.register_loxberry_operate_tool(server, Operations())
    for action in ("add", "remove", "purge"):
        result = await server._tool_manager.call_tool(
            f"loxberry_{action}_event_history_source",
            {
                "control_uuid": CHILD,
                "state_uuid": STATE,
                **({"confirm": True} if action == "purge" else {}),
            },
        )
        assert result.ok
    assert received == [(action, CHILD, STATE) for action in ("add", "remove", "purge")]
