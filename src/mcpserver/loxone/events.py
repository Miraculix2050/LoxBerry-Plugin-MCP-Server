"""Decode documented Loxone WebSocket headers and binary event tables."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Final
from uuid import UUID

from mcpserver.loxone.models import StateValue

_HEADER: Final = struct.Struct("<BBBBI")
_VALUE_EVENT: Final = struct.Struct("<16sd")
_TEXT_PREFIX: Final = struct.Struct("<16s16sI")
_DAYTIMER_PREFIX: Final = struct.Struct("<16sdi")
_DAYTIMER_ENTRY: Final = struct.Struct("<iiiid")
_WEATHER_PREFIX: Final = struct.Struct("<16sIi")
_WEATHER_ENTRY: Final = struct.Struct("<iiiiidddddd")


class MessageType(IntEnum):
    TEXT = 0
    BINARY_FILE = 1
    VALUE_STATES = 2
    TEXT_STATES = 3
    DAYTIMER_STATES = 4
    OUT_OF_SERVICE = 5
    KEEPALIVE = 6
    WEATHER_STATES = 7


class LoxoneProtocolError(ValueError):
    """Raised when a WebSocket payload violates the documented binary format."""


@dataclass(frozen=True, slots=True)
class MessageHeader:
    message_type: MessageType
    estimated: bool
    payload_length: int


@dataclass(frozen=True, slots=True)
class StateEvent:
    uuid: str
    value: StateValue


def parse_header(payload: bytes, *, max_payload_bytes: int) -> MessageHeader:
    if len(payload) != _HEADER.size:
        raise LoxoneProtocolError("WebSocket header must contain exactly 8 bytes")
    marker, identifier, info, reserved, payload_length = _HEADER.unpack(payload)
    if marker != 0x03 or reserved != 0 or info & 0x7F:
        raise LoxoneProtocolError("WebSocket header contains invalid reserved data")
    try:
        message_type = MessageType(identifier)
    except ValueError as exc:
        raise LoxoneProtocolError("WebSocket header contains an unknown message type") from exc
    if payload_length > max_payload_bytes:
        raise LoxoneProtocolError("WebSocket payload exceeds the configured limit")
    return MessageHeader(
        message_type=message_type,
        estimated=bool(info & 0x80),
        payload_length=payload_length,
    )


def _uuid(raw: bytes) -> str:
    if len(raw) != 16:
        raise LoxoneProtocolError("Event UUID must contain 16 bytes")
    data1, data2, data3 = struct.unpack("<IHH", raw[:8])
    tail = "".join(f"{byte:02x}" for byte in raw[8:])
    return str(UUID(f"{data1:08x}-{data2:04x}-{data3:04x}-{tail[:4]}-{tail[4:]}"))


def parse_value_events(payload: bytes) -> tuple[StateEvent, ...]:
    if len(payload) % _VALUE_EVENT.size:
        raise LoxoneProtocolError("Value event table has a truncated entry")
    return tuple(
        StateEvent(uuid=_uuid(raw_uuid), value=value)
        for raw_uuid, value in _VALUE_EVENT.iter_unpack(payload)
    )


def parse_text_events(payload: bytes) -> tuple[StateEvent, ...]:
    events: list[StateEvent] = []
    offset = 0
    while offset < len(payload):
        if len(payload) - offset < _TEXT_PREFIX.size:
            raise LoxoneProtocolError("Text event table has a truncated prefix")
        raw_uuid, _icon_uuid, length = _TEXT_PREFIX.unpack_from(payload, offset)
        offset += _TEXT_PREFIX.size
        end = offset + length
        if end > len(payload):
            raise LoxoneProtocolError("Text event table has a truncated value")
        try:
            text = payload[offset:end].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LoxoneProtocolError("Text event is not valid UTF-8") from exc
        events.append(StateEvent(uuid=_uuid(raw_uuid), value=text))
        offset = end + ((-length) % 4)
        if offset > len(payload):
            raise LoxoneProtocolError("Text event table has invalid padding")
    return tuple(events)


def parse_daytimer_events(payload: bytes) -> tuple[StateEvent, ...]:
    events: list[StateEvent] = []
    offset = 0
    while offset < len(payload):
        if len(payload) - offset < _DAYTIMER_PREFIX.size:
            raise LoxoneProtocolError("Daytimer table has a truncated prefix")
        raw_uuid, default_value, count = _DAYTIMER_PREFIX.unpack_from(payload, offset)
        offset += _DAYTIMER_PREFIX.size
        if count < 0 or count > (len(payload) - offset) // _DAYTIMER_ENTRY.size:
            raise LoxoneProtocolError("Daytimer table has an invalid entry count")
        entries: list[object] = [default_value]
        for _ in range(count):
            entries.append(_DAYTIMER_ENTRY.unpack_from(payload, offset))
            offset += _DAYTIMER_ENTRY.size
        events.append(StateEvent(uuid=_uuid(raw_uuid), value=tuple(entries)))
    return tuple(events)


def parse_weather_events(payload: bytes) -> tuple[StateEvent, ...]:
    events: list[StateEvent] = []
    offset = 0
    while offset < len(payload):
        if len(payload) - offset < _WEATHER_PREFIX.size:
            raise LoxoneProtocolError("Weather table has a truncated prefix")
        raw_uuid, last_update, count = _WEATHER_PREFIX.unpack_from(payload, offset)
        offset += _WEATHER_PREFIX.size
        if count < 0 or count > (len(payload) - offset) // _WEATHER_ENTRY.size:
            raise LoxoneProtocolError("Weather table has an invalid entry count")
        entries: list[object] = [last_update]
        for _ in range(count):
            entries.append(_WEATHER_ENTRY.unpack_from(payload, offset))
            offset += _WEATHER_ENTRY.size
        events.append(StateEvent(uuid=_uuid(raw_uuid), value=tuple(entries)))
    return tuple(events)


def parse_state_events(message_type: MessageType, payload: bytes) -> tuple[StateEvent, ...]:
    parsers = {
        MessageType.VALUE_STATES: parse_value_events,
        MessageType.TEXT_STATES: parse_text_events,
        MessageType.DAYTIMER_STATES: parse_daytimer_events,
        MessageType.WEATHER_STATES: parse_weather_events,
    }
    parser = parsers.get(message_type)
    if parser is None:
        raise LoxoneProtocolError("Message does not contain a state event table")
    return parser(payload)
