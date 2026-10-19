from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

import mcpserver.tools as tools_module
from mcpserver.loxone.energy_manager import decode_loads, normalize
from mcpserver.loxone.models import Control, Freshness, LoxoneIdentity, LoxoneStructure, StateRecord
from mcpserver.loxone.runtime import RuntimeSnapshot, RuntimeUnavailable
from mcpserver.loxone.state_semantics import StateSemanticsResolver
from mcpserver.loxone.structure import normalize_structure
from mcpserver.tools import ControlReadTarget, register_read_tools


def manager(kind="EnergyManager", details=None):
    return Control(
        "manager",
        "Native manager",
        kind,
        None,
        None,
        "action",
        (("loads", "loads-state"),),
        energy_manager=normalize(kind, details or {}),
    )


def source(control, admin=True):
    return LoxoneStructure(
        LoxoneIdentity("reader", "serial"), "generation", (), (), (control,), caller_is_admin=admin
    )


def test_structure_normalization_keeps_independent_generation_metadata():
    result = normalize_structure(
        {
            "msInfo": {"serialNr": "serial"},
            "currentUser": {"isAdmin": True},
            "controls": {
                "manager": {
                    "name": "Manager",
                    "type": "EnergyManager",
                    "states": {},
                    "details": {"loads": [{"id": 0, "name": "Load", "minOnTime": 0}]},
                }
            },
        },
        username="reader",
    )
    metadata = result.controls[0].energy_manager
    assert metadata.generation == 1 and metadata.status == "valid"
    assert metadata.declared_loads[0].minimum_on_time_seconds == 0
    assert metadata.declared_loads[0].trigger_status == "unavailable_zero_min_on_time"
    assert result.controls[0].efm is None
    assert normalize("EFM", {"loads": []}) is None
    assert normalize("EnergyManager3", {"loads": []}) is None


@pytest.mark.parametrize(
    "details",
    [
        {"loads": "[]"},
        {"loads": [{"id": True}]},
        {"loads": [{"id": -1}]},
        {"loads": [{"id": 0}, {"id": 0}]},
        {"loads": [{"id": 0, "minOnTime": True}]},
        {"loads": [{"id": 0, "minOnTime": -1}]},
        {"loads": [{"id": 0, "name": "\ud800"}]},
        {"loads": [{"id": i} for i in range(101)]},
        {"loads": [{"id": i, "name": "x" * 200} for i in range(100)]},
    ],
)
def test_invalid_metadata_never_yields_partial_load_associations(details):
    metadata = normalize("EnergyManager", details)
    assert metadata.status == "invalid" and metadata.declared_loads == ()


def test_editing_locks_and_input_validity_are_not_load_locks_or_meter_evidence():
    metadata = normalize(
        "EnergyManager2",
        {
            "MinSocLocked": True,
            "MaxSpwrLocked": False,
            "HasSsoc": True,
            "HasSpwr": 1,
            "loads": [{"id": 0, "name": "Must not be retained"}],
        },
    )
    assert metadata.minimum_soc_parameter_edit_locked is True
    assert metadata.maximum_storage_power_parameter_edit_locked is False
    assert metadata.storage_soc_input_connected_and_valid is True
    assert metadata.storage_power_input_connected_and_valid is None
    assert metadata.status == "invalid" and metadata.declared_loads == ()
    assert normalize("EnergyManager2", {}).status == "missing"


@pytest.mark.parametrize("generation", [1, 2])
@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        '[{"id":0,"id":1}]',
        '[{"id":true}]',
        '[{"id":0},{"id":0}]',
        '[{"id":0,"other":{}}]',
        '[{"id":0,"other":NaN}]',
        '[{"id":0,"other":1e999}]',
        "[]" + " " * 16384,
        '[{"id":0,"name":"' + "\ud800" + '"}]',
        json.dumps([{"id": i} for i in range(101)]),
    ],
)
def test_malformed_load_text_events_are_rejected(generation, payload):
    with pytest.raises((ValueError, UnicodeError)):
        decode_loads(generation, payload)


def test_gen1_uses_output_flags_without_name_join_or_timezone_inference():
    payload = '[{"id":0,"isActive":false,"activeUntil":0,"isPreparing":true}]'
    c = manager(details={"loads": [{"id": 0, "name": "Current renamed load", "minOnTime": 0}]})
    descriptor, decoded = StateSemanticsResolver().resolve(source(c), c, "loads", payload, {})
    assert descriptor.interpretation_status == "partial"
    assert decoded["loads"][0]["isActive"] is False
    assert decoded["loads"][0]["isPreparing"] is True
    assert decoded["loads"][0]["isPermanentOn"] is None
    assert "name" not in decoded["loads"][0]
    assert decoded["structure_load_association"] == "unverified"
    assert decoded["native_activation_is_physical_cycle"] is False
    assert decoded["time_axis"] == "seconds_since_2009_timezone_unverified"
    assert decoded["priority_direction"] is None


def test_gen2_preserves_payload_identity_unknown_power_units_and_optional_fields():
    payload = json.dumps(
        [
            {
                "id": 0,
                "prio": 1,
                "name": "Delivered load",
                "uuid": "opaque-reference",
                "icon": "opaque/icon",
                "pwr": -2,
                "ppwr": 3,
                "hasActual": True,
                "active": True,
                "minimumActiveUntil": 12,
            }
        ]
    )
    decoded = decode_loads(2, payload)
    assert decoded["loads"][0]["pwr"] == -2
    assert decoded["load_power_unit"] is None
    assert decoded["has_actual_proves_power_meter"] is False
    assert decoded["time_axis"] == "utc_seconds_since_2009"
    assert decoded["loads"][0]["activeDueToDailyRuntime"] is None
    old = decode_loads(2, '[{"id":0,"pwr":1}]')
    assert old["loads"][0]["hasActual"] is None and old["loads"][0]["ppwr"] is None
    assert decoded["loads"][0]["power_evidence"] == "status_feedback_type_unverified"
    assert old["loads"][0]["power_evidence"] == "unknown"
    assumed = decode_loads(2, '[{"id":0,"pwr":1,"hasActual":false}]')
    assert assumed["loads"][0]["power_evidence"] == "manager_assumption"


@pytest.mark.parametrize(
    "name,unit,quantity",
    [
        ("Gpwr", "kW", "power"),
        ("Spwr", "kW", "power"),
        ("Ppwr", "kW", "power"),
        ("MaxSpwr", "kW", "power"),
        ("Ssoc", "%", "percentage"),
        ("MinSoc", "%", "percentage"),
    ],
)
def test_only_documented_gen2_global_units_are_bound(name, unit, quantity):
    c = manager("EnergyManager2")
    descriptor, decoded = StateSemanticsResolver().resolve(source(c), c, name, -2, {})
    assert descriptor.unit == unit and descriptor.measurement_quantity == quantity
    assert descriptor.sign_convention is None and decoded is None
    assert descriptor.interpretation_status == "partial"
    assert descriptor.sources[0].document_version == "17.1"
    old = manager()
    assert StateSemanticsResolver().resolve(source(old), old, name, 1, {})[0].unit is None


@pytest.mark.parametrize("admin", [False, None, 1, "true"])
def test_strict_current_admin_disclosure_gate(admin):
    c = manager("EnergyManager2")
    descriptor, decoded = StateSemanticsResolver().resolve(
        source(c, admin), c, "loads", '[{"id":0,"name":"Private delivered name"}]', {}
    )
    assert descriptor.interpretation_status == "unknown" and decoded is None
    assert descriptor.sources == []


def test_rule_references_do_not_invalidate_unchanged_legacy_families():
    resolver = StateSemanticsResolver()
    assert resolver.source_reference(manager(), state_name="loads") == (
        "energy_manager_gen1.loads.17_1.v1+StateSemanticsResolver.energy_manager_gen1.rules.v1"
    )
    assert resolver.source_reference(manager("EnergyManager2"), state_name="Gpwr") == (
        "energy_manager_gen2.Gpwr.17_1.v1+StateSemanticsResolver.energy_manager_gen2.rules.v1"
    )
    irc = replace(
        manager("IRoomControllerV2"),
        state_uuids=(("tempActual", "actual-state"),),
        format="%.1f°C",
        format_total_length=6,
    )
    assert resolver.source_reference(irc, state_name="tempActual") == (
        "IRoomControllerV2.tempActual.v1+StateSemanticsResolver.rules.v1"
    )
    hidden = replace(manager(), is_hidden=True)
    assert resolver.resolve(source(hidden), hidden, "loads", '[{"id":0}]', {})[1] is None


def test_gen2_duplicate_opaque_load_references_are_not_unambiguous_identities():
    with pytest.raises(ValueError, match="invalid_load_reference"):
        decode_loads(2, '[{"id":0,"uuid":"same"},{"id":1,"uuid":"same"}]')


class Runtime:
    def __init__(self, c, admin=True):
        self.current = source(c, admin)
        self.cached = source(c, True)
        self.snapshots = []
        self.reads = []
        self.failure = None
        self.record = StateRecord(
            "loads-state", '[{"id":0,"isActive":true}]', Freshness.STALE, 1_700_000_000
        )

    @asynccontextmanager
    async def call_slot(self, access):
        yield

    async def snapshot(self, access, *, fresh_visibility=False):
        self.snapshots.append(fresh_visibility)
        if self.failure:
            raise self.failure
        return RuntimeSnapshot("family", self.current if fresh_visibility else self.cached, True)

    def state(self, snapshot, uuid):
        self.reads.append(uuid)
        return self.record


def tools(monkeypatch, runtime):
    monkeypatch.setattr(tools_module, "_access", lambda: SimpleNamespace(scopes=["loxone:read"]))
    server = FastMCP("energy-context")
    register_read_tools(server, runtime)
    return server._tool_manager


@pytest.mark.asyncio
async def test_opt_in_context_freshly_authorizes_and_keeps_stale_state_separate(monkeypatch):
    runtime = Runtime(
        manager(details={"loads": [{"id": 0, "name": "Fresh metadata name", "minOnTime": 0}]})
    )
    collection = tools(monkeypatch, runtime)
    describe = collection.get_tool("loxone_describe_control")
    legacy = await describe.fn("manager")
    assert "Fresh metadata name" not in legacy.model_dump_json()
    assert "energy_context" not in legacy.model_dump_json()
    assert runtime.snapshots == [False] and runtime.reads == []
    result = await describe.fn("manager", view="energy_context")
    assert result.ok and result.stale
    assert result.data.metadata.declared_loads[0].name == "Fresh metadata name"
    assert result.data.metadata_state_association == "unverified"
    assert result.data.state_context[0].quality.freshness == "stale"
    assert result.data.state_context[0].semantic_value["loads"][0]["isActive"] is True
    assert runtime.snapshots == [False, True] and runtime.reads == ["loads-state"]
    assert result.data.capabilities.missing_states == ["currentPower", "currentBat"]
    assert len(result.model_dump_json().encode()) < 65536


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,error",
    [
        ("nonadmin", "permission_denied"),
        ("unknown_admin", "permission_denied"),
        ("hidden", "not_found"),
        ("revoked_visibility", "not_found"),
        ("unsupported_family", "unsupported_source"),
        ("refresh_failed", "temporarily_unavailable"),
        ("include_hidden", "invalid_input"),
    ],
)
async def test_context_failures_never_decode_or_disclose_loads(monkeypatch, case, error):
    runtime = Runtime(manager(details={"loads": [{"id": 0, "name": "Sensitive metadata"}]}))
    if case == "nonadmin":
        runtime.current = replace(runtime.current, caller_is_admin=False)
    elif case == "unknown_admin":
        runtime.current = replace(runtime.current, caller_is_admin=None)
    elif case == "hidden":
        runtime.current = replace(
            runtime.current, controls=(replace(runtime.current.controls[0], is_hidden=True),)
        )
    elif case == "revoked_visibility":
        runtime.current = replace(runtime.current, controls=())
    elif case == "unsupported_family":
        runtime.current = source(manager("EnergyManager3"))
    elif case == "refresh_failed":
        runtime.failure = RuntimeUnavailable("unavailable")
    result = (
        await tools(monkeypatch, runtime)
        .get_tool("loxone_describe_control")
        .fn("manager", view="energy_context", include_hidden=case == "include_hidden")
    )
    assert not result.ok and result.data.error == error
    assert "Sensitive metadata" not in result.model_dump_json() and runtime.reads == []
    assert runtime.snapshots == ([] if case == "include_hidden" else [True])


@pytest.mark.asyncio
@pytest.mark.parametrize("admin", [True, False])
async def test_existing_semantic_surfaces_share_decoder_with_one_fresh_context(monkeypatch, admin):
    runtime = Runtime(manager(), admin)
    collection = tools(monkeypatch, runtime)
    one = await collection.get_tool("loxone_get_state_semantics").fn("manager")
    batch = await collection.get_tool("loxone_read_controls").fn(
        [ControlReadTarget(control_uuid="manager")], include_semantics=True
    )
    assert one.ok and batch.ok and runtime.snapshots == [True, True]
    assert one.data.items[0].semantic_value == batch.data.items[0].semantics[0].semantic_value
    assert (one.data.items[0].semantic_value is not None) is admin
    assert one.data.items[0].value == runtime.record.value  # Legacy raw state remains intact.
    assert runtime.reads == ["loads-state", "loads-state"]


@pytest.mark.asyncio
async def test_context_rejects_oversized_raw_state_without_partial_metadata(monkeypatch):
    runtime = Runtime(manager())
    runtime.record = StateRecord("loads-state", "x" * 65_536, Freshness.CURRENT, None)
    result = (
        await tools(monkeypatch, runtime)
        .get_tool("loxone_describe_control")
        .fn("manager", view="energy_context")
    )
    assert not result.ok and result.data.error == "response_too_large"
    assert "state_context" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_semantic_surface_bounds_decoded_and_raw_manager_output(monkeypatch):
    runtime = Runtime(manager("EnergyManager2"))
    payload = json.dumps([{"id": i, "name": "\\" * 65} for i in range(100)], separators=(",", ":"))
    assert len(payload.encode()) < 16 * 1024
    runtime.record = StateRecord("loads-state", payload, Freshness.CURRENT, None)
    result = await tools(monkeypatch, runtime).get_tool("loxone_get_state_semantics").fn("manager")
    assert not result.ok and result.data.error == "response_too_large"
    assert "semantic_value" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_gen2_context_preserves_parameter_lock_and_assumed_power_distinction(monkeypatch):
    runtime = Runtime(manager("EnergyManager2", {"MinSocLocked": True, "HasSpwr": False}))
    runtime.record = StateRecord(
        "loads-state", '[{"id":1,"hasActual":false,"pwr":2,"ppwr":2}]', Freshness.CURRENT, None
    )
    result = (
        await tools(monkeypatch, runtime)
        .get_tool("loxone_describe_control")
        .fn("manager", view="energy_context")
    )
    assert result.ok
    assert result.data.metadata.minimum_soc_parameter_edit_locked is True
    assert result.data.metadata.storage_power_input_connected_and_valid is False
    decoded = result.data.state_context[0].semantic_value
    assert decoded["loads"][0]["power_evidence"] == "manager_assumption"
    assert decoded["load_power_unit"] is None
    assert decoded["native_activation_is_physical_cycle"] is False
    assert runtime.snapshots == [True] and runtime.reads == ["loads-state"]


@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_gen2_edit_lock_requires_documented_boolean_not_coercion(value):
    metadata = normalize("EnergyManager2", {"MinSocLocked": value, "HasSsoc": True})
    assert metadata.status == "invalid"
    assert metadata.minimum_soc_parameter_edit_locked is None
    assert metadata.storage_soc_input_connected_and_valid is True
