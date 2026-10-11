"""Experimental correction files preserve source metadata, not ETS import behavior."""

import sqlite3

import pytest

from mcpserver.knx.drafts import DraftStore
from mcpserver.knx.import_repository import ImportRepository
from mcpserver.knx.import_service import select_candidates
from mcpserver.knx.model import KnxError
from mcpserver.knx.store import KnxStore
from mcpserver.knx.xml_adapter import NAMESPACE, parse_xml
from mcpserver.knx.xml_export import XmlCorrectionExport


def setup(tmp_path, content):
    store = KnxStore(tmp_path / "metadata.sqlite3")
    drafts = DraftStore(tmp_path / "drafts.sqlite3", "a" * 64)
    document = parse_xml(content.encode())
    ImportRepository(store).apply("target", 0, document, select_candidates(document), set(), {})
    return store, drafts, XmlCorrectionExport(store, drafts, "target")


def xml(*, style="three_level", comments=""):
    return (
        f'<GroupAddress-Export xmlns="{NAMESPACE}" Custom="Root">{comments}'
        '<GroupRange Name="Main" RangeStart="0" RangeEnd="2047" Custom="Group">'
        f'<GroupAddress Address="{"0/0/1" if style == "three_level" else "0/1"}" '
        'Name="ETS" Description="Old" DPTs="DPST-1-1 DPST-5-1" Central="false" '
        'Unfiltered="true" Security="Automatic" Custom="Address"/>'
        '<GroupAddress Address="0/0/2" Name="Unselected"/>'
        "</GroupRange></GroupAddress-Export>"
    ).replace('Address="0/0/2"', f'Address="{"0/0/2" if style == "three_level" else "0/2"}"')


def request(**fields):
    return {
        "revision": 1,
        "project_binding": "authorized-ui-snapshot",
        "choices": [{"address_id": 1, "fields": fields}],
    }


@pytest.mark.parametrize("style", ["two_level", "three_level"])
def test_selected_xml_roundtrip_and_corrections_preserve_attributes(tmp_path, style):
    store, _, service = setup(tmp_path, xml(style=style))
    original = store.export("target", 0)
    preview = service.preview(
        request(name="Synthetic & <correction> Ä", description="Line 1\nLine 2")
    )
    result = service.download({**preview, "confirmed_experimental": True})
    parsed = parse_xml(result["content"].encode())
    assert len(parsed.addresses) == 1
    attrs = parsed.addresses[0].source["attributes"]
    assert attrs["Name"] == "Synthetic & <correction> Ä"
    assert attrs["Description"] == "Line 1\nLine 2"
    assert attrs["DPTs"] == "DPST-1-1 DPST-5-1"
    assert attrs["Central"] == "false" and attrs["Unfiltered"] == "true"
    assert attrs["Security"] == "Automatic" and attrs["Custom"] == "Address"
    assert parsed.groups[0].source["Custom"] == "Group"
    assert parsed.source["attributes"]["Custom"] == "Root"
    assert parsed.address_format == style
    assert store.export("target", 0) == original
    assert service.preview(request())["sha256"] == service.preview(request())["sha256"]


def test_confirmations_revisions_and_session_are_bound(tmp_path):
    store, drafts, service = setup(tmp_path, xml())
    preview = service.preview(request(name="Confirmed"))
    with pytest.raises(KnxError, match="knx_export_confirmation_required"):
        service.download(preview)
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        service.download({**preview, "confirmed_experimental": True, "project_binding": "changed"})
    other = XmlCorrectionExport(store, DraftStore(drafts.path, "b" * 64), "target")
    with pytest.raises(KnxError, match="knx_draft_expired"):
        other.download({**preview, "confirmed_experimental": True})
    store.put(
        "target",
        1,
        {"address": "0/0/3", "address_format": "three_level", "fields": {"name": "Manual"}},
    )
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        service.download({**preview, "confirmed_experimental": True})


@pytest.mark.parametrize("fields", [{"description": ""}, {"name": ""}, {"dpts": ["1.001"]}])
def test_empty_descriptions_and_non_correction_fields_are_rejected(tmp_path, fields):
    _, _, service = setup(tmp_path, xml())
    with pytest.raises(KnxError):
        service.preview(request(**fields))


def test_unknown_addresses_comments_and_legacy_group_provenance_block_export(tmp_path):
    store, _, service = setup(tmp_path, xml())
    payload = request(name="Changed")
    payload["choices"][0]["address_id"] = 3
    with pytest.raises(KnxError, match="knx_export_source_unavailable"):
        service.preview(payload)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE import_groups SET source='{}'")
    with pytest.raises(KnxError, match="knx_export_source_unavailable"):
        service.preview(request(name="Changed"))
    _, _, commented = setup(
        tmp_path / "comments", xml().replace("</GroupRange>", "<!--positioned--></GroupRange>")
    )
    with pytest.raises(KnxError, match="knx_export_source_unavailable"):
        commented.preview(request(name="Changed"))


def test_leading_document_comments_are_preserved(tmp_path):
    _, _, service = setup(tmp_path, xml(comments="<!--first--><!--second-->"))
    preview = service.preview(request())
    output = service.download({**preview, "confirmed_experimental": True})
    parsed = parse_xml(output["content"].encode())
    assert parsed.source["comments"] == [
        {"text": "first", "position": 0, "parents": []},
        {"text": "second", "position": 1, "parents": []},
    ]


def test_mixed_import_provenance_is_blocked_until_selected_source_is_current(tmp_path):
    store, _, service = setup(tmp_path, xml())
    document = parse_xml(xml().replace('Address="0/0/1"', 'Address="0/0/3"').encode())
    ImportRepository(store).apply("target", 1, document, select_candidates(document), set(), {})
    with pytest.raises(KnxError, match="knx_export_source_unavailable"):
        service.preview({**request(name="Explicit"), "revision": 2})
    current = {**request(name="Explicit"), "revision": 2}
    current["choices"][0]["address_id"] = 3
    assert service.preview(current)["rows"][0]["address_id"] == 3


def test_selection_limits_duplicates_and_boolean_revision_are_rejected(tmp_path):
    _, _, service = setup(tmp_path, xml())
    for choices in ([], request()["choices"] * 2, request()["choices"] * 51):
        with pytest.raises(KnxError, match="knx_export_selection_invalid"):
            service.preview({**request(), "choices": choices})
    preview = service.preview(request())
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        service.download({**preview, "revision": True, "confirmed_experimental": True})


def test_export_draft_purpose_cannot_replace_or_consume_import(tmp_path):
    _, drafts, service = setup(tmp_path, xml())
    import_id = drafts.create("target", 1, xml().encode(), {})
    preview = service.preview(request())
    assert drafts.load(import_id, "target", 1)[0] == xml().encode()
    with pytest.raises(KnxError, match="knx_draft_invalid"):
        service.download({**preview, "draft_id": import_id, "confirmed_experimental": True})
    drafts.discard_xml_export()
    assert drafts.load(import_id, "target", 1)[0] == xml().encode()
