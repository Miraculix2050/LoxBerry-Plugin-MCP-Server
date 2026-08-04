from __future__ import annotations

import pytest

from mcpserver.auth.provider import CONTROL_SCOPE, READ_SCOPE, StoredAccessToken
from mcpserver.loxone.client import LoxoneToken, MiniserverEndpoint
from mcpserver.loxone.events import StateEvent
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import (
    ControlOperationError,
    LoxoneRuntime,
    RuntimeSnapshot,
)


def _access(*scopes: str) -> StoredAccessToken:
    return StoredAccessToken(
        token="opaque",
        client_id="client",
        scopes=list(scopes),
        expires_at=2_000_000_000,
        resource="https://loxberry.local/plugins/mcpserver/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="miniserver",
    )


def _structure(control_type: str = "Switch") -> LoxoneStructure:
    return LoxoneStructure(
        identity=LoxoneIdentity("user", "serial"),
        last_modified="1",
        rooms=(),
        categories=(),
        controls=(
            Control(
                uuid="control-1",
                name="Light",
                control_type=control_type,
                room_uuid=None,
                category_uuid=None,
                action_uuid="action-1",
                state_uuids=(("active", "state-1"),),
            ),
        ),
    )


class _TokenStore:
    def get(self, *_args: object) -> LoxoneToken:
        return LoxoneToken("jwt", "user", "key", "SHA256", 2_000_000_000)


@pytest.mark.asyncio
async def test_switch_operation_is_sent_and_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        _TokenStore(),  # type: ignore[arg-type]
        control_confirmation_seconds=0.2,
    )
    runtime.cache.begin_connection("family")

    async def snapshot(_access: StoredAccessToken) -> RuntimeSnapshot:
        return RuntimeSnapshot("family", _structure(), True)

    class Session:
        async def load_structure(self) -> LoxoneStructure:
            return _structure()

        async def operate_switch(self, action_uuid: str, action: str) -> None:
            assert (action_uuid, action) == ("action-1", "on")
            runtime.cache.apply("family", [StateEvent("state-1", 1.0)], allowed_uuids={"state-1"})

        async def close(self) -> None:
            return None

    class Client:
        async def open_session(self, _token: LoxoneToken) -> Session:
            return Session()

    monkeypatch.setattr(runtime, "snapshot", snapshot)
    runtime.client = Client()  # type: ignore[assignment]

    result = await runtime.operate_switch(_access(READ_SCOPE, CONTROL_SCOPE), "control-1", "on")

    assert result.accepted is True
    assert result.confirmed is True
    assert result.observed_state == "on"


@pytest.mark.asyncio
async def test_control_requires_scope_and_supported_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        _TokenStore(),  # type: ignore[arg-type]
    )

    with pytest.raises(ControlOperationError, match="loxone:control"):
        await runtime.operate_switch(_access(READ_SCOPE), "control-1", "on")

    async def snapshot(_access: StoredAccessToken) -> RuntimeSnapshot:
        return RuntimeSnapshot("family", _structure(), True)

    class Session:
        async def load_structure(self) -> LoxoneStructure:
            return _structure("Dimmer")

        async def close(self) -> None:
            return None

    class Client:
        async def open_session(self, _token: LoxoneToken) -> Session:
            return Session()

    monkeypatch.setattr(runtime, "snapshot", snapshot)
    runtime.client = Client()  # type: ignore[assignment]
    with pytest.raises(ControlOperationError) as captured:
        await runtime.operate_switch(_access(READ_SCOPE, CONTROL_SCOPE), "control-1", "on")
    assert captured.value.code == "unsupported_control"


@pytest.mark.asyncio
async def test_transport_failure_after_dispatch_has_unknown_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        _TokenStore(),  # type: ignore[arg-type]
    )

    async def snapshot(_access: StoredAccessToken) -> RuntimeSnapshot:
        return RuntimeSnapshot("family", _structure(), True)

    class Session:
        async def load_structure(self) -> LoxoneStructure:
            return _structure()

        async def operate_switch(self, _action_uuid: str, _action: str) -> None:
            raise TimeoutError

        async def close(self) -> None:
            return None

    class Client:
        async def open_session(self, _token: LoxoneToken) -> Session:
            return Session()

    monkeypatch.setattr(runtime, "snapshot", snapshot)
    runtime.client = Client()  # type: ignore[assignment]

    with pytest.raises(ControlOperationError) as captured:
        await runtime.operate_switch(_access(READ_SCOPE, CONTROL_SCOPE), "control-1", "off")
    assert captured.value.code == "outcome_unknown"
