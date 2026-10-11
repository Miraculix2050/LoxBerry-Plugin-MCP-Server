"""Metadata reads are bounded, revisioned and preserve separate source evidence."""

import json
import sqlite3

import pytest

from mcpserver.knx.model import KnxError, address_number
from mcpserver.knx.project_metadata import ProjectMetadata
from mcpserver.knx.store import KnxStore


def test_numeric_lookup_preserves_aliases_and_edge_variants():
    assert address_number("1/2/3:0") == address_number("1/515:1") == 2563
    assert address_number("32/0/0") is None
    assert address_number("1/2/3:2") is None
    assert address_number(None) is None


def test_missing_database_is_empty_without_creating_files(tmp_path):
    service = ProjectMetadata(tmp_path / "metadata.sqlite3")
    assert service.revision("target") == 0
    assert service.lookup("target", 0, {1}) == {}
    assert service.search("target", 0, "name") == frozenset()
    assert not service.store.path.exists()


def test_disappeared_existing_database_is_not_an_empty_catalog(tmp_path):
    service = ProjectMetadata(tmp_path / "metadata.sqlite3")
    service.store.put(
        "target",
        0,
        {
            "address": "0/0/1",
            "address_format": "three_level",
            "fields": {"name": "Local"},
        },
    )
    assert service.revision("target") == 1
    service.store.path.unlink()
    with pytest.raises(KnxError, match="knx_storage_failed"):
        service.revision("target")


def test_batched_cache_includes_negative_results_and_revision_invalidation(tmp_path, monkeypatch):
    path = tmp_path / "metadata.sqlite3"
    store = KnxStore(path)
    revision = store.put(
        "target",
        0,
        {
            "address": "1/2/3",
            "address_format": "three_level",
            "fields": {"name": "Straße local", "description": "", "dpts": ["1.001", "bad"]},
        },
    )
    service = ProjectMetadata(path)
    queries = []
    original = sqlite3.connect

    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        connection.set_trace_callback(queries.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    assert service.revision("target") == revision
    result = service.lookup("target", revision, {2563, 2564})
    assert result[2563]["manual"]["name"] == "Straße local"
    assert result[2563]["manual"]["description"] == ""
    assert result[2563]["imported"] == {}
    assert len(result[2563]["dpt_details"]["manual"]["items"]) == 2
    cold = sum("SELECT a.address,a.imported" in q for q in queries)
    result[2563]["manual"]["name"] = "mutated caller copy"
    assert (
        service.lookup("target", revision, {2563, 2564})[2563]["manual"]["name"] == "Straße local"
    )
    assert sum("SELECT a.address,a.imported" in q for q in queries) == cold == 1
    assert service.search("target", revision, "STRASSE") == {2563}
    assert service.search("target", revision, "%_") == set()
    next_revision = store.put(
        "target",
        revision,
        {
            "address": "1/2/4",
            "address_format": "three_level",
            "fields": {"name": "New"},
        },
    )
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        service.lookup("target", revision, {2563})
    assert service.revision("target") == next_revision
    assert not service.cache and service.cache_bytes == 0
    assert service.lookup("target", next_revision, {2564})[2564]["manual"]["name"] == "New"


def test_cache_budget_batch_bounds_and_storage_failure(tmp_path):
    path = tmp_path / "metadata.sqlite3"
    store = KnxStore(path)
    revision = store.put(
        "target",
        0,
        {
            "address": "0/0/1",
            "address_format": "three_level",
            "fields": {"name": "local", "description": "x" * 4096},
        },
    )
    service = ProjectMetadata(path, max_bytes=512)
    assert service.lookup("target", revision, {1})[1]["manual"]["name"] == "local"
    assert service.cache_bytes <= 512
    for numbers in (set(range(101)), {-1}, {65536}, {True}):
        with pytest.raises(KnxError, match="knx_page_invalid"):
            service.lookup("target", revision, numbers)
    path.write_bytes(b"corrupt database")
    with pytest.raises(KnxError, match="knx_storage_failed"):
        service.revision("target")


def test_long_project_search_is_not_truncated(tmp_path):
    service = ProjectMetadata(tmp_path / "metadata.sqlite3")
    name = "a" * 129 + "distinguishing tail"
    revision = service.store.put(
        "target",
        0,
        {
            "address": "0/0/1",
            "address_format": "three_level",
            "fields": {"name": name},
        },
    )
    assert service.search("target", revision, name) == {1}
    assert service.search("target", revision, "a" * 129 + "wrong tail") == set()


def test_hidden_import_values_and_only_bounded_source_projection(tmp_path):
    service = ProjectMetadata(tmp_path / "metadata.sqlite3")
    revision = service.store.put(
        "target",
        0,
        {
            "address": "1/2/3",
            "address_format": "three_level",
            "fields": {"name": "Local"},
        },
    )
    imported = {"name": "ETS original", "description": "Imported description", "dpts": ["DPST-1-1"]}
    with service.store.connection() as db:
        db.execute("UPDATE addresses SET imported=?", (json.dumps(imported),))
        db.execute(
            "INSERT INTO ets_sources VALUES(?,?,?)",
            (
                "target",
                2563,
                json.dumps(
                    {
                        "file_format": "xml",
                        "imported_at": "2026-10-11T00:00:00Z",
                        "digest": "a" * 64,
                        "attributes": {"PrivateUnused": "must not be projected"},
                    }
                ),
            ),
        )
        db.commit()
    assert service.search("target", revision, "ETS original") == {2563}
    assert service.search("target", revision, "Imported description") == {2563}
    result = service.lookup("target", revision, {2563})[2563]
    assert result["imported"] == imported and result["manual"] == {"name": "Local"}
    assert result["deviations"] == ["name"]
    assert result["dpt_details"]["imported"]["items"][0]["normalized"] == "1.001"
    assert "PrivateUnused" not in repr(result)
    assert set(result["import_info"]) == {"file_format", "imported_at", "digest"}


def test_corrupt_json_is_storage_failure_and_target_cannot_leak(tmp_path):
    service = ProjectMetadata(tmp_path / "metadata.sqlite3")
    revision = service.store.put(
        "first",
        0,
        {
            "address": "0/0/1",
            "address_format": "three_level",
            "fields": {"name": "First"},
        },
    )
    assert service.lookup("second", 0, {1}) == {}
    assert service.search("second", 0, "First") == set()
    with service.store.connection() as db:
        db.execute("UPDATE addresses SET imported=?", ('{"name":',))
        db.commit()
    with pytest.raises(KnxError, match="knx_storage_failed"):
        service.lookup("first", revision, {1})


@pytest.mark.parametrize("failure", [PermissionError, OSError, sqlite3.OperationalError])
def test_database_setup_failures_are_storage_errors(tmp_path, monkeypatch, failure):
    service = ProjectMetadata(tmp_path / "metadata.sqlite3")
    service.store.put(
        "target",
        0,
        {"address": "0/0/1", "address_format": "three_level", "fields": {"name": "Local"}},
    )

    def fail(*_args, **_kwargs):
        raise failure("private setup detail")

    monkeypatch.setattr(sqlite3, "connect", fail)
    for operation in (
        lambda: service.revision("target"),
        lambda: service.lookup("target", 1, {1}),
        lambda: service.search("target", 1, "Local"),
        lambda: service.selected_labels("target", 1),
    ):
        with pytest.raises(KnxError, match="^knx_storage_failed$"):
            operation()
