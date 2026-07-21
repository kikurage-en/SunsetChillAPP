from __future__ import annotations

from zushi_chill.constants import RAIN_WEATHER_CODES
from zushi_chill.models import ScoreResult, SunsetCloud, WeatherSummary


def score_label(score: int) -> str:
    if score >= 85:
        return "S"
    if score >= 70:
        return "A"
    if score >= 55:
        return "B"
    if score >= 40:
        return "C"
    return "D"


def calculate_scores(
    summary: WeatherSummary, sunset_cloud: SunsetCloud | None = None
) -> ScoreResult:
    sunset_score = calculate_sunset_score(summary, sunset_cloud)
    chill_score = calculate_chill_score(summary, sunset_score)
    return ScoreResult(
        sunset_score=sunset_score,
        sunset_label=score_label(sunset_score),
        chill_score=chill_score,
        chill_label=score_label(chill_score),
    )


def calculate_sunset_score(
    summary: WeatherSummary, sunset_cloud: SunsetCloud | None = None
) -> int:
    # Sunset期待度は陽が沈む方角(西の水平線)の雲量で算出する。sunset_cloud が
    # 無い場合(オフライン再現・西地点取得失敗のフォールバック)は逗子の雲量を使う。
    cloud = sunset_cloud or SunsetCloud.from_summary(summary)
    penalties = (
        _low_cloud_penalty(cloud.cloud_cover_low)
        + _sunset_precipitation_penalty(summary, cloud)
        + _visibility_penalty(summary.visibility)
        + _wind_penalty(summary.wind_speed_10m)
    )
    score = 100 + penalties
    score += 5 if 20 <= cloud.cloud_cover_mid <= 60 else 0
    score += 10 if 20 <= cloud.cloud_cover_high <= 70 else 0

    # 飽和是正: ボーナスがペナルティを相殺して満点帯へ戻ることを防ぐ
    if penalties < 0:
        score = min(score, 95)
    if summary.precipitation_probability >= 20:
        score = min(score, 90)

    if cloud.cloud_cover >= 85 or (
        cloud.cloud_cover_low >= 70 and cloud.cloud_cover_mid >= 70
    ):
        score = min(score, 30)
    elif cloud.cloud_cover >= 70:
        score = min(score, 65)
    # 厚い中層雲デッキは低い夕日を遮る。総雲量キャップが効かない帯(総雲量<70%でも
    # 中層雲が厚い日=7/07・7/12型)の過大評価を是正する。
    if cloud.cloud_cover_mid >= 70:
        score = min(score, 40)
    elif cloud.cloud_cover_mid >= 55:
        score = min(score, 60)
    if summary.visibility < 5000:
        score = min(score, 50)
    # 天井の再校正: 旧+20分Vision画像代理値で85点以上は35日中1日しかなく、
    # 式が85+を出した8日の画像代理値中央値は68だった。好条件でも通常の上限は80とし、
    # 90に届き得るのは色を最大限に通す超快晴(総雲量<15%かつ低層雲<5%)のみ。
    if cloud.cloud_cover < 15 and cloud.cloud_cover_low < 5:
        score = min(score, 90)
    else:
        score = min(score, 80)
    return _clamp_score(score)


# Vision による上方修正の上限幅。17:00 のカメラは「これから西から来る雲の壁」を
# 見られない(7/17: 式10=西40kmの低層雲97.7%を捕捉・旧画像代理値15に対し
# Visionは70)ため、
# 式からの持ち上げは +30 までに制限する。下方修正は制限しない(目の前の悪い空を
# 写しているカメラは信頼できる)。
VISION_UPLIFT_CAP = 30

# 2026-06-12 / 2026-07-21型: アンサンブルの降水確率だけが80%以上でも、
# 決定論的な雨量・天気コード・西空の雲が晴天側なら、一律-60は過小評価になった。
# 同型はN=2しかないため、強減点を解除せず暫定的に-25まで緩和する。
DRY_HIGH_PRECIPITATION_PENALTY = -25


def blend_sunset_score(sunset_score: int, vision_sunset_score: int, vision_weight: float) -> int:
    """式スコアと Vision カメラAI予測スコアを ``vision_weight`` でブレンドする。

    式は単一時刻の雲スカラー値しか使えず「雲が光を遮る/夕日を受ける」を分離できない
    ため、実際の空を見る Vision の方が精度が高い。表示用の Sunset期待度をこの合成値
    にする一方、純式 ``sunset_score`` は検証継続のためログにそのまま残す(呼び出し側)。
    Vision が式を上回る方向へは ``VISION_UPLIFT_CAP`` までしか持ち上げない。
    """
    blended = (1.0 - vision_weight) * sunset_score + vision_weight * vision_sunset_score
    blended = min(blended, sunset_score + VISION_UPLIFT_CAP)
    return _clamp_score(blended)


def calculate_chill_score(summary: WeatherSummary, sunset_score: int) -> int:
    score = (
        apparent_temperature_score(summary.apparent_temperature) * 0.30
        + humidity_score(summary.relative_humidity_2m) * 0.20
        + wind_score(summary.wind_speed_10m) * 0.20
        + precipitation_risk_score(summary.precipitation_probability) * 0.20
        + sunset_score * 0.10
    )

    caps: list[int] = []
    if summary.precipitation_probability >= 70:
        caps.append(40)
    if summary.precipitation >= 1.0:
        caps.append(45)
    if summary.wind_speed_10m >= 8:
        caps.append(55)
    if summary.wind_gusts_10m >= 12:
        caps.append(50)
    if summary.weather_code in RAIN_WEATHER_CODES:
        caps.append(45)
    if summary.cloud_cover >= 85 or (
        summary.cloud_cover_low >= 70 and summary.cloud_cover_mid >= 70
    ):
        caps.append(65)
    elif summary.cloud_cover >= 70:
        caps.append(69)
    if summary.apparent_temperature < 18:
        caps.append(55)
    elif summary.apparent_temperature < 20:
        caps.append(70)
    elif summary.apparent_temperature < 22:
        caps.append(80)
    if caps:
        score = min(score, min(caps))

    return _clamp_score(score)


def has_dry_high_precipitation_conflict(
    summary: WeatherSummary, sunset_cloud: SunsetCloud | None = None
) -> bool:
    """降水確率だけが高く、日没方向の決定論的な場が晴天側かを返す。

    この条件は「雨が降らない」と断定するものではなく、アンサンブル降水確率と
    雨量・天気コード・西空の雲が食い違うため、夕焼け予測の不確実性が高い印。
    """
    cloud = sunset_cloud or SunsetCloud.from_summary(summary)
    return (
        summary.precipitation_probability >= 80
        and summary.precipitation <= 0
        and summary.weather_code in {0, 1}
        and cloud.cloud_cover < 50
        and cloud.cloud_cover_low < 30
    )


def apparent_temperature_score(value: float) -> int:
    if 22 <= value <= 28:
        return 100
    if 28.1 <= value <= 30:
        return 80
    if 20 <= value <= 21.9:
        return 70
    if 30.1 <= value <= 32:
        return 60
    if 18 <= value <= 19.9:
        return 45
    if 32.1 <= value <= 34:
        return 40
    if 16 <= value <= 17.9:
        return 25
    return 20


def humidity_score(value: float) -> int:
    if 55 <= value <= 75:
        return 100
    if 45 <= value <= 54 or 76 <= value <= 82:
        return 80
    if 35 <= value <= 44 or 83 <= value <= 88:
        return 60
    if value >= 89:
        return 40
    return 50


def wind_score(value: float) -> int:
    if 2.0 <= value <= 5.0:
        return 100
    if 0.5 <= value <= 1.9 or 5.1 <= value <= 6.9:
        return 80
    if 7.0 <= value <= 8.9:
        return 50
    if value >= 9.0:
        return 25
    return 60


def precipitation_risk_score(value: float) -> int:
    if value <= 19:
        return 100
    if value <= 34:
        return 80
    if value <= 49:
        return 60
    if value <= 69:
        return 35
    return 10


def _low_cloud_penalty(value: float) -> int:
    if value <= 29:
        return 0
    if value <= 49:
        return -10
    if value <= 69:
        return -20
    if value <= 84:
        return -35
    return -50


def _precipitation_penalty(value: float) -> int:
    if value <= 19:
        return 0
    if value <= 39:
        return -10
    if value <= 59:
        return -25
    if value <= 79:
        return -40
    return -60


def _sunset_precipitation_penalty(
    summary: WeatherSummary, sunset_cloud: SunsetCloud
) -> int:
    penalty = _precipitation_penalty(summary.precipitation_probability)
    if has_dry_high_precipitation_conflict(summary, sunset_cloud):
        return max(penalty, DRY_HIGH_PRECIPITATION_PENALTY)
    return penalty


def _visibility_penalty(value: float) -> int:
    if value >= 15000:
        return 0
    if value >= 10000:
        return -5
    if value >= 5000:
        return -15
    return -30


def _wind_penalty(value: float) -> int:
    if value < 6.0:
        return 0
    if value < 8.0:
        return -5
    return -10


def _clamp_score(score: float) -> int:
    return max(0, min(100, int(round(score))))
