"""Decode only the latest authorized notification text state, never client history."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from mcpserver.loxone.system_messages import MessageSourceError, _text, identifier


class Notification(BaseModel):
    uid: str | int
    title: str
    message: str
    source_control_uuid: str | None
    source_type: str | int | None
    source_level: str | int | None
    truncated_fields: list[str]


def decode_notification(value: Any) -> Notification:
    if not isinstance(value, str) or len(value.encode(errors="surrogatepass")) > 16_384:
        raise MessageSourceError("invalid_notification_event")
    try:
        try:
            raw = json.loads(value)
        except ValueError:
            if not value.startswith('{\\"'):
                raise
            raw = json.loads(value.replace('\\"', '"'))
    except (ValueError, RecursionError) as exc:
        raise MessageSourceError("invalid_notification_json") from exc
    if not isinstance(raw, dict):
        raise MessageSourceError("invalid_notification_event")
    uid = raw.get("uid")
    if (
        not isinstance(uid, str | int)
        or isinstance(uid, bool)
        or (isinstance(uid, str) and not 1 <= len(uid) <= 128)
    ):
        raise MessageSourceError("notification_event_has_no_message_identity")
    data = raw.get("data", {})
    if not isinstance(data, dict):
        raise MessageSourceError("invalid_notification_reference")
    for field in (uid, raw.get("type"), data.get("lvl")):
        if isinstance(field, str) and any(0xD800 <= ord(char) <= 0xDFFF for char in field):
            raise MessageSourceError("invalid_notification_text")
    uuid = data.get("uuid")
    if uuid is not None and identifier(uuid) is None:
        raise MessageSourceError("invalid_notification_reference")
    for item in (raw.get("type"), data.get("lvl")):
        if item is not None and (
            type(item) not in {str, int} or (isinstance(item, str) and len(item) > 64)
        ):
            raise MessageSourceError("invalid_notification_classification")
    truncated: list[str] = []
    return Notification(
        uid=uid,
        title=_text(raw.get("title"), "title", 512, truncated),
        message=_text(raw.get("message"), "message", 4096, truncated),
        source_control_uuid=uuid,
        source_type=raw.get("type"),
        source_level=data.get("lvl"),
        truncated_fields=truncated,
    )
