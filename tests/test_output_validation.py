from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolRequest, CallToolRequestParams, CallToolResult, TextContent

from mcpserver.output_validation import OutputValidatedFastMCP
from mcpserver.server import _ForwardedHostFastMCP

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "integer", "minimum": 1},
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def _register(server: OutputValidatedFastMCP, schema: dict = SCHEMA) -> Any:
    def answer(items: list[int]) -> dict[str, Any]:
        return {"items": items}

    server.add_tool(answer)
    tool = server._tool_manager.get_tool("answer")
    assert tool is not None
    tool.output_schema = deepcopy(schema)
    return tool


async def _call(server: OutputValidatedFastMCP, items: Any) -> CallToolResult:
    handler = server._mcp_server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(params=CallToolRequestParams(name="answer", arguments={"items": items}))
    )
    assert isinstance(result.root, CallToolResult)
    return result.root


@pytest.mark.asyncio
async def test_schema_checked_once_but_every_response_fully_validated(monkeypatch) -> None:
    checks = []
    original = Draft202012Validator.check_schema

    def check(cls, schema, *args, **kwargs):
        checks.append(deepcopy(schema))
        return original(schema, *args, **kwargs)

    monkeypatch.setattr(Draft202012Validator, "check_schema", classmethod(check))
    server = _ForwardedHostFastMCP("test")
    _register(server)
    for items in ([1, 2], [1, 1], [0], [2, 3]):
        result = await _call(server, items)
        assert result.isError is (items in ([1, 1], [0]))
        if not result.isError:
            assert result.structuredContent == {"items": items}
    assert checks == [SCHEMA]


@pytest.mark.asyncio
async def test_changed_schema_and_tool_replacement_invalidate_validator() -> None:
    server = OutputValidatedFastMCP("test")
    tool = _register(server)
    assert not (await _call(server, [1])).isError
    first = server._output_validators["answer"][1]
    tool.output_schema["properties"]["items"]["items"]["minimum"] = 2
    assert (await _call(server, [1])).isError
    assert server._output_validators["answer"][1] is not first
    server.remove_tool("answer")
    assert not server._output_validators
    _register(server)
    # The SDK's tools/list cache may still hold the previous definition.
    assert not (await _call(server, [1])).isError


@pytest.mark.asyncio
async def test_invalid_replacement_schema_fails_closed_without_running_tool() -> None:
    server = OutputValidatedFastMCP("test")
    tool = _register(server)
    assert not (await _call(server, [1])).isError
    calls = []

    async def forbidden(**kwargs):
        calls.append(True)
        return {"items": [1]}

    tool.fn = forbidden
    tool.output_schema = {"type": "invalid-schema-type"}
    assert (await _call(server, [1])).isError
    assert not calls
    assert json.loads(server._output_validators["answer"][0]) == SCHEMA


@pytest.mark.asyncio
async def test_cache_is_per_server_and_invalid_inputs_do_not_reach_handler() -> None:
    servers = [OutputValidatedFastMCP("first"), OutputValidatedFastMCP("second")]
    for server in servers:
        _register(server)
        assert not (await _call(server, [1])).isError
    assert (
        servers[0]._output_validators["answer"][1] is not servers[1]._output_validators["answer"][1]
    )
    tool = servers[0]._tool_manager.get_tool("answer")
    calls = []

    async def forbidden(**kwargs):
        calls.append(True)

    tool.fn = forbidden
    assert (await _call(servers[0], "not-an-array")).isError
    assert not calls


@pytest.mark.asyncio
async def test_inflight_call_uses_its_registration_and_cancellation_propagates() -> None:
    server = OutputValidatedFastMCP("test")
    tool = _register(server)
    started, finish = asyncio.Event(), asyncio.Event()

    async def waiting(**kwargs):
        started.set()
        await finish.wait()
        return {"items": [1]}

    tool.fn = waiting
    tool.is_async = True
    task = asyncio.create_task(_call(server, [1]))
    await started.wait()
    server.remove_tool("answer")
    changed = deepcopy(SCHEMA)
    changed["properties"]["items"]["items"]["minimum"] = 2
    _register(server, changed)
    finish.set()
    assert not (await task).isError
    assert (await _call(server, [1])).isError
    tool = server._tool_manager.get_tool("answer")
    started.clear()
    finish.clear()
    tool.fn = waiting
    tool.is_async = True
    task = asyncio.create_task(_call(server, [2]))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["tuple", "dict", "prebuilt", "missing"])
async def test_transport_normalization_never_bypasses_structured_validation(kind) -> None:
    class CustomServer(OutputValidatedFastMCP):
        async def call_tool(self, name, arguments):
            content = [TextContent(type="text", text="preserved")]
            structured = {"items": [0]}
            if kind == "tuple":
                return content, structured
            if kind == "dict":
                return structured
            if kind == "prebuilt":
                return CallToolResult(content=content, structuredContent=structured)
            return content

    server = CustomServer("test")
    _register(server)
    result = await _call(server, [1])
    assert result.isError
    assert result.content[0].text.startswith("Output validation error:")


@pytest.mark.asyncio
async def test_unstructured_tools_and_unknown_tools_keep_sdk_behavior() -> None:
    server = OutputValidatedFastMCP("test")

    @server.tool(structured_output=False)
    def answer(items: list[int]) -> str:
        return "plain text"

    result = await _call(server, [1])
    assert not result.isError
    assert result.content[0].text == "plain text"
    assert result.structuredContent is None
    assert not server._output_validators
    server.remove_tool("answer")
    assert (await _call(server, [1])).isError


@pytest.mark.asyncio
async def test_wire_results_and_tool_definitions_match_pinned_sdk() -> None:
    original = FastMCP("test")
    optimized = OutputValidatedFastMCP("test")
    for server in (original, optimized):
        _register(server)
    assert await original.list_tools() == await optimized.list_tools()
    for items in ([1, 2], [1, 1], [0], "invalid-input"):
        expected = await _call(original, items)
        actual = await _call(optimized, items)
        assert actual.model_dump() == expected.model_dump()


@pytest.mark.asyncio
@pytest.mark.parametrize("constraint", ["const", "enum"])
async def test_schema_key_distinguishes_json_boolean_from_number(constraint) -> None:
    server = OutputValidatedFastMCP("test")
    schema = deepcopy(SCHEMA)
    schema["properties"]["items"] = {constraint: [1] if constraint == "const" else [[1]]}
    tool = _register(server, schema)
    assert not (await _call(server, [1])).isError
    original = server._output_validators["answer"][1]
    tool.output_schema["properties"]["items"][constraint] = (
        [True] if constraint == "const" else [[True]]
    )
    assert (await _call(server, [1])).isError
    assert server._output_validators["answer"][1] is not original
    tool.fn = lambda items: {"items": [True]}
    assert not (await _call(server, [1])).isError
