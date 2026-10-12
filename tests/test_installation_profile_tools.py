from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP

from mcpserver.installation_profile import BindingInput, ProfileStore, installation_identity
from mcpserver.installation_profile_tools import register_profile_read_tool
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import RuntimeAuthorizationError

CONTROL = "00000001-0000-0000-0000000000000001"
STATE = "00000002-0000-0000-0000000000000002"


@pytest.fixture(autouse=True)
def caller_access(monkeypatch):
    monkeypatch.setattr("mcpserver.tools._access", lambda: object())


def _runtime(structure, *, snapshot=None, require_access=None):
    reader = snapshot or AsyncMock(return_value=(object(), SimpleNamespace(structure=structure)))
    authorize = require_access or AsyncMock()

    @asynccontextmanager
    async def context(access, *, fresh_visibility):
        _, value = await reader(fresh_visibility=fresh_visibility)
        yield value
        await authorize(access)

    return SimpleNamespace(
        endpoint=SimpleNamespace(origin="http://synthetic.local"),
        snapshot_context=context,
        _require_access=authorize,
    )


@pytest.mark.asyncio
async def test_profile_output_bounds_entire_envelope_and_smaller_page_remains_usable(
    tmp_path, monkeypatch
):
    from mcpserver.installation_profile import ProfileDocument

    control = Control(CONTROL, "Synthetic", "InfoOnlyAnalog", None, None, None, (("value", STATE),))
    structure = LoxoneStructure(LoxoneIdentity("synthetic", "serial"), "v1", (), (), (control,))
    installation = installation_identity("http://synthetic.local", structure)
    store = ProfileStore(tmp_path / "profile.json")
    binding = BindingInput(
        binding_id="pv",
        role="production",
        source_kind="state",
        control_uuid=CONTROL,
        state_uuid=STATE,
        confirmed=True,
        pv_parameters={"arrays": [{"array_id": f"a{i}", "shading": "\\" * 256} for i in range(16)]},
    )
    stored = store.put(
        installation,
        0,
        binding,
        control,
        origin="local_admin",
        actor_ref=hashlib.sha256(b"synthetic").hexdigest(),
    ).bindings[0]
    store._write(
        ProfileDocument(
            installation=installation,
            revision=1,
            bindings=[stored.model_copy(update={"binding_id": f"pv{i}"}) for i in range(8)],
        )
    )
    server = FastMCP("profile-bounds")
    register_profile_read_tool(
        server,
        _runtime(structure),
        store.path,
    )
    tool = server._tool_manager.get_tool("loxone_get_installation_profile")
    rejected = await tool.fn()
    assert not rejected.ok and rejected.data.error == "response_too_large"
    page = await tool.fn(limit=1)
    assert page.ok and page.data.next_offset == 1 and len(page.model_dump_json().encode()) < 65536


@pytest.mark.asyncio
async def test_each_profile_read_and_page_uses_fresh_visibility(tmp_path, monkeypatch):
    control = Control(CONTROL, "Synthetic", "InfoOnlyAnalog", None, None, None, (("value", STATE),))
    structure = LoxoneStructure(
        LoxoneIdentity("synthetic-user", "synthetic-serial"), "v1", (), (), (control,)
    )
    installation = installation_identity("http://synthetic.local", structure)
    path = tmp_path / "installation-profile.json"
    binding = BindingInput(
        binding_id="room",
        role="actual_temperature",
        control_uuid=CONTROL,
        source_kind="state",
        state_uuid=STATE,
        confirmed=True,
    )
    ProfileStore(path).put(
        installation,
        0,
        binding,
        control,
        origin="local_admin",
        actor_ref=hashlib.sha256(b"synthetic").hexdigest(),
    )
    snapshot = AsyncMock(return_value=(object(), SimpleNamespace(structure=structure)))
    server = FastMCP("profile-test")
    runtime = _runtime(structure, snapshot=snapshot)
    register_profile_read_tool(server, runtime, path)
    tool = server._tool_manager.get_tool("loxone_get_installation_profile")
    first = await tool.fn()
    assert first.ok and first.data.bindings[0].status == "confirmed"
    second = await tool.fn(offset=1)
    assert second.ok and second.data.bindings == []
    assert snapshot.await_count == 2
    assert runtime._require_access.await_count == 2
    assert all(call.kwargs == {"fresh_visibility": True} for call in snapshot.await_args_list)
    snapshot.side_effect = RuntimeAuthorizationError("private-marker")
    rejected = await tool.fn()
    assert not rejected.ok and rejected.data.error == "permission_denied"
    assert "private-marker" not in rejected.model_dump_json()


@pytest.mark.asyncio
async def test_profile_not_configured_is_read_only_and_unavailable():
    server = FastMCP("profile-unavailable")
    register_profile_read_tool(server, None, None)
    tool = server._tool_manager.get_tool("loxone_get_installation_profile")
    assert tool.annotations.readOnlyHint is True
    result = await tool.fn()
    assert not result.ok and result.data.error == "temporarily_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["revoked", "expired"])
async def test_caller_revocation_during_profile_worker_read_blocks_publication(
    tmp_path, monkeypatch, reason
):
    control = Control(CONTROL, "Synthetic", "InfoOnlyAnalog", None, None, None, (("value", STATE),))
    structure = LoxoneStructure(LoxoneIdentity("synthetic", "serial"), "v1", (), (), (control,))
    installation = installation_identity("http://synthetic.local", structure)
    store = ProfileStore(tmp_path / "profile.json")
    store.put(
        installation,
        0,
        BindingInput(
            binding_id="pv",
            role="production",
            source_kind="state",
            control_uuid=CONTROL,
            state_uuid=STATE,
            confirmed=True,
            rationale="private-pv-marker",
            pv_parameters={"installed_kwp": 5.0},
        ),
        control,
        origin="local_admin",
        actor_ref=hashlib.sha256(b"synthetic").hexdigest(),
    )
    events = []
    original = ProfileStore.read

    def read(*args):
        result = original(*args)
        events.append("read")
        return result

    async def require_access(access):
        events.append("reauthorize")
        assert events == ["read", "reauthorize"]
        raise RuntimeAuthorizationError(reason)

    monkeypatch.setattr(ProfileStore, "read", read)
    server = FastMCP("profile-revocation")
    register_profile_read_tool(
        server,
        _runtime(structure, require_access=require_access),
        store.path,
    )
    response = await server._tool_manager.get_tool("loxone_get_installation_profile").fn()
    assert not response.ok and response.data.error == "permission_denied"
    assert "private-pv-marker" not in response.model_dump_json()
    assert events == ["read", "reauthorize"]
