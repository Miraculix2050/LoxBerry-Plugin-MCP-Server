"""Bounded visible alert evaluation; activity rules belong to the shared resolver."""

from collections.abc import Iterable, Mapping
from itertools import islice
from typing import Any

from .models import Control, Freshness, LoxoneStructure, StateRecord
from .state_semantics import StateSemanticsResolver

MAX_SCAN = 1000
MAX_STATES = 100
MAX_EVALUATIONS = 100
MAX_REASONS = 50
CANDIDATE_TYPES = frozenset(
    {
        "AalEmergency",
        "AalSmartAlarm",
        "Alarm",
        "AlarmChain",
        "SmokeAlarm",
        "StatusMonitor",
        "WindowMonitor",
    }
)


def select_sources(controls: Iterable[Control]) -> tuple[list[Control], bool]:
    """Bound traversal before sorting or reading any state, including nested controls."""
    stack = [iter(controls)]
    scanned = 0
    selected: list[Control] = []
    while stack:
        control = next(stack[-1], None)
        if control is None:
            stack.pop()
            continue
        if control.is_hidden:
            continue
        if scanned == MAX_SCAN:
            return sorted(selected, key=lambda c: c.uuid), False
        scanned += 1
        if not control.is_hidden and control.control_type in CANDIDATE_TYPES:
            selected.append(control)
        if not control.is_hidden:
            stack.append(iter(control.subcontrols))
    return sorted(selected, key=lambda c: c.uuid), True


def source_state(control: Control) -> tuple[str | None, str | None]:
    """Resolve the sole supported state without unbounded reference materialization."""
    refs = list(islice(control.state_uuids, 101))
    if len(refs) > 100:
        return None, "reference_budget"
    matches = [uuid for name, uuid in refs if name == "status"]
    return (matches[0], None) if len(matches) == 1 else (None, "missing_state")


def evaluate_alerts(
    structure: LoxoneStructure,
    sources: list[Control],
    records: Mapping[str, StateRecord],
    refs: Mapping[str, tuple[str | None, str | None]],
    *,
    scan_complete: bool,
    connected: bool,
) -> dict[str, Any]:
    """Evaluate only captured records. Unknown and stale never establish inactivity."""
    findings: list[dict[str, Any]] = []
    reasons: list[dict[str, str]] = []
    evaluated = unsupported = unavailable = attempts = 0
    resolver = StateSemanticsResolver()
    for control in sources:
        reason = None
        if control.control_type != "AalEmergency":
            unsupported += 1
            reason = "unsupported_family"
        else:
            uuid, reason = refs[control.uuid]
            if reason is None and uuid not in records:
                reason = "state_budget"
            if reason is None:
                assert uuid is not None
                record = records[uuid]
                if not connected:
                    reason = "disconnected"
                elif record.freshness is not Freshness.CURRENT:
                    reason = record.freshness.value
                elif record.value is None:
                    reason = "unavailable"
                elif attempts == MAX_EVALUATIONS:
                    reason = "decoder_budget"
                else:
                    attempts += 1
                    semantics, value = resolver.resolve(
                        structure, control, "status", record.value, {}
                    )
                    if semantics.interpretation_status != "known" or not isinstance(value, dict):
                        reason = "invalid"
                    else:
                        evaluated += 1
                        if value["alert_active"]:
                            findings.append(
                                {
                                    "control": control,
                                    "record": record,
                                    "semantics": semantics,
                                    "classification": value["status"],
                                }
                            )
            if reason is not None:
                unavailable += 1
        if reason is not None and len(reasons) < MAX_REASONS:
            reasons.append(
                {
                    "control_uuid": control.uuid,
                    "control_type": control.control_type,
                    "reason": reason,
                }
            )
    complete = connected and scan_complete and unsupported == 0 and unavailable == 0
    return {
        "findings": findings,
        "coverage": {
            "candidate_controls": len(sources) if scan_complete else None,
            "evaluated_controls": evaluated,
            "unsupported_controls": unsupported,
            "unavailable_controls": unavailable,
            "scan_complete": scan_complete,
            "complete": complete,
            "reasons": reasons,
            "reasons_truncated": unsupported + unavailable > len(reasons),
        },
        "known_active": len(findings),
        "total_active": len(findings) if complete else None,
    }
