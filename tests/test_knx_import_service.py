from __future__ import annotations

import base64
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from mcpserver import admin
from mcpserver.admin import AdminError
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.knx.admin import dispatch_knx
from mcpserver.knx.catalog_service import CatalogService
from mcpserver.knx.drafts import DraftStore
from mcpserver.knx.import_repository import ImportRepository
from mcpserver.knx.import_service import select_candidates
from mcpserver.knx.model import KnxError
from mcpserver.knx.store import KnxStore
from mcpserver.knx.xml_adapter import NAMESPACE, parse_xml


def document(rows: str) -> bytes:
    return f'<GroupAddress-Export xmlns="{NAMESPACE}">{rows}</GroupAddress-Export>'.encode()


def apply_payload(preview: dict) -> dict:
    return {key: preview[key] for key in ("target", "draft_id", "preview_token")}


@pytest.mark.parametrize(
    ("raw", "code"),
    [(b"<invalid", "knx_xml_invalid"), (b"<!DOCTYPE x><x/>", "knx_xml_unsafe")],
)
def test_native_module_entrypoint_preserves_knx_error_codes(
    tmp_path: Path, raw: bytes, code: str
) -> None:
    configuration = tmp_path / "config.json"
    AtomicConfigStore(configuration).save(
        replace(PluginConfig.defaults(), loxone_endpoint="http://192.168.10.20")
    )
    environment = {
        **os.environ,
        "MCPSERVER_CONFIG": str(configuration),
        "LBPDATA": str(tmp_path),
        "MCPSERVER_KNX_ADMIN": "1",
        "MCPSERVER_KNX_ADMIN_SESSION": "a" * 64,
    }
    page = subprocess.run(
        [sys.executable, "-m", "mcpserver.admin"],
        input=json.dumps({"action": "knx_page", "payload": {}}),
        text=True,
        capture_output=True,
        check=True,
        env=environment,
        timeout=30,
    )
    request = {
        "action": "knx_import_load",
        "payload": {
            "target": json.loads(page.stdout)["data"]["target"],
            "file": base64.b64encode(raw).decode(),
        },
    }
    result = subprocess.run(
        [sys.executable, "-m", "mcpserver.admin"],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=True,
        env=environment,
        timeout=30,
    )
    assert json.loads(result.stdout) == {
        "ok": False,
        "error": {"code": code, "message": "KNX operation rejected"},
    }


def test_identical_duplicates_merge_but_conflicting_candidates_require_explicit_choice() -> None:
    raw = document(
        '<GroupAddress Address="1/2/3" Name="One"/>'
        '<GroupAddress Address="1/2/3" Name="One"/>'
        '<GroupAddress Address="1/2/3" Name="Two"/>'
    )
    parsed = parse_xml(raw)
    unresolved = select_candidates(parsed)
    assert unresolved.merged_duplicates == 1
    assert not unresolved.addresses
    assert len(unresolved.conflicts) == 1
    assert len(unresolved.conflicts[0]["candidates"]) == 2
    chosen = select_candidates(parsed, {"address:2563": 1})
    assert not chosen.conflicts
    assert chosen.addresses[0].fields["name"] == "Two"
    with pytest.raises(KnxError, match="knx_choices_invalid"):
        select_candidates(parsed, {"address:2563": True})
    with pytest.raises(KnxError, match="knx_choices_invalid"):
        select_candidates(parsed, {"address:9999": 0})


def test_draft_is_session_target_revision_and_expiry_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "knx" / "drafts.sqlite3"
    drafts = DraftStore(path, "a" * 64)
    raw = document('<GroupAddress Address="1/2/3" Name="One"/>')
    identifier = drafts.create("target", 7, raw, {"encoding": "auto"})
    assert drafts.load(identifier, "target", 7) == (raw, {"encoding": "auto"})
    with pytest.raises(KnxError, match="knx_draft_expired"):
        DraftStore(path, "b" * 64).load(identifier, "target", 7)
    with pytest.raises(KnxError, match="knx_target_conflict"):
        drafts.load(identifier, "other", 7)
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        drafts.load(identifier, "target", 8)
    monkeypatch.setattr("mcpserver.knx.drafts.time.time", lambda: 9e12)
    with pytest.raises(KnxError, match="knx_draft_expired"):
        drafts.load(identifier, "target", 7)
    with drafts.connection() as db:
        assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 0


def test_failed_draft_replacement_retains_previous_valid_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drafts = DraftStore(tmp_path / "drafts.sqlite3", "a" * 64)
    identifier = drafts.create("target", 3, b"old", {})
    monkeypatch.setattr("mcpserver.knx.drafts.MAX_DRAFT_BYTES", 1)
    with pytest.raises(KnxError, match="knx_draft_limit"):
        drafts.create("target", 3, b"new", {})
    assert drafts.load(identifier, "target", 3)[0] == b"old"
    drafts.discard(identifier)
    with pytest.raises(KnxError, match="knx_draft_expired"):
        drafts.load(identifier, "target", 3)


def test_merge_reimport_updates_source_fields_but_preserves_each_override(tmp_path: Path) -> None:
    store = KnxStore(tmp_path / "metadata.sqlite3")
    imports = ImportRepository(store)
    initial = parse_xml(
        document('<GroupAddress Address="1/2/3" Name="ETS" Description="Old" Central="true"/>')
    )
    imports.apply(
        "target", 0, initial, select_candidates(initial), set(), {"complete_export": False}
    )
    store.put(
        "target",
        1,
        {
            "address_format": "three_level",
            "address": "1/2/3",
            "fields": {"description": "Local override"},
        },
    )
    next_file = parse_xml(document('<GroupAddress Address="1/2/3" Name="New ETS"/>'))
    assert imports.apply("target", 2, next_file, select_candidates(next_file), set(), {}) == 3
    row = store.page("target")["items"][0]
    assert row["imported"] == {"name": "New ETS"}
    assert row["overrides"] == {"description": "Local override"}
    assert row["effective"] == {"name": "New ETS", "description": "Local override"}
    store.put("target", 3, {"address_format": "three_level", "address": "1/2/3", "fields": {}})
    assert store.page("target")["items"][0]["effective"] == {"name": "New ETS"}
    assert imports.snapshot("other")["addresses"] == {}


def test_import_conflict_and_group_label_failure_roll_back_every_catalog_write(
    tmp_path: Path,
) -> None:
    store = KnxStore(tmp_path / "metadata.sqlite3")
    imports = ImportRepository(store)
    parsed = parse_xml(
        document(
            '<GroupRange Name="Main" RangeStart="2048" RangeEnd="4095">'
            '<GroupAddress Address="1/2/3" Name="ETS"/></GroupRange>'
        )
    )
    selection = select_candidates(parsed)
    imports.apply("target", 0, parsed, selection, {("three_level", "1")}, {})
    before = imports.snapshot("target")
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        imports.apply("target", 0, parsed, selection, set(), {})
    assert imports.snapshot("target") == before
    long_label = parse_xml(
        document(
            f'<GroupRange Name="{"x" * 81}" RangeStart="2048" RangeEnd="4095">'
            '<GroupAddress Address="1/2/4" Name="New"/></GroupRange>'
        )
    )
    with pytest.raises(KnxError, match="knx_field_invalid"):
        imports.apply(
            "target", 1, long_label, select_candidates(long_label), {("three_level", "1")}, {}
        )
    assert imports.snapshot("target") == before
    assert imports.selected_labels("target") == [
        {"address_format": "three_level", "prefix": "1", "label": "Main"}
    ]


def test_admin_import_preview_binding_and_explicit_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LBPDATA", str(tmp_path))
    monkeypatch.setenv("MCPSERVER_KNX_ADMIN_SESSION", "a" * 64)
    config = AtomicConfigStore(tmp_path / "config.json")
    config.save(replace(PluginConfig.defaults(), loxone_endpoint="http://192.168.10.20"))
    state = dispatch_knx("knx_page", {}, config)
    raw = document('<GroupAddress Address="1/2/3" Name="ETS"/>')
    preview = dispatch_knx(
        "knx_import_load",
        {"target": state["target"], "file": base64.b64encode(raw).decode()},
        config,
    )
    assert preview["additions"] == 1
    assert dispatch_knx("knx_page", {}, config)["total"] == 0

    updated = dispatch_knx(
        "knx_import_preview",
        {"target": state["target"], "draft_id": preview["draft_id"], "offset": 0},
        config,
    )
    with pytest.raises(AdminError) as old:
        dispatch_knx("knx_import_apply", apply_payload(preview), config)
    assert old.value.code == "knx_preview_changed"
    applied = dispatch_knx("knx_import_apply", apply_payload(updated), config)
    assert applied["revision"] == 1
    assert applied["items"][0]["imported"] == {"name": "ETS"}
    assert not applied["draft_cleanup_pending"]
    with pytest.raises(AdminError) as expired:
        dispatch_knx("knx_import_apply", apply_payload(updated), config)
    assert expired.value.code == "knx_draft_expired"


@pytest.mark.parametrize("policy", ["keep_unknown", "retain_import_name"])
def test_complete_replace_preserves_manual_records_and_requires_orphan_name_decision(
    tmp_path: Path, policy: str
) -> None:
    store = KnxStore(tmp_path / "metadata.sqlite3")
    repository = ImportRepository(store)
    service = CatalogService(
        repository, DraftStore(tmp_path / "drafts.sqlite3", "a" * 64), "target", []
    )
    initial = parse_xml(
        document(
            '<GroupAddress Address="1/2/3" Name="Removed"/>'
            '<GroupAddress Address="1/2/4" Name="ETS" Description="Old"/>'
        )
    )
    repository.apply("target", 0, initial, select_candidates(initial), set(), {})
    store.put(
        "target",
        1,
        {
            "address_format": "three_level",
            "address": "1/2/4",
            "fields": {"description": "Manual description"},
        },
    )
    store.put(
        "target",
        2,
        {"address_format": "three_level", "address": "1/2/5", "fields": {"name": "Manual record"}},
    )
    incoming = document('<GroupAddress Address="1/2/6" Name="New"/>')
    partial = service.create(incoming, encoding="auto", complete_export=False)
    with pytest.raises(KnxError, match="knx_import_mode_invalid"):
        service.preview(partial["draft_id"], {"mode": "replace"})
    preview = service.create(incoming, encoding="auto", complete_export=True)
    replacement = service.preview(preview["draft_id"], {"mode": "replace"})
    assert replacement["removals"] == 1
    assert replacement["preserved_overrides"] == 1
    assert replacement["name_policy_required"]
    assert {row["kind"] for row in replacement["changes"]} == {"added", "removed", "preserved"}
    with pytest.raises(KnxError, match="knx_orphan_name_policy_required"):
        service.apply(preview["draft_id"], replacement["preview_token"])
    assert store.page("target")["revision"] == 3
    confirmed = service.preview(preview["draft_id"], {"orphan_name_policy": policy})
    service.apply(preview["draft_id"], confirmed["preview_token"])
    rows = {row["address"]: row for row in store.page("target")["items"]}
    assert set(rows) == {"1/2/4", "1/2/5", "1/2/6"}
    assert rows["1/2/4"]["imported"] == {}
    assert rows["1/2/4"]["overrides"] == {
        "description": "Manual description",
        **({"name": "ETS"} if policy == "retain_import_name" else {}),
    }
    assert not rows["1/2/4"]["import_info"]
    assert rows["1/2/5"]["overrides"] == {"name": "Manual record"}
    assert KnxStore(store.path).page("target") == store.page("target")
    # Deliberately unknown names on preserved overrides must survive JSON exchange too.
    exchanged = store.export("target")
    store.restore("other", 0, exchanged)
    assert [row["effective"] for row in store.page("other")["items"]] == [
        row["effective"] for row in store.page("target")["items"]
    ]


def test_conflicts_and_changes_have_independent_bounded_preview_pages(tmp_path: Path) -> None:
    store = KnxStore(tmp_path / "metadata.sqlite3")
    service = CatalogService(
        ImportRepository(store), DraftStore(tmp_path / "drafts.sqlite3", "a" * 64), "t", []
    )
    raw = document(
        "".join(
            f'<GroupAddress Address="0/0/{number}" Name="{name}"/>'
            for number in range(65)
            for name in ("A", "B")
        )
    )
    frame = service.create(raw, encoding="auto", complete_export=False)
    assert frame["conflict_count"] == 65 and len(frame["conflicts"]) == 5
    page = service.preview(frame["draft_id"], {"conflict_offset": 60})
    assert len(page["conflicts"]) == 5 and not page["has_more_conflicts"]
    choices = {f"address:{number}": 0 for number in range(65)}
    selected = service.preview(frame["draft_id"], {"choices": choices, "offset": 50})
    assert selected["conflict_count"] == 0 and len(selected["changes"]) == 15
    assert selected["changes_count"] == 65
    assert store.page("t")["total"] == 0
    service.apply(frame["draft_id"], selected["preview_token"])
    assert store.page("t")["total"] == 65
    changed = service.create(
        raw.replace(b'Name="A"', b'Name="C"'), encoding="auto", complete_export=False
    )
    revised = service.preview(changed["draft_id"], {"choices": choices, "offset": 50})
    assert revised["updates"] == 65 and len(revised["changes"]) == 15
    assert revised["changes"][0]["old_imported"] == {"name": "A"}


def test_invalid_file_does_not_destroy_previous_preview_or_catalog(tmp_path: Path) -> None:
    store = KnxStore(tmp_path / "metadata.sqlite3")
    service = CatalogService(
        ImportRepository(store), DraftStore(tmp_path / "drafts.sqlite3", "a" * 64), "t", []
    )
    frame = service.create(
        document('<GroupAddress Address="1/2/3" Name="ETS"/>'),
        encoding="auto",
        complete_export=False,
    )
    with pytest.raises(KnxError):
        service.create(b"<not-xml", encoding="auto", complete_export=False)
    assert store.page("t")["total"] == 0
    service.apply(frame["draft_id"], frame["preview_token"])
    assert store.page("t")["total"] == 1


def test_version_one_migration_preserves_labels_records_and_revision(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE targets(target TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0);"
            "CREATE TABLE addresses(target TEXT NOT NULL, address INTEGER NOT NULL, "
            "format TEXT NOT NULL, original TEXT NOT NULL, imported TEXT NOT NULL DEFAULT '{}', "
            "overrides TEXT NOT NULL, PRIMARY KEY(target,address), "
            "FOREIGN KEY(target) REFERENCES targets(target)); PRAGMA user_version=1;"
        )
        db.execute("INSERT INTO targets VALUES('t',17)")
        db.execute(
            "INSERT INTO addresses VALUES('t',2563,'three_level','1/2/3','{}',?)",
            (json.dumps({"name": "Legacy"}),),
        )
    store = KnxStore(path)
    before = store.page("t")
    assert before["revision"] == 17 and before["items"][0]["effective"] == {"name": "Legacy"}
    assert KnxStore(path).page("t") == before
    with store.connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
    repository = ImportRepository(store)
    parsed = parse_xml(document('<GroupAddress Address="1/2/3" Name="ETS"/>'))
    repository.apply("t", 17, parsed, select_candidates(parsed), set(), {})
    assert store.page("t")["items"][0]["effective"] == {"name": "Legacy"}


def test_reimport_preview_allows_deselecting_a_lengthened_active_group(tmp_path: Path) -> None:
    store = KnxStore(tmp_path / "metadata.sqlite3")
    service = CatalogService(
        ImportRepository(store), DraftStore(tmp_path / "drafts.sqlite3", "a" * 64), "t", []
    )
    raw = document(
        '<GroupRange Name="Short" RangeStart="2048" RangeEnd="4095">'
        '<GroupAddress Address="1/2/3" Name="ETS"/></GroupRange>'
    )
    frame = service.create(raw, encoding="auto", complete_export=False)
    selected = service.preview(frame["draft_id"], {"selected_groups": ["group:three_level:1"]})
    service.apply(frame["draft_id"], selected["preview_token"])
    long_name = "x" * 81
    next_frame = service.create(
        raw.replace(b"Short", long_name.encode()), encoding="auto", complete_export=False
    )
    assert next_frame["invalid_labels"] == ["group:three_level:1"]
    with pytest.raises(KnxError, match="knx_label_selection_invalid"):
        service.apply(next_frame["draft_id"], next_frame["preview_token"])
    corrected = service.preview(next_frame["draft_id"], {"selected_groups": []})
    service.apply(next_frame["draft_id"], corrected["preview_token"])
    assert not ImportRepository(store).selected_labels("t")
    assert (
        ImportRepository(store).snapshot("t")["groups"][("three_level", "1")]["fields"]["name"]
        == long_name
    )


def test_active_group_labels_share_bound_and_manual_save_remains_separate(tmp_path: Path) -> None:
    store = KnxStore(tmp_path / "metadata.sqlite3")
    manual = [
        {"address_format": "three_level", "prefix": str(number), "label": "M"}
        for number in range(32)
    ]
    manual += [
        {"address_format": "three_level", "prefix": f"0/{number}", "label": "M"}
        for number in range(8)
    ]
    # Different display styles are distinct prefix identities.
    manual += [
        {"address_format": "two_level", "prefix": str(number), "label": "M"} for number in range(32)
    ]
    service = CatalogService(
        ImportRepository(store), DraftStore(tmp_path / "drafts.sqlite3", "a" * 64), "t", manual
    )
    raw = document(
        "".join(
            f'<GroupRange RangeStart="{(main << 11) + (middle << 8)}" '
            f'RangeEnd="{(main << 11) + (middle << 8) + 255}" Name="G"/>'
            for main in (1, 2)
            for middle in range(8)
        )
    )
    # Middle ranges require their main parent; a free hierarchy is not accepted.
    with pytest.raises(KnxError, match="knx_free_hierarchy_unsupported"):
        service.create(raw, encoding="auto", complete_export=False)
    raw = document(
        "".join(
            f'<GroupRange RangeStart="{main << 11}" RangeEnd="{(main << 11) + 2047}" Name="G">'
            + "".join(
                f'<GroupRange RangeStart="{(main << 11) + (middle << 8)}" '
                f'RangeEnd="{(main << 11) + (middle << 8) + 255}" Name="G"/>'
                for middle in range(8)
            )
            + "</GroupRange>"
            for main in range(1, 9)
        )
    )
    frame = service.create(
        raw, encoding="auto", complete_export=False, address_format="three_level"
    )
    choices = [f"group:three_level:{main}/{middle}" for main in range(1, 9) for middle in range(8)]
    with pytest.raises(KnxError, match="knx_label_limit"):
        service.preview(frame["draft_id"], {"selected_groups": choices})
    assert store.page("t")["total"] == 0
    confirmed = service.preview(frame["draft_id"], {"selected_groups": choices[:56]})
    service.apply(frame["draft_id"], confirmed["preview_token"])
    assert len(ImportRepository(store).selected_labels("t")) == 56


def test_generic_admin_save_preserves_concurrently_changed_omitted_knx_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcpserver.loxone.project.taxonomy import parse_taxonomy

    monkeypatch.setenv("LBPDATA", str(tmp_path))
    config = AtomicConfigStore(tmp_path / "config.json")
    config.save(replace(PluginConfig.defaults(), loxone_endpoint="http://192.168.10.20"))
    actual_load = config.load
    previous = actual_load()
    document = previous.to_document()
    document.pop("knx_address_taxonomy", None)
    document.pop("knx_taxonomy_targets", None)
    newer = parse_taxonomy([{"address_format": "three_level", "prefix": "1/2", "label": "New"}])

    def load_then_simulate_concurrent_manual_save() -> PluginConfig:
        snapshot = actual_load()
        config.mutate(
            lambda current: replace(
                current,
                knx_address_taxonomy_endpoint="http://192.168.10.20",
                knx_address_taxonomy=newer,
            )
        )
        return snapshot

    monkeypatch.setattr(config, "load", load_then_simulate_concurrent_manual_save)
    monkeypatch.setattr(admin, "_config_store", lambda: config)
    monkeypatch.setattr(admin, "_restart_service", lambda: None)
    monkeypatch.setattr(admin, "_sessions", lambda: [])
    monkeypatch.setattr(admin, "_service_response", lambda: {})
    admin._save(document)
    assert actual_load().knx_address_taxonomy == newer


def test_admin_manual_label_change_invalidates_open_import_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LBPDATA", str(tmp_path))
    monkeypatch.setenv("MCPSERVER_KNX_ADMIN_SESSION", "a" * 64)
    config = AtomicConfigStore(tmp_path / "config.json")
    config.save(replace(PluginConfig.defaults(), loxone_endpoint="http://192.168.10.20"))
    state = dispatch_knx("knx_page", {}, config)
    preview = dispatch_knx(
        "knx_import_load",
        {
            "target": state["target"],
            "file": base64.b64encode(
                document('<GroupAddress Address="1/2/3" Name="ETS"/>')
            ).decode(),
        },
        config,
    )
    dispatch_knx(
        "knx_taxonomy",
        {
            "target": state["target"],
            "taxonomy_revision": state["taxonomy_revision"],
            "entries": [{"address_format": "three_level", "prefix": "1/2", "label": "Manual"}],
        },
        config,
    )
    with pytest.raises(AdminError) as conflict:
        dispatch_knx("knx_import_apply", apply_payload(preview), config)
    assert conflict.value.code == "knx_revision_conflict"
    assert dispatch_knx("knx_page", {}, config)["total"] == 0
