"""Pure time and evidence projection shared by history surfaces and analysis."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from math import isfinite
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from .state_semantics import SeriesSemantics
from .statistics import StatisticPoint


def utc_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")


def timezone(name: str) -> ZoneInfo:
    if not isinstance(name, str) or not 1 <= len(name) <= 128:
        raise ValueError("explicit IANA timezone is required")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("IANA timezone is unavailable") from exc


def local_midnight(day: date, zone: ZoneInfo) -> datetime:
    """Reject skipped or ambiguous midnight instead of choosing an invented offset."""
    naive = datetime.combine(day, datetime.min.time())
    candidates = {
        candidate.astimezone(UTC)
        for fold in (0, 1)
        if (candidate := naive.replace(tzinfo=zone, fold=fold))
        .astimezone(UTC)
        .astimezone(zone)
        .replace(tzinfo=None)
        == naive
    }
    if len(candidates) != 1:
        raise ValueError("local midnight is ambiguous or nonexistent")
    return candidates.pop()


def local_day_window(first: date, last_exclusive: date, timezone_name: str) -> tuple[float, float]:
    if not first < last_exclusive or (last_exclusive - first).days > 31:
        raise ValueError("local calendar window must contain 1 to 31 days")
    zone = timezone(timezone_name)
    return local_midnight(first, zone).timestamp(), local_midnight(last_exclusive, zone).timestamp()


def legacy_local_timestamp(seconds_since_2009: int, timezone_name: str) -> float:
    """Use only an explicitly supplied Miniserver timezone; reject DST folds/gaps."""
    zone = timezone(timezone_name)
    naive = datetime(2009, 1, 1) + timedelta(seconds=seconds_since_2009)
    candidates = {
        candidate.astimezone(UTC).timestamp()
        for fold in (0, 1)
        if (candidate := naive.replace(tzinfo=zone, fold=fold))
        .astimezone(UTC)
        .astimezone(zone)
        .replace(tzinfo=None)
        == naive
    }
    if len(candidates) != 1:
        raise ValueError("legacy local timestamp is ambiguous or nonexistent")
    return candidates.pop()


class HistoryInterval(BaseModel):
    start: str
    end: str


class CaptureInterval(HistoryInterval):
    initial_observed_at: str | None = None
    initial_value: bool | float | int | str | None = None
    initial_value_known: bool = False


class HistoryEvidence(BaseModel):
    method_version: Literal["history_evidence.v1"] = "history_evidence.v1"
    interval_convention: Literal["half_open"] = "half_open"
    time_basis: Literal["utc", "unverified_legacy_local", "unknown"]
    evidence_kind: Literal["point_observations", "interval_values", "event_capture"]
    intervals: list[HistoryInterval] = Field(default_factory=list, max_length=128)
    point_count: int = Field(default=0, ge=0, le=100_000)
    first_point_at: str | None = None
    last_point_at: str | None = None
    truncated: bool = False
    limitations: list[str] = Field(default_factory=list, max_length=16)


def capture_evidence(
    rows: tuple[tuple[float, float | None, float | None, object], ...],
    *,
    start: float,
    end: float,
    now: float,
    truncated: bool,
) -> tuple[list[CaptureInterval], HistoryEvidence]:
    phases = []
    intervals = []
    for phase_start, phase_end, observed_at, value in rows[:128]:
        actual_end = min(now, phase_end if phase_end is not None else now)
        if actual_end <= phase_start:
            continue
        scalar = value if isinstance(value, bool | float | int | str) else None
        known = (
            observed_at is not None
            and observed_at <= phase_start
            and scalar is not None
            and (not isinstance(scalar, float) or isfinite(scalar))
        )
        phases.append(
            CaptureInterval(
                start=utc_timestamp(phase_start),
                end=utc_timestamp(actual_end),
                initial_observed_at=utc_timestamp(observed_at)
                if known and observed_at is not None
                else None,
                initial_value=scalar if known else None,
                initial_value_known=known,
            )
        )
        usable_start, usable_end = max(start, phase_start), min(end, actual_end)
        if usable_start < usable_end:
            intervals.append(
                HistoryInterval(start=utc_timestamp(usable_start), end=utc_timestamp(usable_end))
            )
    return phases, HistoryEvidence(
        time_basis="utc",
        evidence_kind="event_capture",
        intervals=intervals,
        truncated=truncated or len(rows) > 128,
        limitations=[
            "capture_is_not_activity",
            "initial_value_applies_at_phase_start",
            "reconnect_gaps_are_not_covered",
        ],
    )


def statistic_evidence(
    points: tuple[StatisticPoint, ...],
    semantics: SeriesSemantics,
    *,
    has_more: bool,
) -> HistoryEvidence:
    if semantics.timestamp_basis is None:
        return HistoryEvidence(
            time_basis="unknown",
            evidence_kind="point_observations",
            truncated=has_more,
            limitations=["timestamp_basis_not_established"],
        )
    if semantics.timestamp_basis != "unix_utc":
        return HistoryEvidence(
            time_basis="unverified_legacy_local",
            evidence_kind="point_observations",
            truncated=has_more,
            limitations=["legacy_miniserver_timezone_not_verified"],
        )
    # Only documented hourly diff records represent an exact bounded interval.
    if (
        semantics.value_meaning == "interval_difference_sum"
        and semantics.timestamp_position == "interval_start"
    ):
        return HistoryEvidence(
            time_basis="utc",
            evidence_kind="interval_values",
            truncated=has_more or len(points) > 128,
            intervals=[
                HistoryInterval(
                    start=utc_timestamp(p.timestamp), end=utc_timestamp(p.timestamp + 3600)
                )
                for p in points[:128]
            ],
            limitations=["returned_records_only", "no_missing_interval_interpolation"],
        )
    return HistoryEvidence(
        time_basis="utc",
        evidence_kind="point_observations",
        truncated=has_more,
        point_count=len(points),
        first_point_at=utc_timestamp(points[0].timestamp) if points else None,
        last_point_at=utc_timestamp(points[-1].timestamp) if points else None,
        limitations=["points_do_not_prove_continuous_coverage", "no_inferred_sampling_rate"],
    )
