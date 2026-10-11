from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP

from mcpserver.admin_errors import AdminError
from mcpserver.auth.provider import StoredAccessToken
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.installation_profile import (
    BindingInput,
    ProfileError,
    ProfileStore,
    installation_identity,
)
from mcpserver.installation_profile_permissions import dispatch_permissions
from mcpserver.installation_profile_tools import register_profile_write_tools
from mcpserver.installation_profile_write import ProfileWriteRuntime, profile_binding
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure
from mcpserver.persistence import PersistenceUncertain

CONTROL = "00000001-0000-0000-0000000000000001"
STATE = "00000002-0000-0000-0000000000000002"
HIDDEN = "00000003-0000-0000-0000000000000003"


@pytest.fixture
def context(tmp_path, monkeypatch):
    access = StoredAccessToken(
        token="synthetic-token",
        client_id="synthetic-client",
        scopes=["loxone:read", "loxone:history", "loxberry:operate"],
        expires_at=2_000_000_000,
        resource="https://synthetic.local/mcp",
        family_id="synthetic-family",
        identity_id="synthetic-identity",
        miniserver_id="synthetic-miniserver",
    )
    auth = AtomicJsonAuthStore(tmp_path / "auth.json")
    record = {
        "client_id": access.client_id,
        "identity_id": access.identity_id,
        "miniserver_id": access.miniserver_id,
        "scope": " ".join(access.scopes),
        "expires_at": access.expires_at,
    }
    auth.mutate(lambda document: document["families"].update({access.family_id: record}))
    config = AtomicConfigStore(tmp_path / "config.json")
    config.save(
        replace(
            PluginConfig.defaults(),
            loxone_endpoint="http://10.0.0.1",
            loxone_history_enabled=True,
            loxberry_operate_enabled=True,
            installation_profile_write_enabled=True,
            loxberry_operate_requests_per_minute=20,
            loxberry_operate_bindings=(
                auth.pseudonym(
                    "loxberry-operate-binding-v1",
                    access.client_id,
                    access.identity_id,
                    access.miniserver_id,
                ),
            ),
            installation_profile_write_bindings=(profile_binding(auth, access),),
        )
    )
    control = Control(
        CONTROL, "Synthetic", "InfoOnlyDigital", None, None, None, (("active", STATE),)
    )
    structure = LoxoneStructure(
        LoxoneIdentity("synthetic", "synthetic-serial"), "v1", (), (), (control,)
    )
    snapshot = AsyncMock(return_value=(access, SimpleNamespace(structure=structure)))
    monkeypatch.setattr("mcpserver.installation_profile_write._snapshot", snapshot)
    monkeypatch.setattr("mcpserver.tools._access", lambda: access)
    runtime = ProfileWriteRuntime(
        SimpleNamespace(endpoint=SimpleNamespace(origin="http://10.0.0.1")),
        tmp_path / "installation-profile.json",
        config,
        auth,
    )
    binding = BindingInput(
        binding_id="synthetic-binding",
        role="operating_state",
        control_uuid=CONTROL,
        source_kind="state",
        state_uuid=STATE,
        confirmed=True,
    )
    return SimpleNamespace(
        runtime=runtime,
        access=access,
        config=config,
        auth=auth,
        snapshot=snapshot,
        binding=binding,
        control=control,
        installation=installation_identity("http://10.0.0.1", structure),
    )


@pytest.mark.asyncio
async def test_confirmed_write_revision_and_draft_provenance(context):
    c = context
    result = await c.runtime.change(c.access, 0, binding=c.binding)
    assert result == {"revision": 1, "binding_id": "synthetic-binding"}
    stored = ProfileStore(c.runtime.path).read(c.installation).bindings[0]
    assert stored.confirmation_origin == "mcp_user_confirmed"
    assert stored.actor_ref == profile_binding(c.auth, c.access)
    with pytest.raises(ProfileError, match="profile_revision_conflict"):
        await c.runtime.change(c.access, 0, binding=c.binding)
    await c.runtime.change(c.access, 1, binding=c.binding.model_copy(update={"confirmed": False}))
    stored = ProfileStore(c.runtime.path).read(c.installation).bindings[0]
    assert stored.confirmation_origin is None and stored.actor_ref is None
    await c.runtime.change(c.access, 2, binding_id=c.binding.binding_id)
    assert ProfileStore(c.runtime.path).read(c.installation).revision == 3
    assert all(call.kwargs == {"fresh_visibility": True} for call in c.snapshot.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("installation_profile_write_enabled", False),
        ("installation_profile_write_bindings", ()),
        ("loxberry_operate_enabled", False),
        ("loxberry_operate_bindings", ()),
        ("loxone_read_enabled", False),
    ],
)
async def test_independent_policy_gates_reject_before_discovery(context, field, value):
    c = context
    c.config.mutate(lambda config: replace(config, **{field: value}))
    with pytest.raises(PermissionError):
        await c.runtime.change(c.access, 0, binding=c.binding)
    c.snapshot.assert_not_awaited()
    assert not c.runtime.path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("client_id", "different-client"),
        ("identity_id", "different-identity"),
        ("miniserver_id", "different-miniserver"),
        ("scopes", ["loxone:read"]),
    ],
)
async def test_exact_identity_and_scope_gates(context, field, value):
    with pytest.raises(PermissionError):
        await context.runtime.change(
            context.access.model_copy(update={field: value}), 0, binding=context.binding
        )
    assert not context.runtime.path.exists()


@pytest.mark.asyncio
async def test_hidden_binding_cannot_be_replaced_or_deleted_as_a_whole(context):
    c = context
    hidden = replace(c.control, uuid=HIDDEN)
    stored = c.binding.model_copy(update={"control_uuid": HIDDEN})
    ProfileStore(c.runtime.path).put(
        c.installation,
        0,
        stored,
        hidden,
        origin="local_admin",
        actor_ref=hashlib.sha256(b"synthetic").hexdigest(),
    )
    before = c.runtime.path.read_bytes()
    for options in (
        {"binding": c.binding},
        {"binding_id": None},
        {"binding_id": c.binding.binding_id},
    ):
        with pytest.raises(PermissionError):
            await c.runtime.change(c.access, 1, **options)
        assert c.runtime.path.read_bytes() == before


@pytest.mark.asyncio
async def test_revocation_during_discovery_is_checked_at_commit(context):
    c = context
    original = c.snapshot.return_value

    async def snapshot(*_args, **_kwargs):
        c.config.mutate(lambda config: replace(config, installation_profile_write_bindings=()))
        return original

    c.snapshot.side_effect = snapshot
    with pytest.raises(PermissionError):
        await c.runtime.change(c.access, 0, binding=c.binding)
    assert not c.runtime.path.exists()


@pytest.mark.asyncio
async def test_timeout_holds_worker_slot_and_does_not_write_after_deadline(context, monkeypatch):
    c = context
    entered, release = threading.Event(), threading.Event()
    original = c.config.transaction

    def delayed(operation):
        entered.set()
        assert release.wait(2)
        return original(operation)

    monkeypatch.setattr(c.config, "transaction", delayed)
    monkeypatch.setattr("mcpserver.installation_profile_write.WRITE_TIMEOUT_SECONDS", 0.08)
    try:
        with pytest.raises(TimeoutError):
            await c.runtime.change(c.access, 0, binding=c.binding)
        assert entered.is_set()
        pending = c.runtime._pending
        with pytest.raises(ProfileError, match="profile_busy"):
            await c.runtime.change(c.access, 0, binding=c.binding)
    finally:
        release.set()
    with pytest.raises(ProfileError, match="profile_deadline_expired"):
        await pending
    assert not c.runtime.path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("delete", [False, True])
async def test_profile_lock_wait_does_not_start_persistence_after_deadline(
    context, monkeypatch, delete
):
    c = context
    await c.runtime.change(c.access, 0, binding=c.binding)
    before = c.runtime.path.read_bytes()
    entered, release = threading.Event(), threading.Event()
    original = ProfileStore._locked
    calls = 0

    @contextmanager
    def contended(store):
        nonlocal calls
        calls += 1
        # The first lock reads the visible existing profile; the second is
        # the actual mutation transaction, after the adapter deadline check.
        if calls == 2:
            entered.set()
            assert release.wait(2)
        with original(store):
            yield

    monkeypatch.setattr(ProfileStore, "_locked", contended)
    monkeypatch.setattr("mcpserver.installation_profile_write.WRITE_TIMEOUT_SECONDS", 0.08)
    try:
        with pytest.raises(TimeoutError):
            await c.runtime.change(
                c.access,
                1,
                **({"binding_id": c.binding.binding_id} if delete else {"binding": c.binding}),
            )
        assert entered.is_set()
        pending = c.runtime._pending
        assert pending is not None
    finally:
        release.set()
    with pytest.raises(ProfileError, match="profile_deadline_expired"):
        await pending
    assert c.runtime.path.read_bytes() == before


@pytest.mark.asyncio
async def test_tool_confirmation_uncertainty_and_masked_audit(context, monkeypatch, caplog):
    c = context
    server = FastMCP("profile-write-test")
    register_profile_write_tools(server, c.runtime)
    save = server._tool_manager.get_tool("loxberry_save_installation_profile")
    assert not save.annotations.readOnlyHint and not save.annotations.idempotentHint
    result = await save.fn(c.binding, 0)
    assert not result.ok and result.data.error == "confirmation_required"
    c.snapshot.assert_not_awaited()
    monkeypatch.setattr(
        c.runtime, "change", AsyncMock(side_effect=PersistenceUncertain("private-path"))
    )
    result = await save.fn(c.binding, 0, True)
    assert not result.ok and result.data.error == "write_outcome_uncertain"
    assert "private-path" not in result.model_dump_json()
    assert "synthetic-client" not in caplog.text and "synthetic-token" not in caplog.text


def test_new_policy_defaults_and_configuration_roundtrip():
    config = PluginConfig.defaults()
    assert (
        config.installation_profile_write_enabled is False
        and config.installation_profile_write_bindings == ()
    )
    configured = replace(
        config,
        installation_profile_write_enabled=True,
        installation_profile_write_bindings=("a" * 64,),
    )
    loaded = PluginConfig.from_document(configured.to_document())
    assert loaded.installation_profile_write_enabled is True
    assert loaded.installation_profile_write_bindings == ("a" * 64,)
    assert loaded.to_document() == configured.to_document()


def test_local_profile_permission_is_separate_confirmed_and_revocable(context, monkeypatch):
    c = context
    c.config.mutate(lambda config: replace(config, installation_profile_write_bindings=()))
    monkeypatch.setattr("mcpserver.admin._auth_store", lambda: c.auth)
    monkeypatch.setattr(
        "mcpserver.admin._sessions",
        lambda: [
            {
                "id": c.access.family_id,
                "client_name": "Synthetic client",
                "client": c.access.client_id,
                "scopes": " ".join(c.access.scopes),
                "expires_at": c.access.expires_at,
                "loxberry_operate_approved": True,
            }
        ],
    )
    with pytest.raises(AdminError):
        dispatch_permissions(
            "profile_permission_allow", {"session_id": c.access.family_id}, c.config
        )
    result = dispatch_permissions(
        "profile_permission_allow", {"session_id": c.access.family_id, "confirm": True}, c.config
    )
    assert result["sessions"][0]["approved"] is True
    expected = profile_binding(c.auth, c.access)
    assert c.config.load().installation_profile_write_bindings == (expected,)
    dispatch_permissions(
        "profile_permission_revoke", {"binding_id": expected, "confirm": True}, c.config
    )
    assert c.config.load().installation_profile_write_bindings == ()
    assert c.config.load().loxberry_operate_bindings


@pytest.mark.asyncio
async def test_revoked_family_and_expired_scope_cannot_write(context):
    c = context
    c.auth.mutate(lambda document: document["families"][c.access.family_id].update(revoked=True))
    with pytest.raises(PermissionError):
        await c.runtime.change(c.access, 0, binding=c.binding)
    c.auth.mutate(
        lambda document: document["families"][c.access.family_id].update(
            revoked=False, scope="loxone:read"
        )
    )
    with pytest.raises(PermissionError):
        await c.runtime.change(c.access, 0, binding=c.binding)
    assert not c.runtime.path.exists()
