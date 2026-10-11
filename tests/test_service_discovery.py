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
        self._secure_transport = True
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

    def marker_reply(self, value="marker-a", code=200, control="jdev/sps/LoxAPPversion3"):
        async def send(command):
            assert command == "jdev/sps/LoxAPPversion3"
            self.put(MessageType.KEEPALIVE)
            self.put(MessageType.VALUE_STATES, b"")
            self.put(
                MessageType.TEXT,
                json.dumps(
                    {
                        "LL": {
                            "control": control,
                            "Code": code,
                            "value": value,
                        }
                    }
                ),
            )

        self._websocket.send.side_effect = send


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


@pytest.mark.asyncio
@pytest.mark.parametrize("marker", ["marker-a", "", None, 123])
async def test_marker_dispatch_accepts_only_the_fixed_reply_and_bounds_missing_values(marker):
    socket = SocketHarness()
    socket.marker_reply(marker)
    receiver = DiscoveryReceiver(socket)
    try:
        assert await receiver.marker() == (marker if marker == "marker-a" else None)
        assert await receiver.load() is STRUCTURE
    finally:
        await receiver.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("control", ["other", "dev/fsget/prog/sps.LoxCC"])
async def test_unrelated_marker_text_is_terminal(control):
    socket = SocketHarness()
    socket.marker_reply(control=control)
    receiver = DiscoveryReceiver(socket)
    try:
        with pytest.raises(DiscoveryUnavailable, match="unattributed"):
            await receiver.marker()
        assert receiver.failure is not None
    finally:
        await receiver.close()


@pytest.mark.asyncio
async def test_marker_source_ip_response_persists_block_without_fallback():
    socket = SocketHarness()
    socket.marker_reply(code=4003)
    observed = AsyncMock()
    receiver = DiscoveryReceiver(socket, on_source_ip_blocked=observed)
    try:
        with pytest.raises(LoxoneSourceIpBlocked):
            await receiver.marker()
        observed.assert_awaited_once()
        assert socket.requests == 0
    finally:
        await receiver.close()


@pytest.mark.asyncio
async def test_cancelled_marker_block_observation_is_owned_until_cleanup_finishes():
    socket = SocketHarness()
    socket.marker_reply(code=4003)
    started, release = asyncio.Event(), asyncio.Event()
    blocked = []

    async def observe():
        started.set()
        await release.wait()
        blocked.append(True)

    receiver = DiscoveryReceiver(socket, on_source_ip_blocked=observe)
    request = asyncio.create_task(receiver.marker())
    await started.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    cleanup = asyncio.create_task(receiver.close())
    await asyncio.sleep(0)
    assert not cleanup.done() and blocked == [] and socket.requests == 0
    release.set()
    await cleanup
    assert blocked == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 404])
async def test_marker_permission_denial_never_becomes_a_missing_marker(code):
    socket = SocketHarness()
    socket.marker_reply(code=code)
    receiver = DiscoveryReceiver(socket)
    try:
        if code == 404:
            assert await receiver.marker() is None
        else:
            with pytest.raises(DiscoveryUnavailable, match="permission denied"):
                await receiver.marker()
        assert socket.requests == 0
    finally:
        await receiver.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reply_control", ["plaintext", "encrypted", "decoded"])
async def test_gen1_marker_command_matches_only_its_exact_encrypted_or_plaintext_echo(
    reply_control,
):
    socket = SocketHarness()
    socket._secure_transport = False
    encrypted = []

    def encrypt(command):
        encrypted.append(command)
        return "jdev/sys/enc/synthetic%2Fcommand%3D"

    socket._encryptor = SimpleNamespace(encrypted_command=encrypt)

    async def send(command):
        assert command == "jdev/sys/enc/synthetic%2Fcommand%3D"
        control = {
            "plaintext": "jdev/sps/LoxAPPversion3",
            "encrypted": command,
            "decoded": "jdev/sys/enc/synthetic/command=",
        }[reply_control]
        socket.put(
            MessageType.TEXT,
            json.dumps(
                {
                    "LL": {
                        "control": control,
                        "Code": "200",
                        "value": "marker-a",
                    }
                }
            ),
        )

    socket._websocket.send.side_effect = send
    receiver = DiscoveryReceiver(socket)
    try:
        assert await receiver.marker() == "marker-a"
        assert encrypted == ["jdev/sps/LoxAPPversion3"]
    finally:
        await receiver.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["same", "changed", "missing", "stale", "old", "identity"])
async def test_display_cache_only_reuses_matching_successful_identity_bound_marker(
    tmp_path,
    monkeypatch,
    condition,
):
    from mcpserver.emergency_options_cache import EmergencyOptionsCache

    owner, socket, expected, connects, _, credentials, config, _ = owner_fixture(
        tmp_path, monkeypatch
    )
    cache = EmergencyOptionsCache(
        owner.store.path,
        owner.store.pseudonym(
            "emergency-stop-options-v1",
            config[0].loxone_endpoint,
            *credentials,
        ),
    )
    cache.refresh(
        lambda: {
            "status": "available",
            "options": [{"uuid": "saved", "name": "Signal"}],
            "project_marker": None if condition == "old" else "marker-a",
        }
    )
    if condition == "stale":
        cache.refresh(lambda: {"status": "unavailable", "options": []})
    if condition == "identity":
        credentials[0] = "new-identity"
    socket.marker_reply(
        None if condition == "missing" else "marker-b" if condition == "changed" else "marker-a"
    )
    try:
        result = await owner.project("emergency_stop_display", expected())
        assert socket.requests == (0 if condition == "same" else 1)
        assert len(connects) == 1
        assert result["projection"]["options"] == (
            [{"uuid": "saved", "name": "Signal"}] if condition == "same" else []
        )
        # Ordinary discovery still downloads regardless of marker/cache.
        await owner.project("emergency_stop", expected())
        assert socket.requests == (1 if condition == "same" else 2)
    finally:
        await owner.close()


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
        assert second["projection"] == {"status": "available", "options": [], "project_marker": ""}
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


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,deadline", [("event_history", 35), ("emergency_stop", 90)])
async def test_projection_preserves_existing_discovery_deadline(
    tmp_path, monkeypatch, kind, deadline
):
    import mcpserver.service_discovery as module

    owner, socket, expected, *_rest = owner_fixture(tmp_path, monkeypatch)
    config = _rest[-2]
    config[0] = replace(config[0], connection_timeout=60)
    budgets = []
    real_timeout = asyncio.timeout

    def observed_timeout(seconds):
        budgets.append(seconds)
        return real_timeout(seconds)

    monkeypatch.setattr(module.asyncio, "timeout", observed_timeout)
    try:
        await owner.project(kind, expected())
        assert budgets[0] == deadline
        assert socket.requests == 1
    finally:
        await owner.close()


@pytest.mark.parametrize("kind,deadline", [("event_history", 36), ("emergency_stop", 91)])
def test_local_helper_outlives_projection_discovery_deadline(tmp_path, monkeypatch, kind, deadline):
    import json

    import mcpserver.service_discovery as module

    async def credentials(_self):
        return "synthetic", "synthetic-password"

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return json.dumps({"ok": True, "projection": {}, "timing": {}}).encode()

    observed = []

    class Opener:
        def open(self, request, *, timeout):
            observed.append(timeout)
            return Response()

    monkeypatch.setattr(module.LoxBerryServiceCredentials, "load", credentials)
    monkeypatch.setattr(module, "build_opener", lambda *handlers: Opener())
    assert (
        module.request_projection(
            PluginConfig(connection_timeout=60), AtomicJsonAuthStore(tmp_path / "auth.json"), kind
        )
        == {}
    )
    assert observed == [deadline]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,category",
    [
        (TimeoutError("private-payload"), "timeout"),
        (OSError("private-payload"), "connection"),
        (LoxoneProtocolError("private-payload"), "protocol"),
    ],
)
async def test_failure_diagnostic_retains_phase_and_masks_exception(
    tmp_path, monkeypatch, caplog, failure, category
):
    owner, socket, expected, *_ = owner_fixture(tmp_path, monkeypatch)
    await owner.project("event_history", expected())

    async def failed_marker():
        raise failure

    monkeypatch.setattr(owner.receiver, "marker", failed_marker)
    try:
        with pytest.raises(type(failure)):
            await owner.project("emergency_stop_display", expected(), request_id="abc-123")
        message = caplog.records[-1].getMessage()
        assert "request_id=abc-123" in message
        assert "phase=marker_check" in message
        assert f"code={category}" in message
        assert "session_mode=held" in message
        assert "pending_requests=1" in message
        assert "private-payload" not in message
        assert "synthetic-password" not in message
        assert owner.pending_requests == 0
        assert owner.receiver is None
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_queued_cancellation_diagnostic_does_not_drop_active_session(
    tmp_path, monkeypatch, caplog
):
    owner, socket, expected, *_ = owner_fixture(tmp_path, monkeypatch)
    await owner.project("event_history", expected())
    await owner.lock.acquire()
    task = asyncio.create_task(
        owner.project("emergency_stop", expected(), request_id="secret\nforged")
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    owner.lock.release()
    message = caplog.records[-1].getMessage()
    assert "request_id=-" in message and "forged" not in message
    assert "phase=discovery_wait" in message and "code=cancelled" in message
    assert owner.pending_requests == 0
    assert owner.receiver is not None
    await owner.close()


@pytest.mark.parametrize(
    "request_id,expected_id", [("abc-123", "abc-123"), ("private\nforged", "-")]
)
def test_helper_forwards_only_valid_cgi_request_id(tmp_path, monkeypatch, request_id, expected_id):
    import mcpserver.service_discovery as module

    async def credentials(_self):
        return "synthetic", "synthetic"

    captured = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return b'{"ok":true,"projection":{}}'

    def opened(request, **kwargs):
        captured.append(request.get_header("X-loxberry-admin-request"))
        return Response()

    monkeypatch.setenv("MCPSERVER_ADMIN_REQUEST_ID", request_id)
    monkeypatch.setattr(module.LoxBerryServiceCredentials, "load", credentials)
    monkeypatch.setattr(module, "build_opener", lambda *args: SimpleNamespace(open=opened))
    module.request_projection(
        PluginConfig(), AtomicJsonAuthStore(tmp_path / "auth.json"), "emergency_stop"
    )
    assert captured == [expected_id]


@pytest.mark.asyncio
async def test_real_receiver_timeout_has_typed_category():
    import mcpserver.service_discovery as module

    socket = SocketHarness()
    socket._timeout = 0.01
    socket.frames = []
    receiver = DiscoveryReceiver(socket)
    try:
        with pytest.raises(module.DiscoveryTimeout) as error:
            await receiver.load()
        assert module._failure_category(error.value) == "timeout"
    finally:
        await receiver.close()


def test_normalized_disconnect_retains_fixed_category():
    from websockets.exceptions import ConnectionClosedOK

    from mcpserver.loxone.client import LoxoneConnectionError
    from mcpserver.service_discovery import _failure_category

    try:
        try:
            raise ConnectionClosedOK(None, None)
        except ConnectionClosedOK:
            raise LoxoneConnectionError("private") from None
    except LoxoneConnectionError as error:
        assert _failure_category(error) == "disconnect"


def test_both_admin_cgis_forward_request_correlation():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for name in ("index.cgi", "event_history.cgi"):
        assert (
            "local $ENV{MCPSERVER_ADMIN_REQUEST_ID} = $request_id;"
            in (root / "webfrontend/htmlauth" / name).read_text()
        )


@pytest.mark.asyncio
async def test_failure_pending_count_includes_later_queued_request(tmp_path, monkeypatch, caplog):
    owner, socket, expected, *_ = owner_fixture(tmp_path, monkeypatch)
    await owner.project("event_history", expected())
    entered, release = asyncio.Event(), asyncio.Event()

    async def failed_marker():
        entered.set()
        await release.wait()
        raise TimeoutError()

    monkeypatch.setattr(owner.receiver, "marker", failed_marker)
    first = asyncio.create_task(owner.project("emergency_stop_display", expected()))
    await entered.wait()
    second = asyncio.create_task(owner.project("event_history", expected()))
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(TimeoutError):
        await first
    await second
    messages = [r.getMessage() for r in caplog.records if "outcome=failed" in r.getMessage()]
    assert "pending_requests=2" in messages[-1]
    assert owner.pending_requests == 0
    await owner.close()


def test_fixed_failure_categories_do_not_parse_messages():
    import mcpserver.service_discovery as module
    from mcpserver.loxone.auth_diagnostics import (
        MiniserverAuthenticationCooldown,
        MiniserverAuthenticationSuppressed,
    )
    from mcpserver.loxone.client import LoxoneTokenAuthenticationRejected

    errors = [
        (module.DiscoveryTimeout("private"), "timeout"),
        (module.DiscoveryDisconnected("private"), "disconnect"),
        (module.DiscoveryProtocolFailure("private"), "protocol"),
        (module.DiscoveryPermissionDenied("private"), "permission_denied"),
        (module.DiscoveryIdentityChanged("private"), "identity_changed"),
        (module.DiscoveryStopped("private"), "service_stopped"),
        (LoxoneSourceIpBlocked("private"), "source_ip_blocked"),
        (MiniserverAuthenticationCooldown("private"), "authentication_cooldown"),
        (MiniserverAuthenticationSuppressed("private"), "authentication_busy"),
        (
            LoxoneTokenAuthenticationRejected("private", response_code="401"),
            "authentication_rejected",
        ),
        (RuntimeError("timeout disconnect authentication_busy"), "unknown"),
    ]
    for error, category in errors:
        assert module._failure_category(error) == category


def test_source_ip_suppression_is_not_ordinary_auth_contention():
    from mcpserver.loxone.auth_diagnostics import MiniserverSourceIpSuppressed
    from mcpserver.service_discovery import _failure_category

    assert _failure_category(MiniserverSourceIpSuppressed("private")) == "source_ip_blocked"


def test_wrapped_handshake_timeout_retains_timeout_category():
    from mcpserver.loxone.client import LoxoneConnectionError
    from mcpserver.service_discovery import _failure_category

    try:
        try:
            raise TimeoutError("private")
        except TimeoutError as original:
            raise LoxoneConnectionError("private") from original
    except LoxoneConnectionError as error:
        assert _failure_category(error) == "timeout"
