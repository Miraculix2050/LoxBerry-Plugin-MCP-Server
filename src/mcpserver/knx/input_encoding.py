"""Bounded, lossless character decoding shared by ETS file adapters."""

from .model import MAX_FILE_BYTES, KnxError


def decode_input(raw: bytes, encoding: str = "auto") -> tuple[str, str]:
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise KnxError("knx_file_limit")
    if not isinstance(encoding, str) or encoding not in {"auto", "utf-8", "windows-1252"}:
        raise KnxError("knx_encoding_invalid")
    if b"\0" in raw:
        raise KnxError("knx_encoding_unsupported")
    candidates = ("utf-8", "windows-1252") if encoding == "auto" else (encoding,)
    for candidate in candidates:
        try:
            return raw.decode("utf-8-sig" if candidate == "utf-8" else "cp1252"), candidate
        except UnicodeDecodeError:
            continue
    raise KnxError("knx_encoding_invalid")
