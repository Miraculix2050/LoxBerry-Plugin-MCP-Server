from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from mcpserver.history_analysis import HistoryAnalysisDeadline
from mcpserver.solar_forecast import (
    ForecastEvidenceError,
    SolarWindowOptions,
    parse_local_forecast,
    sampled_solar_windows,
)

NOW = datetime(2026, 10, 13, 12, tzinfo=UTC).timestamp()


def document(values=(100, 300, 500, 0)):
    return {
        "generatedAt": "2026-10-13T13:10:06",
        "location": {
            "timezone": "Europe/Berlin",
            "latitude": 48.123456,
            "longitude": 10.987654,
            "city": "PRIVATE_LOCATION",
        },
        "visualcrossing": {
            "schemaVersion": "v1.0",
            "grabberScript": "grabber_visualcrossing.pl",
            "apiKey": "PRIVATE_CREDENTIAL",
        },
        "hourlyforecast": [
            {
                "time": {
                    "datetime": datetime.fromtimestamp(NOW + (index + 1) * 3600, UTC).isoformat(),
                    "epoch": int(NOW + (index + 1) * 3600),
                },
                "solarRadiation": value,
            }
            for index, value in enumerate(values)
        ],
    }


def valid_document(values=(100, 300, 500, 0)):
    result = document(values)
    for row in result["hourlyforecast"]:
        row["time"]["datetime"] = (
            datetime.fromtimestamp(row["time"]["epoch"], UTC)
            .astimezone(ZoneInfo("Europe/Berlin"))
            .isoformat()
        )
    return result


def parse(data=None, *, origin="http://synthetic.local"):
    return parse_local_forecast(
        json.dumps(data if data is not None else valid_document()).encode(),
        publication_time=NOW - 60,
        target_origin=origin,
        now=NOW,
        deadline=time.monotonic() + 5,
    )


def options(**changes):
    return SolarWindowOptions.model_validate(
        {
            "start": datetime.fromtimestamp(NOW + 3600, UTC).isoformat(),
            "end": datetime.fromtimestamp(NOW + 5 * 3600, UTC).isoformat(),
            "timezone": "Europe/Berlin",
            **changes,
        }
    )


def windows(data=None, **changes):
    return sampled_solar_windows(
        parse(data), options(**changes), now=NOW, deadline=time.monotonic() + 5
    )


def test_documented_units_rank_samples_without_pv_energy_or_private_metadata():
    forecast = parse()
    result = sampled_solar_windows(
        forecast, options(duration_hours=2), now=NOW, deadline=time.monotonic() + 5
    )
    assert result.status == "partial" and result.unit == "W/m²"
    assert result.windows[0].mean_sample_irradiance_w_m2 == 400
    assert result.windows[0].sample_count == 2 and not result.windows[0].samples
    assert result.planning_status == "weather_guidance_only"
    assert result.provider_issued_at is None and result.forecast_confidence is None
    wire = result.model_dump_json()
    for private in (
        "PRIVATE_LOCATION",
        "PRIVATE_CREDENTIAL",
        "48.123456",
        "10.987654",
        forecast.fingerprint,
        forecast.document_digest,
    ):
        assert private not in wire


def test_fingerprint_tracks_location_timezone_and_target_not_changing_predictions():
    first = parse()
    assert parse(valid_document((200, 100, 0, 0))).fingerprint == first.fingerprint
    assert parse(origin="http://different.local").fingerprint != first.fingerprint
    changed = valid_document()
    changed["location"]["latitude"] = 48.0
    assert parse(changed).fingerprint != first.fingerprint


@pytest.mark.parametrize(
    "value,issue",
    [
        (-1, "negative_irradiance"),
        (None, "missing_irradiance"),
        (True, "non_numeric_irradiance"),
        ("PRIVATE_CREDENTIAL", "non_numeric_irradiance"),
        (float("inf"), "non_finite_irradiance"),
        (10**1000, "non_finite_irradiance"),
    ],
)
def test_invalid_point_is_visible_but_other_samples_remain_usable(value, issue):
    forecast = parse(valid_document((value, 300, 500, 0)))
    result = sampled_solar_windows(forecast, options(), now=NOW, deadline=time.monotonic() + 5)
    assert result.invalid_point_count == 1 and result.diagnostics[0].issue == issue
    assert result.windows and result.windows[0].mean_sample_irradiance_w_m2 == 500
    assert "PRIVATE_CREDENTIAL" not in result.model_dump_json()


def test_negative_raw_number_is_retained_in_bounded_diagnostics():
    result = windows(valid_document((-1, 300, 500, 0)))
    assert result.diagnostics[0].raw_number == -1
    forecast = parse(valid_document(tuple(-1 for _ in range(25))))
    assert (
        forecast.invalid_points == 25
        and len(forecast.diagnostics) == 16
        and forecast.diagnostics_truncated
    )


def test_inexact_large_json_integer_is_diagnosed_instead_of_collapsing_candidate_order():
    forecast = parse(valid_document((9007199254740992, 9007199254740993, 100, 0)))
    assert forecast.invalid_points == 1
    assert forecast.diagnostics[0].issue == "numeric_precision_not_supported"
    assert forecast.diagnostics[0].raw_numeric_text == "9007199254740993"


def test_derived_sample_mean_underflow_is_a_limitation_not_an_exception():
    result = windows(valid_document((5e-324, 0, 0)), duration_hours=3)
    assert not result.windows
    assert "sample_mean_not_representable" in result.limitations


def test_decimal_literal_precision_is_checked_before_json_float_rounding():
    payload = (
        json.dumps(valid_document((0.1, 123456789, 500, 0)))
        .replace("123456789", "9007199254740993.0")
        .encode()
    )
    forecast = parse_local_forecast(
        payload,
        publication_time=NOW - 60,
        target_origin="http://synthetic.local",
        now=NOW,
        deadline=time.monotonic() + 5,
    )
    assert forecast.invalid_points == 1
    assert forecast.points[0][1] == 0.1
    assert forecast.diagnostics[0].raw_numeric_text == "9007199254740993.0"


def test_threshold_cannot_silently_round_an_inexact_integer():
    with pytest.raises(ValidationError):
        options(minimum_sample_irradiance_w_m2=9007199254740993)


def test_duplicate_timestamp_is_excluded_even_when_one_duplicate_is_invalid():
    data = valid_document((100, -1, 500, 0))
    data["hourlyforecast"][1]["time"] = data["hourlyforecast"][0]["time"].copy()
    forecast = parse(data)
    assert forecast.invalid_points == 2 and len(forecast.points) == 2
    assert {d.issue for d in forecast.diagnostics} == {"negative_irradiance", "duplicate_timestamp"}


def test_missing_or_bad_hour_does_not_bridge_a_window():
    assert not windows(valid_document((100, None, 500, 0)), duration_hours=3).windows
    data = valid_document()
    data["hourlyforecast"][1]["time"]["epoch"] += 1
    forecast = parse(data)
    assert forecast.diagnostics[0].issue == "epoch_or_offset_mismatch"
    assert not sampled_solar_windows(
        forecast, options(duration_hours=3), now=NOW, deadline=time.monotonic() + 5
    ).windows


def test_source_offsets_are_verified_against_iana_not_assumed_from_hour_index():
    forecast = parse(document())
    assert forecast.invalid_points == 4 and not forecast.points
    data = valid_document()
    data["hourlyforecast"][0]["hour"] = 999
    assert parse(data).points == parse().points


def test_generation_field_is_not_a_channel_for_foreign_text_or_credentials():
    data = valid_document()
    data["generatedAt"] = "PRIVATE_CREDENTIAL_T"
    assert parse(data).source_reported_generated_at is None


def test_nonstandard_timestamp_forms_do_not_bypass_rfc3339_contract():
    with pytest.raises(ForecastEvidenceError, match="invalid_timestamp"):
        windows(start="2026-W42-2T13:00:00+00:00")


@pytest.mark.parametrize(
    "changes",
    [
        {"duration_hours": True},
        {"duration_hours": 1.0},
        {"duration_hours": 0},
        {"duration_hours": 25},
        {"minimum_sample_irradiance_w_m2": True},
        {"minimum_sample_irradiance_w_m2": -1.0},
        {"source": "http://arbitrary.local"},
        {"path": "/etc/passwd"},
    ],
)
def test_future_options_are_strict_bounded_and_have_no_free_file_or_url(changes):
    with pytest.raises(ValidationError):
        options(**changes)


def test_past_ranges_excessive_horizons_and_invalid_timezone_fail_closed():
    with pytest.raises(ForecastEvidenceError, match="invalid_future_window"):
        windows(start=datetime.fromtimestamp(NOW - 1, UTC).isoformat())
    with pytest.raises(ForecastEvidenceError, match="invalid_future_window"):
        windows(end=datetime.fromtimestamp(NOW + 33 * 86400, UTC).isoformat())
    with pytest.raises(ForecastEvidenceError, match="invalid_future_timezone"):
        windows(timezone="unverified")


def test_zero_only_sequences_do_not_claim_solar_opportunity_and_samples_are_opt_in():
    assert not windows(valid_document((0, 0, 0, 0))).windows
    result = windows(include_samples=True)
    assert result.windows[0].samples[0].irradiance_w_m2 == 500


def test_mean_ranking_preserves_small_terms_beside_large_values():
    result = windows(valid_document((1e100, 1e-10, 1e100, 2e-10)), duration_hours=2)
    assert result.windows[0].start == datetime.fromtimestamp(
        NOW + 3 * 3600, UTC
    ).isoformat().replace("+00:00", "Z")


def test_duplicates_unsupported_sources_size_and_clock_bounds_are_closed():
    with pytest.raises(ForecastEvidenceError, match="duplicate_json_key"):
        parse_local_forecast(
            b'{"location":{},"location":{}}',
            publication_time=NOW,
            now=NOW,
            target_origin="http://synthetic.local",
            deadline=time.monotonic() + 5,
        )
    data = valid_document()
    data["visualcrossing"]["schemaVersion"] = "v2"
    with pytest.raises(ForecastEvidenceError, match="unsupported_forecast_source"):
        parse(data)
    with pytest.raises(ForecastEvidenceError, match="forecast_file_too_large"):
        parse_local_forecast(
            b" " * (4 * 1024 * 1024 + 1),
            publication_time=NOW,
            now=NOW,
            target_origin="http://synthetic.local",
            deadline=time.monotonic() + 5,
        )
    with pytest.raises(ForecastEvidenceError, match="invalid_publication_clock"):
        parse_local_forecast(
            b"{}",
            publication_time=NOW + 1,
            now=NOW,
            target_origin="http://synthetic.local",
            deadline=time.monotonic() + 5,
        )
    with pytest.raises(HistoryAnalysisDeadline):
        sampled_solar_windows(parse(), options(), now=NOW, deadline=0)


def test_explicit_dst_offsets_preserve_hourly_utc_sequences():
    first = datetime(2026, 10, 25, tzinfo=UTC).timestamp()
    data = valid_document((100, 300))
    for index, row in enumerate(data["hourlyforecast"]):
        at = first + index * 3600
        row["time"] = {
            "datetime": datetime.fromtimestamp(at, UTC)
            .astimezone(ZoneInfo("Europe/Berlin"))
            .isoformat(),
            "epoch": int(at),
        }
    forecast = parse(data)
    result = sampled_solar_windows(
        forecast,
        options(
            start=datetime.fromtimestamp(first, UTC).isoformat(),
            end=datetime.fromtimestamp(first + 7200, UTC).isoformat(),
            duration_hours=2,
        ),
        now=NOW,
        deadline=time.monotonic() + 5,
    )
    assert len(result.windows) == 1 and result.windows[0].mean_sample_irradiance_w_m2 == 200


def test_nonoverlapping_output_is_bounded_and_threshold_applies_to_each_sample():
    data = valid_document(tuple(100 for _ in range(48)))
    end = datetime.fromtimestamp(NOW + 49 * 3600, UTC).isoformat()
    result = windows(data, end=end)
    assert len(result.windows) == 16
    assert not windows(minimum_sample_irradiance_w_m2=501.0).windows
    with pytest.raises(ForecastEvidenceError, match="invalid_future_window"):
        sampled_solar_windows(parse(), options(), now=NOW, deadline=time.monotonic() + 5, limit=17)
