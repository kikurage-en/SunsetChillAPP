from __future__ import annotations

from zushi_chill.comment_variants import select_comment_variant
from zushi_chill.comment_voice import apply_comment_voice
from zushi_chill.constants import RAIN_WEATHER_CODES
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

    comfort_comment = _comfort_comment(summary, prediction=prediction)

    # 1行目は夕焼けだけ、2行目は過ごしやすさの特記事項だけに分ける。
    # 夕焼け側の補足は改行せず、過ごしやすさに特記事項がなければ1行で終える。
    if sunset_details:
        sunset_comment = f"{sunset_comment} {sunset_details[0]}"
    return "\n".join(
        [sunset_comment, *([comfort_comment] if comfort_comment is not None else [])]
    )


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


def _comfort_comment(summary: WeatherSummary, *, prediction: bool) -> str | None:
    wind_speed = max(
        summary.wind_speed_10m,
        _optional_or_fallback(
            summary.wind_speed_10m_at_sunset, summary.wind_speed_10m
        ),
    )
    humidity = _optional_or_fallback(
        summary.relative_humidity_2m_at_sunset, summary.relative_humidity_2m
    )
    temperature = _comfort_temperature(summary, prediction=prediction)
    if (
        not prediction
        and temperature < 27
        and summary.apparent_temperature >= 28
    ):
        return _cool_actual_comment(
            summary,
            temperature=temperature,
            humid=humidity >= 75,
            wind_speed=wind_speed,
        )
    if summary.apparent_temperature < 28:
        return _strong_wind_comment(summary, prediction=prediction) if wind_speed >= 8 else None

    heat_level = "high" if summary.apparent_temperature >= 32 else "moderate"
    heat_comment = _heat_comment(
        summary,
        heat_level=heat_level,
        humid=humidity >= 75,
        prediction=prediction,
    )
    modifier = _comfort_modifier(
        summary,
        wind_speed=wind_speed,
        prediction=prediction,
    )
    return f"{heat_comment}{modifier}"


def _comfort_temperature(summary: WeatherSummary, *, prediction: bool) -> float:
    if prediction:
        return _optional_or_fallback(
            summary.temperature_2m_at_sunset, summary.temperature_2m
        )
    return _optional_or_fallback(
        summary.temperature_2m_at_run_time,
        _optional_or_fallback(summary.temperature_2m_at_sunset, summary.temperature_2m),
    )


def _cool_actual_comment(
    summary: WeatherSummary,
    *,
    temperature: float,
    humid: bool,
    wind_speed: float,
) -> str:
    daytime_max = summary.temperature_2m_daytime_max
    cooled_from_daytime = (
        daytime_max is not None and daytime_max - temperature >= 3
    )
    temperature_band = int(temperature)
    temperature_description = (
        f"気温は{temperature_band}℃台まで下がって"
        if cooled_from_daytime
        else f"気温は{temperature_band}℃台で"
    )
    coolness = "かなり涼しい" if temperature < 26 else "涼しめ"
    rain = (
        summary.weather_code in RAIN_WEATHER_CODES or summary.precipitation >= 1.0
    )

    if wind_speed >= 8:
        condition = "strong-wind"
    elif rain:
        condition = "rain"
    elif humid and wind_speed >= 3:
        condition = "humid-breeze"
    elif humid:
        condition = "humid"
    elif wind_speed >= 3:
        condition = "breeze"
    else:
        condition = "comfortable"

    variants = {
        "strong-wind": (
            f"{temperature_description}、{coolness}っピ！でも、海風は強すぎるっピ。",
            f"{temperature_description}、涼しいっピ。風の強さには注意っピ。",
            f"海辺は{temperature_band}℃台で涼しいっピ！ただ、風がびゅうびゅうっピ。",
        ),
        "rain": (
            f"{temperature_description}、{coolness}っピ！ただ、雨で過ごしにくいっピ。",
            f"{temperature_description}、涼しいっピ。でも、雨は残ってるっピ。",
            f"海辺は{temperature_band}℃台で涼しいっピ！雨には気をつけたいっピ。",
        ),
        "humid-breeze": (
            (
                f"{temperature_description}、{coolness}っピ！"
                "海風も心地いいけど、湿気は少し残ってるっピ。"
            ),
            (
                f"{temperature_description}、風もあるから涼しくて過ごしやすいっピ！"
                "ただ、湿度は高めっピ。"
            ),
            (
                f"海辺は{temperature_band}℃台で、風もあるから涼しいっピ！"
                "湿気だけ少し残ってるっピ。"
            ),
        ),
        "humid": (
            f"{temperature_description}、{coolness}っピ！ただ、湿気は少し残ってるっピ。",
            f"{temperature_description}、涼しいっピ。湿度だけ高めっピ。",
            f"海辺は{temperature_band}℃台で涼しいっピ！でも、少し湿気があるっピ。",
        ),
        "breeze": (
            f"{temperature_description}、海風もあるから涼しくて過ごしやすいっピ！",
            f"{temperature_description}、風も心地よくて涼しいっピ！",
            f"海辺は{temperature_band}℃台で、風もあるから涼しくて快適っピ！",
        ),
        "comfortable": (
            f"{temperature_description}、涼しくてかなり過ごしやすいっピ！",
            f"{temperature_description}、しっかり涼しいっピ！",
            f"海辺は{temperature_band}℃台で、かなり涼しいっピ！",
        ),
    }[condition]
    return _comment_variant(summary, f"cool-actual-{condition}", variants)


def _heat_comment(
    summary: WeatherSummary,
    *,
    heat_level: str,
    humid: bool,
    prediction: bool,
) -> str:
    variants = {
        ("high", True, True): (
            "気温も湿度も高く、海辺はかなりむし暑くなりそうっピ。",
            "暑さに湿気も重なって、海辺の空気はむわっとしそうっピ。",
            "気温の高さと湿気で、蒸し暑さがしっかり残りそうっピ。",
            "ひええ、気温も湿度も高くて、海辺の暑さは本気っピ！",
            "湿気をまとった暑さが、夕方まで続きそうっピ……。",
            "海辺まで熱気と湿気が残って、かなり暑く感じそうっピ。",
        ),
        ("high", True, False): (
            "気温も湿度も高く、海辺はかなり蒸し暑い状態っピ。",
            "暑さに湿気も重なって、海辺の空気がむわっとしてるっピ。",
            "気温の高さと湿気で、蒸し暑さがしっかり残ってるっピ。",
            "ひええ、気温も湿度も高くて、海辺の暑さは本気っピ！",
            "湿気をまとった暑さが、まだ続いてるっピ……。",
            "海辺まで熱気と湿気が残って、かなり暑く感じるっピ。",
        ),
        ("high", False, True): (
            "気温が高く、海辺でもかなり暑くなりそうっピ。",
            "夕方も気温が高く、暑さがしっかり残りそうっピ。",
            "海辺でも気温の高さが手ごわそうっピ。",
            "ひええ、夕方になっても暑さは本気っピ！",
            "高い気温がしぶとく残りそうっピ……。",
            "海辺でも熱気が残って、かなり暑く感じそうっピ。",
        ),
        ("high", False, False): (
            "気温が高く、海辺でもかなり暑い状態っピ。",
            "夕方も気温が高く、暑さがしっかり残ってるっピ。",
            "海辺でも気温の高さが手ごわいっピ。",
            "ひええ、夕方になっても暑さは本気っピ！",
            "高い気温がしぶとく残ってるっピ……。",
            "海辺でも熱気が残って、かなり暑く感じるっピ。",
        ),
        ("moderate", True, True): (
            "気温と湿度が高めで、少しむし暑くなりそうっピ。",
            "湿気と暑さが重なって、海辺は少しむわっとしそうっピ。",
            "気温は高めで湿気もあり、涼しさは控えめになりそうっピ。",
        ),
        ("moderate", True, False): (
            "気温と湿度が高めで、少しむし暑い状態っピ。",
            "湿気と暑さが重なって、海辺は少しむわっとしてるっピ。",
            "気温は高めで湿気もあり、涼しさは控えめっピ。",
        ),
        ("moderate", False, True): (
            "気温は少し高めで、海辺でも暑さが残りそうっピ。",
            "夕方も気温が高めで、涼しさは控えめになりそうっピ。",
            "海辺では少し暑く感じそうっピ。",
        ),
        ("moderate", False, False): (
            "気温は少し高めで、海辺にも暑さが残ってるっピ。",
            "夕方も気温が高めで、涼しさは控えめっピ。",
            "海辺では少し暑く感じる状態っピ。",
        ),
    }[(heat_level, humid, prediction)]
    return _comment_variant(
        summary,
        f"heat-{heat_level}-{'humid' if humid else 'dry'}-"
        f"{'prediction' if prediction else 'actual'}",
        variants,
    )


def _comfort_modifier(
    summary: WeatherSummary,
    *,
    wind_speed: float,
    prediction: bool,
) -> str:
    temperature = _comfort_temperature(summary, prediction=prediction)
    daytime_max = summary.temperature_2m_daytime_max
    cooling = daytime_max is not None and daytime_max - temperature >= 3
    breeze = 3 <= wind_speed < 8
    rain = (
        summary.weather_code in RAIN_WEATHER_CODES or summary.precipitation >= 1.0
    )

    if wind_speed >= 8:
        modifier = "strong-wind"
    elif rain:
        modifier = "rain"
    elif cooling and breeze:
        modifier = "cooling-breeze"
    elif cooling:
        modifier = "cooling"
    elif breeze:
        modifier = "breeze"
    else:
        return ""

    variants = {
        ("strong-wind", True): (
            "それに、海風も強くなりそうで、のんびりはしにくそうっピ。",
            "さらに風まで強まりそうで、海辺では落ち着きにくそうっピ。",
            "おまけに海風も元気すぎそうで、快適さは下がりそうっピ。",
        ),
        ("strong-wind", False): (
            "それに、海風も強くて、のんびりはしにくい状態っピ。",
            "さらに風まで強く、海辺では落ち着きにくい状態っピ。",
            "おまけに海風も元気すぎて、快適さは下がってるっピ。",
        ),
        ("rain", True): (
            "それに、雨の気配もあって、海辺では過ごしにくそうっピ。",
            "さらに雨もありそうで、のんびりするには手ごわそうっピ。",
            "雨の心配も重なって、海辺の快適さは下がりそうっピ。",
        ),
        ("rain", False): (
            "それに、雨の気配もあって、海辺では過ごしにくい状態っピ。",
            "さらに雨もあって、のんびりするには手ごわいっピ。",
            "雨も重なって、海辺の快適さは下がってるっピ。",
        ),
        ("cooling-breeze", True): (
            "でも、日中より気温が下がって、海風もありそうっピ。",
            "でも、昼間との気温差と海風で、少し助かりそうっピ。",
            "でも、夕方は気温が下がり、風もあるぶん少し楽になりそうっピ。",
        ),
        ("cooling-breeze", False): (
            "でも、日中より気温が下がって、海風も吹いてるっピ。",
            "でも、昼間との気温差と海風で、少し助かるっピ。",
            "でも、昼間より気温が低く、風もあるぶん少し楽っピ。",
        ),
        ("cooling", True): (
            "でも、日中より気温が下がるぶん、昼間よりは楽になりそうっピ。",
            "でも、夕方は気温が下がって、暑さが少し和らぎそうっピ。",
            "でも、昼間との気温差があるぶん、少しほっとできそうっピ。",
        ),
        ("cooling", False): (
            "でも、日中より気温が下がって、昼間よりは楽っピ。",
            "でも、夕方になって気温が下がり、暑さは少し和らいでるっピ。",
            "でも、昼間との気温差があるぶん、少しほっとするっピ。",
        ),
        ("breeze", True): (
            "でも、海風があるぶん少し助かりそうっピ。",
            "でも、風があるから、体感は少し楽になりそうっピ。",
            "でも、海からの風が暑さを少しやわらげてくれそうっピ。",
        ),
        ("breeze", False): (
            "でも、海風があるぶん少し助かるっピ。",
            "でも、風があるから、体感は少し楽っピ。",
            "でも、海からの風が暑さを少しやわらげてるっピ。",
        ),
    }[(modifier, prediction)]
    return _comment_variant(
        summary,
        f"comfort-{modifier}-{'prediction' if prediction else 'actual'}",
        variants,
    )


def _strong_wind_comment(summary: WeatherSummary, *, prediction: bool) -> str:
    return _comment_variant(
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
