from __future__ import annotations

from dataclasses import asdict, dataclass, replace
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
    # 日没時刻を挟む2つのOpen-Meteo時間値。集計窓の最大値・合計値だけでは、
    # 高い降水確率と雨量0の食い違いがどの時間帯にあったかを再検証できないため残す。
    precipitation_probability_before_sunset: float | None = None
    precipitation_before_sunset: float | None = None
    weather_code_before_sunset: int | None = None
    visibility_before_sunset: float | None = None
    precipitation_probability_at_sunset: float | None = None
    precipitation_at_sunset: float | None = None
    weather_code_at_sunset: int | None = None
    visibility_at_sunset: float | None = None
    # 実行時刻に最も近いOpen-Meteo hourly行。日没前のChill指数は従来どおり
    # 対象時間帯の集計値、日没時・残照時はこの一式を使い、異なる時刻基準を混ぜない。
    run_time_snapshot_time: datetime | None = None
    temperature_2m_at_run_time: float | None = None
    apparent_temperature_at_run_time: float | None = None
    relative_humidity_2m_at_run_time: float | None = None
    precipitation_probability_at_run_time: float | None = None
    precipitation_at_run_time: float | None = None
    weather_code_at_run_time: int | None = None
    cloud_cover_at_run_time: float | None = None
    cloud_cover_low_at_run_time: float | None = None
    cloud_cover_mid_at_run_time: float | None = None
    cloud_cover_high_at_run_time: float | None = None
    visibility_at_run_time: float | None = None
    wind_speed_10m_at_run_time: float | None = None
    wind_direction_10m_at_run_time: float | None = None
    wind_gusts_10m_at_run_time: float | None = None
    # 過ごしやすさコメントで夕方との気温差を見るための、6時〜日没の最高気温。
    # 表示組み立て専用で、保存スキーマには含めない。
    temperature_2m_daytime_max: float | None = None
    # 日没前の予測メッセージへ表示する、日没時刻に最も近いhourly行の値。
    # Sunset期待度・Chill指数は従来どおり対象時間帯の集計値を使う。
    sunset_snapshot_time: datetime | None = None
    temperature_2m_at_sunset: float | None = None
    relative_humidity_2m_at_sunset: float | None = None
    cloud_cover_low_at_sunset: float | None = None
    cloud_cover_mid_at_sunset: float | None = None
    cloud_cover_high_at_sunset: float | None = None
    visibility_at_sunset_snapshot: float | None = None
    wind_speed_10m_at_sunset: float | None = None
    wind_direction_10m_at_sunset: float | None = None

    def with_run_time_weather(self) -> WeatherSummary:
        """Return a copy whose scoring fields use the nearest run-time hourly row.

        Missing optional hourly fields fall back independently to the target-window
        aggregates, so an allowed upstream omission does not discard the rest of a
        usable run-time snapshot.
        """

        def current(value: float | int | None, fallback: float | int) -> float | int:
            return fallback if value is None else value

        return replace(
            self,
            temperature_2m=float(
                current(self.temperature_2m_at_run_time, self.temperature_2m)
            ),
            apparent_temperature=float(
                current(
                    self.apparent_temperature_at_run_time,
                    self.apparent_temperature,
                )
            ),
            relative_humidity_2m=float(
                current(
                    self.relative_humidity_2m_at_run_time,
                    self.relative_humidity_2m,
                )
            ),
            precipitation_probability=float(
                current(
                    self.precipitation_probability_at_run_time,
                    self.precipitation_probability,
                )
            ),
            precipitation=float(
                current(self.precipitation_at_run_time, self.precipitation)
            ),
            weather_code=int(current(self.weather_code_at_run_time, self.weather_code)),
            cloud_cover=float(current(self.cloud_cover_at_run_time, self.cloud_cover)),
            cloud_cover_low=float(
                current(self.cloud_cover_low_at_run_time, self.cloud_cover_low)
            ),
            cloud_cover_mid=float(
                current(self.cloud_cover_mid_at_run_time, self.cloud_cover_mid)
            ),
            cloud_cover_high=float(
                current(self.cloud_cover_high_at_run_time, self.cloud_cover_high)
            ),
            visibility=float(current(self.visibility_at_run_time, self.visibility)),
            wind_speed_10m=float(
                current(self.wind_speed_10m_at_run_time, self.wind_speed_10m)
            ),
            wind_direction_10m=float(
                current(
                    self.wind_direction_10m_at_run_time,
                    self.wind_direction_10m,
                )
            ),
            wind_gusts_10m=float(
                current(self.wind_gusts_10m_at_run_time, self.wind_gusts_10m)
            ),
        )


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
    cloud_cover_low_at_sunset: float | None = None
    cloud_cover_mid_at_sunset: float | None = None
    cloud_cover_high_at_sunset: float | None = None

    @classmethod
    def from_summary(cls, summary: WeatherSummary) -> SunsetCloud:
        return cls(
            cloud_cover=summary.cloud_cover,
            cloud_cover_low=summary.cloud_cover_low,
            cloud_cover_mid=summary.cloud_cover_mid,
            cloud_cover_high=summary.cloud_cover_high,
            cloud_cover_low_at_sunset=summary.cloud_cover_low_at_sunset,
            cloud_cover_mid_at_sunset=summary.cloud_cover_mid_at_sunset,
            cloud_cover_high_at_sunset=summary.cloud_cover_high_at_sunset,
        )


@dataclass(frozen=True)
class ScoreResult:
    sunset_score: int
    sunset_label: str
    chill_score: int
    chill_label: str
    comment: str = ""
    chill_weather_basis: str = "target_window"


@dataclass(frozen=True)
class VisionResult:
    sunset_score: int
    sky_condition: str
    comment: str
    model: str
    evaluation_phase: str = ""
    sun_disk_visibility: int | None = None
    sunset_color_score: int | None = None
    afterglow_score: int | None = None


@dataclass(frozen=True)
class SunsethueResult:
    """Sunsethue API(ray-model)の夕焼け品質予測。式・Visionとは独立したベンチマーク。

    ``quality`` / ``cloud_cover`` は API の 0〜1 を 100 倍した 0〜100 整数(式の
    sunset_score・Vision と同じ土俵で突合できるように揃える)。
    """

    quality: int
    cloud_cover: int
    quality_text: str


@dataclass(frozen=True)
class JmaPrecipitationForecast:
    """気象庁の一次細分区域向け6時間降水確率。"""

    probability: int
    period_start: datetime
    period_end: datetime
    area_name: str
    report_time: datetime


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
    sunsethue: SunsethueResult | None = None
    jma_precipitation: JmaPrecipitationForecast | None = None
    observation_id: str = ""
    observation_phase: str = ""
    scheduled_at: datetime | None = None
    captured_at: datetime | None = None

    def to_row(self) -> dict[str, str | int | float | bool]:
        data = asdict(self.summary)
        # 日中最高気温と逗子上空の日没時雲スナップショットは表示組み立て専用。
        # 実行時スナップショットはChill指数の再現に必要なため保存する。
        data.pop("temperature_2m_daytime_max", None)
        for field in (
            "cloud_cover_low_at_sunset",
            "cloud_cover_mid_at_sunset",
            "cloud_cover_high_at_sunset",
        ):
            data.pop(field, None)
        for field in (
            "precipitation_probability_before_sunset",
            "precipitation_before_sunset",
            "weather_code_before_sunset",
            "visibility_before_sunset",
            "precipitation_probability_at_sunset",
            "precipitation_at_sunset",
            "weather_code_at_sunset",
            "visibility_at_sunset",
            "temperature_2m_at_sunset",
            "relative_humidity_2m_at_sunset",
            "visibility_at_sunset_snapshot",
            "wind_speed_10m_at_sunset",
            "wind_direction_10m_at_sunset",
            "temperature_2m_at_run_time",
            "apparent_temperature_at_run_time",
            "relative_humidity_2m_at_run_time",
            "precipitation_probability_at_run_time",
            "precipitation_at_run_time",
            "weather_code_at_run_time",
            "cloud_cover_at_run_time",
            "cloud_cover_low_at_run_time",
            "cloud_cover_mid_at_run_time",
            "cloud_cover_high_at_run_time",
            "visibility_at_run_time",
            "wind_speed_10m_at_run_time",
            "wind_direction_10m_at_run_time",
            "wind_gusts_10m_at_run_time",
        ):
            if data[field] is None:
                data[field] = ""
        data["run_time_snapshot_time"] = (
            self.summary.run_time_snapshot_time.isoformat(timespec="minutes")
            if self.summary.run_time_snapshot_time
            else ""
        )
        data["sunset_snapshot_time"] = (
            self.summary.sunset_snapshot_time.isoformat(timespec="minutes")
            if self.summary.sunset_snapshot_time
            else ""
        )
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
                "chill_weather_basis": self.scores.chill_weather_basis,
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
                "sunsethue_quality": self.sunsethue.quality if self.sunsethue else "",
                "sunsethue_cloud_cover": self.sunsethue.cloud_cover if self.sunsethue else "",
                "sunsethue_quality_text": self.sunsethue.quality_text if self.sunsethue else "",
                "vision_evaluation_phase": (
                    self.vision.evaluation_phase if self.vision else ""
                ),
                "vision_sun_disk_visibility": (
                    self.vision.sun_disk_visibility
                    if self.vision and self.vision.sun_disk_visibility is not None
                    else ""
                ),
                "vision_sunset_color_score": (
                    self.vision.sunset_color_score
                    if self.vision and self.vision.sunset_color_score is not None
                    else ""
                ),
                "vision_afterglow_score": (
                    self.vision.afterglow_score
                    if self.vision and self.vision.afterglow_score is not None
                    else ""
                ),
                "jma_precipitation_probability": (
                    self.jma_precipitation.probability if self.jma_precipitation else ""
                ),
                "jma_precipitation_period_start": (
                    self.jma_precipitation.period_start.isoformat(timespec="minutes")
                    if self.jma_precipitation
                    else ""
                ),
                "jma_precipitation_period_end": (
                    self.jma_precipitation.period_end.isoformat(timespec="minutes")
                    if self.jma_precipitation
                    else ""
                ),
                "jma_precipitation_area": (
                    self.jma_precipitation.area_name if self.jma_precipitation else ""
                ),
                "jma_report_time": (
                    self.jma_precipitation.report_time.isoformat(timespec="minutes")
                    if self.jma_precipitation
                    else ""
                ),
                "sunset_cloud_cover_low_at_sunset": (
                    sunset_cloud.cloud_cover_low_at_sunset
                    if sunset_cloud and sunset_cloud.cloud_cover_low_at_sunset is not None
                    else ""
                ),
                "sunset_cloud_cover_mid_at_sunset": (
                    sunset_cloud.cloud_cover_mid_at_sunset
                    if sunset_cloud and sunset_cloud.cloud_cover_mid_at_sunset is not None
                    else ""
                ),
                "sunset_cloud_cover_high_at_sunset": (
                    sunset_cloud.cloud_cover_high_at_sunset
                    if sunset_cloud and sunset_cloud.cloud_cover_high_at_sunset is not None
                    else ""
                ),
                "observation_id": self.observation_id,
                "observation_phase": self.observation_phase,
                "scheduled_at": (
                    self.scheduled_at.isoformat(timespec="seconds")
                    if self.scheduled_at
                    else ""
                ),
                "captured_at": (
                    self.captured_at.isoformat(timespec="seconds") if self.captured_at else ""
                ),
                "capture_delay_seconds": _capture_delay_seconds(
                    self.scheduled_at,
                    self.captured_at,
                ),
                "observation_data_quality": _observation_data_quality(
                    self.scheduled_at,
                    self.captured_at,
                ),
            }
        )
        return data


def _capture_delay_seconds(
    scheduled_at: datetime | None,
    captured_at: datetime | None,
) -> int | str:
    if scheduled_at is None or captured_at is None:
        return ""
    return max(0, round((captured_at - scheduled_at).total_seconds()))


def _observation_data_quality(
    scheduled_at: datetime | None,
    captured_at: datetime | None,
) -> str:
    delay = _capture_delay_seconds(scheduled_at, captured_at)
    if not isinstance(delay, int):
        return ""
    if delay <= 180:
        return "on_time"
    if delay <= 600:
        return "delayed"
    return "late"
