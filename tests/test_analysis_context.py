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
    assert value.loads[0].cycle.flexibility("pump").cycle_identity == "active_episode_only"
    assert resolve_membership(value, controls(), {"pump": LOAD})[-1].control_uuid is None
    doc["scope"].update(kind="efm", monitor_uuid=MONITOR)
    with pytest.raises(ValidationError):
        EnergyAnalysisContext.model_validate(doc)


@pytest.mark.parametrize("overlap", ["same_path", "parent"])
def test_distinct_day_metrics_do_not_bypass_native_topology_overlap(overlap):
    from mcpserver.analysis_context import resolve_selected_membership

    visible = controls()
    monitor = visible[MONITOR]
    visible[MONITOR] = replace(
        monitor,
        efm=Projection(
            (
                Participant((0,), control_uuid=METER),
                Participant((0,) if overlap == "same_path" else (0, 0), control_uuid=LOAD),
            )
        ),
    )
    with pytest.raises(ValueError, match="overlapping|duplicate"):
        resolve_selected_membership(
            efm_context().scope,
            visible,
            [("pv", METER, "user_confirmed"), ("self", LOAD, "user_confirmed")],
            contribution_roles={"pv": "production", "self": "self_consumption"},
        )
    with pytest.raises(ValueError, match="duplicate"):
        resolve_selected_membership(
            efm_context().scope,
            visible,
            [("pv", METER, "user_confirmed"), ("self", METER, "user_confirmed")],
        )


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


def test_asset_and_load_ids_cannot_collide_in_resolved_provenance():
    doc = context_document()
    doc["loads"][0]["load_id"] = "roof"
    with pytest.raises(ValidationError, match="duplicate"):
        EnergyAnalysisContext.model_validate(doc)


@pytest.mark.parametrize(
    "change", ["none", "child", "duplicate", "missing", "hidden", "profile_conflict"]
)
def test_history_associations_use_exact_members_without_profile_writes(change):
    from mcpserver.analysis_context import HistoryAnalysisContext, resolve_history_associations
    from mcpserver.loxone.models import StatisticSeries
    from mcpserver.loxone.runtime import ControlOperationError

    identifier = LOAD + "/exact-child" if change == "child" else LOAD
    series = StatisticSeries("energy", "statistic_v2", "1", "totalNeg", "Same name", "Wh")
    visible = {identifier: replace(controls()[LOAD], uuid=identifier, statistic_series=(series,))}
    selector = {"control_uuid": identifier, "series_id": "energy", "state_uuid": None}
    declaration = {
        "association_id": "load",
        "source_index": 0,
        "role": "consumer",
        "measurement_boundary": "load-meter",
        "origin": "user_confirmed",
    }
    bindings = {}
    selectors = [selector]
    declarations = [declaration]
    if change == "duplicate":
        selectors.append(dict(selector))
        declarations.append({**declaration, "association_id": "duplicate", "source_index": 1})
    elif change == "missing":
        selector["series_id"] = "not-a-member"
    elif change == "hidden":
        visible[identifier] = replace(visible[identifier], is_hidden=True)
    elif change == "profile_conflict":
        selectors = [{"binding_id": "saved"}]
        bindings = {
            "saved": {
                **selector,
                "status": "confirmed",
                "role": "consumer",
                "measurement_boundary": "other-meter",
            }
        }
    ctx = HistoryAnalysisContext.model_validate(
        {
            "scope": {
                "kind": "scenario",
                "description": "Independent supply",
                "common_supply_origin": "user_confirmed",
            },
            "associations": declarations,
        }
    )
    if change in {"none", "child"}:
        effective, result = resolve_history_associations(
            ctx, selectors, visible, bindings, timezone_name="UTC"
        )
        assert effective[0]["control_uuid"] == identifier
        assert result[0].binding_id is None and result[0].control_uuid == identifier
    else:
        with pytest.raises((ValueError, ControlOperationError)):
            resolve_history_associations(ctx, selectors, visible, bindings, timezone_name="UTC")


@pytest.mark.parametrize("foreign", [False, True])
@pytest.mark.parametrize("stored", [False, True])
def test_declared_real_feedback_retains_saved_operating_companion(foreign, stored):
    from mcpserver.analysis_context import (
        DeclaredCycle,
        HistoryAnalysisContext,
        resolve_history_associations,
    )
    from mcpserver.loxone.models import StatisticSeries

    state, other_state = "active-state", "other-state"
    visible = {
        LOAD: replace(
            controls()[LOAD],
            statistic_series=(
                StatisticSeries("energy", "statistic_v2", "1", "totalNeg", "Energy", "Wh"),
            ),
            state_uuids=(("active", state), ("other", other_state)),
        )
    }
    cycle = DeclaredCycle.model_validate(context_document()["loads"][0]["cycle"])
    consumer = {
        "control_uuid": LOAD,
        "series_id": "energy",
        "state_uuid": None,
        "status": "confirmed",
        "role": "consumer",
        "load_constraints_usable": True,
        "load_flexibility": cycle.flexibility("saved-active").model_dump(),
    }
    active = {
        "control_uuid": LOAD,
        "series_id": None,
        "state_uuid": state,
        "status": "confirmed",
        "role": "operating_state",
    }
    other = {**active, "state_uuid": other_state}
    ctx = HistoryAnalysisContext.model_validate(
        {
            "scope": context_document()["scope"],
            "associations": [
                {"association_id": "load", "source_index": 0, "origin": "user_confirmed"},
                {"association_id": "active", "source_index": 1, "origin": "user_confirmed"},
            ],
            "loads": [
                {
                    "load_id": "model",
                    "kind": "declared_real",
                    "consumer_id": "load",
                    "operating_id": "active",
                    "cycle": cycle.model_dump(),
                }
            ],
        }
    )
    if not stored:
        consumer.pop("load_flexibility")
        consumer["load_constraints_usable"] = False
    selectors = [
        {"binding_id": "saved"},
        {"binding_id": "other-active" if foreign else "saved-active"},
    ]
    bindings = {"saved": consumer, "saved-active": active, "other-active": other}
    if foreign or not stored:
        with pytest.raises(ValueError, match="companion"):
            resolve_history_associations(
                ctx, selectors, visible, bindings, timezone_name="Europe/Berlin"
            )
    else:
        effective, _ = resolve_history_associations(
            ctx, selectors, visible, bindings, timezone_name="Europe/Berlin"
        )
        assert effective[1]["state_uuid"] == state


def test_inherited_profile_cycle_timezone_is_checked_before_source_reads():
    from test_load_flexibility import flexibility

    from mcpserver.analysis_context import HistoryAnalysisContext, resolve_history_associations
    from mcpserver.loxone.models import StatisticSeries

    series = StatisticSeries("energy", "statistic_v2", "1", "totalNeg", "Energy", "Wh")
    state = "00000000-0000-0000-0000000000000011"
    visible = {
        LOAD: replace(
            controls()[LOAD], statistic_series=(series,), state_uuids=(("active", state),)
        )
    }
    consumer = {
        "control_uuid": LOAD,
        "series_id": "energy",
        "state_uuid": None,
        "status": "confirmed",
        "role": "consumer",
        "load_constraints_usable": True,
        "load_flexibility": flexibility(
            timezone="UTC", operating_binding_id="saved-active"
        ).model_dump(),
    }
    active = {
        "control_uuid": LOAD,
        "series_id": None,
        "state_uuid": state,
        "status": "confirmed",
        "role": "operating_state",
    }
    ctx = HistoryAnalysisContext.model_validate(
        {
            "scope": {
                "kind": "scenario",
                "description": "One budget",
                "common_supply_origin": "user_confirmed",
            },
            "associations": [
                {"association_id": "load", "source_index": 0, "origin": "user_confirmed"},
                {"association_id": "active", "source_index": 1, "origin": "user_confirmed"},
            ],
            "loads": [
                {
                    "load_id": "measured",
                    "kind": "observed",
                    "consumer_id": "load",
                    "operating_id": "active",
                }
            ],
        }
    )
    with pytest.raises(ValueError, match="effective cycle timezone"):
        resolve_history_associations(
            ctx,
            [{"binding_id": "saved"}, {"binding_id": "saved-active"}],
            visible,
            {"saved": consumer, "saved-active": active},
            timezone_name="Europe/Berlin",
        )


@pytest.mark.parametrize("role", ["consumer", "self_consumption", "grid_export", "production"])
def test_history_membership_keeps_same_named_independent_efms_separate(role):
    from mcpserver.analysis_context import HistoryAnalysisContext, resolve_history_associations
    from mcpserver.loxone.models import StatisticSeries

    second_load = "00000000-0000-0000-0000000000000021"
    second_monitor = "00000000-0000-0000-0000000000000022"
    series = StatisticSeries("energy", "statistic_v2", "1", "totalNeg", "Same name", "Wh")
    visible = controls()
    visible[LOAD] = replace(visible[LOAD], statistic_series=(series,))
    visible[second_load] = replace(visible[LOAD], uuid=second_load)
    visible[second_monitor] = replace(
        visible[MONITOR],
        uuid=second_monitor,
        efm=Projection((Participant((0,), control_uuid=second_load),)),
    )
    for monitor, own, foreign in (
        (MONITOR, LOAD, second_load),
        (second_monitor, second_load, LOAD),
    ):
        ctx = HistoryAnalysisContext.model_validate(
            {
                "scope": {
                    "kind": "efm",
                    "monitor_uuid": monitor,
                    "description": "Independent budget",
                    "common_supply_origin": "user_confirmed",
                },
                "associations": [
                    {
                        "association_id": "load",
                        "source_index": 0,
                        "role": role,
                        "origin": "user_confirmed",
                    }
                ],
            }
        )
        _, result = resolve_history_associations(
            ctx, [{"control_uuid": own, "series_id": "energy"}], visible, {}, timezone_name="UTC"
        )
        assert result[0].origin == "native_efm" and result[0].monitor_uuid == monitor
        with pytest.raises(ValueError, match="participant"):
            resolve_history_associations(
                ctx,
                [{"control_uuid": foreign, "series_id": "energy"}],
                visible,
                {},
                timezone_name="UTC",
            )


@pytest.mark.asyncio
async def test_optional_profile_resolution_never_opens_or_creates_store(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from mcpserver.analysis_context import read_profile_bindings

    store = Mock(side_effect=AssertionError("profile must remain optional"))
    monkeypatch.setattr("mcpserver.installation_profile.ProfileStore", store)
    assert await read_profile_bindings(None, "unused", None, required=False) == ({}, None)
    assert await read_profile_bindings(
        tmp_path / "absent" / "profile.json", "unused", None, required=False
    ) == ({}, None)
    assert not (tmp_path / "absent").exists()
    store.assert_not_called()


@pytest.mark.parametrize("status", ["draft", "needs_review", "invalid", None])
def test_resolver_cannot_upgrade_confirmation(status):
    from mcpserver.analysis_context import resolve_source_association
    from mcpserver.loxone.runtime import ControlOperationError

    with pytest.raises(ControlOperationError) as failure:
        resolve_source_association(
            "alias",
            controls(),
            binding_id="saved",
            origin="user_confirmed",
            bindings={"saved": {"status": status, "control_uuid": LOAD}},
        )
    assert failure.value.code == "not_found"


def test_resolver_preserves_alias_and_rejects_contradictory_or_hidden_sources():
    from mcpserver.analysis_context import resolve_source_association
    from mcpserver.loxone.runtime import ControlOperationError

    bindings = {"saved": {"status": "confirmed", "role": "consumer", "control_uuid": LOAD}}
    result = resolve_source_association(
        "alias", controls(), bindings=bindings, binding_id="saved", expected_role="consumer"
    )
    assert result.association.identifier == "alias"
    assert result.association.origin == "user_confirmed"
    assert result.association.control_uuid == LOAD
    with pytest.raises(ValueError, match="choose"):
        resolve_source_association(
            "alias", controls(), bindings=bindings, binding_id="saved", control_uuid=METER
        )
    visible = controls()
    visible[LOAD] = replace(visible[LOAD], is_hidden=True)
    with pytest.raises(ControlOperationError):
        resolve_source_association("alias", visible, bindings=bindings, binding_id="saved")
    with pytest.raises(ControlOperationError):
        resolve_source_association(
            "alias", controls(), bindings=bindings, binding_id="saved", expected_role="production"
        )


@pytest.mark.parametrize("change", ["identity", "hidden", "source", "revision", "companion"])
def test_publication_guard_detects_source_and_companion_changes(change):
    from mcpserver.analysis_context import SourceSnapshot
    from mcpserver.loxone.models import LoxoneIdentity, LoxoneStructure
    from mcpserver.loxone.runtime import ControlOperationError

    structure = LoxoneStructure(
        LoxoneIdentity("reader", "SYNTHETIC"), "current", (), (), tuple(controls().values())
    )
    bindings = {"consumer": {"status": "confirmed"}, "active": {"status": "confirmed"}}
    guard = SourceSnapshot.capture(
        "http://synthetic.local", structure, {LOAD}, bindings, 7, {"consumer", "active"}
    )
    guard.validate("http://synthetic.local", structure, bindings, 7)
    revision = 7
    if change == "identity":
        structure = replace(structure, identity=LoxoneIdentity("reader", "OTHER"))
    elif change in {"hidden", "source"}:
        structure = replace(
            structure,
            controls=tuple(
                replace(c, is_hidden=True)
                if change == "hidden"
                else replace(c, control_type="Other")
                for c in structure.controls
            ),
        )
    elif change == "revision":
        revision = 8
    else:
        # In-place edits must not alter the captured initial comparison value.
        bindings["active"]["status"] = "draft"
    with pytest.raises(ControlOperationError) as failure:
        guard.validate("http://synthetic.local", structure, bindings, revision)
    assert failure.value.code == "temporarily_unavailable"
