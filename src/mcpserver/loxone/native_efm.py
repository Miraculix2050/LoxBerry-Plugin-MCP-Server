"""Shape-validated native EFM projections; no inferred units or balance calculations."""

from __future__ import annotations

import json
import math
from typing import Any, Literal

from pydantic import BaseModel, Field

from mcpserver.loxone.state_semantics import SemanticsSource

type NativeResultView = Literal["actual", "day", "week", "month", "year", "lifetime"]
VIEWS = frozenset({"actual", "day", "week", "month", "year", "lifetime"})
REFERENCE_FIRMWARE = "17.2.8.28"  # Historical decoder provenance, not an admission rule.
MAX_OUTER_BYTES = 32 * 1024
MAX_VALUE_BYTES = 16 * 1024
_ACTUAL = ("Gpwr", "Ppwr", "Spwr", "Cpwr", "Rest")
_PERIOD = ("Export", "Import", "Production", "Charge", "Discharge", "Consumption", "Income")


class NativeEfmError(ValueError):
    """Fixed source diagnostics, never source text."""


class NativeEfmField(BaseModel):
    name: str
    status: Literal["present", "missing", "invalid"]
    value: float | None = None
    unit: Literal["W", "kW"] | None = None
    unit_origin: Literal["configured_display_format"] | None = None
    measurement_quantity: Literal["power"] | None = None
    measurement_role: (
        Literal["grid_power", "production_power", "storage_power", "load_power"] | None
    ) = None
    interpretation_status: Literal["partial", "unknown"] = "unknown"
    scale: None = None
    sign_convention: None = None
    currency: None = None


class NativeEfmResult(BaseModel):
    source_kind: Literal["native_efm_result"] = "native_efm_result"
    rule_version: Literal["native_efm_17_2_8_28.v1"] = "native_efm_17_2_8_28.v1"
    schema_version: Literal["native_efm_result.v1", "native_efm_result.v2"] = "native_efm_result.v1"
    semantic_rule_version: (
        Literal[
            "native_efm_actual_semantics_17_2_8_28.v1",
            "native_efm_actual_semantics_17_2_8_28.v2",
        ]
        | None
    ) = None
    source_metadata_status: Literal[
        "not_requested", "not_applicable", "missing", "invalid", "unsupported", "stable", "changed"
    ] = "not_requested"
    semantic_sources: list[SemanticsSource] = Field(default_factory=list, max_length=8)
    report_applicability: (
        Literal["current_snapshot", "current_calendar_period", "lifetime_accumulator"] | None
    ) = None
    historical_date_selection_supported: Literal[False] = False
    report_limitations: list[str] = Field(default_factory=list, max_length=16)
    firmware: str = Field(
        default=REFERENCE_FIRMWARE, max_length=23, pattern=r"^[0-9]{1,5}(?:\.[0-9]{1,5}){3}$"
    )
    view: NativeResultView
    retrieved_at: str
    fields: list[NativeEfmField] = Field(max_length=7)
    omitted_source_fields: int = Field(ge=0, le=16)
    field_delivery_complete: bool
    reference_delivery: Literal["not_requested"] = "not_requested"
    semantic_complete: Literal[False] = False
    observation_freshness: Literal["unknown"] = "unknown"
    retrieval_freshness: Literal["current"] = "current"
    period_kind: NativeResultView
    period_completion: Literal["running", "unknown", "not_applicable"]
    period_start: None = None
    period_end: None = None
    timezone: None = None
    period_boundaries: Literal["unknown"] = "unknown"
    calculation_provenance: Literal["loxone"] = "loxone"


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NativeEfmError("native_efm_duplicate_key")
        result[key] = value
    return result


def decode_native_efm(
    value: object, view: NativeResultView, *, retrieved_at: str, firmware: str = REFERENCE_FIRMWARE
) -> NativeEfmResult:
    """Accept only the evidenced LL.value JSON text with a bounded flat object."""
    if view not in VIEWS:
        raise NativeEfmError("native_efm_invalid_view")
    if not isinstance(value, str):
        raise NativeEfmError("native_efm_invalid_shape")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        raise NativeEfmError("native_efm_invalid_shape") from None
    if size > MAX_VALUE_BYTES:
        raise NativeEfmError("native_efm_response_too_large")
    try:
        document = json.loads(value, object_pairs_hook=_pairs)
    except NativeEfmError:
        raise
    except (ValueError, RecursionError):
        raise NativeEfmError("native_efm_invalid_shape") from None
    if not isinstance(document, dict) or len(document) > 16:
        raise NativeEfmError("native_efm_invalid_shape")
    for item in document.values():
        if isinstance(item, dict | list):
            raise NativeEfmError("native_efm_invalid_shape")
        if type(item) in {int, float}:
            try:
                finite = math.isfinite(item)
            except OverflowError:
                finite = False
            if not finite:
                raise NativeEfmError("native_efm_nonfinite_value")
    names = _ACTUAL if view == "actual" else _PERIOD
    fields = []
    for name in names:
        present = name in document
        numeric = present and type(document[name]) in {int, float}
        fields.append(
            NativeEfmField(
                name=name,
                status="present" if numeric else "invalid" if present else "missing",
                value=float(document[name]) if numeric else None,
            )
        )
    return NativeEfmResult(
        firmware=firmware,
        view=view,
        retrieved_at=retrieved_at,
        period_kind=view,
        period_completion=(
            "not_applicable" if view == "actual" else "unknown" if view == "lifetime" else "running"
        ),
        fields=fields,
        omitted_source_fields=sum(name not in names for name in document),
        field_delivery_complete=all(field.status == "present" for field in fields),
    )
