from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from mcp.server.fastmcp import FastMCP
from test_message_confirmation import manual_warning, setup_confirmation
from test_system_messages import ENTRY

from mcpserver import admin, tools
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.loxone.runtime import ControlOperationError
from mcpserver.message_approval import MessageApprovalStore
from mcpserver.message_confirmation import MessageConfirmations
from mcpserver.message_tools import register_message_tools


@pytest.mark.asyncio
@pytest.mark.parametrize("local_approval", [False, True])
async def test_client_boolean_cannot_replace_independent_admin_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, local_approval: bool
) -> None:
    _, instance, session, access = setup_confirmation()
    config = AtomicConfigStore((tmp_path / "mcpserver.json").resolve())
    config.save(PluginConfig.defaults())
    monkeypatch.setattr(admin, "_config_store", lambda: config)
    approvals = MessageApprovalStore(config.path)
    confirmations = MessageConfirmations(approvals)
    before = manual_warning()
    after = {**before, "isHistoric": True, "setHistoricAt": 1700000001}
    session.system_messages.side_effect = [{"entries": [x]} for x in [before, before, after]]
    preview = await confirmations.preview(instance, access, ENTRY)
    assert preview.local_approval_required
    inspected = admin.dispatch(
        {"action": "inspect_message_confirmation", "payload": {"preview_id": preview.preview_id}}
    )
    assert inspected["entry_uuid"] == ENTRY and inspected["effect"] == "historize"
    assert "challenge" not in preview.model_dump()
    if local_approval:
        assert admin.dispatch(
            {
                "action": "approve_message_confirmation",
                "payload": {"preview_id": preview.preview_id, "challenge": inspected["challenge"]},
            }
        ) == {"approved": True}
        result = await confirmations.confirm(instance, access, preview.preview_id, True)
        assert result.effect_observed
        session.confirm_system_message.assert_awaited_once()
    else:
        with pytest.raises(ControlOperationError, match="local LoxBerry Admin"):
            await confirmations.confirm(instance, access, preview.preview_id, True)
        session.confirm_system_message.assert_not_awaited()
    with pytest.raises(ValueError, match="unavailable"):
        approvals.inspect(preview.preview_id)


def test_approval_challenge_binding_expiry_and_one_time_consumption(tmp_path: Path) -> None:
    store = MessageApprovalStore((tmp_path / "mcpserver.json").resolve())
    preview_id = "x" * 43
    store.stage(preview_id, "binding", {"title": "untrusted <script>"})
    inspected = store.inspect(preview_id)
    with pytest.raises(ValueError, match="does not match"):
        store.approve(preview_id, "invented")
    assert not store.consume(preview_id, "binding")
    store.stage(preview_id, "binding", {})
    store.approve(preview_id, store.inspect(preview_id)["challenge"])
    assert not store.consume(preview_id, "other-binding")
    store.stage(preview_id, "binding", {})
    store.approve(preview_id, store.inspect(preview_id)["challenge"])
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: store.consume(preview_id, "binding"), range(2)))
    assert sorted(results) == [False, True]
    store.stage(preview_id, "binding", {})
    now = time.time()
    with (
        patch("mcpserver.message_approval.time.time", return_value=now + 121),
        pytest.raises(ValueError, match="unavailable"),
    ):
        store.inspect(preview_id)
    assert inspected["title"] == "untrusted <script>"


def test_reader_cannot_fill_other_callers_local_approval_quota(tmp_path: Path) -> None:
    store = MessageApprovalStore((tmp_path / "mcpserver.json").resolve())
    for index in range(60):
        store.stage(str(index).zfill(43), "binding", {"entry_uuid": "same"}, owner="reader")
    for index in range(9):
        store.stage(
            str(index + 100).zfill(43), "binding", {"entry_uuid": str(index)}, owner="reader"
        )
    with pytest.raises(ValueError, match="identity"):
        store.stage("y" * 43, "binding", {"entry_uuid": "eleventh"}, owner="reader")
    store.stage("z" * 43, "other", {"entry_uuid": "same"}, owner="other")
    assert store.inspect("z" * 43)["entry_uuid"] == "same"


@pytest.mark.asyncio
async def test_confirmation_error_envelope_correlates_with_fixed_audit_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _, instance, session, access = setup_confirmation()
    instance.message_approval_store = MessageApprovalStore((tmp_path / "mcpserver.json").resolve())
    session.system_messages.return_value = {"entries": [manual_warning()]}
    monkeypatch.setattr(tools, "_access", lambda: access)
    server = FastMCP("local-approval")
    register_message_tools(server, instance)
    preview_tool = server._tool_manager.get_tool("loxone_preview_system_message_confirmation")
    writer = server._tool_manager.get_tool("loxone_confirm_system_message")
    assert preview_tool and writer
    preview = await preview_tool.fn(entry_uuid=ENTRY)
    with caplog.at_level("INFO"):
        result = await writer.fn(preview_id=preview.data.preview_id, user_approved=True)
    assert not result.ok and result.data.error == "local_approval_required"
    assert f"trace_id={result.trace_id}" in caplog.text
    assert "outcome=local_approval_required" in caplog.text
    session.confirm_system_message.assert_not_awaited()


def test_local_approval_surface_is_native_admin_and_renders_untrusted_text_safely() -> None:
    root = Path(__file__).resolve().parents[1]
    cgi = (root / "webfrontend/htmlauth/message-approval.cgi").read_text(encoding="utf-8")
    bridge = (root / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    script = (root / "webfrontend/htmlauth/message-approval.js").read_text(encoding="utf-8")
    assert "-X_Frame_Options => 'DENY'" in cgi and "frame-ancestors 'none'" in cgi
    assert "same_origin_post()" in bridge
    assert "inspect_message_confirmation" in bridge and "approve_message_confirmation" in bridge
    assert ".textContent = [" in script and "innerHTML" not in script
    assert "current.challenge" in script and "credentials: 'same-origin'" in script
