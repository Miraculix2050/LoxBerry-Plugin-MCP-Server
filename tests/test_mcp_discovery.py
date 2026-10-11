from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from mcpserver.discovery import (
    MAX_DISCOVERY_BYTES,
    MAX_DISCOVERY_TOOLS,
    compare_discovery,
    discovery_identity,
)
from mcpserver.schema_reference import tool_schema_catalog
from mcpserver.tools import register_project_tools


def _capture() -> dict:
    return {
        "tools": [
            {
                "name": "loxone_analyze_project",
                "description": "Analyze the authorized project",
                "annotations": {"readOnlyHint": True},
                "inputSchema": {"properties": {"analyses": {"enum": ["existing"]}}},
                "outputSchema": {"properties": {"data": {"type": "object"}}},
            }
        ]
    }


def test_equivalent_jsonrpc_capture_and_key_order_have_same_identity() -> None:
    capture = _capture()
    reordered = json.loads(json.dumps(capture, sort_keys=True))
    report = compare_discovery(capture, {"result": reordered, "jsonrpc": "2.0", "id": 1})
    assert report["status"] == "equal"
    assert report["reference_identity"] == report["observed_identity"]


@pytest.mark.parametrize("field", ["description", "annotations", "inputSchema", "outputSchema"])
def test_additive_changes_detected_without_changing_tool_name(field: str) -> None:
    old = _capture()
    upgraded = copy.deepcopy(old)
    tool = upgraded["tools"][0]
    if field == "description":
        tool[field] = "Read ETS/manual metadata from the authorized project"
    else:
        tool[field]["new_knx_contract"] = {"enum": ["ets_project_comparison"]}
    report = compare_discovery(upgraded, old)
    assert report["status"] == "different"
    assert report["missing_tools"] == []
    assert report["changed_contracts"] == [{"name": tool["name"], "fields": [field]}]
    assert "new_knx_contract" not in json.dumps(report)
    assert "Read ETS/manual" not in json.dumps(report)


def test_unexposed_client_output_is_incomplete_not_a_confirmed_schema_defect() -> None:
    expected = _capture()
    client = copy.deepcopy(expected)
    client["tools"][0].pop("outputSchema")
    report = compare_discovery(expected, client)
    assert report["status"] == "incomplete"
    assert report["unexposed_fields"] == [
        {"name": "loxone_analyze_project", "fields": ["outputSchema"]}
    ]
    assert report["changed_contracts"] == []


def test_missing_and_additional_tools_are_separate_from_contract_changes() -> None:
    first = _capture()
    second = copy.deepcopy(first)
    second["tools"][0]["name"] = "another_tool"
    report = compare_discovery(first, second)
    assert report["missing_tools"] == ["loxone_analyze_project"]
    assert report["additional_tools"] == ["another_tool"]


def test_newly_exposed_contract_field_is_detected() -> None:
    old = _capture()
    old["tools"][0].pop("outputSchema")
    report = compare_discovery(old, _capture())
    assert report["status"] == "different"
    assert report["changed_contracts"][0]["fields"] == ["outputSchema"]


@pytest.mark.parametrize("document", [None, {}, {"result": []}, {"tools": [None]}])
def test_invalid_documents_are_rejected(document: object) -> None:
    with pytest.raises(ValueError, match="discovery_"):
        discovery_identity(document)


def test_duplicates_and_tool_limit_are_rejected() -> None:
    capture = _capture()
    with pytest.raises(ValueError, match="discovery_tool_invalid"):
        discovery_identity({"tools": capture["tools"] * 2})
    with pytest.raises(ValueError, match="discovery_tool_limit"):
        discovery_identity({"tools": capture["tools"] * (MAX_DISCOVERY_TOOLS + 1)})


@pytest.mark.asyncio
async def test_live_project_discovery_matches_reference_without_project_access() -> None:
    server = FastMCP("discovery regression")
    register_project_tools(server, None)
    live = [tool.model_dump(by_alias=True, exclude_none=True) for tool in await server.list_tools()]
    names = {tool["name"] for tool in live}
    reference = {
        "tools": [tool for tool in tool_schema_catalog("test")["tools"] if tool["name"] in names]
    }
    assert compare_discovery(reference, {"tools": live})["status"] == "equal"
    analysis = next(tool for tool in live if tool["name"] == "loxone_analyze_project")
    assert "ets_project_comparison" in json.dumps(analysis["inputSchema"])
    description = next(tool for tool in live if tool["name"] == "loxone_describe_project_object")
    assert "imported" in json.dumps(description["outputSchema"])


@pytest.mark.parametrize(
    "case,exit_code", [("equal", 0), ("changed", 1), ("invalid", 2), ("large", 2)]
)
def test_cli_reports_bounded_sanitized_results(tmp_path: Path, case: str, exit_code: int) -> None:
    reference = tmp_path / "reference.json"
    observed = tmp_path / "observed.json"
    reference.write_text(json.dumps(_capture()), encoding="utf-8")
    data = _capture()
    if case == "changed":
        data["tools"][0]["description"] = "PRIVATE_UNTRUSTED_TEXT"
    observed.write_bytes(
        b"PRIVATE_UNTRUSTED_TEXT" if case == "invalid" else json.dumps(data).encode()
    )
    if case == "large":
        with observed.open("wb") as stream:
            stream.truncate(MAX_DISCOVERY_BYTES + 1)
    result = subprocess.run(
        [
            sys.executable,
            "tools/check_mcp_discovery.py",
            "--reference",
            str(reference),
            "--observed",
            str(observed),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.returncode == exit_code
    assert result.stderr == ""
    assert "PRIVATE_UNTRUSTED_TEXT" not in result.stdout
    assert str(tmp_path) not in result.stdout
    assert json.loads(result.stdout)["status"] == (
        "equal" if case == "equal" else "different" if case == "changed" else "invalid"
    )
