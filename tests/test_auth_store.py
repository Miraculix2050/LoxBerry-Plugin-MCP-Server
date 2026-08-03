from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mcpserver.auth.store import AtomicJsonAuthStore, AuthStoreError, token_digest


def test_store_is_atomic_and_persists_only_supplied_digests(tmp_path: Path) -> None:
    path = tmp_path / "auth" / "sessions.json"
    store = AtomicJsonAuthStore(path)
    raw = "opaque-secret-value"

    store.mutate(lambda document: document["access_tokens"].update({token_digest(raw): {}}))

    serialized = path.read_text(encoding="utf-8")
    assert raw not in serialized
    assert token_digest(raw) in serialized
    assert json.loads(serialized)["schema_version"] == 1
    assert not list(path.parent.glob("*.tmp"))
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700


def test_store_fails_closed_on_corruption(tmp_path: Path) -> None:
    path = tmp_path / "auth" / "sessions.json"
    store = AtomicJsonAuthStore(path)
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(AuthStoreError, match="corrupt"):
        store.snapshot()

    assert path.read_text(encoding="utf-8") == "not-json"


def test_pseudonyms_are_stable_and_store_local(tmp_path: Path) -> None:
    first = AtomicJsonAuthStore(tmp_path / "one" / "sessions.json")
    second = AtomicJsonAuthStore(tmp_path / "two" / "sessions.json")

    assert first.pseudonym("server", "user") == first.pseudonym("server", "user")
    assert first.pseudonym("server", "user") != second.pseudonym("server", "user")
