"""Bounded, payload-free comparison of advertised and client-visible tool contracts."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

MAX_DISCOVERY_BYTES = 16 * 1024 * 1024
MAX_DISCOVERY_TOOLS = 512
CONTRACT_FIELDS = ("description", "annotations", "inputSchema", "outputSchema", "_meta")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def discovery_identity(document: object) -> dict[str, dict[str, str]]:
    """Return identities only; never retain or report schema text or request payloads."""
    if not isinstance(document, dict):
        raise ValueError("discovery_document_invalid")
    root = document.get("result", document)
    if not isinstance(root, dict) or not isinstance(root.get("tools"), list):
        raise ValueError("discovery_document_invalid")
    tools = root["tools"]
    if len(tools) > MAX_DISCOVERY_TOOLS:
        raise ValueError("discovery_tool_limit")
    identities: dict[str, dict[str, str]] = {}
    for tool in tools:
        if not isinstance(tool, dict):
            raise ValueError("discovery_tool_invalid")
        name = tool.get("name")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name)
            or name in identities
            or not isinstance(tool.get("inputSchema"), dict)
        ):
            raise ValueError("discovery_tool_invalid")
        identity = {}
        for field in CONTRACT_FIELDS:
            value = tool.get(field)
            if value is None:
                continue
            if not isinstance(value, str if field == "description" else dict):
                raise ValueError("discovery_tool_invalid")
            identity[field] = _digest(value)
        identities[name] = identity
    return identities


def compare_discovery(reference: object, observed: object) -> dict[str, Any]:
    """Compare like-for-like captures; mismatches do not assign fault or authorization."""
    expected = discovery_identity(reference)
    actual = discovery_identity(observed)
    return _compare_identities(expected, actual, CONTRACT_FIELDS, "tools")


def _compare_identities(
    expected: dict[str, dict[str, str]],
    actual: dict[str, dict[str, str]],
    fields: tuple[str, ...],
    kind: str,
) -> dict[str, Any]:
    changed = []
    unexposed = []
    for name in sorted(expected.keys() & actual.keys()):
        differences = [
            field
            for field in fields
            if field in actual[name] and expected[name].get(field) != actual[name][field]
        ]
        unavailable = [field for field in expected[name] if field not in actual[name]]
        if differences:
            changed.append({"name": name, "fields": differences})
        if unavailable:
            unexposed.append({"name": name, "fields": sorted(unavailable)})
    missing = sorted(expected.keys() - actual.keys())
    additional = sorted(actual.keys() - expected.keys())
    return {
        "version": 1,
        "reference_identity": _digest(expected),
        "observed_identity": _digest(actual),
        f"reference_{kind}": len(expected),
        f"observed_{kind}": len(actual),
        f"missing_{kind}": missing,
        f"additional_{kind}": additional,
        "changed_contracts": changed,
        "unexposed_fields": unexposed,
        "status": "different"
        if missing or additional or changed
        else "incomplete"
        if unexposed
        else "equal",
    }


def prompt_discovery_identity(document: object) -> dict[str, dict[str, str]]:
    """Hash only bounded prompt advertisement; never expand or retain recipes."""
    if not isinstance(document, dict):
        raise ValueError("discovery_document_invalid")
    root = document.get("result", document)
    if not isinstance(root, dict) or not isinstance(root.get("prompts"), list):
        raise ValueError("discovery_document_invalid")
    prompts = root["prompts"]
    if len(prompts) > 64:
        raise ValueError("discovery_prompt_limit")
    result: dict[str, dict[str, str]] = {}
    for prompt in prompts:
        if not isinstance(prompt, dict):
            raise ValueError("discovery_prompt_invalid")
        name = prompt.get("name")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name)
            or name in result
        ):
            raise ValueError("discovery_prompt_invalid")
        identity = {}
        for field in ("title", "description"):
            value = prompt.get(field)
            if value is not None:
                if not isinstance(value, str) or len(value) > 4096:
                    raise ValueError("discovery_prompt_invalid")
                identity[field] = _digest(value)
        if "arguments" in prompt:
            arguments = prompt["arguments"]
            if not isinstance(arguments, list) or len(arguments) > 32:
                raise ValueError("discovery_prompt_invalid")
            seen: set[str] = set()
            for argument in arguments:
                if not isinstance(argument, dict) or not argument.keys() <= {
                    "name",
                    "description",
                    "required",
                }:
                    raise ValueError("discovery_prompt_invalid")
                arg_name = argument.get("name")
                description = argument.get("description", "")
                if (
                    not isinstance(arg_name, str)
                    or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", arg_name)
                    or arg_name in seen
                    or not isinstance(description, str)
                    or len(description) > 4096
                    or type(argument.get("required", False)) is not bool
                ):
                    raise ValueError("discovery_prompt_invalid")
                seen.add(arg_name)
            identity["arguments"] = _digest(arguments)
        result[name] = identity
    return result


def compare_prompt_discovery(reference: object, observed: object) -> dict[str, Any]:
    """Compare prompts/list separately so clients without prompt support keep tool access."""
    return _compare_identities(
        prompt_discovery_identity(reference),
        prompt_discovery_identity(observed),
        ("title", "description", "arguments"),
        "prompts",
    )
