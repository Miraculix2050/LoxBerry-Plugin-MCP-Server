"""Internal Modbus V1 foundation; public activation requires all five checks.

Only static source occurrences are inspected. No device identity, register width,
defaults, traffic, runtime values or physical installation coverage is inferred.
"""

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .graph import GraphNode
from .mapping import ProjectView
from .modbus import FIELDS, raw_fields

MODBUS_ANALYSIS_VERSION: Literal[1] = 1
MODBUS_ANALYSES = (
    "inventory",
    "configured_register_mappings",
    "direct_consumers",
    "configured_polling",
    "evidence_gaps",
)
IMPLEMENTED_ANALYSES = frozenset({"inventory", "evidence_gaps"})
ModbusAnalysis = Literal[
    "inventory",
    "configured_register_mappings",
    "direct_consumers",
    "configured_polling",
    "evidence_gaps",
]
TruncationReason = Literal[
    "max_candidate_nodes",
    "max_sensor_occurrences",
    "max_relationships",
    "max_ancestry_depth",
    "max_connectors",
    "max_findings",
    "max_summary_groups",
    "max_evidence_records",
    "max_raw_value_bytes",
]
AncestryClass = Literal[
    "modbus_server_ancestry",
    "comm485_ancestry",
    "other_or_unresolved",
    "observed_hierarchy_node",
    "unsupported_occurrences",
    "unresolved_candidate_occurrences",
]


class ProjectModbusCountData(BaseModel):
    value: int = Field(ge=0)
    count_kind: Literal["exact", "lower_bound"] = "exact"


class ProjectModbusCheckStatusData(BaseModel):
    status: Literal["complete", "partial", "blocked"]
    eligible_occurrences: ProjectModbusCountData
    evaluated_occurrences: ProjectModbusCountData
    excluded_occurrences: ProjectModbusCountData
    reason_codes: list[str]
    omitted_count: int | None = Field(default=None, ge=0)


class ProjectModbusCoverageData(BaseModel):
    sensor_source_occurrences: ProjectModbusCountData
    supported_sensor_occurrences: ProjectModbusCountData
    evaluated_sensor_occurrences: ProjectModbusCountData
    actor_source_occurrences: ProjectModbusCountData
    unsupported_occurrences: ProjectModbusCountData
    unresolved_candidate_occurrences: ProjectModbusCountData
    project_device_nodes: ProjectModbusCountData
    hierarchy_unresolved_occurrences: ProjectModbusCountData
    field_status_counts: dict[
        Literal["explicit", "absent", "ambiguous", "invalid"], ProjectModbusCountData
    ]
    graph_gap_counts: dict[
        Literal["absent", "ambiguous", "invalid", "max_ancestry_depth", "max_relationships"],
        ProjectModbusCountData,
    ]
    check_exclusions: dict[ModbusAnalysis, ProjectModbusCountData]
    transport_dimensions: dict[
        Literal["modbus_server_ancestry", "comm485_ancestry", "other_or_unresolved"],
        ProjectModbusCountData,
    ]
    source_ingestion_complete: bool
    candidate_scan_complete: bool
    supported_type_coverage_complete: bool
    presentation_complete: bool
    installation_coverage: Literal["unknown"] = "unknown"


class ProjectModbusSourceTypeData(BaseModel):
    source_type: str = Field(max_length=100)
    source_type_truncated: bool
    source_occurrences: ProjectModbusCountData
    supported_sensor_occurrences: ProjectModbusCountData
    unsupported_occurrences: ProjectModbusCountData
    unresolved_candidate_occurrences: ProjectModbusCountData


class ProjectModbusOccurrenceIdentityData(BaseModel):
    model_source_id: str
    project_node_id: str


class ProjectModbusRawOccurrenceData(BaseModel):
    raw_value: str | None = Field(max_length=64)
    invalid: bool


class ProjectModbusEvidenceData(ProjectModbusOccurrenceIdentityData):
    source_field: str | None = None
    raw_value: str | None = Field(default=None, max_length=200)
    evidence_status: Literal["explicit", "absent", "ambiguous", "invalid"]
    semantics: Literal["proven", "unknown"] = "unknown"
    rule_reference: str
    occurrences: list[ProjectModbusRawOccurrenceData] = Field(default_factory=list, max_length=8)
    occurrences_omitted: int = Field(default=0, ge=0)


class ProjectModbusFindingData(BaseModel):
    finding_id: str
    analysis: ModbusAnalysis
    finding_type: Literal[
        "modbus_inventory",
        "modbus_evidence_gap",
        "configured_mapping_repeated",
        "configured_mapping_attributes_differ",
        "direct_consumer_summary",
        "no_direct_consumer_observed",
        "direct_graph_gap",
        "configured_polling_summary",
        "configured_polling_values_differ",
    ]
    severity: Literal["info", "warning"]
    classification: Literal["fact", "review_candidate", "evidence_gap"]
    description: str = Field(max_length=500)
    evidence: list[ProjectModbusEvidenceData] = Field(max_length=20)
    affected_occurrences: list[ProjectModbusOccurrenceIdentityData] = Field(max_length=20)
    affected_occurrences_omitted: int = Field(ge=0)
    evidence_omitted: int = Field(ge=0)
    source_type: str | None = Field(default=None, max_length=100)
    source_type_truncated: bool = False
    ancestry_class: AncestryClass | None = None
    source_occurrences: ProjectModbusCountData | None = None


class ProjectModbusSummaryData(BaseModel):
    key: str = Field(max_length=100)
    count: ProjectModbusCountData
    source_type: str | None = Field(default=None, max_length=100)
    source_type_truncated: bool = False
    ancestry_class: AncestryClass | None = None


class ProjectModbusLimitationData(BaseModel):
    reason_code: str
    description: str = Field(max_length=500)
    rule_reference: str


class ProjectModbusModelSourceData(BaseModel):
    model_source_id: str
    element_count: int = Field(ge=0)
    anomaly_codes: list[str]
    anomaly_codes_omitted: int = Field(ge=0)


class ProjectModbusSourceDiagnosticData(BaseModel):
    code: str
    count: int = Field(ge=0)
    source_type: str | None
    attribute_name: str | None
    value_shape: str | None
    length_bucket: str | None
    sample_node_ids: list[str] = Field(max_length=3)
    sample_omitted: int = Field(ge=0)


class ProjectModbusSourceDiagnosticsData(BaseModel):
    entries: list[ProjectModbusSourceDiagnosticData] = Field(max_length=50)
    complete: bool
    groups_omitted: int = Field(ge=0)
    labels_truncated: bool


class ProjectModbusAnalysisData(BaseModel):
    analysis_version: Literal[1] = MODBUS_ANALYSIS_VERSION
    project_fingerprint: str
    model_version: int
    scope: Literal["modbus"] = "modbus"
    analyses: list[ModbusAnalysis]
    coverage: ProjectModbusCoverageData
    coverage_by_source_type: list[ProjectModbusSourceTypeData] = Field(max_length=50)
    source_types_omitted: int = Field(ge=0)
    summaries: dict[ModbusAnalysis, Annotated[list[ProjectModbusSummaryData], Field(max_length=50)]]
    summaries_omitted: dict[ModbusAnalysis, Annotated[int, Field(ge=0)]]
    check_status: dict[ModbusAnalysis, ProjectModbusCheckStatusData]
    limitations: list[ProjectModbusLimitationData]
    model_sources: list[ProjectModbusModelSourceData] = Field(max_length=32)
    model_sources_omitted: int = Field(ge=0)
    source_diagnostics: ProjectModbusSourceDiagnosticsData
    findings: list[ProjectModbusFindingData] = Field(max_length=10_000)
    next_cursor: str | None = None
    analysis_truncated: bool
    truncation_reasons: list[TruncationReason]
    page_truncated: bool = False
    page_truncation_reason: Literal["max_response_bytes"] | None = None


@dataclass(frozen=True)
class ModbusLimits:
    candidate_nodes: int = 100_000
    sensor_occurrences: int = 10_000
    relationships: int = 100_000
    ancestry_depth: int = 32
    findings_per_check: int = 2_000
    summary_groups: int = 50
    evidence_records: int = 20


DEFAULT_MODBUS_LIMITS = ModbusLimits()


def validate_modbus_selection(analyses: list[str] | None) -> frozenset[str]:
    """The final selection contract; never silently narrow its default."""
    selected = frozenset(MODBUS_ANALYSES if analyses is None else analyses)
    if not selected or (analyses is not None and len(selected) != len(analyses)):
        raise ValueError("analyses must be a non-empty unique list")
    if not selected <= frozenset(MODBUS_ANALYSES):
        raise ValueError("analyses do not belong to the selected scope")
    return selected


def require_implemented(analyses: frozenset[str]) -> None:
    validate_modbus_selection(list(analyses))
    if not analyses <= IMPLEMENTED_ANALYSES:
        raise ValueError("Modbus analysis is not yet implemented; public activation is deferred")


def occurrence_identity(node: GraphNode) -> tuple[str, str]:
    return node.project, node.key


def finding_id(analysis: str, finding_type: str, basis: object) -> str:
    canonical = json.dumps(
        ["modbus-v1", analysis, finding_type, basis],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "modbus:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def exact_source_type(node: GraphNode) -> str | None:
    values = {value for field, value in node.attributes if field == "Type"}
    return next(iter(values)) if len(values) == 1 else None


def source_type_status(node: GraphNode) -> str:
    values = {value for field, value in node.attributes if field == "Type"}
    return "absent" if not values else "explicit" if len(values) == 1 else "ambiguous"


def resolve_ancestry(
    node: GraphNode,
    nodes: dict[str, GraphNode],
    parents: dict[str, list[str]],
    depth: int,
) -> tuple[list[GraphNode], str]:
    """Resolve observed hierarchy only, retaining ambiguous/cyclic evidence gaps."""
    ancestors: list[GraphNode] = []
    seen = {node.key}
    current = node
    for _ in range(depth):
        candidates = parents.get(current.key, [])
        if not candidates:
            return ancestors, "explicit" if ancestors else "absent"
        if len(candidates) != 1:
            return ancestors, "ambiguous"
        parent = nodes.get(candidates[0])
        if parent is None or parent.key in seen or parent.project != node.project:
            return ancestors, "invalid"
        seen.add(parent.key)
        if exact_source_type(parent) not in {"ModbusDev", "ModbusServer", "Comm485"}:
            return ancestors, "explicit" if ancestors else "absent"
        ancestors.append(parent)
        current = parent
    return ancestors, "max_ancestry_depth" if parents.get(current.key) else "explicit"


def analyze_modbus(
    view: ProjectView,
    analyses: frozenset[str],
    *,
    limits: ModbusLimits = DEFAULT_MODBUS_LIMITS,
) -> dict[str, object]:
    require_implemented(analyses)
    graph = view.snapshot.graph
    diagnostics = view.snapshot.source_diagnostics
    reasons: set[str] = set()
    counters: Counter[str] = Counter()
    types: dict[str, Counter[str]] = defaultdict(Counter)
    field_counts: Counter[str] = Counter()
    gaps: Counter[str] = Counter()
    transport: Counter[str] = Counter()
    device_nodes: set[tuple[str, str]] = set()
    hierarchy_nodes: set[tuple[str, str]] = set()
    inspected_ancestor_fields: set[tuple[str, str]] = set()
    inventory_counts: Counter[tuple[str, str]] = Counter()
    inventory_samples: dict[tuple[str, str], list[GraphNode]] = defaultdict(list)

    def observe_inventory(node: GraphNode, source_type: str, ancestry_class: str) -> None:
        key = (source_type, ancestry_class)
        inventory_counts[key] += 1
        if len(inventory_samples[key]) < limits.evidence_records:
            inventory_samples[key].append(node)

    # Relationship indexes are bounded before construction. A partial index must
    # never establish that a node has a unique parent or no parent.
    nodes = {node.key: node for node in graph.nodes}
    parents: dict[str, list[str]] = defaultdict(list)
    relationships = 0
    relationships_complete = True
    for edge in graph.edges:
        if edge.kind != "contains":
            continue
        if relationships == limits.relationships:
            relationships_complete = False
            reasons.add("max_relationships")
            break
        parents[edge.target].append(edge.source)
        relationships += 1
    # A quota bounds construction and samples, independently for every check.
    findings: dict[str, list[tuple[str, dict[str, object]]]] = {
        analysis: [] for analysis in analyses
    }
    findings_omitted: Counter[str] = Counter()

    def emit(
        analysis: str,
        kind: str,
        basis: object,
        description: str,
        *,
        node: GraphNode | None = None,
        field: str | None = None,
        status: str = "absent",
        raw: str | None = None,
        warning: bool = False,
        classification: str = "evidence_gap",
        raw_evidence: dict[str, object] | None = None,
    ) -> None:
        if analysis not in analyses:
            return
        if len(findings[analysis]) >= limits.findings_per_check:
            findings_omitted[analysis] += 1
            reasons.add("max_findings")
            return
        identity = {"model_source_id": node.project, "project_node_id": node.key} if node else None
        evidence: list[dict[str, object]] = (
            []
            if identity is None
            else [
                {
                    **identity,
                    "source_field": field,
                    "raw_value": raw,
                    "evidence_status": status,
                    "semantics": "unknown",
                    "rule_reference": "modbus-v1:raw-evidence",
                }
            ]
        )
        if evidence and raw_evidence is not None:
            evidence[0]["occurrences"] = raw_evidence["occurrences"]
            evidence[0]["occurrences_omitted"] = raw_evidence["occurrences_omitted"]
        if evidence and raw_evidence is not None and raw_evidence["occurrences_omitted"]:
            reasons.add("max_evidence_records")
        findings[analysis].append(
            (
                json.dumps(basis, sort_keys=True, ensure_ascii=False),
                {
                    "finding_id": finding_id(analysis, kind, basis),
                    "analysis": analysis,
                    "finding_type": kind,
                    "severity": "warning" if warning else "info",
                    "classification": classification,
                    "description": description,
                    "evidence": evidence,
                    "affected_occurrences": [] if identity is None else [identity],
                    "affected_occurrences_omitted": 0,
                    "evidence_omitted": 0,
                },
            )
        )

    scanned = 0
    evaluated = 0
    scan_complete = True
    for node in sorted(graph.nodes, key=occurrence_identity):
        if node.kind != "block":
            continue
        if scanned == limits.candidate_nodes:
            scan_complete = False
            reasons.add("max_candidate_nodes")
            break
        scanned += 1
        source_type = exact_source_type(node)
        markers = any(key in FIELDS["ModbusASensor"] for key, _ in node.attributes)
        category = None
        if source_type == "ModbusASensor":
            category = "supported_sensor_occurrences"
        elif source_type in {"ModbusDev", "ModbusServer"}:
            category = "hierarchy"
        elif source_type and source_type.startswith("Modbus"):
            category = "unsupported_occurrences"
        elif markers:
            category = "unresolved_candidate_occurrences"
        if category is None:
            continue
        type_key = source_type or "unresolved_type"
        types[type_key]["source_occurrences"] += 1
        if category != "hierarchy":
            types[type_key][category] += 1
            counters[category] += 1
        if source_type == "ModbusAActor":
            counters["actor_source_occurrences"] += 1
        if category == "hierarchy":
            hierarchy_nodes.add(occurrence_identity(node))
            observe_inventory(node, type_key, "observed_hierarchy_node")
            if source_type == "ModbusDev":
                device_nodes.add(occurrence_identity(node))
            continue
        if category != "supported_sensor_occurrences":
            observe_inventory(node, type_key, category)
            emit(
                "evidence_gaps",
                "modbus_evidence_gap",
                [occurrence_identity(node), category],
                "Source occurrence is unsupported or has unresolved type evidence; "
                "no endpoint conclusion was evaluated.",
                node=node,
                field="Type",
                status=source_type_status(node),
                warning=source_type_status(node) == "ambiguous",
            )
            continue
        if evaluated == limits.sensor_occurrences:
            reasons.add("max_sensor_occurrences")
            observe_inventory(node, type_key, "other_or_unresolved")
            continue
        evaluated += 1
        for evidence in raw_fields(node):
            field_status = str(evidence["evidence_status"])
            field_counts[field_status] += 1
            if field_status != "explicit":
                emit(
                    "evidence_gaps",
                    "modbus_evidence_gap",
                    [occurrence_identity(node), evidence["source_field"], field_status],
                    "Raw field evidence is insufficient; "
                    "no device parameter validity conclusion was evaluated.",
                    node=node,
                    field=str(evidence["source_field"]),
                    status=field_status,
                    warning=field_status in {"ambiguous", "invalid"},
                    raw_evidence=evidence,
                )
        ancestors: list[GraphNode]
        if not relationships_complete:
            ancestors, ancestry_status = [], "max_relationships"
        else:
            ancestors, ancestry_status = resolve_ancestry(
                node, nodes, parents, limits.ancestry_depth
            )
        for ancestor in ancestors:
            identity = occurrence_identity(ancestor)
            if identity in inspected_ancestor_fields:
                continue
            inspected_ancestor_fields.add(identity)
            if exact_source_type(ancestor) == "Comm485":
                types["Comm485"]["source_occurrences"] += 1
                observe_inventory(ancestor, "Comm485", "observed_hierarchy_node")
            for ancestor_evidence in raw_fields(ancestor):
                ancestor_status = str(ancestor_evidence["evidence_status"])
                field_counts[ancestor_status] += 1
                if ancestor_status != "explicit":
                    emit(
                        "evidence_gaps",
                        "modbus_evidence_gap",
                        [identity, ancestor_evidence["source_field"], ancestor_status],
                        "Ancestor raw field evidence is insufficient; "
                        "no physical unit or transport parameter validity was evaluated.",
                        node=ancestor,
                        field=str(ancestor_evidence["source_field"]),
                        status=ancestor_status,
                        warning=ancestor_status in {"ambiguous", "invalid"},
                        raw_evidence=ancestor_evidence,
                    )
        if ancestry_status in {"explicit", "absent"}:
            ancestor_types = [exact_source_type(a) for a in ancestors]
            hierarchy_resolved = (
                ancestor_types.count("ModbusDev") == 1
                and sum(t in {"ModbusServer", "Comm485"} for t in ancestor_types) == 1
            )
            if not hierarchy_resolved:
                ancestry_status = "absent" if not ancestors else "ambiguous"
        if ancestry_status != "explicit":
            counters["hierarchy_unresolved_occurrences"] += 1
            gaps[ancestry_status] += 1
            transport["other_or_unresolved"] += 1
            observe_inventory(node, type_key, "other_or_unresolved")
            if ancestry_status == "max_ancestry_depth":
                reasons.add(ancestry_status)
            emit(
                "evidence_gaps",
                "modbus_evidence_gap",
                [occurrence_identity(node), "ancestry", ancestry_status],
                "Project ancestry is unresolved or bounded; "
                "physical identity and transport semantics remain unknown.",
                node=node,
                status="ambiguous"
                if ancestry_status == "ambiguous"
                else "invalid"
                if ancestry_status == "invalid"
                else "absent",
                warning=ancestry_status in {"ambiguous", "invalid"},
            )
        else:
            dimension = (
                "modbus_server_ancestry"
                if any(exact_source_type(a) == "ModbusServer" for a in ancestors)
                else "comm485_ancestry"
            )
            transport[dimension] += 1
            observe_inventory(node, type_key, dimension)
    ingestion_complete = view.snapshot.source_ingestion_complete
    domain_complete = scan_complete and ingestion_complete
    sensor_complete = domain_complete and "max_sensor_occurrences" not in reasons
    field_complete = (
        sensor_complete
        and relationships_complete
        and "max_ancestry_depth" not in reasons
        and not gaps["ambiguous"]
        and not gaps["invalid"]
    )

    def count(value: int, complete: bool = domain_complete) -> dict[str, object]:
        return {"value": value, "count_kind": "exact" if complete else "lower_bound"}

    type_records: list[dict[str, object]] = []
    for source_type, values in sorted(types.items()):
        if len(type_records) == limits.summary_groups:
            reasons.add("max_summary_groups")
            break
        if len(source_type) > 100:
            reasons.add("max_raw_value_bytes")
        type_records.append(
            {
                "source_type": source_type[:100],
                "source_type_truncated": len(source_type) > 100,
                **{
                    key: count(
                        values[key],
                        domain_complete and (source_type != "Comm485" or field_complete),
                    )
                    for key in (
                        "source_occurrences",
                        "supported_sensor_occurrences",
                        "unsupported_occurrences",
                        "unresolved_candidate_occurrences",
                    )
                },
            }
        )
    type_omitted = max(0, len(types) - len(type_records))
    for basis, total in sorted(inventory_counts.items()):
        samples = inventory_samples[basis]
        previous = len(findings.get("inventory", []))
        emit(
            "inventory",
            "modbus_inventory",
            basis,
            f"Observed {total} source occurrences in this source-type/ancestry class "
            "in the inspected model sources.",
            classification="fact",
        )
        if len(findings.get("inventory", [])) > previous:
            item = findings["inventory"][-1][1]
            item["source_type"] = basis[0][:100]
            item["source_type_truncated"] = len(basis[0]) > 100
            item["ancestry_class"] = basis[1]
            item["source_occurrences"] = count(
                total, domain_complete and (basis[0] != "Comm485" or field_complete)
            )
            item["affected_occurrences"] = [
                {"model_source_id": n.project, "project_node_id": n.key} for n in samples
            ]
            item["affected_occurrences_omitted"] = total - len(samples)
            item["evidence"] = [
                {
                    "model_source_id": n.project,
                    "project_node_id": n.key,
                    "source_field": "Type",
                    "raw_value": None,
                    "evidence_status": source_type_status(n),
                    "semantics": "proven" if exact_source_type(n) else "unknown",
                    "rule_reference": "modbus-v1:exact-type-and-observed-ancestry",
                }
                for n in samples
            ]
            item["evidence_omitted"] = total - len(samples)
            if total > len(samples):
                reasons.add("max_evidence_records")
    uninspected_hierarchy = hierarchy_nodes - inspected_ancestor_fields
    for identity in sorted(uninspected_hierarchy):
        emit(
            "evidence_gaps",
            "modbus_evidence_gap",
            [identity, "hierarchy_fields_not_inspected"],
            "Hierarchy raw fields were not inspected because this occurrence was not "
            "observed in an evaluated sensor ancestry; no device conclusion was evaluated.",
            node=nodes[identity[1]],
            field="Type",
            status="explicit",
        )
    if types:
        emit(
            "evidence_gaps",
            "modbus_evidence_gap",
            ["deferred_semantics"],
            "Register width, overlap, datatype, byte order, defaults, physical unit identity, "
            "device validity and runtime behavior were not evaluated.",
        )
    source_diagnostic_records = []
    for diagnostic in diagnostics.entries[:50]:
        record = asdict(diagnostic)
        record["sample_node_ids"] = list(diagnostic.sample_node_ids[:3])
        record["sample_omitted"] = diagnostic.sample_omitted + max(
            0, len(diagnostic.sample_node_ids) - 3
        )
        source_diagnostic_records.append(record)
    diagnostic_omitted = diagnostics.groups_omitted + max(0, len(diagnostics.entries) - 50)
    if diagnostic_omitted:
        reasons.add("max_summary_groups")
    statuses = {}
    summaries = {}
    omissions = {}
    for analysis in MODBUS_ANALYSES:
        if analysis not in analyses:
            continue
        excluded = counters["supported_sensor_occurrences"] - evaluated
        if analysis == "evidence_gaps":
            excluded += len(uninspected_hierarchy)
        partial = (
            bool(excluded)
            or not domain_complete
            or not sensor_complete
            or bool(findings_omitted[analysis])
            or "max_relationships" in reasons
            or "max_ancestry_depth" in reasons
        )
        eligible = sum(inventory_counts.values())
        statuses[analysis] = {
            "status": "partial" if partial else "complete",
            "eligible_occurrences": count(eligible, domain_complete and field_complete),
            "evaluated_occurrences": count(eligible - excluded, domain_complete and field_complete),
            "excluded_occurrences": count(excluded),
            "reason_codes": sorted(
                reasons
                | ({"source_ingestion_incomplete"} if not ingestion_complete else set())
                | (
                    {"hierarchy_fields_not_inspected"}
                    if analysis == "evidence_gaps" and uninspected_hierarchy
                    else set()
                )
            ),
            "omitted_count": findings_omitted[analysis] if domain_complete else None,
        }
        if analysis == "inventory":
            summaries[analysis] = [
                {
                    "key": "source_occurrences",
                    "source_type": basis[0][:100],
                    "source_type_truncated": len(basis[0]) > 100,
                    "ancestry_class": basis[1],
                    "count": count(
                        total, domain_complete and (basis[0] != "Comm485" or field_complete)
                    ),
                }
                for basis, total in sorted(inventory_counts.items())[: limits.summary_groups]
            ]
            omissions[analysis] = max(0, len(inventory_counts) - limits.summary_groups)
            if omissions[analysis]:
                reasons.add("max_summary_groups")
        else:
            summaries[analysis] = [
                {"key": "raw_field_" + key, "count": count(field_counts[key], field_complete)}
                for key in ("absent", "ambiguous", "invalid")
            ]
            omissions[analysis] = 0
    model_sources = [
        {
            "model_source_id": part.namespace,
            "element_count": part.element_count,
            "anomaly_codes": list(part.anomaly_codes[:20]),
            "anomaly_codes_omitted": max(0, len(part.anomaly_codes) - 20),
        }
        for part in view.snapshot.projects[:32]
    ]
    if len(view.snapshot.projects) > 32:
        reasons.add("max_summary_groups")
    presentation_complete = not reasons.intersection(
        {"max_findings", "max_summary_groups", "max_evidence_records", "max_raw_value_bytes"}
    )
    output = {
        "analysis_version": MODBUS_ANALYSIS_VERSION,
        "scope": "modbus",
        "project_fingerprint": view.snapshot.fingerprint,
        "model_version": view.snapshot.model_version,
        "analyses": [a for a in MODBUS_ANALYSES if a in analyses],
        "coverage": {
            "sensor_source_occurrences": count(counters["supported_sensor_occurrences"]),
            "supported_sensor_occurrences": count(counters["supported_sensor_occurrences"]),
            "evaluated_sensor_occurrences": (
                count(evaluated, sensor_complete) if "inventory" in analyses else count(0, True)
            ),
            **{
                key: count(counters[key])
                for key in (
                    "actor_source_occurrences",
                    "unsupported_occurrences",
                    "unresolved_candidate_occurrences",
                )
            },
            "project_device_nodes": count(len(device_nodes)),
            "hierarchy_unresolved_occurrences": count(
                counters["hierarchy_unresolved_occurrences"], sensor_complete
            ),
            "field_status_counts": {
                key: count(field_counts[key], field_complete)
                for key in ("explicit", "absent", "ambiguous", "invalid")
            },
            "graph_gap_counts": {
                key: count(gaps[key], sensor_complete)
                for key in (
                    "absent",
                    "ambiguous",
                    "invalid",
                    "max_ancestry_depth",
                    "max_relationships",
                )
            },
            "check_exclusions": {a: statuses[a]["excluded_occurrences"] for a in analyses},
            "transport_dimensions": {
                key: count(transport[key], sensor_complete)
                for key in ("modbus_server_ancestry", "comm485_ancestry", "other_or_unresolved")
            },
            "source_ingestion_complete": ingestion_complete,
            "candidate_scan_complete": scan_complete,
            "supported_type_coverage_complete": domain_complete
            and not counters["unsupported_occurrences"]
            and not counters["unresolved_candidate_occurrences"],
            "presentation_complete": presentation_complete,
            "installation_coverage": "unknown",
        },
        "coverage_by_source_type": type_records,
        "source_types_omitted": type_omitted,
        "summaries": summaries,
        "summaries_omitted": omissions,
        "check_status": statuses,
        "limitations": [
            {
                "reason_code": "deferred_semantics",
                "description": "Static source evidence does not establish installation "
                "completeness, device validity or runtime behavior.",
                "rule_reference": "issue-354:section-7",
            }
        ],
        "model_sources": model_sources,
        "model_sources_omitted": max(0, len(view.snapshot.projects) - 32),
        "source_diagnostics": {
            "entries": source_diagnostic_records,
            "complete": diagnostics.complete and not diagnostic_omitted,
            "groups_omitted": diagnostic_omitted,
            "labels_truncated": diagnostics.labels_truncated,
        },
        "findings": [
            item
            for analysis in MODBUS_ANALYSES
            if analysis in findings
            for _, item in sorted(
                findings[analysis], key=lambda pair: (str(pair[1]["finding_type"]), pair[0])
            )
        ],
        "next_cursor": None,
        "analysis_truncated": bool(reasons),
        "truncation_reasons": sorted(reasons),
    }
    return ProjectModbusAnalysisData.model_validate(output).model_dump(mode="json")
