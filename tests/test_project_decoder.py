import struct
import zlib

import pytest

from mcpserver.loxone.project.decoder import decode_loxcc
from mcpserver.loxone.project.models import ProjectError, ProjectLimits


def envelope(packed, plain):
    return struct.pack("<IIII", 0xAABBCCEE, len(packed), len(plain), zlib.crc32(plain)) + packed


def test_literals_and_overlapping_back_reference():
    assert decode_loxcc(envelope(b"\x50hello", b"hello")) == b"hello"
    assert decode_loxcc(envelope(b"\x14a\x01\x00", b"a" * 9)) == b"a" * 9


def test_extended_literal_length():
    plain = b"z" * 300
    assert decode_loxcc(envelope(b"\xf0\xff\x1e" + plain, plain)) == plain


@pytest.mark.parametrize("distance", [1, 2, 8, 255, 256, 65535])
@pytest.mark.parametrize("count", [4, 8, 18, 19, 300, 65536, 65537])
def test_match_boundaries_preserve_exact_output_and_limits(distance, count):
    def extension(value):
        return b"\xff" * (value // 255) + bytes([value % 255])

    seed = bytes(index % 251 for index in range(distance))
    packed = bytes([(min(distance, 15) << 4) | min(count - 4, 15)])
    if distance >= 15:
        packed += extension(distance - 15)
    packed += seed + distance.to_bytes(2, "little")
    if count >= 19:
        packed += extension(count - 19)
    packed += b"\x50tail!"
    plain = seed + (seed * ((count + distance - 1) // distance))[:count] + b"tail!"
    assert decode_loxcc(envelope(packed, plain)) == plain
    with pytest.raises(ProjectError, match="size_limit"):
        decode_loxcc(envelope(packed, plain), ProjectLimits(decoded_bytes=len(plain) - 1))
    with pytest.raises(ProjectError, match="checksum"):
        decode_loxcc(envelope(packed, plain[:-1] + b"?"))


@pytest.mark.parametrize("packed", [b"\x1fa\x01\x00", b"\x1fa\x01\x00\xff"])
def test_missing_match_length_extension_is_rejected(packed):
    with pytest.raises(ProjectError, match="truncated|size_limit"):
        decode_loxcc(envelope(packed, b"a" * 300))


@pytest.mark.parametrize(
    "packed", [b"\x10", b"\xf0\xff", b"\x10a\x00\x00", b"\x10a\x02\x00", b"\x10a\x01"]
)
def test_invalid_blocks_fail_closed(packed):
    with pytest.raises(ProjectError):
        decode_loxcc(envelope(packed, b"a" * 5))


def test_checksum_and_allocation_limits():
    with pytest.raises(ProjectError, match="checksum"):
        decode_loxcc(envelope(b"\x10a", b"b"))
    with pytest.raises(ProjectError, match="size_limit"):
        decode_loxcc(envelope(b"\x10a", b"a"), ProjectLimits(decoded_bytes=0))


def test_every_truncation_is_rejected():
    valid = envelope(b"\x50hello", b"hello")
    for end in range(len(valid)):
        with pytest.raises(ProjectError):
            decode_loxcc(valid[:end])
