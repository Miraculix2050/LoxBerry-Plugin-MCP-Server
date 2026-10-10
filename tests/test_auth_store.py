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


def test_existing_store_is_secured_before_it_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "auth" / "sessions.json"
    AtomicJsonAuthStore(path)
    calls: list[tuple[Path, int]] = []
    real_chmod = os.chmod

    def recording_chmod(
        target: str | bytes | os.PathLike[str] | os.PathLike[bytes], mode: int
    ) -> None:
        calls.append((Path(target), mode))
        real_chmod(target, mode)

    monkeypatch.setattr("mcpserver.auth.store.os.chmod", recording_chmod)
    AtomicJsonAuthStore(path)

    assert (path, 0o600) in calls


def test_pseudonyms_are_stable_and_store_local(tmp_path: Path) -> None:
    first = AtomicJsonAuthStore(tmp_path / "one" / "sessions.json")
    second = AtomicJsonAuthStore(tmp_path / "two" / "sessions.json")

    assert first.pseudonym("server", "user") == first.pseudonym("server", "user")
    assert first.pseudonym("server", "user") != second.pseudonym("server", "user")


@pytest.mark.parametrize("legacy", [False, True])
def test_first_revocation_cause_survives_repeated_revocation(tmp_path, legacy, caplog):
    from mcpserver.auth.store import mark_family_revoked, revocation_details

    store = AtomicJsonAuthStore(tmp_path / "sessions.json")
    family = {"client_id": "private-client", "revoked": legacy, "expires_at": 2000000000}
    if legacy:
        family["revoked_at"] = 100
    store.mutate(lambda doc: doc["families"].update({"private-family": family}))
    caplog.set_level("INFO", logger="mcpserver.auth.lifecycle")
    caplog.clear()

    def revoke(doc):
        mark_family_revoked(
            doc["families"]["private-family"], now=200, reason="refresh_reuse", source="oauth"
        )

    store.mutate(revoke)
    store.mutate(
        lambda doc: mark_family_revoked(
            doc["families"]["private-family"], now=300, reason="admin_session", source="admin"
        )
    )
    retained = store.snapshot()["families"]["private-family"]
    assert retained["revoked_at"] == (100 if legacy else 200)
    assert revocation_details(retained) == (
        ("unknown", "unknown") if legacy else ("refresh_reuse", "oauth")
    )
    assert len(caplog.records) == (0 if legacy else 1)
    assert "private-family" not in caplog.text
    assert "private-client" not in caplog.text


def test_lifecycle_logs_follow_commit_and_are_silent_for_reads(tmp_path, monkeypatch, caplog):
    store = AtomicJsonAuthStore(tmp_path / "sessions.json")
    caplog.set_level("DEBUG", logger="mcpserver.auth.lifecycle")
    captured = []
    original_write = store._write_unlocked

    def write(doc):
        assert not caplog.records
        original_write(doc)
        captured.append(True)

    monkeypatch.setattr(store, "_write_unlocked", write)
    store.mutate(
        lambda doc: doc["clients"].update({"secret-client": {"client_name": "private-name"}})
    )
    assert captured == [True]
    assert "event=client_registered" in caplog.text
    assert "secret-client" not in caplog.text and "private-name" not in caplog.text
    caplog.clear()
    store.snapshot()
    store.mutate(lambda doc: None)
    assert not caplog.records

    def fail(_doc):
        raise AuthStoreError("synthetic failure")

    monkeypatch.setattr(store, "_write_unlocked", fail)
    with pytest.raises(AuthStoreError):
        store.mutate(lambda doc: doc["families"].update({"never-committed": {}}))
    assert not caplog.records
    assert "never-committed" not in store.snapshot()["families"]


def test_lifecycle_summary_is_bounded_and_sanitizes_legacy_metadata(tmp_path):
    from mcpserver.auth.store import lifecycle_summary

    store = AtomicJsonAuthStore(tmp_path / "sessions.json")
    store.mutate(
        lambda doc: doc["families"].update(
            {
                f"private-family-{i}": {
                    "client_id": "private-client",
                    "revoked": True,
                    "revoked_at": i,
                    "revocation_reason": "secret-reason",
                    "revocation_source": "secret-source",
                    "identity_id": "private-identity",
                    "token": "never-exported",
                }
                for i in range(25)
            }
        )
    )
    before = store.path.read_bytes()
    summary = lifecycle_summary(store.snapshot())
    assert summary["retained_revoked"] == 25
    assert summary["reason_counts"] == {"unknown": 25}
    assert len(summary["recent_revocations"]) == 20
    assert summary["recent_revocations"][0]["revoked_at"] == 24
    serialized = json.dumps(summary)
    for raw in (
        "private-family",
        "private-client",
        "private-identity",
        "never-exported",
        "secret-reason",
        "secret-source",
    ):
        assert raw not in serialized
    assert store.path.read_bytes() == before


def test_lifecycle_event_is_fixed_bounded_and_failure_is_non_fatal(tmp_path, caplog, monkeypatch):
    from mcpserver.auth import store as auth_store

    caplog.set_level("DEBUG", logger="mcpserver.auth.lifecycle")
    auth_store.lifecycle_event(
        "family_revoked",
        family_id="opaque-private",
        client_ref="unsafe\ntext",
        reason="arbitrary\nsecret",
        source="private",
        outcome="unsafe",
        count=999999,
    )
    assert "reason=unknown source=unknown outcome=unknown count=10000" in caplog.text
    assert "opaque-private" not in caplog.text and "arbitrary" not in caplog.text
    assert "client_ref=-" in caplog.text
    auth_store.lifecycle_event("unknown\nevent")
    assert len(caplog.records) == 1
    assert auth_store.lifecycle_reference(
        "family", "opaque-private"
    ) != auth_store.lifecycle_reference("binding", "opaque-private")
    first = AtomicJsonAuthStore(tmp_path / "first.json").snapshot()
    second = AtomicJsonAuthStore(tmp_path / "second.json").snapshot()
    assert auth_store.lifecycle_client_reference(
        first, "chosen"
    ) != auth_store.lifecycle_client_reference(second, "chosen")

    def fail(*args, **kwargs):
        raise RuntimeError("logger unavailable")

    monkeypatch.setattr(auth_store._LIFECYCLE_LOGGER, "log", fail)
    auth_store.lifecycle_event("family_revoked", family_id="private")


def test_lifecycle_bulk_mutation_has_bounded_records(tmp_path, caplog):
    store = AtomicJsonAuthStore(tmp_path / "sessions.json")
    caplog.set_level("INFO", logger="mcpserver.auth.lifecycle")
    store.mutate(lambda doc: doc["clients"].update({f"client-{i}": {} for i in range(70)}))
    assert len(caplog.records) == 33
    assert "event=batch_summary" in caplog.records[-1].message
    assert "count=38" in caplog.records[-1].message


def test_admin_lifecycle_stderr_is_bounded_and_restores_logger(capsys):
    from mcpserver.auth.store import _LIFECYCLE_LOGGER, admin_lifecycle_logging, lifecycle_event

    before = (
        _LIFECYCLE_LOGGER.level,
        _LIFECYCLE_LOGGER.propagate,
        list(_LIFECYCLE_LOGGER.handlers),
    )
    with admin_lifecycle_logging():
        for index in range(30):
            lifecycle_event(
                "family_revoked",
                family_id=f"private-family-{index}",
                reason="admin_session",
                source="admin",
                outcome="committed",
            )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 7
    assert len(captured.err.encode()) < 4096
    assert "event=batch_summary" in captured.err and "count=24" in captured.err
    assert "private-family" not in captured.err
    assert (
        _LIFECYCLE_LOGGER.level,
        _LIFECYCLE_LOGGER.propagate,
        list(_LIFECYCLE_LOGGER.handlers),
    ) == before
    with admin_lifecycle_logging():
        pass
    assert capsys.readouterr().err == ""
