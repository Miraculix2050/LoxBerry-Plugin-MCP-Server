"""Actual tool contracts, reconciliation, fresh authorization and bounded views."""

import asyncio
import hashlib
import json
from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

from mcpserver.auth.provider import StoredAccessToken
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.knx import correction_tools
from mcpserver.knx.catalog import labels_revision
from mcpserver.knx.catalog_runtime import CatalogRuntime
from mcpserver.knx.correction_runtime import CorrectionRuntime
from mcpserver.knx.delegation import draft_binding_id, read_binding_id

TARGET = "https://first.example"
READ = "loxberry_get_knx_correction_drafts"
PREPARE = "loxberry_prepare_knx_corrections"


@pytest.fixture
def client(tmp_path, monkeypatch):
    auth = AtomicJsonAuthStore(tmp_path / "auth.json")
    scopes = ["loxone:read", "loxberry:knx:read", "loxberry:knx:drafts"]
    family = dict(
        client_id="client",
        identity_id="identity",
        miniserver_id="ms",
        scope=" ".join(scopes),
        expires_at=2_000_000_000,
        revoked=False,
    )
    auth.mutate(lambda document: document["families"].update(family=family))
    config = replace(
        PluginConfig.defaults(),
        loxone_endpoint=TARGET,
        loxberry_knx_read_enabled=True,
        loxberry_knx_drafts_enabled=True,
    )
    config = replace(
        config,
        loxberry_knx_read_bindings=(read_binding_id(config, auth, family),),
        loxberry_knx_drafts_bindings=(draft_binding_id(config, auth, family),),
    )
    configs = AtomicConfigStore(tmp_path / "config.json")
    configs.save(config)
    runtime = CatalogRuntime(tmp_path / "metadata.sqlite3", configs, auth, asyncio.Semaphore(1))
    runtime.store.put(
        TARGET,
        0,
        dict(address="0/0/0", address_format="three_level", fields={"name": "Existing local name"}),
    )
    access = StoredAccessToken(
        token="synthetic",
        client_id="client",
        scopes=scopes,
        expires_at=2_000_000_000,
        resource="https://public.example/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="ms",
    )
    monkeypatch.setattr(correction_tools, "_access", lambda: access)
    server = FastMCP("draft contracts")
    correction_tools.register_correction_tools(server, runtime, None)
    return server, runtime


def arguments(runtime):
    with runtime.store.connection() as db:
        revision = runtime.store.revision(db, TARGET)
    return dict(
        target_id=hashlib.sha256(TARGET.encode()).hexdigest(),
        catalog_revision=revision,
        manual_revision=labels_revision(runtime.config_store.load(), TARGET),
        request_id="a" * 32,
        changes=[
            dict(
                destination="local_metadata",
                kind="address",
                address="0/0/0",
                address_format="three_level",
                field="description",
                operation="set",
                value="",
            )
        ],
    )


async def call(server, tool, arguments):
    return (await server._tool_manager.call_tool(tool, arguments)).model_dump()


@pytest.mark.asyncio
async def test_creation_reconciles_without_id_and_does_not_apply(client):
    server, runtime = client
    args = arguments(runtime)
    created = await call(server, PREPARE, args)
    assert created["ok"] is True
    assert created["data"]["applies_changes"] is False
    assert created["data"]["exports_file"] is False
    resolved = await call(server, READ, {"request_id": args["request_id"]})
    assert resolved["data"]["draft"]["draft_id"] == created["data"]["draft_id"]
    change = resolved["data"]["changes"][0]
    assert change["proposed"] == {"state": "value", "value": "", "truncated": False}
    assert change["manual"]["state"] == "missing"
    assert (await call(server, PREPARE, args))["data"] == created["data"]
    assert arguments(runtime)["catalog_revision"] == args["catalog_revision"]


@pytest.mark.asyncio
async def test_continuation_rejects_revision_change_and_marks_truncation(client):
    server, runtime = client
    args = arguments(runtime)
    args["changes"] *= 1
    args["changes"][0]["value"] = "x" * 300
    args["changes"].append(dict(args["changes"][0], field="name", value="Proposed local name"))
    created = (await call(server, PREPARE, args))["data"]
    first = await call(server, READ, {"draft_id": created["draft_id"], "limit": 1})
    assert first["data"]["changes"][0]["proposed"]["truncated"] is True
    assert first["data"]["next_offset"] == 1
    missing = await call(server, READ, {"draft_id": created["draft_id"], "offset": 1})
    assert missing["data"]["error"] == "invalid_input"
    update = dict(args, request_id="b" * 32, draft_id=created["draft_id"], draft_revision=1)
    assert (await call(server, PREPARE, update))["data"]["draft_revision"] == 2
    stale = await call(
        server, READ, dict(draft_id=created["draft_id"], offset=1, expected_draft_revision=1)
    )
    assert stale["data"]["error"] == "knx_revision_conflict"


@pytest.mark.asyncio
async def test_warm_draft_requires_fresh_independent_grant(client):
    server, runtime = client
    created = (await call(server, PREPARE, arguments(runtime)))["data"]
    runtime.config_store.mutate(lambda config: replace(config, loxberry_knx_drafts_bindings=()))
    denied = await call(server, READ, {"draft_id": created["draft_id"]})
    assert denied["data"]["error"] == "permission_denied"


@pytest.mark.asyncio
async def test_private_invalid_input_is_sanitized_inside_actual_sdk(client):
    server, runtime = client
    args = arguments(runtime)
    args["changes"][0]["value"] = {"private-marker": "private proposed information"}
    result = await call(server, PREPARE, args)
    assert result["data"]["error"] == "invalid_input"
    assert "private" not in json.dumps(result)
    tool = server._tool_manager.get_tool(PREPARE)
    assert tool.parameters["properties"]["changes"]["maxItems"] == 50
    assert tool.meta["requiredScopes"][-1] == "loxberry:knx:drafts"


@pytest.mark.asyncio
async def test_cancelled_caller_retains_admission_until_real_worker_finishes(client, monkeypatch):
    _, catalog = client
    runtime = CorrectionRuntime(catalog)
    started, finish = Event(), Event()

    def blocked(*args):
        started.set()
        assert finish.wait(5)
        return {"completed": True}

    monkeypatch.setattr(runtime, "execute", blocked)
    task = asyncio.create_task(runtime.run(None, "prepare", {}))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert catalog.admission.locked()
    finally:
        finish.set()
    await asyncio.wait_for(catalog.admission.acquire(), timeout=3)
    catalog.admission.release()


@pytest.mark.asyncio
async def test_revoke_during_planning_prevents_persistence(client, monkeypatch):
    from mcpserver.knx.correction_service import CorrectionService

    server, runtime = client
    original = CorrectionService.plan

    def revoked_plan(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        runtime.auth_store.mutate(
            lambda document: document["families"]["family"].update(revoked=True)
        )
        return result

    monkeypatch.setattr(CorrectionService, "plan", revoked_plan)
    result = await call(server, PREPARE, arguments(runtime))
    assert result["data"]["error"] == "permission_denied"
    assert not runtime.store.path.with_name("drafts.sqlite3").exists()


@pytest.mark.asyncio
async def test_initial_file_lock_authorization_runs_in_bounded_worker(client, monkeypatch):
    _, catalog = client
    started, finish = Event(), Event()
    original = catalog.config_store.load

    def blocked():
        started.set()
        assert finish.wait(5)
        return original()

    monkeypatch.setattr(catalog.config_store, "load", blocked)
    task = asyncio.create_task(CorrectionRuntime(catalog).authorize(correction_tools._access()))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        await asyncio.sleep(0)
        assert catalog.admission.locked()
    finally:
        finish.set()
    assert (await asyncio.wait_for(task, 3))[0] == TARGET


@pytest.mark.asyncio
async def test_project_permission_is_checked_after_worker_before_releasing_evidence(
    client, monkeypatch
):
    from test_knx_project_comparison import project_view

    from mcpserver.loxone.project.models import ProjectError

    _, runtime = client
    checks = []

    async def denied(access):
        checks.append(access.family_id)
        raise ProjectError("project_access_denied")

    async def query(_):
        return project_view(), None

    monkeypatch.setattr(correction_tools, "_project_query", query)
    server = FastMCP("project revocation")
    correction_tools.register_correction_tools(
        server,
        runtime,
        SimpleNamespace(
            endpoint=SimpleNamespace(origin=TARGET), projects=SimpleNamespace(authorize=denied)
        ),
    )
    args = dict(arguments(runtime), use_project_evidence=True)
    prepared = await call(server, PREPARE, args)
    assert prepared["data"]["error"] == "write_outcome_uncertain"
    # A completed draft is reconciled as a local proposal, never as current
    # project evidence after the independent project view was revoked.
    local = await call(server, READ, {"request_id": args["request_id"]})
    assert local["ok"] is True
    inspected = await call(
        server, READ, {"draft_id": local["data"]["draft"]["draft_id"], "verify_project": True}
    )
    assert inspected["data"]["error"] == "project_access_denied"
    assert checks == ["family", "family"]
