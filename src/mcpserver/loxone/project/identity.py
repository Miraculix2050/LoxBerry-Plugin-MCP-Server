"""Conservative cross-source identities; raw occurrences remain authoritative evidence."""

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .graph import GraphNode, ProjectGraph

SUPPORTED_TYPES = frozenset({"SysVar", "DigitalIn", "Actor", "Online", "Mode", "VoltageOut"})
Classification = Literal["single_source", "equivalent", "complementary", "ambiguous"]
Reason = Literal[
    "single_occurrence",
    "equal_topology",
    "disjoint_connectors",
    "duplicate_source",
    "type_conflict",
    "attribute_conflict",
    "topology_conflict",
    "topology_unresolved",
    "source_limit",
]


@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    classification: Classification
    reason: Reason
    candidate_node_ids: tuple[str, ...]
    candidates_omitted: int = 0


def _uuid(value: str | None) -> str | None:
    normalized = (value or "").replace("-", "").lower()
    return normalized if re.fullmatch("[0-9a-f]{32}", normalized) else None


def _attributes(node: "GraphNode") -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (key, (_uuid(value) or value) if key in {"U", "Ref"} else value)
            for key, value in node.attributes
            if key not in {"Title", "Desc"}
        )
    )


def logical_runtime_nodes(
    graph: "ProjectGraph",
    *,
    unmodeled_node_keys: frozenset[str] = frozenset(),
) -> tuple[
    tuple[tuple[str, str], ...],
    tuple[tuple[str, tuple[str, ...]], ...],
    dict[str, IdentityEvidence],
]:
    """Admit whole UUID groups only, comparing explicit connector slots and neighbors.

    Missing slots may complement another source. Different relations on an occupied
    slot are never assumed to be fan-out. Unidentified neighbors and nested blocks
    fail closed; no recursive equivalence or name matching establishes identity.
    """
    nodes = {node.key: node for node in graph.nodes}
    groups: dict[str, list[GraphNode]] = defaultdict(list)
    local_ids: dict[tuple[str, str], int] = defaultdict(int)
    parents: dict[str, list[str]] = defaultdict(list)
    children: dict[str, list[str]] = defaultdict(list)
    incident: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    unresolved = {key for key, _ in graph.unresolved} | set(unmodeled_node_keys)
    for node in graph.nodes:
        uuid = _uuid(node.source_id)
        if uuid:
            local_ids[node.project, uuid] += 1
            if node.kind == "block":
                groups[uuid].append(node)
    for edge in graph.edges:
        if edge.kind == "contains":
            parents[edge.target].append(edge.source)
            children[edge.source].append(edge.target)
        else:
            incident[edge.source].append(("out", edge.kind, edge.target))
            incident[edge.target].append(("in", edge.kind, edge.source))
    # These families have no reviewed implicit signal or state-table semantics.
    for semantic_edge in graph.semantic_edges:
        unresolved.update((semantic_edge.source, semantic_edge.target))
    unresolved.update(
        node.key
        for node in graph.nodes
        if len({name for name, _ in node.attributes}) != len(node.attributes)
    )
    reliable_groups = {
        uuid
        for uuid, members in groups.items()
        if len(members) <= 32
        and len({item.project for item in members}) == len(members)
        and len({item.block_type for item in members}) == 1
        and len({_attributes(item) for item in members}) == 1
    }
    port_counts: dict[tuple[str, str], int] = defaultdict(int)
    port_signatures: dict[tuple[str, str], set[tuple[tuple[str, str], ...]]] = defaultdict(set)
    for owner, members in children.items():
        for child in members:
            port = dict(nodes[child].attributes).get("K")
            if port is not None:
                port_counts[owner, port] += 1
                owner_uuid = _uuid(nodes[owner].source_id)
                if owner_uuid is not None:
                    port_signatures[owner_uuid, port].add(
                        tuple(pair for pair in _attributes(nodes[child]) if pair[0] != "U")
                    )

    def endpoint(key: str) -> tuple[str, ...] | None:
        node = nodes[key]
        if node.kind == "connector":
            owner_ids = parents.get(key, [])
            port = [value for name, value in node.attributes if name == "K"]
            if len(owner_ids) != 1 or len(port) != 1 or not port[0]:
                return None
            owner = nodes[owner_ids[0]]
        else:
            owner, port = node, []
        uuid = _uuid(owner.source_id)
        if not uuid or local_ids[owner.project, uuid] != 1 or not owner.block_type:
            return None
        if uuid not in reliable_groups or owner.key in unresolved:
            return None
        if port and (
            port_counts[owner.key, port[0]] != 1
            or len(port_signatures[uuid, port[0]]) != 1
            or node.key in unresolved
        ):
            return None
        return (uuid, owner.block_type, *port)

    def topology(node: "GraphNode") -> dict[str, tuple[object, ...]] | None:
        slots: dict[str, tuple[object, ...]] = {}
        members = [node.key, *children.get(node.key, ())]
        if any(key in unresolved for key in members):
            return None
        parent_ids = parents.get(node.key, [])
        if len(parent_ids) > 1:
            return None
        parent = endpoint(parent_ids[0]) if parent_ids else ()
        if parent is None:
            return None
        slots["parent"] = parent
        for key in members:
            item = nodes[key]
            if key == node.key:
                slot = "block"
            else:
                port = [value for name, value in item.attributes if name == "K"]
                if (
                    item.kind != "connector"
                    or len(port) != 1
                    or not port[0]
                    or children.get(key)
                    or parents.get(key) != [node.key]
                ):
                    return None
                slot = "connector:" + port[0]
            if slot in slots:
                return None
            relations = []
            for direction, kind, other in incident.get(key, ()):
                target = endpoint(other)
                if target is None or other in unresolved:
                    return None
                relations.append((direction, kind, target))
            # Connector UUIDs identify physical occurrences, not a logical port.
            attributes = tuple(pair for pair in _attributes(item) if pair[0] != "U")
            slots[slot] = (attributes, tuple(sorted(relations)))
        return slots

    aliases: list[tuple[str, str]] = []
    sources: list[tuple[str, tuple[str, ...]]] = []
    evidence: dict[str, IdentityEvidence] = {}
    for occurrences in groups.values():
        if not any(node.block_type in SUPPORTED_TYPES for node in occurrences):
            continue
        occurrences.sort(key=lambda node: node.key)
        classification: Classification = "ambiguous"
        reason: Reason
        if len(occurrences) > 32:
            reason = "source_limit"
        elif len({node.project for node in occurrences}) != len(occurrences) or any(
            local_ids[node.project, _uuid(node.source_id) or ""] != 1 for node in occurrences
        ):
            reason = "duplicate_source"
        elif len({node.block_type for node in occurrences}) != 1:
            reason = "type_conflict"
        elif len(occurrences) == 1:
            classification, reason = "single_source", "single_occurrence"
        elif len({_attributes(node) for node in occurrences}) != 1:
            reason = "attribute_conflict"
        else:
            topologies = [topology(node) for node in occurrences]
            if any(item is None for item in topologies):
                reason = "topology_unresolved"
            else:
                merged: dict[str, tuple[object, ...]] = {}
                conflict = False
                for slots in topologies:
                    assert slots is not None
                    for slot, value in slots.items():
                        if slot in merged and merged[slot] != value:
                            conflict = True
                        merged[slot] = value
                if conflict:
                    reason = "topology_conflict"
                else:
                    equal = all(item == topologies[0] for item in topologies)
                    classification = "equivalent" if equal else "complementary"
                    reason = "equal_topology" if equal else "disjoint_connectors"
                    canonical = occurrences[0].key
                    aliases.extend((node.key, canonical) for node in occurrences)
                    sources.append((canonical, tuple(sorted(node.project for node in occurrences))))
        item = IdentityEvidence(
            classification,
            reason,
            tuple(node.key for node in occurrences[:32]),
            max(0, len(occurrences) - 32),
        )
        evidence.update((node.key, item) for node in occurrences)
    return tuple(sorted(aliases)), tuple(sorted(sources)), evidence
