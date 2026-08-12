from __future__ import annotations

import gzip
import math
import struct
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from mcpserver.auth.provider import HISTORY_SCOPE, READ_SCOPE, StoredAccessToken
from mcpserver.loxone.events import LoxoneProtocolError
from mcpserver.loxone.models import Control, StatisticSeries
from mcpserver.loxone.runtime import LoxoneRuntime, _parse_legacy_statistic_points
from mcpserver.loxone.statistics import (
    StatisticPoint,
    StatisticsCache,
    parse_statistic_points,
)


def test_statistic_binary_parser_accepts_ordered_single_output_points() -> None:
    payload = struct.pack("<IdId", 100, 1.5, 200, -2.25)

    assert parse_statistic_points(payload) == (
        StatisticPoint(100, 1.5),
        StatisticPoint(200, -2.25),
    )


@pytest.mark.parametrize(
    "payload",
    [struct.pack("<I", 100), struct.pack("<IdId", 200, 1.0, 100, 2.0)],
)
def test_statistic_binary_parser_rejects_truncated_or_unordered_data(payload: bytes) -> None:
    with pytest.raises(LoxoneProtocolError):
        parse_statistic_points(payload)


def test_statistic_binary_parser_rejects_non_finite_values() -> None:
    with pytest.raises(LoxoneProtocolError):
        parse_statistic_points(struct.pack("<Id", 100, math.inf))


def test_legacy_statistic_binary_parser_selects_one_output() -> None:
    payload = struct.pack("<IddIdd", 100, 1.5, 10.0, 200, -2.25, 20.0)

    assert _parse_legacy_statistic_points(payload, output_index=1, output_count=2) == (
        StatisticPoint(100, 10.0),
        StatisticPoint(200, 20.0),
    )


@pytest.mark.asyncio
async def test_runtime_reads_bounded_legacy_raw_statistics() -> None:
    series = StatisticSeries(
        "legacy:1",
        "legacy",
        "1",
        "1",
        "Temperature",
        "%.1f °C",
        legacy_output_index=1,
        legacy_output_count=2,
    )
    control = Control(
        "control-1",
        "Temperature",
        "InfoOnlyAnalog",
        None,
        None,
        "action-1",
        (),
        statistic_series=(series,),
    )
    access = StoredAccessToken(
        token="opaque",
        client_id="client",
        scopes=[READ_SCOPE, HISTORY_SCOPE],
        expires_at=2_000_000_000,
        resource="https://loxberry.local/plugins/mcpserver/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="miniserver",
    )

    class Session:
        def __init__(self) -> None:
            self.dates: list[str] = []

        async def legacy_statistic_data(self, control_uuid: str, date: str) -> bytes:
            assert control_uuid == "control-1"
            self.dates.append(date)
            return struct.pack("<Idd", 100, 1.5, 20.0) if date == "200901" else b""

    session = Session()
    runtime = object.__new__(LoxoneRuntime)
    runtime.statistics_cache = StatisticsCache(None)

    @asynccontextmanager
    async def history_session(_access: StoredAccessToken, control_uuid: str):
        assert control_uuid == "control-1"
        yield control, session

    runtime._history_session = history_session  # type: ignore[method-assign]
    start = 1_230_768_050
    end = 1_230_768_150

    _control, returned_series, points = await runtime.get_statistics(
        access, "control-1", "legacy:1", start, end, "raw"
    )

    assert returned_series is series
    assert points == (StatisticPoint(1_230_768_100, 20.0),)
    assert session.dates == ["200901"]


@pytest.mark.asyncio
async def test_runtime_ignores_history_timestamps_outside_supported_range() -> None:
    control = Control(
        "control-1",
        "History",
        "Switch",
        None,
        None,
        "action-1",
        (),
        has_history=True,
    )
    access = StoredAccessToken(
        token="opaque",
        client_id="client",
        scopes=[READ_SCOPE, HISTORY_SCOPE],
        expires_at=2_000_000_000,
        resource="https://loxberry.local/plugins/mcpserver/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="miniserver",
    )

    class Session:
        async def control_history(self, action_uuid: str) -> list[dict[str, object]]:
            assert action_uuid == "action-1"
            return [
                {"ts": 2**63, "what": "invalid"},
                {"ts": 1_700_000_000, "what": "valid"},
            ]

    runtime = object.__new__(LoxoneRuntime)

    @asynccontextmanager
    async def history_session(_access: StoredAccessToken, control_uuid: str):
        assert control_uuid == "control-1"
        yield control, Session()

    runtime._history_session = history_session  # type: ignore[method-assign]

    _control, entries = await runtime.get_control_history(access, "control-1")

    assert [entry.timestamp for entry in entries] == [1_700_000_000]


def test_statistics_cache_expires_memory_and_clears_private_hybrid_files(
    tmp_path: Path,
) -> None:
    now = [10.0]
    cache = StatisticsCache(tmp_path.resolve(), ttl_seconds=5, clock=lambda: now[0])
    points = (StatisticPoint(100, 1.0),)
    key = cache.source_key("family", "control", "series")

    cache.put(key, points)
    cache.put_legacy_source(key, b"bounded source")

    assert cache.get(key) == points
    stored = list(tmp_path.glob("*.gz"))
    assert len(stored) == 1
    assert gzip.decompress(stored[0].read_bytes()) == b"bounded source"
    now[0] = 16.0
    assert cache.get(key) is None
    result = cache.clear()
    assert result.persistent_entries_removed == 1
    assert result.bytes_freed > 0
    assert list(tmp_path.iterdir()) == []


def test_statistics_cache_rejects_untrusted_persistent_key(tmp_path: Path) -> None:
    cache = StatisticsCache(tmp_path.resolve())

    cache.put_legacy_source("../escape", b"payload")

    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


def test_statistics_cache_purges_expired_and_bounds_memory_points() -> None:
    now = [10.0]
    cache = StatisticsCache(
        None,
        ttl_seconds=5,
        maximum_memory_points=2,
        clock=lambda: now[0],
    )
    point = StatisticPoint(100, 1.0)

    cache.put("expired", (point,))
    now[0] = 16.0
    cache.put("first", (point,))
    cache.put("second", (point,))
    cache.put("third", (point,))

    assert cache.get("expired") is None
    assert cache.get("first") is None
    assert cache.get("second") == (point,)
    assert cache.get("third") == (point,)
