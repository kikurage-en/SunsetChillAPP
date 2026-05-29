from __future__ import annotations

from zushi_chill.constants import RAIN_WEATHER_CODES
from zushi_chill.models import ScoreResult, WeatherSummary


def score_label(score: int) -> str:
    if score >= 85:
        return "S"
    if score >= 70:
        return "A"
    if score >= 55:
        return "B"
    if score >= 40:
        return "C"
    return "D"


def calculate_scores(summary: WeatherSummary) -> ScoreResult:
    sunset_score = calculate_sunset_score(summary)
    chill_score = calculate_chill_score(summary, sunset_score)
    return ScoreResult(
        sunset_score=sunset_score,
        sunset_label=score_label(sunset_score),
        chill_score=chill_score,
        chill_label=score_label(chill_score),
    )


def calculate_sunset_score(summary: WeatherSummary) -> int:
    score = 100
    score += _low_cloud_penalty(summary.cloud_cover_low)
    score += _precipitation_penalty(summary.precipitation_probability)
    score += _visibility_penalty(summary.visibility)
    score += _wind_penalty(summary.wind_speed_10m)
    score += 5 if 20 <= summary.cloud_cover_mid <= 60 else 0
    score += 10 if 20 <= summary.cloud_cover_high <= 70 else 0

    if summary.visibility < 5000:
        score = min(score, 50)
    return _clamp_score(score)


def calculate_chill_score(summary: WeatherSummary, sunset_score: int) -> int:
    score = (
        apparent_temperature_score(summary.apparent_temperature) * 0.30
        + humidity_score(summary.relative_humidity_2m) * 0.20
        + wind_score(summary.wind_speed_10m) * 0.20
        + precipitation_risk_score(summary.precipitation_probability) * 0.20
        + sunset_score * 0.10
    )

    caps: list[int] = []
    if summary.precipitation_probability >= 70:
        caps.append(40)
    if summary.precipitation >= 1.0:
        caps.append(45)
    if summary.wind_speed_10m >= 8:
        caps.append(55)
    if summary.wind_gusts_10m >= 12:
        caps.append(50)
    if summary.weather_code in RAIN_WEATHER_CODES:
        caps.append(45)
    if caps:
        score = min(score, min(caps))

    return _clamp_score(score)


def apparent_temperature_score(value: float) -> int:
    if 22 <= value <= 28:
        return 100
    if 20 <= value <= 21.9 or 28.1 <= value <= 30:
        return 80
    if 18 <= value <= 19.9 or 30.1 <= value <= 32:
        return 60
    if 16 <= value <= 17.9 or 32.1 <= value <= 34:
        return 40
    return 20


def humidity_score(value: float) -> int:
    if 55 <= value <= 75:
        return 100
    if 45 <= value <= 54 or 76 <= value <= 82:
        return 80
    if 35 <= value <= 44 or 83 <= value <= 88:
        return 60
    if value >= 89:
        return 40
    return 50


def wind_score(value: float) -> int:
    if 2.0 <= value <= 5.0:
        return 100
    if 0.5 <= value <= 1.9 or 5.1 <= value <= 6.9:
        return 80
    if 7.0 <= value <= 8.9:
        return 50
    if value >= 9.0:
        return 25
    return 60


def precipitation_risk_score(value: float) -> int:
    if value <= 19:
        return 100
    if value <= 34:
        return 80
    if value <= 49:
        return 60
    if value <= 69:
        return 35
    return 10


def _low_cloud_penalty(value: float) -> int:
    if value <= 29:
        return 0
    if value <= 49:
        return -10
    if value <= 69:
        return -20
    if value <= 84:
        return -35
    return -50


def _precipitation_penalty(value: float) -> int:
    if value <= 19:
        return 0
    if value <= 39:
        return -10
    if value <= 59:
        return -25
    if value <= 79:
        return -40
    return -60


def _visibility_penalty(value: float) -> int:
    if value >= 15000:
        return 0
    if value >= 10000:
        return -5
    if value >= 5000:
        return -15
    return -30


def _wind_penalty(value: float) -> int:
    if value < 6.0:
        return 0
    if value < 8.0:
        return -5
    return -10


def _clamp_score(score: float) -> int:
    return max(0, min(100, int(round(score))))
