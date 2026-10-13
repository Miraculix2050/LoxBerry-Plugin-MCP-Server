import json

import pytest
from pydantic import ValidationError
from test_comparable_days import compare, day

from mcpserver.comparable_days_models import ComparableDayOptions, ComparableDaysResult


@pytest.mark.parametrize(
    "update",
    [
        {"reference_day": "2026-02-30"},
        {"start_hour": True},
        {"start_hour": 14, "end_hour": 10},
        {"radiation_relative_tolerance": float("nan")},
        {"temperature_tolerance_c": float("inf")},
        {"maximum_seasonal_days": 31},
        {"radiation_relative_tolerance": 0.16},
        {"temperature_tolerance_c": 3.1},
        {"radiation_rule": "user-asserted-proof"},
    ],
)
def test_input_contract_rejects_invalid_window_numbers_and_claimed_proof(update):
    with pytest.raises(ValidationError):
        ComparableDayOptions.model_validate({"reference_day": "2026-07-01", **update})


def test_typed_output_roundtrip_preserves_pairwise_and_group_results():
    result = compare([day(0, pv=799), day(1), day(2), day(3)])
    typed = ComparableDaysResult.model_validate(result)
    assert typed.group.check_candidate is True
    assert len(typed.candidates) == 3
    assert ComparableDaysResult.model_validate_json(typed.model_dump_json()) == typed
    assert len(typed.model_dump_json().encode()) < 64 * 1024


def test_result_contract_does_not_accept_unbounded_candidate_pages_or_nonfinite_metrics():
    result = compare([day(), day(1)])
    result["candidates"] *= 31
    with pytest.raises(ValidationError):
        ComparableDaysResult.model_validate(result)
    result["candidates"] = result["candidates"][:1]
    result["candidates"][0]["pv_wh"] = float("inf")
    with pytest.raises(ValidationError):
        ComparableDaysResult.model_validate(result)


def test_schema_keeps_unknown_reference_and_group_explicit():
    schema = ComparableDaysResult.model_json_schema()
    assert "group" in schema["required"]
    assert "reference" not in schema["required"]
    assert (
        json.loads(ComparableDayOptions(reference_day="2026-07-01").model_dump_json())[
            "radiation_relative_tolerance"
        ]
        == 0.15
    )
