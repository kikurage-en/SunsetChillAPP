from __future__ import annotations

from typing import Literal

from zushi_chill.constants import RAIN_WEATHER_CODES
from zushi_chill.models import (
    JmaPrecipitationForecast,
    SunsetCloud,
    VisionResult,
    WeatherSummary,
)
from zushi_chill.scoring import has_dry_high_precipitation_conflict

PredictionUncertainty = Literal[
    "missing_values",
    "convective_weather",
    "rain_timing_shift",
    "dry_high_precipitation_conflict",
    "precipitation_forecast_disagreement",
    "vision_more_optimistic",
    "vision_more_pessimistic",
    "borderline_precipitation",
]

PREDICTION_MESSAGE_TIMES = frozenset({"13:00", "17:00"})
CONVECTIVE_WEATHER_CODES = frozenset({80, 81, 82, 95, 96, 99})
PRECIPITATION_PROBABILITY_SWING = 30
PRECIPITATION_AMOUNT_SWING = 1.0
FORECAST_PROBABILITY_DISAGREEMENT = 40
VISION_FORMULA_DISAGREEMENT = 25


def detect_prediction_uncertainty(
    summary: WeatherSummary,
    sunset_cloud: SunsetCloud,
    *,
    vision: VisionResult | None = None,
    formula_sunset_score: int | None = None,
    jma_precipitation: JmaPrecipitationForecast | None = None,
) -> PredictionUncertainty | None:
    """Return the strongest supported uncertainty signal for 13:00/17:00."""
    if summary.run_time not in PREDICTION_MESSAGE_TIMES:
        return None

    diagnostic_values = (
        summary.precipitation_probability_before_sunset,
        summary.precipitation_before_sunset,
        summary.weather_code_before_sunset,
        summary.visibility_before_sunset,
        summary.precipitation_probability_at_sunset,
        summary.precipitation_at_sunset,
        summary.weather_code_at_sunset,
        summary.visibility_at_sunset,
    )
    if any(value is None for value in diagnostic_values):
        return "missing_values"

    weather_codes = {
        summary.weather_code,
        summary.weather_code_before_sunset,
        summary.weather_code_at_sunset,
    }
    if weather_codes & CONVECTIVE_WEATHER_CODES:
        return "convective_weather"

    if _rain_timing_changes(summary):
        return "rain_timing_shift"

    if has_dry_high_precipitation_conflict(summary, sunset_cloud):
        return "dry_high_precipitation_conflict"

    if (
        jma_precipitation is not None
        and abs(jma_precipitation.probability - summary.precipitation_probability)
        >= FORECAST_PROBABILITY_DISAGREEMENT
    ):
        return "precipitation_forecast_disagreement"

    if vision is not None and formula_sunset_score is not None:
        gap = vision.sunset_score - formula_sunset_score
        if gap >= VISION_FORMULA_DISAGREEMENT:
            return "vision_more_optimistic"
        if gap <= -VISION_FORMULA_DISAGREEMENT:
            return "vision_more_pessimistic"

    displayed_precipitation_probability = (
        jma_precipitation.probability
        if jma_precipitation is not None
        else summary.precipitation_probability
    )
    if 40 <= displayed_precipitation_probability <= 60:
        return "borderline_precipitation"

    return None


def _rain_timing_changes(summary: WeatherSummary) -> bool:
    before_probability = summary.precipitation_probability_before_sunset
    at_probability = summary.precipitation_probability_at_sunset
    before_precipitation = summary.precipitation_before_sunset
    at_precipitation = summary.precipitation_at_sunset
    before_code = summary.weather_code_before_sunset
    at_code = summary.weather_code_at_sunset
    assert before_probability is not None
    assert at_probability is not None
    assert before_precipitation is not None
    assert at_precipitation is not None
    assert before_code is not None
    assert at_code is not None

    before_rain = before_code in RAIN_WEATHER_CODES
    at_rain = at_code in RAIN_WEATHER_CODES
    return (
        abs(before_probability - at_probability)
        >= PRECIPITATION_PROBABILITY_SWING
        or abs(before_precipitation - at_precipitation) >= PRECIPITATION_AMOUNT_SWING
        or before_rain != at_rain
    )
