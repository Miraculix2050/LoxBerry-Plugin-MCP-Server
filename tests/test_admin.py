from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from mcpserver.admin import AdminError, _renew_certificate, _revoke, _save, dispatch
from mcpserver.auth.loxone_store import LoxoneTokenStoreError
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.loxone.client import LoxoneToken
from mcpserver.loxone.events import LoxoneProtocolError


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


def test_page_state_aggregates_initial_admin_ui_data(monkeypatch: pytest.MonkeyPatch) -> None:
    config = PluginConfig.defaults()

    class ConfigStore:
        def load(self) -> PluginConfig:
            return config

    monkeypatch.setattr("mcpserver.admin._config_store", lambda: ConfigStore())
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: True)
    monkeypatch.setattr("mcpserver.admin._sessions", lambda: [{"id": "family"}])
    monkeypatch.setattr(
        "mcpserver.admin._certificate_status",
        lambda: {"available": True, "renewal_supported": False},
    )

    result = dispatch({"action": "page_state"})

    assert result == {
        "configuration": config.to_document(),
        "version": result["version"],
        "service_active": True,
        "sessions": [{"id": "family"}],
        "certificate": {"available": True, "renewal_supported": False},
    }


def test_status_refresh_returns_all_dynamic_admin_ui_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = [{"id": "family"}]
    certificate = {"available": True, "renewal": {"state": "idle"}}
    monkeypatch.setattr("mcpserver.admin._service_active", lambda: True)
    monkeypatch.setattr("mcpserver.admin._sessions", lambda: sessions)
    monkeypatch.setattr("mcpserver.admin._certificate_status", lambda: certificate)

    result = dispatch({"action": "status"})

    assert result == {
        "version": result["version"],
        "service_active": True,
        "sessions": sessions,
        "certificate": certificate,
    }


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


def test_revoke_deletes_local_token_after_remote_protocol_error(
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
    deleted: list[str] = []

    class TrackingTokenStore:
        def get(self, family_id: str, miniserver_id: str, identity_id: str) -> LoxoneToken:
            return LoxoneToken("jwt", "user", "key", "SHA256", 1)

        def delete(self, family_id: str) -> None:
            deleted.append(family_id)

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
    assert deleted == ["family"]
    assert store.snapshot()["families"]["family"]["revoked"] is True


def test_revoke_kills_remote_tokens_concurrently(
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
    active = 0
    maximum_active = 0
    deleted: list[str] = []

    class TokenStore:
        def get(self, family_id: str, miniserver_id: str, identity_id: str) -> LoxoneToken:
            return LoxoneToken(family_id, identity_id, "key", "SHA256", 1)

        def delete(self, family_id: str) -> None:
            deleted.append(family_id)

    class ConcurrentClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def kill_token(self, token: LoxoneToken) -> None:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0)
            active -= 1

    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(auth_path))
    monkeypatch.setattr("mcpserver.admin._token_store", lambda: TokenStore())
    monkeypatch.setattr("mcpserver.admin._loxone_client", ConcurrentClient)
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
    assert maximum_active == 2
    assert sorted(deleted) == ["family-0", "family-1"]
