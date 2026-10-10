from __future__ import annotations

import asyncio
import json
import multiprocessing
import threading
import time
from pathlib import Path

import pytest

from mcpserver.loxone.auth_diagnostics import (
    AttemptProvenance,
    MiniserverAuthCoordinator,
    MiniserverAuthenticationCooldown,
    MiniserverAuthenticationSuppressed,
    _interprocess_lock,
)
from mcpserver.loxone.client import (
    LoxoneCommandRejected,
    LoxoneConnectionError,
    LoxoneSourceIpBlocked,
    LoxoneTokenAuthenticationRejected,
)


@pytest.mark.asyncio
async def test_source_ip_block_suppresses_before_another_network_attempt(tmp_path: Path) -> None:
    coordinator = MiniserverAuthCoordinator(
        (tmp_path / "auth-diagnostics.json").resolve(), initial_probe_seconds=300
    )
    calls = 0

    async def blocked() -> None:
        nonlocal calls
        calls += 1
        raise LoxoneSourceIpBlocked("blocked")

    with pytest.raises(LoxoneSourceIpBlocked):
        await coordinator.attempt(blocked, owner="tool_request", phase="token_authentication")
    with pytest.raises(MiniserverAuthenticationSuppressed):
        await coordinator.attempt(blocked, owner="tool_request", phase="token_authentication")

    assert calls == 1
    assert coordinator.status()["breaker_state"] == "open_source_ip_blocked"
    assert coordinator.status()["backoff_seconds"] == 300


@pytest.mark.asyncio
async def test_separate_coordinators_reload_a_shared_open_breaker(tmp_path: Path) -> None:
    path = (tmp_path / "auth-diagnostics.json").resolve()
    service_coordinator = MiniserverAuthCoordinator(path, initial_probe_seconds=300)
    admin_coordinator = MiniserverAuthCoordinator(path, initial_probe_seconds=300)

    async def blocked() -> None:
        raise LoxoneSourceIpBlocked("blocked")

    with pytest.raises(LoxoneSourceIpBlocked):
        await admin_coordinator.attempt(blocked, owner="local_admin", phase="token_acquisition")

    calls = 0

    async def must_not_run() -> None:
        nonlocal calls
        calls += 1

    with pytest.raises(MiniserverAuthenticationSuppressed):
        await service_coordinator.attempt(
            must_not_run, owner="runtime_event_stream", phase="session_establishment"
        )

    assert calls == 0


@pytest.mark.asyncio
async def test_interprocess_authentication_attempt_is_suppressed_without_waiting(
    tmp_path: Path,
) -> None:
    path = (tmp_path / "auth-diagnostics.json").resolve()
    coordinator = MiniserverAuthCoordinator(path)
    calls = 0

    async def must_not_run() -> None:
        nonlocal calls
        calls += 1

    lock_path = path.with_name(f".{path.name}.lock")
    with _interprocess_lock(lock_path), pytest.raises(MiniserverAuthenticationSuppressed):
        await coordinator.attempt(must_not_run, owner="tool_request", phase="session_establishment")

    assert calls == 0


@pytest.mark.asyncio
async def test_admin_authentication_waits_for_shared_lock(tmp_path: Path) -> None:
    path = (tmp_path / "auth-diagnostics.json").resolve()
    coordinator = MiniserverAuthCoordinator(path)
    lock_path = path.with_name(f".{path.name}.lock")
    acquired = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with _interprocess_lock(lock_path):
            acquired.set()
            release.wait(timeout=3)

    holder = threading.Thread(target=hold_lock, daemon=True)
    holder.start()
    try:
        assert await asyncio.to_thread(acquired.wait, 2)

        async def finish_other_attempt() -> None:
            await asyncio.sleep(0.2)
            release.set()

        release_task = asyncio.create_task(finish_other_attempt())
        started = time.monotonic()

        async def authenticated() -> str:
            return "authenticated"

        result = await coordinator.attempt(
            authenticated,
            owner="local_admin",
            phase="token_acquisition",
            busy_wait_seconds=1,
        )
        await release_task
        assert result == "authenticated"
        assert time.monotonic() - started >= 0.15
    finally:
        release.set()
        holder.join(timeout=3)
    assert not holder.is_alive()


@pytest.mark.asyncio
async def test_admin_authentication_reports_busy_after_wait_timeout(tmp_path: Path) -> None:
    path = (tmp_path / "auth-diagnostics.json").resolve()
    coordinator = MiniserverAuthCoordinator(path)
    called = False

    async def must_not_run() -> None:
        nonlocal called
        called = True

    lock_path = path.with_name(f".{path.name}.lock")
    started = time.monotonic()
    with _interprocess_lock(lock_path), pytest.raises(MiniserverAuthenticationSuppressed):
        await coordinator.attempt(
            must_not_run,
            owner="local_admin",
            phase="token_acquisition",
            busy_wait_seconds=0.2,
        )
    assert time.monotonic() - started >= 0.18
    assert not called


@pytest.mark.asyncio
async def test_response_code_4003_opens_source_ip_breaker(tmp_path: Path) -> None:
    coordinator = MiniserverAuthCoordinator(
        (tmp_path / "auth-diagnostics.json").resolve(), initial_probe_seconds=300
    )

    async def rejected() -> None:
        raise LoxoneCommandRejected("rejected", response_code="4003")

    with pytest.raises(LoxoneCommandRejected):
        await coordinator.attempt(rejected, owner="tool_request", phase="token_authentication")

    assert coordinator.status()["breaker_state"] == "open_source_ip_blocked"
    assert coordinator.status()["backoff_seconds"] == 300


@pytest.mark.asyncio
async def test_failed_cooldown_probe_restarts_breaker_interval(tmp_path: Path) -> None:
    coordinator = MiniserverAuthCoordinator(
        (tmp_path / "auth-diagnostics.json").resolve(), initial_probe_seconds=300
    )

    async def blocked() -> None:
        raise LoxoneSourceIpBlocked("blocked")

    with pytest.raises(LoxoneSourceIpBlocked):
        await coordinator.attempt(blocked, owner="tool_request", phase="token_authentication")
    coordinator._state["opened_at"] = 0

    async def transport_failure() -> None:
        raise LoxoneConnectionError("connection failed")

    with pytest.raises(LoxoneConnectionError):
        await coordinator.attempt(
            transport_failure, owner="tool_request", phase="token_authentication"
        )

    status = coordinator.status()
    assert status["breaker_state"] == "open_source_ip_blocked"
    opened_at = status["opened_at"]
    retry_not_before = status["retry_not_before"]
    assert isinstance(opened_at, int) and opened_at > 0
    assert isinstance(retry_not_before, int)
    assert retry_not_before > opened_at


@pytest.mark.asyncio
async def test_cancelled_cooldown_probe_restarts_breaker_interval(tmp_path: Path) -> None:
    coordinator = MiniserverAuthCoordinator(
        (tmp_path / "auth-diagnostics.json").resolve(), initial_probe_seconds=300
    )

    async def blocked() -> None:
        raise LoxoneSourceIpBlocked("blocked")

    with pytest.raises(LoxoneSourceIpBlocked):
        await coordinator.attempt(blocked, owner="tool_request", phase="token_authentication")
    coordinator._state["opened_at"] = 0

    async def cancelled() -> None:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await coordinator.attempt(
            cancelled,
            owner="tool_request",
            phase="token_authentication",
            force_probe=True,
        )

    status = coordinator.status()
    assert status["breaker_state"] == "open_source_ip_blocked"
    opened_at = status["opened_at"]
    retry_not_before = status["retry_not_before"]
    assert isinstance(opened_at, int) and opened_at > 0
    assert isinstance(retry_not_before, int)
    assert retry_not_before > opened_at

    calls = 0

    async def must_not_run() -> None:
        nonlocal calls
        calls += 1

    with pytest.raises(MiniserverAuthenticationSuppressed):
        await coordinator.attempt(must_not_run, owner="tool_request", phase="token_authentication")

    assert calls == 0


@pytest.mark.asyncio
async def test_persistence_failure_prevents_network_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = MiniserverAuthCoordinator((tmp_path / "auth-diagnostics.json").resolve())

    def cannot_save() -> None:
        raise OSError("diagnostics unavailable")

    monkeypatch.setattr(coordinator, "_save", cannot_save)

    async def succeeds() -> str:
        pytest.fail("Unpersisted authentication must not reach the network")

    with pytest.raises(MiniserverAuthenticationCooldown):
        await coordinator.attempt(succeeds, owner="tool_request", phase="session_establishment")


@pytest.mark.asyncio
async def test_source_ip_block_remains_gated_when_persistence_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = MiniserverAuthCoordinator(
        (tmp_path / "auth-diagnostics.json").resolve(), initial_probe_seconds=300
    )

    save = coordinator._save
    saved = 0

    def cannot_save() -> None:
        nonlocal saved
        saved += 1
        if saved > 1:
            raise OSError("diagnostics unavailable")
        save()

    monkeypatch.setattr(coordinator, "_save", cannot_save)

    async def blocked() -> None:
        raise LoxoneSourceIpBlocked("blocked")

    with pytest.raises(LoxoneSourceIpBlocked):
        await coordinator.attempt(blocked, owner="tool_request", phase="token_authentication")

    calls = 0

    async def must_not_run() -> None:
        nonlocal calls
        calls += 1

    with pytest.raises(MiniserverAuthenticationSuppressed):
        await coordinator.attempt(must_not_run, owner="tool_request", phase="token_authentication")

    assert calls == 0


@pytest.mark.asyncio
async def test_only_own_tool_events_are_returned(tmp_path: Path) -> None:
    coordinator = MiniserverAuthCoordinator((tmp_path / "auth-diagnostics.json").resolve())

    async def succeeds() -> str:
        await asyncio.sleep(0)
        return "session"

    await coordinator.attempt(
        succeeds,
        owner="tool_request",
        phase="session_establishment",
        provenance=AttemptProvenance(trace_id="trace", binding_id="binding-a"),
    )
    await coordinator.attempt(
        succeeds,
        owner="runtime_event_stream",
        phase="session_establishment",
    )

    events = coordinator.events_for("binding-a")
    assert len(events) == 2
    assert {event["outcome"] for event in events} == {"attempt_started", "authenticated"}
    assert all(event["trace_id"] == "trace" for event in events)
    assert coordinator.events_for("binding-b") == []


async def _reject_auth() -> None:
    raise LoxoneTokenAuthenticationRejected("rejected", response_code="401")


async def _authenticate() -> str:
    return "authenticated"


async def _open_guard(coordinator: MiniserverAuthCoordinator) -> None:
    for _ in range(3):
        with pytest.raises(LoxoneTokenAuthenticationRejected):
            await coordinator.attempt(
                _reject_auth, owner="tool_request", phase="session_establishment"
            )


@pytest.mark.asyncio
async def test_shared_guard_threshold_window_and_success_do_not_erase_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000]
    monkeypatch.setattr("mcpserver.loxone.auth_diagnostics.time.time", lambda: now[0])
    path = tmp_path / "auth.json"
    coordinator = MiniserverAuthCoordinator(path)
    for _ in range(2):
        with pytest.raises(LoxoneTokenAuthenticationRejected):
            await coordinator.attempt(
                _reject_auth, owner="tool_request", phase="session_establishment"
            )
        await coordinator.attempt(_authenticate, owner="local_admin", phase="token_acquisition")
    assert coordinator.status()["failure_count"] == 2
    with pytest.raises(LoxoneTokenAuthenticationRejected):
        await coordinator.attempt(_reject_auth, owner="tool_request", phase="session_establishment")
    restarted = MiniserverAuthCoordinator(path)
    assert restarted.status()["next_auth_attempt_at"] == 1060
    assert restarted.status()["breaker_state"] == "closed"
    for owner in ("tool_request", "runtime_event_stream", "local_admin"):
        with pytest.raises(MiniserverAuthenticationCooldown):
            await restarted.attempt(_authenticate, owner=owner, phase="session_establishment")
    now[0] = 1060
    await restarted.attempt(_authenticate, owner="tool_request", phase="session_establishment")
    assert restarted.status()["failure_guard_state"] == "closed"
    assert restarted.status()["failure_count"] == 3
    now[0] = 1300
    assert restarted.status()["failure_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        LoxoneCommandRejected("permission", response_code="401"),
        LoxoneCommandRejected("permission", response_code="403"),
        LoxoneConnectionError("network"),
        TimeoutError(),
        asyncio.CancelledError(),
    ],
)
async def test_only_typed_auth_rejections_consume_budget(
    tmp_path: Path, error: BaseException
) -> None:
    coordinator = MiniserverAuthCoordinator(tmp_path / "auth.json")

    async def fail() -> None:
        raise error

    for _ in range(4):
        with pytest.raises(type(error)):
            await coordinator.attempt(fail, owner="tool_request", phase="project_download")
    assert coordinator.status()["failure_count"] == 0
    assert coordinator.status()["failure_guard_state"] == "closed"


@pytest.mark.asyncio
async def test_rejected_probes_escalate_and_manual_probes_are_globally_spaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000]
    monkeypatch.setattr("mcpserver.loxone.auth_diagnostics.time.time", lambda: now[0])
    path = tmp_path / "auth.json"
    coordinator = MiniserverAuthCoordinator(path)
    await _open_guard(coordinator)
    for delay in (120, 240, 480, 960, 1920, 3600, 3600):
        now[0] += 60
        coordinator = MiniserverAuthCoordinator(path)
        with pytest.raises(LoxoneTokenAuthenticationRejected):
            await coordinator.attempt(
                _reject_auth, owner="local_admin", phase="token_acquisition", early_probe=True
            )
        assert coordinator.status()["next_auth_attempt_at"] == now[0] + delay
        other = MiniserverAuthCoordinator(path)
        with pytest.raises(MiniserverAuthenticationCooldown):
            await other.attempt(
                _authenticate, owner="local_admin", phase="token_acquisition", early_probe=True
            )
        with pytest.raises(ValueError):
            await other.attempt(
                _authenticate, owner="tool_request", phase="token_acquisition", early_probe=True
            )
        with pytest.raises(MiniserverAuthenticationCooldown):
            await other.attempt(
                _authenticate,
                owner="runtime_event_stream",
                phase="token_acquisition",
                force_probe=True,
            )


@pytest.mark.asyncio
async def test_transport_probe_restarts_pause_without_escalating_and_access_is_checked_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000]
    monkeypatch.setattr("mcpserver.loxone.auth_diagnostics.time.time", lambda: now[0])
    coordinator = MiniserverAuthCoordinator(tmp_path / "auth.json")
    await _open_guard(coordinator)

    async def deny() -> None:
        raise PermissionError("revoked")

    with pytest.raises(PermissionError):
        await coordinator.attempt(
            _authenticate, owner="tool_request", phase="session", before_attempt=deny
        )
    now[0] = 1060

    async def timeout() -> None:
        raise TimeoutError()

    with pytest.raises(TimeoutError):
        await coordinator.attempt(timeout, owner="tool_request", phase="session")
    assert coordinator.status()["next_auth_attempt_at"] == 1120
    assert coordinator.status()["failure_count"] == 3


@pytest.mark.asyncio
async def test_crash_reservation_and_corrupt_state_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000]
    monkeypatch.setattr("mcpserver.loxone.auth_diagnostics.time.time", lambda: now[0])
    path = tmp_path / "auth.json"
    coordinator = MiniserverAuthCoordinator(path)
    coordinator._state["failure_guard"]["pending_until"] = 1060
    coordinator._save()
    restarted = MiniserverAuthCoordinator(path)
    with pytest.raises(MiniserverAuthenticationCooldown):
        await restarted.attempt(
            _authenticate, owner="local_admin", phase="session", early_probe=True
        )
    now[0] = 1060
    await restarted.attempt(_authenticate, owner="local_admin", phase="session")
    path.write_text("{invalid", encoding="utf-8")
    restarted = MiniserverAuthCoordinator(path)
    with pytest.raises(MiniserverAuthenticationCooldown):
        await restarted.attempt(_authenticate, owner="tool_request", phase="session")
    assert restarted.status()["failure_guard_state"] == "persistence_uncertain"


@pytest.mark.asyncio
async def test_legacy_state_migration_and_source_ip_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000]
    monkeypatch.setattr("mcpserver.loxone.auth_diagnostics.time.time", lambda: now[0])
    path = tmp_path / "auth.json"
    coordinator = MiniserverAuthCoordinator(path)
    del coordinator._state["failure_guard"]
    path.write_text(json.dumps(coordinator._state), encoding="utf-8")
    coordinator = MiniserverAuthCoordinator(path)
    await _open_guard(coordinator)
    now[0] = 1060

    async def blocked() -> None:
        raise LoxoneSourceIpBlocked("blocked")

    with pytest.raises(LoxoneSourceIpBlocked):
        await coordinator.attempt(blocked, owner="local_admin", phase="session", early_probe=True)
    assert coordinator.status()["manual_probe_at"] is None
    now[0] = 1120
    with pytest.raises(MiniserverAuthenticationSuppressed):
        await coordinator.attempt(
            _authenticate, owner="local_admin", phase="session", early_probe=True
        )


def _process_rejection(path: str, queue: object, barrier: object, probe: bool = False) -> None:
    async def run() -> None:
        coordinator = MiniserverAuthCoordinator(Path(path))
        barrier.wait(timeout=20)  # type: ignore[attr-defined]
        try:
            await coordinator.attempt(
                _authenticate if probe else _reject_auth,
                owner="local_admin" if probe else "tool_request",
                phase="session",
                busy_wait_seconds=5,
                early_probe=probe,
            )
            queue.put("authenticated")  # type: ignore[attr-defined]
        except LoxoneTokenAuthenticationRejected:
            queue.put("rejected")  # type: ignore[attr-defined]
        except MiniserverAuthenticationCooldown:
            queue.put("suppressed")  # type: ignore[attr-defined]

    asyncio.run(run())


def test_process_race_allows_only_three_rejected_attempts(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    barrier = context.Barrier(5)
    processes = [
        context.Process(
            target=_process_rejection, args=(str(tmp_path / "auth.json"), queue, barrier)
        )
        for _ in range(5)
    ]
    for process in processes:
        process.start()
    results = [queue.get(timeout=30) for _ in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    queue.close()
    assert results.count("rejected") == 3
    assert results.count("suppressed") == 2


@pytest.mark.asyncio
async def test_status_read_during_attempt_does_not_replace_its_guard(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    coordinator = MiniserverAuthCoordinator(path)

    async def reject_after_status() -> None:
        assert coordinator.current_status()["failure_guard_state"] == "cooldown"
        await _reject_auth()

    with pytest.raises(LoxoneTokenAuthenticationRejected):
        await coordinator.attempt(reject_after_status, owner="tool_request", phase="session")
    assert MiniserverAuthCoordinator(path).status()["failure_count"] == 1
    assert coordinator._state["failure_guard"]["pending_until"] == 0


def test_process_race_allows_only_one_successful_manual_probe(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    coordinator = MiniserverAuthCoordinator(path)
    asyncio.run(_open_guard(coordinator))
    coordinator._state["failure_guard"]["last_probe"] = int(time.time()) - 61
    coordinator._state["failure_guard"]["until"] = int(time.time()) + 300
    coordinator._save()
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    barrier = context.Barrier(5)
    processes = [
        context.Process(target=_process_rejection, args=(str(path), queue, barrier, True))
        for _ in range(5)
    ]
    for process in processes:
        process.start()
    results = [queue.get(timeout=30) for _ in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    queue.close()
    assert results.count("authenticated") == 1
    assert results.count("suppressed") == 4
