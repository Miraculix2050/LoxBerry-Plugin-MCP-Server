from __future__ import annotations

import pytest
from pydantic import ValidationError

from mcpserver.load_flexibility import LoadFlexibility, LocalLoadWindow


def flexibility(**changes):
    return LoadFlexibility.model_validate(
        {
            "timezone": "Europe/Berlin",
            "windows": [{"weekdays": [0, 1, 2, 3, 4], "start": "10:00", "end": "16:00"}],
            "latest_completion": "17:00",
            "duration_seconds": 7200,
            "interruptible": False,
            "minimum_run_seconds": 7200,
            "minimum_off_seconds": 3600,
            "operating_binding_id": "load-active",
            "energy_profile_origin": "observed_intervals",
            "rationale": "Owner-confirmed operating constraints",
            **changes,
        }
    )


def test_typed_load_constraints_preserve_explicit_origin_and_native_lock_policy():
    value = flexibility()
    assert value.native_lock_policy == "never_override"
    assert value.declared_cycle_energy_wh is None
    assert value.energy_profile_origin == "observed_intervals"
    assert value.cycle_identity == "active_episode_only"
    assert flexibility(energy_profile_origin="user_declared", declared_cycle_energy_wh=1234.5)


@pytest.mark.parametrize(
    "changes",
    [
        {"timezone": "Not/AZone"},
        {"windows": []},
        {"latest_completion": "24:00"},
        {"duration_seconds": True},
        {"duration_seconds": 0},
        {"duration_seconds": 86401},
        {"interruptible": "false"},
        {"minimum_run_seconds": 7201},
        {"minimum_off_seconds": -1},
        {"completion_day_offset": True},
        {"completion_day_offset": False},
        {"completion_day_offset": 1.0},
        {"operating_binding_id": "../private"},
        {"energy_profile_origin": "raw_delivery"},
        {"energy_profile_origin": "user_declared"},
        {"declared_cycle_energy_wh": 1000.0},
        {"energy_profile_origin": "user_declared", "declared_cycle_energy_wh": float("inf")},
        {"rationale": "private\ntext"},
        {"native_lock_policy": "ignore"},
        {"cycle_identity": "native_program_verified"},
    ],
)
def test_load_constraints_reject_ambiguous_or_unsafe_declarations(changes):
    with pytest.raises((ValueError, ValidationError)):
        flexibility(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"weekdays": [0, 0]},
        {"weekdays": [7]},
        {"weekdays": [True]},
        {"end": "10:00"},
        {"start": "23:00", "end": "01:00"},
        {"end_day_offset": 1, "end": "11:00"},
        {"end_day_offset": True},
        {"end_day_offset": 1.0},
        {"end": "24:00"},
    ],
)
def test_local_windows_have_explicit_weekdays_and_midnight_boundary(changes):
    with pytest.raises(ValidationError):
        LocalLoadWindow(
            weekdays=changes.pop("weekdays", [0]),
            start=changes.pop("start", "10:00"),
            end=changes.pop("end", "16:00"),
            **changes,
        )


def test_overnight_window_requires_explicit_next_day_and_normalizes_weekdays():
    value = LocalLoadWindow(weekdays=[6, 0], start="23:00", end="01:00", end_day_offset=1)
    assert value.weekdays == [0, 6]
