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
    # LINEの天気参考値として表示する、実行時刻に最も近いhourly気温。
    # Chill指数は従来どおり apparent_temperature の対象時間帯平均を使う。
    temperature_2m_at_run_time: float | None = None
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


@dataclass(frozen=True)
class SunsetScoreBreakdown:
    """純式Sunset期待度の加減点内訳と上限適用前後の値。"""

    low_cloud_penalty: int
    precipitation_penalty: int
    visibility_penalty: int
    wind_penalty: int
    mid_cloud_bonus: int
    high_cloud_bonus: int
    score_before_caps: int
    final_score: int


@dataclass(frozen=True)
class SunsetBlendResult:
    """表示用ブレンド値とVision上方キャップの診断情報。"""

    final_score: int
    uncapped_score: int
    uplift_cap_applied: bool


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
    sunset_score_breakdown: SunsetScoreBreakdown | None = None
    uncapped_final_sunset_score: int | None = None
    vision_uplift_cap_applied: bool = False
    live_camera_capture_source: str = ""
    live_camera_captured_at: str = ""
    live_camera_image_sha256: str = ""

    def to_row(self) -> dict[str, str | int | float | bool]:
        data = asdict(self.summary)
        # 実行時気温と逗子上空の雲スナップショットは表示組み立て用。日没時表示値は
        # 下で時刻・気象値と、日没方向の層別雲量に分けて保存する。
        data.pop("temperature_2m_at_run_time", None)
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
        ):
            if data[field] is None:
                data[field] = ""
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
                "sunset_low_cloud_penalty": (
                    self.sunset_score_breakdown.low_cloud_penalty
                    if self.sunset_score_breakdown
                    else ""
                ),
                "sunset_precipitation_penalty": (
                    self.sunset_score_breakdown.precipitation_penalty
                    if self.sunset_score_breakdown
                    else ""
                ),
                "sunset_visibility_penalty": (
                    self.sunset_score_breakdown.visibility_penalty
                    if self.sunset_score_breakdown
                    else ""
                ),
                "sunset_wind_penalty": (
                    self.sunset_score_breakdown.wind_penalty
                    if self.sunset_score_breakdown
                    else ""
                ),
                "sunset_mid_cloud_bonus": (
                    self.sunset_score_breakdown.mid_cloud_bonus
                    if self.sunset_score_breakdown
                    else ""
                ),
                "sunset_high_cloud_bonus": (
                    self.sunset_score_breakdown.high_cloud_bonus
                    if self.sunset_score_breakdown
                    else ""
                ),
                "sunset_score_before_caps": (
                    self.sunset_score_breakdown.score_before_caps
                    if self.sunset_score_breakdown
                    else ""
                ),
                "uncapped_final_sunset_score": (
                    self.uncapped_final_sunset_score
                    if self.uncapped_final_sunset_score is not None
                    else ""
                ),
                "vision_uplift_cap_applied": self.vision_uplift_cap_applied,
                "live_camera_capture_source": self.live_camera_capture_source,
                "live_camera_captured_at": self.live_camera_captured_at,
                "live_camera_image_sha256": self.live_camera_image_sha256,
            }
        )
        return data
