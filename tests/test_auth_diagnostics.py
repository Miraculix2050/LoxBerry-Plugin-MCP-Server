from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mcpserver.loxone.auth_diagnostics import (
    AttemptProvenance,
    MiniserverAuthCoordinator,
    MiniserverAuthenticationSuppressed,
)
from mcpserver.loxone.client import LoxoneSourceIpBlocked


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
