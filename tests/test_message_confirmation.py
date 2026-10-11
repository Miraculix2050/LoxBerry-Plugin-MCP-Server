from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP
from test_system_messages import CENTER, ENTRY, access, entry, runtime, source

from mcpserver import tools
from mcpserver.auth.provider import MESSAGE_CONFIRM_SCOPE, READ_SCOPE, normalize_scopes
from mcpserver.config import ConfigError, PluginConfig
from mcpserver.loxone.client import LoxoneWebSocketSession
from mcpserver.loxone.runtime import ControlOperationError
from mcpserver.message_confirmation import MessageConfirmations
from mcpserver.message_tools import register_message_tools


def setup_confirmation():
    instance, session, token = runtime()
    instance.validate_message_confirmation = AsyncMock(return_value=True)
    session.confirm_system_message = AsyncMock()
    current = access().model_copy(update={"scopes": [READ_SCOPE, MESSAGE_CONFIRM_SCOPE]})
    return MessageConfirmations(), instance, session, current


def manual_warning(**updates):
    raw = entry(
        eventId=1121,
        actions=[
            {
                "actionId": 1003,
                "isSecured": False,
                "link": None,
                "location": None,
                "requiredPermissions": 0,
            }
        ],
    )
    raw.update(updates)
    return raw


@pytest.mark.asyncio
@pytest.mark.parametrize("manual", [False, True])
async def test_preview_then_single_dispatch_observes_only_exact_effect(manual, caplog):
    confirmations, instance, session, current = setup_confirmation()
    before = manual_warning() if manual else entry()
    after = {
        **before,
        "isHistoric": manual,
        "setHistoricAt": 1700000001 if manual else None,
        "confirmedAt": None if manual else 1700000001,
    }
    session.system_messages.side_effect = [
        {"entries": [before]},
        {"entries": [before]},
        {"entries": [after]},
    ]
    preview = await confirmations.preview(instance, current, ENTRY)
    session.confirm_system_message.assert_not_awaited()
    assert preview.effect == ("historize" if manual else "acknowledge")
    with caplog.at_level("INFO"):
        result = await confirmations.confirm(instance, current, preview.preview_id, True)
    session.confirm_system_message.assert_awaited_once_with(CENTER, ENTRY, 1003 if manual else 1005)
    assert result.accepted and result.effect_observed and result.outcome == "observed"
    assert not result.retry_allowed
    assert "component=message_confirmation_audit" in caplog.text
    assert ENTRY not in caplog.text and preview.preview_id not in caplog.text
    with pytest.raises(ControlOperationError, match="Preview is unavailable"):
        await confirmations.confirm(instance, current, preview.preview_id, True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"isHistoric": True},
        {"confirmedAt": 1700000001},
        {"isVisuLocked": True},
        {"timestamps": [1700000002]},
        {"actions": []},
        {"severity": 3},
    ],
)
async def test_changed_source_cannot_dispatch(changes):
    confirmations, instance, session, current = setup_confirmation()
    session.system_messages.side_effect = [
        {"entries": [manual_warning()]},
        {"entries": [manual_warning(**changes)]},
    ]
    preview = await confirmations.preview(instance, current, ENTRY)
    with pytest.raises(ControlOperationError):
        await confirmations.confirm(instance, current, preview.preview_id, True)
    session.confirm_system_message.assert_not_awaited()
    assert preview.preview_id not in confirmations.tickets


@pytest.mark.asyncio
@pytest.mark.parametrize("read_marker_only", [False, True])
async def test_raw_redacted_changes_invalidate_approval_but_read_markers_do_not(read_marker_only):
    confirmations, instance, session, current = setup_confirmation()
    before = entry(desc="token=before")
    after = {**before, "readAt": 1700000001} if read_marker_only else entry(desc="token=after")
    session.system_messages.side_effect = [
        {"entries": [before]},
        {"entries": [after]},
        {"entries": [after]},
    ]
    preview = await confirmations.preview(instance, current, ENTRY)
    if read_marker_only:
        result = await confirmations.confirm(instance, current, preview.preview_id, True)
        assert result.accepted
    else:
        with pytest.raises(ControlOperationError, match="Message changed"):
            await confirmations.confirm(instance, current, preview.preview_id, True)
        session.confirm_system_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_revocation_after_dispatch_does_not_expose_post_action_history():
    confirmations, instance, session, current = setup_confirmation()
    preview = await confirmations.preview(instance, current, ENTRY)
    instance.validate_message_confirmation.side_effect = [True, True, False]
    session.system_messages.side_effect = [
        {"entries": [entry()]},
        {"entries": [entry(confirmedAt=1700000001)]},
    ]
    result = await confirmations.confirm(instance, current, preview.preview_id, True)
    assert result.accepted and result.outcome == "accepted_unverified"
    assert result.confirmed_at is None and result.historic is None


@pytest.mark.asyncio
async def test_false_approval_and_other_identity_do_not_consume_preview():
    confirmations, instance, session, current = setup_confirmation()
    preview = await confirmations.preview(instance, current, ENTRY)
    for selected, approved in [
        (current, False),
        (current.model_copy(update={"family_id": "other"}), True),
    ]:
        with pytest.raises(ControlOperationError):
            await confirmations.confirm(instance, selected, preview.preview_id, approved)
    assert preview.preview_id in confirmations.tickets
    session.confirm_system_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["scope", "disabled", "revoked_before_dispatch", "expired"])
async def test_authorization_expiry_or_scope_denies_without_write(mode, monkeypatch):
    confirmations, instance, session, current = setup_confirmation()
    preview = await confirmations.preview(instance, current, ENTRY)
    if mode == "scope":
        current = access()
    elif mode == "disabled":
        instance.validate_message_confirmation.return_value = False
    elif mode == "revoked_before_dispatch":
        instance.validate_message_confirmation.side_effect = [True, False]
    else:
        expired = confirmations.tickets[preview.preview_id].expires + 1
        monkeypatch.setattr(
            "mcpserver.message_confirmation.time.monotonic",
            lambda: expired,
        )
    with pytest.raises(ControlOperationError):
        await confirmations.confirm(instance, current, preview.preview_id, True)
    session.confirm_system_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["write_timeout", "post_read", "cleanup"])
async def test_uncertain_write_or_read_and_cleanup_never_replay(failure):
    confirmations, instance, session, current = setup_confirmation()
    preview = await confirmations.preview(instance, current, ENTRY)
    if failure == "write_timeout":
        session.confirm_system_message.side_effect = TimeoutError()
    elif failure == "post_read":
        session.system_messages.side_effect = [{"entries": [entry()]}, TimeoutError()]
    else:
        session.close.side_effect = TimeoutError()
    result = await confirmations.confirm(instance, current, preview.preview_id, True)
    assert result.dispatched and not result.effect_observed
    assert result.outcome == ("uncertain" if failure == "write_timeout" else "accepted_unverified")
    assert result.accepted is (failure != "write_timeout")
    with pytest.raises(ControlOperationError):
        await confirmations.confirm(instance, current, preview.preview_id, True)
    session.confirm_system_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_replay_and_separate_write_budget():
    confirmations, instance, session, current = setup_confirmation()
    preview = await confirmations.preview(instance, current, ENTRY)
    results = await asyncio.gather(
        *[confirmations.confirm(instance, current, preview.preview_id, True) for _ in range(2)],
        return_exceptions=True,
    )
    assert sum(isinstance(r, ControlOperationError) for r in results) == 1
    session.confirm_system_message.assert_awaited_once()
    for _ in range(2):
        preview = await confirmations.preview(instance, current, ENTRY)
        await confirmations.confirm(instance, current, preview.preview_id, True)
    preview = await confirmations.preview(instance, current, ENTRY)
    with pytest.raises(ControlOperationError, match="budget exceeded"):
        await confirmations.confirm(instance, current, preview.preview_id, True)
    assert session.confirm_system_message.await_count == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"severity": 1},
        {"severity": 3},
        {"severity": 4},
        {"eventId": 1123},
        {"actions": [{"actionId": 1003, "isSecured": True}]},
    ],
)
def test_unverified_manual_action_is_not_offered(changes):
    raw = manual_warning()
    raw.update(changes)
    assert source([raw]).records[0].confirmation_action_id is None


def test_manual_historization_does_not_change_released_acknowledgement_meaning():
    record = source([manual_warning()]).records[0]
    assert not record.acknowledgement_available
    assert record.confirmation_action_id == 1003 and record.confirmation_effect == "historize"


@pytest.mark.asyncio
async def test_native_command_validates_identity_and_action_allowlist():
    session = object.__new__(LoxoneWebSocketSession)
    session._command = AsyncMock()
    session._secure_transport = False
    for center, target, action in [
        ("../delete", ENTRY, 1003),
        (CENTER, "x/action", 1005),
        (CENTER, ENTRY, 1008),
        (CENTER, ENTRY, True),
    ]:
        with pytest.raises(ValueError):
            await session.confirm_system_message(center, target, action)
    session._command.assert_not_awaited()
    await session.confirm_system_message(CENTER, ENTRY, 1003)
    session._command.assert_awaited_once_with(
        f"jdev/sps/io/{CENTER}/action/{ENTRY}/1003", encrypted=True
    )


def test_default_off_config_round_trip_and_independent_scope():
    config = PluginConfig()
    assert not config.loxone_message_confirmation_enabled
    document = config.to_document()
    document["tools"]["loxone_message_confirmation_enabled"] = True
    enabled = PluginConfig.from_document(document)
    assert PluginConfig.from_document(enabled.to_document()).loxone_message_confirmation_enabled
    with pytest.raises(ConfigError):
        document["tools"]["loxone_message_confirmation_enabled"] = "true"
        PluginConfig.from_document(document)
    assert normalize_scopes(f"{READ_SCOPE} {MESSAGE_CONFIRM_SCOPE}", control_enabled=False) == (
        READ_SCOPE,
        MESSAGE_CONFIRM_SCOPE,
    )


@pytest.mark.asyncio
async def test_mcp_preview_is_read_only_writer_requires_explicit_approval(monkeypatch):
    confirmations, instance, session, current = setup_confirmation()
    monkeypatch.setattr(tools, "_access", lambda: current)
    server = FastMCP("confirmation")
    register_message_tools(server, instance)
    preview_tool = server._tool_manager.get_tool("loxone_preview_system_message_confirmation")
    writer = server._tool_manager.get_tool("loxone_confirm_system_message")
    assert preview_tool.annotations.readOnlyHint and not writer.annotations.readOnlyHint
    assert not writer.annotations.idempotentHint
    preview = await preview_tool.fn(ENTRY)
    result = await writer.fn(preview.data.preview_id, False)
    assert not result.ok and result.data.error == "approval_required"
    session.confirm_system_message.assert_not_awaited()
