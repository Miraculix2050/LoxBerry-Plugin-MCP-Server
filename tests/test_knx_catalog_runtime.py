"""Local read identity, bounded continuation, revocation and worker admission."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from threading import Event

import pytest

from mcpserver.auth.provider import StoredAccessToken
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.knx.catalog_runtime import CatalogCursors, CatalogRuntime
from mcpserver.knx.delegation import read_binding_id
from mcpserver.knx.model import KnxError
from mcpserver.loxone.project.taxonomy import AddressTaxonomyEntry


@pytest.mark.asyncio
async def test_typed_tool_preserves_sparse_sources_and_discovery(reader, monkeypatch):
    from mcp.server.fastmcp import FastMCP

    from mcpserver.knx import catalog_tools

    runtime, access = reader
    monkeypatch.setattr(catalog_tools, "_access", lambda: access)
    server = FastMCP("catalog contract")
    catalog_tools.register_catalog_tool(server, runtime)
    tool = server._tool_manager.get_tool("loxberry_get_knx_catalog")
    assert tool.meta == {"requiredScopes": ["loxone:read", "loxberry:knx:read"]}
    assert tool.annotations.readOnlyHint is True
    result = await server._tool_manager.call_tool("loxberry_get_knx_catalog", {"limit": 1})
    structured = result.model_dump()
    assert structured["ok"] is True
    record = structured["data"]["records"][0]
    assert record["sources"] == {"imported": {}, "manual": {"name": "Local 0"}}
    assert record["local_resolution"]["description"] == "unknown"
    assert structured["data"]["next_cursor"]


@pytest.mark.asyncio
async def test_typed_tool_fails_closed_without_grant_and_sanitizes_storage(reader, monkeypatch):
    from mcp.server.fastmcp import FastMCP

    from mcpserver.knx import catalog_tools

    runtime, access = reader
    monkeypatch.setattr(catalog_tools, "_access", lambda: access)
    server = FastMCP("catalog errors")
    catalog_tools.register_catalog_tool(server, runtime)
    config = runtime.config_store.load()
    runtime.config_store.save(replace(config, loxberry_knx_read_enabled=False))
    denied = (await server._tool_manager.call_tool("loxberry_get_knx_catalog", {})).model_dump()
    assert denied["ok"] is False and denied["data"]["error"] == "permission_denied"
    runtime.config_store.save(config)

    def unavailable(*args, **kwargs):
        raise KnxError("knx_storage_unavailable")

    monkeypatch.setattr(runtime.store, "page", unavailable)
    failed = (await server._tool_manager.call_tool("loxberry_get_knx_catalog", {})).model_dump()
    assert failed["ok"] is False and failed["data"]["error"] == "temporarily_unavailable"


def test_sparse_sources_keep_explicit_empty_false_and_zero():
    from mcpserver.knx.catalog_tools import DptIdentifier, LocalFields

    assert LocalFields(name="", dpts=[], central=False).model_dump() == {
        "name": "",
        "dpts": [],
        "central": False,
    }
    assert (
        DptIdentifier(
            raw="0.000",
            status="format_valid_type_unverified",
            normalized="0.000",
            main=0,
            subtype=0,
        ).model_dump()["subtype"]
        == 0
    )


def test_admin_delegation_has_independent_enable_grant_and_revoke(reader):
    from mcpserver.knx.read_admin import dispatch, snapshot

    runtime, access = reader
    target = "https://first.example"
    config = replace(
        runtime.config_store.load(), loxberry_knx_read_enabled=False, loxberry_knx_read_bindings=()
    )
    runtime.config_store.save(config)
    page = snapshot(config, runtime.auth_store, target)
    assert page["enabled"] is False and page["bindings"][0]["approved"] is False
    assert "synthetic" not in json.dumps(page)
    binding = page["bindings"][0]["binding"]
    granted = runtime.config_store.transaction(
        lambda current, save: dispatch(
            "knx_read_grant",
            {"binding": binding, "policy_revision": page["policy_revision"]},
            current,
            save,
            runtime.auth_store,
            target,
        )
    )
    assert granted["bindings"][0]["approved"] is True and granted["enabled"] is False
    with pytest.raises(PermissionError):
        runtime.read(access)
    enabled = runtime.config_store.transaction(
        lambda current, save: dispatch(
            "knx_read_enable",
            {"enabled": True, "policy_revision": granted["policy_revision"]},
            current,
            save,
            runtime.auth_store,
            target,
        )
    )
    assert runtime.read(access)["total_matching"] == 3
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        dispatch(
            "knx_read_revoke",
            {"binding": binding, "policy_revision": page["policy_revision"]},
            runtime.config_store.load(),
            runtime.config_store.save,
            runtime.auth_store,
            target,
        )
    runtime.config_store.transaction(
        lambda current, save: dispatch(
            "knx_read_revoke",
            {"binding": binding, "policy_revision": enabled["policy_revision"]},
            current,
            save,
            runtime.auth_store,
            target,
        )
    )
    with pytest.raises(PermissionError):
        runtime.read(access)


def test_admin_delegation_rejects_family_revocation_and_foreign_target(reader):
    from mcpserver.knx.read_admin import dispatch, snapshot

    runtime, _ = reader
    config = runtime.config_store.load()
    page = snapshot(config, runtime.auth_store, "https://first.example")
    runtime.auth_store.mutate(lambda document: document["families"]["family"].update(revoked=True))
    with pytest.raises(KnxError, match="knx_delegation_unavailable"):
        dispatch(
            "knx_read_grant",
            {"binding": page["bindings"][0]["binding"], "policy_revision": page["policy_revision"]},
            config,
            runtime.config_store.save,
            runtime.auth_store,
            "https://first.example",
        )
    from mcpserver.admin import AdminError
    from mcpserver.knx.admin import dispatch_knx

    with pytest.raises(AdminError, match="target changed"):
        dispatch_knx(
            "knx_read_enable",
            {"target": "foreign", "enabled": True, "policy_revision": page["policy_revision"]},
            runtime.config_store,
        )


@pytest.fixture
def reader(tmp_path):
    auth = AtomicJsonAuthStore(tmp_path / "auth.json")
    family = {
        "client_id": "client",
        "identity_id": "identity",
        "miniserver_id": "ms",
        "scope": "loxone:read loxberry:knx:read",
        "expires_at": 2_000_000_000,
        "revoked": False,
    }
    auth.mutate(lambda document: document["families"].update({"family": family}))
    config = replace(
        PluginConfig.defaults(),
        loxone_endpoint="https://first.example",
        loxberry_knx_read_enabled=True,
    )
    config = replace(config, loxberry_knx_read_bindings=(read_binding_id(config, auth, family),))
    configs = AtomicConfigStore(tmp_path / "config.json")
    configs.save(config)
    runtime = CatalogRuntime(tmp_path / "metadata.sqlite3", configs, auth, asyncio.Semaphore(1))
    for index in range(3):
        runtime.store.put(
            "https://first.example",
            index,
            {
                "address": f"0/0/{index}",
                "address_format": "three_level",
                "fields": {"name": f"Local {index}"},
            },
        )
    access = StoredAccessToken(
        token="synthetic",
        client_id="client",
        scopes=["loxone:read", "loxberry:knx:read"],
        expires_at=2_000_000_000,
        resource="https://public.example/plugins/mcpserver/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="ms",
    )
    return runtime, access


def test_large_catalog_continuation_renews_only_after_live_revision_bound_read(reader, monkeypatch):
    runtime, access = reader
    clock = [0.0]
    monkeypatch.setattr("mcpserver.knx.catalog_runtime.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("mcpserver.knx.catalog_runtime.time.time", lambda: 1_700_000_000 + clock[0])
    target = "https://first.example"
    runtime.store.restore(
        target,
        3,
        {
            "schema_version": 1,
            "records": [
                {
                    "address_id": index,
                    "address": f"0/0/{index}",
                    "address_format": "three_level",
                    "imported": {},
                    "overrides": {"name": f"Synthetic {index}"},
                }
                for index in range(151)
            ],
        },
    )
    cursor = None
    first_cursor = None
    seen = []
    for _ in range(151):
        page = runtime.read(access, limit=1, cursor=cursor)
        assert page["revision"] == 4
        seen.extend(row["address_id"] for row in page["records"])
        cursor = page["next_cursor"]
        first_cursor = first_cursor or cursor
        clock[0] += 2.1  # Below the rate quota, beyond the first cursor's lifetime.
    assert seen == list(range(151)) and cursor is None and clock[0] > 300
    with pytest.raises(ValueError, match="cursor"):
        runtime.read(access, limit=1, cursor=first_cursor)
    clock[0] += 2.1
    fresh = runtime.read(access, limit=1)
    runtime.store.put(
        target,
        4,
        {"address": "0/0/0", "address_format": "three_level", "fields": {"name": "Revised"}},
    )
    clock[0] += 2.1
    with pytest.raises(KnxError, match="revision_conflict"):
        runtime.read(access, limit=1, cursor=fresh["next_cursor"])


def test_catalog_pages_and_summary_keep_identity_without_project_download(reader):
    runtime, access = reader
    first = runtime.read(access, limit=1)
    second = runtime.read(access, limit=1, cursor=first["next_cursor"])
    assert first["records"][0]["address_id"] == 0
    assert second["records"][0]["address_id"] == 1
    assert first["revision"] == second["revision"] == 3
    assert first["labels_revision"] == second["labels_revision"]
    assert len(first["target_id"]) == 64 and "https://" not in json.dumps(first)
    summary = runtime.read(access, view="summary")
    assert summary["records"] == [] and summary["total_matching"] == 3
    assert summary["next_cursor"] is None


@pytest.mark.parametrize(
    "arguments",
    [
        {"limit": 2},
        {"query": "Local"},
        {"source": "manual"},
        {"deviations_only": True},
        {"address": "0/0/0"},
    ],
)
def test_catalog_cursor_binds_every_selection(reader, arguments):
    runtime, access = reader
    first = runtime.read(access, limit=1)
    with pytest.raises(ValueError, match="cursor"):
        runtime.read(access, **{"limit": 1, "cursor": first["next_cursor"], **arguments})


def test_catalog_revision_change_and_live_revocation_reject_old_cursor(reader):
    runtime, access = reader
    first = runtime.read(access, limit=1)
    runtime.store.put(
        "https://first.example",
        3,
        {"address": "0/0/0", "address_format": "three_level", "fields": {"name": "Changed"}},
    )
    with pytest.raises(KnxError, match="revision_conflict"):
        runtime.read(access, limit=1, cursor=first["next_cursor"])
    runtime.auth_store.mutate(
        lambda document: document["families"]["family"].update({"revoked": True})
    )
    with pytest.raises(PermissionError):
        runtime.read(access, limit=1)


def test_revocation_during_worker_never_releases_data(reader, monkeypatch):
    runtime, access = reader
    original = runtime.store.page

    def page(*args, **kwargs):
        result = original(*args, **kwargs)
        runtime.auth_store.mutate(
            lambda document: document["families"]["family"].update({"revoked": True})
        )
        return result

    monkeypatch.setattr(runtime.store, "page", page)
    with pytest.raises(PermissionError):
        runtime.read(access)


def test_whole_row_budget_continuation_does_not_drop_long_metadata(reader):
    runtime, access = reader
    for index in range(3, 23):
        runtime.store.put(
            "https://first.example",
            index,
            {
                "address": f"0/0/{index}",
                "address_format": "three_level",
                "fields": {"name": f"Long {index}", "description": "x" * 4096},
            },
        )
    first = runtime.read(access, limit=100)
    assert first["page_truncated"]
    assert (
        len(json.dumps(first, separators=(",", ":"), ensure_ascii=False).encode()) <= 65536 - 1024
    )
    second = runtime.read(access, limit=100, cursor=first["next_cursor"])
    combined = first["records"] + second["records"]
    assert [row["address_id"] for row in combined] == list(range(23))
    assert all(len(row["sources"]["manual"]["description"]) == 4096 for row in combined[3:])


def test_signed_cursor_is_short_lived_and_server_bound():
    codec = CatalogCursors()
    cursor = codec.encode("scope", 5, 3, 300)
    assert codec.decode("scope", cursor, 100) == (5, 3, 300)
    for scope, value, now in [
        ("scope", cursor, 300),
        ("changed", cursor, 100),
        ("scope", cursor[:-2] + "xx", 100),
        ("scope", "x" * 513, 100),
    ]:
        with pytest.raises(ValueError):
            codec.decode(scope, value, now)
    with pytest.raises(ValueError):
        CatalogCursors().decode("scope", cursor, 100)


def test_manual_prefix_inventory_is_readable_without_any_single_address(reader):
    runtime, access = reader
    for index in range(3):
        runtime.store.delete("https://first.example", 3 + index, index)
    runtime.config_store.mutate(
        lambda config: replace(
            config,
            knx_address_taxonomy_endpoint="https://first.example",
            knx_address_taxonomy=(
                AddressTaxonomyEntry("1", "Three-level context", "three_level"),
                AddressTaxonomyEntry("1", "Two-level context", "two_level"),
            ),
        )
    )
    first = runtime.read(access, kind="prefix_labels", limit=1)
    second = runtime.read(access, kind="prefix_labels", limit=1, cursor=first["next_cursor"])
    assert first["records"] == second["records"] == []
    assert first["total_matching"] == second["total_matching"] == 2
    assert first["count_scope"] == "matching_active_prefixes"
    assert first["prefix_labels"][0]["prefix_id"] != second["prefix_labels"][0]["prefix_id"]
    assert runtime.read(access, kind="prefix_labels", query="Two-level")["total_matching"] == 1
    assert runtime.read(access, kind="prefix_labels", source="imported")["total_matching"] == 0
    assert runtime.read(access, kind="prefix_labels", view="summary")["prefix_labels"] == []
    with pytest.raises(ValueError, match="cursor"):
        runtime.read(access, limit=1, cursor=first["next_cursor"])
    with pytest.raises(ValueError, match="record kind"):
        runtime.read(access, kind="prefix_labels", address="1/2/3")


def test_manual_prefix_change_invalidates_continuation_before_catalog_query(reader, monkeypatch):
    runtime, access = reader
    first = runtime.read(access, limit=1)
    runtime.config_store.mutate(
        lambda config: replace(
            config,
            knx_address_taxonomy_endpoint="https://first.example",
            knx_address_taxonomy=(AddressTaxonomyEntry("0", "New context", "three_level"),),
        )
    )
    monkeypatch.setattr(
        runtime.store, "page", lambda *args, **kwargs: pytest.fail("stale cursor queried catalog")
    )
    with pytest.raises(ValueError, match="cursor"):
        runtime.read(access, limit=1, cursor=first["next_cursor"])


@pytest.mark.asyncio
async def test_cancelled_reader_holds_shared_slot_until_real_worker_finishes(reader, monkeypatch):
    runtime, access = reader
    started, finish = Event(), Event()

    def blocked(*args, **kwargs):
        started.set()
        assert finish.wait(timeout=5)
        return {}

    monkeypatch.setattr(runtime, "read", blocked)
    task = asyncio.create_task(runtime.run(access))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.admission.locked()
    finish.set()
    await asyncio.wait_for(runtime.admission.acquire(), timeout=5)
    runtime.admission.release()
