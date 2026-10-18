"""Request-local energy scope; declarations never establish native topology."""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mcpserver.load_flexibility import LoadFlexibility, LocalLoadWindow
from mcpserver.loxone.models import Control, LoxoneStructure
from mcpserver.loxone.uuid import normalize_loxone_uuid

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Declaration = Literal["user_confirmed", "scenario_assumption"]


class ContextContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class EnergyScope(ContextContract):
    kind: Literal["efm", "scenario"]
    description: str = Field(min_length=1, max_length=256)
    monitor_uuid: str | None = None
    common_supply_origin: Declaration

    @field_validator("monitor_uuid")
    @classmethod
    def monitor_identity(cls, value: str | None) -> str | None:
        return normalize_loxone_uuid(value) if value is not None else None

    @model_validator(mode="after")
    def selection(self) -> EnergyScope:
        if (self.kind == "efm") != (self.monitor_uuid is not None):
            raise ValueError("scope requires exactly the selected monitor or a scenario")
        return self


class ProductionAsset(ContextContract):
    asset_id: Identifier
    description: str = Field(min_length=1, max_length=256)
    production_control_uuid: str | None = None
    association_origin: Declaration

    @field_validator("production_control_uuid")
    @classmethod
    def source_identity(cls, value: str | None) -> str | None:
        return normalize_loxone_uuid(value) if value is not None else None


class ForecastCoverage(ContextContract):
    control_uuid: str
    asset_ids: list[Identifier] = Field(min_length=1, max_length=16)
    coverage_origin: Declaration

    @field_validator("control_uuid")
    @classmethod
    def source_identity(cls, value: str) -> str:
        return normalize_loxone_uuid(value)


class DeclaredCycle(ContextContract):
    """Complete-cycle declarations, independent of a persistent operating binding."""

    timezone: str = Field(min_length=1, max_length=128)
    windows: list[LocalLoadWindow] = Field(min_length=1, max_length=16)
    latest_completion: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    completion_day_offset: Literal[0, 1] = 0
    duration_seconds: int = Field(ge=1, le=86400)
    interruptible: bool
    minimum_run_seconds: int = Field(ge=0, le=86400)
    minimum_off_seconds: int = Field(ge=0, le=86400)
    cycle_energy_wh: float = Field(gt=0, le=1_000_000_000)
    origin: Declaration
    rationale: str = Field(min_length=1, max_length=256)

    def flexibility(self, load_id: str) -> LoadFlexibility:
        return LoadFlexibility.model_validate(
            {
                **self.model_dump(exclude={"origin", "cycle_energy_wh"}),
                "operating_binding_id": load_id,
                "cycle_identity": "user_confirmed_cycle",
                "energy_profile_origin": "user_declared",
                "declared_cycle_energy_wh": self.cycle_energy_wh,
            }
        )

    @model_validator(mode="after")
    def constraints(self) -> DeclaredCycle:
        self.flexibility("validation")
        return self


class ContextLoad(ContextContract):
    load_id: Identifier
    kind: Literal["profile", "real", "hypothetical"]
    binding_id: Identifier | None = None
    control_uuid: str | None = None
    operating_control_uuid: str | None = None
    cycle: DeclaredCycle | None = None

    @field_validator("control_uuid", "operating_control_uuid")
    @classmethod
    def source_identity(cls, value: str | None) -> str | None:
        return normalize_loxone_uuid(value) if value is not None else None

    @model_validator(mode="after")
    def selection(self) -> ContextLoad:
        if self.kind == "profile":
            if self.binding_id is None or any(
                v is not None for v in (self.control_uuid, self.operating_control_uuid, self.cycle)
            ):
                raise ValueError("profile load requires only a binding reference")
        elif self.kind == "real":
            if (
                self.binding_id is not None
                or self.control_uuid is None
                or self.cycle is None
                or self.cycle.origin != "user_confirmed"
            ):
                raise ValueError("real load requires a confirmed complete declared cycle")
        elif (
            self.binding_id is not None
            or self.control_uuid is not None
            or self.operating_control_uuid is not None
            or self.cycle is None
            or self.cycle.origin != "scenario_assumption"
        ):
            raise ValueError("hypothetical load requires only a declared scenario cycle")
        return self


class EnergyAnalysisContext(ContextContract):
    schema_version: Literal["energy_analysis_context.v1"] = "energy_analysis_context.v1"
    scope: EnergyScope
    assets: list[ProductionAsset] = Field(min_length=1, max_length=16)
    forecasts: list[ForecastCoverage] = Field(min_length=1, max_length=4)
    loads: list[ContextLoad] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def coverage(self) -> EnergyAnalysisContext:
        for values in (
            [a.asset_id for a in self.assets] + [load.load_id for load in self.loads],
            [a.asset_id for a in self.assets],
            [f.control_uuid for f in self.forecasts],
            [load.load_id for load in self.loads],
            [load.binding_id for load in self.loads if load.binding_id],
            [load.control_uuid for load in self.loads if load.control_uuid],
            [a.production_control_uuid for a in self.assets if a.production_control_uuid],
        ):
            if len(set(values)) != len(values):
                raise ValueError("duplicate context identity")
        coverage = Counter(a for f in self.forecasts for a in f.asset_ids)
        if set(coverage) != {a.asset_id for a in self.assets} or any(
            n != 1 for n in coverage.values()
        ):
            raise ValueError("forecast coverage must partition the selected assets")
        if len(self.forecasts) > 1 and (
            self.scope.common_supply_origin != "user_confirmed"
            or any(f.coverage_origin != "user_confirmed" for f in self.forecasts)
            or any(a.association_origin != "user_confirmed" for a in self.assets)
        ):
            raise ValueError("combined forecast coverage and common supply require confirmation")
        if self.scope.kind == "efm" and (
            any(a.production_control_uuid is None for a in self.assets)
            or any(load.kind == "hypothetical" for load in self.loads)
        ):
            raise ValueError("EFM scope requires native participants; use an explicit scenario")
        return self


class ResolvedAssociation(ContextContract):
    identifier: str
    origin: Literal["native_efm", "user_confirmed", "scenario_assumption"]
    control_uuid: str | None = None
    monitor_uuid: str | None = None
    conditions: list[str] = Field(default_factory=list)


def resolve_membership(
    context: EnergyAnalysisContext,
    visible: dict[str, Control],
    load_controls: dict[str, str],
) -> list[ResolvedAssociation]:
    """Check explicit members only; no inferred role or physical energy boundary."""
    members: dict[str, tuple[int, ...]] = {}
    if context.scope.kind == "efm":
        monitor = visible.get(context.scope.monitor_uuid or "")
        projection = monitor.efm if monitor else None
        if (
            monitor is None
            or monitor.control_type != "EFM"
            or projection is None
            or projection.omitted_subtrees
            or set(projection.diagnostics)
            & {"invalid_nodes_collection", "repeated_node_identity", "participant_limit"}
        ):
            raise ValueError("complete selected EFM topology required")
        for row in projection.participants:
            if (
                set(row.diagnostics)
                & {"invalid_participant", "invalid_node_identity", "invalid_child_collection"}
                or row.reference_status == "malformed"
            ):
                raise ValueError("complete selected EFM topology required")
            if row.control_uuid:
                if row.control_uuid not in visible or row.control_uuid in members:
                    raise ValueError("ambiguous or inaccessible EFM participant")
                members[row.control_uuid] = row.path
    for load in context.loads:
        if (
            load.kind == "real"
            and load.load_id in load_controls
            and load_controls[load.load_id] != load.control_uuid
        ):
            raise ValueError("real load mapping contradicts declared source")
        if load.kind == "profile" and load.load_id not in load_controls:
            raise ValueError("profile load source must be resolved")
    selections = [
        (a.asset_id, a.production_control_uuid, a.association_origin) for a in context.assets
    ] + [
        (
            load.load_id,
            load.control_uuid if load.kind == "real" else load_controls.get(load.load_id),
            "scenario_assumption"
            if load.kind == "hypothetical"
            else load.cycle.origin
            if load.cycle
            else "user_confirmed",
        )
        for load in context.loads
    ]
    paths = []
    identities = [uuid for _, uuid, _ in selections if uuid is not None]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate selected energy contribution")
    result = []
    for identifier, uuid, origin in selections:
        if uuid is not None and uuid not in visible:
            raise ValueError("context source is not accessible")
        if context.scope.kind == "efm":
            if uuid not in members:
                raise ValueError("source is not a proven selected EFM participant")
            paths.append(members[uuid])
            result.append(
                ResolvedAssociation(
                    identifier=identifier,
                    origin="native_efm",
                    control_uuid=uuid,
                    monitor_uuid=context.scope.monitor_uuid,
                    conditions=["physical_measurement_boundary_requires_confirmation"],
                )
            )
        else:
            result.append(
                ResolvedAssociation(identifier=identifier, origin=origin, control_uuid=uuid)
            )
    if any(a != b and a == b[: len(a)] for a in paths for b in paths):
        raise ValueError("overlapping selected EFM parent and child meters")
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate selected EFM contribution")
    return result


def selected_source_signature(structure: LoxoneStructure, uuids: set[str]) -> tuple[Control, ...]:
    """Stable selected source metadata for publication checks, not authorization reuse."""
    from mcpserver.installation_profile import visible_controls

    visible = {k: c for k, c in visible_controls(structure).items() if not c.is_hidden}
    if not uuids <= visible.keys():
        raise ValueError("context source is not accessible")
    return tuple(visible[uuid] for uuid in sorted(uuids))
