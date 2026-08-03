from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcpserver.admin import _revoke, dispatch
from mcpserver.auth.loxone_store import LoxoneTokenStoreError
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.config import AtomicConfigStore, PluginConfig


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


def test_session_list_excludes_revoked_families(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_path = (tmp_path / "data" / "auth" / "sessions.json").resolve()
    store = AtomicJsonAuthStore(auth_path)

    def add_families(document: dict[str, object]) -> None:
        families = document["families"]
        assert isinstance(families, dict)
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
        def get(self, family_id: str, miniserver_id: str, identity_id: str) -> None:
            raise LoxoneTokenStoreError("cannot decrypt")

        def delete(self, family_id: str) -> None:
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
