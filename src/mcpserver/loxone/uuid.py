"""Canonical UUID serialization shared by Loxone-facing integrations."""

from __future__ import annotations

from uuid import UUID


def normalize_loxone_uuid(value: object) -> str:
    """Return a UUID using Loxone's canonical 8-4-4-16 representation."""
    first, second, third, fourth, fifth = str(UUID(str(value))).split("-")
    return f"{first}-{second}-{third}-{fourth}{fifth}"


def normalize_history_control_id(value: object) -> str:
    """Normalize plain UUIDs; preserve exact bounded runtime suffix identities.

    A suffix is an opaque part of a runtime key, not a connector or parent
    reference. Callers must still resolve the whole key and its state against
    freshly authorized visibility before accessing local history.
    """
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise ValueError("History control identifier is invalid")
    base, separator, _suffix = value.partition("/")
    if not separator:
        return normalize_loxone_uuid(value)
    normalize_loxone_uuid(base)  # Validate syntax without rewriting the runtime key.
    return value
