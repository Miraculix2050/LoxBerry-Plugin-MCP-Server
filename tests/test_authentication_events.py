from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from mcp.server.fastmcp import FastMCP

import mcpserver.loxone.auth_diagnostics as diagnostics_module
import mcpserver.tools as tools_module
from mcpserver.auth.provider import StoredAccessToken
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.loxone.auth_diagnostics import (
    MiniserverAuthCoordinator,
    authentication_binding,
)
from mcpserver.loxone.runtime import LoxoneRuntime, RuntimeAuthorizationError
from mcpserver.tools import register_authentication_diagnostics_tool


def _access(**changes: Any) -> StoredAccessToken:
    return StoredAccessToken(
        token="opaque",
        client_id="client",
        scopes=["loxone:read"],
        expires_at=2_000_000_000,
        resource="https://example.invalid/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="miniserver",
    ).model_copy(update=changes)


def _event(binding: str = "own", **changes: Any) -> dict[str, Any]:
    return {
        "timestamp": int(time.time()),
        "connection_owner": "tool_request",
        "phase": "token_authentication",
        "outcome": "authenticated",
        "binding_id": binding,
        **changes,
    }


def _coordinator(tmp_path: Path, events: list[Any]) -> MiniserverAuthCoordinator:
    coordinator = MiniserverAuthCoordinator(tmp_path / "diagnostics.json")
    coordinator._state["events"] = events
    coordinator._save()
    return coordinator


def _runtime(coordinator: MiniserverAuthCoordinator) -> LoxoneRuntime:
    runtime = object.__new__(LoxoneRuntime)
    runtime._closed = False
    runtime.auth_coordinator = coordinator
    runtime.auth_binding = lambda access: "own" if access.client_id == "client" else "foreign"

    async def valid(access: StoredAccessToken) -> bool:
        return (
            "loxone:read" in access.scopes
            and access.expires_at is not None
            and access.expires_at > time.time()
        )

    runtime.validate_authentication_diagnostics_access = valid
    return runtime


def test_binding_separates_each_verified_identifier_and_survives_new_login(tmp_path: Path) -> None:
    store = AtomicJsonAuthStore((tmp_path / "auth.json").resolve())
    own = authentication_binding(store, "client", "identity", "miniserver")
    assert own == authentication_binding(store, "client", "identity", "miniserver")
    assert own != authentication_binding(store, "other-client", "identity", "miniserver")
    assert own != authentication_binding(store, "client", "other-identity", "miniserver")
    assert own != authentication_binding(store, "client", "identity", "other-miniserver")
    assert own != store.pseudonym("loxberry-read-binding-v1", '["client","identity","miniserver"]')


def test_projection_redacts_secrets_and_reads_without_saves_or_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _coordinator(
        tmp_path,
        [
            _event("foreign", private="foreign-secret"),
            _event(private="own-secret", trace_id="unsafe-text", arbitrary={"token": "secret"}),
            _event(connection_owner="runtime_event_stream"),
        ],
    )
    before = coordinator._path.read_bytes()

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("A diagnostic read attempted to save or lock")

    monkeypatch.setattr(coordinator, "_save", forbidden)
    monkeypatch.setattr(diagnostics_module, "_interprocess_lock", forbidden)
    snapshot = coordinator.diagnostic_snapshot("own")
    assert snapshot["history_status"] == "bounded"
    assert len(snapshot["events"]) == 1
    assert set(snapshot["events"][0]) == {"timestamp", "connection_owner", "phase", "outcome"}
    assert "secret" not in json.dumps(snapshot)
    assert "binding_id" not in json.dumps(snapshot)
    assert coordinator._path.read_bytes() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("timestamp", True),
        ("phase", "future_phase"),
        ("outcome", "credential-secret"),
        ("phase", []),
        ("outcome", {}),
    ],
)
def test_invalid_own_events_are_incomplete_not_exposed(
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    coordinator = _coordinator(tmp_path, [_event(**{field: value})])
    snapshot = coordinator.diagnostic_snapshot("own")
    assert snapshot["events"] == []
    assert snapshot["history_status"] == "incomplete"


def test_retention_and_foreign_malformed_events_do_not_claim_complete_history(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(
        tmp_path,
        [
            _event(timestamp=int(time.time()) - 31 * 86400),
            _event("foreign", phase="unknown"),
            _event(timestamp=int(time.time()) - 2),
            _event(timestamp=int(time.time()) - 1),
        ],
    )
    snapshot = coordinator.diagnostic_snapshot("own")
    assert len(snapshot["events"]) == 2
    assert snapshot["events"][0]["timestamp"] > snapshot["events"][1]["timestamp"]
    assert snapshot["history_status"] == "bounded"


@pytest.mark.parametrize(
    "payload",
    [b"{", b"[]", b"{}", b"x" * (1024 * 1024 + 1)],
    ids=["truncated", "array", "empty", "oversized"],
)
def test_unreadable_history_is_unavailable_and_unchanged(tmp_path: Path, payload: bytes) -> None:
    coordinator = _coordinator(tmp_path, [])
    coordinator._path.write_bytes(payload)
    snapshot = coordinator.diagnostic_snapshot("own")
    assert snapshot["history_status"] == "unavailable"
    assert snapshot["events"] == []
    assert coordinator._path.read_bytes() == payload


@pytest.mark.asyncio
async def test_runtime_rechecks_authorization_after_projection(tmp_path: Path) -> None:
    runtime = _runtime(_coordinator(tmp_path, [_event()]))
    calls = 0

    async def revoked_during_read(access: StoredAccessToken) -> bool:
        nonlocal calls
        calls += 1
        return calls == 1

    runtime.validate_authentication_diagnostics_access = revoked_during_read
    with pytest.raises(PermissionError):
        await runtime.authentication_diagnostics(_access())
    assert calls == 2


@pytest.mark.asyncio
async def test_real_tool_binding_history_and_cursor_security(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _coordinator(
        tmp_path, [_event(timestamp=int(time.time()) - n) for n in (3, 2, 1)]
    )
    runtime = _runtime(coordinator)
    access = _access()
    monkeypatch.setattr(tools_module, "_access", lambda: access)
    server = FastMCP("authentication-events")
    register_authentication_diagnostics_tool(server, runtime)
    tool = server._tool_manager.list_tools()[0]
    assert tool.name == "loxone_list_authentication_events"
    assert tool.annotations is not None and tool.annotations.readOnlyHint
    name = tool.name
    first = await server._tool_manager.call_tool(name, {"limit": 1})
    assert first.ok and first.data.next_cursor
    cursor = first.data.next_cursor
    second = await server._tool_manager.call_tool(name, {"limit": 1, "cursor": cursor})
    assert second.ok and second.data.events[0].timestamp != first.data.events[0].timestamp
    tampered = await server._tool_manager.call_tool(name, {"limit": 1, "cursor": "x" + cursor[1:]})
    assert not tampered.ok and tampered.data.error == "invalid_input"
    coordinator._state["events"].append(_event("foreign", phase="future_phase"))
    coordinator._save()
    foreign_change = await server._tool_manager.call_tool(name, {"limit": 1, "cursor": cursor})
    assert foreign_change.ok
    coordinator._state["events"].append(_event())
    coordinator._save()
    own_change = await server._tool_manager.call_tool(name, {"limit": 1, "cursor": cursor})
    assert not own_change.ok and own_change.data.error == "invalid_input"
    current = await server._tool_manager.call_tool(name, {"limit": 1})
    cursor = current.data.next_cursor
    access = access.model_copy(update={"family_id": "renewed-family"})
    renewed = await server._tool_manager.call_tool(name, {"limit": 1})
    assert renewed.ok and renewed.data.events
    old_family_cursor = await server._tool_manager.call_tool(name, {"limit": 1, "cursor": cursor})
    assert not old_family_cursor.ok and old_family_cursor.data.error == "invalid_input"
    access = access.model_copy(update={"client_id": "foreign-client"})
    isolated = await server._tool_manager.call_tool(name, {})
    assert isolated.ok and len(isolated.data.events) == 0
    access = access.model_copy(update={"scopes": []})
    denied = await server._tool_manager.call_tool(name, {})
    assert not denied.ok and denied.data.error == "permission_denied"
    access = access.model_copy(update={"scopes": ["loxone:read"], "expires_at": 1})
    expired = await server._tool_manager.call_tool(name, {})
    assert not expired.ok and expired.data.error == "permission_denied"


@pytest.mark.asyncio
async def test_tool_restart_invalidates_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(_coordinator(tmp_path, [_event(), _event()]))
    monkeypatch.setattr(tools_module, "_access", _access)
    server = FastMCP("before-restart")
    register_authentication_diagnostics_tool(server, runtime)
    first = await server._tool_manager.call_tool("loxone_list_authentication_events", {"limit": 1})
    restarted = FastMCP("after-restart")
    register_authentication_diagnostics_tool(restarted, runtime)
    result = await restarted._tool_manager.call_tool(
        "loxone_list_authentication_events",
        {"limit": 1, "cursor": first.data.next_cursor},
    )
    assert not result.ok and result.data.error == "invalid_input"


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", ["tool_request", "runtime_event_stream"])
async def test_session_provenance_belongs_only_to_initiating_tool(
    tmp_path: Path,
    owner: str,
) -> None:
    coordinator = _coordinator(tmp_path, [])
    runtime = _runtime(coordinator)
    calls = 0

    async def open_session(token: Any) -> Any:
        nonlocal calls
        calls += 1
        return object()

    runtime.client = cast(Any, SimpleNamespace(timeout_seconds=1, open_session=open_session))
    await runtime._open_session(
        cast(Any, object()),
        owner=owner,
        phase="session_establishment",
        access=_access(),
    )
    assert calls == 1
    events = coordinator.diagnostic_snapshot("own")["events"]
    assert bool(events) is (owner == "tool_request")
    assert all(event["connection_owner"] == "tool_request" for event in events)
    assert "trace_id" not in json.dumps(events)


@pytest.mark.asyncio
async def test_authorization_revoked_while_session_waits_prevents_network(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path, [])
    runtime = _runtime(coordinator)
    allowed = True
    calls = 0

    async def valid(access: StoredAccessToken) -> bool:
        return allowed

    async def open_session(token: Any) -> Any:
        nonlocal calls
        calls += 1
        return object()

    runtime._validate_access = valid
    runtime.client = cast(Any, SimpleNamespace(timeout_seconds=1, open_session=open_session))
    await coordinator._lock.acquire()
    task = asyncio.create_task(
        runtime._open_session(
            cast(Any, object()),
            owner="tool_request",
            phase="session_establishment",
            access=_access(),
        )
    )
    await asyncio.sleep(0)
    allowed = False
    coordinator._lock.release()
    with pytest.raises(RuntimeAuthorizationError):
        await task
    assert calls == 0
    assert coordinator.diagnostic_snapshot("own")["events"] == []
