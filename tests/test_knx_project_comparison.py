"""Exact address observations stay scoped, bounded and independent of overrides."""

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import mcpserver.loxone.project.ets_comparison as comparison_adapter
import mcpserver.tools as tools
from mcpserver.knx.model import KnxError, address_number
from mcpserver.knx.project_comparison import (
    MAX_COMPARISON_FINDINGS,
    ProjectComparison,
    unpack_observation,
)
from mcpserver.knx.project_metadata import ProjectMetadata
from mcpserver.knx.store import KnxStore
from mcpserver.loxone.project.analysis import ANALYSES, analyze_knx
from mcpserver.loxone.project.ets_compact import filter_observations, selected_counts, selection
from mcpserver.loxone.project.ets_comparison import observe_project, project_page
from mcpserver.loxone.project.graph import ProjectPartSummary, ProjectSnapshot, build_graph
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.models import ProjectError
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.query import ProjectQuery


def catalog(tmp_path):
    store = KnxStore(tmp_path / "metadata.sqlite3")
    for revision, value in enumerate(("1/2/3", "1/2/4", "1/2/5")):
        store.put(
            "target",
            revision,
            {"address": value, "address_format": "three_level", "fields": {"name": "Local"}},
        )
    with store.connection() as db:
        db.execute(
            "UPDATE addresses SET imported=? WHERE address=?", (json.dumps({"name": "ETS"}), 2563)
        )
        db.execute(
            "UPDATE addresses SET imported=?,overrides='{}' WHERE address=?",
            (json.dumps({"name": "Import only"}), 2564),
        )
        db.execute(
            "INSERT INTO import_state VALUES(?,?)",
            (
                "target",
                json.dumps(
                    {
                        "complete_export": False,
                        "imported_at": 1,
                        "document_digest": "a" * 64,
                        "private": "not projected",
                    }
                ),
            ),
        )
        db.commit()
    return store, ProjectComparison(ProjectMetadata(store.path))


def test_address_sets_all_project_names_and_overrides_remain_separate(tmp_path):
    store, comparison = catalog(tmp_path)
    # Two-/three-level and edge variants identify one numeric address.
    number = address_number("1/515:1")
    assert number == address_number("1/2/3:0")
    names = {number: ("ETS", "Other Loxone", "ETS"), 2565: ("Local",), 65535: ()}
    result = comparison.observe("target", 3, names)
    assert result["counts"] == {
        "common": 1,
        "import_only": 1,
        "observed_project_only": 2,
        "name_deviations": 1,
        "name_comparisons_unknown": 0,
        "ambiguous_project_names": 1,
    }
    assert [unpack_observation(row) for row in result["rows"]] == [
        {
            "address_id": 2563,
            "relation": "common",
            "names_differ": True,
            "ambiguous_names": True,
            "name_comparison": "compared",
        },
        {
            "address_id": 2564,
            "relation": "import_only",
            "names_differ": False,
            "ambiguous_names": False,
            "name_comparison": "not_applicable",
        },
        {
            "address_id": 2565,
            "relation": "observed_project_only",
            "names_differ": False,
            "ambiguous_names": False,
            "name_comparison": "not_applicable",
        },
        {
            "address_id": 65535,
            "relation": "observed_project_only",
            "names_differ": False,
            "ambiguous_names": False,
            "name_comparison": "not_applicable",
        },
    ]
    assert result["import_info"]["complete_export"] is False
    assert "private" not in result["import_info"]
    assert names[number] == ("ETS", "Other Loxone", "ETS")
    with store.connection() as db:
        assert json.loads(
            db.execute("SELECT overrides FROM addresses WHERE address=2563").fetchone()[0]
        ) == {"name": "Local"}
    assert not result["truncated"]


def test_revision_target_and_unknown_import_scope(tmp_path):
    _, comparison = catalog(tmp_path)
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        comparison.observe("target", 2, {})
    other = comparison.observe("another-target", 0, {0: ("Project",)})
    assert other["import_info"] == {}
    assert other["counts"]["import_only"] == 0
    assert other["counts"]["observed_project_only"] == 1


def test_import_membership_index_migrates_and_tracks_reimport(tmp_path):
    store, comparison = catalog(tmp_path)
    with store.connection() as db:
        db.execute("DROP INDEX addresses_imported")
        db.commit()
    # Opening an existing schema-v3 database adds the derived index without
    # changing its revision or user records.
    with store.connection() as db:
        assert store.revision(db, "target") == 3
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT address FROM addresses "
            "INDEXED BY addresses_imported WHERE target=? AND imported!='{}' ORDER BY address",
            ("target",),
        ).fetchall()
        assert any("addresses_imported" in item[3] for item in plan)
        assert not any("TEMP B-TREE" in item[3] for item in plan)
        db.execute(
            "UPDATE addresses SET imported='{}' WHERE target=? AND address=?", ("target", 2564)
        )
        db.execute(
            "UPDATE addresses SET imported=? WHERE target=? AND address=?",
            (json.dumps({"name": "New import"}), "target", 2565),
        )
        db.commit()
    result = comparison.observe("target", 3, {})
    assert [unpack_observation(row)["address_id"] for row in result["rows"]] == [2563, 2565]
    assert result["counts"]["import_only"] == 2


def test_missing_catalog_is_not_created_and_maximum_key_set_is_bounded(tmp_path):
    path = tmp_path / "missing.sqlite3"
    comparison = ProjectComparison(ProjectMetadata(path))
    names = dict.fromkeys(range(65536), ())
    result = comparison.observe("target", 0, names)
    assert result["counts"]["observed_project_only"] == 65536
    assert len(result["rows"]) == MAX_COMPARISON_FINDINGS
    assert result["truncated"]
    assert not path.exists()
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        comparison.observe("target", 1, names)


def test_missing_names_and_unicode_are_observations_not_inferred_matches(tmp_path):
    store, comparison = catalog(tmp_path)
    with store.connection() as db:
        db.execute(
            "UPDATE addresses SET imported=? WHERE address=2563",
            (json.dumps({"description": "Unknown name"}),),
        )
        db.commit()
    assert not unpack_observation(comparison.observe("target", 3, {2563: ("Loxone",)})["rows"][0])[
        "names_differ"
    ]
    with store.connection() as db:
        db.execute(
            "UPDATE addresses SET imported=? WHERE address=2563",
            (json.dumps({"name": "Stra\u00dfe"}),),
        )
        db.commit()
    assert unpack_observation(comparison.observe("target", 3, {2563: ("STRASSE",)})["rows"][0])[
        "names_differ"
    ]
    assert not unpack_observation(
        comparison.observe("target", 3, {2563: ("Stra\u00dfe",)})["rows"][0]
    )["names_differ"]


@pytest.mark.parametrize("number", [-1, 65536, True])
def test_invalid_numeric_identity_is_rejected(tmp_path, number):
    comparison = ProjectComparison(ProjectMetadata(tmp_path / "metadata.sqlite3"))
    with pytest.raises(KnxError, match="knx_address_invalid"):
        comparison.observe("target", 0, {number: ()})


def project_view(xml=None):
    parsed = parse_project(
        xml
        or b'<P><C Type="EIBextactor" U="first" Title="Primary A" EibAddr="1/2/3:0"/>'
        b'<C Type="EIBextactor" U="second" Title="Primary B" EibAddr="1/515:1"/></P>'
    )
    snapshot = ProjectSnapshot(
        "a" * 64,
        5,
        (ProjectPartSummary("p", 3, ()),),
        build_graph((("p", parsed),)),
        content_identity="content",
    )
    query = ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )
    return query


def test_source_gaps_and_missing_names_are_explicit(tmp_path):
    store, _ = catalog(tmp_path)
    query = project_view(
        b'<P><C Type="EIBactor" U="valid" EibAddr="1/2/3"/>'
        b'<C Type="EIBsensor" U="bad" EibAddr="invalid"/>'
        b'<C Type="EIBsensor" U="missing"/>'
        b'<C Type="EIBunknown" U="unsupported"/>'
        b'<C Type="Other" U="marker" EIBType="5"/></P>'
    )
    result = observe_project(query, ProjectMetadata(store.path), "target", 3)
    summary = result["summaries"]["ets_project_comparison"]
    assert summary["source_limits"] == {
        "unsupported_source_objects": 1,
        "invalid_or_missing_address": 2,
        "ambiguous_source_objects": 1,
        "source_groups_omitted": 0,
        "diagnostic_groups_omitted": 0,
        "incomplete_project_names": 1,
        "counts_scope": "reported_source_groups",
    }
    assert summary["source_coverage_complete"] is False
    assert summary["counts"]["name_comparisons_unknown"] == 1
    assert (
        project_page(query, ProjectMetadata(store.path), "target", 3, result["findings"][:1])[0][
            "comparison"
        ]["project_names_complete"]
        is False
    )


def test_existing_project_index_preserves_variants_names_and_page_cache(tmp_path):
    store, _ = catalog(tmp_path)
    query = project_view()
    index = query.graph_index
    assert index is not None and len(index.knx_by_address[2563]) == 2
    metadata = ProjectMetadata(store.path)
    result = observe_project(query, metadata, "target", 3)
    summary = result["summaries"]["ets_project_comparison"]
    assert summary["counts"]["name_deviations"] == 1
    assert summary["installation_coverage"] == "not_assessable"
    assert summary["import_info"]["complete_export"] is False
    assert summary["catalog_scope"] == "may_combine_imports"
    assert isinstance(result["findings"][0], int)
    page = project_page(query, metadata, "target", 3, result["findings"][:1])
    values = page[0]["comparison"]
    assert {item["loxone_name"] for item in values["project_objects"]} == {"Primary A", "Primary B"}
    assert {item["address_variant"] for item in values["project_objects"]} == {"0", "1"}
    assert {item["address_format"] for item in values["project_objects"]} == {
        "two_level",
        "three_level",
    }
    assert values["local_metadata"]["imported"]["name"] == "ETS"
    assert values["local_metadata"]["manual"]["name"] == "Local"
    assert query.graph_index is index
    values["local_metadata"]["manual"]["name"] = "Changed output"
    assert isinstance(result["findings"][0], int)
    assert (
        project_page(query, metadata, "target", 3, result["findings"][:1])[0]["comparison"][
            "local_metadata"
        ]["manual"]["name"]
        == "Local"
    )


def test_corrupt_import_information_is_a_storage_failure(tmp_path):
    store, comparison = catalog(tmp_path)
    with store.connection() as db:
        db.execute("UPDATE import_state SET information='broken'")
        db.commit()
    with pytest.raises(KnxError, match="knx_storage_failed"):
        comparison.observe("target", 3, {})


@pytest.mark.asyncio
async def test_explicit_selection_defaults_cursor_revision_and_fresh_permission(
    tmp_path, monkeypatch
):
    store, _ = catalog(tmp_path)
    query = project_view()
    authorized = True
    selections = []

    @asynccontextmanager
    async def slot():
        yield

    async def authorize(_access):
        if not authorized:
            raise PermissionError

    async def project_query(_runtime):
        await authorize(None)
        return query, SimpleNamespace(connected=True)

    async def analysis(view, selected, taxonomy):
        selections.append(selected)
        return analyze_knx(view, selected, taxonomy)

    monkeypatch.setattr(tools, "_project_query", project_query)
    monkeypatch.setattr(tools, "process_analysis", analysis)
    monkeypatch.setattr(
        tools,
        "_access",
        lambda: SimpleNamespace(family_id="family", miniserver_id="server", identity_id="identity"),
    )
    runtime = SimpleNamespace(
        endpoint=SimpleNamespace(origin="target"),
        worker_slot=slot,
        projects=SimpleNamespace(authorize=AsyncMock(side_effect=authorize)),
    )
    runner = tools._ProjectAnalysisRunner(runtime, metadata=ProjectMetadata(store.path))
    baseline = await runner.run("knx", None)
    assert baseline.ok and selections == [ANALYSES]
    assert baseline.data.analyses == sorted(ANALYSES)
    found = await runner.run("knx", ["ets_project_comparison"], limit=1)
    assert found.ok and found.data.findings[0].comparison.relation == "common"
    assert len(found.data.findings[0].comparison.project_objects) == 2
    assert found.data.next_cursor is not None
    assert selections == [ANALYSES]
    continued = await runner.run(
        "knx", ["ets_project_comparison"], cursor=found.data.next_cursor, limit=1
    )
    assert continued.ok and continued.data.findings[0].comparison.relation == "import_only"
    assert continued.data.findings[0].comparison.local_metadata.imported["name"] == "Import only"
    repeated = await runner.run("knx", ["ets_project_comparison"], limit=1)
    assert repeated.ok and repeated.data.findings == found.data.findings
    combined = await runner.run("knx", ["address_hierarchy", "ets_project_comparison"], limit=50)
    assert combined.ok
    assert selections[-1] == {"address_hierarchy"}
    assert {"address_hierarchy", "ets_project_comparison"} == set(combined.data.analyses)
    cursor = found.data.next_cursor
    store.put(
        "target",
        3,
        {"address": "1/2/3", "address_format": "three_level", "fields": {"name": "Local override"}},
    )
    changed = await runner.run("knx", ["ets_project_comparison"], cursor=cursor, limit=1)
    assert not changed.ok and changed.data.error == "invalid_input"
    original_page = tools.ets_comparison_page

    def revoke_during_projection(*args):
        nonlocal authorized
        result = original_page(*args)
        authorized = False
        return result

    monkeypatch.setattr(tools, "ets_comparison_page", revoke_during_projection)
    revoked = await runner.run("knx", ["ets_project_comparison"], limit=1)
    assert not revoked.ok and revoked.data.error == "unauthenticated"


def test_analysis_contract_declares_explicit_comparison_and_separate_sources():
    schema = tools.ProjectAnalysisData.model_json_schema()
    assert "ets_project_comparison" in schema["properties"]["analyses"]["items"]["enum"]
    row = schema["$defs"]["ProjectKnxComparisonRowData"]
    assert row["properties"]["project_objects"]["maxItems"] == 20
    assert row["properties"]["relation"]["enum"] == [
        "common",
        "import_only",
        "observed_project_only",
    ]


def test_expired_worker_budget_does_not_start_comparison(tmp_path):
    with pytest.raises(ProjectError, match="project_worker_limit"):
        observe_project(
            project_view(), ProjectMetadata(tmp_path / "metadata.sqlite3"), "target", 0, deadline=0
        )


@pytest.fixture
def compact_runner(tmp_path, monkeypatch):
    store, _ = catalog(tmp_path)
    query = project_view()
    allowed = {"value": True}

    @asynccontextmanager
    async def slot():
        yield

    async def authorize(_access):
        if not allowed["value"]:
            raise PermissionError

    async def project_query(_runtime):
        await authorize(None)
        return query, SimpleNamespace(connected=True)

    monkeypatch.setattr(tools, "_project_query", project_query)
    monkeypatch.setattr(
        tools,
        "_access",
        lambda: SimpleNamespace(family_id="family", miniserver_id="server", identity_id="identity"),
    )
    runtime = SimpleNamespace(
        endpoint=SimpleNamespace(origin="target"),
        worker_slot=slot,
        projects=SimpleNamespace(authorize=AsyncMock(side_effect=authorize)),
    )
    metadata = ProjectMetadata(store.path)
    return tools._ProjectAnalysisRunner(runtime, metadata=metadata), store, allowed


@pytest.mark.asyncio
async def test_summary_never_hydrates_rows_and_reuses_authorized_observation(
    compact_runner, monkeypatch
):
    runner, _, allowed = compact_runner
    observe = AsyncMock(wraps=tools.observe_ets_project)
    monkeypatch.setattr(tools, "observe_ets_project", observe)
    monkeypatch.setattr(
        tools, "ets_comparison_page", lambda *_args: pytest.fail("summary hydration")
    )
    summary = await runner.run("knx", ["ets_project_comparison"], view="summary")
    assert summary.ok and isinstance(summary.data, tools.ProjectKnxCompactAnalysisData)
    assert summary.data.findings == [] and summary.data.next_cursor is None
    assert summary.data.selection["complete"] is True
    assert (
        summary.data.selection["counts"]
        == summary.data.summaries["ets_project_comparison"]["counts"]
    )
    repeated = await runner.run(
        "knx", ["ets_project_comparison"], view="summary", relation="common"
    )
    assert repeated.ok and repeated.data.selection["selected_observations"] == 1
    assert observe.await_count == 1
    assert len(runner.cache) == 1
    allowed["value"] = False
    denied = await runner.run("knx", ["ets_project_comparison"], view="summary")
    assert not denied.ok and denied.data.error == "unauthenticated"


@pytest.mark.asyncio
async def test_compact_pages_equal_full_evidence_and_bind_all_filters(compact_runner):
    runner, store, _ = compact_runner
    full = await runner.run("knx", ["ets_project_comparison"], limit=50)
    assert full.ok and isinstance(full.data, tools.ProjectAnalysisData)
    cursor = None
    comparisons = []
    while True:
        page = await runner.run(
            "knx", ["ets_project_comparison"], view="findings", cursor=cursor, limit=1
        )
        assert page.ok
        comparisons.extend(row.comparison for row in page.data.findings)
        cursor = page.data.next_cursor
        if cursor is None:
            break
    assert comparisons == [row.comparison for row in full.data.findings]
    first = await runner.run("knx", ["ets_project_comparison"], view="findings", limit=1)
    for changed in (
        {"view": "full"},
        {"view": "findings", "relation": "common"},
        {"view": "findings", "names_differ": True},
        {"view": "findings", "ambiguous_names": True},
        {"view": "findings", "address": "1/2/3"},
        {"view": "findings", "source_details": True},
    ):
        denied = await runner.run(
            "knx", ["ets_project_comparison"], cursor=first.data.next_cursor, **changed
        )
        assert not denied.ok and denied.data.error == "invalid_input"
    detail = await runner.run(
        "knx", ["ets_project_comparison"], view="detail", address="1/515", source_details=True
    )
    assert detail.ok and len(detail.data.findings) == 1
    assert detail.data.findings[0].comparison == comparisons[0]
    assert detail.data.source_diagnostics_details is not None
    assert detail.data.source_coverage_details is not None
    store.put(
        "target",
        3,
        {"address": "1/2/3", "address_format": "three_level", "fields": {"name": "Changed"}},
    )
    stale = await runner.run(
        "knx", ["ets_project_comparison"], view="findings", cursor=first.data.next_cursor
    )
    assert not stale.ok and stale.data.error == "invalid_input"


@pytest.mark.parametrize(
    "arguments",
    [
        {"view": "detail"},
        {"view": "summary", "cursor": "cursor"},
        {"view": "findings", "address": "1/2/3:0"},
        {"view": "findings", "address": "32/0"},
        {"view": "full", "names_differ": False},
        {"view": "full", "source_details": True},
    ],
)
@pytest.mark.asyncio
async def test_invalid_compact_selection_is_rejected(compact_runner, arguments):
    runner, _, _ = compact_runner
    result = await runner.run("knx", ["ets_project_comparison"], **arguments)
    assert not result.ok and result.data.error == "invalid_input"


@pytest.mark.asyncio
async def test_compact_views_reject_mixed_analysis_and_other_scope(compact_runner):
    runner, _, _ = compact_runner
    for scope, analyses in (
        ("knx", ["ets_project_comparison", "duplicate_addresses"]),
        ("modbus", None),
    ):
        result = await runner.run(scope, analyses, view="summary")
        assert not result.ok and result.data.error == "invalid_input"


@pytest.mark.asyncio
async def test_compact_keeps_empty_long_and_multi_dpt_source_values(compact_runner):
    runner, store, _ = compact_runner
    with store.connection() as db:
        db.execute(
            "UPDATE addresses SET imported=?,overrides=? WHERE address=?",
            (
                json.dumps({"name": "ETS", "description": "x" * 4096, "dpts": ["1.001", "5.001"]}),
                json.dumps({"name": "", "description": ""}),
                2563,
            ),
        )
        db.commit()
    full = await runner.run("knx", ["ets_project_comparison"], limit=50)
    detail = await runner.run("knx", ["ets_project_comparison"], view="detail", address="1/2/3")
    assert full.ok and detail.ok
    assert detail.data.findings[0].comparison == full.data.findings[0].comparison
    dumped = detail.data.findings[0].comparison.model_dump(mode="json")
    metadata = dumped["local_metadata"]
    assert metadata["manual"]["name"] == "" and metadata["manual"]["description"] == ""
    assert metadata["imported"]["description"] == "x" * 4096
    assert metadata["imported"]["dpts"] == ["1.001", "5.001"]


def test_false_name_filter_excludes_unknown_and_non_comparisons():
    common_equal = 1 | (1 << 16)
    common_unknown = 2 | (17 << 16)
    common_different = 3 | (5 << 16)
    project_only = 4 | (2 << 16)
    common_incomplete = 5 | (33 << 16)
    rows = [common_equal, common_unknown, common_different, project_only, common_incomplete]
    assert filter_observations(rows, selection("findings", None, False, None, None, False)) == [
        common_equal
    ]
    assert filter_observations(rows, selection("findings", None, True, None, None, False)) == [
        common_different
    ]


def test_compact_counts_preserve_overlapping_flags_and_unfiltered_observations():
    rows = [
        address | (flags << 16) for flags in range(64) if flags & 3 != 3 for address in range(7)
    ]
    retained = filter_observations(rows, selection("summary", None, None, None, None, False))
    assert retained is rows
    assert selected_counts(retained) == {
        "common": 112,
        "import_only": 112,
        "observed_project_only": 112,
        "name_deviations": 168,
        "name_comparisons_unknown": 168,
        "ambiguous_project_names": 168,
    }
    assert selected_counts([]) == dict.fromkeys(selected_counts(retained), 0)
    with pytest.raises(ValueError, match="ETS-only"):
        filter_observations([{}], selection("summary", None, None, None, None, False))


def test_incomplete_observed_names_do_not_pass_equality_filter(tmp_path):
    store, _ = catalog(tmp_path)
    query = project_view(
        b'<P><C Type="EIBextactor" U="known" Title="ETS" EibAddr="1/2/3"/>'
        b'<C Type="EIBextactor" U="unknown" EibAddr="1/2/3"/></P>'
    )
    metadata = ProjectMetadata(store.path)
    observed = observe_project(query, metadata, "target", 3)
    assert (
        filter_observations(
            observed["findings"], selection("findings", None, False, None, None, False)
        )
        == []
    )
    # Released full evidence still shows the partial comparison and its limitation.
    full = project_page(query, metadata, "target", 3, observed["findings"])
    row = full[0]["comparison"]
    assert not row["names_differ"] and row["name_comparison"] == "compared"
    assert not row["project_names_complete"]


@pytest.mark.asyncio
async def test_compact_size_reduction_and_page_limit_keep_complete_rows(
    compact_runner, monkeypatch
):
    runner, _, _ = compact_runner
    full = await runner.run("knx", ["ets_project_comparison"], limit=50)
    compact = await runner.run("knx", ["ets_project_comparison"], view="findings", limit=50)
    summary = await runner.run("knx", ["ets_project_comparison"], view="summary")
    assert len(compact.model_dump_json().encode()) < len(full.model_dump_json().encode()) * 0.85
    assert len(summary.model_dump_json().encode()) < len(full.model_dump_json().encode()) * 0.5
    one = compact.model_copy(deep=True)
    one.data.findings = one.data.findings[:1]
    # Reserve room for the continuation token, whose fixed bound is below 300 bytes.
    budget = len(one.model_dump_json().encode()) + 300
    assert budget < len(compact.model_dump_json().encode())
    monkeypatch.setattr(tools, "PROJECT_RESPONSE_MAX_BYTES", budget)
    bounded = await runner.run("knx", ["ets_project_comparison"], view="findings", limit=50)
    assert bounded.ok and len(bounded.data.findings) == 1
    assert bounded.data.page_truncated and bounded.data.next_cursor is not None
    assert len(bounded.model_dump_json().encode()) <= budget
    continued = await runner.run(
        "knx",
        ["ets_project_comparison"],
        view="findings",
        cursor=bounded.data.next_cursor,
        limit=50,
    )
    assert continued.ok and continued.data.findings == compact.data.findings[1:]


@pytest.mark.asyncio
async def test_repeated_request_cancellation_retains_worker_until_thread_ends(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    lease = {"active": False}

    def blocking(*_args):
        started.set()
        assert release.wait(10)
        finished.set()
        return {}

    monkeypatch.setattr(comparison_adapter, "observe_project", blocking)

    async def request():
        lease["active"] = True
        try:
            return await comparison_adapter.observe_project_bounded(None, None, "target", 0)
        finally:
            lease["active"] = False

    task = asyncio.create_task(request())
    try:
        assert await asyncio.to_thread(started.wait, 10)
        task.cancel()
        await asyncio.sleep(0)
        assert lease["active"] and not task.done()
        task.cancel()
        await asyncio.sleep(0)
        assert lease["active"] and not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set() and not lease["active"]
