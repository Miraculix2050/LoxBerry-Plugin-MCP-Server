"""Small immutable configuration receipts, without private correction values."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

LIMIT = 32
MAX_BYTES = 16 * 1024
TTL = 7 * 24 * 60 * 60
_FIELDS = (
    "key",
    "digest",
    "manual_revision",
    "catalog_revision",
    "selected_changes",
    "changed_prefixes",
    "expires_at",
)


@dataclass(frozen=True, slots=True)
class PrefixReceipt:
    key: str
    digest: str
    manual_revision: str
    catalog_revision: int
    selected_changes: int
    changed_prefixes: int
    expires_at: int

    def document(self) -> dict[str, Any]:
        # All fields are validated scalar values. Recursive dataclass copying
        # adds avoidable work to every configuration load and write.
        return {
            "key": self.key,
            "digest": self.digest,
            "manual_revision": self.manual_revision,
            "catalog_revision": self.catalog_revision,
            "selected_changes": self.selected_changes,
            "changed_prefixes": self.changed_prefixes,
            "expires_at": self.expires_at,
        }

    def result(self) -> dict[str, Any]:
        return {
            "storage": "prefix_labels",
            "destination": "local_metadata",
            "manual_revision": self.manual_revision,
            "catalog_revision": self.catalog_revision,
            "selected_changes": self.selected_changes,
            "changed_prefixes": self.changed_prefixes,
            "changed_addresses": 0,
            "loxone_written": False,
            "import_written": False,
            "exports_file": False,
        }

    def config_record(self) -> list[str | int]:
        """Fixed scalar columns avoid repeated keys in the frequently read config."""
        return [
            self.key,
            self.digest,
            self.manual_revision,
            self.catalog_revision,
            self.selected_changes,
            self.changed_prefixes,
            self.expires_at,
        ]


def parse_receipts(value: object) -> tuple[PrefixReceipt, ...]:
    if not isinstance(value, list) or len(value) > LIMIT:
        raise ValueError("Invalid KNX prefix receipts")
    result: list[PrefixReceipt] = []
    seen: set[str] = set()
    fields = set(PrefixReceipt.__dataclass_fields__)
    for row in value:
        # Retain the initial object representation on read; new saves use the
        # strictly sized scalar row. This is internal storage, not MCP output.
        if isinstance(row, list) and len(row) == len(_FIELDS):
            row = dict(zip(_FIELDS, row, strict=True))
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError("Invalid KNX prefix receipt")
        if any(
            not isinstance(row[key], str) or not re.fullmatch(r"[0-9a-f]{64}", row[key])
            for key in ("key", "digest", "manual_revision")
        ):
            raise ValueError("Invalid KNX prefix receipt")
        if (
            any(type(row[key]) is not int for key in fields - {"key", "digest", "manual_revision"})
            or not 0 <= row["catalog_revision"] <= 2**53 - 1
            or not 1 <= row["selected_changes"] <= 50
            or not 0 <= row["changed_prefixes"] <= row["selected_changes"]
            or not 1 <= row["expires_at"] <= 2**53 - 1
            or row["key"] in seen
        ):
            raise ValueError("Invalid KNX prefix receipt")
        seen.add(row["key"])
        result.append(PrefixReceipt(**row))
    # The input was fully validated above; measure it without recreating rows.
    if len(json.dumps(value, separators=(",", ":")).encode()) > MAX_BYTES:
        raise ValueError("KNX prefix receipts exceed limit")
    return tuple(result)


def receipt_key(owner: str, target: str, request: str) -> str:
    return hashlib.sha256(
        json.dumps(
            ["knx-prefix-receipt-v1", owner, target, request], separators=(",", ":")
        ).encode()
    ).hexdigest()
