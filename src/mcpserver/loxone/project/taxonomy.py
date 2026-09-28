"""Validated, administrator supplied labels for exact KNX address prefixes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_PREFIX = re.compile(r"^[0-9]{1,2}(?:/[0-9]{1,4}(?:/[0-9]{1,3})?)?$")
_MAX_ENTRIES = 128


@dataclass(frozen=True, slots=True)
class AddressTaxonomyEntry:
    prefix: str
    label: str
    address_format: Literal["two_level", "three_level"]

    @property
    def segments(self) -> tuple[int, ...]:
        return tuple(int(part) for part in self.prefix.split("/"))


def parse_taxonomy(value: object) -> tuple[AddressTaxonomyEntry, ...]:
    """Accept only canonical two- or three-level prefixes and short plain labels."""
    if not isinstance(value, list) or len(value) > _MAX_ENTRIES:
        raise ValueError("knx_address_taxonomy must be a list of at most 128 entries")
    entries: list[AddressTaxonomyEntry] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"prefix", "label", "address_format"}:
            raise ValueError("knx_address_taxonomy entry is invalid")
        prefix, label = item["prefix"], item["label"]
        address_format = item["address_format"]
        if not isinstance(address_format, str) or address_format not in {
            "two_level",
            "three_level",
        }:
            raise ValueError("knx_address_taxonomy address_format is invalid")
        normalized_format: Literal["two_level", "three_level"] = (
            "two_level" if address_format == "two_level" else "three_level"
        )
        if not isinstance(prefix, str) or not _PREFIX.fullmatch(prefix):
            raise ValueError("knx_address_taxonomy prefix is invalid")
        segments = tuple(int(part) for part in prefix.split("/"))
        if (
            segments[0] > 31
            or (address_format == "two_level" and len(segments) > 2)
            or (address_format == "two_level" and len(segments) == 2 and segments[1] > 2047)
            or (address_format == "three_level" and len(segments) >= 2 and segments[1] > 7)
            or (address_format == "three_level" and len(segments) == 3 and segments[2] > 255)
        ):
            raise ValueError("knx_address_taxonomy prefix is invalid")
        key = (address_format, prefix)
        if prefix != "/".join(str(part) for part in segments) or key in seen:
            raise ValueError("knx_address_taxonomy prefix is duplicate or noncanonical")
        if (
            not isinstance(label, str)
            or not 1 <= len(label) <= 80
            or label != label.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in label)
        ):
            raise ValueError("knx_address_taxonomy label is invalid")
        seen.add(key)
        entries.append(AddressTaxonomyEntry(prefix, label, normalized_format))
    return tuple(
        sorted(
            entries, key=lambda entry: (entry.address_format, len(entry.segments), entry.segments)
        )
    )
