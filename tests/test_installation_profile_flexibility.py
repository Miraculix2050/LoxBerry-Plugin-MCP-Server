from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError
from test_load_flexibility import flexibility

from mcpserver.installation_profile import (
    BindingInput,
    ProfileError,
    ProfileSources,
    ProfileStore,
    project_profile,
)
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure

TARGET = hashlib.sha256(b"fixture-installation").hexdigest()
ACTOR = hashlib.sha256(b"fixture-actor").hexdigest()
C0, C1, C2 = (f"0000000{i}-0000-0000-000000000000000{i}" for i in range(1, 4))
S0, S1, S2 = (f"0000000{i}-0000-0000-000000000000000{i}" for i in range(4, 7))


def context(*, visible=True, digital=True, alternate=False):
    consumer = Control(
        C0, "Fixture load", "InfoOnlyAnalog", None, None, None, (("value", S0),), format="%.1f W"
    )
    operating = Control(
        C2 if alternate else C1,
        "Fixture operating state",
        "InfoOnlyDigital" if digital else "InfoOnlyAnalog",
        None,
        None,
        None,
        (("active" if digital else "value", S2 if alternate else S1),),
    )
    structure = LoxoneStructure(
        LoxoneIdentity("fixture", "fixture"),
        "v1",
        (),
        (),
        (consumer, operating) if visible else (consumer,),
    )
    return ProfileSources.from_structure(TARGET, structure)


def operating(**changes):
    return BindingInput(
        binding_id="load-active",
        role="operating_state",
        control_uuid=C1,
        source_kind="state",
        state_uuid=S1,
        confirmed=True,
        **changes,
    )


def consumer(**changes):
    return BindingInput(
        binding_id="load",
        role="consumer",
        control_uuid=C0,
        source_kind="state",
        state_uuid=S0,
        confirmed=True,
        load_flexibility=flexibility(),
        **changes,
    )


def put(store, binding, sources=None):
    return store.put(
        TARGET,
        store.read(TARGET).revision,
        binding,
        sources or context(),
        origin="local_admin",
        actor_ref=ACTOR,
    )


def setup(tmp_path):
    store = ProfileStore(tmp_path / "profile.json")
    put(store, operating())
    document = put(store, consumer())
    return store, document


def test_confirmed_load_constraints_and_restart_preserve_trusted_link_identity(tmp_path):
    store, document = setup(tmp_path)
    assert document.schema_version == 3 and store.read(TARGET) == document
    load = next(b for b in document.bindings if b.binding_id == "load")
    assert load.load_operating_fingerprint
    row = next(
        b
        for b in project_profile(document, TARGET, context())["bindings"]
        if b["binding_id"] == "load"
    )
    assert row["load_constraints_usable"]
    assert row["load_flexibility"]["cycle_identity"] == "active_episode_only"
    assert row["native_lock_status"] == "not_checked"
    assert "load_operating_fingerprint" not in row and "actor_ref" not in row


def test_hidden_companion_never_leaks_through_visible_consumer(tmp_path):
    store, document = setup(tmp_path)
    projection = project_profile(document, TARGET, context(visible=False))
    row = projection["bindings"][0]
    assert row["load_flexibility"] is None and not row["load_constraints_usable"]
    encoded = json.dumps(projection)
    assert "load-active" not in encoded and S1 not in encoded and C1 not in encoded
    with pytest.raises(ProfileError, match="operating_source_not_confirmed"):
        put(store, consumer(), context(visible=False))
    assert store.read(TARGET) == document


def test_reused_operating_binding_id_does_not_retarget_a_confirmed_load(tmp_path):
    store, _ = setup(tmp_path)
    updated = put(
        store,
        operating().model_copy(update={"control_uuid": C2, "state_uuid": S2}),
        context(alternate=True),
    )
    row = next(
        b
        for b in project_profile(updated, TARGET, context(alternate=True))["bindings"]
        if b["binding_id"] == "load"
    )
    assert not row["load_constraints_usable"]
    reconfirmed = put(store, consumer(), context(alternate=True))
    row = next(
        b
        for b in project_profile(reconfirmed, TARGET, context(alternate=True))["bindings"]
        if b["binding_id"] == "load"
    )
    assert row["load_constraints_usable"]


def test_unconfirmed_and_nonbinary_operating_sources_cannot_qualify(tmp_path):
    store = ProfileStore(tmp_path / "profile.json")
    put(store, operating().model_copy(update={"confirmed": False}))
    with pytest.raises(ProfileError, match="operating_source_not_confirmed"):
        put(store, consumer())
    draft = put(store, consumer().model_copy(update={"confirmed": False}))
    assert not project_profile(draft, TARGET, context())["bindings"][-1]["load_constraints_usable"]
    with pytest.raises(ProfileError, match="operating_source_not_confirmed"):
        put(store, consumer(), context(digital=False))


def test_deleted_companion_disables_constraints_without_discarding_stored_values(tmp_path):
    store, _ = setup(tmp_path)
    updated = store.delete(TARGET, 2, "load-active")
    row = project_profile(updated, TARGET, context())["bindings"][0]
    assert not row["load_constraints_usable"] and row["load_flexibility"] is None
    assert updated.bindings[0].load_flexibility is not None


@pytest.mark.parametrize("changes", [{"role": "production"}, {"role": "operating_state"}])
def test_only_consumer_binding_can_declare_flexibility(changes):
    with pytest.raises(ValidationError):
        BindingInput.model_validate({**consumer().model_dump(), **changes})


def test_self_association_and_caller_supplied_link_fingerprint_are_rejected():
    for changes in ({"binding_id": "load-active"}, {"load_operating_fingerprint": "f" * 64}):
        with pytest.raises(ValidationError):
            BindingInput.model_validate({**consumer().model_dump(), **changes})


def test_version2_read_migration_preserves_bytes_revision_and_existing_fingerprint(tmp_path):
    store = ProfileStore(tmp_path / "profile.json")
    document = put(store, operating()).model_dump()
    document["schema_version"] = 2
    for binding in document["bindings"]:
        binding.pop("load_flexibility")
        binding.pop("load_operating_fingerprint")
        binding.pop("load_operating_control_uuid")
        binding.pop("load_operating_state_uuid")
    store.path.write_text(json.dumps(document), encoding="utf-8")
    original = store.path.read_bytes()
    migrated = store.read(TARGET)
    assert migrated.schema_version == 3 and migrated.revision == 1
    assert store.read(TARGET) == migrated and store.path.read_bytes() == original
    assert migrated.bindings[0].source_fingerprint == document["bindings"][0]["source_fingerprint"]
    put(store, consumer())
    assert json.loads(store.path.read_text(encoding="utf-8"))["schema_version"] == 3
