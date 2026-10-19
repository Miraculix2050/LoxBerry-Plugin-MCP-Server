"""Request-local energy scope; declarations never establish native topology."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

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
                "cycle_identity": (
                    "user_confirmed_cycle"
                    if self.origin == "user_confirmed"
                    else "active_episode_only"
                ),
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


class HistorySourceAssociation(ContextContract):
    association_id: Identifier
    source_index: int = Field(ge=0, le=15)
    role: (
        Literal[
            "consumer",
            "house_consumption",
            "production",
            "grid_export",
            "operating_state",
            "weather_context",
            "self_consumption",
        ]
        | None
    ) = None
    measurement_boundary: str | None = Field(default=None, min_length=1, max_length=128)
    declared_direction: Literal["import", "export", "charge", "discharge"] | None = None
    origin: Declaration


class AnalysisSite(ContextContract):
    site_id: Identifier
    timezone: str = Field(min_length=1, max_length=128)
    association_origin: Literal["user_confirmed"]
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def coordinates(self) -> AnalysisSite:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("site coordinates require latitude and longitude")
        return self


class DayWeatherSelection(ContextContract):
    quantity: Literal["radiation", "temperature", "forecast"]
    source_index: int = Field(ge=0, le=15)


class DayProductionCoverage(ContextContract):
    source_index: int = Field(ge=0, le=15)
    asset_ids: list[Identifier] = Field(min_length=1, max_length=16)
    coverage_origin: Literal["user_confirmed"]


class HistoryDayContext(ContextContract):
    site: AnalysisSite
    weather: list[DayWeatherSelection] = Field(min_length=1, max_length=3)
    assets: list[Identifier] = Field(default_factory=list, max_length=16)
    production: list[DayProductionCoverage] = Field(default_factory=list, max_length=16)
    radiation_independence_origin: Declaration | None = None

    @model_validator(mode="after")
    def coverage(self) -> HistoryDayContext:
        if len({w.quantity for w in self.weather}) != len(self.weather):
            raise ValueError("select one weather source per quantity")
        if (
            self.production
            and any(w.quantity == "radiation" for w in self.weather)
            and self.radiation_independence_origin != "user_confirmed"
        ):
            raise ValueError("radiation independence from evaluated PV requires confirmation")
        indices = [w.source_index for w in self.weather] + [p.source_index for p in self.production]
        if len(set(indices)) != len(indices):
            raise ValueError("weather and production require distinct selected sources")
        coverage = Counter(asset for p in self.production for asset in p.asset_ids)
        if (
            len(set(self.assets)) != len(self.assets)
            or set(coverage) != set(self.assets)
            or any(n != 1 for n in coverage.values())
        ):
            raise ValueError("production coverage must partition declared assets without overlap")
        return self


class HistoryLoadModel(ContextContract):
    load_id: Identifier
    kind: Literal["observed", "declared_real", "hypothetical"]
    consumer_id: Identifier | None = None
    operating_id: Identifier | None = None
    flexibility: LoadFlexibility | None = None
    cycle: DeclaredCycle | None = None

    @model_validator(mode="after")
    def model_kind(self) -> HistoryLoadModel:
        if self.kind == "observed":
            if self.consumer_id is None or self.operating_id is None or self.cycle is not None:
                raise ValueError("observed load requires consumer and operating associations")
            if self.flexibility is not None and (
                self.flexibility.energy_profile_origin != "observed_intervals"
                or self.flexibility.operating_binding_id != self.operating_id
            ):
                raise ValueError("observed model requires the selected measured operating pair")
        elif self.flexibility is not None or self.cycle is None:
            raise ValueError("declared model requires only complete declared cycle constraints")
        elif self.kind == "declared_real":
            if self.consumer_id is None or self.cycle.origin != "user_confirmed":
                raise ValueError("declared real model requires a confirmed visible consumer")
        elif (
            self.consumer_id is not None
            or self.operating_id is not None
            or self.cycle.origin != "scenario_assumption"
        ):
            raise ValueError("hypothetical models cannot claim observed sources")
        return self


class HistoryAnalysisContext(ContextContract):
    schema_version: Literal["history_analysis_context.v1"] = "history_analysis_context.v1"
    scope: EnergyScope
    associations: list[HistorySourceAssociation] = Field(min_length=1, max_length=16)
    loads: list[HistoryLoadModel] = Field(default_factory=list, max_length=16)
    day_context: HistoryDayContext | None = None

    @model_validator(mode="after")
    def references(self) -> HistoryAnalysisContext:
        ids = {a.association_id for a in self.associations}
        if len(ids) != len(self.associations) or len(
            {a.source_index for a in self.associations}
        ) != len(ids):
            raise ValueError("duplicate history association")
        if len({load.load_id for load in self.loads}) != len(self.loads):
            raise ValueError("duplicate history load")
        consumers = [load.consumer_id for load in self.loads if load.consumer_id]
        operating = [load.operating_id for load in self.loads if load.operating_id]
        if len(set(consumers)) != len(consumers) or len(set(operating)) != len(operating):
            raise ValueError("duplicate load contribution or operating association")
        if any(ref not in ids for ref in consumers + operating):
            raise ValueError("unknown history load association")
        if self.day_context is not None:
            indices = {a.source_index for a in self.associations}
            selected = {w.source_index for w in self.day_context.weather} | {
                p.source_index for p in self.day_context.production
            }
            if not selected <= indices or self.loads:
                raise ValueError(
                    "day comparison requires selected existing sources and no load models"
                )
            if (
                len(self.day_context.production) > 1
                and self.scope.common_supply_origin != "user_confirmed"
            ):
                raise ValueError("combined production requires confirmed common supply scope")
        if self.scope.kind == "efm" and any(load.kind == "hypothetical" for load in self.loads):
            raise ValueError("hypothetical loads require an explicit scenario")
        return self


class HistoryResolvedAssociation(ResolvedAssociation):
    source_index: int = Field(ge=0, le=15)
    binding_id: str | None = None


@dataclass(frozen=True)
class ResolvedSource:
    """Request-local association; never a decoder rule or persistent confirmation."""

    association: ResolvedAssociation
    binding: dict[str, Any] | None = None


@dataclass(frozen=True)
class SourceSnapshot:
    """Selected metadata is a publication guard, never reusable authorization."""

    installation: str
    signature: tuple[Control, ...]
    bindings: dict[str, Any]
    revision: int | None
    weather_metadata: tuple[object, ...] | None = None

    @classmethod
    def capture(
        cls,
        origin: str,
        structure: LoxoneStructure,
        source_ids: set[str],
        bindings: dict[str, Any],
        revision: int | None,
        binding_ids: set[str],
        *,
        include_weather: bool = False,
    ) -> SourceSnapshot:
        from mcpserver.installation_profile import installation_identity

        return cls(
            installation_identity(origin, structure),
            selected_source_signature(structure, source_ids),
            deepcopy({key: bindings.get(key) for key in binding_ids}),
            revision,
            deepcopy(
                (
                    structure.weather,
                    tuple(
                        item for item in structure.global_metadata if item.kind == "weather_state"
                    ),
                )
            )
            if include_weather
            else None,
        )

    def validate(
        self,
        origin: str,
        structure: LoxoneStructure,
        bindings: dict[str, Any],
        revision: int | None,
    ) -> None:
        from mcpserver.installation_profile import installation_identity
        from mcpserver.loxone.runtime import ControlOperationError

        try:
            signature = selected_source_signature(structure, {c.uuid for c in self.signature})
        except ValueError:
            raise ControlOperationError(
                "temporarily_unavailable", "Analysis context changed"
            ) from None
        if (
            installation_identity(origin, structure) != self.installation
            or signature != self.signature
            or revision != self.revision
            or any(bindings.get(key) != value for key, value in self.bindings.items())
            or (
                self.weather_metadata is not None
                and self.weather_metadata
                != (
                    structure.weather,
                    tuple(
                        item for item in structure.global_metadata if item.kind == "weather_state"
                    ),
                )
            )
        ):
            raise ControlOperationError("temporarily_unavailable", "Analysis context changed")


async def read_profile_bindings(
    path: Path | None,
    identity: str,
    structure: LoxoneStructure,
    *,
    required: bool,
) -> tuple[dict[str, Any], int | None]:
    """Read current confirmations only for explicit references, without creating a store."""
    from mcpserver.bounded_worker import run_admitted_worker
    from mcpserver.installation_profile import ProfileSources, ProfileStore, project_profile
    from mcpserver.loxone.runtime import ControlOperationError

    if not required:
        return {}, None
    if path is None:
        raise ControlOperationError("temporarily_unavailable", "Analysis profile unavailable")
    document = await run_admitted_worker(ProfileStore(path).read, identity)
    projection = project_profile(
        document, identity, ProfileSources.from_structure(identity, structure), limit=256
    )
    if projection["status"] != "available":
        raise ControlOperationError("temporarily_unavailable", "Analysis profile changed")
    return {b["binding_id"]: b for b in projection["bindings"]}, document.revision


def resolve_source_association(
    identifier: str,
    visible: dict[str, Control],
    *,
    bindings: dict[str, Any],
    binding_id: str | None = None,
    control_uuid: str | None = None,
    origin: Declaration = "scenario_assumption",
    expected_role: str | None = None,
) -> ResolvedSource:
    """Resolve exact sources or confirmations; a declaration cannot override a reference."""
    from mcpserver.loxone.runtime import ControlOperationError

    binding = None
    if binding_id is not None:
        if control_uuid is not None:
            raise ValueError("choose a profile reference or an exact source")
        binding = bindings.get(binding_id)
        if (
            binding is None
            or binding.get("status") != "confirmed"
            or (expected_role is not None and binding.get("role") != expected_role)
        ):
            raise ControlOperationError("not_found", "Confirmed visible source required")
        control_uuid = binding.get("control_uuid")
        origin = "user_confirmed"
    if control_uuid is not None and (
        control_uuid not in visible or visible[control_uuid].is_hidden
    ):
        raise ControlOperationError("not_found", "Analysis source is not accessible")
    return ResolvedSource(
        ResolvedAssociation(identifier=identifier, origin=origin, control_uuid=control_uuid),
        binding,
    )


def resolve_history_associations(
    context: HistoryAnalysisContext,
    selectors: list[dict[str, Any]],
    visible: dict[str, Control],
    bindings: dict[str, Any],
    *,
    timezone_name: str,
    structure: LoxoneStructure | None = None,
    installation: str | None = None,
) -> tuple[dict[int, dict[str, Any]], list[HistoryResolvedAssociation]]:
    """Apply domain declarations to exact selections, never to stored confirmations."""
    effective = {}
    resolved = {}
    physical = set()
    for association in context.associations:
        if association.source_index >= len(selectors):
            raise ValueError("unknown history source index")
        selector = selectors[association.source_index]
        source = resolve_source_association(
            association.association_id,
            visible,
            bindings=bindings,
            binding_id=selector.get("binding_id"),
            control_uuid=selector.get("control_uuid"),
            origin=association.origin,
            expected_role=association.role,
        )
        binding = source.binding
        row = dict(binding) if binding else {}
        if binding and association.origin != "user_confirmed":
            raise ValueError("a profile reference retains its confirmed provenance")
        for key, value in (
            ("role", association.role),
            ("measurement_boundary", association.measurement_boundary),
            ("declared_direction", association.declared_direction),
        ):
            if binding and value is not None and binding.get(key) != value:
                raise ValueError("request declaration contradicts confirmed profile")
            if value is not None:
                row[key] = value
            else:
                row.setdefault(key, None)
        uuid = source.association.control_uuid
        if selector.get("source_kind") == "structured_weather" or (
            binding and binding.get("source_kind") == "weather"
        ):
            from mcpserver.installation_profile import ProfileSources

            if context.day_context is None or structure is None or installation is None:
                raise ValueError("weather context requires fresh source structure")
            weather_state = (
                binding.get("weather_state_uuid") if binding else selector.get("state_uuid")
            )
            mode = binding.get("mode") if binding else selector.get("stored_mode")
            if (
                mode != "actual"
                or (mode, weather_state)
                not in ProfileSources.from_structure(installation, structure).weather
            ):
                raise ValueError("selected actual weather source is not accessible")
            if binding and binding.get("field") != "solar_radiation":
                raise ValueError("class comparisons require the selected radiation field")
            weather_key = ("structured_weather", weather_state, mode)
            if weather_key in physical:
                raise ValueError("duplicate physical weather source")
            physical.add(weather_key)
            row.update(
                control_uuid=None,
                weather_state_uuid=weather_state,
                mode=mode,
                source_kind="weather",
            )
            effective[association.source_index] = row
            resolved[association.association_id] = source.association
            continue
        if uuid is None or uuid not in visible:
            raise ValueError("history requires a visible exact source")
        control = visible[uuid]
        series = binding.get("series_id") if binding else selector.get("series_id")
        state = binding.get("state_uuid") if binding else selector.get("state_uuid")
        if (
            series is not None and series not in {s.series_id for s in control.statistic_series}
        ) or (state is not None and state not in {s for _, s in control.state_uuids}):
            raise ValueError("history source is not a selected control member")
        physical_key = (uuid, series, state)
        if physical_key in physical:
            raise ValueError("duplicate physical history contribution")
        physical.add(physical_key)
        row.update(control_uuid=uuid, series_id=series, state_uuid=state)
        effective[association.source_index] = row
        resolved[association.association_id] = source.association
    by_id = {a.association_id: a for a in context.associations}
    load_controls = set()
    for load in context.loads:
        if load.consumer_id is None:
            continue
        selected = by_id[load.consumer_id]
        consumer = effective[selected.source_index]
        if consumer["role"] != "consumer" or selected.origin != "user_confirmed":
            raise ValueError("real load requires an explicitly confirmed consumer association")
        if consumer["control_uuid"] in load_controls:
            raise ValueError("duplicate physical load model")
        load_controls.add(consumer["control_uuid"])
        operating: dict[str, Any] = {}
        if load.operating_id is not None:
            op = by_id[load.operating_id]
            operating = effective[op.source_index]
            if operating["role"] != "operating_state" or op.origin != "user_confirmed":
                raise ValueError("observed operating association requires confirmation")
        stored = consumer.get("load_flexibility")
        if (
            selectors[selected.source_index].get("binding_id")
            and load.operating_id is not None
            and stored is None
        ):
            raise ValueError("selected operating source requires a confirmed saved companion")
        effective_flex = load.flexibility or (
            LoadFlexibility.model_validate(stored) if stored else None
        )
        if effective_flex is not None and effective_flex.timezone != timezone_name:
            raise ValueError("effective cycle timezone contradicts the analysis timezone")
        if selectors[selected.source_index].get("binding_id") and stored is not None:
            saved = LoadFlexibility.model_validate(stored)
            if load.flexibility is not None and (
                saved.model_dump(exclude={"operating_binding_id"})
                != load.flexibility.model_dump(exclude={"operating_binding_id"})
            ):
                raise ValueError("cycle declaration contradicts confirmed profile constraints")
            if (
                load.cycle is not None
                and load.cycle.flexibility(saved.operating_binding_id) != saved
            ):
                raise ValueError("declared model contradicts confirmed profile constraints")
            if load.operating_id is not None:
                companion = bindings.get(saved.operating_binding_id)
                if (
                    not consumer.get("load_constraints_usable")
                    or companion is None
                    or companion.get("status") != "confirmed"
                    or (companion.get("control_uuid"), companion.get("state_uuid"))
                    != (operating["control_uuid"], operating["state_uuid"])
                ):
                    raise ValueError("selected operating source contradicts confirmed companion")
        if load.flexibility is not None:
            consumer["load_flexibility"] = load.flexibility.model_dump()
            consumer["load_constraints_usable"] = True
    energy = [
        (a.association_id, resolved[a.association_id].control_uuid, a.origin)
        for a in context.associations
        if effective[a.source_index]["role"]
        in {"production", "consumer", "house_consumption", "grid_export", "self_consumption"}
    ]
    native = {
        r.identifier: r
        for r in resolve_selected_membership(
            context.scope,
            visible,
            energy,
            contribution_roles=(
                {a.association_id: effective[a.source_index]["role"] for a in context.associations}
                if context.day_context is not None
                else None
            ),
        )
    }
    if context.day_context is not None:
        day = context.day_context
        if day.site.timezone != timezone_name:
            raise ValueError("site timezone contradicts analysis timezone")
        if any(
            a.origin != "user_confirmed"
            and effective[a.source_index]["role"] in {"self_consumption", "grid_export"}
            for a in context.associations
        ):
            raise ValueError("measured energy balance associations require explicit confirmation")
        for selection in day.production:
            association = next(
                a for a in context.associations if a.source_index == selection.source_index
            )
            row = effective[selection.source_index]
            if association.origin != "user_confirmed" or row["role"] != "production":
                raise ValueError("production coverage requires confirmed production associations")
            parameters = row.get("pv_parameters") or {}
            if (
                day.site.latitude is not None
                and parameters.get("latitude") is not None
                and (
                    day.site.latitude != parameters["latitude"]
                    or day.site.longitude != parameters.get("longitude")
                )
            ):
                raise ValueError("site location contradicts confirmed PV parameters")
        for weather_selection in day.weather:
            association = next(
                a for a in context.associations if a.source_index == weather_selection.source_index
            )
            if (
                association.origin != "user_confirmed"
                or effective[weather_selection.source_index]["role"] != "weather_context"
            ):
                raise ValueError("weather site association requires explicit confirmation")
            row = effective[weather_selection.source_index]
            if weather_selection.quantity == "radiation" and any(
                row.get("control_uuid") is not None
                and row["control_uuid"] == effective[p.source_index].get("control_uuid")
                for p in day.production
            ):
                raise ValueError("radiation source must be independent of evaluated PV production")
    return effective, [
        HistoryResolvedAssociation(
            **native.get(a.association_id, resolved[a.association_id]).model_dump(),
            source_index=a.source_index,
            binding_id=selectors[a.source_index].get("binding_id"),
        )
        for a in context.associations
    ]


def resolve_membership(
    context: EnergyAnalysisContext,
    visible: dict[str, Control],
    load_controls: dict[str, str],
) -> list[ResolvedAssociation]:
    """Check explicit members only; no inferred role or physical energy boundary."""
    for load in context.loads:
        if (
            load.kind == "real"
            and load.load_id in load_controls
            and load_controls[load.load_id] != load.control_uuid
        ):
            raise ValueError("real load mapping contradicts declared source")
        if load.kind == "profile" and load.load_id not in load_controls:
            raise ValueError("profile load source must be resolved")
    selections: list[tuple[str, str | None, Declaration]] = [
        (a.asset_id, a.production_control_uuid, a.association_origin) for a in context.assets
    ] + [
        (
            load.load_id,
            load.control_uuid
            if load.kind == "real"
            else load_controls.get(load.load_id)
            if load.kind == "profile"
            else None,
            "scenario_assumption"
            if load.kind == "hypothetical"
            else load.cycle.origin
            if load.cycle
            else "user_confirmed",
        )
        for load in context.loads
    ]
    return resolve_selected_membership(context.scope, visible, selections)


def resolve_selected_membership(
    scope: EnergyScope,
    visible: dict[str, Control],
    selections: list[tuple[str, str | None, Declaration]],
    *,
    contribution_roles: dict[str, str] | None = None,
) -> list[ResolvedAssociation]:
    """Prove selected native topology independently of any domain's input shape."""
    members: dict[str, tuple[int, ...]] = {}
    if scope.kind == "efm":
        monitor = visible.get(scope.monitor_uuid or "")
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
    paths = []
    identities = [
        (uuid, contribution_roles[identifier] if contribution_roles is not None else None)
        for identifier, uuid, _ in selections
        if uuid is not None
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate selected energy contribution")
    result = []
    checked_controls: set[str | None] = set()
    for identifier, uuid, origin in selections:
        if uuid is not None and uuid not in visible:
            raise ValueError("context source is not accessible")
        if scope.kind == "efm":
            if uuid not in members:
                raise ValueError("source is not a proven selected EFM participant")
            # Distinct day metrics share membership, not a measurement contribution.
            # Keep topology uniqueness across different controls and all legacy calls.
            if contribution_roles is None or uuid not in checked_controls:
                paths.append(members[uuid])
                checked_controls.add(uuid)
            result.append(
                ResolvedAssociation(
                    identifier=identifier,
                    origin="native_efm",
                    control_uuid=uuid,
                    monitor_uuid=scope.monitor_uuid,
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
