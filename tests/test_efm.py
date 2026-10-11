"""Independently authored synthetic fixtures; no installation inventory.

Flat field types reproduce the sanitized 17.2.8.28 specimen contract
(SHA256 242d191e4cbd2efc82397bc3cfb2026ec3e287278527e74ed451addb741af310).
Nesting, missing/invalid metadata, repeated identities and bounds are synthetic,
not observed runtime cases. No role decoder or device compatibility is claimed.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from mcp.server.fastmcp import FastMCP
from test_tools import READ_SCOPE, _loxberry_access

from mcpserver import tools as tools_module
from mcpserver.loxone.efm import MAX_DEPTH, MAX_NODES, describe, normalize
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import RuntimeSnapshot
from mcpserver.tools import register_read_tools


def uuid(n: int) -> str:
    return f"{n:08x}-0000-0000-0000000000000000"


def node(n: int = 1, **extra: object) -> dict[str, object]:
    return {"uuid": uuid(n), "nodeType": "Grid", "title": "Synthetic", **extra}


def target(n: int) -> Control:
    return Control(uuid(n), "Visible", "Meter", None, None, None, ())


def test_synthetic_occurrences_preserve_hierarchy_reuse_and_monitor_identity() -> None:
    projection = normalize(
        {
            "nodes": [
                node(ctrlUuid=uuid(9), nodes=[node(2, ctrlUuid=uuid(9))]),
                node(ctrlUuid=uuid(9)),
            ]
        }
    )
    value = describe(projection, {uuid(9): target(9)})
    rows = value["participants"]
    assert [r["path"] for r in rows] == [[0], [0, 0], [1]]
    assert [r["parent_path"] for r in rows] == [None, [0], None]
    assert all(r["control"]["uuid"] == uuid(9) for r in rows)
    assert value["diagnostics"] == ["repeated_node_identity"]
    assert rows[0]["role_token"] == "Grid" and rows[0]["role"] is None


def test_synthetic_hidden_missing_and_malformed_references_never_echo_identity() -> None:
    projection = normalize(
        {
            "nodes": [
                node(ctrlUuid=uuid(77)),
                node(2),
                node(3, ctrlUuid={"private": "secret"}),
                "invalid",
            ]
        }
    )
    value = describe(projection, {})
    assert [r["reference_status"] for r in value["participants"]] == [
        "unavailable",
        "absent",
        "malformed",
        "malformed",
    ]
    assert uuid(77) not in json.dumps(value)
    assert "secret" not in json.dumps(value)
    assert not value["references_complete"]


@pytest.mark.parametrize("token", ["Unknown", 7, True, {}, "x" * 65])
def test_synthetic_role_tokens_do_not_decode_xml_or_aliases(token: object) -> None:
    value = describe(normalize({"nodes": [node(nodeType=token)]}), {})
    row = value["participants"][0]
    assert row["role"] is None and not value["roles_complete"]
    assert row["role_token"] == token if token in ("Unknown", 7) else row["role_token"] is None


def test_synthetic_limits_and_invalid_collections() -> None:
    value = describe(normalize({"nodes": [node(i + 1) for i in range(MAX_NODES + 3)]}), {})
    assert value["returned"] == MAX_NODES and value["omitted_subtrees"] == 3
    assert value["omitted_descendants"] is None
    nested = node()
    for i in range(MAX_DEPTH + 2):
        nested = node(i + 2, nodes=[nested])
    value = describe(normalize({"nodes": [nested]}), {})
    assert value["returned"] == MAX_DEPTH and not value["topology_complete"]
    value = describe(normalize({"nodes": {}}), {})
    assert not value["topology_complete"] and not value["references_complete"]


def test_synthetic_residual_is_display_metadata_not_participant() -> None:
    value = describe(
        normalize({"nodes": [], "rest": True, "restName": "Synthetic rest", "restIcon": "icon"}), {}
    )
    assert value["participants"] == []
    assert value["residual_display"]["restName"] == "Synthetic rest"


@pytest.mark.asyncio
async def test_full_efm_uses_fresh_visibility_and_compact_views_omit_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []
    monitor = replace(
        target(1), control_type="EFM", efm=normalize({"nodes": [node(3, ctrlUuid=uuid(2))]})
    )
    visible = LoxoneStructure(
        LoxoneIdentity("reader", "synthetic"), "1", (), (), (monitor, target(2))
    )
    fresh = replace(visible, controls=(monitor,), hidden_controls=(target(2),))

    async def snapshot(_runtime: object, *, fresh_visibility: bool = False):
        calls.append(fresh_visibility)
        return _loxberry_access(READ_SCOPE), RuntimeSnapshot(
            "family", fresh if fresh_visibility else visible, True
        )

    monkeypatch.setattr(tools_module, "_snapshot", snapshot)
    server = FastMCP("synthetic-efm")
    register_read_tools(server, None)
    tool = server._tool_manager.get_tool("loxone_describe_control")
    result = await tool.fn(uuid(1), include_hidden=True)
    assert result.ok, result
    assert calls == [False, True]
    row = result.data.capabilities.model.efm.participants[0]
    assert row.reference_status == "unavailable" and row.control is None
    assert uuid(2) not in result.model_dump_json()
    for view in ("history_targets", "operation_targets", "state_refs"):
        result = await tool.fn(uuid(1), view=view)
        assert result.ok
        assert "participants" not in result.model_dump_json()


def test_synthetic_normalizer_keeps_hidden_targets_outside_visible_inventory() -> None:
    from mcpserver.loxone.structure import normalize_structure

    raw = {
        "msInfo": {"serialNr": "synthetic"},
        "controls": {
            uuid(1): {
                "name": "Monitor",
                "type": "EFM",
                "details": {"nodes": [node(3, ctrlUuid=uuid(2), actualEfmState=uuid(4))]},
            },
            uuid(2): {"name": "Hidden", "type": "Meter", "restrictions": 1},
        },
    }
    structure = normalize_structure(raw, username="reader")
    monitor = structure.controls[0]
    assert monitor.efm is not None
    assert [c.uuid for c in structure.controls] == [uuid(1)]
    assert "actualEfmState" not in repr(monitor.efm)
    result = describe(monitor.efm, {c.uuid: c for c in structure.controls})
    assert uuid(2) not in json.dumps(result)


def test_synthetic_metadata_byte_limit_and_independent_completeness() -> None:
    details = {
        "nodes": [
            node(
                i + 1,
                title="\u2603" * 200,
                icon="\u2603" * 200,
                restName="\u2603" * 200,
                restIcon="\u2603" * 200,
            )
            for i in range(100)
        ]
    }
    result = describe(normalize(details), {})
    assert result["returned"] < 100
    assert result["omitted_subtrees"] == 100 - result["returned"]
    assert result["omitted_descendants"] is None
    result = describe(normalize({"nodes": [node(nodeType={})]}), {})
    assert result["topology_complete"]
    assert result["references_complete"]
    assert not result["roles_complete"]


def test_synthetic_malformed_children_are_reference_incomplete() -> None:
    result = describe(normalize({"nodes": [node(nodes={"private": "uninspected"})]}), {})
    assert not result["topology_complete"] and not result["references_complete"]
    assert "uninspected" not in json.dumps(result)


def test_synthetic_display_diagnostics_do_not_change_empty_role_coverage() -> None:
    result = describe(normalize({"nodes": [], "restName": {}}), {})
    assert result["diagnostics"] == ["invalid_residual_metadata"]
    assert result["roles_complete"] and result["topology_complete"]
    assert result["references_complete"]


def test_synthetic_root_residual_metadata_consumes_shared_byte_budget() -> None:
    nodes = [node(i + 1, title="\u2603" * 200, icon="\u2603" * 200) for i in range(100)]
    plain = normalize({"nodes": nodes})
    with_rest = normalize({"nodes": nodes, "restName": "\u2603" * 200, "restIcon": "\u2603" * 200})
    assert len(with_rest.participants) < len(plain.participants)
    assert dict(with_rest.residual)["restName"] == "\u2603" * 200
    assert with_rest.omitted_subtrees > plain.omitted_subtrees


def test_synthetic_resolved_control_amplification_fits_serialized_projection_budget() -> None:
    from mcpserver.loxone.efm import MAX_BYTES

    reused = replace(
        target(9), name="\u2603" * 10000, control_type="private oversized type" * 100000
    )
    projection = normalize({"nodes": [node(i + 1, ctrlUuid=uuid(9)) for i in range(100)]})
    result = describe(projection, {uuid(9): reused})
    assert len(json.dumps(result, ensure_ascii=True).encode()) <= MAX_BYTES
    assert result["projection_omitted"] > 0
    assert result["returned"] + result["projection_omitted"] == len(projection.participants)
    assert all(r["control_metadata_truncated"] for r in result["participants"])
    assert all(len(r["control"]["type"]) <= 64 for r in result["participants"])
    assert not result["topology_complete"] and not result["references_complete"]
