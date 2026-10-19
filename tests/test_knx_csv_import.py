"""Synthetic ETS CSV adapters share XML identity, metadata and import contracts."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from mcpserver.knx.catalog_service import CatalogService
from mcpserver.knx.csv_adapter import parse_csv
from mcpserver.knx.drafts import DraftStore
from mcpserver.knx.import_repository import ImportRepository
from mcpserver.knx.import_service import select_candidates
from mcpserver.knx.model import KnxError
from mcpserver.knx.store import KnxStore
from mcpserver.knx.xml_adapter import NAMESPACE, parse_xml

EXTRA = ["Central", "Unfiltered", "Description", "DatapointType", "Security"]


def document(rows: list[list[str]], layout: str = "3/1", *, newline: str = "\r\n") -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter="\t", lineterminator=newline)
    writer.writerow(
        [
            "Main",
            "Middle",
            "Sub",
            *(["Address"] if layout == "3/1" else ["Main", "Middle", "Sub"]),
            *EXTRA,
        ]
    )
    writer.writerows(rows)
    return stream.getvalue().encode()


def rows(layout: str = "3/1") -> list[list[str]]:
    if layout == "3/1":
        prefixes = [
            ["Main", "", "", "1/-/-"],
            ["", "Middle", "", "1/2/-"],
            ["", "", "Endpoint", "1/2/3"],
        ]
    else:
        prefixes = [
            ["Main", "", "", "1", "", ""],
            ["", "Middle", "", "1", "2", ""],
            ["", "", "Endpoint", "1", "2", "3"],
        ]
    return [
        prefixes[0] + ["", "", "", "", ""],
        prefixes[1] + ["", "", "Group", "", ""],
        prefixes[2] + ["false", "true", "Description", "DPST-1-1,DPST-5-1", "Auto"],
    ]


@pytest.mark.parametrize("layout", ["3/1", "3/3"])
@pytest.mark.parametrize("newline", ["\r\n", "\n"])
def test_csv_normalizes_like_xml_without_inventing_optional_values(
    layout: str, newline: str
) -> None:
    parsed = parse_csv(document(rows(layout), layout, newline=newline))
    xml = parse_xml(
        (
            f'<GroupAddress-Export xmlns="{NAMESPACE}">'
            '<GroupRange Name="Main" RangeStart="2048" RangeEnd="4095">'
            '<GroupRange Name="Middle" Description="Group" RangeStart="2560" RangeEnd="2815">'
            '<GroupAddress Name="Endpoint" Address="1/2/3" Description="Description" '
            'Central="false" '
            'Unfiltered="true" DPTs="DPST-1-1,DPST-5-1" Security="Auto"/>'
            "</GroupRange></GroupRange></GroupAddress-Export>"
        ).encode()
    )
    assert [(r.number, r.original, r.fields) for r in parsed.addresses] == [
        (r.number, r.original, r.fields) for r in xml.addresses
    ]
    assert [(r.prefix, r.fields) for r in parsed.groups] == [
        (r.prefix, r.fields) for r in xml.groups
    ]
    assert parsed.addresses[0].source["parents"] == ["1", "1/2"]
    assert parsed.file_format == "csv" and parsed.source["layout"] == layout
    assert parsed.groups[0].fields == {"name": "Main"}


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp1252"])
@pytest.mark.parametrize("layout", ["3/1", "3/3"])
def test_quotes_tabs_multiline_and_encoding_are_lossless(encoding: str, layout: str) -> None:
    values = rows(layout)
    values[2][2] = 'Änderung "quoted"\tText'
    values[2][-3] = 'Line one\r\nLine "two"; comma, tab\tEnd'
    raw = document(values, layout).decode().encode(encoding)
    parsed = parse_csv(raw)
    assert parsed.encoding == ("windows-1252" if encoding == "cp1252" else "utf-8")
    assert parsed.addresses[0].fields["name"] == values[2][2]
    assert parsed.addresses[0].fields["description"] == values[2][-3]
    if encoding == "cp1252":
        with pytest.raises(KnxError, match="knx_encoding_invalid"):
            parse_csv(raw, encoding="utf-8")


@pytest.mark.parametrize("layout", ["3/1", "3/3"])
def test_two_level_and_partial_export_use_explicit_address_components(layout: str) -> None:
    raw = document(
        [
            [
                "",
                "",
                "Two level",
                *(["31/2047"] if layout == "3/1" else ["31", "", "2047"]),
                "",
                "",
                "",
                "",
                "",
            ]
        ],
        layout,
    )
    parsed = parse_csv(raw)
    assert parsed.address_format == "two_level"
    assert parsed.addresses[0].number == 65535 and parsed.addresses[0].original == "31/2047"
    assert parsed.addresses[0].source["parents"] == []
    with pytest.raises(KnxError, match="knx_format_invalid"):
        parse_csv(raw, address_format="three_level")


@pytest.mark.parametrize(
    "mutation",
    [
        "separator",
        "legacy",
        "missing_header",
        "reordered_duplicate",
        "extra",
        "row_width",
        "both_names",
        "bad_flag",
        "unsafe_name",
        "unclosed_quote",
    ],
)
def test_unsupported_or_invalid_csv_is_rejected(mutation: str) -> None:
    raw = document(rows("3/3"), "3/3")
    if mutation == "separator":
        raw = raw.replace(b"\t", b";")
    elif mutation == "legacy":
        raw = b"Main\tMiddle\tSub\tAddress\nMain\t\t\t1/-/-\n"
    elif mutation == "missing_header":
        raw = raw.split(b"\r\n", 1)[1]
    elif mutation == "reordered_duplicate":
        raw = raw.replace(b"Main\tMiddle\tSub\tMain", b"Main\tMiddle\tSub\tMiddle", 1)
    elif mutation == "extra":
        raw = raw.replace(b"Security", b"Unknown\tSecurity", 1)
    elif mutation == "row_width":
        raw += b"wrong\twidth\n"
    elif mutation == "both_names":
        raw = document([["Main", "Middle", "", "1", "2", "", "", "", "", "", ""]], "3/3")
    elif mutation == "bad_flag":
        raw = raw.replace(b"false", b"False")
    elif mutation == "unsafe_name":
        raw = raw.replace(b"Endpoint", b"bad\x00name")
    else:
        raw += b'\t\t"unclosed'
    with pytest.raises(KnxError):
        parse_csv(raw)


def test_mixed_styles_limits_and_groups_only_do_not_guess() -> None:
    mixed = [*rows(), ["", "", "Two", "1/2047", "", "", "", "", ""]]
    with pytest.raises(KnxError, match="knx_mixed_format_unsupported"):
        parse_csv(document(mixed))
    long = rows()
    long[2][2] = "x" * 256
    with pytest.raises(KnxError, match="knx_field_invalid"):
        parse_csv(document(long))
    long = rows()
    long[2][-2] = ",".join(f"DPST-1-{i}" for i in range(17))
    with pytest.raises(KnxError, match="knx_dpts_invalid"):
        parse_csv(document(long))
    with pytest.raises(KnxError, match="knx_csv_structure_limit"):
        parse_csv(document(rows()) + b"\t" * (64 * 1024 + 1))
    raw = document([["Main", "", "", "1", "", "", "", "", "", "", ""]], "3/3")
    with pytest.raises(KnxError, match="knx_format_invalid"):
        parse_csv(raw)
    assert parse_csv(raw, address_format="two_level").groups[0].address_format == "two_level"


def test_xml_csv_reimport_preserves_overrides_and_has_no_artificial_changes(tmp_path: Path) -> None:
    store = KnxStore(tmp_path / "metadata.sqlite3")
    service = CatalogService(
        ImportRepository(store), DraftStore(tmp_path / "drafts.sqlite3", "a" * 64), "target", []
    )
    first = service.create(
        document(rows()), encoding="auto", complete_export=False, file_format="auto"
    )
    assert first["file_format"] == "csv" and first["layout"] == "3/1"
    assert store.page("target")["total"] == 0
    service.apply(first["draft_id"], first["preview_token"])
    store.put(
        "target",
        1,
        {"address_format": "three_level", "address": "1/2/3", "fields": {"description": "Local"}},
    )
    second = service.create(
        document(rows("3/3"), "3/3"), encoding="auto", complete_export=False, file_format="csv"
    )
    assert second["updates"] == 0 and second["additions"] == 0
    service.apply(second["draft_id"], second["preview_token"])
    row = store.page("target")["items"][0]
    assert row["overrides"] == {"description": "Local"}
    assert row["effective"]["description"] == "Local" and row["import_info"]["file_format"] == "csv"
    duplicated = document([*rows(), rows()[2]])
    assert select_candidates(parse_csv(duplicated)).merged_duplicates == 1
    changed = rows()[2]
    changed[2] = "Different"
    selection = select_candidates(parse_csv(document([*rows(), changed])))
    assert len(selection.conflicts) == 1
