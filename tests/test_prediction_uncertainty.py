from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from zushi_chill.models import JmaPrecipitationForecast, SunsetCloud, VisionResult
from zushi_chill.prediction_uncertainty import detect_prediction_uncertainty


def _cloud(summary) -> SunsetCloud:
    return SunsetCloud.from_summary(summary)


def test_detects_missing_forecast_values_at_scheduled_prediction_time(sample_summary):
    summary = replace(sample_summary, precipitation_probability_at_sunset=None)

    assert detect_prediction_uncertainty(summary, _cloud(summary)) == "missing_values"


def test_detects_convective_weather(sample_summary):
    summary = replace(sample_summary, weather_code_at_sunset=95)

    assert detect_prediction_uncertainty(summary, _cloud(summary)) == "convective_weather"


def test_detects_rain_timing_shift(sample_summary):
    summary = replace(
        sample_summary,
        precipitation_probability_before_sunset=20,
        precipitation_probability_at_sunset=70,
    )

    assert detect_prediction_uncertainty(summary, _cloud(summary)) == "rain_timing_shift"


def test_detects_large_difference_between_precipitation_forecasts(sample_summary):
    period_start = sample_summary.sunset_time.replace(hour=18, minute=0)
    jma = JmaPrecipitationForecast(
        probability=70,
        period_start=period_start,
        period_end=period_start + timedelta(hours=6),
        area_name="東部",
        report_time=period_start.replace(hour=17),
    )

    assert (
        detect_prediction_uncertainty(
            sample_summary,
            _cloud(sample_summary),
            jma_precipitation=jma,
        )
        == "precipitation_forecast_disagreement"
    )


def test_detects_direction_of_formula_and_camera_disagreement(sample_summary):
    optimistic = VisionResult(
        sunset_score=80,
        sky_condition="clear",
        comment="晴れている",
        model="test",
    )
    pessimistic = replace(optimistic, sunset_score=20)

    assert (
        detect_prediction_uncertainty(
            sample_summary,
            _cloud(sample_summary),
            vision=optimistic,
            formula_sunset_score=50,
        )
        == "vision_more_optimistic"
    )
    assert (
        detect_prediction_uncertainty(
            sample_summary,
            _cloud(sample_summary),
            vision=pessimistic,
            formula_sunset_score=50,
        )
        == "vision_more_pessimistic"
    )


def test_uncertainty_is_limited_to_13_and_17_messages(sample_summary):
    summary = replace(
        sample_summary,
        run_time="16:00",
        weather_code_at_sunset=95,
    )

    assert detect_prediction_uncertainty(summary, _cloud(summary)) is None
