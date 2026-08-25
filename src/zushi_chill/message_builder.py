from __future__ import annotations

import re

from zushi_chill.comment_variants import select_comment_variant
from zushi_chill.comment_voice import (
    apply_comment_voice,
    place_interjection_at_comment_start,
)
from zushi_chill.constants import RAIN_WEATHER_CODES
from zushi_chill.models import (
    JmaPrecipitationForecast,
    ScoreResult,
    SunsetCloud,
    SunsetPredictionReference,
    VisionResult,
    WeatherSummary,
)
from zushi_chill.prediction_uncertainty import (
    PredictionUncertainty,
    detect_prediction_uncertainty,
)
from zushi_chill.scoring import (
    has_dry_high_precipitation_conflict,
    normalize_prediction_vision_score,
    score_label,
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

_ACTUAL_COMPARISON_VARIANTS = {
    ("favorable", "visible"): (
        "期待より少し控えめな夕焼けだっピ。",
        "楽しみにしてたけど、色づきは小さめだったっピ。",
        "思っていたより、おとなしい夕焼けだっピ。",
        "期待したほどは色が伸びなかったっピ。",
        "きれいには染まったけど、期待よりやさしい色だっピ。",
        "楽しみにしてたぶん、もうひと声ほしかったっピ。",
        "期待には少し届かなかったけど、夕焼け色は見えたっピ。",
    ),
    ("favorable", "absent"): (
        "楽しみにしてたけど、夕焼けはほとんど見えなかったっピ……。",
        "期待してたけど、空はほとんど染まらなかったっピ……。",
        "待ってた夕焼け色は、今日は出てくれなかったっピ……。",
        "楽しみにしてたぶん、ちょっぴり残念な空だっピ……。",
        "きれいに染まりそうだったけど、色は出なかったっピ……。",
        "期待した夕焼けには、届かなかったっピ……。",
        "わくわくしてたけど、夕焼けはおやすみだったっピ……。",
    ),
    ("uncertain", "vivid"): (
        "思っていたより、ずっときれいな夕焼けだっピ！",
        "わあっ！予想以上に空がきれいに染まったっピ！",
        "思いがけず、鮮やかな夕焼けになったっピ！",
        "迷っていた空が、きれいな色を見せてくれたっピ！",
        "思った以上に、空いっぱいに色が広がったっピ！",
        "予想を越えて、見ごたえのある夕焼けになったっピ！",
        "うれしい方に転んで、きれいな夕焼けになったっピ！",
    ),
    ("uncertain", "absent"): (
        "思ったより色づかず、夕焼けはほとんど見えなかったっピ……。",
        "空の色は、思っていたより静かなままだったっピ……。",
        "夕焼け色は、ほとんど出てくれなかったっピ……。",
        "今日は空が染まらないまま終わったっピ……。",
        "もう少し色づくかと思ったけど、夕焼けは見えなかったっピ……。",
        "きれいな色は出ず、静かな空のままだったっピ……。",
        "夕焼けは、思っていたより元気がなかったっピ……。",
    ),
    ("pessimistic", "vivid"): (
        "心配してたけど、きれいな夕焼けになったっピ！",
        "わあっ！思いがけず空が鮮やかに染まったっピ！",
        "むずかしいと思ってたのに、夕焼けは大当たりっピ！",
        "心配を吹き飛ばす、きれいな夕焼けだっピ！",
        "思った以上に、空が元気な色を見せてくれたっピ！",
        "あきらめかけてたけど、空がきれいに染まったっピ！",
        "うれしいびっくりの夕焼けになったっピ！",
    ),
    ("pessimistic", "visible"): (
        "心配したほど悪くなく、空が少し色づいたっピ。",
        "むずかしいと思ってたけど、夕焼け色が少し見えたっピ。",
        "思っていたより、やさしい色が出てくれたっピ。",
        "あきらめかけてたけど、小さな夕焼けを見つけたっピ。",
        "心配してた空にも、少しだけ色が出たっピ。",
        "うれしい方に外れて、空がほんのり染まったっピ。",
        "夕焼けは小さめだけど、思ったより色づいたっピ。",
    ),
}

_ACTUAL_CAMERA_SUMMARY_VARIANTS = {
    "vivid": (
        "きれいな夕焼けになったっピ！",
        "空が元気に染まったっピ！",
        "夕焼けは大当たりっピ！",
        "わあっ！空がきれいに色づいたっピ！",
        "うれしい夕焼けになったっピ！",
        "空いっぱいに夕焼け色が広がったっピ！",
        "見ごたえのある夕焼けだっピ！",
    ),
    "visible": (
        "ほどよく色づいた夕焼けだっピ。",
        "空に夕焼け色が少し見えたっピ。",
        "やさしい色の夕焼けになったっピ。",
        "夕焼けは、もうひと声っピ。",
        "空がほんのり色づいたっピ。",
        "控えめだけど、夕焼け色が見えたっピ。",
        "小さな夕焼けを見つけたっピ。",
    ),
    "absent": (
        "きょうの夕焼けは控えめだったっピ……。",
        "空の色はおやすみ気分だったっピ……。",
        "夕焼けはちょっぴり元気がなかったっピ……。",
        "きれいな色は、ほとんど出なかったっピ……。",
        "空はほとんど染まらなかったっピ……。",
        "夕焼け色は小さめだったっピ……。",
        "きょうの空は静かなままだったっピ……。",
    ),
}

_AFTER_SUNSET_ENCOURAGEMENT_VARIANTS = (
    "モヤモヤは、夕焼けといっしょにそっと流しちゃうっピ。",
    "深呼吸ひとつぶん、この空を眺めてみるっピ。",
    "夕焼けを見ながら、肩の力をふわっと抜くっピ。",
    "今日の疲れは、この空にちょっとだけ預けるっピ。",
    "空の色が変わる速さに合わせて、気持ちもゆっくりでいいっピ。",
    "なんにも決めずに、ただきれいだなって眺める時間も大事っピ。",
    "忙しい日ほど、空を見上げる小さな寄り道をするっピ。",
    "空を見上げる数秒だけは、自分のための時間っピ。",
    "今日の終わりに、やさしい色をひとつ持って帰るっピ。",
    "夕焼けの色を心にしまって、今日をやさしく終えるっピ。",
    "今日のきれいな空は、ここまでがんばったごほうびっピ！",
    "きょうも一日、おつかれさまっピ。夕焼けの時間はのんびりするっピ。",
    "ひと休みしても大丈夫っピ。いまは空の色を楽しむっピ。",
    "思いどおりじゃない日にも、きれいな空はちゃんとあるっピ。",
    "空がこんなにきれいなら、今日はそれだけでも悪くないっピ。",
    "きょうの空から、ちいさな元気を分けてもらうっピ！",
    "きれいな夕焼けを見つけた日は、ちょっぴり得した気分っピ！",
    "忙しさのすきまに、空のきれいをひとつ置いておくっピ。",
    "今日のモヤモヤより、この空の色を少しだけ長く覚えておくっピ。",
    "あせる気持ちはひと休みっピ。空はゆっくり色づいてるっピ。",
    "今日はもう十分がんばったっピ。あとは夕焼けに任せるっピ。",
    "この夕焼けが、今日の気持ちをそっとほどいてくれたらうれしいっピ。",
    "いい日もそうじゃない日も、夕焼けがおつかれさまって光ってるっピ。",
    "小さないいことを探すなら、今日の夕焼けは大当たりっピ！",
)

_WEATHER_ENCOURAGEMENT_VARIANTS = {
    "hot": (
        "暑い一日だったから、夕焼けを見ながらゆっくりクールダウンするっピ。",
        "暑さが残る夕方も、空の色といっしょにひと息つくっピ。",
        "むし暑さは残ってるけど、きれいな空が気持ちを軽くしてくれるっピ。",
    ),
    "breeze": (
        "海風を感じながら、今日の疲れをそっとほどくっピ。",
        "風が気持ちいい夕方は、深呼吸をひとつしてみるっピ。",
        "夕焼けと海風に、今日のモヤモヤを預けるっピ。",
    ),
    "cool": (
        "涼しい風と夕焼けに、今日の疲れを預けるっピ。",
        "涼しくなった空気のなかで、きれいな色をゆっくり味わうっピ。",
        "ひんやりした夕方っピ。心ものんびり休ませるっピ。",
    ),
    "cooling": (
        "昼間の暑さがやわらいだら、夕焼けといっしょにひと休みするっピ。",
        "暑かった一日の終わりに、やさしい空の色が待ってたっピ。",
        "気温も気持ちも、夕焼けといっしょにゆっくり落ち着けるっピ。",
    ),
}

_PREDICTION_CAMERA_COMMENT_VARIANTS = {
    ("aligned", "good"): (
        "今の空なら、夕焼けはかなり楽しみっピ！",
        "きれいに染まりそうな空で、夕焼けに期待できそうっピ！",
        "目の前の雲もよさそうで、夕焼けが楽しみっピ！",
        "いま見える空なら、きれいな色を期待したいっピ！",
        "空の条件がそろって、夕焼けには期待大っピ！",
        "いまの空は、夕焼けにぴったりの表情っピ！",
        "色づきそうな雲がいて、夕焼けが楽しみっピ！",
    ),
    ("aligned", "medium"): (
        "今の空だと、夕焼けはまだ五分五分っピ。",
        "色づくチャンスはありそうだけど、もう少し様子見っピ。",
        "いまの空なら、夕焼けは半々くらいっピ。",
        "きれいに染まるかは、まだそっと見守りたいっピ。",
        "空の様子は悪くないけど、夕焼けはもうひと声っピ。",
        "いま見える雲だと、色づきはまだ微妙っピ。",
        "小さなチャンスはありそうで、夕焼けは五分五分っピ。",
    ),
    ("aligned", "low"): (
        "今の雲だと、夕焼けはむずかしそうっピ……。",
        "目の前の空は手ごわくて、期待は控えめっピ……。",
        "いま見える雲では、きれいな色はむずかしそうっピ……。",
        "空がちょっぴり元気不足で、夕焼けは慎重っピ……。",
        "目の前の雲が厚く、色づきは期待薄っピ……。",
        "今の空はおとなしくて、夕焼けは手ごわそうっピ……。",
        "雲が夕陽の道をふさいで、期待は小さめっピ……。",
    ),
    ("camera-more-pessimistic", "good"): (
        "今の空は少し控えめだけど、夕焼けには期待できそうっピ！",
        "目の前の雲は気になるけど、きれいな色は楽しみっピ！",
        "空は少し迷ってるけど、夕焼けは期待寄りっピ！",
        "今の空はおとなしいけど、色づくチャンスはありそうっピ！",
        "雲は少し手ごわいけど、夕焼けはまだ楽しみっピ！",
        "目の前の空は控えめでも、きれいな色に期待したいっピ！",
        "今の雲には迷うけど、夕焼けの望みは大きめっピ！",
    ),
    ("camera-more-pessimistic", "medium"): (
        "天気の条件はよさそうだけど、今の空だと夕焼けは五分五分っピ。",
        "条件は期待寄りだけど、目の前の空はもう少し様子見っピ。",
        "染まりそうな条件だけど、今の空ではまだ半々っピ。",
        "天気は味方しそうだけど、目の前の雲には少し慎重っピ。",
        "条件は悪くないけど、今の空だと色づきはまだ微妙っピ。",
        "きれいに染まる条件はあるけど、今の空はもうひと声っピ。",
        "天気の条件はよくても、目の前の空では五分五分っピ。",
    ),
    ("camera-more-pessimistic", "low"): (
        "条件は悪くないけど、今の雲だと夕焼けはむずかしそうっピ……。",
        "天気は味方してても、目の前の空だと夕焼けは手ごわそうっピ……。",
        "染まりそうな条件でも、今の雲だと夕焼けは期待控えめっピ……。",
        "条件はよさそうだけど、目の前の空だと夕焼けは元気不足っピ……。",
        "天気の条件は悪くなくても、夕焼けはむずかしそうっピ……。",
        "条件はあるけど、今の空だと夕焼けは慎重に待ちたいっピ……。",
        "条件より目の前の雲が手ごわくて、夕焼けの期待は小さめっピ……。",
    ),
    ("camera-more-optimistic", "good"): (
        "条件は手ごわそうだけど、今の空には夕焼けのチャンスがあるっピ！",
        "天気の条件は控えめでも、目の前の空には期待できそうっピ！",
        "条件は厳しそうだけど、今の空ならきれいに染まりそうっピ！",
        "天気は心配でも、目の前の雲は夕焼け向きっピ！",
        "条件はもうひと声だけど、今の空には期待大っピ！",
        "天気の条件より今の空が元気で、夕焼けが楽しみっピ！",
        "条件は気がかりでも、目の前の空にはチャンスが見えるっピ！",
    ),
    ("camera-more-optimistic", "medium"): (
        "条件は控えめだけど、今の空なら夕焼けを少し期待できそうっピ。",
        "天気の条件は手ごわいけど、目の前の空には少し望みがあるっピ。",
        "条件は厳しそうでも、今の空なら夕焼けは五分五分っピ。",
        "天気は心配だけど、目の前の雲には色づく余地があるっピ。",
        "条件はもうひと声でも、今の空には小さなチャンスがあるっピ。",
        "天気の条件より今の空が明るく、少し期待したいっピ。",
        "条件は気がかりだけど、目の前の空はもう少し見守りたいっピ。",
    ),
    ("camera-more-optimistic", "low"): (
        "今の空に少し望みはあるけど、夕焼けはまだ手ごわそうっピ……。",
        "目の前の空は少し明るいけど、色づきは慎重に待ちたいっピ……。",
        "空に小さなチャンスはあるけど、期待はまだ控えめっピ……。",
        "今の雲は少しよさそうでも、夕焼けはむずかしそうっピ……。",
        "目の前の空には望みがあるけど、まだ油断できないっピ……。",
        "空は少し元気でも、きれいな色にはもうひと声っピ……。",
        "今の空は明るめだけど、夕焼けはそっと待ちたいっピ……。",
    ),
}

_CLEAR_SKY_PREDICTION_VARIANTS = (
    "快晴で、夕日はよく見えそうっピ！でも、色づきは控えめかもしれないっピ。",
    "太陽はしっかり見えそうっピ！でも、雲が少なくて、空の色はおだやかになりそうっピ。",
    "夕日はくっきり見えそうっピ！でも、派手な色づきは少しむずかしそうっピ。",
    "晴れた空で、夕日はよく見えそうっピ！でも、焼け方はやさしめになりそうっピ。",
    "夕日を見るにはよさそうな空っピ！でも、鮮やかさは控えめかもしれないっピ。",
    "太陽を見送れそうな快晴っピ！でも、空の色は淡くなりそうっピ。",
    "夕日は見つけやすそうっピ！でも、雲が少ないぶん、色づきは穏やかそうっピ。",
)


def build_comment(
    summary: WeatherSummary,
    scores: ScoreResult,
    sunset_cloud: SunsetCloud | None = None,
    *,
    prediction: bool = True,
    vision: VisionResult | None = None,
    formula_sunset_score: int | None = None,
    jma_precipitation: JmaPrecipitationForecast | None = None,
    prior_sunset_prediction: SunsetPredictionReference | None = None,
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
    if uncertainty is not None and vision is None:
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
    if vision is not None:
        if prediction:
            sunset_comment = _prediction_with_camera_comment(
                summary,
                sunset_cloud=cloud,
                displayed_score=scores.sunset_score,
                formula_score=(
                    formula_sunset_score
                    if formula_sunset_score is not None
                    else scores.sunset_score
                ),
                vision=vision,
            )
            if uncertainty is not None and uncertainty not in {
                "vision_more_optimistic",
                "vision_more_pessimistic",
            }:
                connector = "でも、" if sunset_band == "good" else "ただ、"
                sunset_comment = (
                    f"{sunset_comment} {connector}"
                    f"{_uncertain_prediction_comment(uncertainty, summary)}"
                )
        else:
            sunset_comment = _actual_with_camera_comment(
                summary,
                vision=vision,
                prior_sunset_prediction=prior_sunset_prediction,
            )
    sunset_comment = place_interjection_at_comment_start(sunset_comment)
    comment_lines = [
        sunset_comment,
        *([comfort_comment] if comfort_comment is not None else []),
    ]
    if (
        not prediction
        and vision is not None
        and vision.evaluation_phase in {"sunset", "afterglow"}
        and vision.sunset_score >= 70
    ):
        comment_lines.extend(
            [
                "",
                _after_sunset_encouragement_comment(
                    summary,
                    weather_eligible=comfort_comment is None,
                ),
            ]
        )
    return "\n".join(comment_lines)


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


def _after_sunset_encouragement_comment(
    summary: WeatherSummary,
    *,
    weather_eligible: bool,
) -> str:
    # 日没時刻の季節変動で同じ日付の選択がずれないよう、励まし文は固定時刻で選ぶ。
    selection_time = "19:00"
    weather_contexts = (
        _encouragement_weather_contexts(summary) if weather_eligible else ()
    )
    use_weather = (
        bool(weather_contexts)
        and select_comment_variant(
            summary.date,
            selection_time,
            "after-sunset-encouragement-kind",
            ("general", "general", "general", "weather"),
        )
        == "weather"
    )
    if use_weather:
        context = select_comment_variant(
            summary.date,
            selection_time,
            "after-sunset-encouragement-weather-context",
            weather_contexts,
        )
        return select_comment_variant(
            summary.date,
            selection_time,
            f"after-sunset-encouragement-{context}",
            _WEATHER_ENCOURAGEMENT_VARIANTS[context],
        )
    return select_comment_variant(
        summary.date,
        selection_time,
        "after-sunset-encouragement-general",
        _AFTER_SUNSET_ENCOURAGEMENT_VARIANTS,
    )


def _encouragement_weather_contexts(summary: WeatherSummary) -> tuple[str, ...]:
    conditions = summary.with_run_time_weather()
    temperature = _comfort_temperature(summary, prediction=False)
    daytime_max = summary.temperature_2m_daytime_max
    contexts: list[str] = []
    if daytime_max is not None and daytime_max >= 30:
        contexts.append("hot")
    if 3 <= conditions.wind_speed_10m < 8:
        contexts.append("breeze")
    if temperature < 27:
        contexts.append("cool")
    if daytime_max is not None and daytime_max - temperature >= 3:
        contexts.append("cooling")
    return tuple(contexts)


def _prediction_with_camera_comment(
    summary: WeatherSummary,
    *,
    sunset_cloud: SunsetCloud,
    displayed_score: int,
    formula_score: int,
    vision: VisionResult,
) -> str:
    normalized_vision_score = normalize_prediction_vision_score(
        summary,
        sunset_cloud,
        vision_sunset_score=vision.sunset_score,
        sky_condition=vision.sky_condition,
    )
    if normalized_vision_score > vision.sunset_score:
        return _comment_variant(
            summary,
            "camera-prediction-clear-sky-consistency",
            _CLEAR_SKY_PREDICTION_VARIANTS,
        )
    formula_band = _comment_band(formula_score)
    vision_band = _comment_band(vision.sunset_score)
    displayed_band = _comment_band(displayed_score)
    band_order = {"low": 0, "medium": 1, "good": 2}
    if formula_band == vision_band:
        relation = "aligned"
    elif band_order[vision_band] > band_order[formula_band]:
        relation = "camera-more-optimistic"
    else:
        relation = "camera-more-pessimistic"
    return _comment_variant(
        summary,
        f"camera-prediction-{relation}-{displayed_band}",
        _PREDICTION_CAMERA_COMMENT_VARIANTS[(relation, displayed_band)],
    )


def _actual_with_camera_comment(
    summary: WeatherSummary,
    *,
    vision: VisionResult,
    prior_sunset_prediction: SunsetPredictionReference | None,
) -> str:
    observation = _vision_observation_comment(vision)
    if not vision.comment.strip():
        return _actual_camera_summary(summary, vision.sunset_score)
    if prior_sunset_prediction is None:
        return observation

    outlook = _prior_outlook_band(prior_sunset_prediction.score)
    result = _actual_result_band(vision.sunset_score)
    expected_result = {
        "favorable": "vivid",
        "uncertain": "visible",
        "pessimistic": "absent",
    }[outlook]
    if result == expected_result:
        return observation

    comparison = _comment_variant(
        summary,
        f"actual-{outlook}-{result}",
        _ACTUAL_COMPARISON_VARIANTS[(outlook, result)],
    )
    return place_interjection_at_comment_start(f"{comparison} {observation}")


def _actual_camera_summary(summary: WeatherSummary, sunset_score: int) -> str:
    band = _actual_result_band(sunset_score)
    return _comment_variant(
        summary,
        f"camera-actual-summary-{band}",
        _ACTUAL_CAMERA_SUMMARY_VARIANTS[band],
    )


def _vision_observation_comment(vision: VisionResult) -> str:
    raw_comment = vision.comment.strip()
    raw_comment = re.sub(
        r"((?:橙|赤|紫|ピンク|オレンジ)(?:色)?(?:・(?:橙|赤|紫)(?:色)?)*)の残照",
        r"\1の光",
        raw_comment,
    )
    raw_comment = raw_comment.replace("残照", "夕焼け色")
    if vision.sunset_score >= 60:
        raw_comment = re.sub(r"^うーん(?:……[。.]?|[、,])?\s*", "", raw_comment)
    elif vision.sunset_score < 40:
        raw_comment = re.sub(r"^(?:わ[ぁあ]っ|やった)[！!]+\s*", "", raw_comment)
    voiced = apply_comment_voice(raw_comment)
    if voiced:
        return voiced
    return "ライブカメラで夕焼けを確認したっピ。"


def _prior_outlook_band(score: int) -> str:
    if score >= 70:
        return "favorable"
    if score >= 40:
        return "uncertain"
    return "pessimistic"


def _actual_result_band(score: int) -> str:
    if score >= 70:
        return "vivid"
    if score >= 40:
        return "visible"
    return "absent"


def _comfort_comment(summary: WeatherSummary, *, prediction: bool) -> str | None:
    conditions = summary if prediction else summary.with_run_time_weather()
    wind_speed = (
        max(
            summary.wind_speed_10m,
            _optional_or_fallback(
                summary.wind_speed_10m_at_sunset, summary.wind_speed_10m
            ),
        )
        if prediction
        else conditions.wind_speed_10m
    )
    wind_gusts = conditions.wind_gusts_10m
    humidity = (
        _optional_or_fallback(
            summary.relative_humidity_2m_at_sunset, summary.relative_humidity_2m
        )
        if prediction
        else conditions.relative_humidity_2m
    )
    temperature = _comfort_temperature(summary, prediction=prediction)
    if (
        not prediction
        and temperature < 27
        and (
            25 <= temperature < 26
            or conditions.apparent_temperature >= 28
        )
    ):
        return _cool_actual_comment(
            conditions,
            temperature=temperature,
            humid=humidity >= 75,
            wind_speed=wind_speed,
            wind_gusts=wind_gusts,
        )
    if conditions.apparent_temperature < 28:
        if not prediction and wind_gusts >= 12:
            return _gust_comment(conditions)
        return _strong_wind_comment(summary, prediction=prediction) if wind_speed >= 8 else None

    heat_level = "high" if conditions.apparent_temperature >= 32 else "moderate"
    humid = humidity >= 75
    modifier_kind = _comfort_modifier_kind(
        conditions,
        wind_speed=wind_speed,
        wind_gusts=wind_gusts,
        prediction=prediction,
    )
    if heat_level == "moderate" and humid and modifier_kind in {
        "breeze",
        "cooling",
        "cooling-breeze",
    }:
        return _moderate_humid_relief_comment(
            conditions,
            modifier=modifier_kind,
            prediction=prediction,
        )
    heat_comment = _heat_comment(
        conditions,
        heat_level=heat_level,
        humid=humid,
        prediction=prediction,
    )
    modifier = _comfort_modifier(
        conditions,
        modifier=modifier_kind,
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
    wind_gusts: float,
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
    elif wind_gusts >= 12:
        condition = "gust"
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
        "gust": (
            f"{temperature_description}、{coolness}っピ！でも、ときどき強い風が吹くっピ。",
            f"{temperature_description}、涼しいっピ。ただ、急な強い風には注意っピ。",
            f"海辺は{temperature_band}℃台でかなり涼しいっピ！でも、風が急に強まるっピ。",
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
            (
                f"湿度は高めだけど、{temperature_band}℃台と海風で"
                "かなり涼しいっピ！"
            ),
            (
                f"{temperature_band}℃台の海風が気持ちいいっピ！"
                "涼しいけど、少し湿気はあるっピ。"
            ),
            (
                f"海辺は{temperature_band}℃台まで下がって涼しいっピ！"
                "風もあるけど、湿度は高めっピ。"
            ),
            (
                f"湿気は残ってるけど、{temperature_band}℃台と風なら"
                "かなり涼しいっピ！"
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
            "ちょっぴり蒸し暑い夕方になりそうっピ。",
            "湿気が残って、少し暑く感じそうっピ。",
            "海辺も、ほんのりむし暑くなりそうっピ。",
            "夕方でも湿気のある暑さが残りそうっピ。",
        ),
        ("moderate", True, False): (
            "気温と湿度が高めで、少しむし暑い状態っピ。",
            "湿気と暑さが重なって、海辺は少しむわっとしてるっピ。",
            "気温は高めで湿気もあり、涼しさは控えめっピ。",
            "ちょっぴり蒸し暑い夕方っピ。",
            "湿気が残って、少し暑く感じるっピ。",
            "海辺も、ほんのりむし暑いっピ。",
            "まだ湿気のある暑さが残ってるっピ。",
        ),
        ("moderate", False, True): (
            "気温は少し高めで、海辺でも暑さが残りそうっピ。",
            "夕方も気温が高めで、涼しさは控えめになりそうっピ。",
            "海辺では少し暑く感じそうっピ。",
            "夕方も、ほんのり暑さが残りそうっピ。",
            "海辺でも少し暑い空気になりそうっピ。",
            "涼しくなるには、もうひと声ほしそうっピ。",
            "気温は高めで、まだ少し暑そうっピ。",
        ),
        ("moderate", False, False): (
            "気温は少し高めで、海辺にも暑さが残ってるっピ。",
            "夕方も気温が高めで、涼しさは控えめっピ。",
            "海辺では少し暑く感じる状態っピ。",
            "夕方も、ほんのり暑さが残ってるっピ。",
            "海辺でも少し暑い空気っピ。",
            "涼しくなるには、もうひと声っピ。",
            "気温は高めで、まだ少し暑いっピ。",
        ),
    }[(heat_level, humid, prediction)]
    return _comment_variant(
        summary,
        f"heat-{heat_level}-{'humid' if humid else 'dry'}-"
        f"{'prediction' if prediction else 'actual'}",
        variants,
    )


def _moderate_humid_relief_comment(
    summary: WeatherSummary,
    *,
    modifier: str,
    prediction: bool,
) -> str:
    variants = {
        ("breeze", True): (
            "少し蒸し暑そうだけど、海風が救いになりそうっピ。",
            "湿気はあるけど、風のおかげで少し楽そうっピ。",
            "海風があるから、むわっとした暑さはしのげそうっピ。",
            "湿度は高めでも、風が暑さをやわらげてくれそうっピ。",
            "ちょっぴり蒸し暑そうっピ。海風が救いっピ！",
            "風がありそうで、湿気のある暑さも少し軽くなりそうっピ。",
            "むし暑さは残りそうだけど、海辺の風は気持ちよさそうっピ。",
        ),
        ("breeze", False): (
            "少し蒸し暑いけど、海風が救いっピ。",
            "湿気はあるけど、風のおかげで少し楽っピ。",
            "海風が、むわっとした暑さをやわらげてるっピ。",
            "湿度は高めでも、風があるぶん過ごしやすいっピ。",
            "ちょっぴり蒸し暑いっピ。海風が救いっピ！",
            "風があるから、湿気のある暑さも少し軽いっピ。",
            "むし暑さは残ってるけど、海辺の風は気持ちいいっピ。",
        ),
        ("cooling", True): (
            "湿気はあるけど、日中より涼しくなりそうっピ。",
            "むし暑さは残りそうでも、昼間より気温は下がりそうっピ。",
            "夕方は気温が下がって、湿気のある暑さもやわらぎそうっピ。",
            "湿度は高めだけど、日中よりはほっとできそうっピ。",
            "昼間より涼しくなって、むわっと感も少し軽くなりそうっピ。",
            "湿気は残りそうだけど、夕方の気温低下が救いっピ。",
            "日中の暑さが引いて、少し蒸し暑いくらいになりそうっピ。",
        ),
        ("cooling", False): (
            "湿気はあるけど、日中より涼しくなってるっピ。",
            "むし暑さは残っていても、昼間より気温は低いっピ。",
            "夕方は気温が下がって、湿気のある暑さもやわらいでるっピ。",
            "湿度は高めだけど、日中よりはほっとできるっピ。",
            "昼間より涼しくなって、むわっと感も少し軽いっピ。",
            "湿気は残ってるけど、夕方の気温低下が救いっピ。",
            "日中の暑さが引いて、少し蒸し暑いくらいっピ。",
        ),
        ("cooling-breeze", True): (
            "湿気はあるけど、日中より低い気温と海風が救いになりそうっピ。",
            "むし暑さは残りそうでも、昼間との気温差と風で少し楽そうっピ。",
            "湿気はあるけど、夕方は気温が下がって海風も吹きそうっピ。",
            "湿度は高めだけど、日中より涼しく、風も心地よさそうっピ。",
            "昼間より気温が下がり、海風がむわっと感をやわらげそうっピ。",
            "湿気は残りそうだけど、夕方の気温低下と風が助けてくれそうっピ。",
            "日中の蒸し暑さが引いて、海辺の風も気持ちよくなりそうっピ。",
        ),
        ("cooling-breeze", False): (
            "湿気はあるけど、日中より低い気温と海風が救いっピ。",
            "むし暑さは残っていても、昼間との気温差と風で少し楽っピ。",
            "湿気はあるけど、夕方は気温が下がって海風も吹いてるっピ。",
            "湿度は高めだけど、日中より涼しく、風も心地いいっピ。",
            "昼間より気温が下がり、海風がむわっと感をやわらげてるっピ。",
            "湿気は残ってるけど、夕方の気温低下と風が助けてくれるっピ。",
            "日中の蒸し暑さが引いて、海辺の風も気持ちいいっピ。",
        ),
    }[(modifier, prediction)]
    return _comment_variant(
        summary,
        f"moderate-humid-{modifier}-{'prediction' if prediction else 'actual'}",
        variants,
    )


def _comfort_modifier_kind(
    summary: WeatherSummary,
    *,
    wind_speed: float,
    wind_gusts: float,
    prediction: bool,
) -> str | None:
    temperature = _comfort_temperature(summary, prediction=prediction)
    daytime_max = summary.temperature_2m_daytime_max
    cooling = daytime_max is not None and daytime_max - temperature >= 3
    breeze = 3 <= wind_speed < 8
    rain = (
        summary.weather_code in RAIN_WEATHER_CODES or summary.precipitation >= 1.0
    )

    if wind_speed >= 8:
        return "strong-wind"
    if not prediction and wind_gusts >= 12:
        return "gust"
    if rain:
        return "rain"
    if cooling and breeze:
        return "cooling-breeze"
    if cooling:
        return "cooling"
    if breeze:
        return "breeze"
    return None


def _comfort_modifier(
    summary: WeatherSummary,
    *,
    modifier: str | None,
    prediction: bool,
) -> str:
    if modifier is None:
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
        ("gust", False): (
            "それに、ときどき風が強く吹いて、のんびりはしにくい状態っピ。",
            "さらに急な強い風もあって、海辺では落ち着きにくい状態っピ。",
            "おまけに風が急に強まって、快適さは下がってるっピ。",
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


def _gust_comment(summary: WeatherSummary) -> str:
    return _comment_variant(
        summary,
        "gust-actual",
        (
            "ときどき風が強く吹いて、海辺では落ち着きにくい状態っピ。",
            "急に強い風が吹くから、のんびり度は控えめっピ。",
            "風が急に強まって、海辺の快適さが少し下がってるっピ。",
        ),
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
    prior_sunset_prediction: SunsetPredictionReference | None = None,
) -> str:
    cloud = sunset_cloud or SunsetCloud.from_summary(summary)
    comment_scores = scores
    if final_sunset_score is not None:
        comment_scores = ScoreResult(
            sunset_score=final_sunset_score,
            sunset_label=final_sunset_label or score_label(final_sunset_score),
            chill_score=scores.chill_score,
            chill_label=scores.chill_label,
            chill_weather_basis=scores.chill_weather_basis,
        )
    comment = scores.comment or build_comment(
        summary,
        comment_scores,
        sunset_cloud,
        prediction=vision_mode == "predict",
        vision=vision,
        formula_sunset_score=scores.sunset_score,
        jma_precipitation=jma_precipitation,
        prior_sunset_prediction=prior_sunset_prediction,
    )
    # 表示する Sunset期待度は Vision ブレンド後の値(未指定なら純式スコア)。
    display_sunset_score = (
        final_sunset_score if final_sunset_score is not None else scores.sunset_score
    )
    display_sunset_label = final_sunset_label or scores.sunset_label
    if vision_mode != "predict" and prior_sunset_prediction is not None:
        display_sunset_score = prior_sunset_prediction.score
        display_sunset_label = prior_sunset_prediction.label
    use_run_time_weather = vision_mode != "predict"
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
        display_vision_score = vision.sunset_score
        if vision_mode == "predict":
            vision_label = "ライブカメラAI予測"
            display_vision_score = normalize_prediction_vision_score(
                summary,
                cloud,
                vision_sunset_score=vision.sunset_score,
                sky_condition=vision.sky_condition,
            )
        elif vision.evaluation_phase == "sunset":
            vision_label = "ライブカメラ日没時評価"
        elif vision.evaluation_phase == "afterglow":
            vision_label = "ライブカメラ夕焼け評価"
        else:
            vision_label = "ライブカメラ実況評価"
        detail_lines = []
        if vision.sun_disk_visibility is not None:
            detail_lines.append(f"太陽ディスク：{vision.sun_disk_visibility} / 100")
        if vision.sunset_color_score is not None:
            detail_lines.append(f"日没時の発色：{vision.sunset_color_score} / 100")
        detail_section = "" if not detail_lines else "\n" + "\n".join(detail_lines)
        vision_section = (
            f"\n\n📷 {vision_label}\n"
            f"【 {score_label(display_vision_score)} 】{display_vision_score} / 100"
            f"（{vision.sky_condition}）{detail_section}"
        )
    precipitation_line = _precipitation_probability_line(
        summary,
        jma_precipitation,
        use_run_time_weather=use_run_time_weather,
    )
    gust_line = ""
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
    elif use_run_time_weather:
        current = summary.with_run_time_weather()
        display_temperature = current.temperature_2m
        display_humidity = current.relative_humidity_2m
        display_wind_speed = current.wind_speed_10m
        display_wind_direction = current.wind_direction_10m
        display_visibility = current.visibility
        if current.wind_gusts_10m >= 12:
            gust_line = f"\n突風：{current.wind_gusts_10m:.1f}m/s"
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
Chill指数【 {scores.chill_label} 】{scores.chill_score} / 100{vision_section}

コメント：
{comment}

--
{sunset_line}
気温：{display_temperature:.1f}℃
湿度：{display_humidity:.0f}%
風：{wind_direction_label(display_wind_direction)} {display_wind_speed:.1f}m/s{gust_line}
{precipitation_line}

夕焼け方向の雲
{cloud_line}
視程：{display_visibility / 1000:.1f}km"""


def _optional_or_fallback(value: float | None, fallback: float) -> float:
    return value if value is not None else fallback


def _precipitation_probability_line(
    summary: WeatherSummary,
    jma_precipitation: JmaPrecipitationForecast | None,
    *,
    use_run_time_weather: bool = False,
) -> str:
    if use_run_time_weather:
        current = summary.with_run_time_weather()
        return f"降水確率：{current.precipitation_probability:.0f}%"
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
