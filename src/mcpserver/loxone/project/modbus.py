"""Allowlisted raw analog endpoint evidence; no defaults or protocol decoder."""

import re
from collections.abc import Mapping

from .graph import GraphNode

FIELDS = {
    "ModbusASensor": (
        "ModbusAddress",
        "ModbusCmd",
        "ModbusDataType",
        "ModbusPollingCycle",
        "SourceValHigh",
        "DestValHigh",
    ),
    "ModbusAActor": (
        "ModbusAddress",
        "ModbusCmd",
        "ModbusDataType",
        "SourceValHigh",
        "DestValHigh",
        "Channel",
        "RepeatRate",
        "ModbusCoilQuantity",
    ),
    "ModbusDev": ("Channel",),
    "ModbusServer": ("Timeout",),
    "Comm485": ("RxTimeout", "Baudrate", "Databits", "Parity", "Pause", "Protocol"),
}
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


def raw_fields(node: GraphNode) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for field in FIELDS.get(node.block_type or "", ()):
        values = [value for key, value in node.attributes if key == field]
        invalid = any(len(value) > 64 or not _NUMBER.fullmatch(value) for value in values)
        status = (
            "absent"
            if not values
            else "ambiguous"
            if len(set(values)) > 1
            else "invalid"
            if invalid
            else "explicit"
        )
        result.append(
            {
                "source_field": field,
                "evidence_status": status,
                "raw_value": values[0] if status == "explicit" else None,
                "occurrences": [
                    {
                        "raw_value": value
                        if len(value) <= 64 and _NUMBER.fullmatch(value)
                        else None,
                        "invalid": len(value) > 64 or not bool(_NUMBER.fullmatch(value)),
                    }
                    for value in values[:8]
                ],
                "occurrences_omitted": max(0, len(values) - 8),
                "semantics": "unresolved",
            }
        )
    return result


def sensor_projection(
    node: GraphNode,
    nodes: Mapping[str, GraphNode],
    parents: Mapping[str, list[str]],
    limit: int,
) -> dict[str, object] | None:
    if node.kind != "block" or node.block_type not in {"ModbusASensor", "ModbusAActor"}:
        return None
    ancestors: list[dict[str, object]] = []
    seen = {node.key}
    current = node
    status = "absent"
    truncated = False
    for _ in range(min(limit, 16)):
        candidates = parents.get(current.key, [])
        if not candidates:
            break
        if len(candidates) != 1:
            status = "ambiguous"
            break
        parent = nodes.get(candidates[0])
        if parent is None or parent.key in seen or parent.project != node.project:
            status = "invalid"
            break
        seen.add(parent.key)
        if parent.block_type not in {"ModbusDev", "ModbusServer", "Comm485"} and not (
            node.block_type == "ModbusAActor" and parent.block_type == "ActorCaption"
        ):
            break
        status = "explicit"
        ancestors.append(
            {
                "project_node_id": parent.key,
                "model_source_id": parent.project,
                "source_type": parent.block_type,
                "relationship": "contains",
                "child_project_node_id": current.key,
                "fields": raw_fields(parent),
            }
        )
        current = parent
    else:
        truncated = bool(parents.get(current.key))
    return {
        "source_type": node.block_type,
        "flow_direction": "source_read"
        if node.block_type == "ModbusASensor"
        else "configured_write",
        "project_node_id": node.key,
        "model_source_id": node.project,
        "fields": raw_fields(node),
        "ancestors": ancestors,
        "ancestry_status": status,
        "ancestry_truncated": truncated,
        "coverage_complete": False,
    }
