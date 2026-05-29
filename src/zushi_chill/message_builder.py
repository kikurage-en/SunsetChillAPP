from __future__ import annotations

from zushi_chill.models import ScoreResult, WeatherSummary


def build_comment(summary: WeatherSummary, scores: ScoreResult) -> str:
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

    if summary.cloud_cover_low >= 70:
        parts.append("低層雲が多く、夕陽が隠れる可能性があります。")
    if 20 <= summary.cloud_cover_high <= 70 and summary.cloud_cover_low < 50:
        parts.append("高層雲がほどよく、夕焼け色が出る可能性があります。")
    if summary.wind_speed_10m >= 8:
        parts.append("風が強めです。海辺での体感は指数より厳しく感じる可能性があります。")

    return "\n".join(parts)


def build_line_message(
    summary: WeatherSummary,
    scores: ScoreResult,
    *,
    google_form_url: str = "",
) -> str:
    comment = scores.comment or build_comment(summary, scores)
    return f"""【逗子サンセットチル指数｜{summary.date} {summary.run_time}時点】

Chill指数：{scores.chill_score} / 100（{scores.chill_label}）
Sunset期待度：{scores.sunset_score} / 100（{scores.sunset_label}）

日没：{summary.sunset_time.strftime("%H:%M")}
体感温度：{summary.apparent_temperature:.1f}℃
湿度：{summary.relative_humidity_2m:.0f}%
風：{wind_direction_label(summary.wind_direction_10m)} {summary.wind_speed_10m:.1f}m/s
突風：{summary.wind_gusts_10m:.1f}m/s
降水確率：{summary.precipitation_probability:.0f}%
低層雲：{summary.cloud_cover_low:.0f}%
中層雲：{summary.cloud_cover_mid:.0f}%
高層雲：{summary.cloud_cover_high:.0f}%
視程：{summary.visibility / 1000:.1f}km

コメント：
{comment}

検証メモ：
実際の空模様と快適度を「◎ / ○ / △ / ×」で記録してください。
Googleフォーム：
{google_form_url}"""


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
