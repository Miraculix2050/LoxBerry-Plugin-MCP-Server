"""Persistence, absolute lifetime, owner isolation and shared draft resource bounds."""

import pytest

from mcpserver.knx.correction_drafts import CORRECTION_TTL_SECONDS, CorrectionDraftStore
from mcpserver.knx.drafts import DraftStore
from mcpserver.knx.model import KnxError


def proposal(value="Additional name"):
    return [{"destination": "local", "address_id": 1, "field": "name", "value": value}]


def test_uncertain_creation_resolves_only_live_owner_target_request(tmp_path, monkeypatch):
    clock = [1000]
    monkeypatch.setattr("mcpserver.knx.drafts.time.time", lambda: clock[0])
    store = CorrectionDraftStore(tmp_path / "drafts.sqlite3", "a" * 64)
    request_id = "d" * 32
    created = store.create_correction("target", 7, "b" * 64, proposal(), request_id=request_id)
    assert store.resolve_request(request_id, "target") == created["draft_id"]
    for reader, target, request in (
        (CorrectionDraftStore(store.path, "c" * 64), "target", request_id),
        (store, "other-target", request_id),
        (store, "target", "e" * 32),
    ):
        with pytest.raises(KnxError, match="knx_draft_unavailable"):
            reader.resolve_request(request, target)
    clock[0] = created["expires_at"]
    with pytest.raises(KnxError, match="knx_draft_unavailable"):
        store.resolve_request(request_id, "target")


def test_correction_survives_reopen_and_edit_without_renewing_lifetime(tmp_path, monkeypatch):
    clock = [1000]
    monkeypatch.setattr("mcpserver.knx.drafts.time.time", lambda: clock[0])
    store = CorrectionDraftStore(tmp_path / "drafts.sqlite3", "a" * 64)
    created = store.create_correction("target", 7, "b" * 64, proposal())
    identifier = created["draft_id"]
    assert created["expires_at"] == 1000 + CORRECTION_TTL_SECONDS
    clock[0] += 60
    reopened = CorrectionDraftStore(store.path, "a" * 64)
    reopened.update_correction(identifier, "target", 1, proposal("Owner decision"))
    updated = reopened.inspect_correction(identifier, "target")
    assert updated["draft_revision"] == 2
    assert updated["catalog_revision"] == 7
    assert updated["manual_revision"] == "b" * 64
    assert updated["expires_at"] == created["expires_at"]
    clock[0] = created["expires_at"]
    with pytest.raises(KnxError, match="knx_draft_unavailable"):
        reopened.inspect_correction(identifier, "target")


def test_owner_target_and_optimistic_revision_are_independent_boundaries(tmp_path):
    store = CorrectionDraftStore(tmp_path / "drafts.sqlite3", "a" * 64)
    created = store.create_correction("target", 7, "b" * 64, proposal())
    identifier = created["draft_id"]
    other = CorrectionDraftStore(store.path, "c" * 64)
    for reader, target in ((other, "target"), (store, "other-target")):
        with pytest.raises(KnxError, match="knx_draft_unavailable"):
            reader.inspect_correction(identifier, target)
        with pytest.raises(KnxError, match="knx_draft_unavailable"):
            reader.update_correction(identifier, target, 1, proposal())
    store.update_correction(identifier, "target", 1, proposal("First editor"))
    for operation in (
        lambda: store.update_correction(identifier, "target", 1, proposal("Stale editor")),
        lambda: store.discard_correction(identifier, "target", 1),
    ):
        with pytest.raises(KnxError, match="knx_revision_conflict"):
            operation()
    assert store.inspect_correction(identifier, "target")["changes"] == proposal("First editor")
    store.discard_correction(identifier, "target", 2)
    with pytest.raises(KnxError, match="knx_draft_unavailable"):
        store.inspect_correction(identifier, "target")


def test_import_and_correction_drafts_share_one_global_count_limit(tmp_path):
    path = tmp_path / "drafts.sqlite3"
    for index in range(7):
        DraftStore(path, f"{index:064x}").create("target", 0, b"import", {})
    corrections = CorrectionDraftStore(path, "a" * 64)
    created = corrections.create_correction("target", 0, "b" * 64, proposal())
    with pytest.raises(KnxError, match="knx_draft_limit"):
        corrections.create_correction("target", 0, "b" * 64, proposal())
    with pytest.raises(KnxError, match="knx_draft_limit"):
        DraftStore(path, "d" * 64).create("target", 0, b"import", {})
    assert corrections.inspect_correction(created["draft_id"], "target")["draft_revision"] == 1


def test_correction_and_legacy_drafts_keep_separate_expiry(tmp_path, monkeypatch):
    clock = [1000]
    monkeypatch.setattr("mcpserver.knx.drafts.time.time", lambda: clock[0])
    path = tmp_path / "drafts.sqlite3"
    imports = DraftStore(path, "a" * 64)
    imported = imports.create("target", 0, b"import", {})
    corrections = CorrectionDraftStore(path, "a" * 64)
    created = corrections.create_correction("target", 0, "b" * 64, proposal())
    clock[0] += 600
    with pytest.raises(KnxError, match="knx_draft_expired"):
        imports.load(imported, "target", 0)
    assert corrections.inspect_correction(created["draft_id"], "target")["draft_revision"] == 1


def test_correction_limit_failure_preserves_previous_proposal(tmp_path):
    store = CorrectionDraftStore(tmp_path / "drafts.sqlite3", "a" * 64)
    created = store.create_correction("target", 0, "b" * 64, proposal())
    with pytest.raises(KnxError, match="knx_draft_limit"):
        store.update_correction(created["draft_id"], "target", 1, proposal() * 51)
    assert store.inspect_correction(created["draft_id"], "target")["changes"] == proposal()


def test_compact_listing_does_not_decode_changes_or_leak_another_owner(tmp_path, monkeypatch):
    store = CorrectionDraftStore(tmp_path / "drafts.sqlite3", "a" * 64)
    created = store.create_correction(
        "target", 7, "b" * 64, proposal("Private proposal"), project_binding="private binding"
    )
    other = CorrectionDraftStore(store.path, "c" * 64)
    other.create_correction("target", 7, "b" * 64, proposal("Other private proposal"))

    def forbidden(*args, **kwargs):
        raise AssertionError("Summary must not decode proposal contents")

    monkeypatch.setattr("mcpserver.knx.correction_drafts.json.loads", forbidden)
    summary = store.list_corrections("target")
    assert len(summary) == 1 and summary[0]["draft_id"] == created["draft_id"]
    assert summary[0]["change_count"] == 1
    assert len(summary[0]["project_binding_digest"]) == 64
    assert "Private proposal" not in str(summary) and "private binding" not in str(summary)
    assert store.list_corrections("other-target") == []


def test_combined_byte_budget_and_failed_update_preserve_both_kinds(tmp_path, monkeypatch):
    monkeypatch.setattr("mcpserver.knx.drafts.MAX_DRAFT_BYTES", 2048)
    monkeypatch.setattr("mcpserver.knx.correction_drafts.MAX_DRAFT_BYTES", 2048)
    path = tmp_path / "drafts.sqlite3"
    imports = DraftStore(path, "a" * 64)
    imported = imports.create("target", 7, b"x" * 1000, {})
    corrections = CorrectionDraftStore(path, "c" * 64)
    created = corrections.create_correction("target", 7, "b" * 64, proposal())
    with pytest.raises(KnxError, match="knx_draft_limit"):
        corrections.update_correction(created["draft_id"], "target", 1, proposal("x" * 2000))
    with pytest.raises(KnxError, match="knx_draft_limit"):
        DraftStore(path, "d" * 64).create("target", 7, b"x" * 1000, {})
    assert imports.load(imported, "target", 7)[0] == b"x" * 1000
    assert corrections.inspect_correction(created["draft_id"], "target")["changes"] == proposal()


def test_preparation_request_is_idempotent_and_does_not_renew_expiry(tmp_path, monkeypatch):
    clock = [1000]
    monkeypatch.setattr("mcpserver.knx.drafts.time.time", lambda: clock[0])
    store = CorrectionDraftStore(tmp_path / "drafts.sqlite3", "a" * 64)
    arguments = ("target", 7, "b" * 64, proposal())
    created = store.create_correction(*arguments, request_id="c" * 32)
    clock[0] += 60
    replayed = store.create_correction(*arguments, request_id="c" * 32)
    assert replayed == created
    assert len(store.list_corrections("target")) == 1
    with pytest.raises(KnxError, match="knx_correction_request_conflict"):
        store.create_correction("target", 7, "b" * 64, proposal("Changed"), request_id="c" * 32)
    other = CorrectionDraftStore(store.path, "d" * 64)
    assert (
        other.create_correction(*arguments, request_id="c" * 32)["draft_id"] != created["draft_id"]
    )


def test_update_request_reconciles_old_result_after_a_later_edit(tmp_path):
    store = CorrectionDraftStore(tmp_path / "drafts.sqlite3", "a" * 64)
    created = store.create_correction("target", 7, "b" * 64, proposal())
    identifier = created["draft_id"]
    assert (
        store.update_correction(identifier, "target", 1, proposal("First"), request_id="c" * 32)
        == 2
    )
    assert (
        store.update_correction(identifier, "target", 2, proposal("Later"), request_id="d" * 32)
        == 3
    )
    assert (
        store.update_correction(identifier, "target", 1, proposal("First"), request_id="c" * 32)
        == 2
    )
    with pytest.raises(KnxError, match="knx_correction_request_conflict"):
        store.update_correction(identifier, "target", 1, proposal("Other"), request_id="c" * 32)
    current = store.inspect_correction(identifier, "target")
    assert current["draft_revision"] == 3 and current["changes"] == proposal("Later")
    assert "operations" not in current


def test_request_history_is_bounded_without_eviction(tmp_path):
    store = CorrectionDraftStore(tmp_path / "drafts.sqlite3", "a" * 64)
    identifier = store.create_correction("target", 7, "b" * 64, proposal())["draft_id"]
    for number in range(32):
        store.update_correction(
            identifier, "target", number + 1, proposal(), request_id=f"{number:032x}"
        )
    with pytest.raises(KnxError, match="knx_draft_limit"):
        store.update_correction(identifier, "target", 33, proposal(), request_id="f" * 32)
    assert store.inspect_correction(identifier, "target")["draft_revision"] == 33


@pytest.mark.parametrize(
    "damage", ["missing_table", "missing_row", "wrong_revision", "bad_options"]
)
def test_corrupt_index_or_payload_is_not_a_successful_read(tmp_path, damage):
    store = CorrectionDraftStore(tmp_path / "drafts.sqlite3", "a" * 64)
    identifier = store.create_correction("target", 7, "b" * 64, proposal())["draft_id"]
    with store.connection() as db:
        if damage == "missing_table":
            db.execute("DROP TABLE correction_index")
        elif damage == "missing_row":
            db.execute("DELETE FROM correction_index")
        elif damage == "wrong_revision":
            db.execute("UPDATE correction_index SET draft_revision=99")
        else:
            db.execute("UPDATE drafts SET options=json_set(options,'$.changes',null)")
    with pytest.raises(KnxError, match="knx_draft_storage_failed"):
        store.inspect_correction(identifier, "target")


def test_expiry_cleans_compact_index_for_legacy_store_calls(tmp_path, monkeypatch):
    clock = [1000]
    monkeypatch.setattr("mcpserver.knx.drafts.time.time", lambda: clock[0])
    store = CorrectionDraftStore(tmp_path / "drafts.sqlite3", "a" * 64)
    created = store.create_correction("target", 7, "b" * 64, proposal())
    clock[0] = created["expires_at"]
    # Ordinary imports expire both kinds through the same persistent database.
    with DraftStore(store.path, "d" * 64).connection() as db:
        assert db.execute("SELECT count(*) FROM correction_index").fetchone()[0] == 0
    assert store.list_corrections("target") == []
