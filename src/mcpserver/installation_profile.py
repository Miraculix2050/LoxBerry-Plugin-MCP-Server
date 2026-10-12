"""Minimal confirmed installation metadata; no observations or decoder rules."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from mcpserver.config import _unlock_file
from mcpserver.loxone.models import Control, LoxoneStructure
from mcpserver.loxone.state_semantics import StateSemanticsResolver
from mcpserver.loxone.uuid import normalize_loxone_uuid
from mcpserver.persistence import PersistenceUncertain, fsync_parent_directory

MAX_BINDINGS = 256
MAX_DOCUMENT_BYTES = 1024 * 1024
LOCK_WAIT_SECONDS = 2.0
Role = Literal[
    "production",
    "grid_import",
    "grid_export",
    "house_consumption",
    "storage_charge",
    "storage_discharge",
    "consumer",
    "actual_temperature",
    "target_temperature",
    "room_sensor",
    "operating_state",
    "door_contact",
    "window_contact",
    "lighting_intent",
]


class ProfileError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class LegacyBindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    binding_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    role: Role
    control_uuid: str = Field(max_length=128)
    source_kind: Literal["state", "statistic"]
    state_uuid: str | None = Field(default=None, max_length=128)
    series_id: str | None = Field(default=None, min_length=1, max_length=128)
    measurement_boundary: str | None = Field(default=None, min_length=1, max_length=128)
    declared_direction: Literal["import", "export", "charge", "discharge"] | None = None
    rationale: str = Field(default="", max_length=256)
    confirmed: bool = False

    @field_validator("control_uuid", "state_uuid")
    @classmethod
    def identifier(cls, value: str | None) -> str | None:
        return normalize_loxone_uuid(value) if value is not None else None

    @field_validator("rationale", "measurement_boundary", "series_id")
    @classmethod
    def text(cls, value: str | None) -> str | None:
        if value is not None and any(ord(char) < 32 for char in value):
            raise ValueError("profile_text_invalid")
        return value

    @model_validator(mode="after")
    def source(self) -> LegacyBindingInput:
        if self.source_kind == "state":
            valid = self.state_uuid is not None and self.series_id is None
        else:
            valid = self.series_id is not None and self.state_uuid is None
        if not valid:
            raise ValueError("profile_source_invalid")
        return self


class PVArray(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    array_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    installed_kwp: float | None = Field(default=None, gt=0, le=1_000_000)
    azimuth_degrees: float | None = Field(default=None, ge=0, lt=360)
    tilt_degrees: float | None = Field(default=None, ge=0, le=90)
    shading: str | None = Field(default=None, max_length=256)

    @field_validator("shading")
    @classmethod
    def text(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value.encode("utf-8")) > 1024 or any(ord(char) < 32 for char in value)
        ):
            raise ValueError("profile_text_invalid")
        return value


class PVParameters(BaseModel):
    """User declarations, never inferred geometry or a technical source rule."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    installed_kwp: float | None = Field(default=None, gt=0, le=1_000_000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    arrays: list[PVArray] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def geometry(self) -> PVParameters:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("profile_coordinates_incomplete")
        if len({item.array_id for item in self.arrays}) != len(self.arrays):
            raise ValueError("profile_duplicate_array")
        return self


class BindingInput(LegacyBindingInput):
    pv_parameters: PVParameters | None = None

    @model_validator(mode="after")
    def production_parameters(self) -> BindingInput:
        if self.pv_parameters is not None and self.role != "production":
            raise ValueError("profile_pv_role_invalid")
        return self


WeatherField = Literal[
    "weather_type",
    "wind_direction",
    "solar_radiation",
    "relative_humidity",
    "temperature",
    "perceived_temperature",
    "dew_point",
    "precipitation",
    "wind_speed",
    "barometric_pressure",
]
WEATHER_FIELDS = TypeAdapter(WeatherField).json_schema()["enum"]
WEATHER_FORMAT_KEYS = {
    "relative_humidity": "relativeHumidity",
    "temperature": "temperature",
    "precipitation": "precipitation",
    "wind_speed": "windSpeed",
    "barometric_pressure": "barometricPressure",
}
WEATHER_RULE = "installation_weather.raw_fields.v1"


class WeatherBindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    binding_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    role: Literal["weather_context"]
    source_kind: Literal["weather"]
    weather_state_uuid: str = Field(max_length=128)
    mode: Literal["actual", "forecast"]
    field: WeatherField
    rationale: str = Field(default="", max_length=256)
    confirmed: bool = False

    @field_validator("weather_state_uuid")
    @classmethod
    def identifier(cls, value: str) -> str:
        return normalize_loxone_uuid(value)

    @field_validator("rationale")
    @classmethod
    def text(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError("profile_text_invalid")
        return value


class ConfirmationFields(BaseModel):
    source_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    semantic_reference: str | None = Field(default=None, max_length=256)
    confirmation_origin: Literal["local_admin", "mcp_user_confirmed"] | None = None
    actor_ref: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def confirmation(self) -> ConfirmationFields:
        confirmed = getattr(self, "confirmed", False)
        if confirmed != (self.confirmation_origin is not None and self.actor_ref is not None):
            raise ValueError("profile_confirmation_invalid")
        if not confirmed and (self.confirmation_origin is not None or self.actor_ref is not None):
            raise ValueError("profile_confirmation_invalid")
        return self


class LegacyStoredBinding(LegacyBindingInput, ConfirmationFields):
    pass


class StoredBinding(BindingInput, ConfirmationFields):
    pass


class StoredWeatherBinding(WeatherBindingInput, ConfirmationFields):
    pass


ProfileBindingInput = Annotated[
    BindingInput | WeatherBindingInput, Field(discriminator="source_kind")
]
StoredProfileBinding = Annotated[
    StoredBinding | StoredWeatherBinding, Field(discriminator="source_kind")
]
BINDING_INPUT: TypeAdapter[BindingInput | WeatherBindingInput] = TypeAdapter(ProfileBindingInput)


class LegacyProfileDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    installation: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: int = Field(ge=0, le=2**31 - 1)
    bindings: list[LegacyStoredBinding] = Field(default_factory=list, max_length=MAX_BINDINGS)

    @model_validator(mode="after")
    def unique_bindings(self) -> LegacyProfileDocument:
        if len({binding.binding_id for binding in self.bindings}) != len(self.bindings):
            raise ValueError("profile_duplicate_binding")
        return self


class ProfileDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[2] = 2
    installation: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: int = Field(ge=0, le=2**31 - 1)
    bindings: list[StoredProfileBinding] = Field(default_factory=list, max_length=MAX_BINDINGS)

    @model_validator(mode="after")
    def unique_bindings(self) -> ProfileDocument:
        if len({binding.binding_id for binding in self.bindings}) != len(self.bindings):
            raise ValueError("profile_duplicate_binding")
        return self


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def installation_identity(origin: str, structure: LoxoneStructure) -> str:
    serial = structure.identity.miniserver_serial
    if not serial:
        raise ProfileError("profile_installation_unavailable")
    return _digest(["installation-profile-v1", origin, serial])


def visible_controls(structure: LoxoneStructure) -> dict[str, Control]:
    pending = list(structure.controls)
    controls = {}
    while pending:
        control = pending.pop()
        controls[control.uuid] = control
        pending.extend(control.subcontrols)
    return controls


def source_fingerprint(binding: BindingInput, control: Control) -> str:
    """Ignore presentation names; include exact association and semantic inputs."""
    if binding.source_kind == "state":
        name = next(
            (name for name, uuid in control.state_uuids if uuid == binding.state_uuid), None
        )
        if name is None:
            raise ProfileError("profile_source_not_visible")
        source: object = [name, binding.state_uuid]
    else:
        series = next(
            (s for s in control.statistic_series if s.series_id == binding.series_id), None
        )
        if series is None:
            raise ProfileError("profile_source_not_visible")
        source = [
            series.series_id,
            series.source,
            series.group_id,
            series.output,
            series.accumulated,
            series.format,
            series.state_uuid,
        ]
        if series.source == "statistic_v2":
            source.extend([str(series.recording_mode), series.accumulated_metadata_valid])
    return _digest(
        [
            control.uuid,
            control.control_type,
            control.room_uuid,
            control.format,
            control.minimum,
            control.maximum,
            control.step,
            control.is_analog,
            control.semantics_invalid_fields,
            control.format_total_length,
            control.statistic_series_truncated,
            [[s.status_id, s.name, s.priority, s.uuid] for s in control.status_monitor_statuses],
            [[s.index, s.uuid, s.room_uuid] for s in control.status_monitor_inputs],
            control.status_monitor_status_total,
            control.status_monitor_status_complete,
            control.status_monitor_input_total,
            control.status_monitor_input_complete,
            [
                [s.index, s.room_uuid, s.control_uuid, s.diagnostics]
                for s in control.window_monitor_items
            ],
            asdict(control.window_monitor_summary) if control.window_monitor_summary else None,
            source,
        ]
    )


def semantic_reference(binding: BindingInput, control: Control) -> str | None:
    resolver = StateSemanticsResolver()
    if binding.source_kind == "statistic":
        series = next(
            (s for s in control.statistic_series if s.series_id == binding.series_id), None
        )
        return resolver.source_reference(control, series=series) if series else None
    name = next((name for name, uuid in control.state_uuids if uuid == binding.state_uuid), None)
    return resolver.source_reference(control, state_name=name)


class ProfileSources:
    """One freshly authorized snapshot index; no source reads or service privileges."""

    def __init__(
        self,
        installation: str,
        controls: dict[str, Control],
        weather: set[tuple[str, str]] | None = None,
        formats: dict[str, str] | None = None,
    ) -> None:
        self.installation = installation
        self.controls = controls
        self.weather = weather or set()
        self.formats = formats or {}

    @classmethod
    def from_structure(cls, installation: str, structure: LoxoneStructure) -> ProfileSources:
        weather = set()
        for item in structure.global_metadata:
            if item.kind == "weather_state" and item.identifier in {"actual", "forecast"}:
                try:
                    weather.add((item.identifier, normalize_loxone_uuid(item.state_uuid)))
                except (ValueError, TypeError):
                    continue
        return cls(
            installation, visible_controls(structure), weather, dict(structure.weather.formats)
        )

    def authorized(self, binding: ProfileBindingInput) -> bool:
        # Legacy mutations retain the control anchor even when a state was removed.
        if isinstance(binding, WeatherBindingInput):
            return (binding.mode, binding.weather_state_uuid) in self.weather
        return binding.control_uuid in self.controls

    def evidence(self, binding: ProfileBindingInput) -> tuple[str, str | None]:
        if not self.authorized(binding):
            raise ProfileError("profile_source_not_visible")
        if isinstance(binding, WeatherBindingInput):
            key = WEATHER_FORMAT_KEYS.get(binding.field)
            return _digest(
                [
                    self.installation,
                    binding.weather_state_uuid,
                    binding.mode,
                    binding.field,
                    self.formats.get(key) if key is not None else None,
                    WEATHER_RULE,
                ]
            ), WEATHER_RULE
        control = self.controls[binding.control_uuid]
        return source_fingerprint(binding, control), semantic_reference(binding, control)


class ProfileStore:
    """Revision-checked atomic file store with a cross-process lock and tombstones."""

    def __init__(self, path: Path) -> None:
        if not path.is_absolute() or path.suffix != ".json":
            raise ProfileError("profile_storage_invalid")
        self.path = path

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = self.path.with_suffix(".lock")
        if self.path.is_symlink() or lock.is_symlink():
            raise ProfileError("profile_storage_invalid")
        fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "r+b") as handle:
            deadline = time.monotonic() + LOCK_WAIT_SECONDS
            while True:
                try:
                    if sys.platform == "win32":  # pragma: win32 cover
                        import msvcrt

                        handle.seek(0)
                        if os.fstat(handle.fileno()).st_size == 0:
                            handle.write(b"0")
                            handle.flush()
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:  # pragma: posix cover
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ProfileError("profile_storage_busy") from None
                    time.sleep(0.05)
            try:
                yield
            finally:
                _unlock_file(handle)

    def _load(self, installation: str) -> ProfileDocument:
        if not self.path.exists():
            return ProfileDocument(installation=installation, revision=0)
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(MAX_DOCUMENT_BYTES + 1)
            if len(raw) > MAX_DOCUMENT_BYTES:
                raise ProfileError("profile_storage_limit")
            value = json.loads(raw)
            if isinstance(value, dict) and value.get("schema_version", 1) == 1:
                # Validate the original contract before the read-only conversion.
                legacy = LegacyProfileDocument.model_validate(value)
                value = legacy.model_dump()
                value["schema_version"] = 2
            return ProfileDocument.model_validate(value)
        except (OSError, ValueError, ValidationError) as exc:
            raise ProfileError("profile_storage_invalid") from exc

    def read(self, installation: str) -> ProfileDocument:
        with self._locked():
            return self._load(installation)

    def _write(self, document: ProfileDocument, *, deadline: float | None = None) -> None:
        payload = document.model_dump_json(indent=2).encode() + b"\n"
        if len(payload) > MAX_DOCUMENT_BYTES:
            raise ProfileError("profile_storage_limit")
        temporary = self.path.parent / (".profile-" + secrets.token_hex(16) + ".tmp")
        if deadline is not None and time.monotonic() >= deadline:
            raise ProfileError("profile_deadline_expired")
        try:
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            try:
                fsync_parent_directory(self.path)
            except OSError as exc:
                raise PersistenceUncertain("profile_durability_unconfirmed") from exc
        finally:
            temporary.unlink(missing_ok=True)

    def put(
        self,
        installation: str,
        expected_revision: int,
        binding: ProfileBindingInput,
        control: Control | ProfileSources,
        *,
        origin: Literal["local_admin", "mcp_user_confirmed"],
        actor_ref: str,
        deadline: float | None = None,
    ) -> ProfileDocument:
        sources = (
            control
            if isinstance(control, ProfileSources)
            else ProfileSources(installation, {control.uuid: control})
        )
        if sources.installation != installation:
            raise ProfileError("profile_installation_changed")
        fingerprint, reference = sources.evidence(binding)
        with self._locked():
            document = self._load(installation)
            if document.installation != installation:
                raise ProfileError("profile_installation_changed")
            if document.revision != expected_revision:
                raise ProfileError("profile_revision_conflict")
            retained = [item for item in document.bindings if item.binding_id != binding.binding_id]
            stored_type = (
                StoredWeatherBinding if isinstance(binding, WeatherBindingInput) else StoredBinding
            )
            stored = stored_type(
                **binding.model_dump(),
                source_fingerprint=fingerprint,
                semantic_reference=reference,
                confirmation_origin=origin if binding.confirmed else None,
                actor_ref=actor_ref if binding.confirmed else None,
            )
            updated = ProfileDocument(
                installation=installation,
                revision=document.revision + 1,
                bindings=[*retained, stored],
            )
            self._write(updated, deadline=deadline)
            return updated

    def delete(
        self,
        installation: str,
        expected_revision: int,
        binding_id: str | None,
        *,
        deadline: float | None = None,
    ) -> ProfileDocument:
        with self._locked():
            document = self._load(installation)
            if document.installation != installation and binding_id is not None:
                raise ProfileError("profile_installation_changed")
            if document.revision != expected_revision:
                raise ProfileError("profile_revision_conflict")
            retained = (
                []
                if binding_id is None
                else [b for b in document.bindings if b.binding_id != binding_id]
            )
            updated = ProfileDocument(
                installation=installation, revision=document.revision + 1, bindings=retained
            )
            self._write(updated, deadline=deadline)
            return updated


def project_profile(
    document: ProfileDocument,
    installation: str,
    controls: dict[str, Control] | ProfileSources,
    *,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    if document.installation != installation:
        return {
            "status": "installation_changed",
            "revision": document.revision,
            "bindings": [],
            "next_offset": None,
        }
    sources = (
        controls if isinstance(controls, ProfileSources) else ProfileSources(installation, controls)
    )
    visible = []
    for binding in document.bindings:
        if not sources.authorized(binding):
            continue
        control = (
            None
            if isinstance(binding, WeatherBindingInput)
            else sources.controls[binding.control_uuid]
        )
        status = "confirmed" if binding.confirmed else "draft"
        try:
            fingerprint, current_reference = sources.evidence(binding)
            if fingerprint != binding.source_fingerprint:
                status = "needs_review"
            if current_reference != binding.semantic_reference:
                status = "needs_review"
        except ProfileError:
            # Keep an invalid binding to a visible control actionable without
            # disclosing the old source identity or user-authored source context.
            if control is None:
                continue
            visible.append(
                {
                    "binding_id": binding.binding_id,
                    "role": binding.role,
                    "control_uuid": control.uuid,
                    "control_name": control.name,
                    "source_kind": binding.source_kind,
                    "state_uuid": None,
                    "series_id": None,
                    "rationale": "",
                    "confirmed": False,
                    "confirmation_origin": None,
                    "measurement_boundary": None,
                    "declared_direction": None,
                    "status": "invalid",
                    "fact_origin": "user_declared",
                    "semantic_status": "not_resolved",
                    "semantic_reference": None,
                    "measurement_boundary_origin": "user_declared",
                }
            )
            continue
        item = binding.model_dump(exclude={"actor_ref", "source_fingerprint"})
        item.update(
            {
                "status": status,
                "fact_origin": "user_declared",
                "semantic_status": "not_resolved",
                "semantic_reference": current_reference,
            }
        )
        if isinstance(binding, WeatherBindingInput):
            key = WEATHER_FORMAT_KEYS.get(binding.field)
            item.update(
                {
                    "source_format": sources.formats.get(key) if key is not None else None,
                    "unit": None,
                    "history_status": "unavailable",
                    "value_origin": "current_source_value"
                    if binding.mode == "actual"
                    else "forecast",
                }
            )
        else:
            assert control is not None
            item.update(
                {
                    "control_name": control.name,
                    "measurement_boundary_origin": "user_declared",
                    "pv_parameters_usable": status == "confirmed"
                    and binding.pv_parameters is not None,
                }
            )
        visible.append(item)
    selected = visible[offset : offset + limit]
    return {
        "status": "available",
        "revision": document.revision,
        "bindings": selected,
        "next_offset": offset + limit if offset + limit < len(visible) else None,
    }
