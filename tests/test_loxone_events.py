from __future__ import annotations

import struct
from uuid import UUID

import pytest

from mcpserver.loxone.events import (
    LoxoneProtocolError,
    MessageType,
    parse_header,
    parse_text_events,
    parse_value_events,
)


def _loxone_uuid(value: str) -> bytes:
    parsed = UUID(value)
    return (
        struct.pack("<IHH", parsed.time_low, parsed.time_mid, parsed.time_hi_version)
        + parsed.bytes[8:]
    )


def test_header_parses_little_endian_length() -> None:
    header = parse_header(struct.pack("<BBBBI", 3, 2, 0, 0, 24), max_payload_bytes=100)

    assert header.message_type is MessageType.VALUE_STATES
    assert header.payload_length == 24
    assert header.estimated is False


def test_header_rejects_oversized_payload() -> None:
    with pytest.raises(LoxoneProtocolError, match="exceeds"):
        parse_header(struct.pack("<BBBBI", 3, 2, 0, 0, 101), max_payload_bytes=100)


def test_value_table_decodes_multiple_events() -> None:
    first = "00112233-4455-6677-8899-aabbccddeeff"
    second = "11112222-3333-4444-aaaa-bbbbccccdddd"
    payload = _loxone_uuid(first) + struct.pack("<d", 1.5)
    payload += _loxone_uuid(second) + struct.pack("<d", -2.0)

    events = parse_value_events(payload)

    assert [(event.uuid, event.value) for event in events] == [
        ("00112233-4455-6677-8899aabbccddeeff", 1.5),
        ("11112222-3333-4444-aaaabbbbccccdddd", -2.0),
    ]


def test_text_table_honors_four_byte_padding() -> None:
    state_uuid = "00112233-4455-6677-8899-aabbccddeeff"
    icon_uuid = "00000000-0000-0000-0000-000000000000"
    text = b"on"
    payload = _loxone_uuid(state_uuid) + _loxone_uuid(icon_uuid) + struct.pack("<I", len(text))
    payload += text + b"\0\0"

    event = parse_text_events(payload)[0]

    assert event.uuid == "00112233-4455-6677-8899aabbccddeeff"
    assert event.value == "on"
