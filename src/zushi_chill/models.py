from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass(frozen=True)
class WeatherSummary:
    date: str
    run_time: str
    location_name: str
    latitude: float
    longitude: float
    sunset_time: datetime
    target_window_start: datetime
    target_window_end: datetime
    temperature_2m: float
    apparent_temperature: float
    relative_humidity_2m: float
    precipitation_probability: float
    precipitation: float
    weather_code: int
    cloud_cover: float
    cloud_cover_low: float
    cloud_cover_mid: float
    cloud_cover_high: float
    visibility: float
    wind_speed_10m: float
    wind_direction_10m: float
    wind_gusts_10m: float


@dataclass(frozen=True)
class ScoreResult:
    sunset_score: int
    sunset_label: str
    chill_score: int
    chill_label: str
    comment: str = ""


@dataclass(frozen=True)
class PredictionRecord:
    summary: WeatherSummary
    scores: ScoreResult
    line_sent: bool
    error_message: str = ""

    def to_row(self) -> dict[str, str | int | float | bool]:
        data = asdict(self.summary)
        data.update(
            {
                "sunset_time": self.summary.sunset_time.isoformat(timespec="minutes"),
                "target_window_start": self.summary.target_window_start.isoformat(
                    timespec="minutes"
                ),
                "target_window_end": self.summary.target_window_end.isoformat(timespec="minutes"),
                "chill_score": self.scores.chill_score,
                "chill_label": self.scores.chill_label,
                "sunset_score": self.scores.sunset_score,
                "sunset_label": self.scores.sunset_label,
                "comment": self.scores.comment,
                "line_sent": self.line_sent,
                "error_message": self.error_message,
            }
        )
        return data
