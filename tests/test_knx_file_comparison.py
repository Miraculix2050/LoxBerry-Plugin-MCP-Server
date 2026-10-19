"""Structured file comparisons preserve absence, manual sources and draft isolation."""

import base64
import csv
import io
from dataclasses import replace

import pytest

from mcpserver.admin import AdminError
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.knx.admin import dispatch_knx
from mcpserver.knx.catalog_service import CatalogService
from mcpserver.knx.drafts import DraftStore
from mcpserver.knx.file_comparison import FileComparison
from mcpserver.knx.import_repository import ImportRepository
from mcpserver.knx.import_service import select_candidates
from mcpserver.knx.model import KnxError
from mcpserver.knx.store import KnxStore
from mcpserver.knx.xml_adapter import NAMESPACE, parse_xml


def xml(rows):
    return f'<GroupAddress-Export xmlns="{NAMESPACE}">{rows}</GroupAddress-Export>'.encode()


def setup(tmp_path):
    store = KnxStore(tmp_path / "metadata.sqlite3")
    drafts = DraftStore(tmp_path / "drafts.sqlite3", "a" * 64)
    return store, drafts, FileComparison(store, drafts, "target", [])


def load(service, raw, side, *, complete=False, fmt=None):
    return service.load(
        raw,
        side,
        {
            "encoding": "auto",
            "file_format": "auto",
            "address_format": fmt,
            "complete_export": complete,
        },
    )


def compare(service, left, right, offset=0):
    return service.page(
        {
            "left_id": left["draft_id"] if isinstance(left, dict) else left,
            "right_id": right["draft_id"],
            "revision": right["revision"],
            "taxonomy_revision": right["taxonomy_revision"],
            "offset": offset,
        }
    )


def test_xml_csv_equivalence_dpt_sets_and_order(tmp_path):
    _, _, service = setup(tmp_path)
    left = load(
        service,
        xml(
            '<GroupRange RangeStart="2048" RangeEnd="4095" Name="Main">'
            '<GroupAddress Address="1/2/3" Name="Same" Description="Details" '
            'DPTs="DPST-1-1 DPST-5-1"/></GroupRange>'
        ),
        "left",
    )
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter="\t")
    writer.writerow(["Main", "Middle", "Sub", "Address", "Description", "DatapointType"])
    writer.writerow(["", "", "Same", "1/2/3", "Details", "5.001,1.001,1.001"])
    writer.writerow(["Main", "", "", "1/-/-", "", ""])
    right = load(service, stream.getvalue().encode(), "right")
    result = compare(service, left, right)
    assert result["total"] == 0 and result["rows"] == []
    assert result["counts"]["address"]["unchanged"] == 1
    assert result["counts"]["group"]["unchanged"] == 1


def test_numeric_style_equivalence_without_group_reassignment(tmp_path):
    _, _, service = setup(tmp_path)
    left = load(service, xml('<GroupAddress Address="1/2/3" Name="Same"/>'), "left")
    right = load(
        service, xml('<GroupAddress Address="1/515" Name="Same"/>'), "right", fmt="two_level"
    )
    assert compare(service, left, right)["total"] == 0


def test_added_removed_changed_unknown_empty_false_and_partial_input(tmp_path):
    _, _, service = setup(tmp_path)
    left = load(
        service,
        xml('<GroupAddress Address="0/0/1" Name="One"/><GroupAddress Address="0/0/2" Name="Two"/>'),
        "left",
        complete=True,
    )
    right = load(
        service,
        xml(
            '<GroupAddress Address="0/0/2" Name="Two" Description="" Central="false"/>'
            '<GroupAddress Address="0/0/3" Name="Three"/>'
        ),
        "right",
    )
    result = compare(service, left, right)
    assert [row["change"] for row in result["rows"]] == ["removed", "changed", "added"]
    changed = result["rows"][1]
    assert changed["changed_fields"] == ["central", "description"]
    assert "description" not in changed["before"]
    assert changed["after"]["description"] == "" and changed["after"]["central"] is False
    assert result["left"]["completeness"] == "complete"
    assert result["right"]["completeness"] == "partial"
    assert result["absence_scope"] == "selected_inputs_only"
    assert result["catalog_changed"] is False


def test_catalog_overrides_and_manual_only_records_are_separate(tmp_path):
    store, _, service = setup(tmp_path)
    document = parse_xml(xml('<GroupAddress Address="0/0/1" Name="ETS"/>'))
    ImportRepository(store).apply(
        "target", 0, document, select_candidates(document), set(), {"complete_export": True}
    )
    store.put(
        "target",
        1,
        {"address": "0/0/1", "address_format": "three_level", "fields": {"description": "Manual"}},
    )
    store.put(
        "target",
        2,
        {"address": "0/0/2", "address_format": "three_level", "fields": {"name": "Manual only"}},
    )
    right = load(service, xml('<GroupAddress Address="0/0/1" Name="ETS"/>'), "right")
    result = compare(service, "current", right)
    assert result["counts"]["address"]["removed"] == 0
    assert result["counts"]["address"]["manual"] == 2
    assert [row["manual"] for row in result["rows"]] == [
        {"description": "Manual"},
        {"name": "Manual only"},
    ]
    assert result["rows"][0]["changed_fields"] == []
    assert result["left"]["completeness"] == "unknown"
    assert store.page("target")["revision"] == 3
    assert store.page("target")["items"][0]["imported"]["name"] == "ETS"


def test_group_changes_manual_labels_and_page_bound(tmp_path):
    store, _, service = setup(tmp_path)
    document = parse_xml(
        xml(
            '<GroupRange RangeStart="0" RangeEnd="2047" Name="Old">'
            '<GroupAddress Address="0/0/1" Name="One"/></GroupRange>'
        )
    )
    ImportRepository(store).apply("target", 0, document, select_candidates(document), set(), {})
    service.manual_labels = [{"address_format": "three_level", "prefix": "0", "label": "Local"}]
    right = load(
        service,
        xml(
            '<GroupRange RangeStart="0" RangeEnd="2047" Name="New">'
            + "".join(f'<GroupAddress Address="0/0/{n}" Name="New {n}"/>' for n in range(1, 65))
            + "</GroupRange>"
        ),
        "right",
    )
    first, second = compare(service, "current", right), compare(service, "current", right, 50)
    assert len(first["rows"]) == 50 and first["has_more"]
    assert len(second["rows"]) == 15 and not second["has_more"]
    group = second["rows"][-1]
    assert group["kind"] == "group" and group["changed_fields"] == ["name"]
    assert group["manual"] == {"name": "Local"}
    assert [row["address_id"] for row in first["rows"]] == list(range(1, 51))


def test_draft_purposes_preserve_import_and_cannot_apply_comparison(tmp_path):
    store, drafts, service = setup(tmp_path)
    importer = CatalogService(ImportRepository(store), drafts, "target", [])
    raw = xml('<GroupAddress Address="0/0/1" Name="One"/>')
    original = importer.create(raw, encoding="auto", complete_export=False)
    left, right = load(service, raw, "left"), load(service, raw, "right")
    assert importer.preview(original["draft_id"], {})["addresses"] == 1
    assert compare(service, left, right)["total"] == 0
    with pytest.raises(KnxError, match="knx_draft_invalid"):
        importer.apply(right["draft_id"], "irrelevant")
    drafts.discard(original["draft_id"], slots=("compare_left", "compare_right"))
    assert drafts.load(original["draft_id"], "target", 0)
    drafts.discard(right["draft_id"], slots=("compare_left", "compare_right"))
    with pytest.raises(KnxError, match="knx_draft_expired"):
        compare(service, left, right)
    other = DraftStore(drafts.path, "b" * 64)
    other_id = other.create("target", 0, raw, {}, slot="compare_left")
    drafts.discard_comparison()
    assert drafts.load(original["draft_id"], "target", 0)
    assert other.load(other_id, "target", 0)
    with pytest.raises(KnxError, match="knx_draft_expired"):
        drafts.load(left["draft_id"], "target", 0)


def test_no_history_conflicts_revision_and_session_bounds(tmp_path):
    store, drafts, service = setup(tmp_path)
    raw = xml('<GroupAddress Address="0/0/1" Name="One"/>')
    right = load(service, raw, "right")
    with pytest.raises(KnxError, match="knx_comparison_no_import"):
        compare(service, "current", right)
    with pytest.raises(KnxError, match="knx_comparison_conflicts"):
        load(
            service,
            xml(
                '<GroupAddress Address="0/0/1" Name="One"/>'
                '<GroupAddress Address="0/0/1" Name="Other"/>'
            ),
            "left",
        )
    other = FileComparison(store, DraftStore(drafts.path, "b" * 64), "target", [])
    with pytest.raises(KnxError, match="knx_draft_expired"):
        compare(other, "current", right)
    store.put(
        "target",
        0,
        {"address": "0/0/1", "address_format": "three_level", "fields": {"name": "Manual"}},
    )
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        compare(service, "current", right)
    with pytest.raises(KnxError, match="knx_page_invalid"):
        compare(service, "current", right, -1)


def test_admin_actions_are_target_bound_and_payload_allowlisted(tmp_path, monkeypatch):
    monkeypatch.setenv("LBPDATA", str(tmp_path))
    monkeypatch.setenv("MCPSERVER_KNX_ADMIN_SESSION", "a" * 64)
    config = AtomicConfigStore(tmp_path / "config.json")
    config.save(replace(PluginConfig.defaults(), loxone_endpoint="http://192.168.10.20"))
    page = dispatch_knx("knx_page", {}, config)
    payload = {
        "target": page["target"],
        "file": base64.b64encode(xml('<GroupAddress Address="0/0/1" Name="One"/>')).decode(),
        "side": "right",
    }
    result = dispatch_knx("knx_compare_load", payload, config)
    assert result["target"] == page["target"]
    with pytest.raises(AdminError) as exc:
        dispatch_knx("knx_compare_load", {**payload, "target": "wrong"}, config)
    assert exc.value.code == "knx_target_conflict"
    with pytest.raises(AdminError) as exc:
        dispatch_knx("knx_compare_load", {**payload, "path": "/private"}, config)
    assert exc.value.code == "knx_preview_invalid"


def test_manual_prefix_change_invalidates_comparison_pages_and_drafts(tmp_path):
    store, _, service = setup(tmp_path)
    raw = xml('<GroupAddress Address="0/0/1" Name="Imported"/>')
    document = parse_xml(raw)
    ImportRepository(store).apply("target", 0, document, select_candidates(document), set(), {})
    right = load(service, raw, "right")
    first = compare(service, "current", right)
    service.manual_labels = [{"address_format": "three_level", "prefix": "0/0", "label": "Manual"}]
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        compare(service, "current", right, 50)
    # Updating the page's digest cannot authorize a draft from the old source state.
    right["taxonomy_revision"] = service.manual_revision()
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        compare(service, "current", right)
    fresh = compare(service, "current", load(service, raw, "right"))
    assert fresh["revision"] == first["revision"]
    assert fresh["taxonomy_revision"] != first["taxonomy_revision"]
    assert fresh["counts"]["group"]["manual"] == 1
