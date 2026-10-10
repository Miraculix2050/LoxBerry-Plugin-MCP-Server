"""Deterministic dedicated-socket interleavings and service authorization gates."""

import asyncio
import json
import struct
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.config import PluginConfig
from mcpserver.loxone.client import LoxoneSourceIpBlocked
from mcpserver.loxone.events import LoxoneProtocolError, MessageHeader, MessageType
from mcpserver.loxone.models import LoxoneIdentity, LoxoneStructure
from mcpserver.service_discovery import (
    AdminDiscovery,
    DiscoveryReceiver,
    DiscoveryUnavailable,
    binding,
)

STRUCTURE = LoxoneStructure(LoxoneIdentity("synthetic", "synthetic"), "", (), (), ())


class SocketHarness:
    def __init__(self):
        self.queue = asyncio.Queue()
        self._timeout = 1
        self._websocket = SimpleNamespace(send=AsyncMock())
        self.requests = 0
        self.frames = [(MessageType.BINARY_FILE, json.dumps({"controls": {}}))]

    async def _receive(self):
        return await self.queue.get()

    def put(self, kind, payload=None):
        self.queue.put_nowait((MessageHeader(kind, False, len(payload or b"")), payload))

    async def load_structure(self, *, receive):
        self.requests += 1
        for kind, payload in self.frames:
            self.put(kind, payload)
        await receive()
        return STRUCTURE


@pytest.mark.asyncio
async def test_one_receiver_dispatches_bounded_state_keepalive_structure_interleavings():
    socket = SocketHarness()
    socket.frames = [
        (MessageType.VALUE_STATES, struct.pack("<16sd", b"\0" * 16, 1.0)),
        (MessageType.KEEPALIVE, None),
        (MessageType.TEXT_STATES, b""),
        (MessageType.TEXT, '{"controls":{}}'),
    ]
    receiver = DiscoveryReceiver(socket)
    try:
        assert await receiver.load() is STRUCTURE
        assert await receiver.load() is STRUCTURE
        assert socket.requests == 2
    finally:
        await receiver.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "frames",
    [
        [(MessageType.BINARY_FILE, b"\x1f\x8bunknown")],
        [(MessageType.TEXT, '{"LL":{"control":"other","value":1}}')],
        [(MessageType.OUT_OF_SERVICE, None)],
        [(MessageType.VALUE_STATES, b"bad")],
        [(MessageType.KEEPALIVE, None)] * 33,
    ],
)
async def test_unknown_files_text_disconnect_and_overflow_are_terminal(frames):
    socket = SocketHarness()
    socket.frames = frames
    receiver = DiscoveryReceiver(socket)
    try:
        with pytest.raises((DiscoveryUnavailable, LoxoneProtocolError)):
            await receiver.load()
        assert receiver.failure is not None
        with pytest.raises((DiscoveryUnavailable, LoxoneProtocolError)):
            await receiver.load()
        assert socket.requests == 1
    finally:
        await receiver.close()


@pytest.mark.asyncio
async def test_unsolicited_file_is_never_queued_for_a_later_request():
    socket = SocketHarness()
    receiver = DiscoveryReceiver(socket)
    socket.put(MessageType.BINARY_FILE, '{"controls":{}}')
    await asyncio.sleep(0)
    with pytest.raises(DiscoveryUnavailable):
        await receiver.load()
    assert socket.requests == 0
    await receiver.close()


def owner_fixture(tmp_path, monkeypatch):
    import mcpserver.service_discovery as module

    config = [PluginConfig(enabled=True, loxone_endpoint="http://192.168.1.10")]
    credentials = ["synthetic", "synthetic-password"]
    store = AtomicJsonAuthStore(tmp_path / "auth.json")
    socket = SocketHarness()
    socket.close = AsyncMock()
    connects = []
    closes = []

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        async def connect(self, username, password):
            connects.append(1)
            return socket

        async def close(self):
            closes.append(1)

    async def load(_self):
        return tuple(credentials)

    monkeypatch.setattr(module.LoxBerryServiceCredentials, "load", load)
    monkeypatch.setattr(module, "ServiceMiniserverConnection", Connection)
    breaker = ["closed"]
    coordinator = SimpleNamespace(
        current_status=lambda: {"breaker_state": breaker[0]}, observe_source_ip_blocked=AsyncMock()
    )
    owner = AdminDiscovery(store, lambda: config[0], lambda _config: coordinator)

    def expected():
        return binding(store, config[0], *credentials)

    return owner, socket, expected, connects, closes, credentials, config, breaker


@pytest.mark.asyncio
async def test_simultaneous_and_later_requests_each_download_without_reauthentication(
    tmp_path, monkeypatch
):
    owner, socket, expected, connects, closes, *_ = owner_fixture(tmp_path, monkeypatch)
    try:
        first, second = await asyncio.gather(
            owner.project("event_history", expected()), owner.project("emergency_stop", expected())
        )
        third = await owner.project("event_history", expected())
        assert [
            first["timing"]["selector_auth_count"],
            second["timing"]["selector_auth_count"],
            third["timing"]["selector_auth_count"],
        ] == [1, 0, 0]
        assert socket.requests == 3 and len(connects) == 1
        assert first["projection"]["controls"] == []
        assert second["projection"] == {"status": "available", "options": []}
    finally:
        await owner.close()
    assert len(closes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["identity", "config", "blocked", "disabled"])
async def test_warm_reuse_invalidates_changed_identity_config_and_source_ip(
    tmp_path, monkeypatch, change
):
    owner, socket, expected, connects, closes, credentials, config, breaker = owner_fixture(
        tmp_path, monkeypatch
    )
    original = expected()
    await owner.project("event_history", original)
    if change == "identity":
        credentials[0] = "different"
    elif change == "config":
        config[0] = replace(config[0], loxone_endpoint="http://other.test")
    elif change == "blocked":
        breaker[0] = "open"
    else:
        config[0] = replace(config[0], enabled=False)
    try:
        with pytest.raises((DiscoveryUnavailable, LoxoneSourceIpBlocked)):
            await owner.project("event_history", original)
        assert socket.requests == 1 and len(connects) == 1 and len(closes) == 1
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_cancelled_file_request_drops_late_response_and_no_stale_fallback(
    tmp_path, monkeypatch
):
    owner, socket, expected, connects, closes, *_ = owner_fixture(tmp_path, monkeypatch)
    await owner.project("event_history", expected())
    socket.frames = []
    task = asyncio.create_task(owner.project("event_history", expected()))
    while socket.requests < 2:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    socket.put(MessageType.BINARY_FILE, '{"controls":{}}')
    assert owner.receiver is None and owner.connection is None
    assert len(closes) == 1 and len(connects) == 1
    await owner.close()


@pytest.mark.asyncio
async def test_shutdown_during_disposal_still_closes_connection(tmp_path, monkeypatch):
    owner, socket, expected, connects, closes, *_ = owner_fixture(tmp_path, monkeypatch)
    await owner.project("event_history", expected())
    entered = asyncio.Event()
    release = asyncio.Event()
    original_close = owner.receiver.close

    async def paused():
        entered.set()
        await release.wait()
        await original_close()

    owner.receiver.close = paused

    async def expiring():
        async with owner.lock:
            await owner._drop()

    owner.idle_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner.idle_task
    owner.idle_task = asyncio.create_task(expiring())
    await entered.wait()
    stopping = asyncio.create_task(owner.close())
    await asyncio.sleep(0)
    release.set()
    await stopping
    assert len(closes) == 1 and owner.disposal is None


@pytest.mark.asyncio
async def test_idle_and_absolute_age_require_new_connection(tmp_path, monkeypatch):
    owner, socket, expected, connects, closes, *_ = owner_fixture(tmp_path, monkeypatch)
    try:
        await owner.project("event_history", expected())
        owner.last_used -= 61
        await owner.project("event_history", expected())
        owner.created -= 301
        await owner.project("event_history", expected())
        assert len(connects) == 3 and len(closes) == 2 and socket.requests == 3
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_receiver_unanswered_keepalive_and_absolute_receive_deadline():
    socket = SocketHarness()
    socket._timeout = 0.01
    receiver = DiscoveryReceiver(socket)
    try:
        await receiver.task
        assert isinstance(receiver.failure, DiscoveryUnavailable)
        socket._websocket.send.assert_awaited_once_with("keepalive")
        with pytest.raises(DiscoveryUnavailable):
            await receiver.load()
    finally:
        await receiver.close()


@pytest.mark.asyncio
async def test_byte_budget_rejects_before_state_parsing():
    socket = SocketHarness()
    socket.frames = [(MessageType.VALUE_STATES, b"x" * (1024 * 1024 + 1))]
    receiver = DiscoveryReceiver(socket)
    with pytest.raises(DiscoveryUnavailable, match="frame limit"):
        await receiver.load()
    await receiver.close()


def test_local_helper_retains_emergency_retry_without_fallback_login(tmp_path, monkeypatch):
    import mcpserver.service_discovery as module

    async def credentials(_self):
        return "synthetic", "synthetic"

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return json.dumps(
                {"ok": False, "error": "authentication_cooldown", "retry_not_before": 1234567890}
            ).encode()

    monkeypatch.setattr(module.LoxBerryServiceCredentials, "load", credentials)
    monkeypatch.setattr(
        module,
        "build_opener",
        lambda *args: SimpleNamespace(open=lambda *args, **kwargs: Response()),
    )
    store = AtomicJsonAuthStore(tmp_path / "auth.json")
    result = module.request_projection(PluginConfig(), store, "emergency_stop")
    assert result == {
        "status": "unavailable",
        "options": [],
        "discovery_failure_code": "authentication_cooldown",
        "retry_not_before": 1234567890,
    }


def test_stopped_service_has_fixed_error_and_never_falls_back(tmp_path, monkeypatch):
    import mcpserver.service_discovery as module
    from mcpserver.admin import AdminError

    async def credentials(_self):
        return "synthetic", "synthetic"

    def unavailable(*args):
        raise OSError("private source value")

    monkeypatch.setattr(module.LoxBerryServiceCredentials, "load", credentials)
    monkeypatch.setattr(module, "build_opener", unavailable)
    store = AtomicJsonAuthStore(tmp_path / "auth.json")
    with pytest.raises(AdminError) as result:
        module.request_projection(PluginConfig(), store, "event_history")
    assert result.value.code == "temporarily_unavailable"
    assert "private" not in str(result.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload_phase", [False, True])
async def test_idle_4003_is_shared_and_prevents_next_authentication(
    tmp_path, monkeypatch, payload_phase
):
    from websockets.exceptions import ConnectionClosedError
    from websockets.frames import Close

    from mcpserver.loxone.auth_diagnostics import MiniserverAuthCoordinator

    owner, socket, expected, connects, closes, *_ = owner_fixture(tmp_path, monkeypatch)
    path = tmp_path / "diagnostics.json"
    coordinator = MiniserverAuthCoordinator(path, initial_probe_seconds=300)
    owner.coordinator_factory = lambda _config: coordinator
    await owner.project("event_history", expected())
    failure = (
        ConnectionClosedError(Close(4003, ""), None)
        if payload_phase
        else LoxoneSourceIpBlocked("synthetic")
    )

    async def blocked():
        raise failure

    socket._receive = blocked
    # Wake the receiver already waiting on its previous queue.get().
    socket.put(MessageType.KEEPALIVE)
    await owner.receiver.task
    assert coordinator.current_status()["breaker_state"] == "open_source_ip_blocked"
    another = MiniserverAuthCoordinator(path, initial_probe_seconds=300)
    assert another.current_status()["breaker_state"] == "open_source_ip_blocked"
    assert all(event["outcome"] != "attempt_started" for event in another._state["events"])
    with pytest.raises(LoxoneSourceIpBlocked):
        await owner.project("event_history", expected())
    assert len(connects) == 1 and len(closes) == 1
    await owner.close()


@pytest.mark.asyncio
async def test_identity_change_during_download_discards_result(tmp_path, monkeypatch):
    owner, socket, expected, connects, closes, credentials, *_ = owner_fixture(
        tmp_path, monkeypatch
    )
    original = socket.load_structure

    async def changed(**kwargs):
        result = await original(**kwargs)
        credentials[1] = "changed"
        return result

    socket.load_structure = changed
    with pytest.raises(DiscoveryUnavailable):
        await owner.project("event_history", expected())
    assert len(closes) == 1
    await owner.close()


@pytest.mark.asyncio
async def test_cancellation_while_queued_does_not_close_other_callers_socket(tmp_path, monkeypatch):
    owner, socket, expected, connects, closes, *_ = owner_fixture(tmp_path, monkeypatch)
    await owner.project("event_history", expected())
    socket.frames = []
    active = asyncio.create_task(owner.project("event_history", expected()))
    while socket.requests < 2:
        await asyncio.sleep(0)
    queued = asyncio.create_task(owner.project("event_history", expected()))
    await asyncio.sleep(0)
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    assert not closes
    socket.put(MessageType.BINARY_FILE, '{"controls":{}}')
    assert (await active)["projection"]["controls"] == []
    await owner.close()


@pytest.mark.asyncio
async def test_service_stop_discards_inflight_and_rejects_later_requests(tmp_path, monkeypatch):
    owner, socket, expected, connects, closes, *_ = owner_fixture(tmp_path, monkeypatch)
    await owner.project("event_history", expected())
    socket.frames = []
    active = asyncio.create_task(owner.project("event_history", expected()))
    while socket.requests < 2:
        await asyncio.sleep(0)
    stopping = asyncio.create_task(owner.close())
    await asyncio.sleep(0)
    socket.put(MessageType.BINARY_FILE, '{"controls":{}}')
    with pytest.raises(DiscoveryUnavailable):
        await active
    await stopping
    with pytest.raises(DiscoveryUnavailable):
        await owner.project("event_history", expected())
    assert len(connects) == 1 and len(closes) == 1
