"""Local KNX delegation is independent from project and diagnostics scopes."""

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from mcpserver.auth.provider import StoredAccessToken, normalize_scopes
from mcpserver.auth.scopes import LOXBERRY_KNX_DRAFTS_SCOPE, LOXBERRY_KNX_READ_SCOPE, READ_SCOPE
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.config import ConfigError, PluginConfig
from mcpserver.knx.delegation import (
    authorize_drafts,
    authorize_read,
    draft_binding_id,
    read_binding_id,
)


def test_knx_read_policy_is_additive_disabled_and_round_trips():
    previous = PluginConfig.defaults()
    assert not previous.loxberry_knx_read_enabled
    assert not previous.loxberry_knx_read_bindings
    document = previous.to_document()
    document["tools"]["loxberry_knx_read_enabled"] = True
    document["policies"]["loxberry_knx_read_bindings"] = ["a" * 64]
    current = PluginConfig.from_document(document)
    assert current.loxberry_knx_read_enabled
    assert current.loxberry_knx_read_bindings == ("a" * 64,)
    assert not current.loxberry_read_enabled
    assert not current.loxberry_operate_enabled
    assert PluginConfig.from_document(current.to_document()) == current


@pytest.mark.parametrize("bindings", [["A" * 64], ["a" * 63], ["a" * 64] * 2, ["a" * 64] * 65])
def test_knx_read_bindings_retain_strict_identity_and_capacity_validation(bindings):
    with pytest.raises(ConfigError):
        PluginConfig.from_document({"policies": {"loxberry_knx_read_bindings": bindings}})


def test_knx_scope_requires_core_read_but_not_history_or_diagnostics():
    assert normalize_scopes(f"{LOXBERRY_KNX_READ_SCOPE} {READ_SCOPE}", control_enabled=False) == (
        READ_SCOPE,
        LOXBERRY_KNX_READ_SCOPE,
    )
    with pytest.raises(ValueError):
        normalize_scopes(LOXBERRY_KNX_READ_SCOPE, control_enabled=False)


def test_draft_scope_requires_independent_catalog_consent_and_defaults_off():
    config = PluginConfig.defaults()
    assert not config.loxberry_knx_drafts_enabled and not config.loxberry_knx_drafts_bindings
    assert PluginConfig.from_document(config.to_document()).to_document() == config.to_document()
    with pytest.raises(ValueError, match="unsupported scope"):
        normalize_scopes(f"{READ_SCOPE} {LOXBERRY_KNX_DRAFTS_SCOPE}", control_enabled=False)
    assert normalize_scopes(
        f"{LOXBERRY_KNX_DRAFTS_SCOPE} {LOXBERRY_KNX_READ_SCOPE} {READ_SCOPE}",
        control_enabled=False,
    ) == (READ_SCOPE, LOXBERRY_KNX_READ_SCOPE, LOXBERRY_KNX_DRAFTS_SCOPE)


@pytest.fixture
def delegated(tmp_path):
    store = AtomicJsonAuthStore(tmp_path / "auth.json")
    family = {
        "client_id": "client",
        "identity_id": "identity",
        "miniserver_id": "ms",
        "scope": f"{READ_SCOPE} {LOXBERRY_KNX_READ_SCOPE}",
        "expires_at": 200,
        "revoked": False,
    }
    store.mutate(lambda document: document["families"].update({"family": family}))
    config = replace(
        PluginConfig.defaults(),
        loxone_endpoint="https://first.example",
        loxberry_knx_read_enabled=True,
    )
    config = replace(config, loxberry_knx_read_bindings=(read_binding_id(config, store, family),))
    access = StoredAccessToken(
        token="synthetic",
        client_id="client",
        scopes=[READ_SCOPE, LOXBERRY_KNX_READ_SCOPE],
        expires_at=200,
        resource="https://public.example/plugins/mcpserver/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="ms",
    )
    return config, store, access


def test_draft_access_never_inherits_read_or_other_local_approvals(delegated):
    config, auth, access = delegated
    scopes = [READ_SCOPE, LOXBERRY_KNX_READ_SCOPE, LOXBERRY_KNX_DRAFTS_SCOPE]
    auth.mutate(lambda doc: doc["families"]["family"].update(scope=" ".join(scopes)))
    access = access.model_copy(update={"scopes": scopes})
    family = auth.snapshot()["families"]["family"]
    binding = draft_binding_id(config, auth, family)
    assert binding != read_binding_id(config, auth, family)
    granted = replace(
        config, loxberry_knx_drafts_enabled=True, loxberry_knx_drafts_bindings=(binding,)
    )
    target, owner = authorize_drafts(granted, auth, access, now=100)
    assert target == "https://first.example" and len(owner) == 64
    for changed in (
        config,
        replace(granted, loxberry_knx_drafts_enabled=False),
        replace(granted, loxberry_knx_drafts_bindings=config.loxberry_knx_read_bindings),
        replace(granted, loxberry_knx_read_enabled=False),
        replace(granted, loxberry_knx_read_bindings=()),
        replace(granted, loxone_endpoint="https://second.example"),
    ):
        with pytest.raises(PermissionError):
            authorize_drafts(changed, auth, access, now=100)
    with pytest.raises(PermissionError):
        authorize_drafts(granted, auth, access, now=200)
    auth.mutate(lambda doc: doc["families"]["family"].update(revoked=True))
    with pytest.raises(PermissionError):
        authorize_drafts(granted, auth, access, now=100)


def test_live_knx_delegation_does_not_inherit_diagnostics_or_changed_target(delegated):
    config, store, access = delegated
    assert authorize_read(config, store, access, now=100) == "https://first.example"
    for changed in (
        replace(config, loxberry_knx_read_enabled=False),
        replace(config, loxberry_knx_read_bindings=(), loxberry_read_enabled=True),
        replace(config, loxone_endpoint="https://second.example"),
    ):
        with pytest.raises(PermissionError):
            authorize_read(changed, store, access, now=100)
    with pytest.raises(PermissionError):
        authorize_read(
            config,
            store,
            access.model_copy(update={"scopes": [READ_SCOPE, "loxberry:read"]}),
            now=100,
        )
    with pytest.raises(PermissionError):
        authorize_read(config, store, access, now=200)


@pytest.mark.parametrize(
    "change",
    [
        {"revoked": True},
        {"identity_id": "other"},
        {"client_id": "other"},
        {"miniserver_id": "other"},
        {"scope": READ_SCOPE},
        {"scope": LOXBERRY_KNX_READ_SCOPE},
    ],
)
def test_knx_read_rechecks_current_family_before_cached_or_worker_results(delegated, change):
    config, store, access = delegated
    assert authorize_read(config, store, access, now=100)
    store.mutate(lambda document: document["families"]["family"].update(change))
    with pytest.raises(PermissionError):
        authorize_read(config, store, access, now=100)


def test_admin_delegation_reader_does_not_import_mcp_server_stack():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import mcpserver.knx.read_admin; "
            "assert 'mcpserver.auth.provider' not in sys.modules; "
            "assert 'mcp.server.fastmcp' not in sys.modules",
        ],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
