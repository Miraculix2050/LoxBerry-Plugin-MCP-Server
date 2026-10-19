"""Strict modern ETS tab-separated CSV, with positional 3/1 and 3/3 headers."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from typing import Any

from .import_model import MAX_GROUPS, ImportAddress, ImportDocument, ImportGroup
from .input_encoding import decode_input
from .model import MAX_ADDRESSES, KnxError, address, text
from .source_fields import source_fields

OPTIONAL_COLUMNS = frozenset({"Central", "Unfiltered", "Description", "DatapointType", "Security"})


def _header(columns: list[str]) -> tuple[str, int]:
    if not 6 <= len(columns) <= 11:
        raise KnxError("knx_csv_header_unsupported")
    if columns[:4] == ["Main", "Middle", "Sub", "Address"]:
        layout, width = "3/1", 4
    elif columns[:6] == ["Main", "Middle", "Sub", "Main", "Middle", "Sub"]:
        layout, width = "3/3", 6
    else:
        raise KnxError("knx_csv_header_unsupported")
    additional = columns[width:]
    # These modern columns distinguish the supported export from the legacy
    # compatibility layout. Their cells may be empty; no defaults are invented.
    if (
        not {"Description", "DatapointType"} <= set(additional)
        or not set(additional) <= OPTIONAL_COLUMNS
        or len(set(additional)) != len(additional)
    ):
        raise KnxError("knx_csv_header_unsupported")
    return layout, width


def _identity(row: list[str], layout: str, name_column: int) -> tuple[str | None, str, bool]:
    """Return style, full address/prefix and whether this is an address row."""
    if layout == "3/1":
        parts = row[3].split("/")
        if len(parts) not in {2, 3}:
            raise KnxError("knx_csv_row_invalid")
        fmt = "two_level" if len(parts) == 2 else "three_level"
        group = name_column != 2
        depth = 1 if name_column == 0 else 2
        if group:
            if depth >= len(parts) or any(value != "-" for value in parts[depth:]):
                raise KnxError("knx_csv_row_invalid")
            prefix = "/".join(parts[:depth])
            address(prefix + ("/0/0" if depth == 1 and fmt == "three_level" else "/0"), fmt)
            return fmt, prefix, False
        _, original = address(row[3], fmt)
        return fmt, original, True
    main, middle, sub = row[3:6]
    if name_column == 0:
        if middle or sub:
            raise KnxError("knx_csv_row_invalid")
        address(main + "/0/0", "three_level")
        return None, main, False
    if name_column == 1:
        if sub:
            raise KnxError("knx_csv_row_invalid")
        address(main + "/" + middle + "/0", "three_level")
        return "three_level", main + "/" + middle, False
    if middle and sub:
        fmt, value = "three_level", "/".join((main, middle, sub))
    elif bool(middle) != bool(sub):
        # With exactly one numeric subordinate component and a name in the Sub
        # name column, this is an explicit two-level address, not a middle group.
        fmt, value = "two_level", main + "/" + (sub or middle)
    else:
        raise KnxError("knx_csv_row_invalid")
    _, original = address(value, fmt)
    return fmt, original, True


def _lines(content: str) -> Iterator[str]:
    stream = io.StringIO(content, newline="")
    while line := stream.readline(64 * 1024 + 1):
        if len(line) > 64 * 1024:
            raise KnxError("knx_csv_structure_limit")
        yield line


def parse_csv(
    raw: bytes, *, encoding: str = "auto", address_format: str | None = None
) -> ImportDocument:
    if address_format not in (None, "two_level", "three_level"):
        raise KnxError("knx_format_invalid")
    content, detected_encoding = decode_input(raw, encoding)
    reader = csv.reader(_lines(content), delimiter="\t", strict=True)
    addresses: list[ImportAddress] = []
    groups: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    styles: set[str] = set()
    try:
        columns = next(reader, [])
        layout, width = _header(columns)
        for row in reader:
            if not row or all(value == "" for value in row):
                continue
            if len(row) != len(columns):
                raise KnxError("knx_csv_row_invalid")
            for value in row:
                text(value, 4096)
            names = [index for index in range(3) if row[index] != ""]
            if len(names) != 1:
                raise KnxError("knx_csv_row_invalid")
            name_column = names[0]
            fmt, value, is_address = _identity(row, layout, name_column)
            if fmt is not None:
                styles.add(fmt)
            attrs = {"Name": row[name_column]}
            for column, cell in zip(columns[width:], row[width:], strict=True):
                if cell != "":
                    attrs["DPTs" if column == "DatapointType" else column] = cell
            # Validate supplied flags and DPT counts on group rows as well,
            # although only names/descriptions become effective group metadata.
            normalized = source_fields(attrs)
            if is_address:
                assert fmt is not None
                number, original = address(value, fmt)
                attrs["Address"] = original
                addresses.append(
                    ImportAddress(
                        number, fmt, original, normalized, {"attributes": attrs, "parents": []}
                    )
                )
                if len(addresses) > MAX_ADDRESSES:
                    raise KnxError("knx_address_limit")
            else:
                groups.append((value, source_fields(attrs, group=True), dict(attrs)))
                if len(groups) > MAX_GROUPS:
                    raise KnxError("knx_group_limit")
            if len(styles) > 1:
                raise KnxError("knx_mixed_format_unsupported")
    except csv.Error:
        raise KnxError("knx_csv_invalid") from None
    fmt = next(iter(styles), address_format or "")
    if fmt not in {"two_level", "three_level"} or address_format not in (None, fmt):
        raise KnxError("knx_format_invalid")
    known_groups = {prefix for prefix, _, _ in groups}
    for record in addresses:
        parts = record.original.split("/")
        record.source["parents"] = [
            "/".join(parts[:depth])
            for depth in range(1, len(parts))
            if "/".join(parts[:depth]) in known_groups
        ]
    return ImportDocument(
        tuple(addresses),
        tuple(ImportGroup(fmt, prefix, fields, attrs) for prefix, fields, attrs in groups),
        "csv",
        detected_encoding,
        fmt,
        {"layout": layout, "columns": columns},
    )
