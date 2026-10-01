"""Bounded visible alert evaluation; activity rules belong to the shared resolver."""

from collections.abc import Iterable, Mapping
from itertools import islice
from typing import Any

from .models import Control, Freshness, LoxoneStructure, StateRecord
from .state_semantics import ALERT_FAMILIES, StateSemanticsResolver

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


def source_states(control: Control) -> tuple[dict[str, str], str | None]:
    """Resolve bounded primary, required and optional references in read order."""
    refs = list(islice(control.state_uuids, 101))
    if len(refs) > 100:
        return {}, "reference_budget"
    family = ALERT_FAMILIES[control.control_type]
    selected: dict[str, str] = {}
    for name in (family.primary, *sorted(family.required), *sorted(family.optional)):
        matches = [uuid for key, uuid in refs if key == name]
        if len(matches) == 1:
            selected[name] = matches[0]
        elif name == family.primary or name in family.required:
            return {}, "missing_state"
    return selected, None


def evaluate_alerts(
    structure: LoxoneStructure,
    sources: list[Control],
    records: Mapping[str, StateRecord],
    refs: Mapping[str, tuple[dict[str, str], str | None]],
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
        if control.control_type not in ALERT_FAMILIES:
            unsupported += 1
            reason = "unsupported_family"
        else:
            state_refs, reason = refs[control.uuid]
            family = ALERT_FAMILIES[control.control_type]
            required = (family.primary, *family.required)
            if reason is None and any(state_refs[name] not in records for name in required):
                reason = "state_budget"
            if reason is None:
                uuid = state_refs[family.primary]
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
                    companions = {
                        name: records[state_uuid].value
                        for name, state_uuid in state_refs.items()
                        if name != family.primary
                        and state_uuid in records
                        and records[state_uuid].freshness is Freshness.CURRENT
                    }
                    semantics, value = resolver.resolve(
                        structure, control, family.primary, record.value, companions
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
                                    "semantic_value": value,
                                    "classification": "alarm_triggered",
                                    "state_name": family.primary,
                                    "context": value.get("context"),
                                    "companions": [
                                        (name, records[state_uuid])
                                        for name, state_uuid in state_refs.items()
                                        if name != family.primary and state_uuid in records
                                    ],
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
