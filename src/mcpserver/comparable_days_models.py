"""Typed comparable-day contracts; evidence rules are never caller supplied."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator

DayString = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=10)]
Reason = Annotated[str, Field(min_length=1, max_length=128)]
Nonnegative = Annotated[FiniteFloat, Field(ge=0)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ComparableDayOptions(Contract):
    reference_day: DayString
    start_hour: int = Field(default=0, ge=0, le=23)
    end_hour: int = Field(default=24, ge=1, le=24)
    maximum_seasonal_days: int = Field(default=30, ge=0, le=30)
    radiation_relative_tolerance: FiniteFloat = Field(default=0.15, gt=0, le=0.15)
    temperature_tolerance_c: FiniteFloat = Field(default=3.0, gt=0, le=3)

    @field_validator("reference_day")
    @classmethod
    def calendar_day(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def ordered_window(self) -> "ComparableDayOptions":
        if self.start_hour >= self.end_hour:
            raise ValueError("common local window must be nonempty")
        return self


class UsedDayOptions(Contract):
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)
    maximum_seasonal_days: int = Field(ge=0, le=30)
    radiation_relative_tolerance: FiniteFloat = Field(gt=0, le=0.15)
    temperature_tolerance_c: FiniteFloat = Field(gt=0, le=3)


class DaySourceSummary(Contract):
    radiation_wh_m2: Nonnegative
    matched_sample_mean_c: FiniteFloat
    pv_wh: Nonnegative | None
    pv_evidence: Literal[
        "qualified",
        "rule_unverified",
        "rule_changed",
        "intervals_incomplete",
        "values_invalid",
        "derived_numeric_overflow",
    ]


class ComparableDayCandidate(DaySourceSummary):
    day: DayString
    seasonal_distance_days: int = Field(ge=0, le=30)
    radiation_relative_difference: Nonnegative
    temperature_difference_c: Nonnegative
    pv_absolute_difference_wh: FiniteFloat | None
    pv_relative_difference: FiniteFloat | None
    normalized_weather_distance: Nonnegative


class ComparableDayExclusion(Contract):
    day: DayString
    reason: Reason


class ComparableDayGroup(Contract):
    count: int = Field(ge=3, le=30)
    median_pv_wh: Nonnegative
    minimum_pv_wh: Nonnegative
    maximum_pv_wh: Nonnegative
    absolute_difference_wh: FiniteFloat
    relative_difference: FiniteFloat | None
    check_candidate: bool


class ComparableDaysResult(Contract):
    method_version: Literal["comparable_days.v1"]
    status: Literal["partial", "insufficient_evidence"]
    reference_day: DayString
    timezone: str = Field(min_length=1, max_length=64)
    common_hour_positions: list[Annotated[int, Field(ge=0, le=23)]] = Field(max_length=24)
    options: UsedDayOptions
    reference: DaySourceSummary | None = None
    candidates: list[ComparableDayCandidate] = Field(max_length=30)
    exclusions: list[ComparableDayExclusion] = Field(max_length=30)
    group: ComparableDayGroup | None
    group_minimum_days: Literal[3]
    advisory_relative_threshold: FiniteFloat = Field(ge=-0.2, le=-0.2)
    advisory_threshold_comparison: Literal["strictly_less_than"]
    limitations: list[Reason] = Field(max_length=32)
