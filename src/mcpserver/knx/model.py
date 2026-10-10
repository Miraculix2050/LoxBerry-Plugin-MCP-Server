"""Bounded metadata validation shared by manual and import adapters."""

from __future__ import annotations

import re
from typing import Any

MAX_ADDRESSES = 65_536
MAX_FILE_BYTES = 16 * 1024 * 1024
FIELDS = frozenset({"name", "description", "dpts", "central", "unfiltered", "security"})


class KnxError(ValueError):
    """A fixed, sanitized metadata error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def address(value: object, address_format: object) -> tuple[int, str]:
    if not isinstance(value, str) or len(value) > 16:
        raise KnxError("knx_address_invalid")
    pattern = r"(0|[1-9][0-9]?)/(0|[1-9][0-9]{0,3})"
    if address_format == "three_level":
        pattern += r"/(0|[1-9][0-9]{0,2})"
    elif address_format != "two_level":
        raise KnxError("knx_format_invalid")
    if not re.fullmatch(pattern, value):
        raise KnxError("knx_address_invalid")
    parts = [int(part) for part in value.split("/")]
    if parts[0] > 31:
        raise KnxError("knx_address_invalid")
    if address_format == "three_level":
        if parts[1] > 7 or parts[2] > 255:
            raise KnxError("knx_address_invalid")
        return (parts[0] << 11) | (parts[1] << 8) | parts[2], value
    if parts[1] > 2047:
        raise KnxError("knx_address_invalid")
    return (parts[0] << 11) | parts[1], value


def text(value: object, maximum: int, *, empty: bool = True) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or (not empty and not value.strip())
        or any(ord(c) < 32 and c not in "\r\n\t" for c in value)
        or any(0xD800 <= ord(c) <= 0xDFFF or ord(c) == 127 for c in value)
    ):
        raise KnxError("knx_field_invalid")
    return value


def metadata(value: object, *, require_name: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict) or not value.keys() <= FIELDS:
        raise KnxError("knx_fields_invalid")
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"name", "description", "security"}:
            result[key] = text(item, 4096 if key == "description" else 255)
        elif key == "dpts":
            if not isinstance(item, list) or len(item) > 16:
                raise KnxError("knx_dpts_invalid")
            result[key] = list(dict.fromkeys(text(dpt, 64, empty=False) for dpt in item))
        elif type(item) is not bool:
            raise KnxError("knx_flag_invalid")
        else:
            result[key] = item
    if require_name:
        text(result.get("name"), 255, empty=False)
    return result
