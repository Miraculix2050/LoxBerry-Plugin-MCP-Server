from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from mcp.server.fastmcp import FastMCP

import mcpserver.tools as tools_module
from mcpserver.auth.provider import READ_SCOPE, StoredAccessToken
from mcpserver.loxone.models import (
    Control,
    Freshness,
    LoxoneIdentity,
    LoxoneStructure,
    StateRecord,
    StatisticSeries,
)
from mcpserver.loxone.runtime import LoxoneRuntime, RuntimeSnapshot, RuntimeUnavailable
from mcpserver.tools import ControlStateRefsData, register_read_tools


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


def _control(count: int, *, kind: str = "Dimmer", series_count: int = 0) -> Control:
    return Control(
        "00000000-0000-0000-0000-000000000001",
        "Fixture",
        kind,
        None,
        None,
        "action",
        tuple((f"state-{i}", f"10000000-0000-0000-0000-{i:012d}") for i in range(count)),
        statistic_series=tuple(
            StatisticSeries(f"series-{i}", "statistic_v2", "g", "o", f"Series {i}", "W")
            for i in range(series_count)
        ),
    )


def _structure(control: Control) -> LoxoneStructure:
    return LoxoneStructure(
        LoxoneIdentity("reader", "serial"),
        "same-marker",
        (),
        (),
        () if control.is_hidden else (control,),
        hidden_controls=(control,) if control.is_hidden else (),
    )


class _Runtime:
    def __init__(self, control: Control, *, connected: bool = True) -> None:
        self.current = self.cached = _structure(control)
        self.connected = connected
        self.fail_refresh = False
        self.fresh_requests: list[bool] = []
        self.state_reads: set[str] = set()
        self.gate = object.__new__(LoxoneRuntime)
        self.gate._rate = defaultdict(deque)
        self.gate._rate_limit = 1_000
        self.gate._parallel = asyncio.Semaphore(8)

    @asynccontextmanager
    async def call_slot(self, access: StoredAccessToken):
        async with self.gate.call_slot(access):
            yield

    async def snapshot(
        self, _access: StoredAccessToken, *, fresh_visibility: bool = False
    ) -> RuntimeSnapshot:
        self.fresh_requests.append(fresh_visibility)
        if fresh_visibility:
            if self.fail_refresh:
                raise RuntimeUnavailable("Miniserver structure refresh failed")
            self.cached = self.current
        return RuntimeSnapshot("family", self.cached, self.connected)

    def state(self, _snapshot: RuntimeSnapshot, uuid: str) -> StateRecord:
        self.state_reads.add(uuid)
        return StateRecord(uuid, 1.0, Freshness.CURRENT, 1_700_000_000.0)


def _server(monkeypatch: pytest.MonkeyPatch, runtime: _Runtime) -> FastMCP:
    monkeypatch.setattr(tools_module, "get_access_token", lambda: _access(READ_SCOPE))
    server = FastMCP("state-ref-contract")
    register_read_tools(server, runtime)  # type: ignore[arg-type]
    return server


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "count", "series_count", "truncated"),
    [
        ("Switch", 1, 0, False),
        ("Dimmer", 5, 0, False),
        ("Dimmer", 100, 0, False),
        ("Dimmer", 101, 0, False),
        ("Dimmer", 256, 0, False),
        ("Switch", 1, 128, False),
        ("Dimmer", 5, 128, False),
        ("Dimmer", 5, 128, True),
    ],
)
async def test_state_refs_measurement_and_complete_projection(
    monkeypatch: pytest.MonkeyPatch, kind: str, count: int, series_count: int, truncated: bool
) -> None:
    control = replace(
        _control(count, kind=kind, series_count=series_count), statistic_series_truncated=truncated
    )
    runtime = _Runtime(control)
    server = _server(monkeypatch, runtime)
    describe = server._tool_manager.get_tool("loxone_describe_control")
    assert describe is not None
    history = await describe.fn(control.uuid, view="history_targets")
    compact = await describe.fn(control.uuid, view="state_refs")
    assert history.ok and compact.ok
    assert isinstance(compact.data, ControlStateRefsData)
    data = compact.data.model_dump(mode="json")
    assert set(data) == {"uuid", "name", "type", "visibility", "view", "states"}
    assert data["states"] == history.data.model_dump(mode="json")["states"]
    assert len(data["states"]) == count
    assert runtime.fresh_requests == [False, True]
    if truncated:
        assert history.data.model_dump(mode="json")["capabilities"]["native_statistics_truncated"]

    sizes = []
    for result in (history, compact):
        envelope = result.model_dump(mode="json")
        envelope["observed_at"] = "2026-09-30T00:00:00Z"
        envelope["trace_id"] = "00000000-0000-0000-0000-000000000000"
        sizes.append(
            len(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        )
    baseline, proposed = sizes
    saving = baseline - proposed
    percent = 100 * saving / baseline
    print(
        f"state_refs kind={kind} states={count} series={series_count} truncated={truncated} "
        f"history={baseline} compact={proposed} saved={saving} percent={percent:.2f}"
    )
    assert saving > 0
    if count in {1, 5} and not series_count:
        assert percent >= 25
    if series_count:
        assert saving >= 1024


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 100, 101, 256])
async def test_state_refs_feed_complete_deduplicated_value_reads(
    monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    control = _control(count)
    if count:
        control = replace(
            control, state_uuids=(*control.state_uuids, ("alias", control.state_uuids[0][1]))
        )
    unrelated = _control(1)
    unrelated = replace(
        unrelated, uuid="other-control", state_uuids=(("foreign", "foreign-state"),)
    )
    runtime = _Runtime(control)
    runtime.current = runtime.cached = replace(runtime.current, controls=(control, unrelated))
    server = _server(monkeypatch, runtime)
    described = await server._tool_manager.call_tool(
        "loxone_describe_control", {"control_uuid": control.uuid, "view": "state_refs"}
    )
    assert described.ok
    assert isinstance(described.data, ControlStateRefsData)
    assert [(item.name, item.uuid) for item in described.data.states] == list(control.state_uuids)
    selected = list(dict.fromkeys(item.uuid for item in described.data.states))
    returned = []
    batch_sizes = []
    for offset in range(0, len(selected), 100):
        batch = selected[offset : offset + 100]
        result = await server._tool_manager.call_tool("loxone_get_states", {"state_uuids": batch})
        assert result.ok and not result.stale
        returned.extend(item["uuid"] for item in result.data.model_dump(mode="json")["states"])
        batch_sizes.append(len(batch))
    assert returned == selected
    assert runtime.state_reads == set(selected)
    assert batch_sizes == [min(100, count - offset) for offset in range(0, count, 100)]


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", ["direct", "linked", "hidden"])
async def test_state_refs_visibility_and_hidden_value_reads(
    monkeypatch: pytest.MonkeyPatch, visibility: str
) -> None:
    control = replace(
        _control(1), is_hidden=visibility == "hidden", is_user_linked=visibility == "linked"
    )
    runtime = _Runtime(control)
    server = _server(monkeypatch, runtime)
    describe = server._tool_manager.get_tool("loxone_describe_control")
    assert describe is not None
    if visibility == "hidden":
        denied = await describe.fn(control.uuid, view="state_refs")
        assert denied.data.model_dump()["error"] == "not_found"
    result = await describe.fn(control.uuid, view="state_refs", include_hidden=control.is_hidden)
    assert result.ok and isinstance(result.data, ControlStateRefsData)
    assert result.data.visibility == visibility
    uuids = [item.uuid for item in result.data.states]
    if control.is_hidden:
        denied_values = await server._tool_manager.call_tool(
            "loxone_get_states", {"state_uuids": uuids}
        )
        assert denied_values.data.model_dump()["error"] == "not_found"
    values = await server._tool_manager.call_tool(
        "loxone_get_states", {"state_uuids": uuids, "include_hidden": control.is_hidden}
    )
    assert values.ok


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["changed", "removed", "failed", "disconnected"])
async def test_state_refs_fresh_structure_and_failure_metadata(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    control = _control(1)
    runtime = _Runtime(control, connected=outcome != "disconnected")
    updated = replace(control, state_uuids=(("new-name", "new-state"),))
    runtime.current = replace(runtime.current, controls=(updated,) if outcome != "removed" else ())
    runtime.fail_refresh = outcome == "failed"
    server = _server(monkeypatch, runtime)
    describe = server._tool_manager.get_tool("loxone_describe_control")
    assert describe is not None
    result = await describe.fn(control.uuid, view="state_refs")
    assert runtime.fresh_requests == [True]
    if outcome in {"removed", "failed"}:
        assert not result.ok
        assert result.data.model_dump()["error"] == (
            "not_found" if outcome == "removed" else "temporarily_unavailable"
        )
    else:
        assert result.ok and isinstance(result.data, ControlStateRefsData)
        assert [(state.name, state.uuid) for state in result.data.states] == [
            ("new-name", "new-state")
        ]
        assert result.stale is (outcome == "disconnected")
        assert result.observed_at


@pytest.mark.asyncio
async def test_state_refs_requires_read_scope_and_call_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = _control(1)
    runtime = _Runtime(control)
    server = _server(monkeypatch, runtime)
    describe = server._tool_manager.get_tool("loxone_describe_control")
    assert describe is not None
    monkeypatch.setattr(tools_module, "get_access_token", lambda: None)
    unauthenticated = await describe.fn(control.uuid, view="state_refs")
    assert unauthenticated.data.model_dump()["error"] == "unauthenticated"
    assert runtime.fresh_requests == []
    monkeypatch.setattr(tools_module, "get_access_token", lambda: _access())
    denied = await describe.fn(control.uuid, view="state_refs")
    assert denied.data.model_dump()["error"] == "unauthenticated"
    assert runtime.fresh_requests == []
    monkeypatch.setattr(tools_module, "get_access_token", lambda: _access(READ_SCOPE))
    runtime.gate._rate_limit = 0
    limited = await describe.fn(control.uuid, view="state_refs")
    assert limited.data.model_dump()["error"] == "temporarily_unavailable"
    assert runtime.fresh_requests == []


@pytest.mark.asyncio
async def test_state_refs_waits_for_and_releases_existing_parallel_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = _control(1)
    runtime = _Runtime(control)
    runtime.gate._parallel = asyncio.Semaphore(0)
    server = _server(monkeypatch, runtime)
    describe = server._tool_manager.get_tool("loxone_describe_control")
    assert describe is not None
    task = asyncio.create_task(describe.fn(control.uuid, view="state_refs"))
    await asyncio.sleep(0)
    assert not task.done()
    assert runtime.fresh_requests == []
    runtime.gate._parallel.release()
    assert (await task).ok
    assert runtime.fresh_requests == [True]
    assert runtime.gate._parallel._value == 1


@pytest.mark.asyncio
async def test_state_refs_does_not_build_summary_and_rejects_unknown_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = _control(1, series_count=128)
    runtime = _Runtime(control)
    server = _server(monkeypatch, runtime)
    describe = server._tool_manager.get_tool("loxone_describe_control")
    assert describe is not None

    def unexpected_summary(*_args: object) -> None:
        raise AssertionError("state_refs must return before metadata projection")

    monkeypatch.setattr(tools_module, "_control_summary", unexpected_summary)
    assert (await describe.fn(control.uuid, view="state_refs")).ok
    unknown = await describe.fn("unknown", view="state_refs")
    assert unknown.data.model_dump()["error"] == "not_found"
