"""Atomic effect/receipt rollback and source-preserving address corrections."""

import json

import pytest

from mcpserver.knx import address_apply as module
from mcpserver.knx.model import KnxError
from mcpserver.knx.store import KnxStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "current_time", lambda: 100)
    value = KnxStore(tmp_path / "metadata.sqlite3")
    for number in (1, 2):
        value.put(
            "synthetic",
            number - 1,
            {
                "address": f"0/0/{number}",
                "address_format": "three_level",
                "fields": {"name": f"Synthetic {number}", "description": "Keep this"},
            },
        )
    return value


def changes():
    return [
        {
            "address_id": 1,
            "destination": "local_metadata",
            "kind": "address",
            "decision": "accepted",
            "field": "name",
            "operation": "set",
            "value": "Revised",
        }
    ]


def apply(store, selected=None, digest="b" * 64):
    return module.apply_addresses(
        store,
        "a" * 64,
        "synthetic",
        "c" * 32,
        digest,
        2,
        changes() if selected is None else selected,
        now=100,
        expires_at=200,
        authorize_effect=lambda: None,
    )


def snapshot(store):
    with store.connection() as db:
        return {
            "revision": store.revision(db, "synthetic"),
            "addresses": db.execute("SELECT * FROM addresses ORDER BY address").fetchall(),
            "receipts": db.execute("SELECT * FROM local_apply_receipts").fetchall(),
        }


def test_unselected_field_and_identity_survive_and_receipt_reconciles(store):
    before = snapshot(store)
    result = apply(store)
    after = snapshot(store)
    assert after["revision"] == result["catalog_revision"] == 3
    assert after["addresses"][0][:4] == before["addresses"][0][:4]
    assert after["addresses"][1] == before["addresses"][1]
    assert json.loads(after["addresses"][0][5]) == {
        "name": "Revised",
        "description": "Keep this",
    }
    assert len(after["receipts"]) == 1
    assert apply(store) == result  # Exact receipt despite now-stale input revision.
    assert snapshot(store) == after
    with pytest.raises(KnxError, match="knx_correction_request_conflict"):
        apply(store, digest="d" * 64)


def test_receipt_write_failure_rolls_back_effect_and_revision(store):
    with store.connection() as db:
        db.execute(
            "CREATE TRIGGER reject_receipt BEFORE INSERT ON local_apply_receipts "
            "BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
        )
        db.commit()
    before = snapshot(store)
    with pytest.raises(KnxError, match="knx_storage_failed"):
        apply(store)
    assert snapshot(store) == before


def test_invalid_final_manual_name_rolls_back_entire_batch(store):
    selected = [
        *changes(),
        {
            "address_id": 2,
            "destination": "local_metadata",
            "kind": "address",
            "decision": "accepted",
            "field": "name",
            "operation": "remove_override",
        },
    ]
    before = snapshot(store)
    with pytest.raises(KnxError):
        apply(store, selected)
    assert snapshot(store) == before


def test_unknown_address_never_creates_record_or_receipt(store):
    selected = changes()
    selected[0]["address_id"] = 3
    before = snapshot(store)
    with pytest.raises(KnxError, match="knx_correction_address_unavailable"):
        apply(store, selected)
    assert snapshot(store) == before


def test_expired_at_effect_boundary_is_rejected_without_changes(store, monkeypatch):
    before = snapshot(store)
    monkeypatch.setattr(module, "current_time", lambda: 201)
    with pytest.raises(KnxError, match="knx_draft_unavailable"):
        apply(store)
    assert snapshot(store) == before


def test_expiry_during_live_authorization_rolls_back_effect_and_receipt(store, monkeypatch):
    def authorize_after_wait():
        monkeypatch.setattr(module, "current_time", lambda: 201)

    before = snapshot(store)
    with pytest.raises(KnxError, match="knx_draft_unavailable"):
        module.apply_addresses(
            store,
            "a" * 64,
            "synthetic",
            "c" * 32,
            "b" * 64,
            2,
            changes(),
            now=100,
            expires_at=200,
            authorize_effect=authorize_after_wait,
        )
    assert snapshot(store) == before


def test_live_authorization_failure_before_effect_rolls_back(store):
    def denied():
        raise KnxError("permission_denied")

    before = snapshot(store)
    with pytest.raises(KnxError, match="permission_denied"):
        module.apply_addresses(
            store,
            "a" * 64,
            "synthetic",
            "c" * 32,
            "b" * 64,
            2,
            changes(),
            now=100,
            expires_at=200,
            authorize_effect=denied,
        )
    assert snapshot(store) == before


@pytest.mark.parametrize("damaged", ["{}", "true", '{"unexpected":"value"}', "x" * 4097])
def test_damaged_receipt_is_not_reported_as_applied(store, damaged):
    apply(store)
    with store.connection() as db:
        db.execute("UPDATE local_apply_receipts SET result=?", (damaged,))
        db.commit()
    before = snapshot(store)
    with pytest.raises(KnxError, match="knx_storage_failed"):
        apply(store)
    assert snapshot(store) == before


def test_empty_import_fields_use_provenance_and_preserve_sources(store):
    with store.connection() as db:
        db.execute(
            "INSERT INTO ets_sources VALUES(?,?,?)",
            ("synthetic", 1, '{"file_format":"xml","synthetic":true}'),
        )
        db.commit()
    selected = changes()
    selected[0].pop("value")
    selected[0]["operation"] = "remove_override"
    with store.connection() as db:
        provenance = db.execute("SELECT * FROM ets_sources").fetchall()
    apply(store, selected)
    with store.connection() as db:
        assert db.execute("SELECT * FROM ets_sources").fetchall() == provenance
        imported, overrides = db.execute(
            "SELECT imported,overrides FROM addresses WHERE address=1"
        ).fetchone()
        assert json.loads(imported) == {}
        assert json.loads(overrides) == {"description": "Keep this"}
