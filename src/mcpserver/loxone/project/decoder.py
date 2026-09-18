"""Decode a bounded LoxCC envelope and its LZ4-style block, independently of I/O."""

import struct
import zlib

from .models import DEFAULT_LIMITS, ProjectError, ProjectLimits


def decode_loxcc(data: bytes, limits: ProjectLimits = DEFAULT_LIMITS) -> bytes:
    if len(data) < 16:
        raise ProjectError("loxcc_header_invalid")
    magic, packed, expected, checksum = struct.unpack_from("<IIII", data)
    if magic != 0xAABBCCEE or packed != len(data) - 16:
        raise ProjectError("loxcc_header_invalid")
    if not 0 < expected <= limits.decoded_bytes or packed > limits.expanded_bytes:
        raise ProjectError("loxcc_size_limit")
    output = bytearray()
    cursor = 16

    def length(initial: int) -> int:
        nonlocal cursor
        value = initial
        if initial == 15:
            while True:
                if cursor >= len(data):
                    raise ProjectError("loxcc_truncated")
                extension = data[cursor]
                cursor += 1
                value += extension
                if value > expected:
                    raise ProjectError("loxcc_size_limit")
                if extension != 255:
                    break
        return value

    while cursor < len(data):
        sequence = data[cursor]
        cursor += 1
        literals = length(sequence >> 4)
        if cursor + literals > len(data):
            raise ProjectError("loxcc_truncated")
        if len(output) + literals > expected:
            raise ProjectError("loxcc_size_limit")
        output.extend(data[cursor : cursor + literals])
        cursor += literals
        if cursor == len(data):
            break
        if cursor + 2 > len(data):
            raise ProjectError("loxcc_truncated")
        distance = int.from_bytes(data[cursor : cursor + 2], "little")
        cursor += 2
        if distance == 0 or distance > len(output):
            raise ProjectError("loxcc_reference_invalid")
        count = length(sequence & 15) + 4
        if len(output) + count > expected:
            raise ProjectError("loxcc_size_limit")
        # Overlapping matches repeat a finite existing suffix. Copy in bounded
        # chunks rather than allocating an attacker-controlled repeat buffer.
        while count:
            step = min(count, distance, 65536)
            start = len(output) - distance
            output.extend(output[start : start + step])
            count -= step
    if len(output) != expected:
        raise ProjectError("loxcc_length_invalid")
    if zlib.crc32(output) != checksum:
        raise ProjectError("loxcc_checksum_invalid")
    return bytes(output)
