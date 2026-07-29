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

_PREDICTION_HEADLINE_VARIANTS = {
    ("good", "good"): (
        "わあっ、夕焼けも海辺の気持ちよさも大当たりになりそうっピ！",
        "やったっピ！夕焼けも海辺の気持ちよさも、どっちも期待大っピ！",
        "きょうは空も海辺もごきげんそうっピ！すてきな夕方になりそうっピ！",
    ),
    ("good", "medium"): (
        "夕焼けはすっごく期待できそうっピ！海辺の過ごしやすさは、まあまあっピ。",
        "夕焼けはかなり楽しみっピ！海辺の居心地は、ほどほどっピ。",
        "空の色には期待できそうっピ！海辺はちょっぴり様子見っピ。",
    ),
    ("good", "low"): (
        "夕焼けはきれいになりそうっピ！でも海辺はちょっと大変かもっピ……。",
        "夕焼けはやる気いっぱいっピ！でも海辺の快適さは元気がないっピ……。",
        "きれいな空になりそうっピ！海辺でのんびりするには少し厳しそうっピ。",
    ),
    ("medium", "good"): (
        "海辺は気持ちよさそうっピ！夕焼けも、あとひとがんばりっピ！",
        "海辺はのんびりできそうっピ！夕焼けは、うまく色づけばうれしいっピ。",
        "海辺の気持ちよさは期待大っピ！空の色はもう少し様子見っピ。",
    ),
    ("medium", "medium"): (
        "うーん、どっちも半分くらいっピ。のんびり見守るっピ！",
        "空も海辺も、いいところと心配なところが半分ずつっピ。",
        "どっちもほどほどっピ。すごすぎないけど悪くもなさそうっピ。",
    ),
    ("medium", "low"): (
        "夕焼けは少し期待できそうっピ。"
        "でも海辺の居心地はしょんぼりかもっピ……。",
        "夕焼けはまだ望みがあるっピ。でも海辺は過ごしにくそうっピ……。",
        "空は少しがんばってくれそうっピ。海辺の快適さは弱気っピ……。",
    ),
    ("low", "good"): (
        "夕焼けはむずかしそうっピ……。でも海辺は気持ちよく過ごせそうっピ！",
        "空の色は期待薄っピ……。でも海辺は気持ちよく過ごせそうっピ！",
        "夕焼けはおとなしくなりそうっピ。でも海辺の居心地はよさそうっピ！",
    ),
    ("low", "medium"): (
        "あっ……夕焼けはちょっと苦手な空っピ。海辺は、まあまあっピ。",
        "夕焼けはちょっとむずかしそうっピ……。海辺はほどほどっピ。",
        "空はしょんぼり気味っピ。海辺の過ごしやすさは、まあまあっピ。",
    ),
    ("low", "low"): (
        "きょうは夕焼けも海辺もおやすみ気分っピ……。こんな日もあるっピ。",
        "うーん……空も海辺も今日は元気がなさそうっピ。",
        "きょうはどっちも手ごわそうっピ……。期待は控えめにするっピ。",
    ),
}

_ACTUAL_HEADLINE_VARIANTS = {
    ("good", "good"): (
        "わあっ、夕焼けも海辺の気持ちよさも大当たりっピ！",
        "やったっピ！夕焼けも海辺の居心地も、どっちもいい感じっピ！",
        "空も海辺もごきげんっピ！すてきな夕方っピ！",
    ),
    ("good", "medium"): (
        "夕焼けはすっごくいい感じっピ！海辺の過ごしやすさは、まあまあっピ。",
        "空の色は大当たりっピ！海辺の居心地は、ほどほどっピ。",
        "夕焼けは元気いっぱいっピ！海辺はちょっぴり控えめっピ。",
    ),
    ("good", "low"): (
        "夕焼けはきれいっピ！でも海辺はちょっと大変な状態っピ……。",
        "空の色はいい感じっピ！でも海辺の快適さは元気がないっピ……。",
        "夕焼けは大当たりっピ！海辺でのんびりするには少し厳しいっピ。",
    ),
    ("medium", "good"): (
        "海辺は気持ちいいっピ！夕焼け条件は、もうひと声っピ。",
        "海辺はのんびりできる状態っピ！夕焼けはほどほどっピ。",
        "海辺の居心地はいい感じっピ！空の色はもう少しほしいっピ。",
    ),
    ("medium", "medium"): (
        "うーん、どっちも半分くらいっピ。のんびりした空っピ。",
        "空も海辺も、いいところと惜しいところが半分ずつっピ。",
        "どっちもほどほどっピ。おだやかな夕方っピ。",
    ),
    ("medium", "low"): (
        "夕焼け条件はまあまあっピ。でも海辺の居心地はしょんぼりっピ……。",
        "空は少し色づきやすい条件っピ。でも海辺は過ごしにくいっピ……。",
        "夕焼けはあとひと声っピ。海辺の快適さは弱気っピ……。",
    ),
    ("low", "good"): (
        "夕焼けはむずかしい空っピ……。でも海辺は気持ちよく過ごせる状態っピ！",
        "空の色はしょんぼりっピ……。でも海辺の居心地はいい感じっピ！",
        "夕焼け条件は元気がないっピ。でも海辺はのんびりできるっピ！",
    ),
    ("low", "medium"): (
        "あっ……夕焼けはちょっと苦手な空っピ。海辺は、まあまあっピ。",
        "夕焼け条件はしょんぼりっピ……。海辺の居心地はほどほどっピ。",
        "空の色はむずかしい状態っピ。海辺は、もうひと声っピ。",
    ),
    ("low", "low"): (
        "夕焼けも海辺もおやすみ気分っピ……。こんな日もあるっピ。",
        "うーん……空も海辺も今日は元気がないっピ。",
        "どっちも手ごわい夕方っピ……。静かに見送るっピ。",
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
    chill_band = _comment_band(scores.chill_score)
    headline = _comment_headline(
        sunset_band,
        chill_band,
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
        return _uncertain_prediction_comment(uncertainty, summary)

    details: list[str] = []
    if cloud.cloud_cover_low >= 70:
        details.append(
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
    if summary.apparent_temperature >= 32:
        details.append(
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
        details.append(
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
        details.append(
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
    if 20 <= cloud.cloud_cover_high <= 70 and cloud.cloud_cover_low < 50:
        details.append(
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
    if has_dry_high_precipitation_conflict(summary, cloud):
        details.insert(
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

    # コメント欄も情報過多にしない。総評1文に、優先度が最も高い1件だけ補足する。
    return "\n".join([headline, *details[:1]])


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
    headline = _comment_variant(
        summary,
        f"uncertainty-headline-{summary.run_time}",
        (
            (
                "うーん……まだ先の空は気が変わりそうっピ。"
                "ぼく、ちょっと自信ないっピ……。"
            ),
            (
                "えっと……まだ空の気分が決まってないみたいっピ。"
                "ぼく、強くは言えないっピ……。"
            ),
            (
                "予想がふらふらしてるっピ……。"
                "13時のぼくは、かなり慎重っピ。"
            ),
        )
        if summary.run_time == "13:00"
        else (
            (
                "もうすぐ日没なのに、まだ読み切れないっピ……。"
                "ぼく、ちょっと自信ないっピ。"
            ),
            (
                "日没が近いのに、空の答えが見えないっピ……。"
                "ちょっと弱気っピ。"
            ),
            (
                "えっと、もう夕方なのに予想がまとまらないっピ。"
                "ぼくも迷ってるっピ……。"
            ),
        ),
    )
    details = {
        "missing_values": (
            (
                "予報の数字がところどころぼんやりっピ。"
                "今回はかなり弱気に見てるっピ……。"
            ),
            (
                "空の数字がいくつか見えないっピ……。"
                "ぼくの予想も小さな声になるっピ。"
            ),
            (
                "予報の材料が少し足りないっピ。"
                "今回はそーっと予想するっピ……。"
            ),
        ),
        "convective_weather": (
            (
                "急な雨や雷がまざる予報っピ。"
                "空がころっと変わるかもしれないっピ……。"
            ),
            (
                "にわか雨や雷がひょいっと来るかもっピ……。"
                "空の気分が読みにくいっピ。"
            ),
            (
                "急にざあっと降る可能性があるっピ。"
                "夕方まで油断できないっピ……。"
            ),
        ),
        "rain_timing_shift": (
            (
                "日没前後で雨の予報ががらっと変わるっピ。"
                "まだ言い切れないっピ……。"
            ),
            (
                "日没の前と後で雨の数字が落ち着かないっピ……。"
                "空も迷ってるみたいっピ。"
            ),
            (
                "夕方の途中で雨予報がくるっと変わるっピ。"
                "ぼくも慎重になるっピ……。"
            ),
        ),
        "dry_high_precipitation_conflict": (
            (
                "雨のしるしと予想雨量・西の空が、うまくつながらないっピ。"
                "どっちになるか迷うっピ……。"
            ),
            (
                "雨の確率は高いのに、ほかの数字は晴れっぽいっピ。"
                "うーん、悩ましいっピ……。"
            ),
            (
                "雨のしるしだけが元気すぎるっピ……。"
                "西の空との話が合わないっピ。"
            ),
        ),
        "precipitation_forecast_disagreement": (
            (
                "雨の予報どうしで数字がかなりちがうっピ……。"
                "どっちになるか迷うっピ。"
            ),
            (
                "ふたつの雨予報が別々の答えっピ。"
                "ぼく、どっちを信じるか悩むっピ……。"
            ),
            (
                "雨の数字が予報ごとにばらばらっピ……。"
                "今回は弱気に見るっピ。"
            ),
        ),
        "vision_more_optimistic": (
            (
                "カメラの空はよさそうなのに、予報の数字は弱気っピ……。"
                "判断がむずかしいっピ。"
            ),
            (
                "カメラは元気な空なのに、気象の式はしょんぼりっピ。"
                "どっちになるか迷うっピ……。"
            ),
            (
                "目の前の空と予報の数字が反対方向っピ……。"
                "明るく言い切れないっピ。"
            ),
        ),
        "vision_more_pessimistic": (
            (
                "予報よりカメラの空がしょんぼりっピ……。"
                "期待しすぎないほうがよさそうっピ。"
            ),
            (
                "数字よりカメラの雲が手ごわそうっピ。"
                "ぼく、ちょっと弱気っピ……。"
            ),
            (
                "予報は元気なのに、カメラの空は静かっピ……。"
                "慎重に見てるっピ。"
            ),
        ),
        "borderline_precipitation": (
            (
                "雨が降るか降らないか、予報も迷ってるみたいっピ……。"
                "ぼくも強く言えないっピ。"
            ),
            (
                "雨の確率がちょうど迷いやすいところっピ。"
                "降るとも降らないとも言いにくいっピ……。"
            ),
            (
                "雨の数字がまんなかあたりっピ……。"
                "ぼくの予想もふわふわっピ。"
            ),
        ),
    }
    detail = _comment_variant(
        summary,
        f"uncertainty-detail-{uncertainty}",
        details[uncertainty],
    )
    return "\n".join((headline, detail))


def _comment_headline(
    sunset_band: str,
    chill_band: str,
    *,
    prediction: bool,
    day: str,
    run_time: str,
) -> str:
    category = (
        f"headline-prediction-{sunset_band}-{chill_band}"
        if prediction
        else f"headline-actual-{sunset_band}-{chill_band}"
    )
    variants = (
        _PREDICTION_HEADLINE_VARIANTS[(sunset_band, chill_band)]
        if prediction
        else _ACTUAL_HEADLINE_VARIANTS[(sunset_band, chill_band)]
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
