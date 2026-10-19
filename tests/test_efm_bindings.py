"""Synthetic binding fixtures; observed UUID wire shape only on 17.2.8.28.

Names, aliases, repetition, contradiction, reordering, gaps, malformed/absent
metadata, nested participants and bounds are independently authored, unobserved
synthetic scenarios. Config application version is unknown. No live acceptance.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP
from test_efm import node, target, uuid
from test_tools import READ_SCOPE, _loxberry_access

from mcpserver import tools as tools_module
from mcpserver.loxone.client import LoxoneConnectionError, ProbeResult
from mcpserver.loxone.efm import normalize
from mcpserver.loxone.efm_bindings import FIRMWARE, MAX_BINDING_BYTES, bind
from mcpserver.loxone.models import LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import RuntimeSnapshot
from mcpserver.tools import register_read_tools


def monitor(nodes, states=()):
    return replace(
        target(1), control_type="EFM", state_uuids=tuple(states), efm=normalize({"nodes": nodes})
    )


def test_synthetic_uuid_join_is_independent_of_order_numbering_and_control_identity() -> None:
    first = node(3, ctrlUuid=uuid(99), actualEfmState=uuid(7))
    second = node(4, actualEfmState=uuid(8))
    control = monitor([second, first], [("actual19", uuid(7)), ("actual0", uuid(8))])
    result = bind(control.efm, control, FIRMWARE)
    assert [r["states"] for r in result["participants"]] == [
        [{"name": "actual0", "uuid": uuid(8)}],
        [{"name": "actual19", "uuid": uuid(7)}],
    ]
    assert uuid(99) not in json.dumps(result)
    assert result["reference_complete"]
    assert not result["semantic_complete"] and not result["observation_complete"]
    control = replace(control, state_uuids=tuple(reversed(control.state_uuids)))
    assert bind(control.efm, control, FIRMWARE) == result


def test_synthetic_aliases_and_repeated_participant_bindings_preserve_all_facts() -> None:
    control = monitor(
        [node(3, actualEfmState=uuid(7)), node(4, actualEfmState=uuid(7))],
        [("actual0", uuid(7)), ("alias", uuid(7))],
    )
    rows = bind(control.efm, control, FIRMWARE)["participants"]
    assert all(
        r["states"] == [{"name": "actual0", "uuid": uuid(7)}, {"name": "alias", "uuid": uuid(7)}]
        for r in rows
    )


def test_synthetic_conflicting_normalized_map_never_selects_first_candidate() -> None:
    control = monitor([node(actualEfmState=uuid(7))], [("actual0", uuid(7)), ("actual0", uuid(8))])
    result = bind(control.efm, control, FIRMWARE)
    assert result["participants"][0]["status"] == "conflict"
    assert [s["uuid"] for s in result["participants"][0]["states"]] == [uuid(7), uuid(8)]
    assert not result["reference_complete"]
    assert result["source_property_uniqueness"] == "not_checked"


@pytest.mark.parametrize(
    "value,status,wire",
    [
        ("actual0", "unsupported_encoding", "string"),
        ("", "malformed", "string"),
        (True, "malformed", "boolean"),
        ({"secret": "private"}, "malformed", "object"),
        (None, "malformed", "null"),
        (7, "malformed", "number"),
        ([], "malformed", "array"),
    ],
)
def test_synthetic_unobserved_encodings_are_not_guessed(value, status, wire) -> None:
    control = monitor([node(actualEfmState=value)], [("actual0", uuid(7))])
    result = bind(control.efm, control, FIRMWARE)
    row = result["participants"][0]
    assert row["status"] == status and row["source_wire_type"] == wire
    assert not row["states"] and "private" not in json.dumps(result)


def test_synthetic_absent_nested_binding_differs_from_reference_missing() -> None:
    control = monitor([node(actualEfmState=uuid(7), nodes=[node(2)])])
    result = bind(control.efm, control, FIRMWARE)
    assert [r["status"] for r in result["participants"]] == ["reference_missing", "absent"]
    assert result["participants"][1]["path"] == [0, 0]
    assert control.efm.participants[1].node_uuid == uuid(2)


@pytest.mark.parametrize("firmware", [None, "17.2.8.27", "17.3.0.0"])
def test_synthetic_other_or_unknown_firmware_has_no_binding_decoder(firmware) -> None:
    control = monitor([node(actualEfmState=uuid(7))], [("actual0", uuid(7))])
    result = bind(control.efm, control, firmware)
    assert result["rule_id"] is None
    assert result["participants"][0]["status"] == "unsupported_version"
    assert not result["participants"][0]["states"]
    assert not result["reference_complete"]


def test_synthetic_candidate_map_and_response_bounds() -> None:
    control = monitor(
        [node(i + 1, actualEfmState=uuid(7)) for i in range(100)],
        [("\u2603" * 120 + str(i), uuid(7)) for i in range(101)],
    )
    result = bind(control.efm, control, FIRMWARE)
    assert len(json.dumps(result, ensure_ascii=True).encode()) <= MAX_BINDING_BYTES
    assert sum(len(r["states"]) for r in result["participants"]) <= 100
    assert any(r["candidates_omitted"] for r in result["participants"])
    assert not result["reference_complete"]
    control = replace(control, state_uuids=tuple((f"state{i}", uuid(7)) for i in range(1001)))
    assert bind(control.efm, control, FIRMWARE)["participants"][0]["status"] == "state_map_limit"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    [
        "verified",
        "case_separator",
        "different_serial",
        "invalid_identity",
        "unavailable",
        "invalid_version",
    ],
)
async def test_synthetic_full_describe_checks_target_version_without_value_reads(
    monkeypatch, source
) -> None:
    control = monitor([node(3, actualEfmState=uuid(7))], [("actual9", uuid(7))])
    structure = LoxoneStructure(LoxoneIdentity("reader", "020000AABBCC"), "1", (), (), (control,))
    fresh_calls = []
    probe_calls = []

    async def snapshot(_runtime, *, fresh_visibility=False):
        fresh_calls.append(fresh_visibility)
        return _loxberry_access(READ_SCOPE), RuntimeSnapshot("family", structure, True)

    @asynccontextmanager
    async def slot(_access):
        yield

    async def probe():
        probe_calls.append(True)
        if source == "unavailable":
            raise LoxoneConnectionError("Synthetic failure")
        return ProbeResult(
            "private malformed version" if source == "invalid_version" else FIRMWARE,
            {
                "different_serial": "020000000002",
                "invalid_identity": "private invalid serial",
                "case_separator": "02:00:00:aa:bb:cc",
            }.get(source, "020000AABBCC"),
            True,
            None,
        )

    runtime = SimpleNamespace(call_slot=slot, client=SimpleNamespace(probe=probe))
    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("synthetic-bindings")
    register_read_tools(server, runtime)
    tool = server._tool_manager.get_tool("loxone_describe_control")
    result = await tool.fn(uuid(1))
    assert result.ok, result
    bindings = result.data.capabilities.model.efm_bindings
    assert bindings.participants[0].status == (
        "resolved" if source in {"verified", "case_separator"} else "unsupported_version"
    )
    assert bindings.firmware_version == (
        FIRMWARE if source in {"verified", "case_separator"} else None
    )
    assert (
        bindings.firmware_verification
        == {
            "verified": "verified",
            "case_separator": "verified",
            "invalid_identity": "invalid_identity",
            "different_serial": "identity_mismatch",
            "unavailable": "unavailable",
            "invalid_version": "invalid_version",
        }[source]
    )
    assert "private malformed version" not in result.model_dump_json()
    assert "private invalid serial" not in result.model_dump_json()
    assert fresh_calls == [False, True] and probe_calls == [True]
    for view in ("state_refs", "history_targets", "operation_targets"):
        result = await tool.fn(uuid(1), view=view)
        assert result.ok and "efm_bindings" not in result.model_dump_json()
    assert probe_calls == [True]


def test_synthetic_uninspected_children_make_binding_coverage_incomplete() -> None:
    control = monitor([node(nodes={"private": "uninspected"})])
    result = bind(control.efm, control, FIRMWARE)
    assert not result["reference_complete"]
    assert "uninspected" not in json.dumps(result)


def test_synthetic_binding_projection_validates_public_schema() -> None:
    from mcpserver.tools import EfmBindingsData

    control = monitor([node(actualEfmState=uuid(7))], [("actual0", uuid(7)), ("actual0", uuid(8))])
    result = EfmBindingsData.model_validate(bind(control.efm, control, FIRMWARE))
    assert result.participants[0].status == "conflict"


def test_synthetic_binding_paths_follow_bounded_participant_projection() -> None:
    from mcpserver.loxone.efm import describe

    control = monitor(
        [node(i + 1, ctrlUuid=uuid(99), actualEfmState=uuid(7)) for i in range(100)],
        [("actual0", uuid(7))],
    )
    visible = replace(target(99), name="\u2603" * 200, control_type="\u2603" * 64)
    projection = describe(control.efm, {uuid(99): visible})
    assert projection["projection_omitted"] > 0
    bindings = bind(control.efm, control, FIRMWARE, occurrence_limit=projection["returned"])
    assert [r["path"] for r in bindings["participants"]] == [
        r["path"] for r in projection["participants"]
    ]
    assert bindings["projection_omitted"] == projection["projection_omitted"]
    assert not bindings["reference_complete"]


def test_synthetic_xml_field_aliases_never_become_runtime_bindings() -> None:
    control = monitor([node(liveState=uuid(7), efmState=uuid(7))], [("actual0", uuid(7))])
    result = bind(control.efm, control, FIRMWARE)
    assert result["participants"][0]["status"] == "absent"
    assert not result["participants"][0]["states"]
