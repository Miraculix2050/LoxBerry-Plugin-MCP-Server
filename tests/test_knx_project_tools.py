"""Authorized public metadata projection without replacing Loxone evidence."""

import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP

import mcpserver.tools as tools
from mcpserver.knx.project_metadata import ProjectMetadata
from mcpserver.knx.store import KnxStore
from mcpserver.loxone.project.graph import ProjectPartSummary, ProjectSnapshot, build_graph
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.models import ProjectError
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.query import ProjectQuery
from mcpserver.loxone.project.taxonomy import parse_taxonomy


def project():
    parsed = parse_project(
        b'<P><C Type="EIBactor" U="actor" Title="Loxone primary" Desc="Project description" '
        b'EibAddr="1/2/3" EIBType="5"/><C Type="EIBactor" U="other" '
        b'Title="Other Loxone" EibAddr="1/2/4"/></P>'
    )
    snapshot = ProjectSnapshot(
        "a" * 64,
        5,
        (ProjectPartSummary("p", 3, ()),),
        build_graph((("p", parsed),)),
        content_identity="content",
    )
    return ProjectQuery(
        ProjectView(
            snapshot,
            map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=())),
        ),
        {},
    )


def test_metadata_schema_preserves_optional_fields_and_typed_dpt_sources():
    schema = tools.ProjectKnxMetadataData.model_json_schema()
    fields = schema["$defs"]["ProjectKnxMetadataFieldsData"]
    assert not fields.get("required")
    declarations = schema["$defs"]["ProjectKnxDptDeclarationData"]["properties"]
    assert declarations["items"]["maxItems"] == 16
    assert declarations["state"]["enum"] == ["unknown", "empty", "declared"]
    identifiers = schema["$defs"]["ProjectKnxDptIdentifierData"]
    assert "main" not in identifiers["required"] and "subtype" not in identifiers["required"]
    assert identifiers["properties"]["status"]["enum"] == [
        "invalid_format",
        "format_valid_type_unverified",
    ]


@pytest.mark.asyncio
async def test_metadata_search_description_cursor_and_fresh_authorization(tmp_path, monkeypatch):
    monkeypatch.setenv("LBPDATA", str(tmp_path))
    catalog = KnxStore(tmp_path / "knx" / "metadata.sqlite3")
    target = "http://miniserver.example"
    revision = catalog.put(
        target,
        0,
        {
            "address": "1/2/3",
            "address_format": "three_level",
            "fields": {"name": "Straße metadata", "description": "", "dpts": ["1.001", "bad"]},
        },
    )
    view = project()
    main_thread = threading.get_ident()
    original_lookup = ProjectMetadata.lookup
    lookups = []

    def lookup(self, *args):
        assert threading.get_ident() != main_thread
        lookups.append(args)
        return original_lookup(self, *args)

    monkeypatch.setattr(ProjectMetadata, "lookup", lookup)

    async def query(_runtime):
        return view, SimpleNamespace(connected=True)

    monkeypatch.setattr(tools, "_project_query", query)
    monkeypatch.setattr(
        tools,
        "_access",
        lambda: SimpleNamespace(
            family_id="family",
            miniserver_id="server",
            identity_id="identity",
        ),
    )
    runtime = SimpleNamespace(
        endpoint=SimpleNamespace(origin=target), projects=SimpleNamespace(authorize=AsyncMock())
    )
    server = FastMCP("knx-project-metadata")
    tools.register_project_tools(server, runtime)
    find = server._tool_manager.get_tool("loxone_find_project_objects").fn
    describe = server._tool_manager.get_tool("loxone_describe_project_object").fn
    found = await find(query="STRASSE")
    assert found.ok and len(found.data.items) == 1
    item = found.data.items[0]
    assert item.knx.metadata.manual["name"] == "Straße metadata"
    detail = await describe(item.project_node_id)
    assert detail.ok
    assert detail.data.knx.title == "Loxone primary"
    assert detail.data.knx.description == "Project description"
    assert detail.data.knx.datatype.source_value == "5"
    assert detail.data.knx.normalized_dpt_evidence is None
    assert detail.data.knx.metadata.manual["description"] == ""
    assert detail.data.knx.metadata.dpt_details["manual"]["items"][1]["status"] == "invalid_format"
    first = await find(limit=1)
    assert first.ok and first.data.next_cursor
    follow = await find(limit=1, cursor=first.data.next_cursor)
    assert follow.ok and follow.data.items[0].project_node_id != item.project_node_id
    assert max(len(args[2]) for args in lookups) <= 1
    revision = catalog.put(
        target,
        revision,
        {
            "address": "1/2/4",
            "address_format": "three_level",
            "fields": {"name": "Updated"},
        },
    )
    old_cursor = await find(limit=1, cursor=first.data.next_cursor)
    assert not old_cursor.ok and old_cursor.data.error == "invalid_input"
    fresh = await find(query="Updated")
    assert fresh.ok and fresh.data.items[0].knx.metadata.revision == revision
    # A local setup permission failure must not be reported as Loxone authentication.
    from unittest.mock import patch

    import mcpserver.knx.store as store_module

    with patch.object(store_module.os, "open", side_effect=PermissionError("private path")):
        failed_read = await find(query="Updated")
        assert not failed_read.ok and failed_read.data.error == "temporarily_unavailable"
    runtime.projects.authorize.side_effect = PermissionError()
    denied = await find(query="Updated")
    assert not denied.ok and denied.data.error == "unauthenticated"


def test_additional_names_match_only_existing_numeric_address_relationship():
    view = project()
    found = view.find(
        query="unrelated additional name",
        kind=None,
        block_type=None,
        source_id=None,
        runtime_control_uuid=None,
        metadata_matches=frozenset({2563}),
    )
    assert len(found) == 1
    assert found[0]["knx"]["group_address"]["original"] == "1/2/3"
    assert view.graph_index is not None
    index = view.graph_index
    repeated = ProjectQuery(view.view, view.control_names, graph_index=index)
    assert repeated.graph_index is index
    assert (
        repeated.find(
            query="unrelated additional name",
            kind=None,
            block_type=None,
            source_id=None,
            runtime_control_uuid=None,
        )
        == []
    )


@pytest.mark.asyncio
async def test_selected_imported_labels_stay_below_manual_exact_prefix(tmp_path, monkeypatch):
    metadata = ProjectMetadata(tmp_path / "metadata.sqlite3")
    target = "http://miniserver.example"
    with metadata.store.connection() as db:
        db.execute("INSERT INTO targets VALUES(?,1)", (target,))
        db.executemany(
            "INSERT INTO import_groups VALUES(?,?,?,?,?,?)",
            [
                (target, "three_level", "1", '{"name":"ETS main"}', "{}", 1),
                (target, "three_level", "1/2", '{"name":"ETS middle"}', "{}", 1),
                (target, "three_level", "2", '{"name":"Not selected"}', "{}", 0),
            ],
        )
        db.commit()
    manual = parse_taxonomy([{"address_format": "three_level", "prefix": "1", "label": "Manual"}])
    config = SimpleNamespace(knx_address_taxonomy_endpoint=target, knx_address_taxonomy=manual)
    captured = []

    @asynccontextmanager
    async def slot():
        yield

    runtime = SimpleNamespace(
        endpoint=SimpleNamespace(origin=target),
        worker_slot=slot,
        projects=SimpleNamespace(authorize=AsyncMock()),
    )

    async def query(_runtime):
        return project(), SimpleNamespace(connected=True)

    async def analyze(_view, _selected, taxonomy):
        captured.extend(taxonomy)
        raise ProjectError("project_worker_limit")

    monkeypatch.setattr(tools, "_project_query", query)
    monkeypatch.setattr(tools, "process_analysis", analyze)
    monkeypatch.setattr(
        tools,
        "_access",
        lambda: SimpleNamespace(family_id="family", miniserver_id="server", identity_id="identity"),
    )
    runner = tools._ProjectAnalysisRunner(runtime, SimpleNamespace(load=lambda: config), metadata)
    result = await runner.run("knx", ["address_hierarchy"])
    assert not result.ok and result.data.error == "temporarily_unavailable"
    assert [(e.prefix, e.label) for e in captured] == [("1/2", "ETS middle"), ("1", "Manual")]
