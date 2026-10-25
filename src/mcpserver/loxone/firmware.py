"""Bounded firmware metadata, without version-specific admission rules."""

import re


def valid_firmware(value: object) -> bool:
    """Validate public metadata without claiming device compatibility."""
    return (
        isinstance(value, str) and re.fullmatch(r"[0-9]{1,5}(?:\.[0-9]{1,5}){3}", value) is not None
    )
