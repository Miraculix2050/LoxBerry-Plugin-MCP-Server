"""Version-bound Message Center decoding; source text is untrusted evidence."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel

SUPPORTED_FIRMWARE = frozenset({"17.2.8.28"})
SYSTEM_MESSAGES_PERMISSION = 131072
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 2000
_IDENTIFIER = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-(?:[0-9a-fA-F]{16}|[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)
type MessageSeverity = Literal["info", "warning", "important", "critical", "unknown"]
_SEVERITIES: dict[int, MessageSeverity] = {1: "info", 2: "warning", 3: "important", 4: "critical"}


class MessageSourceError(ValueError):
    """A fixed, privacy-safe source diagnostic."""


class SystemMessage(BaseModel):
    entry_uuid: str
    event_id: int
    title: str
    description: str
    affected_name: str
    source_uuid: str | None
    affected_uuids: list[str]
    room_uuid: str | None
    installation_place: str | None
    severity_code: int
    severity: MessageSeverity
    historic: bool
    set_historic_at: int | None
    confirmed_at: int | None
    timestamps: list[int]
    read_at: int | None
    visu_locked: bool
    acknowledgement_available: bool
    truncated_fields: list[str]


class MessageSource(BaseModel):
    firmware: str
    miniserver_serial: str
    message_center_uuid: str
    source_revision: str
    source: Literal["message_center_getEntries_v2"] = "message_center_getEntries_v2"
    experimental: Literal[True] = True
    retention_complete: Literal[False] = False
    source_total: int
    records: list[SystemMessage]


def identifier(value: Any) -> str | None:
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def canonical_serial(value: str) -> str:
    """Normalize only the observed MAC presentation, never arbitrary target strings."""
    normalized = value.replace(":", "").replace("-", "").lower()
    if re.fullmatch(r"[0-9a-f]{12}", normalized) is None:
        raise MessageSourceError("invalid_source_identity")
    return normalized


def _timestamp(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 4_102_444_800:
        raise MessageSourceError("invalid_source_timestamp")
    return value


def _text(value: Any, field: str, maximum: int, truncated: list[str]) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise MessageSourceError("invalid_source_text")
    # Drop source URLs and common credential assignments. Never return action links.
    text = re.sub(r"https?://[^\s<>\"']+", "[link omitted]", value)
    text = re.sub(
        r"(?i)\b(password|passwd|token|secret|authorization|api[_ -]?key|pin)\s*[:=]\s*[^\s<>]+",
        r"\1=[redacted]",
        text,
    )
    text = "".join(char for char in text if char in "\n\t" or ord(char) >= 32)
    if len(text) > maximum:
        truncated.append(field)
    return text[:maximum]


def decode_messages(
    raw: Any, *, firmware: str, serial: str, center: str, rights: int
) -> MessageSource:
    """Reject incompatible payloads rather than silently reporting message absence."""
    if isinstance(raw, str):
        if len(raw.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise MessageSourceError("source_too_large")
        try:
            raw = json.loads(raw)
        except (ValueError, RecursionError) as exc:
            raise MessageSourceError("invalid_source_json") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
        raise MessageSourceError("invalid_source_collection")
    encoded = json.dumps(raw, sort_keys=True, ensure_ascii=True).encode()
    if len(encoded) > MAX_SOURCE_BYTES or len(raw["entries"]) > MAX_ENTRIES:
        raise MessageSourceError("source_too_large")
    records: list[SystemMessage] = []
    seen: set[str] = set()
    for entry in raw["entries"]:
        if not isinstance(entry, dict):
            raise MessageSourceError("invalid_source_entry")
        entry_uuid = identifier(entry.get("entryUuid"))
        if entry_uuid is None or entry_uuid in seen:
            raise MessageSourceError("invalid_source_entry_identity")
        seen.add(entry_uuid)
        severity, event_id = entry.get("severity"), entry.get("eventId")
        if type(severity) is not int or type(event_id) is not int or not 0 <= event_id < 2**32:
            raise MessageSourceError("invalid_source_classification")
        historic, locked = entry.get("isHistoric"), entry.get("isVisuLocked")
        if type(historic) is not bool or type(locked) is not bool:
            raise MessageSourceError("invalid_source_lifecycle")
        timestamps, affected = entry.get("timestamps"), entry.get("affectedUuids")
        if not isinstance(timestamps, list) or not timestamps or len(timestamps) > 1000:
            raise MessageSourceError("invalid_source_timestamps")
        parsed_times = [_timestamp(value) for value in timestamps]
        if any(value is None for value in parsed_times):
            raise MessageSourceError("invalid_source_timestamps")
        if (
            not isinstance(affected, list)
            or len(affected) > 100
            or any(identifier(v) is None for v in affected)
        ):
            raise MessageSourceError("invalid_source_references")
        for key in ("sourceUuid", "roomUuid"):
            if entry.get(key) is not None and identifier(entry[key]) is None:
                raise MessageSourceError("invalid_source_references")
        actions = entry.get("actions")
        if not isinstance(actions, list) or len(actions) > 20:
            raise MessageSourceError("invalid_source_actions")
        acknowledgement = any(
            isinstance(action, dict)
            and type(action.get("actionId")) is int
            and action["actionId"] == 1005
            and action.get("isSecured") is False
            and action.get("link") is None
            and action.get("location") is None
            and type(action.get("requiredPermissions")) is int
            and 0 <= action["requiredPermissions"] < 2**32
            and rights & action["requiredPermissions"] == action["requiredPermissions"]
            for action in actions
        )
        truncated: list[str] = []
        records.append(
            SystemMessage(
                entry_uuid=entry_uuid,
                event_id=event_id,
                title=_text(entry.get("title"), "title", 512, truncated),
                description=_text(entry.get("desc"), "description", 4096, truncated),
                affected_name=_text(entry.get("affectedName"), "affected_name", 256, truncated),
                source_uuid=entry.get("sourceUuid"),
                affected_uuids=affected,
                room_uuid=entry.get("roomUuid"),
                installation_place=_text(
                    entry.get("installationPlace"), "installation_place", 256, truncated
                )
                or None,
                severity_code=severity,
                severity=_SEVERITIES.get(severity, "unknown"),
                historic=historic,
                set_historic_at=_timestamp(entry.get("setHistoricAt")),
                confirmed_at=_timestamp(entry.get("confirmedAt")),
                timestamps=[value for value in parsed_times if value is not None],
                read_at=_timestamp(entry.get("readAt")),
                visu_locked=locked,
                acknowledgement_available=acknowledgement,
                truncated_fields=truncated,
            )
        )
    records.sort(key=lambda record: (max(record.timestamps), record.entry_uuid), reverse=True)
    return MessageSource(
        firmware=firmware,
        miniserver_serial=serial,
        message_center_uuid=center,
        source_revision=hashlib.sha256(encoded).hexdigest(),
        source_total=len(records),
        records=records,
    )
