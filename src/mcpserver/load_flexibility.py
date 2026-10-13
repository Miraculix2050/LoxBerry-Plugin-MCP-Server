"""Explicit load constraints; declarations never establish measurement semantics."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mcpserver.loxone.history_evidence import timezone


def clock_minutes(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


class LocalLoadWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    weekdays: list[int] = Field(min_length=1, max_length=7)
    start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end_day_offset: Literal[0, 1] = 0

    @field_validator("end_day_offset", mode="before")
    @classmethod
    def explicit_offset(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("load_day_offset_invalid")
        return value

    @field_validator("weekdays")
    @classmethod
    def unique_days(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value) or any(not 0 <= day <= 6 for day in value):
            raise ValueError("load_window_weekdays_invalid")
        return sorted(value)

    @model_validator(mode="after")
    def interval(self) -> LocalLoadWindow:
        length = clock_minutes(self.end) + 1440 * self.end_day_offset - clock_minutes(self.start)
        if not 0 < length <= 1440:
            raise ValueError("load_window_duration_invalid")
        return self


class LoadFlexibility(BaseModel):
    """Whole-binding confirmation is required; no device operation is authorized."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    timezone: str = Field(min_length=1, max_length=128)
    windows: list[LocalLoadWindow] = Field(min_length=1, max_length=16)
    latest_completion: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    completion_day_offset: Literal[0, 1] = 0
    duration_seconds: int = Field(ge=1, le=86400)
    interruptible: bool
    minimum_run_seconds: int = Field(ge=0, le=86400)
    minimum_off_seconds: int = Field(ge=0, le=86400)
    operating_binding_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    cycle_identity: Literal["active_episode_only", "user_confirmed_cycle"] = "active_episode_only"
    energy_profile_origin: Literal["observed_intervals", "user_declared"]
    declared_cycle_energy_wh: float | None = Field(default=None, gt=0, le=1_000_000_000)
    rationale: str = Field(min_length=1, max_length=256)
    native_lock_policy: Literal["never_override"] = "never_override"

    @field_validator("completion_day_offset", mode="before")
    @classmethod
    def explicit_offset(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("load_day_offset_invalid")
        return value

    @field_validator("timezone")
    @classmethod
    def local_timezone(cls, value: str) -> str:
        timezone(value)
        return value

    @field_validator("rationale")
    @classmethod
    def safe_text(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError("load_profile_text_invalid")
        return value

    @model_validator(mode="after")
    def constraints(self) -> LoadFlexibility:
        if self.minimum_run_seconds > self.duration_seconds:
            raise ValueError("load_minimum_run_exceeds_duration")
        declared = self.energy_profile_origin == "user_declared"
        if declared != (self.declared_cycle_energy_wh is not None):
            raise ValueError("load_energy_provenance_invalid")
        return self
