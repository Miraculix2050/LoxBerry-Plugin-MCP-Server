from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from mcp.server.fastmcp import FastMCP

from mcpserver import tools
from mcpserver.auth.provider import HISTORY_SCOPE, READ_SCOPE, StoredAccessToken
from mcpserver.loxone.client import MiniserverEndpoint
from mcpserver.loxone.models import LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import ControlOperationError, LoxoneRuntime
from mcpserver.loxone.structure import normalize_structure
from mcpserver.loxone.system_messages import MessageSourceError, decode_messages
from mcpserver.message_tools import register_message_tools

CENTER = "11111111-1111-1111-1111111111111111"
ENTRY = "22222222-2222-2222-2222222222222222"


def access() -> StoredAccessToken:
    return StoredAccessToken(
        token="opaque",
        client_id="client",
        scopes=[READ_SCOPE],
        expires_at=2_000_000_000,
        resource="https://example.test/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="miniserver",
    )


def entry(**updates: object) -> dict[str, object]:
    return {
        "entryUuid": ENTRY,
        "eventId": 503,
        "severity": 2,
        "title": "Restart",
        "desc": "Check power. token=private https://user:secret@example.test/path",
        "affectedName": "Device",
        "sourceUuid": CENTER,
        "affectedUuids": [CENTER],
        "roomUuid": None,
        "installationPlace": None,
        "isHistoric": False,
        "setHistoricAt": None,
        "confirmedAt": None,
        "readAt": None,
        "timestamps": [1_700_000_000],
        "isVisuLocked": False,
        "actions": [
            {
                "actionId": 1005,
                "isSecured": False,
                "link": None,
                "location": None,
                "requiredPermissions": 0,
            }
        ],
        **updates,
    }


def source(entries: list[dict[str, object]]):
    return decode_messages(
        {"entries": entries},
        firmware="17.2.8.28",
        serial="001122334455",
        center=CENTER,
        rights=131072,
    )


def test_source_preserves_lifecycle_severity_and_redacts_text() -> None:
    record = source(
        [
            entry(
                isHistoric=True, setHistoricAt=1_700_000_001, confirmedAt=1_700_000_002, severity=99
            )
        ]
    ).records[0]
    assert record.historic and record.confirmed_at and record.set_historic_at
    assert record.severity == "unknown" and record.severity_code == 99
    assert record.acknowledgement_available
    assert "private" not in record.description and "secret" not in record.description
    assert "https://" not in record.description
    assert source([]).retention_complete is False


@pytest.mark.parametrize(
    "changes",
    [
        {"entryUuid": "../action"},
        {"severity": True},
        {"timestamps": [True]},
        {"timestamps": []},
        {"sourceUuid": "bad"},
        {"affectedUuids": ["bad"]},
        {"isHistoric": "false"},
        {"actions": "bad"},
        {"desc": {}},
    ],
)
def test_invalid_source_is_not_empty_success(changes: dict[str, object]) -> None:
    with pytest.raises(MessageSourceError):
        source([entry(**changes)])


def test_duplicate_entries_and_oversize_are_rejected() -> None:
    with pytest.raises(MessageSourceError):
        source([entry(), entry()])
    with pytest.raises(MessageSourceError):
        source([entry(desc="x" * 2_097_153)])


@pytest.mark.parametrize("rights", [None, True, "131072", -1, 2**32, 1, 131072])
def test_normalization_never_infers_message_permission_from_admin(rights: object) -> None:
    structure = normalize_structure(
        {
            "msInfo": {
                "serialNr": "serial",
                "currentUser": {"isAdmin": True, "userRights": rights},
            },
            "messageCenter": {"center": {"uuidAction": CENTER}},
        },
        username="reader",
    )
    assert structure.message_center_uuid == CENTER
    assert structure.user_rights == (
        rights if type(rights) is int and 0 <= rights < 2**32 else None
    )


def runtime():
    structure = LoxoneStructure(
        LoxoneIdentity("reader", "00:11:22:33:44:55"),
        "now",
        (),
        (),
        (),
        message_center_uuid=CENTER,
        user_rights=131072,
    )
    session = SimpleNamespace(
        load_structure=AsyncMock(return_value=structure),
        close=AsyncMock(),
        system_messages=AsyncMock(return_value={"entries": [entry()]}),
    )
    token = SimpleNamespace(destroy=Mock())
    instance = LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"), SimpleNamespace(get=lambda *_: token)
    )  # type: ignore[arg-type]
    instance._open_session = AsyncMock(return_value=session)
    instance.client = SimpleNamespace(
        probe=AsyncMock(return_value=SimpleNamespace(firmware="17.2.8.28", serial="001122334455"))
    )
    return instance, session, token


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rights,center,firmware",
    [(1, CENTER, "17.2.8.28"), (131072, None, "17.2.8.28"), (131072, CENTER, "99.0")],
)
async def test_fresh_permission_and_version_gate_precede_message_command(rights, center, firmware):
    instance, session, token = runtime()
    session.load_structure.return_value = replace(
        session.load_structure.return_value, user_rights=rights, message_center_uuid=center
    )
    instance.client.probe.return_value.firmware = firmware
    with pytest.raises(ControlOperationError):
        await instance.get_system_messages(access())
    session.system_messages.assert_not_awaited()
    session.close.assert_awaited_once()
    token.destroy.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enabled,scopes", [(False, [READ_SCOPE, HISTORY_SCOPE]), (True, [READ_SCOPE])]
)
async def test_history_denial_precedes_network(enabled, scopes) -> None:
    instance, session, token = runtime()
    instance.history_enabled = enabled
    with pytest.raises(ControlOperationError, match="History scope"):
        await instance.get_system_messages(
            access().model_copy(update={"scopes": scopes}), include_history=True
        )
    instance._open_session.assert_not_awaited()
    session.system_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_current_runtime_does_not_release_historical_records() -> None:
    instance, session, token = runtime()
    session.system_messages.return_value = {
        "entries": [entry(isHistoric=True, setHistoricAt=1_700_000_001)]
    }
    current = await instance.get_system_messages(access())
    assert current.records == [] and current.source_total == 1
    instance.history_enabled = True
    historical = await instance.get_system_messages(
        access().model_copy(update={"scopes": [READ_SCOPE, HISTORY_SCOPE]}), include_history=True
    )
    assert len(historical.records) == 1


@pytest.mark.asyncio
async def test_revocation_before_return_discards_source() -> None:
    instance, session, token = runtime()
    instance._require_access = AsyncMock(side_effect=[None, None, PermissionError()])
    with pytest.raises(PermissionError):
        await instance.get_system_messages(access())
    session.close.assert_awaited_once()
    token.destroy.assert_called_once()


@pytest.mark.asyncio
async def test_mcp_pagination_is_identity_query_revision_bound(monkeypatch) -> None:
    current = access()
    monkeypatch.setattr(tools, "_access", lambda: current)
    records = [entry(), entry(entryUuid=CENTER, isHistoric=True, setHistoricAt=1_700_000_001)]
    instance = SimpleNamespace(get_system_messages=AsyncMock(return_value=source(records)))
    server = FastMCP("messages")
    register_message_tools(server, instance)  # type: ignore[arg-type]
    tool = server._tool_manager.get_tool("loxone_get_system_messages")
    assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
    first = await tool.fn(mode="all", limit=1)
    assert first.ok and first.data.returned == 1 and first.data.cursor
    second = await tool.fn(mode="all", limit=1, cursor=first.data.cursor)
    assert second.ok and second.data.cursor is None
    changed_query = await tool.fn(mode="history", cursor=first.data.cursor)
    assert not changed_query.ok and changed_query.data.error == "invalid_cursor"
    current = current.model_copy(update={"family_id": "other"})
    changed_identity = await tool.fn(mode="all", cursor=first.data.cursor)
    assert not changed_identity.ok
    current = access()
    instance.get_system_messages.return_value = source(records[:1])
    changed_revision = await tool.fn(mode="all", cursor=first.data.cursor)
    assert not changed_revision.ok


@pytest.mark.asyncio
async def test_mcp_response_bound_and_truncation(monkeypatch) -> None:
    monkeypatch.setattr(tools, "_access", access)
    records = [
        entry(entryUuid=f"{i:08x}-1111-1111-1111111111111111", desc="ü" * 5000) for i in range(50)
    ]
    server = FastMCP("bounded-messages")
    register_message_tools(
        server, SimpleNamespace(get_system_messages=AsyncMock(return_value=source(records)))
    )
    result = await server._tool_manager.get_tool("loxone_get_system_messages").fn()
    assert result.ok and len(result.model_dump_json().encode()) <= 65_536
    assert result.data.truncated and not result.data.page_complete and result.data.cursor
