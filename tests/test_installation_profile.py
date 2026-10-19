from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from mcpserver.installation_profile import (
    BindingInput,
    ProfileError,
    ProfileStore,
    installation_identity,
    project_profile,
)
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure, StatisticSeries
from mcpserver.persistence import PersistenceUncertain

CONTROL = "00000001-0000-0000-0000000000000001"
STATE = "00000002-0000-0000-0000000000000002"
TARGET = hashlib.sha256(b"synthetic-installation").hexdigest()
ACTOR = hashlib.sha256(b"synthetic-actor").hexdigest()


def control() -> Control:
    return Control(
        CONTROL,
        "Synthetic room",
        "InfoOnlyAnalog",
        None,
        None,
        None,
        (("value", STATE),),
        format="%.1f",
    )


def binding(**changes) -> BindingInput:
    return BindingInput.model_validate(
        {
            "binding_id": "temperature",
            "role": "actual_temperature",
            "control_uuid": CONTROL,
            "source_kind": "state",
            "state_uuid": STATE,
            **changes,
        }
    )


def store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(tmp_path / "installation-profile.json")


def save(storage: ProfileStore, revision=0, **changes):
    return storage.put(
        TARGET, revision, binding(**changes), control(), origin="local_admin", actor_ref=ACTOR
    )


def test_draft_confirmation_restart_and_tombstone_revision(tmp_path: Path) -> None:
    storage = store(tmp_path)
    first = save(storage)
    assert first.revision == 1 and first.bindings[0].confirmation_origin is None
    second = save(storage, 1, confirmed=True)
    loaded = store(tmp_path).read(TARGET)
    assert loaded == second and loaded.bindings[0].confirmation_origin == "local_admin"
    deleted = storage.delete(TARGET, 2, None)
    assert deleted.bindings == [] and deleted.revision == 3
    with pytest.raises(ProfileError, match="revision_conflict"):
        save(storage, 0)


def test_profile_rule_references_migrate_without_inventing_semantics(
    tmp_path: Path, monkeypatch
) -> None:
    c = replace(control(), control_type="IRoomControllerV2", state_uuids=(("tempActual", STATE),))
    storage = store(tmp_path)
    document = storage.put(
        TARGET, 0, binding(confirmed=True), c, origin="local_admin", actor_ref=ACTOR
    )
    assert (
        document.bindings[0].semantic_reference
        == "IRoomControllerV2.tempActual.v1+StateSemanticsResolver.rules.v1"
    )
    assert project_profile(document, TARGET, {CONTROL: c})["bindings"][0]["status"] == "confirmed"
    legacy = document.model_copy(
        update={"bindings": [document.bindings[0].model_copy(update={"semantic_reference": None})]}
    )
    assert project_profile(legacy, TARGET, {CONTROL: c})["bindings"][0]["status"] == "needs_review"
    monkeypatch.setattr(
        "mcpserver.installation_profile.semantic_reference", lambda *args: "new-rule.v2"
    )
    assert (
        project_profile(document, TARGET, {CONTROL: c})["bindings"][0]["status"] == "needs_review"
    )


def test_pre_pr5_legacy_statistic_document_does_not_get_unrelated_review(tmp_path: Path) -> None:
    s = StatisticSeries("legacy:0", "legacy", "0", "0", "Synthetic", "%.1f", state_uuid=STATE)
    c = replace(control(), statistic_series=(s,))
    storage = store(tmp_path)
    document = storage.put(
        TARGET,
        0,
        binding(source_kind="statistic", state_uuid=None, series_id="legacy:0", confirmed=True),
        c,
        origin="local_admin",
        actor_ref=ACTOR,
    ).model_dump()
    # Independently computed from integrated pre-PR5 a19f5ed source_fingerprint.
    document["bindings"][0]["source_fingerprint"] = (
        "df02a051b70428a007c0a3bf2791229ce3cdda161e7ee3daae252adab22613ac"
    )
    del document["bindings"][0]["semantic_reference"]
    storage.path.write_text(json.dumps(document), encoding="utf-8")
    loaded = storage.read(TARGET)
    projected = project_profile(loaded, TARGET, {CONTROL: c})["bindings"][0]
    assert projected["status"] == "confirmed" and projected["semantic_reference"] is None


def test_presentation_names_do_not_invalidate_but_technical_changes_do(tmp_path: Path) -> None:
    document = save(store(tmp_path), confirmed=True)
    renamed = replace(control(), name="Renamed")
    assert (
        project_profile(document, TARGET, {CONTROL: renamed})["bindings"][0]["status"]
        == "confirmed"
    )
    changed = replace(control(), control_type="Slider")
    assert (
        project_profile(document, TARGET, {CONTROL: changed})["bindings"][0]["status"]
        == "needs_review"
    )


def test_hidden_sources_and_removed_source_identifiers_are_not_exposed(tmp_path: Path) -> None:
    document = save(store(tmp_path), confirmed=True, rationale="private source context")
    hidden = project_profile(document, TARGET, {})
    assert hidden["bindings"] == []
    assert CONTROL not in json.dumps(hidden) and "private" not in json.dumps(hidden)
    removed = project_profile(document, TARGET, {CONTROL: replace(control(), state_uuids=())})
    assert removed["bindings"][0]["status"] == "invalid"
    assert STATE not in json.dumps(removed) and "private" not in json.dumps(removed)
    assert "actor_ref" not in json.dumps(removed)


@pytest.mark.parametrize(
    "changes",
    [
        {"semantics_invalid_fields": ("format",)},
        {"format_total_length": 100},
        {"status_monitor_status_complete": True},
        {"status_monitor_input_total": 2},
        {"statistic_series_truncated": True},
    ],
)
def test_semantic_metadata_changes_require_review(tmp_path, changes):
    document = save(store(tmp_path), confirmed=True)
    changed = replace(control(), **changes)
    assert (
        project_profile(document, TARGET, {CONTROL: changed})["bindings"][0]["status"]
        == "needs_review"
    )


def test_installation_replacement_requires_explicit_whole_profile_deletion(tmp_path: Path) -> None:
    storage = store(tmp_path)
    document = save(storage, confirmed=True)
    changed = hashlib.sha256(b"other-installation").hexdigest()
    assert project_profile(document, changed, {CONTROL: control()})["bindings"] == []
    with pytest.raises(ProfileError, match="installation_changed"):
        storage.put(changed, 1, binding(), control(), origin="local_admin", actor_ref=ACTOR)
    deleted = storage.delete(changed, 1, None)
    assert deleted.installation == changed and not deleted.bindings and deleted.revision == 2


def test_target_identity_includes_serial_and_origin_but_not_user() -> None:
    structure = LoxoneStructure(LoxoneIdentity("user-a", "synthetic-serial"), "v1", (), (), ())
    first = installation_identity("http://synthetic.local", structure)
    assert first == installation_identity(
        "http://synthetic.local",
        replace(structure, identity=LoxoneIdentity("user-b", "synthetic-serial")),
    )
    assert first != installation_identity("http://other.local", structure)
    assert first != installation_identity(
        "http://synthetic.local",
        replace(structure, identity=LoxoneIdentity("user-a", "other-serial")),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"control_uuid": "../path"},
        {"source_kind": "state", "series_id": "s"},
        {"state_uuid": None},
        {"confirmed": "true"},
        {"rationale": "a\nb"},
        {"role": "arbitrary"},
        {"credentials": "forbidden"},
    ],
)
def test_binding_contract_rejects_invalid_or_extra_fields(changes) -> None:
    with pytest.raises((ValidationError, ValueError)):
        binding(**changes)


def test_unknown_schema_and_invalid_persistence_do_not_overwrite(tmp_path: Path) -> None:
    storage = store(tmp_path)
    save(storage)
    document = json.loads(storage.path.read_text())
    document["schema_version"] = 99
    storage.path.write_text(json.dumps(document))
    before = storage.path.read_bytes()
    with pytest.raises(ProfileError, match="storage_invalid"):
        save(storage, 1)
    assert storage.path.read_bytes() == before


def test_failed_atomic_replace_preserves_last_profile(tmp_path: Path, monkeypatch) -> None:
    storage = store(tmp_path)
    save(storage)
    before = storage.path.read_bytes()
    monkeypatch.setattr(
        "mcpserver.installation_profile.os.replace", lambda *_: (_ for _ in ()).throw(OSError())
    )
    with pytest.raises(OSError):
        save(storage, 1, confirmed=True)
    assert storage.path.read_bytes() == before
    assert not list(tmp_path.glob(".profile-*.tmp"))


def test_post_commit_durability_failure_is_explicit(tmp_path: Path, monkeypatch) -> None:
    storage = store(tmp_path)
    monkeypatch.setattr(
        "mcpserver.installation_profile.fsync_parent_directory",
        lambda *_: (_ for _ in ()).throw(OSError()),
    )
    with pytest.raises(PersistenceUncertain):
        save(storage, confirmed=True)
    assert storage.read(TARGET).revision == 1


def test_contended_profile_lock_fails_with_bounded_availability(tmp_path, monkeypatch):
    storage = store(tmp_path)
    monkeypatch.setattr("mcpserver.installation_profile.LOCK_WAIT_SECONDS", 0)
    with storage._locked(), pytest.raises(ProfileError, match="profile_storage_busy"):
        storage.read(TARGET)
