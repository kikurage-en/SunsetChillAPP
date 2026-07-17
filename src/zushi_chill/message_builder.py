from __future__ import annotations

from zushi_chill.models import ScoreResult, SunsetCloud, VisionResult, WeatherSummary
from zushi_chill.scoring import score_label


def build_comment(
    summary: WeatherSummary,
    scores: ScoreResult,
    sunset_cloud: SunsetCloud | None = None,
) -> str:
    # 雲に関する所見は Sunset期待度を駆動する「夕焼け方向(西の空)」の雲で判断する。
    cloud = sunset_cloud or SunsetCloud.from_summary(summary)
    if scores.chill_score >= 80 and scores.sunset_score >= 70:
        parts = ["夕方の滞在環境、夕陽ともに期待できそうです。実際の空の抜け感を確認してください。"]
    elif scores.chill_score >= 70 and scores.sunset_score < 50:
        parts = ["体感は良さそうですが、低層雲や降水リスクの影響で夕陽は控えめかもしれません。"]
    elif scores.chill_score < 50:
        parts = [
            "風・湿度・雨リスクのいずれかがネックです。実際の滞在感を重点的に確認してください。"
        ]
    else:
        parts = ["夕方の実際の空模様と海辺の体感を確認してください。"]

    if cloud.cloud_cover_low >= 70:
        parts.append("低層雲が多く、夕陽が隠れる可能性があります。")
    if 20 <= cloud.cloud_cover_high <= 70 and cloud.cloud_cover_low < 50:
        parts.append("高層雲がほどよく、夕焼け色が出る可能性があります。")
    if summary.wind_speed_10m >= 8:
        parts.append("風が強めです。海辺での体感は指数より厳しく感じる可能性があります。")

    return "\n".join(parts)


def build_line_message(
    summary: WeatherSummary,
    scores: ScoreResult,
    *,
    vision: VisionResult | None = None,
    vision_mode: str = "actual",
    sunset_cloud: SunsetCloud | None = None,
    final_sunset_score: int | None = None,
    final_sunset_label: str | None = None,
) -> str:
    cloud = sunset_cloud or SunsetCloud.from_summary(summary)
    comment = scores.comment or build_comment(summary, scores, sunset_cloud)
    # 表示する Sunset期待度は Vision ブレンド後の値(未指定なら純式スコア)。
    display_sunset_score = (
        final_sunset_score if final_sunset_score is not None else scores.sunset_score
    )
    display_sunset_label = final_sunset_label or scores.sunset_label
    cloud_line = (
        f"低層 {cloud.cloud_cover_low:.0f}% / 中層 {cloud.cloud_cover_mid:.0f}%"
        f" / 高層 {cloud.cloud_cover_high:.0f}%"
    )
    vision_section = ""
    if vision is not None:
        vision_label = "ライブカメラAI予測" if vision_mode == "predict" else "ライブカメラ実況評価"
        vision_section = (
            f"\n\n📷 {vision_label}\n"
            f"【 {score_label(vision.sunset_score)} 】{vision.sunset_score} / 100"
            f"（{vision.sky_condition}）\n"
            f"{vision.comment}"
        )
    return f"""【逗子サンセットチル指数｜{summary.date} {summary.run_time}】

Sunset期待度【 {display_sunset_label} 】{display_sunset_score} / 100
Chill指数【 {scores.chill_label} 】{scores.chill_score} / 100
コメント：
{comment}

日没：{summary.sunset_time.strftime("%H:%M")}
対象時間帯：{summary.target_window_start.strftime("%H:%M")}〜{summary.target_window_end.strftime("%H:%M")}
体感温度：{summary.apparent_temperature:.1f}℃
湿度：{summary.relative_humidity_2m:.0f}%
風：{wind_direction_label(summary.wind_direction_10m)} {summary.wind_speed_10m:.1f}m/s
突風：{summary.wind_gusts_10m:.1f}m/s
降水確率（最大）：{summary.precipitation_probability:.0f}%

夕焼け方向の雲
{cloud_line}
視程：{summary.visibility / 1000:.1f}km{vision_section}"""


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
