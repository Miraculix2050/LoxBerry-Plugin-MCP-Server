from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from mcpserver.admin import (
    AdminError,
    _allow_loxberry_operate,
    _allow_loxberry_read,
    _clear_event_history,
    _emergency_stop_runtime_status,
    _loxberry_bindings,
    _loxberry_operate_bindings,
    _remote_cleanup_status,
    _renew_certificate,
    _revoke,
    _revoke_loxberry_operate,
    _revoke_loxberry_read,
    _save,
    _save_mcp,
    _save_mqtt,
    _service_status,
    _set_logging,
    dispatch,
)
from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore, LoxoneTokenStoreError
from mcpserver.auth.provider import (
    CONTROL_SCOPE,
    HISTORY_SCOPE,
    LOXBERRY_OPERATE_SCOPE,
    LOXBERRY_READ_SCOPE,
    READ_SCOPE,
)
from mcpserver.auth.remote_revocation import RemoteRevocationState
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.config import AtomicConfigStore, ConfigError, PluginConfig
from mcpserver.emergency_stop import VirtualStatusOptions
from mcpserver.loxone.auth_diagnostics import MiniserverAuthCoordinator
from mcpserver.loxone.client import LoxoneToken
from mcpserver.loxone.events import LoxoneProtocolError
from tools.benchmark_admin_page_state import measure


def test_admin_import_defers_mqtt_and_loxone_clients() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, sys; import mcpserver.admin; "
            "print(json.dumps(['mcpserver.mqtt_health' in sys.modules, "
            "'mcpserver.loxone.client' in sys.modules]))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == [False, False]


def test_page_state_does_not_import_emergency_stop_runtime() -> None:
    script = """
import json
import os
import sys
from mcpserver import admin

os.environ.pop("LBHOMEDIR", None)
os.environ.pop("MCPSERVER_MQTT_CREDENTIALS", None)
result = admin.dispatch({"action": "page_state"})
print(json.dumps({
    "mqtt_loaded": "mcpserver.mqtt_health" in sys.modules,
    "emergency_stop_loaded": "mcpserver.emergency_stop" in sys.modules,
    "gateway_configured": result["mqtt_gateway"]["gateway_configured"],
    "password_configured": result["mqtt_password_configured"],
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "mqtt_loaded": True,
        "emergency_stop_loaded": False,
        "gateway_configured": False,
        "password_configured": False,
    }


def test_list_sessions_does_not_import_oauth_provider() -> None:
    script = """
import json
import sys
from mcpserver import admin
from mcpserver.config import PluginConfig

document = {
    "clients": {},
    "families": {
        "family": {
            "scope": "loxone:read loxberry:read",
            "expires_at": 2_000_000_000,
            "pending_loxberry_read": True,
            "revoked": False,
        },
    },
}
snapshot = admin._AdminReadSnapshot(PluginConfig.defaults(), document, None, 1_000_000_000)
admin._admin_read_snapshot = lambda: snapshot
result = admin.dispatch({"action": "list_sessions"})
print(json.dumps({
    "provider_loaded": "mcpserver.auth.provider" in sys.modules,
    "session_count": len(result["sessions"]),
    "read_eligible": result["sessions"][0]["loxberry_read_eligible"],
    "read_bindings": result["loxberry_bindings"],
    "operate_bindings": result["loxberry_operate_bindings"],
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "provider_loaded": False,
        "session_count": 1,
        "read_eligible": True,
        "read_bindings": [],
        "operate_bindings": [],
    }


def test_clear_event_history_stops_the_recorder_before_deleting_its_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = PluginConfig(event_history_enabled=True, loxone_history_enabled=True)
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    store.save(config)
    path = (tmp_path / "data" / "event-history.sqlite3").resolve()
    calls: list[str] = []

    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: True)
    monkeypatch.setattr("mcpserver.admin._stop_service", lambda: calls.append("stop"))
    monkeypatch.setattr("mcpserver.admin._start_service", lambda: calls.append("start"))
    monkeypatch.setenv("MCPSERVER_EVENT_HISTORY_STORE", str(path))

    result = _clear_event_history()

    assert calls == ["stop", "start"]
    assert result == {"event_history_entries_removed": 0}


def test_diagnostic_contains_no_paths_endpoint_or_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = (tmp_path / "config" / "mcpserver.json").resolve()
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    AtomicConfigStore(config_path).save(
        PluginConfig.from_document(
            {
                "schema_version": 1,
                "server": {
                    "enabled": True,
                    "public_origin": "https://loxberry.example",
                },
                "loxone": {"endpoint": "http://192.168.10.20"},
            }
        )
    )
    AtomicJsonAuthStore(auth_path)
    monkeypatch.setenv("MCPSERVER_CONFIG", str(config_path))
    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: True)

    result = dispatch({"action": "diagnostic"})
    serialized = json.dumps(result)

    assert result["service_active"] is True
    assert result["transport"] == "ws"
    assert "192.168" not in serialized
    assert str(tmp_path) not in serialized


def test_admin_rejects_unknown_actions() -> None:
    with pytest.raises(Exception, match="not supported"):
        dispatch({"action": "delete_everything"})


def test_page_snapshot_reuses_one_dispatch_and_keeps_section_failures_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcpserver import admin

    original_dispatch = admin.dispatch
    calls: list[str] = []

    def section_dispatch(
        request: object, *, timing: dict[str, float] | None = None
    ) -> dict[str, object]:
        assert isinstance(request, dict)
        action = request["action"]
        assert isinstance(action, str)
        if action == "page_snapshot":
            return original_dispatch(request, timing=timing)
        calls.append(action)
        if action == "page_state":
            raise AdminError("MQTT unavailable", code="mqtt_unavailable")
        return {"section": action}

    monkeypatch.setattr(admin, "dispatch", section_dispatch)
    timing: dict[str, float] = {}
    result = admin.dispatch({"action": "page_snapshot"}, timing=timing)

    assert calls == [
        "get_config",
        "page_state",
        "service_status",
        "certificate_status",
        "list_sessions",
    ]
    assert result["get_config"] == {"ok": True, "data": {"section": "get_config"}}
    assert result["page_state"] == {
        "ok": False,
        "error": {"code": "mqtt_unavailable", "message": "MQTT unavailable"},
    }
    assert result["list_sessions"] == {
        "ok": True,
        "data": {"section": "list_sessions"},
    }
    assert set(timing) == {f"{action}_ms" for action in calls}


def test_loxberry_approval_accepts_pending_control_scoped_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = (tmp_path / "config" / "mcpserver.json").resolve()
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    AtomicConfigStore(config_path).save(PluginConfig.defaults())
    auth_store = AtomicJsonAuthStore(auth_path)
    auth_store.mutate(
        lambda document: document["families"].update(
            {
                "control-family": {
                    "scope": f"{READ_SCOPE} {CONTROL_SCOPE}",
                    "client_id": "client",
                    "identity_id": "identity",
                    "miniserver_id": "miniserver",
                    "expires_at": 2_000_000_000,
                    "pending_loxberry_read": True,
                    "revoked": False,
                }
            }
        )
    )
    monkeypatch.setenv("MCPSERVER_CONFIG", str(config_path))
    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))

    _allow_loxberry_read({"session_id": "control-family"})
    assert AtomicConfigStore(config_path).load().loxberry_read_bindings


def test_loxberry_approval_rejects_expired_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = (tmp_path / "config" / "mcpserver.json").resolve()
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    AtomicConfigStore(config_path).save(PluginConfig.defaults())
    auth_store = AtomicJsonAuthStore(auth_path)
    auth_store.mutate(
        lambda document: document["families"].update(
            {
                "expired-family": {
                    "scope": "loxone:read",
                    "expires_at": 1,
                    "pending_loxberry_read": True,
                    "revoked": False,
                }
            }
        )
    )
    monkeypatch.setenv("MCPSERVER_CONFIG", str(config_path))
    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))

    with pytest.raises(AdminError, match="pending diagnostic session"):
        _allow_loxberry_read({"session_id": "expired-family"})


def test_explorer_approval_is_application_bound_and_individually_revocable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = (tmp_path / "config" / "mcpserver.json").resolve()
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    AtomicConfigStore(config_path).save(PluginConfig.defaults())
    auth_store = AtomicJsonAuthStore(auth_path)
    auth_store.mutate(
        lambda document: document["families"].update(
            {
                "explorer-family": {
                    "scope": f"{READ_SCOPE} {LOXBERRY_READ_SCOPE}",
                    "client_id": "dynamic-client-a",
                    "client_kind": "tool_explorer",
                    "explorer_origin": "https://public.example",
                    "identity_id": "identity",
                    "miniserver_id": "miniserver",
                    "created_at": 1_900_000_000,
                    "expires_at": 2_000_000_000,
                    "pending_loxberry_read": True,
                    "revoked": False,
                }
            }
        )
    )
    monkeypatch.setenv("MCPSERVER_CONFIG", str(config_path))
    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))

    response = _allow_loxberry_read({"session_id": "explorer-family"})
    config = AtomicConfigStore(config_path).load()

    assert config.loxberry_read_bindings == ()
    assert len(config.explorer_bindings) == 1
    assert response["loxberry_bindings"][0]["active"] is True
    binding_id = config.explorer_bindings[0].binding_id

    revoked: list[str] = []
    monkeypatch.setattr(
        "mcpserver.admin._revoke_many", lambda family_ids, **_kwargs: revoked.extend(family_ids)
    )
    _revoke_loxberry_read({"binding_id": binding_id})

    assert AtomicConfigStore(config_path).load().explorer_bindings == ()
    assert revoked == ["explorer-family"]


def test_loxberry_operate_approval_uses_separate_exact_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = (tmp_path / "config" / "mcpserver.json").resolve()
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    AtomicConfigStore(config_path).save(PluginConfig.defaults())
    auth_store = AtomicJsonAuthStore(auth_path)
    auth_store.mutate(
        lambda document: document["families"].update(
            {
                "operate-family": {
                    "scope": f"{READ_SCOPE} {HISTORY_SCOPE} {LOXBERRY_OPERATE_SCOPE}",
                    "client_id": "client",
                    "identity_id": "identity",
                    "miniserver_id": "miniserver",
                    "expires_at": 2_000_000_000,
                    "pending_loxberry_operate": True,
                    "revoked": False,
                }
            }
        )
    )
    monkeypatch.setenv("MCPSERVER_CONFIG", str(config_path))
    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))

    _allow_loxberry_operate({"session_id": "operate-family"})
    config = AtomicConfigStore(config_path).load()

    assert len(config.loxberry_operate_bindings) == 1
    assert config.loxberry_read_bindings == ()


def test_revoking_loxberry_operate_keeps_other_bound_scope_families(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = (tmp_path / "config" / "mcpserver.json").resolve()
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    auth_store = AtomicJsonAuthStore(auth_path)
    binding = auth_store.pseudonym(
        "loxberry-operate-binding-v1", "client", "identity", "miniserver"
    )
    AtomicConfigStore(config_path).save(
        PluginConfig.from_document(
            {"schema_version": 1, "policies": {"loxberry_operate_bindings": [binding]}}
        )
    )
    auth_store.mutate(
        lambda document: document["families"].update(
            {
                "operate-family": {
                    "scope": f"{READ_SCOPE} {HISTORY_SCOPE} {LOXBERRY_OPERATE_SCOPE}",
                    "client_id": "client",
                    "identity_id": "identity",
                    "miniserver_id": "miniserver",
                    "revoked": False,
                },
                "read-family": {
                    "scope": READ_SCOPE,
                    "client_id": "client",
                    "identity_id": "identity",
                    "miniserver_id": "miniserver",
                    "revoked": False,
                },
            }
        )
    )
    revoked: list[str] = []
    monkeypatch.setenv("MCPSERVER_CONFIG", str(config_path))
    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))
    monkeypatch.setattr(
        "mcpserver.admin._revoke_many", lambda family_ids, **_kwargs: revoked.extend(family_ids)
    )

    _revoke_loxberry_operate({"binding_id": binding})

    assert revoked == ["operate-family"]


def test_concurrent_loxberry_read_binding_revocations_remove_each_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = (tmp_path / "config" / "mcpserver.json").resolve()
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    auth_store = AtomicJsonAuthStore(auth_path)
    families = {
        f"family-{index}": {
            "scope": f"{READ_SCOPE} {LOXBERRY_READ_SCOPE}",
            "client_id": f"client-{index}",
            "identity_id": f"identity-{index}",
            "miniserver_id": f"miniserver-{index}",
            "revoked": False,
        }
        for index in range(2)
    }
    bindings = tuple(
        auth_store.pseudonym(
            "loxberry-read-binding-v1",
            f"client-{index}",
            f"identity-{index}",
            f"miniserver-{index}",
        )
        for index in range(len(families))
    )
    AtomicConfigStore(config_path).save(
        PluginConfig.from_document(
            {"schema_version": 1, "policies": {"loxberry_read_bindings": list(bindings)}}
        )
    )
    auth_store.mutate(lambda document: document["families"].update(families))
    monkeypatch.setenv("MCPSERVER_CONFIG", str(config_path))
    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))
    monkeypatch.setattr("mcpserver.admin._token_store", lambda: None)

    with ThreadPoolExecutor(max_workers=len(bindings)) as executor:
        list(executor.map(lambda binding: _revoke_loxberry_read({"binding_id": binding}), bindings))

    assert AtomicConfigStore(config_path).load().loxberry_read_bindings == ()
    assert all(record["revoked"] for record in auth_store.snapshot()["families"].values())


def test_loxberry_bindings_expose_related_active_client_without_raw_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = (tmp_path / "config" / "mcpserver.json").resolve()
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    auth_store = AtomicJsonAuthStore(auth_path)
    auth_store.mutate(
        lambda document: (
            document["clients"].update({"desktop-client-id": {"client_name": "MCP Tool Explorer"}}),
            document["families"].update(
                {
                    "diagnostic-family": {
                        "scope": f"{READ_SCOPE} {LOXBERRY_READ_SCOPE}",
                        "client_id": "desktop-client-id",
                        "identity_id": "private-identity",
                        "miniserver_id": "private-miniserver",
                        "expires_at": 2_000_000_000,
                        "revoked": False,
                    }
                }
            ),
        )
    )
    binding = auth_store.pseudonym(
        "loxberry-read-binding-v1",
        "desktop-client-id",
        "private-identity",
        "private-miniserver",
    )
    AtomicConfigStore(config_path).save(
        PluginConfig.from_document(
            {"schema_version": 1, "policies": {"loxberry_read_bindings": [binding]}}
        )
    )
    monkeypatch.setenv("MCPSERVER_CONFIG", str(config_path))
    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))

    bindings = _loxberry_bindings()

    assert bindings == [
        {
            "id": binding,
            "fingerprint": binding[:12],
            "active": True,
            "sessions": [
                {
                    "client": "desktop-clie",
                    "client_name": "MCP Tool Explorer",
                    "identity": "private-iden",
                    "scopes": f"{READ_SCOPE} {LOXBERRY_READ_SCOPE}",
                }
            ],
            "rows": [
                {
                    "client": "desktop-clie",
                    "client_name": "MCP Tool Explorer",
                    "identity": "private-iden",
                    "scopes": f"{READ_SCOPE} {LOXBERRY_READ_SCOPE}",
                    "binding_id": binding,
                    "fingerprint": binding[:12],
                    "inactive": False,
                }
            ],
        }
    ]
    assert "private-identity" not in json.dumps(bindings)


def test_loxberry_bindings_include_a_revocable_inactive_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = (tmp_path / "config" / "mcpserver.json").resolve()
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    auth_store = AtomicJsonAuthStore(auth_path)
    binding = auth_store.pseudonym("loxberry-read-binding-v1", "client", "identity", "miniserver")
    AtomicConfigStore(config_path).save(
        PluginConfig.from_document(
            {"schema_version": 1, "policies": {"loxberry_read_bindings": [binding]}}
        )
    )
    monkeypatch.setenv("MCPSERVER_CONFIG", str(config_path))
    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))

    row = _loxberry_bindings()[0]["rows"]

    assert row == [
        {
            "client": binding[:12],
            "client_name": "",
            "identity": "",
            "binding_id": binding,
            "fingerprint": binding[:12],
            "inactive": True,
        }
    ]


def test_loxberry_operate_bindings_ignore_read_only_families(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = (tmp_path / "config" / "mcpserver.json").resolve()
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    auth_store = AtomicJsonAuthStore(auth_path)
    binding = auth_store.pseudonym(
        "loxberry-operate-binding-v1", "client", "identity", "miniserver"
    )
    AtomicConfigStore(config_path).save(
        PluginConfig.from_document(
            {"schema_version": 1, "policies": {"loxberry_operate_bindings": [binding]}}
        )
    )
    auth_store.mutate(
        lambda document: document["families"].update(
            {
                "read-family": {
                    "scope": f"{READ_SCOPE} {LOXBERRY_READ_SCOPE}",
                    "client_id": "client",
                    "identity_id": "identity",
                    "miniserver_id": "miniserver",
                    "expires_at": 2_000_000_000,
                    "revoked": False,
                }
            }
        )
    )
    monkeypatch.setenv("MCPSERVER_CONFIG", str(config_path))
    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))

    binding_data = _loxberry_operate_bindings()[0]

    assert binding_data["active"] is False
    assert binding_data["sessions"] == []


def test_page_state_contains_only_fast_local_mqtt_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mcpserver.admin._mqtt_gateway_status", lambda: {"gateway_configured": True}
    )
    monkeypatch.setattr("mcpserver.admin._mqtt_password_configured", lambda: True)
    monkeypatch.setattr(
        "mcpserver.admin._admin_read_snapshot",
        lambda **_kwargs: pytest.fail("page_state must not read session data"),
    )
    monkeypatch.setattr(
        "mcpserver.admin._service_response",
        lambda: pytest.fail("page_state must not read service status"),
    )
    monkeypatch.setattr(
        "mcpserver.admin._certificate_status",
        lambda **_kwargs: pytest.fail("page_state must not inspect certificates"),
    )

    result = dispatch({"action": "page_state"})

    assert result == {
        "mqtt_gateway": {"gateway_configured": True},
        "mqtt_password_configured": True,
    }


def test_emergency_stop_options_distinguishes_empty_available_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConfigStore:
        def load(self) -> PluginConfig:
            return PluginConfig(loxone_endpoint="http://miniserver.test")

    async def empty_available(_config: PluginConfig) -> VirtualStatusOptions:
        return VirtualStatusOptions(status="available", options=())

    monkeypatch.setattr("mcpserver.admin._config_store", ConfigStore)
    monkeypatch.setattr("mcpserver.emergency_stop.virtual_status_options", empty_available)

    assert dispatch({"action": "emergency_stop_options"}) == {
        "status": "available",
        "options": [],
    }


def test_emergency_stop_options_uses_the_shared_authentication_breaker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class ConfigStore:
        def load(self) -> PluginConfig:
            return PluginConfig(loxone_endpoint="http://192.168.1.10")

    captured: MiniserverAuthCoordinator | None = None

    async def available(
        _config: PluginConfig, coordinator: MiniserverAuthCoordinator
    ) -> VirtualStatusOptions:
        nonlocal captured
        captured = coordinator
        return VirtualStatusOptions(status="available", options=())

    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str((tmp_path / "auth.json").resolve()))
    monkeypatch.setattr("mcpserver.admin._config_store", ConfigStore)
    monkeypatch.setattr("mcpserver.emergency_stop.virtual_status_options", available)

    assert dispatch({"action": "emergency_stop_options"}) == {
        "status": "available",
        "options": [],
    }
    assert isinstance(captured, MiniserverAuthCoordinator)


def test_emergency_stop_options_returns_a_fixed_internal_failure_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConfigStore:
        def load(self) -> PluginConfig:
            return PluginConfig(loxone_endpoint="http://miniserver.test")

    async def unavailable(_config: PluginConfig) -> VirtualStatusOptions:
        return VirtualStatusOptions(
            status="unavailable",
            options=(),
            failure_code="credentials_helper_missing",
        )

    monkeypatch.setattr("mcpserver.admin._config_store", ConfigStore)
    monkeypatch.setattr("mcpserver.emergency_stop.virtual_status_options", unavailable)

    assert dispatch({"action": "emergency_stop_options"}) == {
        "status": "unavailable",
        "options": [],
        "discovery_failure_code": "credentials_helper_missing",
    }


def test_emergency_stop_discovery_deadline_cancels_and_returns_fixed_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConfigStore:
        def load(self) -> PluginConfig:
            return PluginConfig(loxone_endpoint="http://miniserver.test")

    cancelled = False

    async def slow_discovery(_config: PluginConfig) -> VirtualStatusOptions:
        nonlocal cancelled
        try:
            await asyncio.sleep(1)
        finally:
            cancelled = True
        return VirtualStatusOptions(status="available", options=())

    monkeypatch.setattr("mcpserver.admin._config_store", ConfigStore)
    monkeypatch.setattr("mcpserver.admin._EMERGENCY_STOP_DISCOVERY_DEADLINE_SECONDS", 0.001)
    monkeypatch.setattr("mcpserver.emergency_stop.virtual_status_options", slow_discovery)

    assert dispatch({"action": "emergency_stop_options"}) == {
        "status": "unavailable",
        "options": [],
        "discovery_failure_code": "connection_failed",
    }
    assert cancelled


def test_admin_manual_emergency_stop_retry_is_explicit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class ConfigStore:
        def load(self) -> PluginConfig:
            return PluginConfig(loxone_endpoint="http://192.168.1.10")

    seen: list[bool] = []

    async def options(
        _config: PluginConfig,
        _coordinator: MiniserverAuthCoordinator,
        *,
        manual_retry: bool = False,
    ) -> VirtualStatusOptions:
        seen.append(manual_retry)
        return VirtualStatusOptions(status="available", options=())

    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str((tmp_path / "auth.json").resolve()))
    monkeypatch.setattr("mcpserver.admin._config_store", ConfigStore)
    monkeypatch.setattr("mcpserver.emergency_stop.virtual_status_options", options)
    dispatch({"action": "emergency_stop_options"})
    dispatch({"action": "emergency_stop_retry"})
    assert seen == [False, True]


@pytest.mark.parametrize("session_count", [0, 10, 100])
def test_admin_list_responses_use_one_snapshot_per_request(
    session_count: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject_key = b"s" * 32
    subject_key_text = base64.urlsafe_b64encode(subject_key).decode("ascii")
    families = {
        f"family-{index:03}": {
            "scope": f"{READ_SCOPE} {HISTORY_SCOPE} {LOXBERRY_READ_SCOPE} {LOXBERRY_OPERATE_SCOPE}",
            "client_id": f"client-{index}",
            "identity_id": f"identity-{index}",
            "miniserver_id": "miniserver",
            "expires_at": 2_000_000_000,
            "pending_loxberry_read": True,
            "pending_loxberry_operate": True,
            "revoked": False,
        }
        for index in range(session_count)
    }
    first_record = next(
        iter(families.values()),
        {"client_id": "", "identity_id": "", "miniserver_id": ""},
    )

    def binding(namespace: str) -> str:
        canonical = "\0".join(
            (
                namespace,
                first_record["client_id"],
                first_record["identity_id"],
                first_record["miniserver_id"],
            )
        ).encode("utf-8")
        return hmac.new(subject_key, canonical, hashlib.sha256).hexdigest()

    configuration = replace(
        PluginConfig.defaults(),
        loxberry_read_bindings=(binding("loxberry-read-binding-v1"),),
        loxberry_operate_bindings=(binding("loxberry-operate-binding-v1"),),
    )
    document = {
        "schema_version": 1,
        "subject_key": subject_key_text,
        "clients": {
            record["client_id"]: {"client_name": f"Client {index}"}
            for index, record in enumerate(families.values())
        },
        "families": families,
        "codes": {},
        "access_tokens": {},
        "refresh_tokens": {},
    }

    class ConfigStore:
        calls = 0

        def load(self) -> PluginConfig:
            self.calls += 1
            return configuration

    class AuthStore:
        calls = 0

        def snapshot(self) -> dict[str, object]:
            self.calls += 1
            return document

    config_store = ConfigStore()
    auth_store = AuthStore()
    monkeypatch.setattr("mcpserver.admin._config_store", lambda: config_store)
    monkeypatch.setattr("mcpserver.admin._auth_store", lambda: auth_store)
    monkeypatch.setattr("mcpserver.admin._service_status", lambda: {"active": True})
    monkeypatch.setattr(
        "mcpserver.admin._certificate_status", lambda **_kwargs: {"available": False}
    )

    result = dispatch({"action": "list_sessions"})

    assert config_store.calls == 1
    assert auth_store.calls == 1
    assert len(result["sessions"]) == session_count
    if session_count:
        assert result["sessions"][0]["id"] == "family-000"
    approved = [session for session in result["sessions"] if session["loxberry_read_approved"]]
    assert [session["id"] for session in approved] == (["family-000"] if session_count else [])
    approved = [session for session in result["sessions"] if session["loxberry_operate_approved"]]
    assert [session["id"] for session in approved] == (["family-000"] if session_count else [])
    assert result["loxberry_bindings"][0]["active"] is (session_count > 0)
    assert result["loxberry_operate_bindings"][0]["active"] is (session_count > 0)


def test_deferred_session_benchmark_reports_machine_readable_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import benchmark_admin_page_state

    calls: list[str] = []
    original_dispatch = benchmark_admin_page_state.admin.dispatch

    def dispatch(request: object) -> dict[str, object]:
        assert isinstance(request, dict)
        calls.append(str(request["action"]))
        return original_dispatch(request)

    monkeypatch.setattr(benchmark_admin_page_state.admin, "dispatch", dispatch)

    result = measure(session_count=10, warmups=0, samples=2)

    assert result["sessions"] == 10
    assert result["warmups"] == 0
    assert result["samples"] == 2
    assert isinstance(result["p50_ms"], float)
    assert isinstance(result["p95_ms"], float)
    assert isinstance(result["peak_bytes"], int)
    assert calls == ["list_sessions", "list_sessions"]


def test_status_refresh_returns_all_dynamic_admin_ui_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = [{"id": "family"}]
    certificate = {"available": True, "renewal": {"state": "idle"}}
    service = {
        "name": "loxberry-mcpserver.service",
        "installed": True,
        "active_state": "active",
        "sub_state": "running",
        "pid": 456,
        "active": True,
    }
    monkeypatch.setattr("mcpserver.admin._service_status", lambda: service)
    runtime = {
        "availability": "available",
        "signal_uuid": None,
        "signal_name": None,
        "status": "not_configured",
    }
    monkeypatch.setattr("mcpserver.admin._emergency_stop_runtime_status", lambda _service: runtime)
    monkeypatch.setattr("mcpserver.admin._sessions", lambda: sessions)
    monkeypatch.setattr("mcpserver.admin._certificate_status", lambda: certificate)

    result = dispatch({"action": "status"})

    assert result == {
        "version": result["version"],
        "service_active": True,
        "service": service,
        "emergency_stop_runtime": runtime,
        "sessions": sessions,
        "certificate": certificate,
    }


@pytest.mark.parametrize(
    ("active_state", "sub_state", "raw_pid", "expected_pid", "active"),
    [
        ("active", "running", "1234", 1234, True),
        ("inactive", "dead", "0", None, False),
        ("failed", "failed", "", None, False),
    ],
)
def test_service_status_reads_bounded_systemd_properties(
    active_state: str,
    sub_state: str,
    raw_pid: str,
    expected_pid: int | None,
    active: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.extend(command)
        output = (
            "LoadState=loaded\n"
            f"ActiveState={active_state}\n"
            f"SubState={sub_state}\n"
            f"MainPID={raw_pid}\n"
            "UnitFileState=enabled\n"
        )
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr("mcpserver.admin.subprocess.run", run)

    result = _service_status()

    assert captured == [
        "/bin/systemctl",
        "show",
        "--property=LoadState",
        "--property=ActiveState",
        "--property=SubState",
        "--property=MainPID",
        "--property=UnitFileState",
        "--no-pager",
        "loxberry-mcpserver.service",
        "/bin/systemctl",
        "is-enabled",
        "--quiet",
        "loxberry-mcpserver.service",
    ]
    assert result == {
        "name": "loxberry-mcpserver.service",
        "installed": True,
        "active_state": active_state,
        "sub_state": sub_state,
        "pid": expected_pid,
        "active": active,
        "enabled": True,
        "enable_state": "enabled",
    }


def test_service_status_fails_closed_when_systemctl_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "mcpserver.admin.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired(args[0], 5)),
    )

    assert _service_status() == {
        "name": "loxberry-mcpserver.service",
        "installed": False,
        "active_state": "unknown",
        "sub_state": "unknown",
        "pid": None,
        "active": False,
        "enabled": False,
        "enable_state": "unknown",
    }


class _RuntimeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self._status = status

    def __enter__(self) -> _RuntimeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def getcode(self) -> int:
        return self._status

    def read(self, _limit: int) -> bytes:
        return self._body


def test_emergency_stop_runtime_status_reads_only_the_validated_loopback_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    payload = {
        "ok": True,
        "emergency_stop": {
            "signal_uuid": "00112233-4455-6677-8899aabbccddeeff",
            "signal_name": "Workshop emergency stop",
            "status": "active",
        },
    }

    def open_runtime(request: object, *, timeout: float) -> _RuntimeResponse:
        captured["url"] = request.full_url  # type: ignore[attr-defined]
        captured["timeout"] = timeout
        return _RuntimeResponse(json.dumps(payload).encode())

    monkeypatch.setattr("mcpserver.admin.urlopen", open_runtime)

    assert _emergency_stop_runtime_status({"active": True}) == {
        "availability": "available",
        "signal_uuid": "00112233-4455-6677-8899aabbccddeeff",
        "signal_name": "Workshop emergency stop",
        "status": "active",
    }
    assert captured == {
        "url": "http://127.0.0.1:8765/internal/emergency-stop-status",
        "timeout": 1,
    }


def test_emergency_stop_runtime_status_never_invents_unknown_for_an_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "mcpserver.admin.urlopen",
        lambda *_args, **_kwargs: _RuntimeResponse(
            b'{"ok":true,"emergency_stop":{"signal_uuid":null,"signal_name":null,"status":"active"}}'
        ),
    )

    assert _emergency_stop_runtime_status({"active": True}) == {"availability": "unavailable"}
    assert _emergency_stop_runtime_status({"active": False}) == {"availability": "service_inactive"}


@pytest.mark.parametrize("command", ["start", "stop", "restart"])
def test_service_action_uses_only_the_fixed_unit(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[tuple[list[str], dict[str, object]]] = []
    service = {
        "name": "loxberry-mcpserver.service",
        "installed": True,
        "active_state": "active",
        "sub_state": "running",
        "pid": 987,
        "active": True,
    }

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr("mcpserver.admin.subprocess.run", run)
    monkeypatch.setattr("mcpserver.admin._service_status", lambda: service)
    monkeypatch.setattr(
        "mcpserver.admin._emergency_stop_runtime_status",
        lambda _service: {"availability": "unavailable"},
    )
    monkeypatch.setattr("mcpserver.admin.request_service_restart", lambda: None)

    result = dispatch({"action": "service_action", "payload": {"command": command}})

    assert len(captured) == 1
    argv, kwargs = captured[0]
    assert argv == ["sudo", "-n", "/bin/systemctl", command, "loxberry-mcpserver.service"]
    assert kwargs["timeout"] == 65
    assert result == {
        "service_active": True,
        "service": service,
        "emergency_stop_runtime": {"availability": "unavailable"},
    }


def test_service_action_rejects_arbitrary_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def run(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("mcpserver.admin.subprocess.run", run)

    with pytest.raises(AdminError, match="invalid"):
        dispatch({"action": "service_action", "payload": {"command": "disable"}})
    assert called is False


def test_service_action_maps_timeout_to_sanitized_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "mcpserver.admin.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired(args[0], 65)),
    )

    with pytest.raises(AdminError) as failure:
        dispatch({"action": "service_action", "payload": {"command": "restart"}})
    assert failure.value.code == "service_action_failed"
    assert str(failure.value) == "the service action failed"


def test_certificate_reissue_passes_securepin_only_over_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = tmp_path / "renew-web-certificate"
    helper.write_text("helper", encoding="utf-8")
    helper.chmod(0o755)
    monkeypatch.setenv("MCPSERVER_CERT_HELPER", str(helper.resolve()))
    monkeypatch.setattr(
        "mcpserver.admin._certificate_status",
        lambda: {"available": True, "renewal_supported": True},
    )
    captured: dict[str, object] = {}

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["command"] = command
        captured["input"] = kwargs["input"]
        return subprocess.CompletedProcess(command, 0, b"scheduled\n", b"")

    monkeypatch.setattr("mcpserver.admin.subprocess.run", run)

    result = _renew_certificate({"securepin": "1234", "confirmation": "renew"})

    assert result == {"renewal": {"state": "scheduled"}}
    assert captured["command"] == ["sudo", "-n", str(helper.resolve())]
    assert captured["input"] == b"1234\n"
    assert "1234" not in " ".join(captured["command"])


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"securepin": "123", "confirmation": "renew"}, "securepin_invalid"),
        ({"securepin": "1234", "confirmation": ""}, "confirmation_required"),
    ],
)
def test_certificate_reissue_requires_pin_and_confirmation(
    payload: dict[str, str], code: str
) -> None:
    with pytest.raises(AdminError) as failure:
        _renew_certificate(payload)
    assert failure.value.code == code


def test_certificate_reissue_maps_securepin_lockout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = tmp_path / "renew-web-certificate"
    helper.write_text("helper", encoding="utf-8")
    helper.chmod(0o755)
    monkeypatch.setenv("MCPSERVER_CERT_HELPER", str(helper.resolve()))
    monkeypatch.setattr(
        "mcpserver.admin._certificate_status",
        lambda: {"available": True, "renewal_supported": True},
    )
    monkeypatch.setattr(
        "mcpserver.admin.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 11, b"", b""),
    )

    with pytest.raises(AdminError) as failure:
        _renew_certificate({"securepin": "1234", "confirmation": "renew"})
    assert failure.value.code == "securepin_locked"


def test_failed_config_apply_restores_previous_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    previous = PluginConfig.defaults()
    store.save(previous)
    restarts = 0

    def restart() -> None:
        nonlocal restarts
        restarts += 1
        if restarts == 1:
            raise AdminError("simulated apply failure")

    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._restart_service", restart)

    with pytest.raises(AdminError, match="previous configuration restored"):
        _save(
            {
                "schema_version": 1,
                "server": {"enabled": True, "public_origin": "https://loxberry.example"},
                "loxone": {"endpoint": "http://192.168.10.20"},
            }
        )

    assert restarts == 2
    assert store.load().to_document() == previous.to_document()


def test_first_complete_configuration_does_not_enable_mcp_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    store.save(PluginConfig.defaults())
    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._restart_service", lambda: None)
    monkeypatch.setattr("mcpserver.admin._sessions", lambda: [])
    monkeypatch.setattr("mcpserver.admin._service_response", lambda: {"service_active": True})

    result = _save(
        {
            "schema_version": 4,
            "server": {"enabled": False, "public_origin": "https://loxberry.example"},
            "loxone": {"endpoint": "http://192.168.10.20"},
        }
    )

    assert store.load().enabled is False
    assert result["configuration"]["server"]["enabled"] is False


def test_partial_config_save_preserves_explorer_approvals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcpserver.config import ExplorerBindingApproval

    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    approval = ExplorerBindingApproval(
        binding_id="a" * 64,
        capability="loxberry:read",
        application_id="tool-explorer-v1",
        version=1,
        created_at=100,
        last_active_at=100,
        last_active_until=200,
    )
    store.save(replace(PluginConfig.defaults(), explorer_bindings=(approval,)))
    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._restart_service", lambda: None)
    monkeypatch.setattr("mcpserver.admin._sessions", lambda: [])
    monkeypatch.setattr("mcpserver.admin._service_response", lambda: {"service_active": True})

    _save(
        {
            "schema_version": 10,
            "server": {"enabled": False, "public_origin": "https://loxberry.example"},
            "loxone": {"endpoint": "http://192.168.10.20"},
        }
    )

    assert store.load().explorer_bindings == (approval,)


def test_section_saves_are_atomic_and_preserve_the_other_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    initial = PluginConfig(
        mqtt_enabled=True,
        mqtt_root_topic="existing",
        mqtt_heartbeat_seconds=120,
    )
    store.save(initial)
    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: False)
    monkeypatch.setattr("mcpserver.admin._service_response", lambda: {"service_active": False})

    _save_mcp(
        {
            "schema_version": 5,
            "server": {"enabled": False, "public_origin": "https://loxberry.example"},
            "loxone": {"endpoint": "http://192.168.10.20"},
        }
    )
    after_mcp = store.load()
    assert after_mcp.mqtt_enabled is True
    assert after_mcp.mqtt_root_topic == "existing"

    _save_mqtt(
        {
            "schema_version": 5,
            "mqtt": {"enabled": False, "root_topic": "mcpserver", "heartbeat_seconds": 60},
        }
    )
    after_mqtt = store.load()
    assert after_mqtt.public_origin == "https://loxberry.example"
    assert after_mqtt.loxone_endpoint == "http://192.168.10.20"
    assert after_mqtt.mqtt_enabled is False


def test_failed_mcp_section_apply_restores_running_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    previous = PluginConfig(public_origin="https://previous.example")
    store.save(previous)
    restarts = 0

    def restart() -> None:
        nonlocal restarts
        restarts += 1
        if restarts == 1:
            raise AdminError("simulated apply failure")

    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: True)
    monkeypatch.setattr("mcpserver.admin._restart_service", restart)

    with pytest.raises(AdminError, match="previous configuration restored"):
        _save_mcp(
            {
                "schema_version": 6,
                "server": {"enabled": True, "public_origin": "https://new.example"},
                "loxone": {"endpoint": "http://192.168.10.20"},
            }
        )

    assert restarts == 2
    assert store.load().to_document() == previous.to_document()


def test_failed_mcp_section_rollback_restart_reports_distinct_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    previous = PluginConfig(public_origin="https://previous.example")
    store.save(previous)
    restarts = 0

    def restart() -> None:
        nonlocal restarts
        restarts += 1
        raise AdminError("simulated restart failure")

    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: True)
    monkeypatch.setattr("mcpserver.admin._restart_service", restart)

    with pytest.raises(AdminError, match="MCP configuration apply and rollback failed"):
        _save_mcp(
            {
                "schema_version": 6,
                "server": {"enabled": True, "public_origin": "https://new.example"},
                "loxone": {"endpoint": "http://192.168.10.20"},
            }
        )

    assert restarts == 2
    assert store.load().to_document() == previous.to_document()


def test_failed_mcp_section_rollback_reports_distinct_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    previous = PluginConfig(public_origin="https://previous.example")
    store.save(previous)
    original_save = store._save_unlocked
    saves = 0

    def save(config: PluginConfig) -> None:
        nonlocal saves
        saves += 1
        if saves == 2:
            raise ConfigError("simulated rollback failure")
        original_save(config)

    monkeypatch.setattr(store, "_save_unlocked", save)
    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: True)
    monkeypatch.setattr(
        "mcpserver.admin._restart_service",
        lambda: (_ for _ in ()).throw(AdminError("simulated apply failure")),
    )

    with pytest.raises(AdminError, match="MCP configuration apply and rollback failed"):
        _save_mcp(
            {
                "schema_version": 6,
                "server": {"enabled": True, "public_origin": "https://new.example"},
                "loxone": {"endpoint": "http://192.168.10.20"},
            }
        )

    assert store.load().public_origin == "https://new.example"


def test_inactive_section_saves_do_not_restart_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    store.save(PluginConfig())
    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: False)
    monkeypatch.setattr(
        "mcpserver.admin._restart_service",
        lambda: (_ for _ in ()).throw(AssertionError("inactive service was restarted")),
    )
    monkeypatch.setattr("mcpserver.admin._service_response", lambda: {"service_active": False})

    _save_mcp(
        {
            "schema_version": 6,
            "server": {"enabled": True, "public_origin": "https://loxberry.example"},
            "loxone": {"endpoint": "http://192.168.10.20"},
        }
    )
    _save_mqtt(
        {
            "schema_version": 6,
            "mqtt": {
                "enabled": True,
                "root_topic": "mcpserver",
                "heartbeat_seconds": 60,
            },
        }
    )


def test_mqtt_gateway_status_masks_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcpserver.admin import _mqtt_gateway_status

    path = tmp_path / "config" / "system"
    path.mkdir(parents=True)
    (path / "general.json").write_text(
        json.dumps(
            {
                "Mqtt": {
                    "Brokerhost": "broker.local",
                    "Brokerport": "1883",
                    "Brokeruser": "sensitive-user",
                    "Brokerpass": "sensitive-password",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LBHOMEDIR", str(tmp_path))

    status = _mqtt_gateway_status()

    assert status == {
        "gateway_configured": True,
        "host": "broker.local",
        "port": 1883,
        "username": "sensitive-user",
    }
    assert "sensitive-password" not in json.dumps(status)


def test_save_mqtt_keeps_custom_password_out_of_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    store.save(PluginConfig())
    key = tmp_path / "data" / "auth" / "install.key"
    key.parent.mkdir(parents=True)
    key.write_bytes(b"k" * 32)
    credentials = key.with_name("mqtt-credentials.json.enc")
    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: False)
    monkeypatch.setattr("mcpserver.admin._service_response", lambda: {"service_active": False})
    monkeypatch.setenv("MCPSERVER_INSTALL_KEY", str(key.resolve()))
    monkeypatch.setenv("MCPSERVER_MQTT_CREDENTIALS", str(credentials.resolve()))

    result = _save_mqtt(
        {
            "schema_version": 6,
            "mqtt": {
                "enabled": True,
                "root_topic": "mcpserver",
                "heartbeat_seconds": 60,
                "use_loxberry_gateway": False,
                "host": "broker.example",
                "port": 1883,
                "username": "health",
            },
            "mqtt_password": "custom-secret",
        }
    )

    rendered = json.dumps(result)
    assert result["mqtt_password_configured"] is True
    assert "custom-secret" not in rendered
    assert "custom-secret" not in store.path.read_text(encoding="utf-8")
    assert "custom-secret" not in credentials.read_text(encoding="utf-8")

    cleared = _save_mqtt(
        {
            "schema_version": 6,
            "mqtt": {
                "enabled": True,
                "root_topic": "mcpserver",
                "heartbeat_seconds": 60,
                "use_loxberry_gateway": False,
                "host": "broker.example",
                "port": 1883,
                "username": "health",
            },
            "mqtt_clear_password": True,
        }
    )
    assert cleared["mqtt_password_configured"] is False
    assert not credentials.exists()


def test_save_mqtt_cleans_an_obsolete_destination_before_starting_the_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    previous = PluginConfig(
        mqtt_enabled=True,
        mqtt_root_topic="old",
        mqtt_use_loxberry_gateway=False,
        mqtt_host="broker.example",
        mqtt_username="health",
    )
    store.save(previous)
    key = tmp_path / "data" / "auth" / "install.key"
    key.parent.mkdir(parents=True)
    key.write_bytes(b"k" * 32)
    credentials = key.with_name("mqtt-credentials.json.enc")
    from mcpserver.mqtt_health import MqttCredentialStore

    MqttCredentialStore(credentials.resolve(), key.resolve()).save("previous-secret")
    calls: list[str] = []

    def cleanup(config: PluginConfig, **kwargs: object) -> bool:
        calls.append("cleanup")
        assert config.mqtt_root_topic == "old"
        assert config.mqtt_host == "broker.example"
        assert kwargs["broker"].password == "previous-secret"  # type: ignore[index,union-attr]
        return True

    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: True)
    monkeypatch.setattr("mcpserver.admin._stop_service", lambda: calls.append("stop"))
    monkeypatch.setattr("mcpserver.admin._start_service", lambda: calls.append("start"))
    monkeypatch.setattr("mcpserver.admin.clear_retained_topics", cleanup)
    monkeypatch.setattr("mcpserver.admin._service_response", lambda: {"service_active": True})
    monkeypatch.setenv("MCPSERVER_INSTALL_KEY", str(key.resolve()))
    monkeypatch.setenv("MCPSERVER_MQTT_CREDENTIALS", str(credentials.resolve()))

    result = _save_mqtt(
        {
            "schema_version": 6,
            "mqtt": {
                "enabled": True,
                "root_topic": "new",
                "heartbeat_seconds": 60,
                "use_loxberry_gateway": False,
                "host": "broker.example",
                "port": 1883,
                "username": "health",
            },
        }
    )

    assert calls == ["stop", "cleanup", "start"]
    assert result["retained_cleanup"] == {"status": "completed"}
    assert store.load().mqtt_root_topic == "new"


def test_save_mqtt_cleanup_failure_keeps_the_new_configuration_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    store.save(PluginConfig(mqtt_enabled=True, mqtt_root_topic="old"))
    calls: list[str] = []

    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: True)
    monkeypatch.setattr("mcpserver.admin._stop_service", lambda: calls.append("stop"))
    monkeypatch.setattr("mcpserver.admin._start_service", lambda: calls.append("start"))
    monkeypatch.setattr("mcpserver.admin.clear_retained_topics", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("mcpserver.admin._service_response", lambda: {"service_active": True})
    gateway = tmp_path / "config" / "system"
    gateway.mkdir(parents=True)
    (gateway / "general.json").write_text(
        json.dumps(
            {
                "Mqtt": {
                    "Brokerhost": "broker",
                    "Brokerport": 1883,
                    "Brokeruser": "u",
                    "Brokerpass": "p",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LBHOMEDIR", str(tmp_path))

    result = _save_mqtt(
        {
            "schema_version": 6,
            "mqtt": {"enabled": False, "root_topic": "old", "heartbeat_seconds": 60},
        }
    )

    assert calls == ["stop", "start"]
    assert result["retained_cleanup"] == {"status": "failed"}
    assert store.load().mqtt_enabled is False


def test_save_mqtt_credential_change_at_the_same_destination_uses_a_normal_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    previous = PluginConfig(
        mqtt_enabled=True,
        mqtt_use_loxberry_gateway=False,
        mqtt_host="broker.example",
        mqtt_username="health",
    )
    store.save(previous)
    key = tmp_path / "data" / "auth" / "install.key"
    key.parent.mkdir(parents=True)
    key.write_bytes(b"k" * 32)
    credentials = key.with_name("mqtt-credentials.json.enc")
    from mcpserver.mqtt_health import MqttCredentialStore

    MqttCredentialStore(credentials.resolve(), key.resolve()).save("previous-secret")
    restarts: list[str] = []
    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: True)
    monkeypatch.setattr("mcpserver.admin._restart_service", lambda: restarts.append("restart"))
    monkeypatch.setattr(
        "mcpserver.admin.clear_retained_topics",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected cleanup")),
    )
    monkeypatch.setattr("mcpserver.admin._service_response", lambda: {"service_active": True})
    monkeypatch.setenv("MCPSERVER_INSTALL_KEY", str(key.resolve()))
    monkeypatch.setenv("MCPSERVER_MQTT_CREDENTIALS", str(credentials.resolve()))

    result = _save_mqtt(
        {
            "schema_version": 6,
            "mqtt": {
                "enabled": True,
                "root_topic": "mcpserver",
                "heartbeat_seconds": 60,
                "use_loxberry_gateway": False,
                "host": "broker.example",
                "port": 1883,
                "username": "health",
            },
            "mqtt_password": "new-secret",
        }
    )

    assert restarts == ["restart"]
    assert result["retained_cleanup"] == {"status": "not_required"}


def test_failed_mqtt_apply_restores_previous_encrypted_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcpserver.mqtt_health import MqttCredentialStore

    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    previous = PluginConfig(mqtt_use_loxberry_gateway=False, mqtt_host="previous.example")
    store.save(previous)
    key = tmp_path / "data" / "auth" / "install.key"
    key.parent.mkdir(parents=True)
    key.write_bytes(b"k" * 32)
    credentials = key.with_name("mqtt-credentials.json.enc")
    credential_store = MqttCredentialStore(credentials.resolve(), key.resolve())
    credential_store.save("previous-secret")
    restarts = 0

    def restart() -> None:
        nonlocal restarts
        restarts += 1
        if restarts == 1:
            raise AdminError("simulated apply failure")

    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: True)
    monkeypatch.setattr("mcpserver.admin._restart_service", restart)
    monkeypatch.setenv("MCPSERVER_INSTALL_KEY", str(key.resolve()))
    monkeypatch.setenv("MCPSERVER_MQTT_CREDENTIALS", str(credentials.resolve()))

    with pytest.raises(AdminError, match="previous configuration restored"):
        _save_mqtt(
            {
                "schema_version": 6,
                "mqtt": {
                    "enabled": True,
                    "root_topic": "mcpserver",
                    "heartbeat_seconds": 60,
                    "use_loxberry_gateway": False,
                    "host": "new.example",
                    "port": 1883,
                    "username": "health",
                },
                "mqtt_password": "new-secret",
            }
        )

    assert restarts == 2
    assert store.load().mqtt_host == "previous.example"
    assert credential_store.load() == "previous-secret"


def test_failed_mqtt_credential_rollback_reports_distinct_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcpserver.mqtt_health import MqttCredentialStore, MqttCredentialStoreError

    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    previous = PluginConfig(mqtt_use_loxberry_gateway=False, mqtt_host="previous.example")
    store.save(previous)
    key = tmp_path / "data" / "auth" / "install.key"
    key.parent.mkdir(parents=True)
    key.write_bytes(b"k" * 32)
    credentials = key.with_name("mqtt-credentials.json.enc")
    credential_store = MqttCredentialStore(credentials.resolve(), key.resolve())
    credential_store.save("previous-secret")
    original_save = MqttCredentialStore.save
    save_calls = 0
    restarts = 0

    def save(target: MqttCredentialStore, password: str) -> None:
        nonlocal save_calls
        save_calls += 1
        if save_calls == 2:
            raise MqttCredentialStoreError("simulated credential rollback failure")
        original_save(target, password)

    def restart() -> None:
        nonlocal restarts
        restarts += 1
        raise AdminError("simulated apply failure")

    monkeypatch.setattr(MqttCredentialStore, "save", save)
    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: True)
    monkeypatch.setattr("mcpserver.admin._restart_service", restart)
    monkeypatch.setenv("MCPSERVER_INSTALL_KEY", str(key.resolve()))
    monkeypatch.setenv("MCPSERVER_MQTT_CREDENTIALS", str(credentials.resolve()))

    with pytest.raises(AdminError, match="MQTT configuration apply and rollback failed"):
        _save_mqtt(
            {
                "schema_version": 6,
                "mqtt": {
                    "enabled": True,
                    "root_topic": "mcpserver",
                    "heartbeat_seconds": 60,
                    "use_loxberry_gateway": False,
                    "host": "new.example",
                    "port": 1883,
                    "username": "health",
                },
                "mqtt_password": "new-secret",
            }
        )

    assert restarts == 1
    assert store.load().mqtt_host == "previous.example"
    assert credential_store.load() == "new-secret"


def test_failed_mqtt_credential_persistence_restores_previous_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcpserver.mqtt_health import MqttCredentialStore, MqttCredentialStoreError

    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    previous = PluginConfig(mqtt_use_loxberry_gateway=False, mqtt_host="previous.example")
    store.save(previous)
    key = tmp_path / "data" / "auth" / "install.key"
    key.parent.mkdir(parents=True)
    key.write_bytes(b"k" * 32)
    credentials = key.with_name("mqtt-credentials.json.enc")
    credential_store = MqttCredentialStore(credentials.resolve(), key.resolve())
    credential_store.save("previous-secret")
    original_save = MqttCredentialStore.save
    saves = 0

    def save(target: MqttCredentialStore, password: str) -> None:
        nonlocal saves
        saves += 1
        original_save(target, password)
        if saves == 1:
            raise MqttCredentialStoreError("simulated post-replace credential failure")

    monkeypatch.setattr(MqttCredentialStore, "save", save)
    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: True)
    monkeypatch.setattr(
        "mcpserver.admin._restart_service",
        lambda: (_ for _ in ()).throw(AssertionError("service was restarted")),
    )
    monkeypatch.setenv("MCPSERVER_INSTALL_KEY", str(key.resolve()))
    monkeypatch.setenv("MCPSERVER_MQTT_CREDENTIALS", str(credentials.resolve()))

    with pytest.raises(AdminError, match="previous configuration restored"):
        _save_mqtt(
            {
                "schema_version": 6,
                "mqtt": {
                    "enabled": True,
                    "root_topic": "mcpserver",
                    "heartbeat_seconds": 60,
                    "use_loxberry_gateway": False,
                    "host": "new.example",
                    "port": 1883,
                    "username": "health",
                },
                "mqtt_password": "new-secret",
            }
        )


def test_failed_mqtt_config_persistence_restores_changed_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcpserver.mqtt_health import MqttCredentialStore

    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    previous = PluginConfig(mqtt_use_loxberry_gateway=False, mqtt_host="previous.example")
    store.save(previous)
    key = tmp_path / "data" / "auth" / "install.key"
    key.parent.mkdir(parents=True)
    key.write_bytes(b"k" * 32)
    credentials = key.with_name("mqtt-credentials.json.enc")
    credential_store = MqttCredentialStore(credentials.resolve(), key.resolve())
    credential_store.save("previous-secret")

    original_save = store._save_unlocked
    saves = 0

    def fail_save(config: PluginConfig) -> None:
        nonlocal saves
        saves += 1
        original_save(config)
        if saves == 1:
            raise ConfigError("simulated post-replace persistence failure")

    restarts = 0

    def restart() -> None:
        nonlocal restarts
        restarts += 1

    monkeypatch.setattr(store, "_save_unlocked", fail_save)
    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: True)
    monkeypatch.setattr("mcpserver.admin._restart_service", restart)
    monkeypatch.setenv("MCPSERVER_INSTALL_KEY", str(key.resolve()))
    monkeypatch.setenv("MCPSERVER_MQTT_CREDENTIALS", str(credentials.resolve()))

    with pytest.raises(AdminError, match="previous configuration restored"):
        _save_mqtt(
            {
                "schema_version": 6,
                "mqtt": {
                    "enabled": True,
                    "root_topic": "mcpserver",
                    "heartbeat_seconds": 60,
                    "use_loxberry_gateway": False,
                    "host": "new.example",
                    "port": 1883,
                    "username": "health",
                },
                "mqtt_password": "new-secret",
            }
        )

    assert restarts == 0
    assert store.load().mqtt_host == "previous.example"
    assert credential_store.load() == "previous-secret"


def test_concurrent_mqtt_saves_keep_broker_and_password_paired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcpserver.mqtt_health import MqttCredentialStore

    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    store.save(PluginConfig())
    key = tmp_path / "data" / "auth" / "install.key"
    key.parent.mkdir(parents=True)
    key.write_bytes(b"k" * 32)
    credentials = key.with_name("mqtt-credentials.json.enc")
    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: False)
    monkeypatch.setattr("mcpserver.admin._service_response", lambda: {"service_active": False})
    monkeypatch.setattr("mcpserver.admin.clear_retained_topics", lambda *_args, **_kwargs: True)
    monkeypatch.setenv("MCPSERVER_INSTALL_KEY", str(key.resolve()))
    monkeypatch.setenv("MCPSERVER_MQTT_CREDENTIALS", str(credentials.resolve()))

    def save(host: str, password: str) -> None:
        _save_mqtt(
            {
                "schema_version": 6,
                "mqtt": {
                    "enabled": True,
                    "root_topic": "mcpserver",
                    "heartbeat_seconds": 60,
                    "use_loxberry_gateway": False,
                    "host": host,
                    "port": 1883,
                    "username": host,
                },
                "mqtt_password": password,
            }
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(save, "one.example", "one-secret"),
            executor.submit(save, "two.example", "two-secret"),
        ]
        for future in futures:
            future.result()

    final = store.load()
    password = MqttCredentialStore(credentials.resolve(), key.resolve()).load()
    assert (final.mqtt_host, final.mqtt_username, password) in {
        ("one.example", "one.example", "one-secret"),
        ("two.example", "two.example", "two-secret"),
    }


@pytest.mark.parametrize(
    ("enabled", "commands"),
    [(True, ["enable", "start"]), (False, ["disable", "stop"])],
)
def test_master_service_state_uses_only_fixed_systemd_operations(
    enabled: bool, commands: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []
    monkeypatch.setattr("mcpserver.admin._run_service_command", called.append)
    monkeypatch.setattr(
        "mcpserver.admin._service_status",
        lambda: {"enabled": not enabled, "active": not enabled},
    )
    response = {"service_active": enabled, "service": {"enabled": enabled, "active": enabled}}
    monkeypatch.setattr("mcpserver.admin._service_response", lambda: response)

    assert dispatch({"action": "set_service_enabled", "payload": {"enabled": enabled}}) == response
    assert called == commands


def test_failed_master_service_second_action_compensates(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def command(value: str) -> None:
        called.append(value)
        if value == "start":
            raise AdminError("failed")

    monkeypatch.setattr("mcpserver.admin._run_service_command", command)
    monkeypatch.setattr(
        "mcpserver.admin._service_status", lambda: {"enabled": False, "active": False}
    )

    with pytest.raises(AdminError, match="not applied"):
        dispatch({"action": "set_service_enabled", "payload": {"enabled": True}})

    assert called == ["enable", "start", "disable", "stop"]


def test_master_service_state_rejects_an_unconfirmed_systemd_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    monkeypatch.setattr("mcpserver.admin._run_service_command", called.append)
    monkeypatch.setattr(
        "mcpserver.admin._service_status", lambda: {"enabled": False, "active": False}
    )
    monkeypatch.setattr(
        "mcpserver.admin._service_response",
        lambda: {"service_active": False, "service": {"enabled": False, "active": False}},
    )

    with pytest.raises(AdminError, match="not applied"):
        dispatch({"action": "set_service_enabled", "payload": {"enabled": True}})

    assert called == ["enable", "start", "disable", "stop"]


def test_first_complete_configuration_respects_disabled_read_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    store.save(PluginConfig.defaults())
    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._restart_service", lambda: None)
    monkeypatch.setattr("mcpserver.admin._sessions", lambda: [])
    monkeypatch.setattr("mcpserver.admin._service_response", lambda: {"service_active": True})

    result = _save(
        {
            "schema_version": 4,
            "server": {"enabled": False, "public_origin": "https://loxberry.example"},
            "loxone": {"endpoint": "http://192.168.10.20"},
            "tools": {"loxone_read_enabled": False},
        }
    )

    assert store.load().enabled is False
    assert result["configuration"]["server"]["enabled"] is False


@pytest.mark.parametrize(
    "mode",
    ["off", "error", "warning", "info", "debug"],
)
def test_logging_mode_is_validated_persisted_and_applied(
    mode: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    store.save(PluginConfig.defaults())
    restarts: list[str] = []
    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._restart_service", lambda: restarts.append("restart"))

    result = _set_logging({"mode": mode})

    assert store.load().log_level == mode
    assert result["configuration"]["logging"] == {"level": mode}
    assert restarts == ["restart"]


def test_invalid_logging_mode_is_rejected_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    store.save(PluginConfig.defaults())
    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)

    with pytest.raises(AdminError, match="logging mode is invalid"):
        _set_logging({"mode": "debug_15"})

    assert store.load().to_document() == PluginConfig.defaults().to_document()


def test_main_config_save_preserves_separately_managed_logging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    previous = PluginConfig(log_level="debug", _source={})
    store.save(previous)
    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._restart_service", lambda: None)
    monkeypatch.setattr("mcpserver.admin._sessions", lambda: [])
    monkeypatch.setattr(
        "mcpserver.admin._service_response",
        lambda: {"service_active": True, "service": {"active": True}},
    )

    _save({"schema_version": 1, "server": {"enabled": False}})

    assert store.load().log_level == "debug"


def test_disabling_control_revokes_control_sessions_after_successful_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    previous_document = PluginConfig.defaults().to_document()
    previous_document["tools"]["loxone_control_enabled"] = True
    previous_document["loxone"]["endpoint"] = "http://192.168.10.20"
    previous = PluginConfig.from_document(previous_document)
    store.save(previous)
    next_document = previous.to_document()
    next_document["tools"]["loxone_control_enabled"] = False
    next_document["loxone"]["endpoint"] = "http://192.168.10.30"
    events: list[str] = []
    revocations: list[tuple[list[str], str | None, float | None]] = []

    class AuthStore:
        def snapshot(self) -> dict[str, object]:
            return {
                "families": {
                    "control-family": {
                        "scope": "loxone:read loxone:control",
                        "revoked": False,
                    },
                    "read-family": {"scope": "loxone:read", "revoked": False},
                }
            }

    monkeypatch.setattr("mcpserver.admin._config_store", lambda: store)
    monkeypatch.setattr("mcpserver.admin._auth_store", lambda: AuthStore())
    monkeypatch.setattr("mcpserver.admin._restart_service", lambda: events.append("restart"))

    def revoke_many(
        family_ids: list[str],
        *,
        endpoint: str | None = None,
        timeout_seconds: float | None = None,
    ) -> int:
        events.append(f"revoke:{','.join(family_ids)}")
        revocations.append((family_ids, endpoint, timeout_seconds))
        return len(family_ids)

    monkeypatch.setattr("mcpserver.admin._revoke_many", revoke_many)

    _save(next_document)

    assert events == ["restart", "revoke:control-family"]
    assert revocations == [
        (["control-family"], "http://192.168.10.20", previous.connection_timeout)
    ]


def test_session_list_excludes_revoked_families(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    store = AtomicJsonAuthStore(auth_path)

    def add_families(document: dict[str, object]) -> None:
        clients = document["clients"]
        families = document["families"]
        assert isinstance(clients, dict)
        assert isinstance(families, dict)
        clients["active-client"] = {"client_name": "Claude Desktop"}
        families["active-family"] = {
            "client_id": "active-client",
            "identity_id": "active-identity",
            "expires_at": 1_900_000_000,
            "revoked": False,
        }
        families["revoked-family"] = {
            "client_id": "revoked-client",
            "identity_id": "revoked-identity",
            "expires_at": 1_900_000_000,
            "revoked": True,
        }

    store.mutate(add_families)
    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))

    result = dispatch({"action": "list_sessions"})

    assert [session["id"] for session in result["sessions"]] == ["active-family"]
    assert result["sessions"][0]["client_name"] == "Claude Desktop"
    assert result["sessions"][0]["client"] == "active-clien"


def test_remote_cleanup_admin_status_is_aggregate_and_value_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = tmp_path / "install.key"
    key.write_bytes(b"k" * 32)
    token_store = EncryptedLoxoneTokenStore(tmp_path / "tokens.enc", key)
    token_store.put(
        "private-family",
        "private-miniserver",
        "private-identity",
        LoxoneToken("private-jwt", "private-user", "private-key", "SHA256", 2_000_000_000),
    )
    token_store.schedule_remote_revoke("private-family")
    sidecar = RemoteRevocationState(token_store.path)
    value = sidecar.read()
    value["last_failure_category"] = "transport_failed"
    value["last_failure_at"] = 123
    sidecar.write(value)

    class Config:
        def load(self) -> PluginConfig:
            return PluginConfig.defaults()

    monkeypatch.setattr("mcpserver.admin._token_store", lambda: token_store)
    monkeypatch.setattr("mcpserver.admin._config_store", Config)
    status = _remote_cleanup_status()
    assert status["available"] is True
    assert status["pending"] == 1
    assert status["last_failure_category"] == "transport_failed"
    rendered = json.dumps(status)
    for secret in ("private-family", "private-miniserver", "private-identity", "private-jwt"):
        assert secret not in rendered


def test_admin_can_confirm_a_faulty_loxone_token_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    store = AtomicJsonAuthStore(auth_path)
    store.mutate(
        lambda document: document["families"].update(
            {
                "family": {
                    "client_id": "client",
                    "identity_id": "identity",
                    "revoked": False,
                    "loxone_token_confirmation_required": True,
                    "loxone_token_rejections": 3,
                    "loxone_token_rejection_kind": "token_authentication",
                }
            }
        )
    )
    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))

    result = dispatch({"action": "confirm_loxone_token", "payload": {"session_id": "family"}})

    assert result["sessions"][0]["loxone_token_confirmation_required"] is False
    record = store.snapshot()["families"]["family"]
    assert "loxone_token_confirmation_required" not in record
    assert "loxone_token_rejections" not in record
    assert "loxone_token_rejection_kind" not in record


def test_session_list_uses_empty_name_for_missing_or_invalid_client_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    store = AtomicJsonAuthStore(auth_path)

    def add_records(document: dict[str, object]) -> None:
        clients = document["clients"]
        families = document["families"]
        assert isinstance(clients, dict)
        assert isinstance(families, dict)
        clients["invalid-client"] = {"client_name": 42}
        clients["blank-client"] = {"client_name": "   "}
        families["invalid-family"] = {"client_id": "invalid-client", "revoked": False}
        families["blank-family"] = {"client_id": "blank-client", "revoked": False}
        families["missing-family"] = {"client_id": "missing-client", "revoked": False}

    store.mutate(add_records)
    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))

    sessions = dispatch({"action": "list_sessions"})["sessions"]

    assert {session["client_name"] for session in sessions} == {""}


def test_revoke_response_contains_updated_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mcpserver.admin._revoke", lambda family_id: 1)
    monkeypatch.setattr("mcpserver.admin._sessions", lambda: [])

    result = dispatch({"action": "revoke_session", "payload": {"id": "family"}})

    assert result == {"revoked": 1, "sessions": []}


def test_revoke_survives_unreadable_encrypted_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    store = AtomicJsonAuthStore(auth_path)

    def add_family(document: dict[str, object]) -> None:
        families = document["families"]
        assert isinstance(families, dict)
        families["family"] = {
            "client_id": "client",
            "identity_id": "identity",
            "miniserver_id": "miniserver",
            "expires_at": 1_900_000_000,
            "revoked": False,
        }

    store.mutate(add_family)

    class BrokenTokenStore:
        def schedule_remote_revoke(self, family_id: str) -> None:
            raise LoxoneTokenStoreError("cannot read store")

    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))
    monkeypatch.setattr("mcpserver.admin._token_store", lambda: BrokenTokenStore())
    monkeypatch.setattr(
        "mcpserver.admin._config_store",
        lambda: type(
            "ConfigStore",
            (),
            {
                "load": lambda self: PluginConfig.from_document(
                    {
                        "schema_version": 1,
                        "loxone": {"endpoint": "http://192.168.10.20"},
                    }
                )
            },
        )(),
    )

    assert _revoke(None) == 1
    assert store.snapshot()["families"]["family"]["revoked"] is True


def test_revoke_survives_corrupt_encrypted_token_store_constructor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    token_path = (tmp_path / "data" / "auth" / "loxone-tokens.json.enc").resolve()
    key_path = (tmp_path / "data" / "auth" / "install.key").resolve()
    store = AtomicJsonAuthStore(auth_path)

    def add_family(document: dict[str, object]) -> None:
        families = document["families"]
        assert isinstance(families, dict)
        families["family"] = {
            "client_id": "client",
            "identity_id": "identity",
            "miniserver_id": "miniserver",
            "expires_at": 1_900_000_000,
            "revoked": False,
        }

    store.mutate(add_family)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("not-json", encoding="utf-8")
    key_path.write_bytes(b"k" * 32)
    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))
    monkeypatch.setenv("MCPSERVER_LOXONE_TOKEN_STORE", str(token_path))
    monkeypatch.setenv("MCPSERVER_INSTALL_KEY", str(key_path))
    monkeypatch.setattr(
        "mcpserver.admin._config_store",
        lambda: type("ConfigStore", (), {"load": lambda self: PluginConfig.defaults()})(),
    )

    assert _revoke("family") == 1
    assert store.snapshot()["families"]["family"]["revoked"] is True


def test_revoke_queues_local_token_after_remote_protocol_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    store = AtomicJsonAuthStore(auth_path)

    def add_family(document: dict[str, object]) -> None:
        families = document["families"]
        assert isinstance(families, dict)
        families["family"] = {
            "client_id": "client",
            "identity_id": "identity",
            "miniserver_id": "miniserver",
            "expires_at": 1_900_000_000,
            "revoked": False,
        }

    store.mutate(add_family)
    queued: list[str] = []

    class TrackingTokenStore:
        def schedule_remote_revoke(self, family_id: str) -> None:
            queued.append(family_id)

    class ProtocolFailingClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def kill_token(self, token: LoxoneToken) -> None:
            raise LoxoneProtocolError("unexpected response")

    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))
    monkeypatch.setattr("mcpserver.admin._token_store", lambda: TrackingTokenStore())
    monkeypatch.setattr("mcpserver.admin._loxone_client", ProtocolFailingClient)
    monkeypatch.setattr(
        "mcpserver.admin._config_store",
        lambda: type(
            "ConfigStore",
            (),
            {
                "load": lambda self: PluginConfig.from_document(
                    {
                        "schema_version": 1,
                        "loxone": {"endpoint": "http://192.168.10.20"},
                    }
                )
            },
        )(),
    )

    assert _revoke("family") == 1
    assert queued == ["family"]
    assert store.snapshot()["families"]["family"]["revoked"] is True


def test_revoke_queues_remote_tokens_without_waiting_for_miniserver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    store = AtomicJsonAuthStore(auth_path)

    def add_families(document: dict[str, object]) -> None:
        families = document["families"]
        assert isinstance(families, dict)
        for number in range(2):
            families[f"family-{number}"] = {
                "client_id": f"client-{number}",
                "identity_id": f"identity-{number}",
                "miniserver_id": "miniserver",
                "revoked": False,
            }

    store.mutate(add_families)
    queued: list[str] = []

    class TokenStore:
        def schedule_remote_revoke(self, family_id: str) -> None:
            queued.append(family_id)

    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))
    monkeypatch.setattr("mcpserver.admin._token_store", lambda: TokenStore())
    monkeypatch.setattr(
        "mcpserver.admin._config_store",
        lambda: type(
            "ConfigStore",
            (),
            {
                "load": lambda self: PluginConfig.from_document(
                    {
                        "schema_version": 1,
                        "loxone": {"endpoint": "http://192.168.10.20"},
                    }
                )
            },
        )(),
    )

    assert _revoke(None) == 2
    assert sorted(queued) == ["family-0", "family-1"]
