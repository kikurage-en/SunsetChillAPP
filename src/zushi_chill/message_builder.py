from __future__ import annotations

from zushi_chill.comment_variants import select_comment_variant
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

_ACTUAL_HIGH_HEAT_COMMENTS = (
    "うわっ、むしむしっピ！海辺でもかなり暑い状態っピ。",
    "まだむしむしが残ってるっピ……。海辺の暑さもしぶといっピ。",
    "あれれ、夕方なのに暑いっピ！海辺の空気もまだむわっとしてるっピ。",
    "暑さがなかなか帰ってくれないっピ……。かなり蒸し暑い状態っピ。",
    "むわっとした空気が続いてるっピ。海辺もまだ熱気たっぷりっピ……。",
    "ひええ、空気が重たいっピ！海辺でも蒸し暑さが強いっピ。",
)

_PREDICTION_SUNSET_VARIANTS = {
    "good": (
        "夕焼けはすっごく期待できそうっピ！",
        "夕焼けはかなり楽しみっピ！",
        "空の色には期待できそうっピ！",
    ),
    "medium": (
        "夕焼けは、あとひとがんばりっピ！",
        "空の色はもう少し様子見っピ。",
        "夕焼けは少し期待できそうっピ。",
    ),
    "low": (
        "夕焼けはむずかしそうっピ……。",
        "空の色は期待薄っピ……。",
        "きょうの夕焼けはおやすみ気分っピ……。",
    ),
}

_ACTUAL_SUNSET_VARIANTS = {
    "good": (
        "夕焼けはすっごくいい感じっピ！",
        "空の色は大当たりっピ！",
        "夕焼けは元気いっぱいっピ！",
    ),
    "medium": (
        "夕焼け条件は、もうひと声っピ。",
        "空の色はほどほどっピ。",
        "夕焼けは少し色づきやすい空っピ。",
    ),
    "low": (
        "夕焼けはむずかしい空っピ……。",
        "空の色はしょんぼりっピ……。",
        "夕焼け条件は元気がないっピ。",
    ),
}


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
    sunset_comment = _comment_headline(
        sunset_band,
        prediction=prediction,
        day=summary.date,
        run_time=summary.run_time,
    )
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
        caveat = _uncertain_prediction_comment(uncertainty, summary)
        connector = "でも、" if sunset_band == "good" else "ただ、"
        sunset_comment = f"{sunset_comment} {connector}{caveat}"

    sunset_details: list[str] = []
    if uncertainty is None and cloud.cloud_cover_low >= 70:
        sunset_details.append(
            _comment_variant(
                summary,
                "low-cloud-prediction" if prediction else "low-cloud-actual",
                (
                    (
                        "あっ……低い雲がいっぱいっピ。"
                        "夕陽がかくれちゃうかもしれないっピ。"
                    ),
                    (
                        "うーん、水平線のあたりが雲でぎゅうぎゅうっピ……。"
                        "夕陽が見えにくそうっピ。"
                    ),
                    (
                        "夕陽の通り道に低い雲がいるっピ。"
                        "今日はちょっと手ごわそうっピ……。"
                    ),
                )
                if prediction
                else (
                    "あっ……低い雲がいっぱいっピ。夕陽がかくれやすい空っピ。",
                    (
                        "水平線のあたりが低い雲でいっぱいっピ……。"
                        "夕陽が見えにくい空っピ。"
                    ),
                    (
                        "夕陽の通り道を低い雲がふさいでるっピ。"
                        "ちょっと手ごわい空っピ……。"
                    ),
                ),
            )
        )
    if (
        uncertainty is None
        and 20 <= cloud.cloud_cover_high <= 70
        and cloud.cloud_cover_low < 50
    ):
        sunset_details.append(
            _comment_variant(
                summary,
                "high-cloud-prediction" if prediction else "high-cloud-actual",
                (
                    (
                        "わあっ、高い雲がちょうどいいっピ！"
                        "きれいな色になってくれそうっピ！"
                    ),
                    (
                        "高い雲がいい場所にいるっピ！"
                        "夕焼け色をひろってくれそうっピ！"
                    ),
                    (
                        "わくわくっピ！高い雲がきれいな色の"
                        "キャンバスになりそうっピ！"
                    ),
                )
                if prediction
                else (
                    (
                        "わあっ、高い雲がちょうどいいっピ！"
                        "夕焼け色が出やすい空っピ！"
                    ),
                    (
                        "高い雲がいい場所にいるっピ！"
                        "夕焼け色をひろいやすい空っピ！"
                    ),
                    (
                        "高い雲が色のキャンバスになりやすい空っピ！"
                        "ちょっとわくわくっピ！"
                    ),
                ),
            )
        )
    if uncertainty is None and has_dry_high_precipitation_conflict(summary, cloud):
        sunset_details.insert(
            0,
            _comment_variant(
                summary,
                (
                    "dry-rain-conflict-prediction"
                    if prediction
                    else "dry-rain-conflict-actual"
                ),
                (
                    (
                        "あれれ……雨のしるしと予想雨量・西の空が、"
                        "うまくつながらないっピ。"
                        "きょうの夕焼け予想はむずかしいっピ。"
                    ),
                    (
                        "雨の予報と西の空が別々のことを言ってるっピ……。"
                        "ぼく、ちょっと迷うっピ。"
                    ),
                    (
                        "数字は雨っぽいのに、空の条件はちがって見えるっピ。"
                        "まだ言い切れないっピ……。"
                    ),
                )
                if prediction
                else (
                    (
                        "あれれ……雨のしるしと予想雨量・西の空が、"
                        "うまくつながらないっピ。算出条件が不確かっピ。"
                    ),
                    (
                        "雨の数字と西の空が別々のことを言ってるっピ……。"
                        "判断がむずかしい状態っピ。"
                    ),
                    (
                        "降水信号と空の条件がかみ合ってないっピ。"
                        "今回はちょっと不確かっピ……。"
                    ),
                ),
            ),
        )

    comfort_details: list[str] = []
    if summary.apparent_temperature >= 32:
        comfort_details.append(
            _comment_variant(
                summary,
                "high-heat-prediction" if prediction else "high-heat-actual",
                (
                    "うわっ、むしむしっピ！海辺でもかなり暑く感じそうっピ。",
                    "ひええ、暑さが本気っピ！海辺でもむしむしが強くなりそうっピ。",
                    (
                        "空気がむわっとしそうっピ……。"
                        "海辺でもかなり暑く感じそうっピ。"
                    ),
                )
                if prediction
                else _ACTUAL_HIGH_HEAT_COMMENTS,
            )
        )
    elif summary.apparent_temperature >= 28:
        comfort_details.append(
            _comment_variant(
                summary,
                "moderate-heat-prediction" if prediction else "moderate-heat-actual",
                (
                    "海辺ではちょっとむしむししそうっピ。",
                    "少しむしむししそうっピ。海辺も涼しさは控えめっピ。",
                    (
                        "海辺の空気がちょっぴり重たそうっピ。"
                        "少し暑く感じそうっピ。"
                    ),
                )
                if prediction
                else (
                    "海辺ではちょっとむしむしする状態っピ。",
                    "海辺の空気がちょっぴり重たいっピ。少しむしむしっピ。",
                    "まだ少し暑さが残ってるっピ。海辺も涼しさは控えめっピ。",
                ),
            )
        )
    if summary.wind_speed_10m >= 8:
        comfort_details.append(
            _comment_variant(
                summary,
                "strong-wind-prediction" if prediction else "strong-wind-actual",
                (
                    (
                        "風がびゅうびゅうになりそうっピ！"
                        "海辺ののんびり度が下がりそうっピ。"
                    ),
                    "海風が元気すぎるかもっピ！のんびりするには強そうっピ。",
                    (
                        "びゅーっと強い風になりそうっピ。"
                        "海辺の快適さが逃げちゃいそうっピ……。"
                    ),
                )
                if prediction
                else (
                    "風がびゅうびゅうっピ！海辺ののんびり度が下がる状態っピ。",
                    "海風が元気すぎるっピ！のんびりするには強い風っピ。",
                    "びゅーっと強い風っピ。海辺の快適さが逃げちゃうっピ……。",
                ),
            )
        )

    # 1行目は夕焼けだけ、2行目は過ごしやすさの特記事項だけに分ける。
    # 夕焼け側の補足は改行せず、過ごしやすさに特記事項がなければ1行で終える。
    if sunset_details:
        sunset_comment = f"{sunset_comment} {sunset_details[0]}"
    return "\n".join([sunset_comment, *comfort_details[:1]])


def _comment_variant(
    summary: WeatherSummary,
    category: str,
    variants: tuple[str, ...],
) -> str:
    return select_comment_variant(
        summary.date,
        summary.run_time,
        category,
        variants,
    )


def _uncertain_prediction_comment(
    uncertainty: PredictionUncertainty,
    summary: WeatherSummary,
) -> str:
    details = {
        "missing_values": (
            "空の様子がまだつかみにくくて、自信は少し控えめっピ。",
            "夕方の空がまだぼんやりしていて、そーっと見てるっピ。",
            "空模様を読む材料が少なくて、ちょっぴり慎重っピ。",
            "日没ごろの空がまだ見通しにくくて、強くは言えないっピ。",
            "空の変わり方がまだつかめなくて、自信は小さめっピ。",
        ),
        "convective_weather": (
            "急な雨や雷で空がころっと変わるかもしれないっピ。",
            "にわか雨で空模様が急に変わりそうっピ。",
            "夕方は天気がばたばた変わるかもしれなくて、少し慎重っピ。",
            "急にざあっと降るかもしれないから、空の変化には注意っピ。",
            "雷や急な雨で、夕焼けのころに空が落ち着かないかもしれないっピ。",
        ),
        "rain_timing_shift": (
            "日没前後は天気が急に変わりそうっピ。",
            "夕方の途中で空模様がくるっと変わるかもしれないっピ。",
            "日没の前後で空が落ち着きにくくて、少し慎重っピ。",
            "夕焼けのころは天気が変わりやすそうっピ。",
            "空模様の切り替わりが早そうで、自信は少し控えめっピ。",
        ),
        "dry_high_precipitation_conflict": (
            "空模様がちぐはぐで、少し慎重っピ。",
            "雨の気配と西の空がかみ合わなくて、自信は控えめっピ。",
            "空は明るそうなのに雨の気配もあって、少し落ち着かないっピ。",
            "西の空はよさそうだけど、天気が急に変わるかもしれないっピ。",
            "空の条件がそろい切らなくて、そーっと見てるっピ。",
        ),
        "precipitation_forecast_disagreement": (
            "空模様は変わりやすそうで、自信は少し控えめっピ。",
            "天気が急に変わるかもしれなくて、ちょっぴり慎重っピ。",
            "不安定な空模様になりそうで、まだ油断はできないっピ。",
            "空が落ち着きにくそうだから、自信は少しだけ控えめっピ。",
            "夕方の天気が揺れやすそうで、そーっと見守るっピ。",
        ),
        "vision_more_optimistic": (
            "今の空と周りの条件がかみ合わなくて、少し慎重っピ。",
            "目の前の空はよさそうだけど、急に変わるかもしれないっピ。",
            "空は明るく見えるけど、このあと変わりやすそうっピ。",
            "見えている空は元気だけど、まだ油断はできないっピ。",
            "今の空は期待寄りだけど、先の変化には少し慎重っピ。",
        ),
        "vision_more_pessimistic": (
            "目の前の雲が少し手ごわそうっピ。",
            "今の空は思ったより静かで、自信は少し控えめっピ。",
            "空がしょんぼりしていて、期待しすぎないほうがよさそうっピ。",
            "目の前の空が暗めで、ちょっぴり慎重っピ。",
            "雲が元気すぎて、夕焼けの邪魔をするかもしれないっピ。",
        ),
        "borderline_precipitation": (
            "雨になるかはっきりしない空で、少し慎重っピ。",
            "降るかどうか迷いやすい空模様で、自信は控えめっピ。",
            "雨の気配が行ったり来たりして、空が落ち着かなさそうっピ。",
            "夕方は降るか降らないか、まだ揺れそうっピ。",
            "空模様がどちらにも転びそうで、そーっと見てるっピ。",
        ),
    }
    detail = _comment_variant(
        summary,
        f"uncertainty-detail-{uncertainty}",
        details[uncertainty],
    )
    return detail


def _comment_headline(
    sunset_band: str,
    *,
    prediction: bool,
    day: str,
    run_time: str,
) -> str:
    category = (
        f"headline-prediction-{sunset_band}"
        if prediction
        else f"headline-actual-{sunset_band}"
    )
    variants = (
        _PREDICTION_SUNSET_VARIANTS[sunset_band]
        if prediction
        else _ACTUAL_SUNSET_VARIANTS[sunset_band]
    )
    return select_comment_variant(day, run_time, category, variants)


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
