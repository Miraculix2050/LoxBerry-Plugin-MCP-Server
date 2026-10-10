"""Bounded modern ETS XML reader; no DTD, entities or external resolution."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, cast

from .import_model import MAX_GROUPS, ImportAddress, ImportDocument, ImportGroup
from .model import MAX_ADDRESSES, MAX_FILE_BYTES, KnxError, address, metadata, text

NAMESPACE = "http://knx.org/xml/ga-export/01"
TAG = "{" + NAMESPACE + "}"


def decode_input(raw: bytes, encoding: str = "auto") -> tuple[str, str]:
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise KnxError("knx_file_limit")
    if encoding not in {"auto", "utf-8", "windows-1252"}:
        raise KnxError("knx_encoding_invalid")
    if b"\0" in raw:
        raise KnxError("knx_encoding_unsupported")
    candidates = ("utf-8", "windows-1252") if encoding == "auto" else (encoding,)
    for candidate in candidates:
        try:
            value = raw.decode("utf-8-sig" if candidate == "utf-8" else "cp1252")
            return value, candidate
        except UnicodeDecodeError:
            continue
    raise KnxError("knx_encoding_invalid")


class _BoundedTree:
    """Reject unsafe or oversized content while building, before traversal."""

    def __init__(self) -> None:
        self.builder = ET.TreeBuilder(insert_comments=True)
        self.depth = 0
        self.elements = 0
        self.comments = 0
        self.comment_bytes = 0
        self.outer_comments: list[dict[str, str]] = []
        self.started = False

    def start(self, tag: str, attrs: dict[str, str]) -> ET.Element:
        self.depth += 1
        self.started = True
        self.elements += 1
        if self.depth > 4 or self.elements > MAX_ADDRESSES + MAX_GROUPS + 1:
            raise KnxError("knx_xml_structure_limit")
        if (
            len(attrs) > 64
            or len(tag) > 255
            or sum(len(key) + len(value) for key, value in attrs.items()) > 16 * 1024
        ):
            raise KnxError("knx_xml_structure_limit")
        for key, value in attrs.items():
            text(key, 255, empty=False)
            text(value, 4096)
        return self.builder.start(tag, attrs)

    def end(self, tag: str) -> ET.Element:
        self.depth -= 1
        return self.builder.end(tag)

    def data(self, value: str) -> None:
        if value.strip():
            raise KnxError("knx_xml_text_unsupported")
        self.builder.data(value)

    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise KnxError("knx_xml_unsafe")

    def comment(self, value: str) -> None:
        text(value, 4096)
        self.comments += 1
        self.comment_bytes += len(value.encode("utf-8"))
        if self.comments > 1024 or self.comment_bytes > 64 * 1024:
            raise KnxError("knx_xml_structure_limit")
        if self.depth == 0:
            self.outer_comments.append(
                {"text": value, "location": "after" if self.started else "before"}
            )
        self.builder.comment(value)

    def pi(self, target: str, value: str) -> None:
        raise KnxError("knx_xml_element_unsupported")

    def close(self) -> ET.Element:
        return self.builder.close()


def _fields(attrs: dict[str, str], *, group: bool = False) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for source, field in (("Name", "name"), ("Description", "description")):
        if source in attrs:
            fields[field] = attrs[source]
    if not group:
        if "DPTs" in attrs:
            fields["dpts"] = attrs["DPTs"].split()
        for source, field in (("Central", "central"), ("Unfiltered", "unfiltered")):
            if source in attrs:
                if attrs[source] not in {"true", "false"}:
                    raise KnxError("knx_flag_invalid")
                fields[field] = attrs[source] == "true"
        if "Security" in attrs:
            fields["security"] = attrs["Security"]
    return metadata(fields, require_name=True)


def _range(element: ET.Element, depth: int) -> tuple[int, int, str]:
    try:
        lower_text, upper_text = element.attrib["RangeStart"], element.attrib["RangeEnd"]
        if not re.fullmatch(r"[0-9]{1,5}", lower_text) or not re.fullmatch(
            r"[0-9]{1,5}", upper_text
        ):
            raise ValueError
        lower, upper = int(lower_text), int(upper_text)
    except (KeyError, ValueError):
        raise KnxError("knx_range_invalid") from None
    if not 0 <= lower <= upper < MAX_ADDRESSES:
        raise KnxError("knx_range_invalid")
    bits = 11 if depth == 0 else 8
    mask = (1 << bits) - 1
    if lower >> bits != upper >> bits or lower & mask not in {0, 1} or upper & mask != mask:
        raise KnxError("knx_free_hierarchy_unsupported")
    prefix = str(lower >> 11)
    if depth == 1:
        prefix += "/" + str((lower >> 8) & 7)
    return lower, upper, prefix


def parse_xml(
    raw: bytes, *, encoding: str = "auto", address_format: str | None = None
) -> ImportDocument:
    content, detected_encoding = decode_input(raw, encoding)
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", content, re.IGNORECASE):
        raise KnxError("knx_xml_unsafe")
    try:
        tree = _BoundedTree()
        root = ET.fromstring(content, parser=ET.XMLParser(target=tree))
    except ET.ParseError:
        raise KnxError("knx_xml_invalid") from None
    if root.tag != TAG + "GroupAddress-Export":
        raise KnxError("knx_xml_format_unsupported")
    records: list[ImportAddress] = []
    ranges: list[tuple[str, dict[str, Any], dict[str, Any], int]] = []
    styles: set[str] = set()
    comments: list[dict[str, Any]] = []

    def parent_prefixes(parents: tuple[dict[str, str], ...]) -> list[str]:
        return [
            str(int(parent["RangeStart"]) >> 11)
            if depth == 0
            else str(int(parent["RangeStart"]) >> 11)
            + "/"
            + str((int(parent["RangeStart"]) >> 8) & 7)
            for depth, parent in enumerate(parents)
        ]

    def walk(element: ET.Element[Any], parents: tuple[dict[str, str], ...] = ()) -> None:
        for position, child in enumerate(element):
            if cast(object, child.tag) is ET.Comment:
                comments.append(
                    {
                        "text": child.text or "",
                        "position": position,
                        "parents": parent_prefixes(parents),
                    }
                )
            elif child.tag == TAG + "GroupRange":
                if len(parents) > 1:
                    raise KnxError("knx_free_hierarchy_unsupported")
                lower, upper, prefix = _range(child, len(parents))
                if parents and not int(parents[-1]["RangeStart"]) <= lower <= upper <= int(
                    parents[-1]["RangeEnd"]
                ):
                    raise KnxError("knx_range_invalid")
                ranges.append(
                    (prefix, _fields(child.attrib, group=True), dict(child.attrib), len(parents))
                )
                if len(ranges) > MAX_GROUPS:
                    raise KnxError("knx_group_limit")
                walk(child, (*parents, dict(child.attrib)))
            elif child.tag == TAG + "GroupAddress":
                if any(cast(object, leaf.tag) is not ET.Comment for leaf in child):
                    raise KnxError("knx_xml_element_unsupported")
                value = child.attrib.get("Address", "")
                fmt = {2: "two_level", 3: "three_level"}.get(len(value.split("/")), "")
                number, original = address(value, fmt)
                for position, comment in enumerate(child):
                    comments.append(
                        {"text": comment.text or "", "position": position, "address": number}
                    )
                if any(
                    not int(parent["RangeStart"]) <= number <= int(parent["RangeEnd"])
                    for parent in parents
                ):
                    raise KnxError("knx_range_invalid")
                styles.add(fmt)
                records.append(
                    ImportAddress(
                        number,
                        fmt,
                        original,
                        _fields(child.attrib),
                        {
                            "attributes": dict(child.attrib),
                            "parents": parent_prefixes(parents),
                        },
                    )
                )
                if len(records) > MAX_ADDRESSES:
                    raise KnxError("knx_address_limit")
            else:
                raise KnxError("knx_xml_element_unsupported")

    walk(root)
    if len(styles) > 1:
        raise KnxError("knx_mixed_format_unsupported")
    fmt = next(iter(styles), address_format or "")
    if fmt not in {"two_level", "three_level"} or address_format not in {None, fmt}:
        raise KnxError("knx_format_invalid")
    if fmt == "two_level" and any(depth == 1 for _, _, _, depth in ranges):
        raise KnxError("knx_free_hierarchy_unsupported")
    groups = tuple(ImportGroup(fmt, prefix, fields, attrs) for prefix, fields, attrs, _ in ranges)
    return ImportDocument(
        tuple(records),
        groups,
        "xml",
        detected_encoding,
        fmt,
        {
            "attributes": dict(root.attrib),
            "comments": comments,
            "outer_comments": tree.outer_comments,
        },
    )
