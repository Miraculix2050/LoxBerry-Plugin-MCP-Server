"""Local search bounds, literal Unicode matching and source uncertainty."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace

import pytest

from mcpserver.config import PluginConfig
from mcpserver.knx.catalog import catalog_page, labels_revision
from mcpserver.knx.model import KnxError, address
from mcpserver.knx.read_model import datapoint
from mcpserver.knx.store import KnxStore
from mcpserver.loxone.project.taxonomy import AddressTaxonomyEntry


def record(value, imported, overrides, fmt="three_level"):
    return {
        "address_id": address(value, fmt)[0],
        "address": value,
        "address_format": fmt,
        "imported": imported,
        "overrides": overrides,
    }


def test_summary_never_hydrates_catalog_and_exact_id_is_not_name_matching(store, monkeypatch):
    number = address("1/2/3", "three_level")[0]
    expected = store.page("target", address_id=number)
    assert expected["total"] == 1
    assert expected["items"][0]["address_id"] == number
    # Pure counts use the same SQL filter/revision but never decode metadata.
    monkeypatch.setattr(store, "project", lambda _row: pytest.fail("summary hydrated metadata"))
    summary = store.page("target", address_id=number, count_only=True)
    assert summary["items"] == []
    assert summary["total"] == expected["total"]
    assert summary["revision"] == expected["revision"]


@pytest.mark.parametrize("number", [-1, 65536, True, "1"])
def test_exact_catalog_identity_is_strictly_bounded(store, number):
    with pytest.raises(KnxError, match="knx_page_invalid"):
        store.page("target", address_id=number)


def test_local_catalog_preserves_sources_empty_values_and_style_bound_prefixes(store):
    config = replace(
        PluginConfig.defaults(),
        knx_address_taxonomy_endpoint="target",
        knx_address_taxonomy=(
            AddressTaxonomyEntry("1/2", "Manual group", "three_level"),
            AddressTaxonomyEntry("1/2/3", "Exact context", "three_level"),
            AddressTaxonomyEntry("1", "Other style", "two_level"),
        ),
    )
    with store.connection() as db:
        db.execute(
            "INSERT INTO import_groups VALUES(?,?,?,?,?,?)",
            ("target", "three_level", "1/2", json.dumps({"name": "ETS group"}), "{}", 1),
        )
        db.commit()
    page = catalog_page(store, config, "target", address_id=address("1/2/3", "three_level")[0])
    assert page["total_matching"] == 1
    assert not page["loxone_names_included"]
    row = page["records"][0]
    assert row["sources"]["imported"]["name"] == "Straße Küche"
    assert row["sources"]["manual"]["name"] == "Local"
    assert row["sources"]["manual"]["description"] == ""
    assert row["local_resolution"] == dict.fromkeys(("name", "description", "dpts"), "manual")
    assert row["sources"]["imported"]["dpts"] == ["DPST-1-1"]
    assert row["dpt_details"]["imported"]["items"][0]["status"] == "format_valid_type_unverified"
    assert row["prefix_ids"] == ["three_level:1/2", "three_level:1/2/3"]
    assert page["active_prefix_count"] == 3
    assert page["prefix_context"][0]["sources"] == {
        "imported": "ETS group",
        "manual": "Manual group",
    }
    assert page["prefix_context"][0]["local_label_source"] == "manual"
    assert page["labels_revision"] == labels_revision(config, "target")
    assert (
        labels_revision(replace(config, knx_address_taxonomy_endpoint="other"), "target")
        != page["labels_revision"]
    )


def test_local_catalog_summary_has_no_rows_and_manual_only_unknown_stays_unknown(
    store, monkeypatch
):
    config = PluginConfig.defaults()
    manual = catalog_page(store, config, "target", address_id=65535)["records"][0]
    assert manual["sources"]["imported"] == {}
    assert manual["local_resolution"]["dpts"] == "unknown"
    monkeypatch.setattr(store, "project", lambda _row: pytest.fail("summary hydrated rows"))
    summary = catalog_page(store, config, "target", count_only=True)
    assert summary["total_matching"] == 3
    assert summary["records"] == []
    assert summary["prefix_context"] == []


@pytest.fixture
def store(tmp_path):
    result = KnxStore(tmp_path / "metadata.sqlite3")
    result.restore(
        "target",
        0,
        {
            "schema_version": 1,
            "records": [
                record(
                    "1/2/3",
                    {
                        "name": "Straße Küche",
                        "description": "<script>line\nnext</script>",
                        "dpts": ["DPST-1-1"],
                    },
                    {"name": "Local", "description": "", "dpts": ["1.001"]},
                ),
                record(
                    "1/2/4",
                    {
                        "name": "Duplicate",
                        "dpts": ["DPT-9", "DPST-9-1", "unrecognized", "DPST-99999-1"],
                    },
                    {},
                ),
                record(
                    "31/2047",
                    {},
                    {"name": "Duplicate", "description": "literal %_ quote'"},
                    "two_level",
                ),
            ],
        },
    )
    result.put(
        "other",
        0,
        {"address": "1/2/3", "address_format": "three_level", "fields": {"name": "Other"}},
    )
    return result


@pytest.mark.parametrize(
    "query,expected",
    [
        ("STRASSE", "1/2/3"),
        ("küche", "1/2/3"),
        ("<script>", "1/2/3"),
        ("%_", "31/2047"),
        ("quote'", "31/2047"),
        ("31/7/255", "31/2047"),
    ],
)
def test_literal_unicode_source_and_address_alias_search(store, query, expected):
    page = store.page("target", filters={"query": query})
    assert page["total"] == 1 and page["items"][0]["address"] == expected
    assert store.page("other", filters={"query": query})["total"] == 0


@pytest.mark.parametrize("source,total", [("all", 3), ("imported", 2), ("manual", 2), ("both", 1)])
def test_sources_and_explicit_deviations_are_separate(store, source, total):
    assert store.page("target", filters={"source": source})["total"] == total
    page = store.page("target", filters={"deviations_only": True})
    assert page["total"] == 1
    row = page["items"][0]
    assert row["deviations"] == ["description", "name"]
    assert row["imported"]["description"] != row["overrides"]["description"] == ""
    assert row["dpt_details"]["manual"]["items"][0]["normalized"] == "1.001"
    assert row["dpt_details"]["imported"]["association"] == "not_established"


def test_dpt_missing_empty_multiple_invalid_and_unverified_types(store):
    rows = store.page("target")["items"]
    assert rows[2]["dpt_details"]["manual"]["state"] == "unknown"
    declarations = rows[1]["dpt_details"]["imported"]["items"]
    assert len(declarations) == 4
    assert declarations[0]["main"] == 9 and declarations[0]["subtype"] is None
    assert declarations[1]["normalized"] == "9.001"
    assert declarations[2]["status"] == "invalid_format"
    assert declarations[3]["status"] == "format_valid_type_unverified"
    store.put(
        "target",
        1,
        {
            "address": "31/2047",
            "address_format": "two_level",
            "fields": {"name": "Duplicate", "dpts": []},
        },
    )
    assert store.page("target")["items"][2]["dpt_details"]["manual"]["state"] == "empty"
    assert datapoint("DPST-0-1")["status"] == "invalid_format"


@pytest.mark.parametrize(
    "filters",
    [
        [],
        {"query": 5},
        {"query": "x" * 129},
        {"query": "a\x00b"},
        {"source": []},
        {"source": "private"},
        {"deviations_only": 1},
        {"unexpected": True},
    ],
)
def test_search_rejects_invalid_values(store, filters):
    with pytest.raises(KnxError, match="knx_query_invalid"):
        store.page("target", filters=filters)


def test_pagination_revision_and_exchange_contract(store):
    first = store.page("target", limit=1, filters={"query": "Duplicate"})
    assert first["total"] == 2
    second = store.page(
        "target", offset=1, limit=1, filters=first["filters"], expected=first["revision"]
    )
    assert second["items"][0]["address"] == "31/2047"
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        store.page("target", offset=1, filters=first["filters"])
    exported = store.export("target", filters={"query": "Duplicate"}, expected=1)
    assert len(exported["records"]) == 2
    assert set(exported["records"][0]) == {
        "address_id",
        "address",
        "address_format",
        "imported",
        "overrides",
    }
    store.put(
        "target",
        1,
        {"address": "1/2/4", "address_format": "three_level", "fields": {"name": "Changed"}},
    )
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        store.page("target", offset=1, filters=first["filters"], expected=1)


def test_query_uses_fixed_read_count_and_bounded_projection(store, monkeypatch):
    statements = []
    original = store.connection

    @contextmanager
    def traced():
        with original() as db:
            db.set_trace_callback(statements.append)
            yield db

    monkeypatch.setattr(store, "connection", traced)
    result = store.page("target", filters={"query": "Duplicate"})
    assert result["total"] == 2 and len(result["items"]) == 2
    reads = [s for s in statements if s.startswith("SELECT")]
    assert len(reads) == 3
    assert "LIMIT 50 OFFSET 0" in reads[-1]
    assert "a.target='target'" in reads[-1]


def test_database_failure_is_not_an_empty_search(tmp_path):
    path = tmp_path / "metadata.sqlite3"
    path.write_bytes(b"not sqlite")
    with pytest.raises(KnxError, match="knx_storage_failed"):
        KnxStore(path).page("target", filters={"query": "absent"})


@pytest.mark.parametrize("summary,expected_reads", [(False, 5), (True, 3)])
def test_catalog_reads_are_constant_and_share_one_snapshot(
    store, monkeypatch, summary, expected_reads
):
    statements = []
    original = store.connection

    @contextmanager
    def traced():
        with original() as db:
            db.set_trace_callback(statements.append)
            yield db

    monkeypatch.setattr(store, "connection", traced)
    result = catalog_page(store, PluginConfig.defaults(), "target", count_only=summary)
    assert result["total_matching"] == 3
    assert (
        len([statement for statement in statements if statement.startswith("SELECT")])
        == expected_reads
    )
    assert len([statement for statement in statements if statement == "BEGIN"]) == 1


def test_all_imported_groups_keep_sources_bounds_and_address_context(store):
    from mcpserver.knx.catalog import catalog_group_page

    with store.connection() as db:
        for fmt, prefix, name, attrs in [
            ("three_level", "1", "Imported main", {"RangeStart": "2049", "RangeEnd": "4095"}),
            ("three_level", "1/2", "x" * 255, {}),
            ("three_level", "2", "Empty group", {}),
            ("two_level", "1", "Other format", {}),
        ]:
            db.execute(
                "INSERT INTO import_groups VALUES(?,?,?,?,?,?)",
                (
                    "target",
                    fmt,
                    prefix,
                    json.dumps({"name": name, "description": ""}),
                    json.dumps({"attributes": attrs}),
                    0,
                ),
            )
        db.execute("INSERT INTO targets(target) VALUES(?)", ("foreign",))
        db.execute(
            "INSERT INTO import_groups VALUES(?,?,?,?,?,?)",
            (
                "foreign",
                "three_level",
                "1",
                '{"name":"Foreign"}',
                "{}",
                0,
            ),
        )
        db.commit()
    config = replace(
        PluginConfig.defaults(),
        knx_address_taxonomy_endpoint="target",
        knx_address_taxonomy=(AddressTaxonomyEntry("1", "Manual", "three_level"),),
    )
    page = catalog_group_page(store, config, "target")
    assert page["total_matching"] == 4
    assert page["active_prefix_count"] == 1
    main, middle, empty, other = page["imported_groups"]
    assert main["fields"]["name"] == "Imported main"
    assert main["range_start"] == 2049 and main["range_end"] == 4095
    assert main["range_source"] == "ets_xml" and not main["active_label"]
    assert middle["range_start"] == 2560 and middle["range_end"] == 2815
    assert middle["range_source"] == "address_prefix"
    assert middle["fields"] == {"name": "x" * 255, "description": ""}
    assert empty["prefix"] == "2" and other["address_format"] == "two_level"
    addresses = catalog_page(store, config, "target", address_id=2563)
    assert addresses["records"][0]["group_ids"] == ["three_level:1", "three_level:1/2"]
    assert addresses["group_context"] == [main, middle]
    assert (
        catalog_group_page(store, config, "target", filters={"query": "Empty"})["total_matching"]
        == 1
    )
    for filters in ({"source": "manual"}, {"source": "both"}, {"deviations_only": True}):
        assert catalog_group_page(store, config, "target", filters=filters)["total_matching"] == 0
    summary = catalog_group_page(store, config, "target", count_only=True)
    assert summary["total_matching"] == 4 and summary["imported_groups"] == []


def test_xml_import_projects_exact_ranges_without_selecting_labels(tmp_path):
    from mcpserver.knx.catalog import catalog_group_page
    from mcpserver.knx.import_repository import ImportRepository
    from mcpserver.knx.import_service import select_candidates
    from mcpserver.knx.xml_adapter import NAMESPACE, parse_xml

    store = KnxStore(tmp_path / "metadata.sqlite3")
    document = parse_xml(
        (
            f'<GroupAddress-Export xmlns="{NAMESPACE}">'
            '<GroupRange Name="Main" RangeStart="2049" RangeEnd="4095">'
            '<GroupRange Name="Middle" RangeStart="2560" RangeEnd="2815">'
            '<GroupAddress Address="1/2/3" Name="Function"/>'
            "</GroupRange></GroupRange></GroupAddress-Export>"
        ).encode()
    )
    ImportRepository(store).apply("target", 0, document, select_candidates(document), set(), {})
    config = PluginConfig.defaults()
    groups = catalog_group_page(store, config, "target")["imported_groups"]
    assert groups[0]["range_start"] == 2049
    assert groups[0]["range_source"] == "ets_xml"
    assert all(not group["active_label"] for group in groups)
    assert catalog_page(store, config, "target")["group_context"] == groups


def test_large_search_returns_only_one_page(tmp_path):
    store = KnxStore(tmp_path / "metadata.sqlite3")
    records = [
        record(f"2/0/{number}", {}, {"name": "Shared name", "description": "x" * 4096})
        for number in range(105)
    ]
    store.restore("target", 0, {"schema_version": 1, "records": records})
    first = store.page("target", filters={"query": "Shared"})
    assert first["total"] == 105 and len(first["items"]) == 50
    second = store.page("target", offset=50, filters=first["filters"], expected=1)
    assert len(second["items"]) == 50
    assert second["items"][0]["address"] == "2/0/50"
    last = store.page("target", offset=100, filters=first["filters"], expected=1)
    assert len(last["items"]) == 5
