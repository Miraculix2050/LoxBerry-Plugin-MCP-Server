"""Canonical UUID serialization shared by Loxone-facing integrations."""

from __future__ import annotations

from uuid import UUID


def normalize_loxone_uuid(value: object) -> str:
    """Return a UUID using Loxone's canonical 8-4-4-16 representation."""
    first, second, third, fourth, fifth = str(UUID(str(value))).split("-")
    return f"{first}-{second}-{third}-{fourth}{fifth}"
