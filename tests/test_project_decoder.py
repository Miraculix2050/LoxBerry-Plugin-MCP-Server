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
