from __future__ import annotations

from pathlib import Path

import pytest

from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore, LoxoneTokenStoreError
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
