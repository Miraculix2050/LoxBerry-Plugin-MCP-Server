from __future__ import annotations

import pytest

from mcpserver.knx.model import KnxError
from mcpserver.knx.xml_adapter import NAMESPACE, parse_xml


def xml(body: str, *, namespace: str = NAMESPACE) -> bytes:
    return f'<GroupAddress-Export xmlns="{namespace}">{body}</GroupAddress-Export>'.encode()


def test_xml_preserves_sources_optional_presence_and_shared_numeric_identity() -> None:
    document = parse_xml(
        xml(
            '<GroupRange Name="Main" RangeStart="2048" RangeEnd="4095">'
            '<GroupRange Name="Middle" RangeStart="2560" RangeEnd="2815">'
            '<GroupAddress Address="1/2/3" Name="Additional &amp; name" Description="" '
            'DPTs="DPST-1-1 DPST-5-1" Central="false" Unfiltered="true" Custom="Keep"/>'
            "</GroupRange></GroupRange>"
        )
    )
    record = document.addresses[0]
    assert record.number == 2563
    assert record.fields == {
        "name": "Additional & name",
        "description": "",
        "dpts": ["DPST-1-1", "DPST-5-1"],
        "central": False,
        "unfiltered": True,
    }
    assert record.source["attributes"]["Custom"] == "Keep"
    assert len(record.source["parents"]) == 2
    assert [group.prefix for group in document.groups] == ["1", "1/2"]
    assert document.encoding == "utf-8"


def test_xml_two_level_partial_export_and_ets_zero_exclusion_ranges() -> None:
    document = parse_xml(
        xml(
            '<GroupRange Name="Main" RangeStart="1" RangeEnd="2047">'
            '<GroupAddress Address="0/259" Name="Two level"/>'
            "</GroupRange>"
        )
    )
    assert document.address_format == "two_level"
    assert document.addresses[0].number == 259
    assert document.addresses[0].fields == {"name": "Two level"}
    assert document.groups[0].prefix == "0"


def test_ets_comments_are_bounded_and_retained_without_duplicating_group_attributes() -> None:
    raw = (
        b"<!--before-->"
        + xml(
            '<GroupRange Name="Main" RangeStart="2048" RangeEnd="4095">'
            '<!--generated group comment--><GroupAddress Address="1/2/3" Name="ETS">'
            "<!--address comment--></GroupAddress></GroupRange>"
        )
        + b"<!--after-->"
    )
    parsed = parse_xml(raw)
    assert parsed.source["outer_comments"] == [
        {"text": "before", "location": "before"},
        {"text": "after", "location": "after"},
    ]
    assert parsed.source["comments"] == [
        {"text": "generated group comment", "position": 0, "parents": ["1"]},
        {"text": "address comment", "position": 0, "address": 2563},
    ]
    with pytest.raises(KnxError, match="knx_xml_structure_limit"):
        parse_xml(
            xml(("<!--" + ("x" * 4096) + "-->") * 17 + '<GroupAddress Address="1/2/3" Name="ETS"/>')
        )


@pytest.mark.parametrize(
    "encoding,bom", [("utf-8", b""), ("utf-8", b"\xef\xbb\xbf"), ("cp1252", b"")]
)
def test_encoding_detection_and_explicit_selection(encoding: str, bom: bytes) -> None:
    raw = xml('<GroupAddress Address="1/2/3" Name="Öffnen"/>').decode().encode(encoding)
    result = parse_xml(bom + raw)
    assert result.addresses[0].fields["name"] == "Öffnen"
    expected = "windows-1252" if encoding == "cp1252" else "utf-8"
    assert result.encoding == expected
    assert parse_xml(raw, encoding=expected).encoding == expected


@pytest.mark.parametrize(
    "raw,code",
    [
        (b'<!DOCTYPE a [<!ENTITY x "bad">]><a/>', "knx_xml_unsafe"),
        (b'<!DOCTYPE a SYSTEM "file:///etc/passwd"><a/>', "knx_xml_unsafe"),
        (xml('<GroupAddress Address="32/0/0" Name="Bad"/>'), "knx_address_invalid"),
        (xml('<GroupAddress Address="1/2/3" Name="Bad" Central="1"/>'), "knx_flag_invalid"),
        (
            xml('<GroupAddress Address="1/2/3" Name="Bad"/>', namespace="legacy"),
            "knx_xml_format_unsupported",
        ),
        (
            xml('<GroupRange Name="Free" RangeStart="123" RangeEnd="456"/>'),
            "knx_free_hierarchy_unsupported",
        ),
        (
            xml(
                '<GroupAddress Address="1/2/3" Name="One"/>'
                '<GroupAddress Address="1/259" Name="Two"/>'
            ),
            "knx_mixed_format_unsupported",
        ),
        (
            xml('<GroupAddress Address="1/2/3" Name="One"><Extra/></GroupAddress>'),
            "knx_xml_element_unsupported",
        ),
        (xml("not whitespace"), "knx_xml_text_unsupported"),
        (b"\xff\xfe\0\0", "knx_encoding_unsupported"),
    ],
)
def test_xml_rejects_unsafe_unsupported_and_invalid_content(raw: bytes, code: str) -> None:
    with pytest.raises(KnxError, match=code):
        parse_xml(raw)


def test_xml_keeps_duplicate_candidates_for_domain_conflict_resolution() -> None:
    document = parse_xml(
        xml('<GroupAddress Address="1/2/3" Name="One"/><GroupAddress Address="1/2/3" Name="Two"/>')
    )
    assert len(document.addresses) == 2
    assert document.addresses[0].number == document.addresses[1].number


def test_xml_enforces_limits_before_unbounded_tree_traversal() -> None:
    with pytest.raises(KnxError, match="knx_field_invalid"):
        parse_xml(xml(f'<GroupAddress Address="1/2/3" Name="{"x" * 256}"/>'))
    with pytest.raises(KnxError, match="knx_xml_structure_limit"):
        parse_xml(
            xml(
                "<GroupRange><GroupRange><GroupRange><GroupAddress/></GroupRange></GroupRange></GroupRange>"
            )
        )
    with pytest.raises(KnxError, match="knx_file_limit"):
        parse_xml(b" " * (16 * 1024 * 1024 + 1))
