from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from mcpserver.installation_profile import (
    BINDING_INPUT,
    BindingInput,
    ProfileError,
    ProfileSources,
    ProfileStore,
    PVParameters,
    WeatherBindingInput,
    project_profile,
)
from mcpserver.loxone.models import (
    Control,
    GlobalMetadata,
    LoxoneIdentity,
    LoxoneStructure,
    WeatherMetadata,
)

CONTROL = "00000001-0000-0000-0000000000000001"
STATE = "00000002-0000-0000-0000000000000002"
WEATHER = "00000003-0000-0000-0000000000000003"
TARGET = hashlib.sha256(b"synthetic-profile").hexdigest()
ACTOR = hashlib.sha256(b"synthetic-actor").hexdigest()


def structure():
    return LoxoneStructure(
        LoxoneIdentity("synthetic", "synthetic-serial"),
        "v1",
        (),
        (),
        (Control(CONTROL, "Synthetic", "InfoOnlyAnalog", None, None, None, (("value", STATE),)),),
        global_metadata=(GlobalMetadata("weather_state", "actual", "Actual", state_uuid=WEATHER),),
        weather=WeatherMetadata(formats=(("temperature", "%.1f °C"), ("windSpeed", "%.1f"))),
    )


def weather(**changes):
    return WeatherBindingInput.model_validate(
        {
            "binding_id": "weather",
            "role": "weather_context",
            "source_kind": "weather",
            "weather_state_uuid": WEATHER,
            "mode": "actual",
            "field": "temperature",
            "confirmed": True,
            "rationale": "Private declaration",
            **changes,
        }
    )


def production(**changes):
    return BindingInput.model_validate(
        {
            "binding_id": "production",
            "role": "production",
            "source_kind": "state",
            "control_uuid": CONTROL,
            "state_uuid": STATE,
            "confirmed": True,
            **changes,
        }
    )


def put(store, revision, binding, source=None):
    return store.put(
        TARGET,
        revision,
        binding,
        source or ProfileSources.from_structure(TARGET, structure()),
        origin="local_admin",
        actor_ref=ACTOR,
    )


def test_v1_migration_is_idempotent_and_read_does_not_persist(tmp_path):
    store = ProfileStore(tmp_path / "profile.json")
    document = put(store, 0, production()).model_dump()
    document["schema_version"] = 1
    del document["bindings"][0]["pv_parameters"]
    store.path.write_text(json.dumps(document))
    original = store.path.read_bytes()
    first = store.read(TARGET)
    assert first == store.read(TARGET) and first.schema_version == 2
    assert store.path.read_bytes() == original
    assert first.bindings[0].source_fingerprint == document["bindings"][0]["source_fingerprint"]
    second = put(store, 1, weather())
    assert second.revision == 2 and len(second.bindings) == 2
    assert json.loads(store.path.read_text())["schema_version"] == 2
    assert second.bindings[0] == first.bindings[0]


def test_v1_is_validated_with_original_shape_before_migration(tmp_path):
    store = ProfileStore(tmp_path / "profile.json")
    document = put(store, 0, production(pv_parameters={"installed_kwp": 5.0})).model_dump()
    document["schema_version"] = 1
    store.path.write_text(json.dumps(document))
    with pytest.raises(ProfileError, match="storage_invalid"):
        store.read(TARGET)


def test_mixed_weather_source_projection_and_revocation(tmp_path):
    store = ProfileStore(tmp_path / "profile.json")
    put(store, 0, production())
    document = put(store, 1, weather())
    sources = ProfileSources.from_structure(TARGET, structure())
    result = project_profile(document, TARGET, sources, limit=1)
    assert result["next_offset"] == 1
    item = project_profile(document, TARGET, sources, offset=1)["bindings"][0]
    assert item["status"] == "confirmed" and item["unit"] is None
    assert (
        item["history_status"] == "not_checked" and item["value_origin"] == "current_source_value"
    )
    assert "control_uuid" not in item and "actor_ref" not in item
    revoked = ProfileSources.from_structure(TARGET, replace(structure(), global_metadata=()))
    hidden = project_profile(document, TARGET, revoked)
    assert WEATHER not in json.dumps(hidden) and "Private declaration" not in json.dumps(hidden)
    assert not revoked.authorized(document.bindings[1])
    wrong_mode = ProfileSources.from_structure(
        TARGET,
        replace(
            structure(),
            global_metadata=(
                GlobalMetadata("weather_state", "forecast", "Forecast", state_uuid=WEATHER),
            ),
        ),
    )
    assert not wrong_mode.authorized(weather())


def test_weather_fingerprint_uses_only_relevant_format_and_versioned_rule(tmp_path, monkeypatch):
    store = ProfileStore(tmp_path / "profile.json")
    document = put(store, 0, weather())

    def project(formats):
        changed = replace(structure(), weather=WeatherMetadata(formats=tuple(formats.items())))
        return project_profile(document, TARGET, ProfileSources.from_structure(TARGET, changed))[
            "bindings"
        ][0]

    assert project({"temperature": "%.1f °C", "windSpeed": "changed"})["status"] == "confirmed"
    assert project({"temperature": "%.1f °F"})["status"] == "needs_review"
    monkeypatch.setattr("mcpserver.installation_profile.WEATHER_RULE", "raw_fields.v2")
    assert project({"temperature": "%.1f °C"})["status"] == "needs_review"


def test_pv_parameters_are_declarations_with_fresh_confirmation_and_source_anchor(tmp_path):
    store = ProfileStore(tmp_path / "profile.json")
    before = put(store, 0, production())
    draft = put(store, 1, production(confirmed=False, pv_parameters={"installed_kwp": 5.0}))
    sources = ProfileSources.from_structure(TARGET, structure())
    item = project_profile(draft, TARGET, sources)["bindings"][0]
    assert item["status"] == "draft" and not item["pv_parameters_usable"]
    assert draft.bindings[0].source_fingerprint == before.bindings[0].source_fingerprint
    assert draft.bindings[0].confirmation_origin is None
    confirmed = put(store, 2, production(pv_parameters={"arrays": [{"array_id": "south"}]}))
    item = project_profile(confirmed, TARGET, sources)["bindings"][0]
    assert item["pv_parameters_usable"]
    assert item["pv_parameters"]["installed_kwp"] is None
    invalid_control = replace(structure().controls[0], state_uuids=())
    hidden = project_profile(confirmed, TARGET, {CONTROL: invalid_control})
    assert hidden["bindings"][0]["status"] == "invalid" and "south" not in json.dumps(hidden)
    assert not project_profile(confirmed, TARGET, {})["bindings"]


@pytest.mark.parametrize(
    "value",
    [
        {"installed_kwp": 0.0},
        {"installed_kwp": float("nan")},
        {"installed_kwp": True},
        {"latitude": 1.0},
        {"latitude": 91.0, "longitude": 0.0},
        {"arrays": [{"array_id": "a", "azimuth_degrees": 360.0}]},
        {"arrays": [{"array_id": "a", "tilt_degrees": 91.0}]},
        {"arrays": [{"array_id": "a", "shading": "a\nb"}]},
        {"arrays": [{"array_id": "a"}, {"array_id": "a"}]},
        {"arrays": [{"array_id": "../path"}]},
        {"arrays": [{"array_id": str(i)} for i in range(17)]},
    ],
)
def test_invalid_pv_parameters_are_rejected(value):
    with pytest.raises(ValidationError):
        PVParameters.model_validate(value)


@pytest.mark.parametrize(
    "changes",
    [
        {"control_uuid": CONTROL},
        {"weather_state_uuid": "../path"},
        {"field": "arbitrary"},
        {"mode": "history"},
        {"role": "production"},
        {"confirmed": "true"},
    ],
)
def test_weather_input_is_separate_and_allowlisted(changes):
    with pytest.raises(ValidationError):
        weather(**changes)


def test_binding_union_legacy_requirements_and_global_id_uniqueness(tmp_path):
    with pytest.raises(ValidationError):
        BINDING_INPUT.validate_python(
            {"binding_id": "x", "role": "production", "source_kind": "state", "state_uuid": STATE}
        )
    with pytest.raises(ValidationError):
        production(role="consumer", pv_parameters={})
    store = ProfileStore(tmp_path / "profile.json")
    put(store, 0, production())
    document = put(store, 1, weather(binding_id="production"))
    assert len(document.bindings) == 1 and document.bindings[0].source_kind == "weather"
