from __future__ import annotations

from zushi_chill.models import (
    JmaPrecipitationForecast,
    ScoreResult,
    SunsetCloud,
    VisionResult,
    WeatherSummary,
)
from zushi_chill.scoring import has_dry_high_precipitation_conflict, score_label


def build_comment(
    summary: WeatherSummary,
    scores: ScoreResult,
    sunset_cloud: SunsetCloud | None = None,
    *,
    prediction: bool = True,
) -> str:
    # 雲に関する所見は Sunset期待度を駆動する「夕焼け方向(西の空)」の雲で判断する。
    cloud = sunset_cloud or SunsetCloud.from_summary(summary)
    sunset_band = _comment_band(scores.sunset_score)
    chill_band = _comment_band(scores.chill_score)
    headline = _comment_headline(sunset_band, chill_band, prediction=prediction)

    details: list[str] = []
    if cloud.cloud_cover_low >= 70:
        details.append(
            "低層雲が多く、夕陽が隠れる可能性があります。"
            if prediction
            else "低層雲が多く、夕陽が隠れやすい条件です。"
        )
    if summary.apparent_temperature >= 32:
        details.append(
            "体感温度が高く、海辺では蒸し暑さが強い見込みです。"
            if prediction
            else "体感温度が高く、海辺では蒸し暑さが強い状態です。"
        )
    elif summary.apparent_temperature >= 28:
        details.append(
            "海辺ではやや蒸し暑く感じる見込みです。"
            if prediction
            else "海辺ではやや蒸し暑い状態です。"
        )
    if summary.wind_speed_10m >= 8:
        details.append(
            "風が強く、海辺の快適さを下げる見込みです。"
            if prediction
            else "風が強く、海辺の快適さを下げる条件です。"
        )
    if 20 <= cloud.cloud_cover_high <= 70 and cloud.cloud_cover_low < 50:
        details.append(
            "高層雲がほどよく、夕焼け色が出る可能性があります。"
            if prediction
            else "高層雲がほどよく、夕焼け色が出やすい条件です。"
        )
    if has_dry_high_precipitation_conflict(summary, cloud):
        details.insert(
            0,
            (
                "Sunset算出用の降水信号と予想雨量・西空の雲が食い違うため、"
                "夕焼け予測の不確実性が高いです。"
                if prediction
                else "Sunset算出用の降水信号と予想雨量・西空の雲が食い違い、"
                "算出条件の不確実性が高い状態です。"
            ),
        )

    # コメント欄も情報過多にしない。総評1文に、優先度が最も高い1件だけ補足する。
    return "\n".join([headline, *details[:1]])


def _comment_headline(sunset_band: str, chill_band: str, *, prediction: bool) -> str:
    if prediction:
        if sunset_band == "good" and chill_band == "good":
            return "夕焼け条件・海辺の快適さともに良好な見込みです。"
        if sunset_band == "good":
            return "夕焼け条件は良好ですが、海辺の快適さは控えめな見込みです。"
        if chill_band == "good":
            return "海辺の快適さは良好ですが、夕焼け条件は控えめな見込みです。"
        if sunset_band == "low" and chill_band == "low":
            return "夕焼け条件・海辺の快適さともに低調な見込みです。"
        if sunset_band == "low":
            return "海辺の快適さは中程度ですが、夕焼け条件は低調な見込みです。"
        if chill_band == "low":
            return "夕焼け条件は中程度ですが、海辺の快適さは低調な見込みです。"
        return "夕焼け条件・海辺の快適さともに中程度の見込みです。"

    if sunset_band == "good" and chill_band == "good":
        return "夕焼け条件・海辺の快適さともに良好です。"
    if sunset_band == "good":
        return "夕焼け条件は良好ですが、海辺の快適さは控えめです。"
    if chill_band == "good":
        return "海辺の快適さは良好ですが、夕焼け条件は控えめです。"
    if sunset_band == "low" and chill_band == "low":
        return "夕焼け条件・海辺の快適さともに低調です。"
    if sunset_band == "low":
        return "海辺の快適さは中程度ですが、夕焼け条件は低調です。"
    if chill_band == "low":
        return "夕焼け条件は中程度ですが、海辺の快適さは低調です。"
    return "夕焼け条件・海辺の快適さともに中程度です。"


def _comment_band(score: int) -> str:
    if score >= 70:
        return "good"
    if score >= 55:
        return "medium"
    return "low"


def build_line_message(
    summary: WeatherSummary,
    scores: ScoreResult,
    *,
    vision: VisionResult | None = None,
    vision_mode: str = "actual",
    sunset_cloud: SunsetCloud | None = None,
    jma_precipitation: JmaPrecipitationForecast | None = None,
    final_sunset_score: int | None = None,
    final_sunset_label: str | None = None,
) -> str:
    cloud = sunset_cloud or SunsetCloud.from_summary(summary)
    comment_scores = scores
    if final_sunset_score is not None:
        comment_scores = ScoreResult(
            sunset_score=final_sunset_score,
            sunset_label=final_sunset_label or score_label(final_sunset_score),
            chill_score=scores.chill_score,
            chill_label=scores.chill_label,
        )
    comment = scores.comment or build_comment(
        summary,
        comment_scores,
        sunset_cloud,
        prediction=vision_mode == "predict",
    )
    # 表示する Sunset期待度は Vision ブレンド後の値(未指定なら純式スコア)。
    display_sunset_score = (
        final_sunset_score if final_sunset_score is not None else scores.sunset_score
    )
    display_sunset_label = final_sunset_label or scores.sunset_label
    use_sunset_snapshot = vision_mode == "predict" and summary.sunset_snapshot_time is not None
    display_cloud_low = (
        cloud.cloud_cover_low_at_sunset
        if use_sunset_snapshot and cloud.cloud_cover_low_at_sunset is not None
        else cloud.cloud_cover_low
    )
    display_cloud_mid = (
        cloud.cloud_cover_mid_at_sunset
        if use_sunset_snapshot and cloud.cloud_cover_mid_at_sunset is not None
        else cloud.cloud_cover_mid
    )
    display_cloud_high = (
        cloud.cloud_cover_high_at_sunset
        if use_sunset_snapshot and cloud.cloud_cover_high_at_sunset is not None
        else cloud.cloud_cover_high
    )
    cloud_line = (
        f"低層 {display_cloud_low:.0f}% / 中層 {display_cloud_mid:.0f}%"
        f" / 高層 {display_cloud_high:.0f}%"
    )
    vision_section = ""
    if vision is not None:
        if vision_mode == "predict":
            vision_label = "ライブカメラAI予測"
        elif vision.evaluation_phase == "sunset":
            vision_label = "ライブカメラ日没時評価"
        elif vision.evaluation_phase == "afterglow":
            vision_label = "ライブカメラ残照評価"
        else:
            vision_label = "ライブカメラ実況評価"
        detail_lines = []
        if vision.sun_disk_visibility is not None:
            detail_lines.append(f"太陽ディスク：{vision.sun_disk_visibility} / 100")
        if vision.sunset_color_score is not None:
            detail_lines.append(f"日没時の発色：{vision.sunset_color_score} / 100")
        if vision.afterglow_score is not None:
            detail_lines.append(f"残照：{vision.afterglow_score} / 100")
        detail_section = "" if not detail_lines else "\n" + "\n".join(detail_lines)
        vision_section = (
            f"\n\n📷 {vision_label}\n"
            f"【 {score_label(vision.sunset_score)} 】{vision.sunset_score} / 100"
            f"（{vision.sky_condition}）\n"
            f"{vision.comment}{detail_section}"
        )
    precipitation_line = _precipitation_probability_line(summary, jma_precipitation)
    if use_sunset_snapshot:
        display_temperature = _optional_or_fallback(
            summary.temperature_2m_at_sunset, summary.temperature_2m
        )
        display_humidity = _optional_or_fallback(
            summary.relative_humidity_2m_at_sunset, summary.relative_humidity_2m
        )
        display_wind_speed = _optional_or_fallback(
            summary.wind_speed_10m_at_sunset, summary.wind_speed_10m
        )
        display_wind_direction = _optional_or_fallback(
            summary.wind_direction_10m_at_sunset, summary.wind_direction_10m
        )
        display_visibility = _optional_or_fallback(
            summary.visibility_at_sunset_snapshot, summary.visibility
        )
        sunset_line = f"日没：{summary.sunset_time.strftime('%H:%M')}"
    else:
        display_temperature = _optional_or_fallback(
            summary.temperature_2m_at_run_time, summary.temperature_2m
        )
        display_humidity = summary.relative_humidity_2m
        display_wind_speed = summary.wind_speed_10m
        display_wind_direction = summary.wind_direction_10m
        display_visibility = summary.visibility
        sunset_line = f"日没：{summary.sunset_time.strftime('%H:%M')}"
    return f"""{summary.date} {summary.run_time}

Sunset期待度【 {display_sunset_label} 】{display_sunset_score} / 100
Chill指数【 {scores.chill_label} 】{scores.chill_score} / 100
コメント：
{comment}

{sunset_line}
気温：{display_temperature:.1f}℃
湿度：{display_humidity:.0f}%
風：{wind_direction_label(display_wind_direction)} {display_wind_speed:.1f}m/s
{precipitation_line}

夕焼け方向の雲
{cloud_line}
視程：{display_visibility / 1000:.1f}km{vision_section}"""


def _optional_or_fallback(value: float | None, fallback: float) -> float:
    return value if value is not None else fallback


def _precipitation_probability_line(
    summary: WeatherSummary,
    jma_precipitation: JmaPrecipitationForecast | None,
) -> str:
    if jma_precipitation is None:
        return f"降水確率：{summary.precipitation_probability:.0f}%"
    return f"降水確率：{jma_precipitation.probability}%"


def wind_direction_label(degrees: float) -> str:
    directions = [
        "北",
        "北北東",
        "北東",
        "東北東",
        "東",
        "東南東",
        "南東",
        "南南東",
        "南",
        "南南西",
        "南西",
        "西南西",
        "西",
        "西北西",
        "北西",
        "北北西",
    ]
    index = int((degrees % 360) / 22.5 + 0.5) % 16
    return directions[index]
