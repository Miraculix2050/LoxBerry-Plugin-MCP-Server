"""Bounded configuration evidence, never a physical opening inventory."""

from __future__ import annotations

import re
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from .models import Control, LoxoneStructure, StateRecord
from .presentation import visible_controls, window_monitor_description
from .project.graph import GraphEdge, GraphNode, SemanticEdge
from .project.query import ProjectQuery
from .project.semantics import STATE_RULE_ID, StateFlow, signal_use_rules, state_connector_reason
from .window_states import decode_window_states

type OpeningScope = Literal["monitor", "room", "contact", "consumer"]
MAX_MONITORS = 100
MAX_CONTACTS = 100
MAX_CONSUMERS = 100
MAX_TRACE_STARTS = 200
MAX_RESULT_RELATIONSHIPS = 200
MAX_GAPS_PER_TRACE = 20
MAX_GAPS_PER_CALL = 200
_SAFE_GAP_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
CONNECTOR_RULE_VERSION = 3
CONSUMER_CONNECTORS = {"AutoJalousie": "Window"}


class OpeningScopeError(ValueError):
    """The exact requested target is not visible or has the wrong type."""


@dataclass
class OpeningGraph:
    """Index once per call; each traversal bounds both nodes and edges."""

    query: ProjectQuery
    nodes: dict[str, GraphNode] = field(init=False)
    children: dict[str, list[str]] = field(init=False)
    parents: dict[str, str] = field(init=False)
    forward: dict[str, list[GraphEdge | SemanticEdge]] = field(init=False)
    backward: dict[str, list[GraphEdge | SemanticEdge]] = field(init=False)
    unresolved: set[str] = field(init=False)
    boundary_incomplete: dict[str, bool] = field(init=False)
    state_flows: dict[str, StateFlow] = field(init=False)
    starts: int = 0
    gaps_returned: int = 0

    def __post_init__(self) -> None:
        graph = self.query.view.snapshot.graph
        self.nodes = {node.key: node for node in graph.nodes}
        self.state_flows = {flow.block_key: flow for flow in graph.state_flows}
        self.children = defaultdict(list)
        self.parents = {}
        self.forward = defaultdict(list)
        self.backward = defaultdict(list)
        self.unresolved = {key for key, _code in graph.unresolved}
        self.unresolved.update(
            key
            for key, codes in self.query.view.snapshot.source_diagnostics.parser_codes_by_node
            if codes
        )
        for edge in graph.edges:
            if edge.kind == "contains":
                self.children[edge.source].append(edge.target)
                self.parents[edge.target] = edge.source
            elif edge.kind in {"signal", "reference"}:
                self.forward[edge.source].append(edge)
                self.backward[edge.target].append(edge)
        for semantic in graph.semantic_edges:
            self.forward[semantic.source].append(semantic)
            self.backward[semantic.target].append(semantic)
        self.boundary_incomplete = {}
        for parent, siblings in self.children.items():
            block = self.nodes[parent]
            rules = signal_use_rules(block.block_type)
            keys = Counter(dict(self.nodes[child].attributes).get("K") for child in siblings)
            configured_inputs = any(
                isinstance(e, GraphEdge) and e.kind in {"signal", "reference"}
                for child in siblings
                for e in self.backward[child]
            )
            connected_inputs = configured_inputs or bool(self.backward[parent])
            connected_outputs = any(self.forward[child] for child in siblings)
            reference_projection = any(
                isinstance(e, SemanticEdge) and e.rule_id == "input_ref_aq_v1"
                for e in self.forward[parent]
            )
            input_keys = {r.input_key for r in rules}
            output_keys = {r.output_key for r in rules}
            consumer_connector = CONSUMER_CONNECTORS.get(block.block_type or "")
            if consumer_connector:
                input_keys.add(consumer_connector)
            reference_block = block.block_type == "InputRef"
            if reference_block:
                output_keys.add("AQ")
            reviewed_boundary = bool(rules) or bool(consumer_connector) or reference_block
            uncovered_connections = reviewed_boundary and any(
                dict(self.nodes[child].attributes).get("K") not in covered_keys
                and (
                    child in self.unresolved
                    or any(isinstance(e, GraphEdge) for e in adjacency[child])
                )
                for adjacency, covered_keys in (
                    (self.backward, input_keys),
                    (self.forward, output_keys),
                )
                for child in siblings
            )
            self.boundary_incomplete[parent] = (
                (
                    connected_inputs
                    and connected_outputs
                    and not rules
                    and (not reference_projection or configured_inputs)
                    and block.block_type not in CONSUMER_CONNECTORS
                )
                or uncovered_connections
                or any(keys[r.input_key] != 1 or keys[r.output_key] != 1 for r in rules)
            )

    def connectors(
        self, block: GraphNode, key: str | None = None, *, limit: int | None = None
    ) -> list[str]:
        result = []
        for child in self.children[block.key]:
            if self.nodes[child].kind == "connector" and (
                key is None or dict(self.nodes[child].attributes).get("K") == key
            ):
                result.append(child)
                if limit is not None and len(result) >= limit:
                    break
        return result

    def trace(
        self, seeds: list[str], direction: str, max_depth: int, max_nodes: int
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "nodes": [],
            "edges": [],
            "complete": True,
            "warnings": [],
            "gaps": [],
            "gaps_omitted": 0,
        }
        if self.starts >= MAX_TRACE_STARTS:
            result.update(complete=False, warnings=["max_trace_starts"])
            return result
        self.starts += 1
        adjacency = self.forward if direction == "downstream" else self.backward
        visited = set(seeds[:max_nodes])
        ordered = list(dict.fromkeys(seeds[:max_nodes]))
        queue = deque((key, 0) for key in ordered)
        edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        warnings = set()

        def append_gap(key: str, reason: str) -> None:
            # Bound materialization across all traces, not just each traversal.
            if len(result["gaps"]) >= MAX_GAPS_PER_TRACE or self.gaps_returned >= MAX_GAPS_PER_CALL:
                result["gaps_omitted"] += 1
                warnings.add("max_gap_evidence")
                return
            node = self.nodes[key]
            parent = self.parents.get(key)
            block = self.nodes[parent] if node.kind == "connector" and parent is not None else node

            def token(value: str | None) -> str | None:
                return value if value and _SAFE_GAP_TOKEN.fullmatch(value) else None

            rules = signal_use_rules(block.block_type)
            result["gaps"].append(
                {
                    "direction": direction,
                    "project_node_id": key,
                    "node_kind": node.kind if node.kind in {"block", "connector"} else "unknown",
                    "block_type": token(block.block_type),
                    "connector_key": token(dict(node.attributes).get("K")),
                    "reason": reason,
                    "connector_rule_version": CONNECTOR_RULE_VERSION,
                    "rule_ids": [STATE_RULE_ID]
                    if block.key in self.state_flows and self.state_flows[block.key].reason is None
                    else [r.rule_id for r in rules[:8]],
                    "rule_ids_omitted": max(0, len(rules) - 8),
                    "reference_projection_rule_id": "input_ref_aq_v1"
                    if any(
                        isinstance(e, SemanticEdge) and e.rule_id == "input_ref_aq_v1"
                        for e in self.forward[block.key]
                    )
                    else None,
                    "evidence_node_ids": [key],
                }
            )
            self.gaps_returned += 1

        if len(seeds) > max_nodes:
            warnings.add("max_nodes")
        while queue:
            key, depth = queue.popleft()
            if key in self.unresolved:
                warnings.add("unresolved_relationship")
            # A reference into a block is not an implicit edge to its connectors.
            if (
                key not in seeds
                and self.nodes[key].kind == "block"
                and self.children[key]
                and (self.backward[key] or any(self.backward[c] for c in self.children[key]))
                and not any(
                    isinstance(e, SemanticEdge) and e.rule_id == "input_ref_aq_v1"
                    for e in self.forward[key]
                )
            ):
                warnings.add("unmodeled_internal_flow")
                append_gap(key, "block_reference_projection_unavailable")
            parent = self.parents.get(key)
            if parent is not None and self.nodes[key].kind == "connector":
                flow = self.state_flows.get(parent)
                if flow is not None:
                    reason = state_connector_reason(
                        flow, dict(self.nodes[key].attributes).get("K"), direction
                    )
                    # An unresolved configured relationship remains independent evidence.
                    if reason is not None:
                        warnings.add("unmodeled_internal_flow")
                        append_gap(key, reason)
                elif self.boundary_incomplete[parent]:
                    warnings.add("unmodeled_internal_flow")
                    append_gap(key, "parent_boundary_incomplete")
            for edge in adjacency[key]:
                neighbor = edge.target if direction == "downstream" else edge.source
                kind = "derived_semantic" if isinstance(edge, SemanticEdge) else edge.kind
                edge_key = (edge.source, edge.target, kind)
                if edge_key in edges:
                    continue
                if depth >= max_depth:
                    warnings.add("max_depth")
                    continue
                if len(edges) >= max_nodes:
                    warnings.add("max_edges")
                    break
                if neighbor not in visited and len(visited) >= max_nodes:
                    warnings.add("max_nodes")
                    break
                edges[edge_key] = {
                    "source": edge.source,
                    "target": edge.target,
                    "kind": kind,
                    "semantic_rule_id": edge.rule_id if isinstance(edge, SemanticEdge) else None,
                }
                if neighbor not in visited:
                    visited.add(neighbor)
                    ordered.append(neighbor)
                    queue.append((neighbor, depth + 1))
        result["nodes"] = [
            {
                "project_node_id": key,
                "kind": self.nodes[key].kind,
                "block_type": self.nodes[key].block_type,
                "connector_key": dict(self.nodes[key].attributes).get("K"),
                "parent_project_node_id": self.parents.get(key),
                "parent_block_type": self.nodes[self.parents[key]].block_type
                if key in self.parents
                else None,
            }
            for key in ordered
        ]
        result["edges"] = list(edges.values())
        result["warnings"] = sorted(warnings)
        result["complete"] = not warnings
        return result


def _state_alignment(
    monitor: Control,
    items: list[dict[str, Any]],
    summary: dict[str, Any],
    records: Mapping[str, StateRecord],
) -> dict[str, Any]:
    state_uuid = dict(monitor.state_uuids).get("windowStates")
    record = records.get(state_uuid or "")
    result: dict[str, Any] = {
        "state_uuid": state_uuid,
        "freshness": "unknown",
        "observed_at": None,
        "vector_length": None,
        "alignment": "unavailable",
        "warnings": [],
    }
    if record is not None:
        result.update(freshness=record.freshness.value, observed_at=record.observed_at)
    if record is None or record.value is None:
        result["warnings"] = ["state_unavailable"]
        return result
    result.update(freshness=record.freshness.value, observed_at=record.observed_at)
    if not isinstance(record.value, str) or len(record.value) > 65_536:
        result.update(alignment="invalid", warnings=["invalid_state_vector"])
        return result
    # Count the entire bounded string, but materialize only retained positions.
    length = record.value.count(",") + 1 if record.value else 0
    values = record.value.split(",", 100)[:100] if record.value else []
    result["vector_length"] = length
    result["alignment"] = (
        "unknown"
        if summary["total"] is None
        else "match"
        if length == summary["total"]
        else "mismatch"
    )
    if result["alignment"] != "match":
        result["warnings"].append(
            "state_vector_length_unverified"
            if summary["total"] is None
            else "state_vector_length_mismatch"
        )
    if record.freshness.value != "current":
        result["warnings"].append("state_not_current")
    decoded = decode_window_states(monitor, record.value)
    assert decoded is not None
    result.update(
        decoding_complete=decoded["decoding_complete"],
        mapping_complete=decoded["mapping_complete"],
        decoding_truncated=decoded["truncated"],
    )
    decoded_items = {contact["index"]: contact for contact in decoded["contacts"]}
    for item in items:
        index = item["index"]
        value = values[index].strip() if index < len(values) else None
        # Preserve source tokens only when they are small numeric codes; no state verdict.
        valid = value is not None and value.isascii() and value.isdigit() and len(value) <= 10
        item["state_value"] = value if valid else None
        item["decoded_state"] = decoded_items.get(index)
        if item["decoded_state"] is not None and not valid:
            # Preserve this analysis tool's existing nonnumeric-token redaction boundary.
            item["decoded_state"] = {
                **item["decoded_state"],
                "raw_token": None,
                "raw_token_redacted": value is not None,
            }
        if item["decoded_state"] is None or item["decoded_state"]["bitmask"] is None:
            result["warnings"].append("invalid_or_missing_state_value")
        if not valid:
            result["warnings"].append("invalid_or_missing_state_value")
    result["warnings"] = sorted(set(result["warnings"]))
    return result


def analyze_opening_contacts(
    structure: LoxoneStructure,
    project: ProjectQuery | None,
    *,
    scope_type: OpeningScope,
    scope_uuid: str,
    candidate_contact_uuids: list[str],
    include_current_state: bool = False,
    records: Mapping[str, StateRecord] | None = None,
    max_depth: int = 6,
    max_nodes: int = 100,
    state_reader: Callable[[str], StateRecord] | None = None,
) -> dict[str, Any]:
    """Join exact identities; classify absences only under complete relevant evidence."""
    controls = {control.uuid: control for control in visible_controls(structure)}
    rooms = {room.uuid: room.name for room in structure.rooms}
    target = controls.get(scope_uuid)
    if scope_type == "room":
        if scope_uuid not in rooms:
            raise OpeningScopeError("scope_not_accessible")
    elif (
        target is None
        or (scope_type == "monitor" and target.control_type != "WindowMonitor")
        or (scope_type == "consumer" and target.control_type not in CONSUMER_CONNECTORS)
    ):
        raise OpeningScopeError("scope_not_accessible")
    if any(uuid not in controls for uuid in candidate_contact_uuids):
        raise OpeningScopeError("candidate_not_accessible")
    all_monitors = [c for c in controls.values() if c.control_type == "WindowMonitor"]
    selected: list[Control] = []
    selected_count = 0
    for monitor in sorted(all_monitors, key=lambda c: c.uuid):
        matches = scope_type == "monitor" and monitor.uuid == scope_uuid
        if scope_type == "room" or scope_type == "consumer":
            room_uuid = scope_uuid if scope_type == "room" else target.room_uuid if target else None
            matches = room_uuid is not None and (
                monitor.room_uuid == room_uuid
                or any(item.room_uuid == room_uuid for item in monitor.window_monitor_items)
            )
        if scope_type == "contact":
            matches = any(
                item.control_uuid == scope_uuid
                or (
                    item.control_uuid in controls
                    and scope_uuid in controls[item.control_uuid].linked_control_uuids
                )
                for item in monitor.window_monitor_items
            )
        if matches:
            selected_count += 1
            if len(selected) < MAX_MONITORS:
                selected.append(monitor)
    warnings: set[str] = set()
    if scope_type != "monitor" and any(
        m.window_monitor_summary is not None
        and (m.window_monitor_summary.truncated or m.window_monitor_summary.diagnostics)
        for m in all_monitors
    ):
        warnings.add("scope_selection_incomplete")
    if selected_count > len(selected):
        warnings.add("max_monitors")
    origins: dict[str, set[str]] = defaultdict(set)
    omitted_contacts: set[str] = set()
    # Explicit caller candidates take precedence over bounded inferred candidates.
    if scope_type == "contact":
        origins[scope_uuid].add("caller_selected_candidate")
    for uuid in candidate_contact_uuids:
        if uuid in origins or len(origins) < MAX_CONTACTS:
            origins[uuid].add("caller_selected_candidate")
        else:
            omitted_contacts.add(uuid)
            warnings.add("max_contacts")
    monitors: list[dict[str, Any]] = []
    references: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for monitor in selected:
        items, summary = window_monitor_description(monitor, controls, rooms)
        assert summary is not None
        for item in items:
            uuid = item["control_uuid"]
            if uuid:
                references[uuid].append((monitor.uuid, item["index"]))
            if item["control"] is None:
                warnings.add("monitor_reference_unavailable")
            in_room = (
                scope_type != "room"
                or item["room_uuid"] == scope_uuid
                or (uuid in controls and controls[uuid].room_uuid == scope_uuid)
            )
            if uuid in controls and in_room:
                if uuid in origins or len(origins) < MAX_CONTACTS:
                    origins[uuid].add("direct_monitor_reference")
                else:
                    omitted_contacts.add(uuid)
                    warnings.add("max_contacts")
                for linked in sorted(controls[uuid].linked_control_uuids):
                    if linked in controls:
                        if linked in origins or len(origins) < MAX_CONTACTS:
                            origins[linked].add("explicit_control_link")
                        else:
                            omitted_contacts.add(linked)
                            warnings.add("max_contacts")
                    else:
                        warnings.add("linked_control_unavailable")
        if summary["truncated"] or summary["diagnostics"]:
            warnings.add("monitor_collection_incomplete")
        state_records = records or {}
        state_uuid = dict(monitor.state_uuids).get("windowStates")
        if include_current_state and state_reader is not None and state_uuid is not None:
            state_records = {state_uuid: state_reader(state_uuid)}
        monitors.append(
            {
                "monitor_uuid": monitor.uuid,
                "items": items,
                "summary": summary,
                "state": _state_alignment(monitor, items, summary, state_records)
                if include_current_state
                else None,
            }
        )
    duplicates = [
        {
            "control_uuid": uuid,
            "positions": [
                {"monitor_uuid": monitor_uuid, "index": index} for monitor_uuid, index in positions
            ],
        }
        for uuid, positions in sorted(references.items())
        if len(positions) > 1
    ]
    consumers: list[Control] = []
    consumer_count = 0
    for control in sorted(controls.values(), key=lambda c: c.uuid):
        if control.control_type not in CONSUMER_CONNECTORS:
            continue
        if scope_type == "consumer" and control.uuid != scope_uuid:
            continue
        if scope_type == "room" and control.room_uuid != scope_uuid:
            continue
        consumer_count += 1
        if len(consumers) < MAX_CONSUMERS:
            consumers.append(control)
    if consumer_count > len(consumers):
        warnings.add("max_consumers")
    if len(origins) > MAX_CONTACTS:
        warnings.add("max_contacts")
        origins = dict(list(origins.items())[:MAX_CONTACTS])
    contacts: list[dict[str, Any]] = [
        {"control_uuid": uuid, "evidence_kinds": sorted(kinds), "mapping_status": "unavailable"}
        for uuid, kinds in sorted(origins.items())
    ]
    result: dict[str, Any] = {
        "analysis_version": 1,
        "connector_rule_version": CONNECTOR_RULE_VERSION,
        "scope_type": scope_type,
        "scope_uuid": scope_uuid,
        "physical_opening_coverage": "not_assessable",
        "monitors": monitors,
        "contacts": contacts,
        "consumers": [],
        "duplicates": duplicates,
        "connections": [],
        "findings": [],
        "evidence": [],
        "project_fingerprint": None,
        "project_model_version": None,
        "project_marker": None,
        "structure_last_modified": structure.last_modified,
        "trace_starts": 0,
        "monitors_omitted": selected_count - len(selected),
        "consumers_omitted": consumer_count - len(consumers),
        "contacts_omitted": len(omitted_contacts),
        "response_units_omitted": 0,
        "connections_omitted": 0,
        "findings_omitted": 0,
        "warnings": [],
        "completeness": {
            "monitors": not bool(
                warnings
                & {"max_monitors", "monitor_collection_incomplete", "scope_selection_incomplete"}
            ),
            "mapping": False,
            "graph": False,
            "states": "not_requested"
            if not include_current_state
            else (
                "complete" if all(not m["state"]["warnings"] for m in monitors) else "incomplete"
            ),
        },
        "counts": {
            "resolved": sum(m["summary"]["resolved"] for m in monitors),
            "partially_resolved": sum(m["summary"]["partially_resolved"] for m in monitors),
            "unresolved": sum(m["summary"]["unresolved"] for m in monitors),
            "mismatched": sum(
                i["room_consistency"] == "mismatch" for m in monitors for i in m["items"]
            ),
            "duplicate_references": len(duplicates),
            "truncated_monitors": sum(m["summary"]["truncated"] for m in monitors),
        },
    }
    if project is None:
        result["warnings"] = sorted(warnings | {"project_unavailable"})
        return result
    result.update(
        project_fingerprint=project.view.snapshot.fingerprint,
        project_model_version=project.view.snapshot.model_version,
        project_marker=project.view.marker,
    )
    graph = OpeningGraph(project)
    if not project.view.snapshot.source_diagnostics.complete:
        warnings.add("project_source_incomplete")
    mapping = {m.control_uuid: m for m in project.view.mapping.entries}
    downstream: dict[str, dict[str, Any]] = {}
    contact_seeds: dict[str, set[str]] = {}
    negative_findings: list[dict[str, Any]] = []
    contact_consumers: dict[str, list[str]] = defaultdict(list)

    def append_finding(finding: dict[str, Any], *, negative: bool = False) -> None:
        destination = negative_findings if negative else result["findings"]
        if len(destination) < MAX_RESULT_RELATIONSHIPS:
            destination.append(finding)
        else:
            result["findings_omitted"] += 1
            warnings.add("max_findings")

    for contact in contacts:
        uuid = contact["control_uuid"]
        entry = mapping.get(uuid)
        contact["mapping_status"] = entry.status if entry else "unmapped"
        if entry is None or entry.status != "exact":
            warnings.add("mapping_incomplete")
            continue
        node = graph.nodes[entry.node_keys[0]]
        seeds: list[str] = []
        for occurrence in project.view.snapshot.occurrence_keys_for(node.key):
            seeds.append(occurrence)
            if len(seeds) > max_nodes:
                break
            seeds.extend(
                graph.connectors(graph.nodes[occurrence], limit=max_nodes + 1 - len(seeds))
            )
            if len(seeds) > max_nodes:
                break
        contact_seeds[uuid] = set(seeds)
        downstream[uuid] = graph.trace(seeds, "downstream", max_depth, max_nodes)
        downstream[uuid]["evidence_id"] = f"downstream:{uuid}"
        result["evidence"].append(downstream[uuid])
    for consumer in consumers:
        entry = mapping.get(consumer.uuid)
        consumer_data: dict[str, Any] = {
            "control_uuid": consumer.uuid,
            "connector_key": CONSUMER_CONNECTORS[consumer.control_type],
            "mapping_status": entry.status if entry else "unmapped",
            "connector_project_node_id": None,
        }
        result["consumers"].append(consumer_data)
        if entry is None or entry.status != "exact":
            warnings.add("mapping_incomplete")
            continue
        block = graph.nodes[entry.node_keys[0]]
        if block.block_type != consumer.control_type:
            warnings.add("consumer_connector_unresolved")
            continue
        connectors = graph.connectors(block, consumer_data["connector_key"], limit=2)
        if len(connectors) != 1:
            warnings.add("consumer_connector_unresolved")
            continue
        connector = connectors[0]
        consumer_data["connector_project_node_id"] = connector
        upstream = graph.trace([connector], "upstream", max_depth, max_nodes)
        upstream["evidence_id"] = f"upstream:{consumer.uuid}"
        result["evidence"].append(upstream)
        upstream_nodes = {node["project_node_id"] for node in upstream["nodes"]}
        sources: list[str] = []
        for uuid, trace in downstream.items():
            down_nodes = {node["project_node_id"] for node in trace["nodes"]}
            # Reaching a containing block is not reaching its connector.
            if (
                connector in down_nodes
                and contact_seeds[uuid] & upstream_nodes
                and connector not in contact_seeds[uuid]
            ):
                sources.append(uuid)
                contact_consumers[uuid].append(consumer.uuid)
                if len(result["connections"]) >= MAX_RESULT_RELATIONSHIPS:
                    result["connections_omitted"] += 1
                    warnings.add("max_connections")
                    continue
                result["connections"].append(
                    {
                        "contact_uuid": uuid,
                        "consumer_uuid": consumer.uuid,
                        "evidence_kind": "project_signal_path",
                        "evidence_ids": [trace["evidence_id"], upstream["evidence_id"]],
                    }
                )
        complete = upstream["complete"] and all(t["complete"] for t in downstream.values())
        complete = complete and not warnings
        if len(sources) > 1:
            append_finding(
                {
                    "finding_type": "multiple_contact_sources",
                    "contact_uuids": sources,
                    "consumer_uuids": [consumer.uuid],
                    "evidence_ids": [upstream["evidence_id"]],
                }
            )
        if not sources and complete:
            append_finding(
                {
                    "finding_type": "consumer_without_resolved_contact",
                    "contact_uuids": [],
                    "consumer_uuids": [consumer.uuid],
                    "evidence_ids": [upstream["evidence_id"]],
                },
                negative=True,
            )
        if sources and complete:
            for contact in contacts:
                uuid = contact["control_uuid"]
                if (
                    uuid not in sources
                    and controls[uuid].room_uuid is not None
                    and (controls[uuid].room_uuid == consumer.room_uuid)
                ):
                    append_finding(
                        {
                            "finding_type": "cross_assignment_review_candidate",
                            "contact_uuids": [*sources, uuid],
                            "consumer_uuids": [consumer.uuid],
                            "evidence_ids": [
                                upstream["evidence_id"],
                                downstream[uuid]["evidence_id"],
                                *(downstream[source]["evidence_id"] for source in sources),
                            ],
                        },
                        negative=True,
                    )
    result["trace_starts"] = graph.starts
    for evidence in result["evidence"]:
        warnings.update(evidence["warnings"])
    complete = not warnings
    if complete:
        for finding in negative_findings:
            append_finding(finding)
    else:
        result["findings_omitted"] += len(negative_findings)
    for contact in contacts:
        uuid = contact["control_uuid"]
        connected = contact_consumers[uuid]
        if len(connected) > 1:
            append_finding(
                {
                    "finding_type": "contact_feeds_multiple_consumers",
                    "contact_uuids": [uuid],
                    "consumer_uuids": connected,
                    "evidence_ids": [downstream[uuid]["evidence_id"]],
                }
            )
        if not connected and complete and "direct_monitor_reference" in contact["evidence_kinds"]:
            append_finding(
                {
                    "finding_type": "monitored_without_supported_consumer",
                    "contact_uuids": [uuid],
                    "consumer_uuids": [],
                    "evidence_ids": [downstream[uuid]["evidence_id"]],
                }
            )
    complete = complete and not warnings
    if not complete:
        retained_findings = [
            f
            for f in result["findings"]
            if f["finding_type"] in {"multiple_contact_sources", "contact_feeds_multiple_consumers"}
        ]
        result["findings_omitted"] += len(result["findings"]) - len(retained_findings)
        result["findings"] = retained_findings
    result["completeness"].update(
        mapping=not bool(
            warnings
            & {
                "mapping_incomplete",
                "monitor_reference_unavailable",
                "linked_control_unavailable",
                "max_contacts",
                "max_consumers",
            }
        ),
        graph=complete,
    )
    result["warnings"] = sorted(warnings)
    return result
