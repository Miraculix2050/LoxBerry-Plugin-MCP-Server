"""Canonical ETS input, independent of file format and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAX_GROUPS = 1_024


@dataclass(frozen=True)
class ImportAddress:
    number: int
    address_format: str
    original: str
    fields: dict[str, Any]
    source: dict[str, Any]


@dataclass(frozen=True)
class ImportGroup:
    address_format: str
    prefix: str
    fields: dict[str, Any]
    source: dict[str, Any]


@dataclass(frozen=True)
class ImportDocument:
    addresses: tuple[ImportAddress, ...]
    groups: tuple[ImportGroup, ...]
    file_format: str
    encoding: str
    address_format: str
    source: dict[str, Any]


@dataclass(frozen=True)
class ImportSelection:
    addresses: tuple[ImportAddress, ...]
    groups: tuple[ImportGroup, ...]
    conflicts: tuple[dict[str, Any], ...]
    merged_duplicates: int
