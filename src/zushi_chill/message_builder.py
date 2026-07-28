from __future__ import annotations

from zushi_chill.comment_voice import apply_comment_voice
from zushi_chill.models import (
    JmaPrecipitationForecast,
    ScoreResult,
    SunsetCloud,
    VisionResult,
    WeatherSummary,
)
from zushi_chill.prediction_uncertainty import (
    PredictionUncertainty,
    detect_prediction_uncertainty,
)
from zushi_chill.scoring import has_dry_high_precipitation_conflict, score_label


def build_comment(
    summary: WeatherSummary,
    scores: ScoreResult,
    sunset_cloud: SunsetCloud | None = None,
    *,
    prediction: bool = True,
    vision: VisionResult | None = None,
    formula_sunset_score: int | None = None,
    jma_precipitation: JmaPrecipitationForecast | None = None,
) -> str:
    # 雲に関する所見は Sunset期待度を駆動する「夕焼け方向(西の空)」の雲で判断する。
    cloud = sunset_cloud or SunsetCloud.from_summary(summary)
    sunset_band = _comment_band(scores.sunset_score)
    chill_band = _comment_band(scores.chill_score)
    headline = _comment_headline(sunset_band, chill_band, prediction=prediction)
    uncertainty = (
        detect_prediction_uncertainty(
            summary,
            cloud,
            vision=vision,
            formula_sunset_score=formula_sunset_score,
            jma_precipitation=jma_precipitation,
        )
        if prediction
        else None
    )
    if uncertainty is not None:
        return _uncertain_prediction_comment(uncertainty, summary.run_time)

    details: list[str] = []
    if cloud.cloud_cover_low >= 70:
        details.append(
            "あっ……低い雲がいっぱいっピ。夕陽がかくれちゃうかもしれないっピ。"
            if prediction
            else "あっ……低い雲がいっぱいっピ。夕陽がかくれやすい空っピ。"
        )
    if summary.apparent_temperature >= 32:
        details.append(
            "うわっ、むしむしっピ！海辺でもかなり暑く感じそうっピ。"
            if prediction
            else "うわっ、むしむしっピ！海辺でもかなり暑い状態っピ。"
        )
    elif summary.apparent_temperature >= 28:
        details.append(
            "海辺ではちょっとむしむししそうっピ。"
            if prediction
            else "海辺ではちょっとむしむしする状態っピ。"
        )
    if summary.wind_speed_10m >= 8:
        details.append(
            "風がびゅうびゅうになりそうっピ！海辺ののんびり度が下がりそうっピ。"
            if prediction
            else "風がびゅうびゅうっピ！海辺ののんびり度が下がる状態っピ。"
        )
    if 20 <= cloud.cloud_cover_high <= 70 and cloud.cloud_cover_low < 50:
        details.append(
            "わあっ、高い雲がちょうどいいっピ！きれいな色になってくれそうっピ！"
            if prediction
            else "わあっ、高い雲がちょうどいいっピ！夕焼け色が出やすい空っピ！"
        )
    if has_dry_high_precipitation_conflict(summary, cloud):
        details.insert(
            0,
            (
                "あれれ……雨のしるしと予想雨量・西の空が、"
                "うまくつながらないっピ。きょうの夕焼け予想はむずかしいっピ。"
                if prediction
                else "あれれ……雨のしるしと予想雨量・西の空が、"
                "うまくつながらないっピ。算出条件が不確かっピ。"
            ),
        )

    # コメント欄も情報過多にしない。総評1文に、優先度が最も高い1件だけ補足する。
    return "\n".join([headline, *details[:1]])


def _uncertain_prediction_comment(
    uncertainty: PredictionUncertainty,
    run_time: str,
) -> str:
    headline = (
        "うーん……まだ先の空は気が変わりそうっピ。"
        "ぼく、ちょっと自信ないっピ……。"
        if run_time == "13:00"
        else "もうすぐ日没なのに、まだ読み切れないっピ……。"
        "ぼく、ちょっと自信ないっピ。"
    )
    details = {
        "missing_values": (
            "予報の数字がところどころぼんやりっピ。"
            "今回はかなり弱気に見てるっピ……。"
        ),
        "convective_weather": (
            "急な雨や雷がまざる予報っピ。"
            "空がころっと変わるかもしれないっピ……。"
        ),
        "rain_timing_shift": (
            "日没前後で雨の予報ががらっと変わるっピ。"
            "まだ言い切れないっピ……。"
        ),
        "dry_high_precipitation_conflict": (
            "雨のしるしと予想雨量・西の空が、うまくつながらないっピ。"
            "どっちになるか迷うっピ……。"
        ),
        "precipitation_forecast_disagreement": (
            "雨の予報どうしで数字がかなりちがうっピ……。"
            "どっちになるか迷うっピ。"
        ),
        "vision_more_optimistic": (
            "カメラの空はよさそうなのに、予報の数字は弱気っピ……。"
            "判断がむずかしいっピ。"
        ),
        "vision_more_pessimistic": (
            "予報よりカメラの空がしょんぼりっピ……。"
            "期待しすぎないほうがよさそうっピ。"
        ),
        "borderline_precipitation": (
            "雨が降るか降らないか、予報も迷ってるみたいっピ……。"
            "ぼくも強く言えないっピ。"
        ),
    }
    return "\n".join((headline, details[uncertainty]))


def _comment_headline(sunset_band: str, chill_band: str, *, prediction: bool) -> str:
    if prediction:
        headlines = {
            ("good", "good"): (
                "わあっ、夕焼けも海辺の気持ちよさも大当たりになりそうっピ！"
            ),
            ("good", "medium"): (
                "夕焼けはすっごく期待できそうっピ！海辺の過ごしやすさは、まあまあっピ。"
            ),
            ("good", "low"): (
                "夕焼けはきれいになりそうっピ！でも海辺はちょっと大変かもっピ……。"
            ),
            ("medium", "good"): (
                "海辺は気持ちよさそうっピ！夕焼けも、あとひとがんばりっピ！"
            ),
            ("medium", "medium"): (
                "うーん、どっちも半分くらいっピ。のんびり見守るっピ！"
            ),
            ("medium", "low"): (
                "夕焼けは少し期待できそうっピ。"
                "でも海辺の居心地はしょんぼりかもっピ……。"
            ),
            ("low", "good"): (
                "夕焼けはむずかしそうっピ……。でも海辺は気持ちよく過ごせそうっピ！"
            ),
            ("low", "medium"): (
                "あっ……夕焼けはちょっと苦手な空っピ。海辺は、まあまあっピ。"
            ),
            ("low", "low"): (
                "きょうは夕焼けも海辺もおやすみ気分っピ……。こんな日もあるっピ。"
            ),
        }
        return headlines[(sunset_band, chill_band)]

    headlines = {
        ("good", "good"): "わあっ、夕焼けも海辺の気持ちよさも大当たりっピ！",
        ("good", "medium"): (
            "夕焼けはすっごくいい感じっピ！海辺の過ごしやすさは、まあまあっピ。"
        ),
        ("good", "low"): (
            "夕焼けはきれいっピ！でも海辺はちょっと大変な状態っピ……。"
        ),
        ("medium", "good"): (
            "海辺は気持ちいいっピ！夕焼け条件は、もうひと声っピ。"
        ),
        ("medium", "medium"): (
            "うーん、どっちも半分くらいっピ。のんびりした空っピ。"
        ),
        ("medium", "low"): (
            "夕焼け条件はまあまあっピ。でも海辺の居心地はしょんぼりっピ……。"
        ),
        ("low", "good"): (
            "夕焼けはむずかしい空っピ……。でも海辺は気持ちよく過ごせる状態っピ！"
        ),
        ("low", "medium"): (
            "あっ……夕焼けはちょっと苦手な空っピ。海辺は、まあまあっピ。"
        ),
        ("low", "low"): (
            "夕焼けも海辺もおやすみ気分っピ……。こんな日もあるっピ。"
        ),
    }
    return headlines[(sunset_band, chill_band)]


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
        vision=vision,
        formula_sunset_score=scores.sunset_score,
        jma_precipitation=jma_precipitation,
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
            f"{apply_comment_voice(vision.comment)}{detail_section}"
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
