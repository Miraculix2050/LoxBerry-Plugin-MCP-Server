"""Independent Admin authority, fresh project evidence and accepted XML handoff."""

import asyncio
import hashlib
import json
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from test_knx_project_comparison import project_view
from test_knx_xml_export import xml

from mcpserver.admin import AdminError
from mcpserver.auth.provider import StoredAccessToken
from mcpserver.auth.store import AtomicJsonAuthStore, token_digest
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.knx.admin import dispatch_knx
from mcpserver.knx.admin_bridge import (
    MAX_REQUEST,
    PATH,
    PROOF_HEADER,
    SESSION_HEADER,
    AdminProjectBridge,
    canonical,
    helper_key,
    proof,
)
from mcpserver.knx.catalog import labels_revision
from mcpserver.knx.correction_drafts import CorrectionDraftStore
from mcpserver.knx.correction_service import CorrectionService
from mcpserver.knx.import_repository import ImportRepository
from mcpserver.knx.import_service import select_candidates
from mcpserver.knx.store import KnxStore
from mcpserver.knx.xml_adapter import parse_xml
from mcpserver.loxone.endpoint import MiniserverEndpoint

TARGET = "https://first.example"
SESSION = "b" * 64


def catalog(
    tmp_path, monkeypatch, *, xml_source=False, project=False, destination="local_metadata"
):
    monkeypatch.setenv("LBPDATA", str(tmp_path))
    monkeypatch.setenv("MCPSERVER_KNX_ADMIN_SESSION", SESSION)
    configs = AtomicConfigStore(tmp_path / "config.json")
    configs.save(replace(PluginConfig.defaults(), loxone_endpoint=TARGET))
    store = KnxStore(tmp_path / "knx" / "metadata.sqlite3")
    value = "Primary B" if project else "Agreed export name"
    address = "1/2/3" if project else "0/0/1"
    if xml_source:
        content = xml()
        document = parse_xml(content.encode())
        ImportRepository(store).apply(TARGET, 0, document, select_candidates(document), set(), {})
    else:
        store.put(
            TARGET,
            0,
            dict(address=address, address_format="three_level", fields={"name": "Original"}),
        )
    owner = CorrectionDraftStore(store.path.with_name("drafts.sqlite3"), "a" * 64)
    query = project_view() if project else None
    row = dict(
        destination=destination,
        kind="address",
        address_format="three_level",
        address=address,
        field="name",
        operation="set",
        value=value,
    )
    if project:
        row["project_object_id"] = "p:2"
    config = configs.load()
    plan = CorrectionService(store, owner).plan(
        config, TARGET, 1, labels_revision(config, TARGET), [row], query=query
    )
    created = owner.create_correction(
        TARGET,
        1,
        plan["manual_revision"],
        [{**row, "decision": "accepted"} for row in plan["changes"]],
        project_binding=plan["project_binding"],
    )
    selection = dict(
        target=hashlib.sha256(TARGET.encode()).hexdigest(),
        draft_id=created["draft_id"],
        draft_revision=1,
        catalog_revision=1,
        manual_revision=plan["manual_revision"],
        approved_change_ids=[created["changes"][0]["change_id"]],
    )
    return configs, store, owner, selection, query


def test_accepted_export_remains_separate_and_generic_download_cannot_bypass_review(
    tmp_path, monkeypatch
):
    configs, store, owner, selection, _ = catalog(
        tmp_path, monkeypatch, xml_source=True, destination="ets_export"
    )
    before = store.export(TARGET)
    preview = dispatch_knx("knx_correction_xml_preview", selection, configs)
    assert preview["correction_handoff"] and preview["experimental"]
    download = dict(
        target=selection["target"],
        draft_id=preview["draft_id"],
        revision=1,
        confirmed_experimental=True,
    )
    with pytest.raises(AdminError) as legacy:
        dispatch_knx(
            "knx_xml_download", {**download, "project_binding": preview["project_binding"]}, configs
        )
    assert legacy.value.code == "knx_correction_invalid"
    result = dispatch_knx("knx_correction_xml_download", download, configs)
    assert parse_xml(result["content"].encode()).addresses[0].fields["name"] == "Agreed export name"
    assert store.export(TARGET) == before
    changes = owner.inspect_correction(selection["draft_id"], TARGET)["changes"]
    owner.update_correction(
        selection["draft_id"], TARGET, 1, [{**row, "decision": "rejected"} for row in changes]
    )
    with pytest.raises(AdminError) as changed:
        dispatch_knx("knx_correction_xml_download", download, configs)
    assert changed.value.code == "knx_revision_conflict"


def test_export_download_requires_same_admin_session_and_live_manual_revision(
    tmp_path, monkeypatch
):
    configs, store, _, selection, _ = catalog(
        tmp_path, monkeypatch, xml_source=True, destination="ets_export"
    )
    preview = dispatch_knx("knx_correction_xml_preview", selection, configs)
    download = dict(
        target=selection["target"],
        draft_id=preview["draft_id"],
        revision=1,
        confirmed_experimental=True,
    )
    monkeypatch.setenv("MCPSERVER_KNX_ADMIN_SESSION", "c" * 64)
    with pytest.raises(AdminError) as other:
        dispatch_knx("knx_correction_xml_download", download, configs)
    assert other.value.code == "knx_draft_expired"
    monkeypatch.setenv("MCPSERVER_KNX_ADMIN_SESSION", SESSION)
    from mcpserver.loxone.project.taxonomy import parse_taxonomy

    configs.mutate(
        lambda config: replace(
            config,
            knx_address_taxonomy_endpoint=TARGET,
            knx_address_taxonomy=parse_taxonomy(
                [dict(address_format="three_level", prefix="1/2", label="New")]
            ),
        )
    )
    with pytest.raises(AdminError) as manual:
        dispatch_knx("knx_correction_xml_download", download, configs)
    assert manual.value.code == "knx_revision_conflict"
    assert store.page(TARGET)["items"][0]["imported"]["name"] == "ETS"


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    configs, store, owner, selection, query = catalog(tmp_path, monkeypatch, project=True)
    # The service uses explicit persistent settings, not CGI environment state.
    monkeypatch.delenv("LBPDATA")
    monkeypatch.delenv("MCPSERVER_KNX_ADMIN_SESSION")
    auth = AtomicJsonAuthStore(tmp_path / "auth.json")
    access = StoredAccessToken(
        token="synthetic",
        client_id="client",
        scopes=["loxone:read"],
        expires_at=2_000_000_000,
        resource="https://public.example/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="ms",
    )
    family = dict(
        client_id="client",
        identity_id="identity",
        miniserver_id="ms",
        scope="loxone:read",
        expires_at=2_000_000_000,
        revoked=False,
    )
    record = dict(
        client_id="client",
        identity_id="identity",
        miniserver_id="ms",
        family_id="family",
        scopes=["loxone:read"],
        expires_at=2_000_000_000,
        resource=access.resource,
        status="active",
    )
    auth.mutate(
        lambda data: (
            data["families"].update(family=family),
            data["access_tokens"].update({token_digest(access.token): record}),
        )
    )
    provider = SimpleNamespace(
        load_access_token=AsyncMock(return_value=access), now=lambda: int(time.time())
    )
    runtime = SimpleNamespace(
        endpoint=MiniserverEndpoint.parse(TARGET), projects=SimpleNamespace(authorize=AsyncMock())
    )
    query_loader = AsyncMock(return_value=(query, None))
    monkeypatch.setattr("mcpserver.tools._project_query", query_loader)
    service = AdminProjectBridge(auth, configs, provider, runtime, store.path, asyncio.Semaphore(1))
    app = Starlette(routes=[Route(PATH, service.handle, methods=["POST"])])
    selection.update(request_id="d" * 32, storage="addresses", confirmed=True, action="apply")
    value = dict(action="knx_correction_apply", payload=selection)
    body = canonical(value)
    headers = {
        SESSION_HEADER: SESSION,
        PROOF_HEADER: proof(helper_key(auth), SESSION, body, int(time.time())),
        "Authorization": "Bearer synthetic",
    }
    return service, app, body, headers, query_loader, store, selection, configs, owner


def test_bridge_uses_fresh_project_query_and_independent_admin_authority(bridge):
    service, app, body, headers, loader, store, _, configs, _ = bridge
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        result = client.post(PATH, content=body, headers=headers).json()
    assert result["ok"] and result["data"]["outcome"] == "applied"
    assert loader.await_count == 1
    assert loader.await_args.args[1].family_id == "family"
    assert service.runtime.projects.authorize.await_count == 1
    assert store.page(TARGET)["items"][0]["effective"]["name"] == "Primary B"
    assert not configs.load().loxberry_knx_write_enabled
    assert not result["data"]["loxone_written"] and not result["data"]["exports_file"]


@pytest.mark.parametrize(
    "failure", ["proof", "body", "expired", "session", "bearer", "scope", "peer", "oversize"]
)
def test_bridge_does_not_infer_admin_permission_from_project_access(bridge, failure):
    service, app, body, headers, loader, store, _, _, _ = bridge
    headers = dict(headers)
    peer = "127.0.0.1"
    if failure == "proof":
        headers.pop(PROOF_HEADER)
    if failure == "body":
        body += b" "
    if failure == "expired":
        headers[PROOF_HEADER] = proof(
            helper_key(service.store), SESSION, body, int(time.time()) - 61
        )
    if failure == "session":
        headers[SESSION_HEADER] = "c" * 64
    if failure == "bearer":
        headers.pop("Authorization")
    if failure == "scope":
        service.provider.load_access_token.return_value = (
            service.provider.load_access_token.return_value.model_copy(update={"scopes": []})
        )
    if failure == "peer":
        peer = "192.0.2.1"
    if failure == "oversize":
        body = b"x" * (MAX_REQUEST + 1)
    with TestClient(app, client=(peer, 12345)) as client:
        result = client.post(PATH, content=body, headers=headers).json()
    assert not result["ok"] and loader.await_count == 0
    assert store.page(TARGET)["items"][0]["effective"]["name"] == "Original"


def test_bridge_revocation_between_query_and_effect_is_not_cached(bridge):
    service, app, body, headers, loader, store, _, _, _ = bridge

    async def revoked(*args):
        service.store.mutate(lambda data: data["families"]["family"].update(revoked=True))
        return loader.return_value

    loader.side_effect = revoked
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        result = client.post(PATH, content=body, headers=headers).json()
    assert not result["ok"] and result["error"]["code"] == "knx_project_evidence_required"
    assert store.page(TARGET)["items"][0]["effective"]["name"] == "Original"


def test_bridge_does_not_accept_changed_project(bridge):
    _, app, body, headers, loader, store, _, _, _ = bridge
    query = loader.return_value[0]
    loader.return_value = (
        replace(
            query,
            view=replace(query.view, snapshot=replace(query.view.snapshot, fingerprint="b" * 64)),
        ),
        None,
    )
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        result = client.post(PATH, content=body, headers=headers).json()
    assert not result["ok"] and result["error"]["code"] == "knx_project_evidence_changed"
    assert store.page(TARGET)["items"][0]["effective"]["name"] == "Original"


@pytest.mark.asyncio
async def test_bridge_cancellation_retains_both_leases_until_dispatch_finishes(bridge, monkeypatch):
    import threading

    service, _, body, headers, loader, _, _, _, _ = bridge
    started, release = threading.Event(), threading.Event()
    calls = []

    def blocked(*args, **kwargs):
        calls.append(args[0])
        started.set()
        assert release.wait(5)
        return {"outcome": "applied"}

    monkeypatch.setattr("mcpserver.knx.admin.dispatch_knx", blocked)
    service.slots = asyncio.Semaphore(1)
    value = json.loads(body)
    access = service.provider.load_access_token.return_value

    def execute():
        return service.execute(
            value, SESSION, helper_key(service.store), headers[PROOF_HEADER], body, access
        )

    first = asyncio.create_task(execute())
    try:
        assert await asyncio.to_thread(started.wait, 5)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert service.slots.locked() and service.admission.locked()
        assert len(service.workers) == 1
        second = asyncio.create_task(execute())
        await asyncio.sleep(0)
        assert loader.await_count == 1 and len(calls) == 1
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        workers = list(service.workers)
        release.set()
        await asyncio.gather(*workers)
        await asyncio.sleep(0)
        assert not service.slots.locked() and not service.admission.locked()
        assert not service.workers and len(calls) == 1
    finally:
        release.set()


def test_bridge_rejects_browser_supplied_project_authority(bridge):
    service, app, body, headers, loader, store, _, _, _ = bridge
    value = json.loads(body)
    value["payload"]["project_binding"] = "claimed-browser-authority"
    body = canonical(value)
    headers = {
        **headers,
        PROOF_HEADER: proof(helper_key(service.store), SESSION, body, int(time.time())),
    }
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        result = client.post(PATH, content=body, headers=headers).json()
    assert not result["ok"] and result["error"]["code"] == "knx_correction_invalid"
    assert loader.await_count == 1
    assert store.page(TARGET)["items"][0]["effective"]["name"] == "Original"


@pytest.mark.parametrize("expire_call", [1, 2])
def test_export_does_not_return_after_shared_proposal_expires_during_authorization(
    tmp_path, monkeypatch, expire_call
):
    from mcpserver.knx import admin_export

    configs, store, owner, selection, _ = catalog(
        tmp_path, monkeypatch, xml_source=True, destination="ets_export"
    )
    preview = dispatch_knx("knx_correction_xml_preview", selection, configs)
    expiry = owner.inspect_correction(selection["draft_id"], TARGET)["expires_at"]
    clock = [float(expiry) - 0.25]
    monkeypatch.setattr(admin_export, "time", SimpleNamespace(time=lambda: clock[0]))
    count = [0]

    def authorize():
        count[0] += 1
        if count[0] == expire_call:
            clock[0] = float(expiry)

    with pytest.raises(AdminError) as expired:
        dispatch_knx(
            "knx_correction_xml_download",
            dict(
                target=selection["target"],
                draft_id=preview["draft_id"],
                revision=1,
                confirmed_experimental=True,
            ),
            configs,
            authorize_effect=authorize,
        )
    assert expired.value.code == "knx_draft_expired"
    assert count[0] == expire_call
    assert store.page(TARGET)["items"][0]["imported"]["name"] == "ETS"
