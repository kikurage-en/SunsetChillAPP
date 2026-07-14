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
class SunsetCloud:
    """Sunset期待度の算出に使う雲量。

    Chill指数は逗子海岸の雲量を使うが、夕焼けの見え方は「陽が沈む方角(西の
    水平線)の雲」に支配されるため、Sunset期待度はその地点の雲量で算出する。
    ``cloud_cover`` などは逗子と同名だが、参照地点が異なる。
    """

    cloud_cover: float
    cloud_cover_low: float
    cloud_cover_mid: float
    cloud_cover_high: float

    @classmethod
    def from_summary(cls, summary: WeatherSummary) -> SunsetCloud:
        return cls(
            cloud_cover=summary.cloud_cover,
            cloud_cover_low=summary.cloud_cover_low,
            cloud_cover_mid=summary.cloud_cover_mid,
            cloud_cover_high=summary.cloud_cover_high,
        )


@dataclass(frozen=True)
class ScoreResult:
    sunset_score: int
    sunset_label: str
    chill_score: int
    chill_label: str
    comment: str = ""


@dataclass(frozen=True)
class VisionResult:
    sunset_score: int
    sky_condition: str
    comment: str
    model: str


@dataclass(frozen=True)
class PredictionRecord:
    summary: WeatherSummary
    scores: ScoreResult
    line_sent: bool
    error_message: str = ""
    vision: VisionResult | None = None
    sunset_cloud: SunsetCloud | None = None
    final_sunset_score: int | None = None
    final_sunset_label: str | None = None

    def to_row(self) -> dict[str, str | int | float | bool]:
        data = asdict(self.summary)
        sunset_cloud = self.sunset_cloud
        # 表示用ブレンド値。未設定の実行(欠測・ブレンド無効)は純式スコアを既定にする。
        final_sunset_score = (
            self.final_sunset_score
            if self.final_sunset_score is not None
            else self.scores.sunset_score
        )
        final_sunset_label = self.final_sunset_label or self.scores.sunset_label
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
                "vision_sunset_score": self.vision.sunset_score if self.vision else "",
                "vision_sky_condition": self.vision.sky_condition if self.vision else "",
                "vision_comment": self.vision.comment if self.vision else "",
                "vision_model": self.vision.model if self.vision else "",
                "sunset_cloud_cover": sunset_cloud.cloud_cover if sunset_cloud else "",
                "sunset_cloud_cover_low": sunset_cloud.cloud_cover_low if sunset_cloud else "",
                "sunset_cloud_cover_mid": sunset_cloud.cloud_cover_mid if sunset_cloud else "",
                "sunset_cloud_cover_high": sunset_cloud.cloud_cover_high if sunset_cloud else "",
                "final_sunset_score": final_sunset_score,
                "final_sunset_label": final_sunset_label,
            }
        )
        return data
