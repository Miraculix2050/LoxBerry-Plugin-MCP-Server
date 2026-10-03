"""Bounded positional contact decoding; no alarm or physical-coverage inference."""

from __future__ import annotations

import json
import re
from typing import Any

from .models import Control, WindowMonitorItem

WINDOW_DOCUMENT = (
    "https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf"
)
WINDOW_BITS = ((1, "closed"), (2, "tilted"), (4, "open"), (8, "locked"), (16, "unlocked"))


def decode_window_states(control: Control, value: object) -> dict[str, Any] | None:
    """Decode at most 100 positions and 16 KiB from a bounded source string."""
    if not isinstance(value, str) or len(value) > 65_536:
        return None
    total = value.count(",") + 1 if value else 0
    tokens = value.split(",", 100)[:100] if value else []
    summary = control.window_monitor_summary
    expected = summary.total if summary is not None else None
    metadata: dict[int, list[WindowMonitorItem]] = {}
    for source_item in control.window_monitor_items[:100]:
        if 0 <= source_item.index < 100:
            metadata.setdefault(source_item.index, []).append(source_item)
    positions = min(100, max(total, expected or 0, max(metadata, default=-1) + 1))
    contacts: list[dict[str, Any]] = []
    for index in range(positions):
        raw = tokens[index] if index < len(tokens) else None
        token = raw.strip(" \t\r\n") if raw is not None else None
        mask = int(token) if token is not None and re.fullmatch(r"[0-9]{1,10}", token) else None
        if mask is not None and mask > 31:
            mask = None
        status = "missing" if raw is None else "invalid" if mask is None else "decoded"
        candidates = metadata.get(index, [])
        item = candidates[0] if len(candidates) == 1 else None
        mapping = (
            "ambiguous"
            if len(candidates) > 1
            else "missing_metadata"
            if item is None
            else "invalid_metadata"
            if item.diagnostics
            else "missing_reference"
            if not item.control_uuid or not item.room_uuid
            else "matched"
        )
        contacts.append(
            {
                "index": index,
                "raw_token": raw[:200] if raw is not None else None,
                "raw_token_truncated": raw is not None and len(raw) > 200,
                "bitmask": mask,
                "states": [name for bit, name in WINDOW_BITS if mask & bit] if mask else [],
                "decoding_status": "unknown_or_offline" if mask == 0 else status,
                "mapping_status": mapping,
                "contact": {
                    "index": item.index,
                    "name": item.name,
                    "room_uuid": item.room_uuid,
                    "control_uuid": item.control_uuid,
                    "install_place": item.install_place,
                    "diagnostics": list(item.diagnostics),
                }
                if item is not None
                else None,
            }
        )
    truncated = (
        max(total, expected or 0, max(metadata, default=-1) + 1) > positions
        or len(control.window_monitor_items) > 100
        or (summary is not None and summary.truncated)
    )
    alignment = "unknown" if expected is None else "match" if expected == total else "mismatch"
    metadata_complete = (
        summary is not None
        and not summary.truncated
        and not summary.diagnostics
        and summary.returned == expected
        and len(control.window_monitor_items) == expected
    )
    decoding_complete = all(c["bitmask"] is not None for c in contacts) and not truncated
    result: dict[str, Any] = {
        "kind": "window_contact_states",
        "provenance": {
            "control_uuid": control.uuid,
            "state_name": "windowStates",
            "state_uuid": dict(control.state_uuids).get("windowStates"),
            "document_version": "17.1",
            "reference": WINDOW_DOCUMENT + "#page=152",
        },
        "contacts": contacts,
        "values_total": total,
        "positions_total": expected,
        "positions_returned": len(contacts),
        "alignment": alignment,
        "truncated": truncated,
        "metadata_complete": metadata_complete,
        "invalid_values": any(c["decoding_status"] == "invalid" for c in contacts),
        "decoding_complete": decoding_complete,
        "mapping_complete": decoding_complete
        and metadata_complete
        and alignment == "match"
        and all(c["mapping_status"] == "matched" for c in contacts),
    }
    while contacts and len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 16_384:
        contacts.pop()
        result.update(
            positions_returned=len(contacts),
            truncated=True,
            decoding_complete=False,
            mapping_complete=False,
        )
    return result
