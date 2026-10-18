from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import ValidationError

from mcpserver.analysis_context import EnergyAnalysisContext, resolve_membership
from mcpserver.loxone.efm import Participant, Projection
from mcpserver.loxone.models import Control

PV = "00000000-0000-0000-0000000000000001"
LOAD = "00000000-0000-0000-0000000000000002"
METER = "00000000-0000-0000-0000000000000003"
MONITOR = "00000000-0000-0000-0000000000000004"


def context_document():
    return {
        "scope": {
            "kind": "scenario",
            "description": "One confirmed supply area",
            "common_supply_origin": "user_confirmed",
        },
        "assets": [
            {
                "asset_id": "roof",
                "description": "Confirmed production coverage",
                "production_control_uuid": METER,
                "association_origin": "user_confirmed",
            }
        ],
        "forecasts": [
            {"control_uuid": PV, "asset_ids": ["roof"], "coverage_origin": "user_confirmed"}
        ],
        "loads": [
            {
                "load_id": "pump",
                "kind": "real",
                "control_uuid": LOAD,
                "cycle": {
                    "timezone": "Europe/Berlin",
                    "windows": [
                        {"weekdays": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "23:59"}
                    ],
                    "latest_completion": "23:59",
                    "duration_seconds": 3600,
                    "interruptible": False,
                    "minimum_run_seconds": 0,
                    "minimum_off_seconds": 0,
                    "cycle_energy_wh": 1000.0,
                    "origin": "user_confirmed",
                    "rationale": "One complete owner-confirmed job",
                },
            }
        ],
    }


def test_request_load_needs_no_meter_or_persistent_profile():
    value = EnergyAnalysisContext.model_validate(context_document())
    flex = value.loads[0].cycle.flexibility("pump")
    assert flex.declared_cycle_energy_wh == 1000
    assert flex.cycle_identity == "user_confirmed_cycle"
    assert value.scope.monitor_uuid is None


@pytest.mark.parametrize("change", ["overlap", "unknown", "duplicate", "unconfirmed", "native"])
def test_invalid_forecast_coverage_or_forged_native_origin(change):
    doc = context_document()
    if change == "overlap":
        doc["forecasts"][0]["asset_ids"] *= 2
    elif change == "unknown":
        doc["forecasts"][0]["asset_ids"] = ["unknown"]
    elif change == "duplicate":
        doc["forecasts"] *= 2
    elif change == "native":
        doc["assets"][0]["association_origin"] = "native_efm"
    else:
        doc["assets"].append(
            {"asset_id": "shed", "description": "Shed", "association_origin": "user_confirmed"}
        )
        doc["forecasts"].append(
            {
                "control_uuid": LOAD,
                "asset_ids": ["shed"],
                "coverage_origin": "scenario_assumption",
            }
        )
    with pytest.raises(ValidationError):
        EnergyAnalysisContext.model_validate(doc)


def efm_context():
    doc = context_document()
    doc["scope"].update(kind="efm", monitor_uuid=MONITOR)
    return EnergyAnalysisContext.model_validate(doc)


def controls():
    consumer = Control(LOAD, "Same name", "Switch", None, None, None, ())
    meter = replace(consumer, uuid=METER)
    monitor = replace(
        consumer,
        uuid=MONITOR,
        control_type="EFM",
        efm=Projection(
            (Participant((0,), control_uuid=METER), Participant((1,), control_uuid=LOAD))
        ),
    )
    return {c.uuid: c for c in (consumer, meter, monitor)}


def test_efm_membership_is_server_derived_and_does_not_prove_physical_boundary():
    rows = resolve_membership(efm_context(), controls(), {"pump": LOAD})
    assert {row.origin for row in rows} == {"native_efm"}
    assert all(row.conditions for row in rows)


@pytest.mark.parametrize("bad", ["other_monitor", "hidden", "partial", "parent", "duplicate"])
def test_independent_efms_and_incomplete_or_overlapping_membership_fail_closed(bad):
    visible = controls()
    monitor = visible[MONITOR]
    rows = monitor.efm.participants
    projection = monitor.efm
    if bad == "other_monitor":
        projection = Projection((rows[0],))
    elif bad == "hidden":
        del visible[LOAD]
    elif bad == "partial":
        projection = replace(projection, omitted_subtrees=1)
    elif bad == "parent":
        projection = Projection((rows[0], replace(rows[1], path=(0, 0))))
    else:
        projection = Projection((rows[0], rows[1], rows[1]))
    visible[MONITOR] = replace(monitor, efm=projection)
    with pytest.raises(ValueError):
        resolve_membership(efm_context(), visible, {"pump": LOAD})


def test_hypothetical_load_cannot_claim_real_source_or_native_membership():
    doc = context_document()
    load = doc["loads"][0]
    load["kind"] = "hypothetical"
    with pytest.raises(ValidationError):
        EnergyAnalysisContext.model_validate(doc)
    del load["control_uuid"]
    load["cycle"]["origin"] = "scenario_assumption"
    value = EnergyAnalysisContext.model_validate(doc)
    rows = resolve_membership(value, controls(), {})
    assert rows[-1].control_uuid is None
    doc["scope"].update(kind="efm", monitor_uuid=MONITOR)
    with pytest.raises(ValidationError):
        EnergyAnalysisContext.model_validate(doc)


def test_real_source_is_derived_and_contradictory_mapping_is_rejected():
    value = EnergyAnalysisContext.model_validate(context_document())
    assert resolve_membership(value, controls(), {})[-1].control_uuid == LOAD
    with pytest.raises(ValueError, match="contradicts"):
        resolve_membership(value, controls(), {"pump": METER})


def test_display_diagnostics_do_not_remove_valid_efm_membership():
    visible = controls()
    projection = visible[MONITOR].efm
    projection = replace(
        projection,
        participants=tuple(
            replace(row, diagnostics=("invalid_role_token", "invalid_title", "invalid_icon"))
            for row in projection.participants
        ),
    )
    visible[MONITOR] = replace(visible[MONITOR], efm=projection)
    assert resolve_membership(efm_context(), visible, {"pump": LOAD})
