"""Pure, bounded interpretation of user-visible runtime states."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from itertools import islice
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from .energy_manager import DOCUMENT as MANAGER_DOCUMENT
from .energy_manager import PERCENT_ROLES, POWER_ROLES, decode_loads
from .models import Control, LoxoneIdentity, LoxoneStructure, StatisticSeries
from .pv_forecast import DOCUMENT as PVPF_DOCUMENT
from .pv_forecast import ENERGY_STATES as PVPF_ENERGY_STATES
from .pv_forecast import STATES as PVPF_STATES
from .pv_forecast import decode as decode_pv_forecast
from .source_time import loxone_time as _loxone_time
from .window_states import WINDOW_DOCUMENT, decode_window_states

if TYPE_CHECKING:
    from .native_efm import NativeEfmResult


@dataclass(frozen=True, slots=True)
class SemanticsSource:
    kind: Literal["structure_file", "runtime_state", "decoder_rule"]
    reference: str
    fields: tuple[str, ...]
    rule_id: str | None = None
    document_version: str | None = None
    firmware_version: str | None = None
    state_uuid: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticsRange:
    minimum: float
    maximum: float
    step: float


@dataclass(frozen=True, slots=True)
class SemanticsEncoding:
    code: int
    label: str


@dataclass(frozen=True, slots=True)
class SemanticsPosition:
    index: int
    label: str | None


@dataclass(slots=True)
class StateSemantics:
    interpretation_status: Literal["known", "partial", "unknown", "invalid"] = "unknown"
    reason: Literal[
        "no_supported_evidence",
        "metadata_only",
        "invalid_structure_metadata",
        "position_bound_metadata",
        "incomplete_metadata",
        "value_unavailable",
        "invalid_documented_value",
        "documented_decoder",
        "owner_approved_decoder",
        "companion_unavailable",
        "metadata_truncated",
    ] = "no_supported_evidence"
    value_type: str | None = None
    display_format: str | None = None
    display_format_total_length: int | None = None
    display_format_returned_length: int = 0
    display_format_truncated: bool = False
    display_format_complete: bool = False
    unit: str | None = None
    measurement_quantity: (
        Literal["temperature", "binary_state", "power", "percentage", "energy"] | None
    ) = None
    measurement_role: (
        Literal[
            "actual_temperature",
            "target_temperature",
            "on_off_indication",
            "counter_activity",
            "grid_power",
            "storage_power",
            "production_power",
            "maximum_storage_power_parameter",
            "storage_state_of_charge",
            "minimum_storage_soc_parameter",
            "predicted_pv_energy",
        ]
        | None
    ) = None
    range: SemanticsRange | None = None
    precision: int | None = None
    sign_convention: str | None = None
    encoding: Annotated[list[SemanticsEncoding], Field(max_length=100)] = field(
        default_factory=list
    )
    encoding_total: int | None = None
    encoding_returned: int = 0
    encoding_truncated: bool = False
    encoding_complete: bool = False
    positions: Annotated[list[SemanticsPosition], Field(max_length=100)] = field(
        default_factory=list
    )
    positions_total: int | None = None
    positions_returned: int = 0
    positions_truncated: bool = False
    positions_complete: bool = False
    sources: Annotated[list[SemanticsSource], Field(max_length=8)] = field(default_factory=list)
    sources_returned: int = 0
    sources_total: int = 0
    sources_truncated: bool = False
    sources_complete: bool = True


@dataclass(frozen=True, slots=True)
class SeriesSemantics:
    """Source meaning, separate from values, coverage and user-declared roles."""

    interpretation_status: Literal["known", "partial", "unknown", "invalid"]
    value_meaning: Literal["cumulative_counter", "sample", "interval_difference_sum"] | None
    unit: str | None = None
    unit_origin: Literal["structure_declared"] | None = None
    measurement_quantity: Literal["temperature", "power", "energy"] | None = None
    measurement_role: str | None = None
    direction: str | None = None
    measurement_boundary: str | None = None
    measurement_method: str | None = None
    reset_semantics: Literal["control_reset_to_zero_supported"] | None = None
    rollover_semantics: str | None = None
    aggregation: Literal["recorded_values", "sum_of_differences"] | None = None
    timestamp_basis: Literal["unix_utc", "local_miniserver_seconds_since_2009"] | None = None
    timestamp_position: Literal["observation", "interval_start"] | None = None
    recording_mode: int | None = None
    limitations: Annotated[tuple[str, ...], Field(max_length=16)] = ()
    sources: Annotated[tuple[SemanticsSource, ...], Field(max_length=8)] = ()


_DOCUMENT = "https://www.loxone.com/enen/kb/api/"
_STATUS_DOCUMENT = (
    "https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf"
)
_STATUS_COUNTS = {**{f"numState{i}": i for i in range(10)}, "numDef": 10}
_IRRIGATION_RULES = {"zones", "rainActive", "currentZone"}
_ALARM_RULES = {
    "isEnabled",
    "isAlarmActive",
    "confirmationNeeded",
    "entryList",
    "currentEntry",
    "nextEntry",
    "nextEntryMode",
    "ringingTime",
    "ringDuration",
    "prepareDuration",
    "snoozeTime",
    "snoozeDuration",
    "nextEntryTime",
    "deviceState",
    "deviceSettings",
    "wakeAlarmSoundSettings",
}
_FORMAT_TYPES = {"InfoOnlyAnalog", "UpDownAnalog", "Slider"}
# Bump when a supported decoder/companion rule changes, including branches
# whose rule provenance depends on a value that profile metadata does not read.
_STATE_RULESET_REFERENCE = "StateSemanticsResolver.rules.v1"
_REFERENCE_STRUCTURE = LoxoneStructure(LoxoneIdentity("", ""), "", (), (), ())


@dataclass(frozen=True, slots=True)
class AlertFamily:
    primary: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()


ALERT_FAMILIES = {
    "Alarm": AlertFamily("level"),
    "SmokeAlarm": AlertFamily("level", optional=("testAlarm",)),
    "AalEmergency": AlertFamily("status"),
    "AalSmartAlarm": AlertFamily(
        "alarmLevel", optional=("disableEndTime", "isLeaveActive", "isLocked")
    ),
    "AlarmChain": AlertFamily("activeAlarmType"),
}


def _resolve_measurement(
    control: Control, state_name: str, value: object
) -> tuple[StateSemantics, object | None] | None:
    """Resolve only the reviewed scalar measurement families without I/O."""
    documented_temperature = control.control_type == "IRoomControllerV2" and state_name in {
        "tempActual",
        "tempTarget",
    }
    documented_binary = (
        control.control_type in {"InfoOnlyDigital", "Hourcounter"} and state_name == "active"
    )
    if not (documented_temperature or documented_binary):
        return None
    state_uuid = dict(control.state_uuids).get(state_name)
    if state_uuid is None:
        return None
    result = StateSemantics()
    semantic_value: object | None = None
    result.measurement_quantity = "temperature" if documented_temperature else "binary_state"
    result.measurement_role = (
        ("actual_temperature" if state_name == "tempActual" else "target_temperature")
        if documented_temperature
        else ("counter_activity" if control.control_type == "Hourcounter" else "on_off_indication")
    )
    result.value_type = "number" if documented_temperature else "boolean"
    page = 76 if documented_temperature else (71 if control.control_type == "Hourcounter" else 72)
    result.sources.extend(
        [
            SemanticsSource(
                "decoder_rule",
                _STATUS_DOCUMENT + f"#page={page}",
                ("measurement_quantity", "measurement_role", "semantic_value"),
                rule_id=f"{control.control_type}.{state_name}.v1",
                document_version="17.1",
            ),
            SemanticsSource(
                "runtime_state",
                "states." + state_name,
                ("semantic_value",),
                state_uuid=state_uuid,
            ),
        ]
    )
    if documented_temperature:
        result.display_format = (
            control.format if control.format is not None and len(control.format) <= 64 else None
        )
        result.display_format_total_length = (
            control.format_total_length
            if control.format_total_length is not None
            else (len(control.format) if control.format is not None else None)
        )
        result.display_format_returned_length = len(result.display_format or "")
        result.display_format_truncated = (result.display_format_total_length or 0) > 64
        result.display_format_complete = (
            control.format is not None and not result.display_format_truncated
        )
        # The documented temperature field provides the quantity;
        # only a complete explicit unit provides Celsius/Fahrenheit.
        unit_match = re.fullmatch(r"(?:%[0-9]*(?:\.[0-9]+)?f\s*)?°([CF])", control.format or "")
        if (
            result.display_format_total_length is not None
            or "format" in control.semantics_invalid_fields
        ):
            result.sources.append(
                SemanticsSource(
                    "structure_file",
                    "details.format",
                    ("display_format", "display_format_total_length", "display_format_truncated"),
                    document_version="17.1",
                )
            )
        if (
            unit_match
            and result.display_format_complete
            and "format" not in control.semantics_invalid_fields
        ):
            result.unit = "°" + unit_match[1]
            result.sources.append(
                SemanticsSource(
                    "structure_file",
                    "details.format",
                    ("unit", "display_format"),
                    document_version="17.1",
                )
            )
    else:
        result.encoding = [SemanticsEncoding(0, "off"), SemanticsEncoding(1, "on")]
        result.encoding_total = result.encoding_returned = 2
        result.encoding_complete = True
    if value is None:
        result.interpretation_status, result.reason = "partial", "value_unavailable"
    elif not _valid_measurement_number(value, binary=documented_binary):
        result.interpretation_status, result.reason = (
            "invalid",
            "invalid_documented_value",
        )
    else:
        result.interpretation_status, result.reason = "known", "documented_decoder"
        if documented_temperature:
            semantic_value = {
                "kind": "temperature",
                "role": result.measurement_role,
                "value": value,
                "unit": result.unit,
            }
            if result.unit is None:
                result.interpretation_status, result.reason = "partial", "metadata_only"
                if result.display_format_truncated:
                    result.reason = "metadata_truncated"
                if "format" in control.semantics_invalid_fields:
                    result.reason = "invalid_structure_metadata"
        else:
            semantic_value = {
                "kind": "binary_state",
                "active": value == 1,
                "role": result.measurement_role,
            }
    result.sources_returned = result.sources_total = len(result.sources)
    return result, semantic_value


def _resolve_energy_manager(
    structure: LoxoneStructure, control: Control, name: str, value: object
) -> tuple[StateSemantics, object | None] | None:
    if control.control_type not in {"EnergyManager", "EnergyManager2"}:
        return None
    result = StateSemantics()
    generation: Literal[1, 2] = 1 if control.control_type == "EnergyManager" else 2
    if name == "loads":
        # Fresh caller authorization is provided by the existing tool surfaces.
        # Cached state delivery is never evidence of present administrator rights.
        if structure.caller_is_admin is not True or control.is_hidden:
            return result, None
        result.value_type = "array"
        result.interpretation_status, result.reason = "partial", "value_unavailable"
        result.sources.append(
            SemanticsSource(
                "decoder_rule",
                f"{MANAGER_DOCUMENT}#page={61 if generation == 1 else 62}",
                ("semantic_value",),
                rule_id=f"energy_manager_gen{generation}.loads.17_1.v1",
                document_version="17.1",
            )
        )
        decoded = None
        if value is not None:
            try:
                decoded = decode_loads(generation, value)
                result.reason = "documented_decoder"
            except (ValueError, UnicodeError, RecursionError, OverflowError):
                result.interpretation_status, result.reason = "invalid", "invalid_documented_value"
        result.sources_returned = result.sources_total = len(result.sources)
        return result, decoded
    if generation == 2 and name in POWER_ROLES.keys() | PERCENT_ROLES.keys():
        if name in POWER_ROLES:
            result.unit, result.measurement_quantity = "kW", "power"
            result.measurement_role = POWER_ROLES[name]
        else:
            result.unit, result.measurement_quantity = "%", "percentage"
            result.measurement_role = PERCENT_ROLES[name]
        result.value_type = "number"
        result.interpretation_status, result.reason = "partial", "value_unavailable"
        result.sources.append(
            SemanticsSource(
                "decoder_rule",
                f"{MANAGER_DOCUMENT}#page=62",
                ("unit", "measurement_quantity", "measurement_role"),
                rule_id=f"energy_manager_gen2.{name}.17_1.v1",
                document_version="17.1",
            )
        )
        if value is not None:
            try:
                valid = (
                    not isinstance(value, bool)
                    and isinstance(value, int | float)
                    and math.isfinite(value)
                )
            except OverflowError:
                valid = False
            result.reason = "documented_decoder" if valid else "invalid_documented_value"
            if not valid:
                result.interpretation_status = "invalid"
        result.sources_returned = result.sources_total = len(result.sources)
        return result, None
    return result, None


class StateSemanticsResolver:
    """Resolve only exact, reviewed type/state rules, without I/O or role inference."""

    def resolve_native_efm(
        self, result: NativeEfmResult, before: Control, after: Control
    ) -> NativeEfmResult:
        """Bind only documented aggregate power fields to unchanged EFM metadata."""
        rule = "native_efm_actual_semantics_17_2_8_28.v1"
        limitations = [
            "sign_convention_unverified",
            "measurement_boundary_unverified",
            "physical_observation_time_unverified",
            "historical_date_selection_unavailable",
            "self_consumption_unavailable",
        ]
        enriched = result.model_copy(
            deep=True,
            update={
                "schema_version": "native_efm_result.v2",
                "semantic_rule_version": rule if result.view == "actual" else None,
                "source_metadata_status": "not_applicable",
                "report_applicability": (
                    "current_snapshot"
                    if result.view == "actual"
                    else "lifetime_accumulator"
                    if result.view == "lifetime"
                    else "current_calendar_period"
                ),
                "report_limitations": limitations,
            },
        )
        if result.view != "actual":
            enriched.report_limitations.extend(
                ["period_units_unverified", "period_boundaries_unverified"]
            )
            return enriched
        if (
            before.control_type != "EFM"
            or after.control_type != "EFM"
            or before.uuid != after.uuid
            or before.action_uuid != after.action_uuid
        ):
            enriched.source_metadata_status = "changed"
            enriched.report_limitations.append("source_metadata_changed")
            return enriched
        roles = {
            "Gpwr": "grid_power",
            "Ppwr": "production_power",
            "Spwr": "storage_power",
            "Cpwr": "load_power",
        }
        enriched.fields = [
            field.model_copy(
                update={
                    "measurement_quantity": "power",
                    "measurement_role": roles[field.name],
                    "interpretation_status": "partial",
                }
            )
            if field.name in roles
            else field
            for field in enriched.fields
        ]
        enriched.semantic_sources.append(
            SemanticsSource(
                "decoder_rule",
                _STATUS_DOCUMENT + "#page=66",
                (
                    "fields.Gpwr.measurement_quantity",
                    "fields.Gpwr.measurement_role",
                    "fields.Ppwr.measurement_quantity",
                    "fields.Ppwr.measurement_role",
                    "fields.Spwr.measurement_quantity",
                    "fields.Spwr.measurement_role",
                ),
                rule_id=rule,
                document_version="17.1",
                firmware_version=result.firmware,
            )
        )
        enriched.semantic_sources.append(
            SemanticsSource(
                "decoder_rule",
                _STATUS_DOCUMENT + "#page=67",
                ("fields.Cpwr.measurement_quantity", "fields.Cpwr.measurement_role"),
                rule_id=rule,
                document_version="17.1",
                firmware_version=result.firmware,
            )
        )
        previous = (
            (before.efm.actual_format, before.efm.actual_format_status)
            if before.efm
            else (None, "missing")
        )
        current = (
            (after.efm.actual_format, after.efm.actual_format_status)
            if after.efm
            else (None, "missing")
        )
        if previous != current:
            enriched.source_metadata_status = "changed"
            enriched.report_limitations.append("source_metadata_changed")
            return enriched
        if current[1] != "retained":
            enriched.source_metadata_status = "invalid" if current[1] == "invalid" else "missing"
            enriched.report_limitations.append("power_units_unverified")
            return enriched
        source_format = current[0] or ""
        match = (
            re.fullmatch(r"%[0-9]*(?:\.[0-9]+)?f *(W|kW)", source_format)
            if len(source_format) <= 128
            else None
        )
        if match is None:
            enriched.source_metadata_status = "unsupported"
            enriched.report_limitations.append("power_units_unverified")
            return enriched
        enriched.source_metadata_status = "stable"
        enriched.semantic_sources[0] = replace(
            enriched.semantic_sources[0],
            fields=(
                *enriched.semantic_sources[0].fields,
                "fields.Gpwr.unit",
                "fields.Ppwr.unit",
                "fields.Spwr.unit",
            ),
        )
        enriched.fields = [
            field.model_copy(update={"unit": match[1]})
            if field.name in {"Gpwr", "Ppwr", "Spwr"}
            else field
            for field in enriched.fields
        ]
        enriched.semantic_sources.append(
            SemanticsSource(
                "structure_file",
                "controls[target].details.actualFormat",
                ("fields.Gpwr.unit", "fields.Ppwr.unit", "fields.Spwr.unit"),
                rule_id=rule,
                document_version="17.1",
                firmware_version=result.firmware,
            )
        )
        enriched.semantic_sources.append(
            SemanticsSource(
                "decoder_rule",
                _STATUS_DOCUMENT + "#page=64",
                ("fields.Gpwr.unit", "fields.Ppwr.unit", "fields.Spwr.unit"),
                rule_id=rule,
                document_version="17.1",
                firmware_version=result.firmware,
            )
        )
        return enriched

    def source_reference(
        self,
        control: Control,
        *,
        state_name: str | None = None,
        series: StatisticSeries | None = None,
    ) -> str | None:
        """Stable rule reference for profile invalidation, with no decoder duplication."""
        # Source identity is technical evidence, independent of the caller's
        # temporary permission to decode a cached load payload. New families get
        # their own ruleset; unchanged legacy families keep their fingerprints.
        if series is None and control.control_type in {"EnergyManager", "EnergyManager2"}:
            generation = 1 if control.control_type == "EnergyManager" else 2
            if state_name == "loads" or (
                generation == 2 and state_name in POWER_ROLES.keys() | PERCENT_ROLES.keys()
            ):
                return (
                    f"energy_manager_gen{generation}.{state_name}.17_1.v1"
                    f"+StateSemanticsResolver.energy_manager_gen{generation}.rules.v1"
                )
            return None
        if series is not None:
            sources = self.resolve_series(control, series).sources
        else:
            descriptor, _value = self.resolve(
                _REFERENCE_STRUCTURE, control, state_name or "", None, {}
            )
            sources = tuple(descriptor.sources)
        rules = list(dict.fromkeys(source.rule_id for source in sources if source.rule_id))
        if series is None and rules:
            rules.append(_STATE_RULESET_REFERENCE)
        return "+".join(rules) if rules else None

    def resolve_series(
        self, control: Control, series: StatisticSeries, *, granularity: str = "raw"
    ) -> SeriesSemantics:
        """Describe the existing adapter's raw/diff contract; never infer coverage."""
        if series.source != "statistic_v2":
            return SeriesSemantics(
                "unknown",
                None,
                timestamp_basis="local_miniserver_seconds_since_2009",
                limitations=("legacy_timezone_conversion_unverified", "series_meaning_unverified"),
                sources=(
                    SemanticsSource(
                        "structure_file",
                        _STATUS_DOCUMENT + "#page=19",
                        ("timestamp_basis",),
                        document_version="17.1",
                    ),
                ),
            )
        if not series.accumulated_metadata_valid:
            return SeriesSemantics("invalid", None, limitations=("invalid_accumulated_metadata",))
        # These are precisely the modes emitted by the existing native adapter.
        difference = series.accumulated and granularity in {"hour", "day", "month", "year"}
        raw = granularity == "raw"
        meaning: Literal["cumulative_counter", "sample", "interval_difference_sum"] | None = (
            "interval_difference_sum"
            if difference
            else "cumulative_counter"
            if raw and series.accumulated
            else "sample"
            if raw
            else None
        )
        quantity: Literal["temperature", "power", "energy"] | None = None
        reset: Literal["control_reset_to_zero_supported"] | None = None
        unit: str | None = None
        role: str | None = None
        limits = [
            "measurement_method_unverified",
            "measurement_boundary_unverified",
            "direction_unverified",
            "rollover_unverified",
            "continuous_coverage_unverified",
        ]
        if series.accumulated:
            limits.append("decreases_require_reset_evidence")
        temperature = _resolve_measurement(control, series.output, None)
        if temperature is not None and temperature[0].measurement_quantity == "temperature":
            quantity, role = "temperature", temperature[0].measurement_role
            match_temperature = re.fullmatch(r"(?:%[0-9]*(?:\.[0-9]+)?f\s*)?°([CF])", series.format)
            if match_temperature and not series.accumulated:
                unit = "°" + match_temperature[1]
                if temperature[0].unit is not None and temperature[0].unit != unit:
                    unit = None
                    limits.append("channel_unit_conflict")
            if series.accumulated:
                limits.append("channel_accumulation_conflict")
        # Meter exact channels are documented; arbitrary formats/types get no unit inference.
        if control.control_type == "Meter" and series.output in {"actual", "total", "totalNeg"}:
            match = re.fullmatch(r"%[0-9]*(?:\.[0-9]+)?f?\s*(kWh|Wh|kW|W)", series.format)
            if match:
                candidate = match[1]
                if (
                    series.output == "actual"
                    and candidate in {"W", "kW"}
                    and not series.accumulated
                ):
                    quantity, unit, role = "power", candidate, "power_or_flow_channel"
                elif series.output in {"total", "totalNeg"} and candidate in {"Wh", "kWh"}:
                    quantity, unit, role = "energy", candidate, "meter_reading_channel"
                else:
                    limits.append("channel_unit_conflict")
            reset = "control_reset_to_zero_supported"
        if unit is None:
            limits.append("unit_unverified")
        if not raw and not difference:
            limits.append("aggregation_unverified")
        sources = [
            SemanticsSource(
                "decoder_rule",
                _STATUS_DOCUMENT + "#page=20",
                ("value_meaning", "aggregation", "timestamp_basis", "recording_mode"),
                rule_id="StatisticV2.series.v1",
                document_version="17.1",
            )
        ]
        if temperature is not None and quantity == "temperature":
            sources.extend(temperature[0].sources[:2])
            sources.append(
                SemanticsSource(
                    "structure_file",
                    "statisticV2.groups.dataPoints.format",
                    ("unit", "unit_origin"),
                    document_version="17.1",
                )
            )
        if control.control_type == "Meter" and series.output in {"actual", "total", "totalNeg"}:
            sources.append(
                SemanticsSource(
                    "structure_file",
                    _STATUS_DOCUMENT + "#page=106",
                    (
                        "measurement_quantity",
                        "unit",
                        "unit_origin",
                        "measurement_role",
                        "reset_semantics",
                    ),
                    rule_id="Meter.series.v1",
                    document_version="17.1",
                )
            )
            sources.append(
                SemanticsSource(
                    "structure_file",
                    "statisticV2.groups.dataPoints.format",
                    ("unit", "unit_origin"),
                    document_version="17.1",
                )
            )
        return SeriesSemantics(
            "partial",
            meaning,
            unit=unit,
            unit_origin="structure_declared" if unit else None,
            measurement_quantity=quantity,
            measurement_role=role,
            reset_semantics=reset,
            aggregation="sum_of_differences" if difference else "recorded_values" if raw else None,
            timestamp_basis="unix_utc",
            timestamp_position="observation"
            if raw
            else "interval_start"
            if difference and granularity == "hour"
            else None,
            recording_mode=series.recording_mode,
            limitations=tuple(limits),
            sources=tuple(sources),
        )

    def resolve(
        self,
        structure: LoxoneStructure,
        control: Control,
        state_name: str,
        value: object,
        companion_values: Mapping[str, object],
    ) -> tuple[StateSemantics, object | None]:
        if control.control_type == "PvProductionForecast" and state_name in PVPF_STATES:
            result = StateSemantics()
            result.value_type = "number"
            if state_name in PVPF_ENERGY_STATES:
                result.unit, result.measurement_quantity = "kWh", "energy"
                result.measurement_role = "predicted_pv_energy"
            elif state_name == "inputperiod":
                result.unit = "h"
            result.sources = [
                SemanticsSource(
                    "decoder_rule",
                    PVPF_DOCUMENT,
                    ("semantic_value", "unit", "measurement_quantity", "measurement_role"),
                    rule_id=f"PvProductionForecast.{state_name}.17_1.v1",
                    document_version="17.1",
                )
            ]
            result.sources_returned = result.sources_total = 1
            result.interpretation_status, result.reason = "partial", "value_unavailable"
            pv_decoded = None
            if value is not None:
                try:
                    pv_decoded = decode_pv_forecast(state_name, value, companion_values)
                    result.interpretation_status = "known"
                    result.reason = "documented_decoder"
                    if pv_decoded.get("status") == "incomplete":
                        result.interpretation_status, result.reason = (
                            "partial",
                            "companion_unavailable",
                        )
                except ValueError:
                    result.interpretation_status, result.reason = (
                        "invalid",
                        "invalid_documented_value",
                    )
            return result, pv_decoded
        manager = _resolve_energy_manager(structure, control, state_name, value)
        if manager is not None:
            return manager
        measurement = _resolve_measurement(control, state_name, value)
        if measurement is not None:
            return measurement
        result = StateSemantics()
        semantic_value: object | None = None
        family = ALERT_FAMILIES.get(control.control_type)
        if control.control_type == "SmokeAlarm" and state_name == "level":
            smoke_labels = ("no_alarm", "pre_alarm", "main_alarm")
            result.value_type = "integer"
            result.encoding = [SemanticsEncoding(i, label) for i, label in enumerate(smoke_labels)]
            result.encoding_total = result.encoding_returned = 3
            result.encoding_complete = True
            result.sources.extend(
                [
                    SemanticsSource(
                        "decoder_rule",
                        "https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf#page=126",
                        ("encoding.1", "encoding.2", "value_type")
                        + (
                            ("semantic_value.level", "semantic_value.alert_active")
                            if value in (1, 2) and not isinstance(value, bool)
                            else ()
                        ),
                        rule_id="SmokeAlarm.level.active.v1",
                        document_version="17.1",
                    ),
                    SemanticsSource(
                        "decoder_rule",
                        "https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/347",
                        ("encoding.0",)
                        + (
                            ("semantic_value.level", "semantic_value.alert_active")
                            if value == 0 and not isinstance(value, bool)
                            else ()
                        ),
                        rule_id="SmokeAlarm.level.zero_owner_assumption.2026-10-11",
                    ),
                ]
            )
            result.interpretation_status, result.reason = "partial", "value_unavailable"
            if value is not None:
                if (
                    isinstance(value, int | float)
                    and not isinstance(value, bool)
                    and value in (0, 1, 2)
                ):
                    raw_test = companion_values.get("testAlarm")
                    test_alarm = (
                        bool(raw_test)
                        if isinstance(raw_test, int | float)
                        and not isinstance(raw_test, bool)
                        and raw_test in (0, 1)
                        else None
                    )
                    semantic_value = {
                        "level": smoke_labels[int(value)],
                        "alert_active": value != 0,
                        "context": {
                            "test_alarm": test_alarm,
                            "acknowledged": None,
                            "signals_suppressed": None,
                        },
                    }
                    if test_alarm is not None:
                        result.sources.extend(
                            [
                                SemanticsSource(
                                    "decoder_rule",
                                    "https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf#page=126",
                                    ("semantic_value.context.test_alarm",),
                                    rule_id="SmokeAlarm.testAlarm.v1",
                                    document_version="17.1",
                                ),
                                SemanticsSource(
                                    "runtime_state",
                                    "states.testAlarm",
                                    ("semantic_value.context.test_alarm",),
                                    state_uuid=dict(islice(control.state_uuids, 100)).get(
                                        "testAlarm"
                                    ),
                                ),
                            ]
                        )
                    result.interpretation_status, result.reason = "known", "owner_approved_decoder"
                else:
                    result.interpretation_status, result.reason = (
                        "invalid",
                        "invalid_documented_value",
                    )
        if control.control_type == "Alarm" and state_name == "level":
            alarm_labels = (
                "inactive",
                "silent",
                "acoustic",
                "optical",
                "internal",
                "external",
                "remote",
            )
            result.value_type = "integer"
            result.encoding = [
                SemanticsEncoding(code, label) for code, label in enumerate(alarm_labels)
            ]
            result.encoding_total = result.encoding_returned = len(alarm_labels)
            result.encoding_complete = True
            result.sources.extend(
                (
                    SemanticsSource(
                        "decoder_rule",
                        "https://www.loxone.com/enen/wp-content/uploads/sites/3/2026/04/1700_Structure-File.pdf#page=28",
                        ("semantic_value.level", "encoding.codes_1_to_6"),
                        rule_id="Alarm.level.v1",
                        document_version="17.0",
                    ),
                    SemanticsSource(
                        "decoder_rule",
                        "https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/346#issuecomment-6103804884",
                        ("semantic_value.alert_active", "encoding.code_0", "value_type"),
                        rule_id="Alarm.level.v1",
                    ),
                )
            )
            result.interpretation_status, result.reason = "partial", "value_unavailable"
            if value is not None:
                if (
                    isinstance(value, int | float)
                    and not isinstance(value, bool)
                    and value in range(7)
                ):
                    semantic_value = {
                        "alert_active": value != 0,
                        "level": alarm_labels[int(value)],
                        "context": {
                            "test_alarm": None,
                            "acknowledged": None,
                            "signals_suppressed": None,
                        },
                    }
                    result.interpretation_status, result.reason = "known", "owner_approved_decoder"
                else:
                    result.interpretation_status, result.reason = (
                        "invalid",
                        "invalid_documented_value",
                    )
        if (
            family is not None
            and state_name == family.primary
            and control.control_type not in {"AalEmergency", "Alarm", "SmokeAlarm"}
        ):
            smart = control.control_type == "AalSmartAlarm"
            labels: tuple[str, ...] = (
                ("no_alarm", "immediate_alarm", "delayed_alarm")
                if smart
                else ("inactive", "acknowledged", "alarm", "urgent_alarm", "ems_alarm")
            )
            codes = (0, 1, 2) if smart else (0, 1, 2, 4, 8)
            result.value_type = "integer" if smart else "bitmask"
            result.encoding = [
                SemanticsEncoding(code, label) for code, label in zip(codes, labels, strict=True)
            ]
            result.encoding_total = result.encoding_returned = len(codes)
            result.encoding_complete = True
            result.sources.append(
                SemanticsSource(
                    "decoder_rule",
                    "https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf#page="
                    + ("27" if smart else "30"),
                    ("semantic_value", "encoding", "value_type"),
                    rule_id=control.control_type + "." + state_name + ".v1",
                    document_version="17.1",
                )
            )
            result.interpretation_status, result.reason = "partial", "value_unavailable"
            if value is not None:
                valid = (
                    isinstance(value, int | float)
                    and not isinstance(value, bool)
                    and (value in codes if smart else value in range(16))
                )
                if valid:
                    assert isinstance(value, int | float)
                    code = int(value)
                    semantic_value = {
                        "alert_active": code != 0 if smart else bool(code & 14),
                        "context": {
                            "test_alarm": None,
                            "acknowledged": None if smart else bool(code & 1),
                            "signals_suppressed": None,
                        },
                    }
                    if smart:
                        semantic_value["level"] = labels[code]
                        for name in family.optional:
                            raw = companion_values.get(name)
                            if name == "disableEndTime":
                                decoded = (
                                    raw
                                    if isinstance(raw, int | float)
                                    and not isinstance(raw, bool)
                                    and 0 <= raw <= 253402300799
                                    and (not isinstance(raw, float) or math.isfinite(raw))
                                    else None
                                )
                            else:
                                decoded = (
                                    bool(raw)
                                    if isinstance(raw, int | float | bool) and raw in (0, 1)
                                    else None
                                )
                            semantic_value[name] = decoded
                            if decoded is not None:
                                refs = dict(islice(control.state_uuids, 100))
                                result.sources.append(
                                    SemanticsSource(
                                        "runtime_state",
                                        "states." + name,
                                        ("semantic_value." + name,),
                                        state_uuid=refs.get(name),
                                    )
                                )
                    else:
                        semantic_value["alarm_types"] = [
                            label
                            for bit, label in zip(codes[2:], labels[2:], strict=True)
                            if code & bit
                        ]
                    result.interpretation_status, result.reason = "known", "documented_decoder"
                else:
                    result.interpretation_status, result.reason = (
                        "invalid",
                        "invalid_documented_value",
                    )
        if control.control_type == "AalEmergency" and state_name == "status":
            result.value_type = "integer"
            labels = ("normal_operation", "alarm_triggered", "reset_active", "temporarily_disabled")
            result.encoding = [SemanticsEncoding(i, label) for i, label in enumerate(labels)]
            result.encoding_total = result.encoding_returned = 4
            result.encoding_complete = True
            result.sources.append(
                SemanticsSource(
                    "decoder_rule",
                    "https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf#page=26",
                    ("semantic_value", "encoding", "value_type"),
                    rule_id="AalEmergency.status.v1",
                    document_version="17.1",
                )
            )
            result.interpretation_status, result.reason = "partial", "value_unavailable"
            if value is not None:
                if (
                    isinstance(value, int | float)
                    and not isinstance(value, bool)
                    and value in (0, 1, 2, 3)
                ):
                    semantic_value = {"status": labels[int(value)], "alert_active": value == 1}
                    result.interpretation_status, result.reason = "known", "documented_decoder"
                else:
                    result.interpretation_status, result.reason = (
                        "invalid",
                        "invalid_documented_value",
                    )
        if control.control_type in _FORMAT_TYPES and state_name == "value":
            result.display_format_total_length = control.format_total_length
            result.display_format_returned_length = (
                len(control.format) if control.format is not None else 0
            )
            result.display_format_truncated = (
                control.format_total_length is not None and control.format_total_length > 64
            )
            result.display_format_complete = (
                control.format_total_length is not None and not result.display_format_truncated
            )
            if control.format is not None:
                result.display_format = control.format
                result.sources.append(
                    SemanticsSource("structure_file", "details.format", ("display_format",))
                )
            if control.control_type == "UpDownAnalog" and all(
                v is not None for v in (control.minimum, control.maximum, control.step)
            ):
                assert (
                    control.minimum is not None
                    and control.maximum is not None
                    and control.step is not None
                )
                result.range = SemanticsRange(control.minimum, control.maximum, control.step)
                result.sources.append(
                    SemanticsSource("structure_file", "details.min/max/step", ("range",))
                )
            if result.sources:
                result.interpretation_status, result.reason = "partial", "metadata_only"
            if result.display_format_truncated:
                result.interpretation_status, result.reason = "partial", "metadata_truncated"
                result.sources.append(
                    SemanticsSource("structure_file", "details.format", ("display_format",))
                )
            invalid_fields = set(control.semantics_invalid_fields) & (
                {"format", "range"} if control.control_type == "UpDownAnalog" else {"format"}
            )
            if invalid_fields:
                result.interpretation_status, result.reason = (
                    "invalid",
                    "invalid_structure_metadata",
                )
                result.sources.append(
                    SemanticsSource("structure_file", "details", ("interpretation_status",))
                )

        if control.control_type == "StatusMonitor" and state_name == "inputStates":
            result.encoding = [
                SemanticsEncoding(s.status_id, s.name)
                for s in control.status_monitor_statuses[:100]
            ]
            result.encoding_total = control.status_monitor_status_total
            result.encoding_complete = (
                control.status_monitor_status_complete
                and len(control.status_monitor_statuses) <= 100
            )
            result.encoding_returned = len(result.encoding)
            result.encoding_truncated = len(control.status_monitor_statuses) > 100 or (
                result.encoding_total is not None and result.encoding_total > len(result.encoding)
            )
            result.positions = [
                SemanticsPosition(s.index, s.name) for s in control.status_monitor_inputs[:100]
            ]
            result.positions_total = control.status_monitor_input_total
            result.positions_complete = (
                control.status_monitor_input_complete and len(control.status_monitor_inputs) <= 100
            )
            result.positions_returned = len(result.positions)
            result.positions_truncated = len(control.status_monitor_inputs) > 100 or (
                result.positions_total is not None
                and result.positions_total > len(result.positions)
            )
            if result.encoding_total is not None or result.encoding:
                result.sources.append(
                    SemanticsSource("structure_file", "details.status", ("encoding",))
                )
            if result.positions_total is not None or result.positions:
                result.sources.append(
                    SemanticsSource("structure_file", "details.inputs", ("positions",))
                )
            if result.encoding or result.positions:
                result.interpretation_status, result.reason = "partial", "position_bound_metadata"
            if "status_monitor" in control.semantics_invalid_fields:
                result.interpretation_status, result.reason = (
                    "invalid",
                    "invalid_structure_metadata",
                )
            elif not result.encoding_complete or not result.positions_complete:
                result.reason = "incomplete_metadata"

        if control.control_type == "StatusMonitor" and (
            state_name == "inputStates" or state_name in _STATUS_COUNTS
        ):
            result.sources.extend(
                [
                    SemanticsSource(
                        "decoder_rule",
                        _STATUS_DOCUMENT + "#page=130",
                        ("semantic_value",),
                        rule_id=f"StatusMonitor.{state_name}.v1",
                        document_version="17.1",
                    ),
                    SemanticsSource(
                        "structure_file",
                        "details.inputs/status",
                        ("semantic_value",),
                    ),
                    SemanticsSource(
                        "runtime_state",
                        "states." + state_name,
                        ("semantic_value",),
                        state_uuid=dict(control.state_uuids).get(state_name),
                    ),
                ]
            )
            result.value_type = "string" if state_name == "inputStates" else "integer"
            if "status_monitor" in control.semantics_invalid_fields:
                result.interpretation_status, result.reason = (
                    "invalid",
                    "invalid_structure_metadata",
                )
            if value is None:
                if result.interpretation_status != "invalid":
                    result.interpretation_status, result.reason = "partial", "value_unavailable"
            else:
                semantic_value, invalid = decode_state_value(
                    structure, control, state_name, value, companion_values
                )
                if invalid:
                    result.interpretation_status, result.reason = (
                        "invalid",
                        "invalid_documented_value",
                    )
                elif "status_monitor" in control.semantics_invalid_fields:
                    result.interpretation_status, result.reason = (
                        "invalid",
                        "invalid_structure_metadata",
                    )
                elif isinstance(semantic_value, dict):
                    complete = semantic_value.get("mapping_complete") is True
                    result.interpretation_status = "known" if complete else "partial"
                    result.reason = "documented_decoder" if complete else "incomplete_metadata"

        if control.control_type == "WindowMonitor" and state_name == "windowStates":
            result.value_type = "string"
            result.sources.extend(
                [
                    SemanticsSource(
                        "decoder_rule",
                        WINDOW_DOCUMENT + "#page=152",
                        ("semantic_value",),
                        rule_id="WindowMonitor.windowStates.v1",
                        document_version="17.1",
                    ),
                    SemanticsSource("structure_file", "details.windows", ("semantic_value",)),
                    SemanticsSource(
                        "runtime_state",
                        "states.windowStates",
                        ("semantic_value",),
                        state_uuid=dict(control.state_uuids).get(state_name),
                    ),
                ]
            )
            result.interpretation_status, result.reason = "partial", "value_unavailable"
            if value is not None:
                semantic_value, invalid = decode_state_value(
                    structure, control, state_name, value, companion_values
                )
                if invalid:
                    result.interpretation_status, result.reason = (
                        "invalid",
                        "invalid_documented_value",
                    )
                elif isinstance(semantic_value, dict):
                    complete = semantic_value["mapping_complete"] is True
                    result.interpretation_status = "known" if complete else "partial"
                    result.reason = "documented_decoder" if complete else "incomplete_metadata"

        supported = (control.control_type == "Irrigation" and state_name in _IRRIGATION_RULES) or (
            control.control_type == "AlarmClock" and state_name in _ALARM_RULES
        )
        if supported:
            result.sources.append(
                SemanticsSource(
                    "decoder_rule",
                    _DOCUMENT,
                    ("semantic_value",),
                    rule_id=f"{control.control_type}.{state_name}.v1",
                )
            )
            result.interpretation_status, result.reason = "partial", "value_unavailable"
            if value is not None:
                semantic_value, invalid = decode_state_value(
                    structure, control, state_name, value, companion_values
                )
                result.interpretation_status = "invalid" if invalid else "known"
                result.reason = "invalid_documented_value" if invalid else "documented_decoder"
                if not invalid and isinstance(semantic_value, dict):
                    missing_companion = (
                        (
                            control.control_type == "Irrigation"
                            and state_name == "currentZone"
                            and semantic_value.get("status") == "zone"
                            and "zone_name" not in semantic_value
                        )
                        or (
                            control.control_type == "AlarmClock"
                            and state_name in {"currentEntry", "nextEntry"}
                            and semantic_value.get("status") == "entry"
                            and "entry" not in semantic_value
                        )
                        or (
                            control.control_type == "AlarmClock"
                            and state_name == "nextEntryMode"
                            and semantic_value.get("status") == "mode"
                            and "mode_name" not in semantic_value
                        )
                    )
                    if missing_companion:
                        result.interpretation_status, result.reason = (
                            "partial",
                            "companion_unavailable",
                        )
                    refs = dict(control.state_uuids)
                    if "zone_name" in semantic_value:
                        result.sources.append(
                            SemanticsSource(
                                "runtime_state",
                                "states.zones",
                                ("semantic_value.zone_name",),
                                state_uuid=refs.get("zones"),
                            )
                        )
                    if "entry" in semantic_value:
                        result.sources.append(
                            SemanticsSource(
                                "runtime_state",
                                "states.entryList",
                                ("semantic_value.entry",),
                                state_uuid=refs.get("entryList"),
                            )
                        )
                    if "mode_name" in semantic_value:
                        result.sources.append(
                            SemanticsSource(
                                "structure_file",
                                "global_metadata.operating_mode",
                                ("semantic_value.mode_name",),
                            )
                        )
            if state_name in {"rainActive", "isEnabled", "isAlarmActive", "confirmationNeeded"}:
                result.value_type = "boolean"
            elif state_name in {
                "ringingTime",
                "ringDuration",
                "prepareDuration",
                "snoozeTime",
                "snoozeDuration",
            }:
                result.unit = "s"
                result.value_type = "integer"
            if result.value_type or result.unit:
                result.sources.append(
                    SemanticsSource(
                        "decoder_rule",
                        _DOCUMENT,
                        ("value_type", "unit"),
                        rule_id=f"{control.control_type}.{state_name}.v1",
                    )
                )
        result.sources_returned = result.sources_total = len(result.sources)
        return result, semantic_value


_MAX_SEMANTIC_JSON_TEXT = 65_536
_MAX_SEMANTIC_ENTRIES = 100


class _SemanticValueError(ValueError):
    pass


def _semantic_json(value: object) -> object:
    if not isinstance(value, str) or len(value) > _MAX_SEMANTIC_JSON_TEXT:
        raise _SemanticValueError
    try:
        return json.loads(value)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise _SemanticValueError from exc


def _semantic_integer(value: object, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _SemanticValueError
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise _SemanticValueError from exc
    if not math.isfinite(number) or not number.is_integer():
        raise _SemanticValueError
    result = int(number)
    if not minimum <= result <= maximum:
        raise _SemanticValueError
    return result


def _semantic_number(value: object, *, minimum: float, maximum: float) -> float | int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _SemanticValueError
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise _SemanticValueError from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise _SemanticValueError
    return value


def _semantic_boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return bool(_semantic_integer(value, minimum=0, maximum=1))


def _semantic_text(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        raise _SemanticValueError
    return value


def _irrigation_zones(value: object) -> list[dict[str, object]]:
    raw = _semantic_json(value)
    if not isinstance(raw, list) or len(raw) > _MAX_SEMANTIC_ENTRIES:
        raise _SemanticValueError
    result: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise _SemanticValueError
        result.append(
            {
                "id": _semantic_integer(item.get("id"), minimum=0, maximum=99),
                "name": _semantic_text(item.get("name")),
                "duration_seconds": _semantic_integer(
                    item.get("duration"), minimum=0, maximum=31_536_000
                ),
                "set_by_logic": _semantic_boolean(item.get("setByLogic")),
            }
        )
    return result


def _alarm_entries(value: object) -> list[dict[str, object]]:
    raw = _semantic_json(value)
    if not isinstance(raw, Mapping) or len(raw) > _MAX_SEMANTIC_ENTRIES:
        raise _SemanticValueError
    result: list[dict[str, object]] = []
    for identifier, item in raw.items():
        if (
            not isinstance(identifier, str)
            or not identifier.isdecimal()
            or not isinstance(item, Mapping)
        ):
            raise _SemanticValueError
        entry_id = int(identifier)
        if not 0 <= entry_id <= 1_000_000:
            raise _SemanticValueError
        alarm_time = _semantic_integer(item.get("alarmTime"), minimum=0, maximum=86_399)
        modes = item.get("modes")
        if not isinstance(modes, list) or len(modes) > _MAX_SEMANTIC_ENTRIES:
            raise _SemanticValueError
        mode_ids = [_semantic_integer(mode, minimum=0, maximum=1000) for mode in modes]
        alarm_time_text = (
            f"{alarm_time // 3600:02d}:{alarm_time % 3600 // 60:02d}:{alarm_time % 60:02d}"
        )
        result.append(
            {
                "id": entry_id,
                "name": _semantic_text(item.get("name")),
                "active": _semantic_boolean(item.get("isActive")),
                "alarm_time_seconds": alarm_time,
                "alarm_time": alarm_time_text,
                "mode_ids": mode_ids,
                "night_light": _semantic_boolean(item.get("nightLight", False)),
                "daily": _semantic_boolean(item.get("daily", False)),
            }
        )
    return sorted(
        result,
        key=lambda item: _semantic_integer(item["id"], minimum=0, maximum=1_000_000),
    )


def _alarm_settings(value: object, *, sound: bool) -> dict[str, object]:
    raw = _semantic_json(value)
    if not isinstance(raw, Mapping) or len(raw) > 16:
        raise _SemanticValueError
    result: dict[str, object] = {}
    if sound:
        if "sound" in raw:
            result["sound_id"] = _semantic_integer(raw["sound"], minimum=0, maximum=1000)
        if "volume" in raw:
            result["volume"] = _semantic_number(raw["volume"], minimum=0, maximum=100)
        if "isSloping" in raw:
            result["sloping"] = _semantic_boolean(raw["isSloping"])
    else:
        if "beepUsed" in raw:
            result["beep_used"] = _semantic_boolean(raw["beepUsed"])
        if "brightInactive" in raw:
            result["brightness_inactive"] = _semantic_number(
                raw["brightInactive"], minimum=0, maximum=100
            )
        if "brightActive" in raw:
            result["brightness_active"] = _semantic_number(
                raw["brightActive"], minimum=0, maximum=100
            )
    return result


def _alarm_entry_reference(value: object, entries_value: object) -> dict[str, object]:
    entry_id = _semantic_integer(value, minimum=-1, maximum=1_000_000)
    if entry_id == -1:
        return {"status": "none"}
    result: dict[str, object] = {"status": "entry", "entry_id": entry_id}
    try:
        entry = next(
            (item for item in _alarm_entries(entries_value) if item["id"] == entry_id), None
        )
    except _SemanticValueError:
        entry = None
    if entry is not None:
        result["entry"] = entry
    return result


def _status_provenance(control: Control, state_name: str) -> dict[str, object]:
    return {
        "document": _STATUS_DOCUMENT,
        "document_version": "17.1",
        "pages": [130, 131],
        "rule_id": f"StatusMonitor.{state_name}.v1",
        "state_uuid": dict(control.state_uuids).get(state_name),
        "structure_fields": ["details.inputs", "details.status"],
    }


def _status_definition(control: Control, code: int) -> tuple[dict[str, object] | None, str]:
    # 255 is reserved for an integrated, unconfigured monitor, never a configured tuple.
    if code == 255:
        return None, "unmatched"
    matches = [s for s in control.status_monitor_statuses[:100] if s.status_id == code]
    if len(matches) != 1:
        return None, "ambiguous" if matches else "unmatched"
    item = matches[0]
    return {
        "status_id": item.status_id,
        "name": item.name,
        "priority": item.priority,
        "color": item.color,
        "uuid": item.uuid,
    }, "matched"


def _visible_status_input_types(structure: LoxoneStructure) -> dict[str, str]:
    """Use only already-visible controls; never expand navigation references or read states."""
    result: dict[str, str] = {}
    stack = [iter(structure.controls)]
    examined = 0
    while stack and examined < 1000:
        item = next(stack[-1], None)
        if item is None:
            stack.pop()
            continue
        examined += 1
        if item.is_hidden:
            continue
        result[item.uuid] = item.control_type
        stack.append(iter(item.subcontrols))
    return result


def _status_inputs(
    structure: LoxoneStructure, control: Control, value: object
) -> dict[str, object]:
    if not isinstance(value, str) or len(value) > _MAX_SEMANTIC_JSON_TEXT:
        raise _SemanticValueError
    total = value.count(",") + 1
    # maxsplit prevents unbounded list materialization; keep empty positions.
    tokens = value.split(",", _MAX_SEMANTIC_ENTRIES)[:_MAX_SEMANTIC_ENTRIES]
    inputs = {s.index: s for s in control.status_monitor_inputs[:100]}
    types = _visible_status_input_types(structure)
    expected = control.status_monitor_input_total
    positions = min(max(total, expected or 0), _MAX_SEMANTIC_ENTRIES)
    items: list[dict[str, object]] = []
    decoding_complete = True
    for index in range(positions):
        token = tokens[index] if index < len(tokens) else None
        item = inputs.get(index)
        code: int | None = None
        definition: dict[str, object] | None = None
        mapping = "missing_value" if token is None else "invalid"
        if token is not None and re.fullmatch(r"[0-9]{1,3}", token):
            code = int(token)
            if code <= 255:
                definition, mapping = _status_definition(control, code)
            else:
                code = None
        if token is not None and code is None:
            decoding_complete = False
        source = None
        aggregated: bool | None = None
        if item is not None:
            source = {
                "index": item.index,
                "name": item.name,
                "install_place": item.install_place,
                "uuid": item.uuid,
                "room_uuid": item.room_uuid,
            }
            if item.uuid in types:
                aggregated = types[item.uuid] == "StatusMonitor"
        # Keep independent input and definition resolution; neither invents source wiring.
        items.append(
            {
                "index": index,
                "raw_token": token[:200] if token is not None else None,
                "raw_token_truncated": token is not None and len(token) > 200,
                "status_id": code,
                "input": source,
                "configured_status": definition,
                "mapping_status": mapping,
                "input_resolved": item is not None,
                "is_aggregated": aggregated,
            }
        )
    truncated = max(total, expected or 0) > positions
    mapping_complete = (
        decoding_complete
        and not truncated
        and expected == total
        and control.status_monitor_input_complete
        and control.status_monitor_status_complete
        and all(v["mapping_status"] == "matched" and v["input_resolved"] for v in items)
        and "status_monitor" not in control.semantics_invalid_fields
    )
    result: dict[str, object] = {
        "kind": "input_states",
        "provenance": _status_provenance(control, "inputStates"),
        "inputs": items,
        "values_total": total,
        "positions_returned": len(items),
        "truncated": truncated,
        "decoding_complete": decoding_complete and not truncated,
        "mapping_complete": mapping_complete,
        "invalid_values": any(v["mapping_status"] == "invalid" for v in items),
        "input_metadata_complete": control.status_monitor_input_complete,
        "status_metadata_complete": control.status_monitor_status_complete,
    }
    # Bound enrichment bytes independently of the caller's raw-value/delivery budget.
    while items and len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 16_384:
        items.pop()
        result.update(
            positions_returned=len(items),
            truncated=True,
            decoding_complete=False,
            mapping_complete=False,
        )
    return result


def decode_state_value(
    structure: LoxoneStructure,
    control: Control,
    state_name: str,
    value: object,
    companion_values: Mapping[str, object],
) -> tuple[object | None, bool]:
    try:
        if control.control_type == "PvProductionForecast" and state_name in PVPF_STATES:
            return decode_pv_forecast(state_name, value, companion_values), False
        if control.control_type == "WindowMonitor" and state_name == "windowStates":
            decoded_window = decode_window_states(control, value)
            return decoded_window, decoded_window is None or decoded_window[
                "invalid_values"
            ] is True
        if control.control_type == "StatusMonitor":
            if state_name == "inputStates":
                decoded = _status_inputs(structure, control, value)
                return decoded, decoded["invalid_values"] is True
            if state_name in _STATUS_COUNTS:
                code = _STATUS_COUNTS[state_name]
                count = _semantic_integer(value, minimum=0, maximum=9_007_199_254_740_991)
                definition, mapping = _status_definition(control, code)
                return {
                    "kind": "status_count",
                    "provenance": _status_provenance(control, state_name),
                    "status_id": code,
                    "count": count,
                    "configured_status": definition,
                    "mapping_status": mapping,
                    "mapping_complete": mapping == "matched"
                    and control.status_monitor_status_complete
                    and len(control.status_monitor_statuses) <= 100
                    and "status_monitor" not in control.semantics_invalid_fields,
                }, False
        if control.control_type == "Irrigation":
            if state_name == "zones":
                return _irrigation_zones(value), False
            if state_name == "rainActive":
                return _semantic_boolean(value), False
            if state_name == "currentZone":
                zone_id = _semantic_integer(value, minimum=-1, maximum=8)
                if zone_id == -1:
                    return {"status": "off"}, False
                if zone_id == 8:
                    return {"status": "all"}, False
                result: dict[str, object] = {"status": "zone", "zone_id": zone_id}
                try:
                    zone = next(
                        (
                            item
                            for item in _irrigation_zones(companion_values.get("zones"))
                            if item["id"] == zone_id
                        ),
                        None,
                    )
                except _SemanticValueError:
                    zone = None
                if zone is not None:
                    result["zone_name"] = zone["name"]
                return result, False

        if control.control_type == "AlarmClock":
            if state_name in {"isEnabled", "isAlarmActive", "confirmationNeeded"}:
                return _semantic_boolean(value), False
            if state_name == "entryList":
                return _alarm_entries(value), False
            if state_name in {"currentEntry", "nextEntry"}:
                return _alarm_entry_reference(value, companion_values.get("entryList")), False
            if state_name == "nextEntryMode":
                mode_id = _semantic_integer(value, minimum=-1, maximum=1000)
                if mode_id == -1:
                    return {"status": "none"}, False
                result = {"status": "mode", "mode_id": mode_id}
                mode_name = next(
                    (
                        item.name
                        for item in structure.global_metadata
                        if item.kind == "operating_mode" and item.identifier == str(mode_id)
                    ),
                    None,
                )
                if mode_name is not None:
                    result["mode_name"] = mode_name
                return result, False
            if state_name in {
                "ringingTime",
                "ringDuration",
                "prepareDuration",
                "snoozeTime",
                "snoozeDuration",
            }:
                return {"seconds": _semantic_integer(value, minimum=0, maximum=31_536_000)}, False
            if state_name == "nextEntryTime":
                seconds = _semantic_integer(value, minimum=-1, maximum=4_000_000_000)
                if seconds <= 0:
                    return {"status": "none"}, False
                return {"status": "scheduled", "at": _loxone_time(seconds)}, False
            if state_name == "deviceState":
                state = _semantic_integer(value, minimum=0, maximum=2)
                return {"status": {0: "not_connected", 1: "offline", 2: "online"}[state]}, False
            if state_name == "deviceSettings":
                return _alarm_settings(value, sound=False), False
            if state_name == "wakeAlarmSoundSettings":
                return _alarm_settings(value, sound=True), False
    except ValueError:
        return None, True
    return None, False


def _valid_measurement_number(value: object, *, binary: bool) -> bool:
    try:
        if binary:
            _semantic_integer(value, minimum=0, maximum=1)
        else:
            _semantic_number(value, minimum=-math.inf, maximum=math.inf)
    except _SemanticValueError:
        return False
    return True
