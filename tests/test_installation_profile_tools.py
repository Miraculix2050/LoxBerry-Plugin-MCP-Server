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
    summary = await tool.fn(view="summary", limit=1)
    assert summary.ok and summary.data.view == "summary"
    assert summary.data.next_offset == page.data.next_offset
    assert len(summary.model_dump_json().encode()) <= len(page.model_dump_json().encode()) * 0.8
    binding = summary.data.bindings[0].model_dump()
    original = page.data.bindings[0].model_dump()
    assert "rationale" not in binding and "pv_parameters" not in binding
    assert "load_flexibility" not in binding and "control_name" not in binding
    assert all(original[key] == value for key, value in binding.items())
    many = await tool.fn(view="summary")
    assert many.ok and len(many.data.bindings) == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("view", ["full", "summary"])
async def test_each_profile_read_and_page_uses_fresh_visibility(tmp_path, monkeypatch, view):
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
    first = await tool.fn(view=view)
    assert first.ok and first.data.bindings[0].status == "confirmed"
    second = await tool.fn(offset=1, view=view)
    assert second.ok and second.data.bindings == []
    assert snapshot.await_count == 2
    assert runtime._require_access.await_count == 2
    assert all(call.kwargs == {"fresh_visibility": True} for call in snapshot.await_args_list)
    snapshot.side_effect = RuntimeAuthorizationError("private-marker")
    rejected = await tool.fn(view=view)
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
@pytest.mark.parametrize("view", ["full", "summary"])
async def test_caller_revocation_during_profile_worker_read_blocks_publication(
    tmp_path, monkeypatch, reason, view
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
    response = await server._tool_manager.get_tool("loxone_get_installation_profile").fn(view=view)
    assert not response.ok and response.data.error == "permission_denied"
    assert "private-pv-marker" not in response.model_dump_json()
    assert events == ["read", "reauthorize"]


@pytest.mark.asyncio
async def test_summary_reduces_representative_profile_and_keeps_evidence(tmp_path):
    controls = tuple(
        Control(
            f"{i + 1:08x}-0000-0000-0000000000000001",
            f"Room {i} temperature probe",
            "InfoOnlyAnalog",
            None,
            None,
            None,
            (("value", f"{i + 1:08x}-0000-0000-0000000000000002"),),
        )
        for i in range(4)
    )
    structure = LoxoneStructure(LoxoneIdentity("synthetic", "serial"), "v1", (), (), controls)
    installation = installation_identity("http://synthetic.local", structure)
    store = ProfileStore(tmp_path / "profile.json")
    for i, control in enumerate(controls):
        store.put(
            installation,
            i,
            BindingInput(
                binding_id=f"room{i}",
                role="actual_temperature",
                source_kind="state",
                control_uuid=control.uuid,
                state_uuid=control.state_uuids[0][1],
                confirmed=True,
                rationale=(
                    "Owner confirmed this exact state for repeated room-temperature questions. "
                    "Units and period coverage require independent source evidence."
                ),
            ),
            control,
            origin="local_admin",
            actor_ref=hashlib.sha256(b"synthetic").hexdigest(),
        )
    server = FastMCP("representative-summary")
    register_profile_read_tool(server, _runtime(structure), store.path)
    tool = server._tool_manager.get_tool("loxone_get_installation_profile")
    full = await tool.fn()
    summary = await tool.fn(view="summary")
    assert full.ok and summary.ok and summary.data.view == "summary"
    assert len(summary.model_dump_json().encode()) <= len(full.model_dump_json().encode()) * 0.8
    assert full.warnings == summary.warnings and full.data.revision == summary.data.revision
    for left, right in zip(full.data.bindings, summary.data.bindings, strict=True):
        assert all(left.model_dump()[k] == v for k, v in right.model_dump().items())


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["retired_state", "hidden_control", "installation"])
async def test_summary_preserves_reference_redaction_and_installation_changes(tmp_path, change):
    from dataclasses import replace

    control = Control(CONTROL, "Synthetic", "InfoOnlyAnalog", None, None, None, (("value", STATE),))
    structure = LoxoneStructure(LoxoneIdentity("synthetic", "serial"), "v1", (), (), (control,))
    installation = installation_identity("http://synthetic.local", structure)
    store = ProfileStore(tmp_path / "profile.json")
    store.put(
        installation,
        0,
        BindingInput(
            binding_id="room",
            role="actual_temperature",
            source_kind="state",
            control_uuid=CONTROL,
            state_uuid=STATE,
            confirmed=True,
            rationale="private-declaration",
        ),
        control,
        origin="local_admin",
        actor_ref=hashlib.sha256(b"synthetic").hexdigest(),
    )
    if change == "retired_state":
        structure = replace(structure, controls=(replace(control, state_uuids=()),))
    if change == "hidden_control":
        structure = replace(structure, controls=())
    if change == "installation":
        structure = replace(structure, identity=LoxoneIdentity("synthetic", "new-serial"))
    server = FastMCP("changed-summary")
    register_profile_read_tool(server, _runtime(structure), store.path)
    tool = server._tool_manager.get_tool("loxone_get_installation_profile")
    result = await tool.fn(view="summary")
    assert result.ok and result.data.view == "summary"
    assert (
        STATE not in result.model_dump_json()
        and "private-declaration" not in result.model_dump_json()
    )
    if change == "retired_state":
        assert result.data.bindings[0].status == "invalid"
    else:
        assert result.data.bindings == []
    assert result.data.status == (
        "installation_changed" if change == "installation" else "available"
    )


def test_weather_summary_preserves_exact_source_origin_and_unknown_units():
    from mcpserver.installation_profile_tools import ProfileData, summarize_profile

    full = ProfileData.model_validate(
        {
            "status": "available",
            "revision": 7,
            "next_offset": None,
            "bindings": [
                {
                    "binding_id": "weather",
                    "role": "weather_context",
                    "source_kind": "weather",
                    "weather_state_uuid": STATE,
                    "mode": "forecast",
                    "field": "temperature",
                    "rationale": "Owner-selected forecast context",
                    "confirmed": True,
                    "confirmation_origin": "local_admin",
                    "status": "confirmed",
                    "fact_origin": "user_declared",
                    "semantic_status": "not_resolved",
                    "semantic_reference": "synthetic-rule",
                    "source_format": "%.1f C",
                    "unit": None,
                    "history_status": "not_checked",
                    "value_origin": "forecast",
                }
            ],
        }
    )
    result = summarize_profile(full)
    binding = result.bindings[0].model_dump()
    assert "rationale" not in binding and "control_uuid" not in binding
    assert binding["weather_state_uuid"] == STATE and binding["value_origin"] == "forecast"
    assert binding["unit"] is None and binding["history_status"] == "not_checked"
    assert all(full.bindings[0].model_dump()[key] == value for key, value in binding.items())
