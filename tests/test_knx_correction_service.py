"""Proposal planning preserves source separation and existing export previews."""

import json

import pytest
from test_knx_project_comparison import project_view
from test_knx_xml_export import request, setup, xml

from mcpserver.config import PluginConfig
from mcpserver.knx.catalog import labels_revision
from mcpserver.knx.correction_drafts import CorrectionDraftStore
from mcpserver.knx.correction_service import CorrectionService
from mcpserver.knx.model import KnxError
from mcpserver.knx.store import KnxStore


def change(*, destination="local_metadata", address="1/2/3", **extra):
    return {
        "destination": destination,
        "kind": "address",
        "address_format": "three_level",
        "address": address,
        "field": "name",
        "operation": "set",
        "value": "Additional local name",
        **extra,
    }


def service(tmp_path):
    store = KnxStore(tmp_path / "metadata.sqlite3")
    store.put(
        "target",
        0,
        {"address": "1/2/3", "address_format": "three_level", "fields": {"name": "Local"}},
    )
    with store.connection() as db:
        db.execute("UPDATE addresses SET imported=?", (json.dumps({"name": "ETS"}),))
        db.commit()
    drafts = CorrectionDraftStore(tmp_path / "drafts.sqlite3", "a" * 64)
    return CorrectionService(store, drafts), PluginConfig()


def test_plan_separates_sources_and_never_changes_catalog(tmp_path):
    planner, config = service(tmp_path)
    before = planner.store.export("target")
    result = planner.plan(config, "target", 1, labels_revision(config, "target"), [change()])
    assert result["changes"][0]["sources"] == {
        "imported": {"name": "ETS"},
        "manual": {"name": "Local"},
    }
    assert result["changes"][0]["decision"] == "proposed"
    assert result["project_binding"] is None
    assert planner.store.export("target") == before
    assert planner.drafts.list_corrections("target") == []


def test_explicit_project_selection_requires_matching_fresh_source(tmp_path):
    planner, config = service(tmp_path)
    selected = change(project_object_id="p:2", value="Primary B")
    arguments = (config, "target", 1, labels_revision(config, "target"), [selected])
    with pytest.raises(KnxError, match="knx_project_evidence_required"):
        planner.plan(*arguments)
    query = project_view()
    planned = planner.plan(*arguments, query=query)
    assert len(planned["project_binding"]) == 64
    # All other project names remain outside the saved proposal.
    assert "Primary A" not in repr(planned)
    for changed in (
        change(project_object_id="p:2", value="Primary A"),
        change(project_object_id="p:1", address="1/2/4", value="Primary A"),
        change(project_object_id="missing", value="Primary B"),
    ):
        with pytest.raises(KnxError, match="knx_project_evidence_changed"):
            planner.plan(
                config, "target", 1, labels_revision(config, "target"), [changed], query=query
            )


def test_missing_empty_and_removed_override_remain_separate(tmp_path):
    planner, config = service(tmp_path)
    description = change(field="description", value="")
    planned = planner.plan(config, "target", 1, labels_revision(config, "target"), [description])
    row = planned["changes"][0]
    assert row["sources"] == {"imported": {}, "manual": {}}
    assert row["value"] == ""
    removal = change(operation="remove_override")
    removal.pop("value")
    removed = planner.plan(config, "target", 1, labels_revision(config, "target"), [removal])
    assert "value" not in removed["changes"][0]


def test_stale_draft_stays_readable_without_inheriting_project_authority(tmp_path):
    planner, config = service(tmp_path)
    query = project_view()
    plan = planner.plan(
        config,
        "target",
        1,
        labels_revision(config, "target"),
        [change(project_object_id="p:2", value="Primary B")],
        query=query,
    )
    created = planner.drafts.create_correction(
        "target",
        plan["catalog_revision"],
        plan["manual_revision"],
        plan["changes"],
        project_binding=plan["project_binding"],
    )
    assert planner.inspect(created["draft_id"], config, "target")["project_status"] == "not_checked"
    assert (
        planner.inspect(created["draft_id"], config, "target", query=query)["project_status"]
        == "current"
    )
    different = project_view(b'<P><C Type="EIBextactor" Title="Different" EibAddr="1/2/3"/></P>')
    # Real query stand identities change with content; this fixture fixes identity,
    # so adjust its immutable stand identity to model a genuinely new stand.
    from dataclasses import replace

    different = replace(
        different,
        view=replace(
            different.view, snapshot=replace(different.view.snapshot, content_identity="other")
        ),
    )
    assert (
        planner.inspect(created["draft_id"], config, "target", query=different)["project_status"]
        == "changed"
    )
    planner.store.put(
        "target",
        1,
        {"address": "1/2/3", "address_format": "three_level", "fields": {"name": "Changed"}},
    )
    inspected = planner.inspect(created["draft_id"], config, "target")
    assert inspected["catalog_stale"] and inspected["changes"] == plan["changes"]
    assert inspected["applies_changes"] is False and inspected["exports_file"] is False


def test_export_eligibility_uses_serializer_without_evicting_existing_preview(tmp_path):
    store, old_drafts, exporter = setup(tmp_path, xml())
    previous = exporter.preview(request(name="Existing preview"))
    planner = CorrectionService(store, CorrectionDraftStore(old_drafts.path, "a" * 64))
    config = PluginConfig()
    planned = planner.plan(
        config,
        "target",
        1,
        labels_revision(config, "target"),
        [change(destination="ets_export", address="0/0/1", value="Proposal")],
    )
    assert planned["changes"][0]["sources"]["imported"]["name"] == "ETS"
    old_drafts.load(previous["draft_id"], "target", 1)
    assert exporter.download({**previous, "confirmed_experimental": True})["content"]
    with store.connection() as db:
        db.execute("UPDATE ets_sources SET source=json_set(source,'$.file_format','csv')")
        db.commit()
    with pytest.raises(KnxError, match="knx_export_source_unavailable"):
        planner.plan(
            config,
            "target",
            1,
            labels_revision(config, "target"),
            [change(destination="ets_export", address="0/0/1")],
        )


def test_labels_and_catalog_revisions_are_both_required(tmp_path):
    planner, config = service(tmp_path)
    for revision, manual in [
        (0, labels_revision(config, "target")),
        (1, "b" * 64),
        (True, labels_revision(config, "target")),
    ]:
        with pytest.raises(KnxError, match="knx_revision_conflict"):
            planner.plan(config, "target", revision, manual, [change()])


def correction_fixture(tmp_path):
    planner, config = service(tmp_path)
    plan = planner.plan(
        config,
        "target",
        1,
        labels_revision(config, "target"),
        [change(), change(field="description", value="original proposal")],
    )
    draft = planner.drafts.create_correction("target", 1, plan["manual_revision"], plan["changes"])
    return planner, config, draft


def test_review_records_selected_decisions_and_reconciles_exact_operation(tmp_path):
    planner, config, draft = correction_fixture(tmp_path)
    before = planner.store.export("target")
    decisions = [{"change_id": draft["changes"][0]["change_id"], "decision": "accepted"}]
    args = (draft["draft_id"], config, "target", 1, 1, draft["manual_revision"], decisions)
    assert planner.review(*args, request_id="a" * 32) == 2
    assert planner.review(*args, request_id="a" * 32) == 2
    current = planner.drafts.inspect_correction(draft["draft_id"], "target")
    assert [row["decision"] for row in current["changes"]] == ["accepted", "proposed"]
    assert current["expires_at"] == draft["expires_at"]
    assert planner.store.export("target") == before
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        planner.review(*args, request_id="b" * 32)
    decisions[0]["decision"] = "rejected"
    with pytest.raises(KnxError, match="knx_correction_request_conflict"):
        planner.review(*args, request_id="a" * 32)


@pytest.mark.parametrize(
    "decisions",
    [
        [],
        [{"change_id": "f" * 24, "decision": "accepted"}],
        [{"change_id": "f" * 24, "decision": "accepted", "value": "injection"}],
        [{"change_id": "f" * 24, "decision": "apply"}],
        [{"change_id": "f" * 24, "decision": "accepted"}] * 2,
    ],
)
def test_review_rejects_unknown_duplicate_or_arbitrary_selections(tmp_path, decisions):
    planner, config, draft = correction_fixture(tmp_path)
    with pytest.raises(KnxError, match="knx_correction_invalid"):
        planner.review(
            draft["draft_id"],
            config,
            "target",
            1,
            1,
            draft["manual_revision"],
            decisions,
            request_id="a" * 32,
        )
    assert planner.drafts.inspect_correction(draft["draft_id"], "target")["draft_revision"] == 1


def test_edit_resets_only_affected_decision_and_preserves_sources_and_expiry(tmp_path):
    planner, config, draft = correction_fixture(tmp_path)
    before = planner.store.export("target")
    decisions = [
        {"change_id": row["change_id"], "decision": "accepted"} for row in draft["changes"]
    ]
    planner.review(
        draft["draft_id"],
        config,
        "target",
        1,
        1,
        draft["manual_revision"],
        decisions,
        request_id="a" * 32,
    )
    change_id = draft["changes"][0]["change_id"]
    args = (
        draft["draft_id"],
        config,
        "target",
        2,
        1,
        draft["manual_revision"],
        change_id,
        {"operation": "set", "value": "<script>literal user selection</script>"},
    )
    assert planner.edit(*args, request_id="b" * 32) == 3
    assert planner.edit(*args, request_id="b" * 32) == 3
    current = planner.drafts.inspect_correction(draft["draft_id"], "target")
    assert [row["decision"] for row in current["changes"]] == ["proposed", "accepted"]
    assert current["changes"][0]["sources"] == draft["changes"][0]["sources"]
    assert current["changes"][0]["change_id"] == change_id
    assert current["expires_at"] == draft["expires_at"]
    assert planner.store.export("target") == before


def test_edit_missing_empty_and_removal_are_distinct(tmp_path):
    planner, config, draft = correction_fixture(tmp_path)
    change_id = draft["changes"][1]["change_id"]
    args = (draft["draft_id"], config, "target")
    planner.edit(
        *args,
        1,
        1,
        draft["manual_revision"],
        change_id,
        {"operation": "set", "value": ""},
        request_id="a" * 32,
    )
    assert (
        planner.drafts.inspect_correction(draft["draft_id"], "target")["changes"][1]["value"] == ""
    )
    planner.edit(
        *args,
        2,
        1,
        draft["manual_revision"],
        change_id,
        {"operation": "remove_override"},
        request_id="b" * 32,
    )
    assert (
        "value" not in planner.drafts.inspect_correction(draft["draft_id"], "target")["changes"][1]
    )


def test_changed_catalog_blocks_decisions_and_edits(tmp_path):
    planner, config, draft = correction_fixture(tmp_path)
    planner.store.put(
        "target",
        1,
        {"address": "1/2/4", "address_format": "three_level", "fields": {"name": "concurrent"}},
    )
    args = (draft["draft_id"], config, "target", 1, 1, draft["manual_revision"])
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        planner.review(
            *args,
            [{"change_id": draft["changes"][0]["change_id"], "decision": "accepted"}],
            request_id="a" * 32,
        )
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        planner.edit(
            *args,
            draft["changes"][0]["change_id"],
            {"operation": "set", "value": "new"},
            request_id="b" * 32,
        )
