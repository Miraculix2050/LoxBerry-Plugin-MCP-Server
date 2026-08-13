from __future__ import annotations

from pathlib import Path

import pytest

from mcpserver.auth.loxone_store import (
    EncryptedLoxoneTokenStore,
    ExplorerSession,
    LoxoneTokenStoreError,
)
from mcpserver.loxone.client import LoxoneToken


def _store(tmp_path: Path) -> EncryptedLoxoneTokenStore:
    key = tmp_path / "install.key"
    key.write_bytes(b"k" * 32)
    return EncryptedLoxoneTokenStore((tmp_path / "loxone-tokens.json.enc").resolve(), key.resolve())


def _token() -> LoxoneToken:
    return LoxoneToken("secret-jwt", "reader", "hash-key", "SHA256", 2_000_000_000)


def test_token_is_encrypted_and_bound_to_family_identity_and_miniserver(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.put("family", "miniserver", "identity", _token())

    raw = store.path.read_text(encoding="utf-8")
    assert "secret-jwt" not in raw
    assert store.get("family", "miniserver", "identity") == _token()
    with pytest.raises(LoxoneTokenStoreError, match="binding"):
        store.get("family", "other", "identity")


def test_delete_removes_only_selected_family(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.put("family-1", "miniserver", "identity", _token())
    store.put("family-2", "miniserver", "identity", _token())

    store.delete("family-1")

    assert store.get("family-1", "miniserver", "identity") is None
    assert store.family_ids() == ("family-2",)


def test_wrong_installation_key_cannot_decrypt(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.put("family", "miniserver", "identity", _token())
    store.key_path.write_bytes(b"z" * 32)
    reopened = EncryptedLoxoneTokenStore(store.path, store.key_path)

    with pytest.raises(LoxoneTokenStoreError, match="cannot be decrypted"):
        reopened.get("family", "miniserver", "identity")


def test_explorer_session_is_encrypted_and_removed_with_its_oauth_family(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session = ExplorerSession(
        "browser-session",
        "family",
        "client",
        "https://example/mcp",
        "loxone:read",
        "access-secret",
        2_000_000_000,
        "refresh-secret",
        2_000_010_000,
    )

    store.put_explorer_session(session)

    assert "access-secret" not in store.path.read_text(encoding="utf-8")
    assert "refresh-secret" not in store.path.read_text(encoding="utf-8")
    assert store.get_explorer_session("browser-session") == session
    store.delete_explorer_family("family")
    assert store.get_explorer_session("browser-session") is None


def test_remote_revocation_keeps_token_until_confirmed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    token = LoxoneToken("token-secret", "user", "key", "SHA256", 2_000_000_000)
    store.put("family", "miniserver", "identity", token)

    assert store.schedule_remote_revoke("family") is True
    assert store.pending_remote_revocations(0)[0].token == token
    store.defer_remote_revoke("family", 0)
    assert store.pending_remote_revocations(1) == ()
    assert store.pending_remote_revocations(2)[0].family_id == "family"
    store.complete_remote_revoke("family")
    assert store.get("family", "miniserver", "identity") is None
