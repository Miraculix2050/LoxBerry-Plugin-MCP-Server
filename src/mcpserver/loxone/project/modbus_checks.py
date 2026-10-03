"""Static configured comparisons and direct graph observations, never bus diagnostics."""

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .graph import GraphEdge, GraphNode

Identity = tuple[str, str]
Record = dict[str, Any]
Emit = Callable[..., None]


@dataclass(frozen=True)
class SensorEvidence:
    node: GraphNode
    fields: dict[str, dict[str, object]]
    ancestors: tuple[GraphNode, ...]
    ancestry_status: str

    @property
    def identity(self) -> Identity:
        return self.node.project, self.node.key


@dataclass
class CheckResult:
    evaluated: set[Identity] = field(default_factory=set)
    reasons: set[str] = field(default_factory=set)
    summaries: list[Record] = field(default_factory=list)
    summary_omitted: int = 0
    partial: bool = False


def identity_record(identity: Identity) -> Record:
    return {"model_source_id": identity[0], "project_node_id": identity[1]}


def raw_value(sensor: SensorEvidence, name: str) -> str | None:
    evidence = sensor.fields[name]
    value = evidence["raw_value"]
    return value if evidence["evidence_status"] == "explicit" and isinstance(value, str) else None


def mapping_key(sensor: SensorEvidence) -> tuple[str, ...] | None:
    command = raw_value(sensor, "ModbusCmd")
    address = raw_value(sensor, "ModbusAddress")
    if sensor.ancestry_status != "explicit" or command not in {"3", "4"} or not address:
        return None
    # Ancestry has already passed the independent, source-local uniqueness gate.
    device = [a for a in sensor.ancestors if a.block_type == "ModbusDev"]
    transport = [a for a in sensor.ancestors if a.block_type in {"Comm485", "ModbusServer"}]
    if len(device) != 1 or len(transport) != 1:
        return None
    return sensor.node.project, transport[0].key, device[0].key, command, address


def gap(
    emit: Emit, sensor: SensorEvidence, check: str, reason: str, name: str | None = None
) -> None:
    evidence = sensor.fields.get(name or "")
    status = str(evidence["evidence_status"]) if evidence else "absent"
    emit(
        "evidence_gaps",
        "modbus_evidence_gap",
        [sensor.identity, check, reason, name],
        "Evidence is insufficient for this configured check; no dependent "
        "conclusion was evaluated.",
        node=sensor.node,
        field=name,
        status=status,
        warning=status in {"ambiguous", "invalid"},
        raw_evidence=evidence,
        extra={"blocked_check": check, "reason_code": reason},
    )


def configured_checks(
    sensors: list[SensorEvidence],
    selected: frozenset[str],
    emit: Emit,
    count: Callable[[int, bool], dict[str, object]],
    complete: bool,
    mapping_complete: bool,
    sample_limit: int,
    summary_limit: int,
) -> dict[str, CheckResult]:
    """Hash aggregation bounds work by admitted occurrences, never all pairs."""
    results = {
        name: CheckResult() for name in ("configured_register_mappings", "configured_polling")
    }
    groups: dict[tuple[str, ...], list[SensorEvidence]] = defaultdict(list)
    polling: dict[str, list[SensorEvidence]] = defaultdict(list)
    polling_status: Counter[str] = Counter()
    for sensor in sensors:
        key = mapping_key(sensor)
        if key is not None:
            groups[key].append(sensor)
            results["configured_register_mappings"].evaluated.add(sensor.identity)
        else:
            name = (
                "ModbusCmd" if raw_value(sensor, "ModbusCmd") not in {"3", "4"} else "ModbusAddress"
            )
            reason = (
                "mapping_command_unsupported"
                if name == "ModbusCmd"
                else "mapping_address_unavailable"
            )
            if sensor.ancestry_status != "explicit":
                name, reason = "", "mapping_ancestry_unresolved"
            results["configured_register_mappings"].reasons.add(reason)
            if "configured_register_mappings" in selected:
                gap(emit, sensor, "configured_register_mappings", reason, name or None)
        value = raw_value(sensor, "ModbusPollingCycle")
        status = str(sensor.fields["ModbusPollingCycle"]["evidence_status"])
        polling_status[status] += 1
        if value is not None:
            polling[value].append(sensor)
            results["configured_polling"].evaluated.add(sensor.identity)
            if key is None:
                results["configured_polling"].partial = True
                results["configured_polling"].reasons.add(
                    "polling_comparison_prerequisite_unavailable"
                )
                if "configured_polling" in selected:
                    gap(
                        emit,
                        sensor,
                        "configured_polling",
                        "polling_comparison_prerequisite_unavailable",
                    )
        else:
            results["configured_polling"].reasons.add("polling_evidence_unavailable")
            if "configured_polling" in selected:
                gap(
                    emit,
                    sensor,
                    "configured_polling",
                    "polling_evidence_unavailable",
                    "ModbusPollingCycle",
                )

    def group_extra(
        members: list[SensorEvidence],
        name: str = "ModbusAddress",
        group_complete: bool | None = None,
    ) -> Record:
        identities = [identity_record(s.identity) for s in members[:sample_limit]]
        evidence = [
            {
                **identity_record(s.identity),
                **s.fields[name],
                "semantics": "unknown",
                "rule_reference": "modbus-v1:raw-evidence",
            }
            for s in members[:sample_limit]
        ]
        return {
            "affected_occurrences": identities,
            "affected_occurrences_omitted": len(members) - len(identities),
            "source_occurrences": count(
                len(members), complete if group_complete is None else group_complete
            ),
            "evidence": evidence,
            "evidence_omitted": len(members) - len(evidence),
        }

    for key, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        common = {
            **group_extra(members, group_complete=mapping_complete),
            "configured_mapping": {
                "model_source_id": key[0],
                "transport_project_node_id": key[1],
                "device_project_node_id": key[2],
                "function_code": key[3],
                "requested_register_table": "holding_registers"
                if key[3] == "3"
                else "input_registers",
                "raw_address": key[4],
                "rule_reference": "MODBUS-Application-Protocol-V1.1b3:6.3/6.4",
            },
        }
        emit(
            "configured_register_mappings",
            "configured_mapping_repeated",
            key,
            "Multiple source occurrences configure the same raw address and "
            "requested register table "
            "under this project device; review intent.",
            classification="review_candidate",
            extra=common,
        )
        for name in ("ModbusDataType", "SourceValHigh", "DestValHigh", "ModbusPollingCycle"):
            unavailable = [s for s in members if raw_value(s, name) is None]
            if unavailable:
                results["configured_register_mappings"].partial = True
                results["configured_register_mappings"].reasons.add(
                    "mapping_attribute_evidence_incomplete"
                )
                if "configured_register_mappings" in selected:
                    for sensor in unavailable:
                        gap(
                            emit,
                            sensor,
                            "configured_register_mappings",
                            "mapping_attribute_evidence_incomplete",
                            name,
                        )
            values = sorted({value for s in members if (value := raw_value(s, name)) is not None})
            if len(values) > 1:
                extra = {
                    **common,
                    **group_extra(members, name, mapping_complete),
                    "comparison_field": name,
                    "raw_variants": values[:sample_limit],
                    "raw_variants_omitted": max(0, len(values) - sample_limit),
                }
                emit(
                    "configured_register_mappings",
                    "configured_mapping_attributes_differ",
                    [key, name, values],
                    "Comparable configured mappings contain different explicit raw attributes; "
                    "review intent. No device incompatibility or overlap was evaluated.",
                    classification="review_candidate",
                    extra=extra,
                )
                if name == "ModbusPollingCycle":
                    emit(
                        "configured_polling",
                        "configured_polling_values_differ",
                        [key, values],
                        "Comparable configured mappings contain different explicit "
                        "polling values; review intent. "
                        "Units, achieved rates and bus load remain unknown.",
                        classification="review_candidate",
                        extra={**extra, "polling_unit": "unknown"},
                    )

    for value, members in sorted(polling.items()):
        emit(
            "configured_polling",
            "configured_polling_summary",
            [value],
            "Source occurrences configure this explicit raw polling value; "
            "unit and runtime behavior remain unknown.",
            classification="fact",
            extra={
                **group_extra(members, "ModbusPollingCycle"),
                "raw_variants": [value],
                "polling_unit": "unknown",
            },
        )
    mapping = results["configured_register_mappings"]
    mapping.summaries = [
        {"key": "comparable_occurrences", "count": count(len(mapping.evaluated), mapping_complete)}
    ]
    poll = results["configured_polling"]
    buckets = [
        {
            "key": "explicit_polling",
            "raw_value": value,
            "polling_unit": "unknown",
            "count": count(len(members), complete),
        }
        for value, members in sorted(polling.items())
    ]
    buckets += [
        {"key": "polling_" + status, "count": count(polling_status[status], complete)}
        for status in ("absent", "ambiguous", "invalid")
    ]
    poll.summaries = buckets[:summary_limit]
    poll.summary_omitted = max(0, len(buckets) - summary_limit)
    return results


def direct_check(
    sensors: list[SensorEvidence],
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    unresolved: list[tuple[str, str]],
    relationships_complete: bool,
    unresolved_complete: bool,
    emit: Emit,
    count: Callable[[int, bool], dict[str, object]],
    complete: bool,
    connector_limit: int,
    sample_limit: int,
) -> CheckResult:
    """Observe only explicit source-local connector signal edges and unique owners."""
    result = CheckResult()
    parents: dict[str, list[str]] = defaultdict(list)
    children: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[GraphEdge]] = defaultdict(list)
    for edge in edges:
        if edge.kind == "contains":
            parents[edge.target].append(edge.source)
            children[edge.source].append(edge.target)
        elif edge.kind in {"signal", "reference"}:
            outgoing[edge.source].append(edge)
    unknown_signal_sources = [
        (key, reason) for key, reason in unresolved if reason == "signal_unresolved"
    ]
    unresolved_nodes = {key for key, _ in unresolved}
    if sensors and unknown_signal_sources:
        result.reasons.add("unresolved_signal_source_not_attributable")
        result.partial = True
        targets = [
            identity_record((nodes[key].project, key))
            for key, _ in unknown_signal_sources
            if key in nodes
        ]
        emit(
            "direct_consumers",
            "direct_graph_gap",
            ["unresolved_signal_source_not_attributable"],
            "Unresolved signal sources cannot be attributed to an endpoint; "
            "absence of additional consumers is unknown.",
            warning=True,
            extra={
                "reason_code": "unresolved_signal_source_not_attributable",
                "affected_occurrences": targets[:sample_limit],
                "affected_occurrences_omitted": max(0, len(targets) - sample_limit),
            },
        )
    total_edges = 0
    for sensor in sensors:
        connector_ids = sorted(
            {
                key
                for key in children.get(sensor.node.key, [])
                if key in nodes and nodes[key].kind == "connector"
            }
        )
        omitted = max(0, len(connector_ids) - connector_limit)
        connector_ids = connector_ids[:connector_limit]
        reasons: set[str] = set()
        if not connector_ids:
            reasons.add("sensor_connectors_absent")
        if omitted:
            reasons.add("max_connectors")
        if not relationships_complete:
            reasons.add("max_relationships")
        if not unresolved_complete:
            reasons.add("max_relationships")
            reasons.add("unresolved_relationships_truncated")
        labels: Counter[str] = Counter()
        for key in connector_ids:
            values = {value for name, value in nodes[key].attributes if name == "K"}
            if len(values) == 1:
                labels.update(values)
            elif len(values) > 1:
                reasons.add("ambiguous_connector_key")
        if any(n > 1 for n in labels.values()):
            reasons.add("duplicate_connector_key")
        observed_edges: list[Record] = []
        consumer_ids: set[Identity] = set()
        edge_count = 0
        reference_count = sum(e.kind == "reference" for e in outgoing.get(sensor.node.key, []))
        for source in connector_ids:
            source_node = nodes[source]
            if parents[source] != [sensor.node.key] or source_node.project != sensor.node.project:
                reasons.add("source_connector_owner_ambiguous")
                continue
            for edge in outgoing.get(source, []):
                if edge.kind == "reference":
                    reference_count += 1
                    continue
                target = nodes.get(edge.target)
                owner_ids = parents.get(edge.target, [])
                if not relationships_complete:
                    continue  # A partial index cannot establish unique ownership.
                if (
                    target is None
                    or target.kind != "connector"
                    or target.project != sensor.node.project
                ):
                    reasons.add("target_connector_unresolved")
                    continue
                if len(owner_ids) != 1 or owner_ids[0] not in nodes:
                    reasons.add("target_owner_ambiguous")
                    continue
                owner = nodes[owner_ids[0]]
                if owner.kind != "block" or owner.project != sensor.node.project:
                    reasons.add("target_owner_unresolved")
                    continue
                edge_count += 1
                consumer_ids.add((owner.project, owner.key))
                if len(observed_edges) < sample_limit:
                    observed_edges.append(
                        {
                            "model_source_id": sensor.node.project,
                            "source_connector_project_node_id": source,
                            "target_connector_project_node_id": target.key,
                            "consumer_project_node_id": owner.key,
                        }
                    )
        if connector_ids and relationships_complete:
            result.evaluated.add(sensor.identity)
        if reference_count:
            reasons.add("reference_is_not_direct_signal")
        local_unresolved = (
            bool(unresolved_nodes.intersection(connector_ids))
            or sensor.node.key in unresolved_nodes
        )
        if local_unresolved:
            reasons.add("endpoint_reference_unresolved")
        slice_complete = (
            not (reasons - {"reference_is_not_direct_signal"}) and not unknown_signal_sources
        )
        result.partial |= not slice_complete
        result.reasons.update(reasons)
        total_edges += edge_count
        extra = {
            "direct_edge_count": count(edge_count, complete and slice_complete),
            "consumer_occurrence_count": count(len(consumer_ids), complete and slice_complete),
            "direct_edges": observed_edges,
            "direct_edges_omitted": max(0, edge_count - len(observed_edges)),
            "consumer_occurrences": [
                identity_record(i) for i in sorted(consumer_ids)[:sample_limit]
            ],
            "consumer_occurrences_omitted": max(0, len(consumer_ids) - sample_limit),
            "connectors_inspected": count(
                len(connector_ids), relationships_complete and not omitted
            ),
            "connectors_omitted": omitted if relationships_complete else None,
            "reference_edge_count": count(
                reference_count, complete and relationships_complete and not omitted
            ),
            "direct_slice_complete": slice_complete and complete,
        }
        emit(
            "direct_consumers",
            "direct_consumer_summary" if edge_count else "no_direct_consumer_observed",
            sensor.identity,
            "Direct configured signal consumer relationships were observed in "
            "the inspected connectors."
            if edge_count
            else "No direct configured signal consumer was observed in the "
            "inspected endpoint connectors; "
            "indirect or unmodeled use is not excluded.",
            node=sensor.node,
            classification="fact",
            extra=extra,
        )
        for reason in sorted(reasons):
            warning = reason in {
                "ambiguous_connector_key",
                "duplicate_connector_key",
                "source_connector_owner_ambiguous",
                "target_connector_unresolved",
                "target_owner_ambiguous",
                "target_owner_unresolved",
                "endpoint_reference_unresolved",
            }
            emit(
                "direct_consumers",
                "direct_graph_gap",
                [sensor.identity, reason],
                "Direct configured evidence is incomplete or separate from signal "
                "edges; no non-use or fault conclusion was evaluated.",
                node=sensor.node,
                warning=warning,
                extra={"reason_code": reason},
            )
            gap(emit, sensor, "direct_consumers", reason)
    result.summaries = [
        {"key": "direct_signal_edges", "count": count(total_edges, complete and not result.partial)}
    ]
    return result
