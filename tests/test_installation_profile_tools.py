from __future__ import annotations

import hashlib
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
    monkeypatch.setattr("mcpserver.installation_profile_tools._snapshot", snapshot)
    server = FastMCP("profile-test")
    runtime = SimpleNamespace(endpoint=SimpleNamespace(origin="http://synthetic.local"))
    register_profile_read_tool(server, runtime, path)
    tool = server._tool_manager.get_tool("loxone_get_installation_profile")
    first = await tool.fn()
    assert first.ok and first.data.bindings[0].status == "confirmed"
    second = await tool.fn(offset=1)
    assert second.ok and second.data.bindings == []
    assert snapshot.await_count == 2
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
