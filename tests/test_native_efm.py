from __future__ import annotations

import asyncio
import json
import struct
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from mcp.server.fastmcp import FastMCP

import mcpserver.loxone.client as client_module
import mcpserver.tools as tools_module
from mcpserver.auth.loxone_health import LoxoneTokenHealthStore
from mcpserver.auth.provider import HISTORY_SCOPE, READ_SCOPE, StoredAccessToken
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.loxone.auth_diagnostics import MiniserverAuthCoordinator
from mcpserver.loxone.client import (
    LoxoneCommandRejected,
    LoxoneTokenAuthenticationRejected,
    LoxoneWebSocketSession,
    _websocket_command,
)
from mcpserver.loxone.efm import normalize as normalize_efm
from mcpserver.loxone.endpoint import MiniserverEndpoint
from mcpserver.loxone.events import LoxonePayloadTooLarge
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.native_efm import VIEWS, NativeEfmError, NativeEfmResult, decode_native_efm
from mcpserver.loxone.runtime import ControlOperationError, LoxoneRuntime
from mcpserver.loxone.state_semantics import StateSemanticsResolver
from mcpserver.loxone.structure import normalize_structure
from mcpserver.tools import ControlReadTarget, register_read_tools

TARGET = "00000000-0000-0000-0000000000000001"
ACTION = "00000000-0000-0000-0000000000000002"
SERIAL = "001122aabbcc"
RECEIVED = "2026-10-11T10:00:00+00:00"
ACTUAL = '{"Gpwr":1,"Ppwr":2,"Spwr":3,"Cpwr":4}'


def semantic_control(details, *, generic_format=None):
    return Control(
        TARGET,
        "Monitor",
        "EFM",
        None,
        None,
        ACTION,
        (),
        efm=normalize_efm(details),
        format=generic_format,
    )


@pytest.mark.parametrize(
    "source_format,unit",
    [
        ("%.3fkW", "kW"),
        ("%f W", "W"),
        ("%10.2f kW", "kW"),
    ],
)
def test_actual_power_semantics_bind_only_documented_format(source_format, unit):
    control = semantic_control({"actualFormat": source_format, "nodes": []})
    raw = decode_native_efm(
        '{"Gpwr":-2,"Ppwr":0,"Spwr":3,"Cpwr":4,"Rest":5}', "actual", retrieved_at=RECEIVED
    )
    result = StateSemanticsResolver().resolve_native_efm(raw, control, control)
    assert result.schema_version == "native_efm_result.v2"
    assert result.source_metadata_status == "stable" and not result.semantic_complete
    assert result.semantic_rule_version == "native_efm_actual_semantics_17_2_8_28.v2"
    assert [field.unit for field in result.fields] == [unit, unit, unit, unit, None]
    assert [field.unit_origin for field in result.fields] == [
        "configured_display_format",
        "configured_display_format",
        "configured_display_format",
        "configured_display_format",
        None,
    ]
    assert all(field.unit_origin is None for field in raw.fields)
    for name in ("Gpwr", "Ppwr", "Spwr", "Cpwr"):
        assert any(
            f"fields.{name}.unit_origin" in source.fields for source in result.semantic_sources
        )
    assert [field.measurement_quantity for field in result.fields] == ["power"] * 4 + [None]
    assert [field.measurement_role for field in result.fields] == [
        "grid_power",
        "production_power",
        "storage_power",
        "load_power",
        None,
    ]
    assert [field.value for field in result.fields] == [-2, 0, 3, 4, 5]
    assert all(
        field.scale is field.sign_convention is field.currency is None for field in result.fields
    )
    assert all(field.unit is None for field in raw.fields)  # Pure, non-mutating enrichment.
    assert result.report_applicability == "current_snapshot"
    assert not result.historical_date_selection_supported
    assert "self_consumption_unavailable" in result.report_limitations
    assert any(
        source.reference == "controls[target].details.actualFormat"
        for source in result.semantic_sources
    )
    assert all(source.rule_id == result.semantic_rule_version for source in result.semantic_sources)
    assert {source.document_version for source in result.semantic_sources} == {"17.1"}
    assert {source.firmware_version for source in result.semantic_sources} == {"17.2.8.28"}


def test_retained_semantic_rule_v1_result_remains_readable():
    raw = decode_native_efm(ACTUAL, "actual", retrieved_at=RECEIVED)
    retained = raw.model_dump() | {
        "schema_version": "native_efm_result.v2",
        "semantic_rule_version": "native_efm_actual_semantics_17_2_8_28.v1",
    }
    result = NativeEfmResult.model_validate(retained)
    assert result.semantic_rule_version == retained["semantic_rule_version"]
    assert result.fields == raw.fields


def test_display_units_do_not_compute_a_balance_or_clamp_signed_residuals():
    control = semantic_control({"actualFormat": "%.3f kW", "nodes": []})
    raw = decode_native_efm(
        '{"Gpwr":10,"Ppwr":1,"Spwr":-3,"Cpwr":2,"Rest":-0.5}',
        "actual",
        retrieved_at=RECEIVED,
    )
    result = StateSemanticsResolver().resolve_native_efm(raw, control, control)
    assert [field.value for field in result.fields] == [10, 1, -3, 2, -0.5]
    assert result.fields[3].unit == "kW"
    assert result.fields[3].unit_origin == "configured_display_format"
    assert result.fields[4].status == "present"
    assert result.fields[4].value == -0.5
    assert result.fields[4].unit is result.fields[4].unit_origin is None
    assert all(field.scale is field.sign_convention is None for field in result.fields)


@pytest.mark.parametrize(
    "source_format",
    [
        None,
        True,
        "",
        "W",
        "%.3f MW",
        "%.3f kWh",
        "power %.3fkW",
        "%f %f kW",
        "%.3f\nkW",
        "\ud800",
        "%" + "1" * 128 + "fW",
    ],
)
def test_missing_or_unsupported_formats_never_supply_units(source_format):
    control = semantic_control({"actualFormat": source_format}, generic_format="%.2f kW")
    result = StateSemanticsResolver().resolve_native_efm(
        decode_native_efm(ACTUAL, "actual", retrieved_at=RECEIVED), control, control
    )
    rejected = (
        not isinstance(source_format, str)
        or not source_format
        or len(source_format) > 128
        or source_format == "\ud800"
    )
    assert result.source_metadata_status == ("invalid" if rejected else "unsupported")
    assert all(field.unit is None for field in result.fields)
    assert all(field.unit_origin is None for field in result.fields)
    assert "power_units_unverified" in result.report_limitations
    assert not any(source.kind == "structure_file" for source in result.semantic_sources)


def test_absent_root_format_does_not_inherit_participant_or_total_format():
    control = semantic_control(
        {
            "totalFormat": "%.3f kWh",
            "nodes": [{"actualFormat": "%.3f kW"}],
        },
        generic_format="%.3f kW",
    )
    result = StateSemanticsResolver().resolve_native_efm(
        decode_native_efm(ACTUAL, "actual", retrieved_at=RECEIVED), control, control
    )
    assert result.source_metadata_status == "missing"
    assert all(field.unit is None for field in result.fields)
    assert all(field.unit_origin is None for field in result.fields)


def test_changed_format_discards_unit_enrichment_and_preserves_values():
    before = semantic_control({"actualFormat": "%.3f kW", "nodes": []})
    after = semantic_control({"actualFormat": "%.3f W", "nodes": []})
    result = StateSemanticsResolver().resolve_native_efm(
        decode_native_efm(ACTUAL, "actual", retrieved_at=RECEIVED), before, after
    )
    assert result.source_metadata_status == "changed"
    assert "source_metadata_changed" in result.report_limitations
    assert all(field.unit is None for field in result.fields)
    assert all(field.unit_origin is None for field in result.fields)
    assert [field.value for field in result.fields] == [1, 2, 3, 4, None]
    assert result.fields[0].measurement_quantity == "power"


@pytest.mark.parametrize("view", sorted(VIEWS - {"actual"}))
@pytest.mark.parametrize(
    "name", ["Export", "Import", "Production", "Charge", "Discharge", "Consumption", "Income"]
)
def test_native_period_report_does_not_gain_units_or_historical_dates(view, name):
    control = semantic_control(
        {
            "actualFormat": "%.3f kW",
            "totalFormat": "%.3f kWh",
            "currency": "EUR",
            "timezone": "Europe/Berlin",
            "nodes": [],
        }
    )
    result = StateSemanticsResolver().resolve_native_efm(
        decode_native_efm(json.dumps({name: -1.25}), view, retrieved_at=RECEIVED),
        control,
        control,
    )
    assert result.source_metadata_status == "not_applicable" and not result.semantic_sources
    assert all(field.unit_origin is None for field in result.fields)
    assert all(
        field.unit is field.measurement_quantity is field.measurement_role is None
        for field in result.fields
    )
    delivered = next(field for field in result.fields if field.name == name)
    assert delivered.status == "present" and delivered.value == -1.25
    assert all(
        field.scale is field.sign_convention is field.currency is None for field in result.fields
    )
    assert all(field.status == "missing" for field in result.fields if field.name != name)
    assert result.period_start is result.period_end is result.timezone is None
    assert result.period_completion == ("unknown" if view == "lifetime" else "running")
    assert result.observation_freshness == "unknown" and not result.semantic_complete
    assert not result.historical_date_selection_supported
    assert "period_units_unverified" in result.report_limitations


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_runtime_semantics_reuse_exact_pre_and_post_structure(changed):
    runtime, structure, session, _ = fixture_runtime()
    before = replace(
        structure, controls=(semantic_control({"actualFormat": "%.3fkW", "nodes": []}),)
    )
    after = (
        replace(before, controls=(semantic_control({"actualFormat": "%.3fW", "nodes": []}),))
        if changed
        else before
    )
    session.load_structure.side_effect = [before, after]
    _, _, result = await runtime.read_native_efm(access(), TARGET, "actual")
    assert result.source_metadata_status == ("changed" if changed else "stable")
    assert result.fields[0].unit == (None if changed else "kW")
    assert session.load_structure.await_count == 2
    assert session.native_efm_result.await_count == runtime.client.probe.await_count == 1
    assert not runtime._records


@pytest.mark.parametrize("view", sorted(VIEWS))
def test_views_preserve_native_names_and_unknown_meaning(view):
    result = decode_native_efm(ACTUAL, view, retrieved_at=RECEIVED)
    assert result.retrieved_at == RECEIVED
    assert result.observation_freshness == "unknown" and not result.semantic_complete
    assert result.period_start is result.period_end is result.timezone is None
    assert result.calculation_provenance == "loxone"
    assert all(f.unit is f.scale is f.sign_convention is f.currency is None for f in result.fields)
    if view == "actual":
        assert [f.name for f in result.fields] == ["Gpwr", "Ppwr", "Spwr", "Cpwr", "Rest"]
        assert result.fields[-1].status == "missing" and result.fields[-1].value is None
    else:
        assert result.fields[0].name == "Export" and result.omitted_source_fields == 4
    assert not result.field_delivery_complete


def test_complete_period_and_unknown_names_are_not_published():
    names = ["Export", "Import", "Production", "Charge", "Discharge", "Consumption", "Income"]
    result = decode_native_efm(
        json.dumps({**dict.fromkeys(names, 0), "Income": -1, "private_field": 42}),
        "day",
        retrieved_at=RECEIVED,
    )
    assert result.field_delivery_complete and not result.semantic_complete
    assert result.fields[-1].value == -1 and result.fields[0].value == 0
    assert result.omitted_source_fields == 1 and "private_field" not in result.model_dump_json()


@pytest.mark.parametrize("value", [True, "1", None])
def test_known_bad_scalars_remain_invalid_not_coerced(value):
    result = decode_native_efm(json.dumps({"Gpwr": value}), "actual", retrieved_at=RECEIVED)
    assert result.fields[0].status == "invalid" and result.fields[0].value is None


@pytest.mark.parametrize(
    "raw",
    [
        {},
        "[]",
        "null",
        '{"Gpwr":1,"Gpwr":2}',
        '{"Gpwr":[]}',
        '{"x":{}}',
        '{"Gpwr":NaN}',
        '{"Gpwr":Infinity}',
        '{"Gpwr":1e999}',
        '{"Gpwr":' + "9" * 5000 + "}",
        " " * 16385,
        json.dumps({str(i): i for i in range(17)}),
        "\ud800",
    ],
    ids=lambda raw: "malformed",
)
def test_untrusted_shapes_fail_with_fixed_diagnostics(raw):
    with pytest.raises(NativeEfmError, match="^native_efm_"):
        decode_native_efm(raw, "actual", retrieved_at=RECEIVED)


@pytest.mark.parametrize(
    "admin,expected", [(True, True), (False, False), (1, None), ("true", None), (None, None)]
)
def test_structure_administration_is_strict_and_not_inferred(admin, expected):
    structure = normalize_structure(
        {
            "msInfo": {"serialNr": SERIAL, "currentUser": {"isAdmin": admin, "userRights": 131072}},
            "controls": {},
        },
        username="reader",
    )
    assert structure.caller_is_admin is expected


def access(*, history=False):
    return StoredAccessToken(
        token="opaque",
        client_id="client",
        scopes=[READ_SCOPE, HISTORY_SCOPE] if history else [READ_SCOPE],
        expires_at=2_000_000_000,
        resource="https://loxberry.local/plugins/mcpserver/mcp",
        subject="identity",
        claims={},
        family_id="family",
        identity_id="identity",
        miniserver_id="miniserver",
    )


def fixture_runtime(*, history=False):
    control = Control(TARGET, "Monitor", "EFM", None, None, ACTION, ())
    structure = LoxoneStructure(
        LoxoneIdentity("reader", SERIAL), "current", (), (), (control,), caller_is_admin=True
    )
    token = SimpleNamespace(destroy=Mock())
    store = SimpleNamespace(get=Mock(return_value=token))
    runtime = LoxoneRuntime(
        MiniserverEndpoint.parse_gen1("http://192.168.1.10"), store, history_enabled=history
    )
    session = SimpleNamespace(
        load_structure=AsyncMock(side_effect=[structure, structure]),
        native_efm_result=AsyncMock(return_value=ACTUAL),
        close=AsyncMock(),
    )
    runtime._open_session = AsyncMock(return_value=session)
    runtime.client.probe = AsyncMock(
        return_value=SimpleNamespace(firmware="17.2.8.28", serial=SERIAL)
    )
    return runtime, structure, session, token


@pytest.mark.asyncio
@pytest.mark.parametrize("view", sorted(VIEWS))
async def test_authorized_native_own_session_pre_post_and_cleanup(view):
    runtime, structure, session, token = fixture_runtime(history=True)
    a = access(history=True)
    control, returned, result = await runtime.read_native_efm(a, TARGET, view)
    assert control.uuid == TARGET and returned is structure and result.view == view
    assert session.load_structure.await_count == 2
    session.native_efm_result.assert_awaited_once_with(ACTION, view)
    session.close.assert_awaited_once()
    token.destroy.assert_called_once()
    runtime.token_store.get.assert_called_once_with(a.family_id, a.miniserver_id, a.identity_id)
    assert not runtime._records and runtime._parallel._value == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("post", [False, True])
@pytest.mark.parametrize("gate", ["admin", "hidden", "absent", "serial", "type", "action"])
async def test_fresh_gates_discard_native_values(post, gate):
    runtime, structure, session, token = fixture_runtime()
    if gate == "admin":
        changed = replace(structure, caller_is_admin=None)
    elif gate == "hidden":
        changed = replace(structure, controls=(replace(structure.controls[0], is_hidden=True),))
    elif gate == "absent":
        changed = replace(structure, controls=())
    elif gate == "serial":
        changed = replace(structure, identity=LoxoneIdentity("reader", "112233aabbcc"))
    elif gate == "action":
        changed = replace(structure, controls=(replace(structure.controls[0], action_uuid=None),))
    else:
        changed = replace(
            structure, controls=(replace(structure.controls[0], control_type="Switch"),)
        )
    session.load_structure.side_effect = [structure, changed] if post else [changed]
    with pytest.raises(ControlOperationError):
        await runtime.read_native_efm(access(), TARGET, "actual")
    assert session.native_efm_result.await_count == int(post)
    session.close.assert_awaited_once()
    token.destroy.assert_called_once()


@pytest.mark.asyncio
async def test_changed_action_reference_discards_native_result():
    runtime, structure, session, token = fixture_runtime()
    changed = replace(structure, controls=(replace(structure.controls[0], action_uuid=TARGET),))
    session.load_structure.side_effect = [structure, changed]
    with pytest.raises(ControlOperationError, match="action identity changed"):
        await runtime.read_native_efm(access(), TARGET, "actual")
    session.native_efm_result.assert_awaited_once_with(ACTION, "actual")
    session.close.assert_awaited_once()
    token.destroy.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("history_scope,activated", [(False, False), (True, False), (False, True)])
async def test_period_requires_scope_and_activation_before_login(history_scope, activated):
    runtime, _, _, _ = fixture_runtime(history=activated)
    with pytest.raises(ControlOperationError, match="history"):
        await runtime.read_native_efm(access(history=history_scope), TARGET, "day")
    runtime._open_session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "firmware,serial",
    [("17.2.8.29", SERIAL), ("17.2.8.28", "112233aabbcc"), ("17.2.8.28", "invalid")],
)
async def test_probe_gate_never_reads_unsupported_source(firmware, serial):
    runtime, _, session, _ = fixture_runtime()
    runtime.client.probe.return_value = SimpleNamespace(firmware=firmware, serial=serial)
    with pytest.raises(ControlOperationError) as failure:
        await runtime.read_native_efm(access(), TARGET, "actual")
    assert failure.value.code == "unsupported_source"
    session.native_efm_result.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["read", "post"])
async def test_revocation_discards_result(phase):
    runtime, structure, session, _ = fixture_runtime()
    allowed = True

    async def validate(_access):
        return allowed

    async def revoke(*_args):
        nonlocal allowed
        allowed = False
        return ACTUAL if phase == "read" else structure

    runtime._validate_access = validate
    if phase == "read":
        session.native_efm_result.side_effect = revoke
    else:
        calls = 0

        async def structures():
            nonlocal calls
            calls += 1
            return structure if calls == 1 else await revoke()

        session.load_structure.side_effect = structures
    with pytest.raises(ControlOperationError) as failure:
        await runtime.read_native_efm(access(), TARGET, "actual")
    assert failure.value.code == "permission_denied"
    session.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["read", "post"])
async def test_cancellation_releases_session_and_admission(stage):
    runtime, structure, session, token = fixture_runtime()
    started = asyncio.Event()

    async def waiting(*_args):
        started.set()
        await asyncio.Event().wait()

    if stage == "read":
        session.native_efm_result.side_effect = waiting
    else:
        calls = 0

        async def structures():
            nonlocal calls
            calls += 1
            if calls == 1:
                return structure
            await waiting()

        session.load_structure.side_effect = structures
    task = asyncio.create_task(runtime.read_native_efm(access(), TARGET, "actual"))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    session.close.assert_awaited_once()
    token.destroy.assert_called_once()
    assert runtime._parallel._value == 4


@pytest.mark.asyncio
async def test_bounds_have_structured_size_error():
    runtime, _, session, _ = fixture_runtime()
    session.native_efm_result.side_effect = LoxonePayloadTooLarge("private response")
    with pytest.raises(ControlOperationError) as failure:
        await runtime.read_native_efm(access(), TARGET, "actual")
    assert failure.value.code == "response_too_large" and "private" not in str(failure.value)


@pytest.mark.asyncio
async def test_authentication_health_only_records_definite_token_rejection():
    runtime, _, _, _ = fixture_runtime()
    health = SimpleNamespace(
        get=Mock(return_value=SimpleNamespace(confirmation_required=False)),
        record_rejected_authentication=Mock(),
        record_successful_authentication=Mock(),
    )
    runtime.token_health = health
    runtime._open_session.side_effect = LoxoneTokenAuthenticationRejected(
        "private", response_code="401"
    )
    with pytest.raises(ControlOperationError):
        await runtime.read_native_efm(access(), TARGET, "actual")
    health.record_rejected_authentication.assert_called_once_with("family")
    health.record_rejected_authentication.reset_mock()
    runtime._open_session.side_effect = LoxoneCommandRejected("private", response_code="403")
    with pytest.raises(ControlOperationError):
        await runtime.read_native_efm(access(), TARGET, "actual")
    health.record_rejected_authentication.assert_not_called()


@pytest.mark.asyncio
async def test_native_tool_serialization_and_invalid_selectors(monkeypatch):
    runtime, structure, _, _ = fixture_runtime()
    a = access()
    monkeypatch.setattr(tools_module, "_access", lambda: a)
    server = FastMCP("native")
    register_read_tools(server, runtime)
    tool = server._tool_manager.get_tool("loxone_read_controls")
    result = await tool.fn([ControlReadTarget(control_uuid=TARGET)], native_result_view="actual")
    assert result.ok and result.data.requested_states == result.data.returned_states == 0
    item = result.model_dump(mode="json")["data"]["items"][0]
    assert item["values"] == [] and "semantics" not in item and "native_result" in item
    runtime._open_session.reset_mock()
    invalid = await tool.fn([ControlReadTarget(control_uuid=TARGET)], True, "actual")
    assert invalid.data.error == "invalid_input"
    runtime._open_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmation_after_coordinator_wait_prevents_login(tmp_path):
    runtime, _, _, token = fixture_runtime()
    health = SimpleNamespace(get=Mock(return_value=SimpleNamespace(confirmation_required=False)))
    runtime.token_health = health
    coordinator = MiniserverAuthCoordinator(tmp_path / "auth.json")

    async def queued(_operation, **kwargs):
        health.get.return_value = SimpleNamespace(confirmation_required=True)
        await kwargs["before_attempt"]()
        raise AssertionError("must not authenticate")

    coordinator.attempt = queued
    runtime.auth_coordinator = coordinator
    runtime.client.open_session = AsyncMock()
    with pytest.raises(ControlOperationError):
        await LoxoneRuntime._open_session(
            runtime,
            token,
            owner="tool_request",
            phase="native_efm",
            access=access(),
            require_token_confirmation=True,
        )
    runtime.client.open_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_waiting_admission_rechecks_confirmation_before_login():
    runtime, _, _, _ = fixture_runtime()
    health = SimpleNamespace(get=Mock(return_value=SimpleNamespace(confirmation_required=False)))
    runtime.token_health = health
    runtime._parallel = asyncio.Semaphore(0)
    task = asyncio.create_task(runtime.read_native_efm(access(), TARGET, "actual"))
    await asyncio.sleep(0)
    health.get.return_value = SimpleNamespace(confirmation_required=True)
    runtime._parallel.release()
    with pytest.raises(ControlOperationError):
        await task
    runtime._open_session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("secure", [False, True])
async def test_native_transport_fixed_command_encryption_and_bounds(monkeypatch, secure):
    session = object.__new__(LoxoneWebSocketSession)
    session._websocket = object()
    session._encryptor = object()
    session._secure_transport = secure
    session._timeout = 25
    session._max_payload = 8 * 1024 * 1024
    command = AsyncMock(return_value=ACTUAL)
    monkeypatch.setattr(client_module, "_websocket_command", command)
    await session.native_efm_result(TARGET, "day")
    assert command.call_args.args[-1] == f"jdev/sps/io/{TARGET}/get/day"
    assert command.call_args.kwargs == {
        "encrypted": not secure,
        "timeout_seconds": 10,
        "max_payload_bytes": 32768,
    }
    with pytest.raises(ValueError):
        await session.native_efm_result(TARGET, "get/day/other")
    assert command.await_count == 1


@pytest.mark.asyncio
async def test_outer_large_integer_is_fixed_protocol_error():
    payload = '{"LL":{"Code":"200","value":' + "9" * 5000 + "}}"
    socket = SimpleNamespace(
        send=AsyncMock(),
        recv=AsyncMock(
            side_effect=[
                struct.pack("<BBBBI", 3, 0, 0, 0, len(payload)),
                payload,
            ]
        ),
    )
    with pytest.raises(client_module.LoxoneProtocolError, match="response is not JSON"):
        await _websocket_command(
            socket, Mock(), "fixed", encrypted=False, timeout_seconds=1, max_payload_bytes=32768
        )


@pytest.mark.asyncio
async def test_three_native_authentication_rejections_block_further_logins(tmp_path):
    runtime, _, _, _ = fixture_runtime()
    store = AtomicJsonAuthStore((tmp_path / "sessions.json").resolve())
    store.mutate(lambda document: document["families"].update({"family": {"revoked": False}}))
    runtime.token_health = LoxoneTokenHealthStore(store)
    runtime._open_session.side_effect = LoxoneTokenAuthenticationRejected(
        "private", response_code="401"
    )
    for _ in range(3):
        with pytest.raises(ControlOperationError):
            await runtime.read_native_efm(access(), TARGET, "actual")
    assert runtime.token_health.get("family").confirmation_required
    with pytest.raises(ControlOperationError):
        await runtime.read_native_efm(access(), TARGET, "actual")
    assert runtime._open_session.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup", ["own_timeout", "outer_timeout"])
async def test_stalled_close_aborts_socket(cleanup):
    started = asyncio.Event()

    async def stalled():
        started.set()
        await asyncio.Event().wait()

    socket = SimpleNamespace(close=stalled, transport=SimpleNamespace(abort=Mock()))
    if cleanup == "own_timeout":
        await client_module._close_websocket(socket, 0.01)
    else:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(client_module._close_websocket(socket, 10), 0.01)
    assert started.is_set()
    socket.transport.abort.assert_called_once()


@pytest.mark.asyncio
async def test_outer_recursion_is_fixed_protocol_error(monkeypatch):
    payload = '{"LL":{"Code":"200","value":' + "[" * 2000 + "0" + "]" * 2000 + "}}"
    socket = SimpleNamespace(
        send=AsyncMock(),
        recv=AsyncMock(
            side_effect=[
                struct.pack("<BBBBI", 3, 0, 0, 0, len(payload)),
                payload,
            ]
        ),
    )
    # CPython's JSON nesting limit is independent of the Python recursion limit
    # on some supported versions. Exercise the parser failure deterministically.
    monkeypatch.setattr(client_module.json, "loads", Mock(side_effect=RecursionError))
    with pytest.raises(client_module.LoxoneProtocolError, match="response is not JSON"):
        await _websocket_command(
            socket, Mock(), "fixed", encrypted=False, timeout_seconds=1, max_payload_bytes=32768
        )


@pytest.mark.asyncio
async def test_native_authentication_success_resets_persisted_rejections(tmp_path):
    runtime, _, _, _ = fixture_runtime()
    store = AtomicJsonAuthStore((tmp_path / "sessions.json").resolve())
    store.mutate(lambda document: document["families"].update({"family": {"revoked": False}}))
    runtime.token_health = LoxoneTokenHealthStore(store)
    runtime.token_health.record_rejected_authentication("family")
    assert runtime.token_health.get("family").rejected_authentications == 1
    await runtime.read_native_efm(access(), TARGET, "actual")
    assert runtime.token_health.get("family").rejected_authentications == 0
    assert not runtime.token_health.get("family").confirmation_required


@pytest.mark.asyncio
async def test_cancellation_during_authentication_aborts_and_releases():
    runtime, _, _, token = fixture_runtime()
    socket = SimpleNamespace(close=AsyncMock(), transport=SimpleNamespace(abort=Mock()))
    started = asyncio.Event()

    async def authenticating(*_args, **_kwargs):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            socket.transport.abort()

    runtime._open_session.side_effect = authenticating
    task = asyncio.create_task(runtime.read_native_efm(access(), TARGET, "actual"))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    socket.transport.abort.assert_called_once()
    token.destroy.assert_called_once()
    assert runtime._parallel._value == 4
