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
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from mcpserver.config import _unlock_file
from mcpserver.loxone.models import Control, LoxoneStructure
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


class BindingInput(BaseModel):
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
    def source(self) -> BindingInput:
        if self.source_kind == "state":
            valid = self.state_uuid is not None and self.series_id is None
        else:
            valid = self.series_id is not None and self.state_uuid is None
        if not valid:
            raise ValueError("profile_source_invalid")
        return self


class StoredBinding(BindingInput):
    source_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmation_origin: Literal["local_admin", "mcp_user_confirmed"] | None = None
    actor_ref: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def confirmation(self) -> StoredBinding:
        if self.confirmed != (self.confirmation_origin is not None and self.actor_ref is not None):
            raise ValueError("profile_confirmation_invalid")
        if not self.confirmed and (
            self.confirmation_origin is not None or self.actor_ref is not None
        ):
            raise ValueError("profile_confirmation_invalid")
        return self


class ProfileDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    installation: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: int = Field(ge=0, le=2**31 - 1)
    bindings: list[StoredBinding] = Field(default_factory=list, max_length=MAX_BINDINGS)

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
            return ProfileDocument.model_validate(json.loads(raw))
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
        binding: BindingInput,
        control: Control,
        *,
        origin: Literal["local_admin", "mcp_user_confirmed"],
        actor_ref: str,
        deadline: float | None = None,
    ) -> ProfileDocument:
        fingerprint = source_fingerprint(binding, control)
        with self._locked():
            document = self._load(installation)
            if document.installation != installation:
                raise ProfileError("profile_installation_changed")
            if document.revision != expected_revision:
                raise ProfileError("profile_revision_conflict")
            retained = [item for item in document.bindings if item.binding_id != binding.binding_id]
            stored = StoredBinding(
                **binding.model_dump(),
                source_fingerprint=fingerprint,
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
    controls: dict[str, Control],
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
    visible = []
    for binding in document.bindings:
        control = controls.get(binding.control_uuid)
        if control is None:
            continue
        status = "confirmed" if binding.confirmed else "draft"
        try:
            if source_fingerprint(binding, control) != binding.source_fingerprint:
                status = "needs_review"
        except ProfileError:
            # Keep an invalid binding to a visible control actionable without
            # disclosing the old source identity or user-authored source context.
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
                    "measurement_boundary_origin": "user_declared",
                }
            )
            continue
        item = binding.model_dump(exclude={"actor_ref", "source_fingerprint"})
        item.update(
            {
                "status": status,
                "fact_origin": "user_declared",
                "control_name": control.name,
                "semantic_status": "not_resolved",
                "measurement_boundary_origin": "user_declared",
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
