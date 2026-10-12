"""Actual SDK local-write consent, selected effects and safe reconciliation."""

import json
from dataclasses import replace

import pytest
from test_knx_correction_runtime import (
    PREPARE,
    READ,
    TARGET,
    arguments,
    call,
)
from test_knx_correction_runtime import (
    client as client,
)

from mcpserver.knx import address_apply, apply_tools, correction_tools
from mcpserver.knx.delegation import draft_binding_id, read_binding_id, write_binding_id

APPLY = "loxberry_apply_knx_corrections"


@pytest.fixture
def write_client(client, monkeypatch):  # noqa: F811 - pytest resolves the imported fixture by name.
    server, runtime = client
    monkeypatch.setattr(apply_tools, "_access", lambda: correction_tools._access())
    apply_tools.register_apply_tools(server, runtime, None)
    return server, runtime


def grant(runtime, monkeypatch):
    access = correction_tools._access()
    scopes = [*access.scopes, "loxberry:knx:write"]
    runtime.auth_store.mutate(lambda doc: doc["families"]["family"].update(scope=" ".join(scopes)))
    access = access.model_copy(update={"scopes": scopes})
    monkeypatch.setattr(correction_tools, "_access", lambda: access)
    family = runtime.auth_store.snapshot()["families"]["family"]
    runtime.config_store.mutate(
        lambda config: replace(
            config,
            loxberry_knx_write_enabled=True,
            loxberry_knx_write_bindings=(write_binding_id(config, runtime.auth_store, family),),
        )
    )


async def approved(server, runtime):
    args = arguments(runtime)
    created = await call(server, PREPARE, args)
    assert created["ok"]
    inspected = await call(server, READ, {"draft_id": created["data"]["draft_id"]})
    identifier = inspected["data"]["changes"][0]["change_id"]
    reviewed = await call(
        server,
        PREPARE,
        {
            **{key: value for key, value in args.items() if key != "changes"},
            "mode": "review",
            "request_id": "d" * 32,
            "draft_id": created["data"]["draft_id"],
            "draft_revision": 1,
            "decisions": [{"change_id": identifier, "decision": "accepted"}],
        },
    )
    assert reviewed["ok"]
    return {
        **{key: value for key, value in args.items() if key != "changes"},
        "action": "apply",
        "request_id": "b" * 32,
        "draft_id": created["data"]["draft_id"],
        "draft_revision": 2,
        "approved_change_ids": [identifier],
    }


def snapshot(runtime):
    with runtime.store.connection() as db:
        return (
            runtime.store.revision(db, TARGET),
            db.execute("SELECT overrides FROM addresses").fetchone()[0],
            db.execute("SELECT count(*) FROM local_apply_receipts").fetchone()[0],
        )


@pytest.mark.asyncio
async def test_read_and_draft_consent_never_grant_local_write(write_client):
    server, runtime = write_client
    args = await approved(server, runtime)
    before = snapshot(runtime)
    denied = await call(server, APPLY, args)
    assert denied["data"]["error"] == "permission_denied"
    assert snapshot(runtime) == before


@pytest.mark.asyncio
async def test_actual_sdk_preserves_name_and_reconciles_exact_effect(write_client, monkeypatch):
    server, runtime = write_client
    args = await approved(server, runtime)
    grant(runtime, monkeypatch)
    applied = await call(server, APPLY, args)
    assert applied["ok"] and applied["data"]["catalog_revision"] == 2
    assert applied["data"]["changed_addresses"] == 1
    assert not applied["data"]["loxone_written"] and not applied["data"]["import_written"]
    revision, raw, receipts = snapshot(runtime)
    assert revision == 2 and receipts == 1
    assert json.loads(raw) == {"name": "Existing local name", "description": ""}
    reconciled = await call(server, APPLY, {**args, "action": "reconcile"})
    assert reconciled["data"] == applied["data"]
    before = snapshot(runtime)
    assert (await call(server, APPLY, args))["data"] == applied["data"]
    assert snapshot(runtime) == before
    absent = await call(server, APPLY, {**args, "action": "reconcile", "request_id": "c" * 32})
    assert absent["data"]["outcome"] == "not_observed"
    assert absent["data"]["automatic_retry_allowed"] is False
    assert snapshot(runtime) == before


@pytest.mark.asyncio
async def test_revoked_write_denies_effect_and_receipt_access(write_client, monkeypatch):
    server, runtime = write_client
    args = await approved(server, runtime)
    grant(runtime, monkeypatch)
    runtime.config_store.mutate(lambda config: replace(config, loxberry_knx_write_bindings=()))
    before = snapshot(runtime)
    for action in ("apply", "reconcile"):
        denied = await call(server, APPLY, {**args, "action": action})
        assert denied["data"]["error"] == "permission_denied"
    assert snapshot(runtime) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "removed",
    [
        "loxberry_knx_read_enabled",
        "loxberry_knx_drafts_enabled",
        "loxberry_knx_write_enabled",
        "loxberry_knx_read_bindings",
        "loxberry_knx_drafts_bindings",
        "loxberry_knx_write_bindings",
    ],
)
async def test_each_live_delegation_is_required(write_client, monkeypatch, removed):
    server, runtime = write_client
    args = await approved(server, runtime)
    grant(runtime, monkeypatch)
    value = False if removed.endswith("enabled") else ()
    runtime.config_store.mutate(lambda config: replace(config, **{removed: value}))
    before = snapshot(runtime)
    result = await call(server, APPLY, args)
    assert result["data"]["error"] == "permission_denied"
    assert snapshot(runtime) == before


@pytest.mark.asyncio
async def test_draft_binding_cannot_be_reused_as_write_binding(write_client, monkeypatch):
    server, runtime = write_client
    args = await approved(server, runtime)
    grant(runtime, monkeypatch)
    runtime.config_store.mutate(
        lambda config: replace(
            config,
            loxberry_knx_write_bindings=config.loxberry_knx_drafts_bindings,
        )
    )
    before = snapshot(runtime)
    result = await call(server, APPLY, args)
    assert result["data"]["error"] == "permission_denied"
    assert snapshot(runtime) == before


@pytest.mark.asyncio
async def test_fully_granted_other_identity_cannot_apply_owned_draft(write_client, monkeypatch):
    server, runtime = write_client
    args = await approved(server, runtime)
    grant(runtime, monkeypatch)
    access = correction_tools._access().model_copy(
        update={
            "identity_id": "other-identity",
            "subject": "other-identity",
            "family_id": "other-family",
        }
    )
    family = {
        **runtime.auth_store.snapshot()["families"]["family"],
        "identity_id": "other-identity",
    }
    runtime.auth_store.mutate(lambda doc: doc["families"].update({"other-family": family}))
    runtime.config_store.mutate(
        lambda config: replace(
            config,
            loxberry_knx_read_bindings=(
                *config.loxberry_knx_read_bindings,
                read_binding_id(config, runtime.auth_store, family),
            ),
            loxberry_knx_drafts_bindings=(
                *config.loxberry_knx_drafts_bindings,
                draft_binding_id(config, runtime.auth_store, family),
            ),
            loxberry_knx_write_bindings=(
                *config.loxberry_knx_write_bindings,
                write_binding_id(config, runtime.auth_store, family),
            ),
        )
    )
    monkeypatch.setattr(correction_tools, "_access", lambda: access)
    before = snapshot(runtime)
    result = await call(server, APPLY, args)
    assert result["data"]["error"] == "knx_draft_unavailable"
    assert snapshot(runtime) == before


@pytest.mark.asyncio
async def test_revocation_after_commit_reports_uncertainty_with_authoritative_receipt(
    write_client,
    monkeypatch,
):
    server, runtime = write_client
    args = await approved(server, runtime)
    grant(runtime, monkeypatch)
    original = address_apply.apply_addresses

    def revoked_after_commit(*values, **options):
        result = original(*values, **options)
        runtime.auth_store.mutate(lambda doc: doc["families"]["family"].update(revoked=True))
        return result

    monkeypatch.setattr("mcpserver.knx.correction_apply.apply_addresses", revoked_after_commit)
    uncertain = await call(server, APPLY, args)
    assert uncertain["data"]["error"] == "write_outcome_uncertain"
    assert snapshot(runtime)[0] == 2 and snapshot(runtime)[2] == 1


@pytest.mark.asyncio
async def test_unaccepted_selection_is_not_an_apply_permission(write_client, monkeypatch):
    server, runtime = write_client
    args = await approved(server, runtime)
    grant(runtime, monkeypatch)
    rejected = await call(
        server,
        PREPARE,
        {
            "target_id": args["target_id"],
            "catalog_revision": args["catalog_revision"],
            "manual_revision": args["manual_revision"],
            "draft_id": args["draft_id"],
            "draft_revision": 2,
            "request_id": "e" * 32,
            "mode": "review",
            "decisions": [{"change_id": args["approved_change_ids"][0], "decision": "rejected"}],
        },
    )
    assert rejected["ok"]
    before = snapshot(runtime)
    denied = await call(server, APPLY, {**args, "draft_revision": 3})
    assert denied["data"]["error"] == "knx_correction_not_accepted"
    assert snapshot(runtime) == before
