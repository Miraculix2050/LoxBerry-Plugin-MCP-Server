"""Reuse checked output validators at the pinned FastMCP transport boundary."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from jsonschema.exceptions import best_match  # type: ignore[import-untyped]
from jsonschema.protocols import Validator  # type: ignore[import-untyped]
from jsonschema.validators import validator_for  # type: ignore[import-untyped]
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, CreateTaskResult, TextContent


class OutputValidatedFastMCP(FastMCP):
    """Keep full per-response validation without rechecking unchanged schemas.

    The MCP 1.28.1 low-level handler accepts prebuilt CallToolResult objects.
    Normalize and validate here before using that path; keep its exception and
    cancellation handling and FastMCP's argument validation unchanged.
    """

    def _setup_handlers(self) -> None:
        self._output_validators: dict[str, tuple[str, Validator]] = {}
        super()._setup_handlers()
        self._mcp_server.call_tool(validate_input=False)(self._validated_tool_call)

    def remove_tool(self, name: str) -> None:
        super().remove_tool(name)
        self._output_validators.pop(name, None)

    def _output_validator(self, name: str, schema: dict[str, Any]) -> Validator:
        # Python equality conflates JSON booleans and numbers (True == 1).
        # A JSON key preserves their distinct const/enum semantics without
        # sorting every nested object on each response. Order-only changes may
        # safely trigger another full schema check.
        key = json.dumps(schema, separators=(",", ":"), allow_nan=False)
        cached = self._output_validators.get(name)
        if cached is None or cached[0] != key:
            # An independent snapshot detects replacement AND in-place edits.
            # Never cache a schema that failed its full meta-schema check.
            snapshot = deepcopy(schema)
            validator_type = validator_for(snapshot)
            validator_type.check_schema(snapshot)
            cached = (key, validator_type(snapshot))
            self._output_validators[name] = cached
        return cached[1]

    async def _validated_tool_call(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tool_manager.get_tool(name)
        schema = tool.output_schema if tool is not None else None
        validator = self._output_validator(name, schema) if schema is not None else None
        # Capture the validator before awaiting the handler: an in-flight call
        # belongs to this registration even if the tool is replaced meanwhile.
        # MCP 1.28.1's annotation omits its actual (content, structured) result.
        result: Any = await self.call_tool(name, arguments)
        if isinstance(result, CreateTaskResult):
            return result  # Protocol task acknowledgement, not a tool answer.
        if isinstance(result, CallToolResult):
            response = result
        elif isinstance(result, tuple) and len(result) == 2:
            content, structured = result
            response = CallToolResult(content=list(content), structuredContent=structured)
        elif isinstance(result, dict):
            response = CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, indent=2))],
                structuredContent=result,
            )
        else:
            response = CallToolResult(content=list(result))
        if validator is not None:
            if response.structuredContent is None:
                raise ValueError(
                    "Output validation error: "
                    "outputSchema defined but no structured output returned"
                )
            # Match jsonschema.validate's complete traversal/error selection,
            # rather than skipping response validation after a cache hit.
            error = best_match(validator.iter_errors(response.structuredContent))
            if error is not None:
                # jsonschema messages can contain entire invalid source values.
                raise ValueError(
                    "Output validation error: response does not match the declared output schema"
                ) from None
        return response
