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


def _structure(
    control_type: str = "Switch",
    *,
    states: tuple[tuple[str, str], ...] = (("active", "state-1"),),
    automatic: bool = False,
    read_only: bool = False,
) -> LoxoneStructure:
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
                state_uuids=states,
                is_automatic=automatic,
                read_only=read_only,
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

        async def operate_control(self, action_uuid: str, command: str) -> None:
            assert (action_uuid, command) == ("action-1", "on")
            runtime.cache.apply("family", [StateEvent("state-1", 1.0)], allowed_uuids={"state-1"})

        async def close(self) -> None:
            return None

    class Client:
        async def open_session(self, _token: LoxoneToken) -> Session:
            return Session()

    monkeypatch.setattr(runtime, "snapshot", snapshot)
    runtime.client = Client()  # type: ignore[assignment]

    result = await runtime.operate_control(_access(READ_SCOPE, CONTROL_SCOPE), "control-1", "on")

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
        await runtime.operate_control(_access(READ_SCOPE), "control-1", "on")

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
        await runtime.operate_control(_access(READ_SCOPE, CONTROL_SCOPE), "control-1", "set_mood")
    assert captured.value.code == "invalid_input"


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

        async def operate_control(self, _action_uuid: str, _command: str) -> None:
            raise TimeoutError

        async def close(self) -> None:
            return None

    class Client:
        async def open_session(self, _token: LoxoneToken) -> Session:
            return Session()

    monkeypatch.setattr(runtime, "snapshot", snapshot)
    runtime.client = Client()  # type: ignore[assignment]

    with pytest.raises(ControlOperationError) as captured:
        await runtime.operate_control(_access(READ_SCOPE, CONTROL_SCOPE), "control-1", "off")
    assert captured.value.code == "outcome_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("control_type", "action", "kwargs", "command", "state_name", "state_value"),
    [
        ("Dimmer", "set_level", {"level": 40}, "40", "position", 40.0),
        ("LightController", "set_mood", {"mood_id": "7"}, "7", "activeScene", 7.0),
        (
            "LightControllerV2",
            "set_mood",
            {"mood_id": "ID12"},
            "changeTo/ID12",
            "activeMoods",
            '["ID12"]',
        ),
        (
            "Jalousie",
            "set_position",
            {"position": 25},
            "manualPosition/25",
            "targetPosition",
            0.25,
        ),
        ("Jalousie", "enable_auto", {}, "auto", "autoActive", 1.0),
    ],
)
async def test_supported_control_operation_is_bounded_and_confirmed(
    monkeypatch: pytest.MonkeyPatch,
    control_type: str,
    action: str,
    kwargs: dict[str, object],
    command: str,
    state_name: str,
    state_value: float | str,
) -> None:
    runtime = LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        _TokenStore(),  # type: ignore[arg-type]
        control_confirmation_seconds=0.2,
    )
    runtime.cache.begin_connection("family")
    structure = _structure(
        control_type,
        states=((state_name, "state-1"),),
        automatic=action == "enable_auto",
    )

    async def snapshot(_access: StoredAccessToken) -> RuntimeSnapshot:
        return RuntimeSnapshot("family", structure, True)

    class Session:
        async def load_structure(self) -> LoxoneStructure:
            return structure

        async def operate_control(self, action_uuid: str, actual: str) -> None:
            assert (action_uuid, actual) == ("action-1", command)
            runtime.cache.apply(
                "family", [StateEvent("state-1", state_value)], allowed_uuids={"state-1"}
            )

        async def close(self) -> None:
            return None

    class Client:
        async def open_session(self, _token: LoxoneToken) -> Session:
            return Session()

    monkeypatch.setattr(runtime, "snapshot", snapshot)
    runtime.client = Client()  # type: ignore[assignment]

    result = await runtime.operate_control(
        _access(READ_SCOPE, CONTROL_SCOPE),
        "control-1",
        action,
        **kwargs,  # type: ignore[arg-type]
    )

    assert result.control_type == control_type
    assert result.confirmed is True
    assert dict(result.observed_values)[state_name] == state_value


@pytest.mark.asyncio
async def test_read_only_restriction_prevents_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"),
        _TokenStore(),  # type: ignore[arg-type]
    )
    structure = _structure(read_only=True)

    async def snapshot(_access: StoredAccessToken) -> RuntimeSnapshot:
        return RuntimeSnapshot("family", structure, True)

    class Session:
        async def load_structure(self) -> LoxoneStructure:
            return structure

        async def close(self) -> None:
            return None

    class Client:
        async def open_session(self, _token: LoxoneToken) -> Session:
            return Session()

    monkeypatch.setattr(runtime, "snapshot", snapshot)
    runtime.client = Client()  # type: ignore[assignment]

    with pytest.raises(ControlOperationError) as captured:
        await runtime.operate_control(_access(READ_SCOPE, CONTROL_SCOPE), "control-1", "on")

    assert captured.value.code == "permission_denied"
