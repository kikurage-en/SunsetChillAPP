from __future__ import annotations

from dataclasses import replace

from zushi_chill.models import SunsetCloud
from zushi_chill.scoring import (
    apparent_temperature_score,
    blend_sunset_score,
    calculate_chill_score,
    calculate_scores,
    calculate_sunset_score,
    has_dry_high_precipitation_conflict,
    has_rain_signal,
    humidity_score,
    precipitation_risk_score,
    score_label,
    wind_score,
)


def test_blend_sunset_score_weights_vision_against_formula():
    """式スコアと Vision カメラAI予測を vision_weight で線形合成する(既定0.8=Vision8割)。"""
    # round(0.2*40 + 0.8*75) = round(68.0) = 68 (式+30=70 の上方キャップ内)
    assert blend_sunset_score(40, 75, 0.8) == 68
    # round(0.2*100 + 0.8*65) = round(72.0) = 72
    assert blend_sunset_score(100, 65, 0.8) == 72
    # 重み0 は純式
    assert blend_sunset_score(40, 75, 0.0) == 40
    # 重み1 でも上方修正は式+30 まで
    assert blend_sunset_score(40, 75, 1.0) == 70
    assert blend_sunset_score(0, 200, 1.0) == 30


def test_blend_uplift_is_capped_but_downgrade_is_not():
    """Vision上方キャップ: 17:00のカメラは「これから西から来る雲の壁」を見えない
    (2026-07-17: 式10=西40km低層雲97.7%を捕捉・旧画像代理値15に対しVision 70)ため、
    上方修正は式+30まで。下方修正(7/07型: 式80・Vision15が的中)は制限しない。
    """
    # 7/17 実例: 旧ブレンド58 → キャップで40
    assert blend_sunset_score(10, 70, 0.8) == 40
    # 下方修正は自由(0.2*80 + 0.8*15 = 28)
    assert blend_sunset_score(80, 15, 0.8) == 28


def test_display_snapshots_do_not_change_sunset_or_chill_scores(sample_summary):
    aggregate_cloud = SunsetCloud(
        cloud_cover=40,
        cloud_cover_low=25,
        cloud_cover_mid=40,
        cloud_cover_high=55,
    )
    snapshot_only_changes = replace(
        sample_summary,
        temperature_2m_at_sunset=40,
        relative_humidity_2m_at_sunset=100,
        visibility_at_sunset_snapshot=100,
        wind_speed_10m_at_sunset=20,
        wind_direction_10m_at_sunset=0,
        apparent_temperature_at_run_time=40,
        relative_humidity_2m_at_run_time=100,
        precipitation_probability_at_run_time=100,
        precipitation_at_run_time=5,
        weather_code_at_run_time=65,
        cloud_cover_at_run_time=100,
        cloud_cover_low_at_run_time=100,
        cloud_cover_mid_at_run_time=100,
        cloud_cover_high_at_run_time=100,
        visibility_at_run_time=100,
        wind_speed_10m_at_run_time=20,
        wind_gusts_10m_at_run_time=30,
    )
    cloud_with_snapshot = replace(
        aggregate_cloud,
        cloud_cover_low_at_sunset=100,
        cloud_cover_mid_at_sunset=100,
        cloud_cover_high_at_sunset=100,
    )

    assert calculate_scores(sample_summary, aggregate_cloud) == calculate_scores(
        snapshot_only_changes,
        cloud_with_snapshot,
    )


def test_actual_chill_uses_complete_run_time_weather_snapshot(sample_summary):
    summary = replace(
        sample_summary,
        apparent_temperature=25,
        relative_humidity_2m=65,
        precipitation_probability=0,
        precipitation=0,
        weather_code=1,
        cloud_cover=20,
        cloud_cover_low=10,
        cloud_cover_mid=10,
        wind_speed_10m=3,
        wind_gusts_10m=6,
        apparent_temperature_at_run_time=27.6,
        relative_humidity_2m_at_run_time=78,
        precipitation_probability_at_run_time=0,
        precipitation_at_run_time=0,
        weather_code_at_run_time=2,
        cloud_cover_at_run_time=54,
        cloud_cover_low_at_run_time=46,
        cloud_cover_mid_at_run_time=82,
        cloud_cover_high_at_run_time=0,
        visibility_at_run_time=26220,
        wind_speed_10m_at_run_time=4.2,
        wind_gusts_10m_at_run_time=13.1,
    )

    forecast = calculate_scores(summary, chill_precipitation_probability=100)
    actual = calculate_scores(
        summary,
        chill_precipitation_probability=100,
        chill_use_run_time_weather=True,
    )

    assert forecast.chill_score == 40
    # 8/3型: 気温・湿度・平均風は快適側でも、直近の突風13.1m/sで上限50。
    assert actual.chill_score == 50
    assert actual.chill_label == "C"
    assert actual.chill_weather_basis == "run_time"
    # 日没後は6時間予測のJMA値100%ではなく、同じhourly行の0%を使う。
    assert actual.chill_score > forecast.chill_score


def test_scores_are_clamped(sample_summary):
    scores = calculate_scores(sample_summary)

    assert 0 <= scores.sunset_score <= 100
    assert 0 <= scores.chill_score <= 100


def test_jma_probability_changes_chill_but_not_sunset(sample_summary):
    summary = replace(
        sample_summary,
        apparent_temperature=25,
        relative_humidity_2m=65,
        wind_speed_10m=3,
        wind_gusts_10m=6,
        precipitation_probability=87,
        precipitation=0,
        weather_code=1,
        cloud_cover=20,
        cloud_cover_low=10,
        cloud_cover_mid=10,
    )

    open_meteo_only = calculate_scores(summary)
    jma_for_chill = calculate_scores(
        summary,
        chill_precipitation_probability=20,
    )

    assert jma_for_chill.sunset_score == open_meteo_only.sunset_score
    assert jma_for_chill.chill_score > open_meteo_only.chill_score


def test_low_cloud_reduces_sunset_score(sample_summary):
    clear = replace(sample_summary, cloud_cover_low=20)
    cloudy = replace(sample_summary, cloud_cover_low=90)

    assert calculate_sunset_score(cloudy) < calculate_sunset_score(clear)


def test_high_cloud_bonus_increases_sunset_score(sample_summary):
    # 天井(80)で差が潰れないよう、降水ペナルティ(-25)で天井の下に下げて勾配を観測する
    without_bonus = replace(
        sample_summary, cloud_cover_low=50, cloud_cover_high=5, precipitation_probability=40
    )
    with_bonus = replace(
        sample_summary, cloud_cover_low=50, cloud_cover_high=50, precipitation_probability=40
    )

    assert calculate_sunset_score(with_bonus) > calculate_sunset_score(without_bonus)


def test_sunset_score_low_cloud_penalty_table(sample_summary):
    # 好条件の上限は天井80に潰れるため、降水ペナルティ(-25)を併用して
    # 低層雲ペナルティの全境界(0/-10/-20/-35/-50)を天井の下で観測する
    baseline = replace(
        sample_summary,
        cloud_cover_mid=0,
        cloud_cover_high=0,
        precipitation_probability=40,
        visibility=20000,
        wind_speed_10m=3,
    )

    assert calculate_sunset_score(replace(baseline, cloud_cover_low=29)) == 75
    assert calculate_sunset_score(replace(baseline, cloud_cover_low=30)) == 65
    assert calculate_sunset_score(replace(baseline, cloud_cover_low=50)) == 55
    assert calculate_sunset_score(replace(baseline, cloud_cover_low=70)) == 40
    assert calculate_sunset_score(replace(baseline, cloud_cover_low=85)) == 25

    # ペナルティなし側は天井80で頭打ち(総雲量40%の fixture は超快晴例外に該当しない)
    no_precip = replace(baseline, precipitation_probability=0)
    assert calculate_sunset_score(replace(no_precip, cloud_cover_low=29)) == 80


def test_sunset_score_precipitation_penalty_table(sample_summary):
    # 低層雲ペナルティ(-20)を併用し、降水確率ペナルティの境界を天井80の下で観測する
    baseline = replace(
        sample_summary,
        cloud_cover_low=50,
        cloud_cover_mid=0,
        cloud_cover_high=0,
        visibility=20000,
        wind_speed_10m=3,
    )

    assert calculate_sunset_score(replace(baseline, precipitation_probability=19)) == 80
    assert calculate_sunset_score(replace(baseline, precipitation_probability=20)) == 70
    assert calculate_sunset_score(replace(baseline, precipitation_probability=40)) == 55
    assert calculate_sunset_score(replace(baseline, precipitation_probability=60)) == 40
    assert calculate_sunset_score(replace(baseline, precipitation_probability=80)) == 20


def test_dry_high_precipitation_conflict_uses_provisional_penalty(sample_summary):
    """7/21型は降水確率87%でも、雨量0・晴天コード・西空の低層雲10%だった。

    一律-60では日没時発色80に対して式40まで落ちたため、同型N=2の暫定補正として
    -25へ緩和する。湿度はSunset期待度へ直接入れず、視程と画像で別評価する。
    """
    july_21 = replace(
        sample_summary,
        precipitation_probability=87,
        precipitation=0,
        weather_code=0,
        visibility=19600,
        wind_speed_10m=3.3,
    )
    west = SunsetCloud(
        cloud_cover=17,
        cloud_cover_low=10,
        cloud_cover_mid=13.3,
        cloud_cover_high=0,
    )

    assert has_dry_high_precipitation_conflict(july_21, west) is True
    assert calculate_sunset_score(july_21, west) == 75


def test_dry_high_precipitation_relief_is_not_applied_to_cloudier_case(sample_summary):
    """7/16型は雨量0でも天気コード2で、旧画像代理値25に対し式60と既に楽観的。

    高い降水確率を一律で緩和すると悪化するため、晴天コード0/1だけを暫定対象にする。
    """
    july_16 = replace(
        sample_summary,
        precipitation_probability=75,
        precipitation=0,
        weather_code=2,
        visibility=14360,
        wind_speed_10m=3.3,
    )
    west = SunsetCloud(
        cloud_cover=28.3,
        cloud_cover_low=26.7,
        cloud_cover_mid=23.3,
        cloud_cover_high=11,
    )

    assert has_dry_high_precipitation_conflict(july_16, west) is False
    assert calculate_sunset_score(july_16, west) == 60


def test_sunset_score_visibility_wind_and_cloud_bonus_tables(sample_summary):
    # 降水ペナルティ(-25)を併用し、視程・風・雲ボーナスの各境界を天井80の下で観測する
    baseline = replace(
        sample_summary,
        cloud_cover_low=0,
        cloud_cover_mid=0,
        cloud_cover_high=0,
        precipitation_probability=40,
    )

    assert calculate_sunset_score(replace(baseline, visibility=15000, wind_speed_10m=3)) == 75
    assert calculate_sunset_score(replace(baseline, visibility=10000, wind_speed_10m=3)) == 70
    assert calculate_sunset_score(replace(baseline, visibility=5000, wind_speed_10m=3)) == 60
    assert calculate_sunset_score(replace(baseline, visibility=4999, wind_speed_10m=3)) == 45
    assert calculate_sunset_score(replace(baseline, visibility=20000, wind_speed_10m=6)) == 70
    assert calculate_sunset_score(replace(baseline, visibility=20000, wind_speed_10m=8)) == 65
    assert calculate_sunset_score(
        replace(baseline, visibility=20000, wind_speed_10m=3, cloud_cover_mid=20)
    ) == 80
    assert calculate_sunset_score(
        replace(
            baseline,
            visibility=20000,
            wind_speed_10m=3,
            cloud_cover_low=50,
            cloud_cover_mid=20,
        )
    ) == 60
    assert calculate_sunset_score(
        replace(
            baseline,
            visibility=20000,
            wind_speed_10m=3,
            cloud_cover_low=50,
            cloud_cover_high=20,
        )
    ) == 65


def test_sunset_score_ceiling_recalibration(sample_summary):
    """天井の再校正: 旧+20分Vision画像代理値がS帯(85+)に達したのは35日中1日のみで、
    式が85+を出した8日の代理値中央値は68だった(2026-07-17分析)。好条件でも上限80、
    色を最大限に通す超快晴(総雲量<15%かつ低層雲<5%)のみ90まで許す。
    """
    perfect = replace(
        sample_summary,
        cloud_cover=40,
        cloud_cover_low=0,
        cloud_cover_mid=0,
        cloud_cover_high=0,
        precipitation_probability=0,
        visibility=20000,
        wind_speed_10m=3,
    )
    # 好条件でも通常の上限は80(旧実装では100)
    assert calculate_sunset_score(perfect) == 80
    # 超快晴(総雲量<15%かつ低層雲<5%)のみ90
    ultra_clear = replace(perfect, cloud_cover=10, cloud_cover_low=0)
    assert calculate_sunset_score(ultra_clear) == 90
    # 境界: 総雲量15%または低層雲5%は例外に入らない
    assert calculate_sunset_score(replace(perfect, cloud_cover=15, cloud_cover_low=0)) == 80
    assert calculate_sunset_score(replace(perfect, cloud_cover=10, cloud_cover_low=5)) == 80
    # 中位帯(80未満)のスコアは影響を受けない
    mid_range = replace(perfect, cloud_cover_low=50, precipitation_probability=40)
    assert calculate_sunset_score(mid_range) == 55


def test_total_cloud_cover_caps_sunset_score(sample_summary):
    otherwise_good_cloudy = replace(
        sample_summary,
        cloud_cover=82,
        cloud_cover_low=20,
        cloud_cover_mid=50,
        cloud_cover_high=60,
        precipitation_probability=0,
        visibility=20000,
        wind_speed_10m=3,
    )
    overcast = replace(otherwise_good_cloudy, cloud_cover=90)

    assert calculate_sunset_score(otherwise_good_cloudy) == 65
    assert calculate_sunset_score(overcast) == 30


def test_thick_low_and_mid_clouds_cap_sunset_score(sample_summary):
    thick_cloud_deck = replace(
        sample_summary,
        cloud_cover=82,
        cloud_cover_low=75,
        cloud_cover_mid=80,
        cloud_cover_high=60,
        precipitation_probability=0,
        visibility=20000,
        wind_speed_10m=3,
    )

    assert calculate_sunset_score(thick_cloud_deck) == 30


def test_penalized_sky_cannot_return_to_full_score_via_bonuses(sample_summary):
    penalized_with_bonuses = replace(
        sample_summary,
        cloud_cover=40,
        cloud_cover_low=30,
        cloud_cover_mid=20,
        cloud_cover_high=20,
        precipitation_probability=0,
        visibility=20000,
        wind_speed_10m=3,
    )

    # -10(低層雲) +5(中層雲) +10(高層雲) = 105 だが、ペナルティありの空は上限95、
    # さらに天井80(総雲量40%は超快晴例外に該当しない)で 80 に制限される
    assert calculate_sunset_score(penalized_with_bonuses) == 80


def test_sunset_saturation_fix_against_recorded_sheet_inputs(sample_summary):
    """SunsetChillログ(Google Sheets)の実レコードによる回帰ケース。

    6/10 17:00 はボーナス(+15)が降水確率ペナルティ(-10)を相殺して
    Sunset=100 に飽和し、実際の空(雲多め・部分的な色)と乖離した。
    飽和是正後も、ペナルティゼロの晴天 100 と既存キャップ適用日は変えない。
    """
    record_20260610_1700 = replace(
        sample_summary,
        cloud_cover=36.7,
        cloud_cover_low=22,
        cloud_cover_mid=28,
        cloud_cover_high=21.3,
        precipitation_probability=21,
        visibility=26120,
        wind_speed_10m=2.7,
    )
    # 旧実装では 100。降水確率20%以上の上限90に加え、天井80が効く
    assert calculate_sunset_score(record_20260610_1700) == 80

    record_20260531_1700 = replace(
        sample_summary,
        cloud_cover=20.3,
        cloud_cover_low=2.7,
        cloud_cover_mid=0.7,
        cloud_cover_high=18.7,
        precipitation_probability=11,
        visibility=21820,
        wind_speed_10m=2,
    )
    # ペナルティゼロの晴天も天井80(総雲量20.3%は超快晴例外<15%に該当しない)
    assert calculate_sunset_score(record_20260531_1700) == 80

    record_20260609_1700 = replace(
        sample_summary,
        cloud_cover=72.7,
        cloud_cover_low=35,
        cloud_cover_mid=58.7,
        cloud_cover_high=72.7,
        precipitation_probability=18,
        visibility=10360,
        wind_speed_10m=2.2,
    )
    # 総雲量70%以上の上限65に加え、厚い中層雲(58.7%≥55)の上限60が効いて 60。
    assert calculate_sunset_score(record_20260609_1700) == 60


def test_rain_signal_caps_sunset_score(sample_summary):
    """雨シグナル(代表天気コードが雨系 or 窓内雨量≥1.0mm)はSunsetを上限40で頭打ち。

    雨量・雨コードはChill式だけが減点しSunset式は素通りだった非対称の是正
    (2026-07-25 17:00: 窓内4.7mm・コード61の予報下で式45・表示61(B)を配信し、
    日没時発色は0)。深さを雨量に比例させないのは、予想雨量と画像代理値の順位相関が
    +0.072(N=17)で、最多雨量日(6/27窓24mm予報・日没前に雨が抜け発色65)が最良だった
    ため。バックテスト(発動21行)で上限40は悪化ゼロ、30は7/13(霧雨・発色75)を悪化させる。
    """
    good_sky = replace(
        sample_summary,
        precipitation_probability=10,
        precipitation=0,
        weather_code=1,
        cloud_cover=20,
        cloud_cover_low=5,
        cloud_cover_mid=30,
        cloud_cover_high=40,
        visibility=25000,
        wind_speed_10m=3,
    )
    assert calculate_sunset_score(good_sky) == 80

    # 好条件でも雨コードなら上限40
    assert calculate_sunset_score(replace(good_sky, weather_code=61, precipitation=0.2)) == 40
    # 雨コードなしでも窓内雨量1.0mm以上なら上限40
    assert calculate_sunset_score(replace(good_sky, weather_code=3, precipitation=1.0)) == 40
    # 雨コードなし・1.0mm未満は発動しない
    assert calculate_sunset_score(replace(good_sky, weather_code=3, precipitation=0.9)) == 80


def test_rain_signal_regression_20260725_1700(sample_summary):
    """2026-07-25 17:00 の実レコード回帰(SunsetChillログ)。

    取得済みOpen-Meteoは窓内4.7mm・18時コード53/19時コード61と雨を明示していたのに
    旧式は45を出した(降水減点はPoPのみのため)。雨キャップ後は40。
    """
    record_20260725_1700 = replace(
        sample_summary,
        precipitation_probability=76,
        precipitation=4.7,
        weather_code=61,
        visibility=3880,
        wind_speed_10m=1.8,
    )
    west = SunsetCloud(
        cloud_cover=72,
        cloud_cover_low=28.7,
        cloud_cover_mid=40,
        cloud_cover_high=54.7,
    )
    assert calculate_sunset_score(record_20260725_1700, west) == 40


def test_rain_signal_is_exclusive_with_dry_conflict_relief(sample_summary):
    """雨シグナルと7/21型緩和(雨量0・晴天コードが条件)は定義上同時に成立しない。"""
    rainy = replace(sample_summary, weather_code=61, precipitation=2.0)
    dry_conflict = replace(
        sample_summary,
        precipitation_probability=87,
        precipitation=0,
        weather_code=0,
    )
    west_clear = SunsetCloud(
        cloud_cover=17, cloud_cover_low=10, cloud_cover_mid=13.3, cloud_cover_high=0
    )

    assert has_rain_signal(rainy) is True
    assert has_dry_high_precipitation_conflict(rainy, west_clear) is False
    assert has_rain_signal(dry_conflict) is False
    assert has_dry_high_precipitation_conflict(dry_conflict, west_clear) is True


def test_high_precipitation_reduces_both_scores(sample_summary):
    dry = replace(sample_summary, precipitation_probability=10, precipitation=0)
    wet = replace(sample_summary, precipitation_probability=80, precipitation=2)

    assert calculate_sunset_score(wet) < calculate_sunset_score(dry)
    assert calculate_chill_score(wet, calculate_sunset_score(wet)) < calculate_chill_score(
        dry, calculate_sunset_score(dry)
    )


def test_strong_wind_reduces_chill_score(sample_summary):
    calm = replace(sample_summary, wind_speed_10m=3, wind_gusts_10m=6)
    windy = replace(sample_summary, wind_speed_10m=9, wind_gusts_10m=13)

    assert calculate_chill_score(windy, 80) < calculate_chill_score(calm, 80)


def test_chill_score_weighted_formula_without_force_caps(sample_summary):
    summary = replace(
        sample_summary,
        apparent_temperature=31,
        relative_humidity_2m=85,
        wind_speed_10m=7,
        precipitation_probability=50,
        precipitation=0,
        wind_gusts_10m=8,
        weather_code=1,
    )

    assert apparent_temperature_score(summary.apparent_temperature) == 60
    assert humidity_score(summary.relative_humidity_2m) == 60
    assert wind_score(summary.wind_speed_10m) == 50
    assert precipitation_risk_score(summary.precipitation_probability) == 35
    assert calculate_chill_score(summary, sunset_score=70) == 54


def test_chilly_apparent_temperature_caps_chill_score(sample_summary):
    comfortable_otherwise = replace(
        sample_summary,
        apparent_temperature=21,
        relative_humidity_2m=65,
        wind_speed_10m=3,
        wind_gusts_10m=6,
        precipitation_probability=0,
        precipitation=0,
        weather_code=1,
    )

    assert calculate_chill_score(comfortable_otherwise, sunset_score=100) == 80
    assert calculate_chill_score(replace(comfortable_otherwise, apparent_temperature=19), 100) == 70
    assert calculate_chill_score(replace(comfortable_otherwise, apparent_temperature=17), 100) == 55


def test_cloudy_and_slightly_chilly_conditions_do_not_get_s_labels(sample_summary):
    cloudy_and_chilly = replace(
        sample_summary,
        apparent_temperature=21,
        relative_humidity_2m=65,
        wind_speed_10m=3,
        wind_gusts_10m=6,
        precipitation_probability=0,
        precipitation=0,
        weather_code=1,
        cloud_cover=82,
        cloud_cover_low=20,
        cloud_cover_mid=50,
        cloud_cover_high=60,
        visibility=20000,
    )

    scores = calculate_scores(cloudy_and_chilly)

    assert scores.sunset_score == 65
    assert scores.sunset_label == "B"
    assert scores.chill_score == 69
    assert scores.chill_label == "B"


def test_overcast_sunset_with_no_afterglow_scores_low(sample_summary):
    overcast_sunset = replace(
        sample_summary,
        apparent_temperature=21,
        relative_humidity_2m=65,
        wind_speed_10m=3,
        wind_gusts_10m=6,
        precipitation_probability=0,
        precipitation=0,
        weather_code=3,
        cloud_cover=90,
        cloud_cover_low=75,
        cloud_cover_mid=80,
        cloud_cover_high=80,
        visibility=20000,
    )

    scores = calculate_scores(overcast_sunset)

    assert scores.sunset_score == 30
    assert scores.sunset_label == "D"
    assert scores.chill_score == 65
    assert scores.chill_label == "B"


def test_apparent_temperature_comfort_band_scores_high():
    assert apparent_temperature_score(25) == 100
    assert apparent_temperature_score(34.1) == 20


def test_score_label_boundaries():
    assert score_label(100) == "S"
    assert score_label(85) == "S"
    assert score_label(84) == "A"
    assert score_label(70) == "A"
    assert score_label(69) == "B"
    assert score_label(55) == "B"
    assert score_label(54) == "C"
    assert score_label(40) == "C"
    assert score_label(39) == "D"
    assert score_label(0) == "D"


def test_component_score_boundaries():
    assert apparent_temperature_score(22) == 100
    assert apparent_temperature_score(28) == 100
    assert apparent_temperature_score(20) == 70
    assert apparent_temperature_score(30.1) == 60
    assert apparent_temperature_score(18) == 45
    assert apparent_temperature_score(16) == 25
    assert humidity_score(55) == 100
    assert humidity_score(82) == 80
    assert humidity_score(88) == 60
    assert humidity_score(89) == 40
    assert humidity_score(34) == 50
    assert wind_score(2.0) == 100
    assert wind_score(6.9) == 80
    assert wind_score(8.9) == 50
    assert wind_score(9.0) == 25
    assert wind_score(0.4) == 60
    assert precipitation_risk_score(19) == 100
    assert precipitation_risk_score(34) == 80
    assert precipitation_risk_score(49) == 60
    assert precipitation_risk_score(69) == 35
    assert precipitation_risk_score(70) == 10


def test_visibility_below_5000_caps_sunset_score(sample_summary):
    low_visibility = replace(
        sample_summary,
        cloud_cover_low=0,
        cloud_cover_mid=40,
        cloud_cover_high=50,
        precipitation_probability=0,
        visibility=4999,
        wind_speed_10m=3,
    )

    assert calculate_sunset_score(low_visibility) <= 50


def test_chill_force_caps(sample_summary):
    comfortable = replace(
        sample_summary,
        apparent_temperature=25,
        relative_humidity_2m=65,
        wind_speed_10m=3,
        wind_gusts_10m=6,
        precipitation_probability=0,
        precipitation=0,
        weather_code=1,
    )

    assert calculate_chill_score(replace(comfortable, precipitation_probability=70), 100) <= 40
    assert calculate_chill_score(replace(comfortable, precipitation=1.0), 100) <= 45
    assert calculate_chill_score(replace(comfortable, wind_speed_10m=8), 100) <= 55
    assert calculate_chill_score(replace(comfortable, wind_gusts_10m=12), 100) <= 50
    assert calculate_chill_score(replace(comfortable, weather_code=61), 100) <= 45


def test_sunset_score_matches_legacy_vision_image_proxy(sample_summary):
    """17:00天気ベース予測 vs 旧19:20 Vision画像代理値の乖離検証。

    SunsetChillログ(Google Sheets predictions)の2026-06-12〜06-24における
    「17:00行のsunset_score」と「同日19:20行のvision_sunset_score(旧代理値)」の
    13ペア。総雲量85%以上の上限を45→30へ下げた補正後、全ペアの集計誤差が
    縮小すること(MAE 20.3→15.7、bias +9.7→+5.1)を全データで証明する。
    部分的な出力assertでは集計悪化を見逃すため、13ペア全てと集計境界を検証する。

    各行: (日付, low, mid, high, cloud_cover, precip_prob, visibility, wind, 画像代理値)
    06-21(総雲量65%・代理値45)はペナルティゼロ+ボーナスで100に飽和する既知の
    外れ値(N=1のため今回は補正対象外、将来サンプル蓄積後に再評価)。
    """
    pairs = [
        ("06-12", 26.7, 36.0, 9.0, 39.0, 94, 6900, 2.3, 65),
        ("06-13", 5.3, 9.0, 6.3, 13.7, 27, 20800, 4.9, 92),
        ("06-14", 15.3, 60.3, 91.0, 91.0, 5, 16640, 2.9, 25),
        ("06-15", 33.7, 31.3, 3.0, 34.0, 50, 16760, 4.4, 55),
        ("06-16", 0.0, 0.0, 76.7, 76.7, 0, 29760, 3.4, 65),
        ("06-17", 24.7, 42.7, 97.0, 97.0, 0, 19480, 3.0, 10),
        ("06-18", 10.7, 13.7, 84.0, 84.0, 7, 19940, 1.6, 72),
        ("06-19", 19.7, 16.7, 67.0, 74.0, 15, 14720, 1.4, 55),
        ("06-20", 44.3, 82.3, 95.7, 95.7, 100, 2360, 2.9, 10),
        ("06-21", 27.0, 23.3, 65.0, 65.0, 14, 20260, 1.5, 45),
        ("06-22", 56.3, 54.3, 72.0, 85.0, 85, 4700, 2.1, 15),
        ("06-23", 39.7, 43.7, 87.3, 87.3, 8, 22960, 2.5, 15),
        ("06-24", 20.0, 33.7, 85.0, 85.0, 14, 13760, 2.4, 15),
    ]

    scores: dict[str, int] = {}
    errors: list[int] = []
    for label, low, mid, high, cloud, precip_prob, vis, wind, gt in pairs:
        summary = replace(
            sample_summary,
            cloud_cover=cloud,
            cloud_cover_low=low,
            cloud_cover_mid=mid,
            cloud_cover_high=high,
            precipitation_probability=precip_prob,
            visibility=vis,
            wind_speed_10m=wind,
        )
        score = calculate_sunset_score(summary)
        scores[label] = score
        errors.append(score - gt)

    mae = sum(abs(error) for error in errors) / len(errors)
    bias = sum(errors) / len(errors)

    # 全データの集計誤差が補正前(MAE 20.3 / bias +9.7)から縮小していること。
    # 7/21型の暫定補正後は MAE 12.2 / bias +5.5。MAEは改善する一方で楽観biasが
    # 2.8→5.5へ増えるため、N=2の条件を広げず前向きサンプルで再校正する。
    assert mae <= 12.3
    assert abs(bias) <= 5.5

    # 補正の核心: 総雲量85%以上の厚い曇天(旧画像代理値10〜25帯)は上限30
    assert scores["06-14"] == 30
    assert scores["06-17"] == 30
    assert scores["06-23"] == 30
    assert scores["06-24"] == 30

    # 高降水確率94%でも雨量0・晴天コード・薄い雲だった06-12は、旧30→65で代理値65。
    assert scores["06-12"] == 65

    # 回帰防止: 快晴・高層雲主体の薄曇り(旧画像代理値が高い日)は悪化させない。
    # 06-13(旧画像代理値92)は天井80になる(この行の逗子雲は low=5.3 で
    # 超快晴例外<5%に
    # 僅かに届かない)。本番の Sunset用雲は西40km地点(この日 low=1)で例外が効く。
    assert scores["06-13"] == 80
    assert scores["06-16"] == 65
    assert scores["06-18"] == 65


def test_thick_mid_cloud_caps_sunset_score(sample_summary):
    """厚い中層雲デッキは低い夕日を遮る。総雲量キャップが効かない帯(総雲量<70%)でも
    中層雲が厚い日の過大評価を是正する。

    2026-07-07 17:00(総雲量57%・中層57%・高層0%)は式が 100 に張り付いたが、
    旧+20分Vision画像代理値は15(overcast)だった。中層雲キャップで過大評価を抑える。
    """
    record_20260707_1700 = replace(
        sample_summary,
        cloud_cover=57,
        cloud_cover_low=7.7,
        cloud_cover_mid=57,
        cloud_cover_high=0,
        precipitation_probability=14,
        visibility=25420,
        wind_speed_10m=1.9,
    )
    # 中層雲 57%(≥55)の上限60。旧実装ではどのキャップも効かず 100
    assert calculate_sunset_score(record_20260707_1700) == 60
    # さらに厚い中層雲(≥70%)は上限40
    assert calculate_sunset_score(replace(record_20260707_1700, cloud_cover_mid=75)) == 40
    # 中層雲が薄ければ(<55%)mid キャップは効かず、天井80 まで戻る
    assert calculate_sunset_score(replace(record_20260707_1700, cloud_cover_mid=54)) == 80


def test_sunset_score_uses_western_cloud_when_provided(sample_summary):
    """Sunset期待度は西の日没方位地点の雲で算出する。逗子が快晴でも、陽の沈む先が
    厚い雲なら夕焼けは出ない
    (2026-07-04型: 逗子 total60% だが西 total100%・旧画像代理値15)。

    一方 Chill指数の雲キャップは逗子の雲を使うため、西の雲では抑制されない。
    """
    comfortable_clear_zushi = replace(
        sample_summary,
        cloud_cover=10,
        cloud_cover_low=0,
        cloud_cover_mid=5,
        cloud_cover_high=5,
        apparent_temperature=25,
        relative_humidity_2m=65,
        precipitation_probability=0,
        precipitation=0,
        weather_code=1,
        visibility=20000,
        wind_speed_10m=3,
        wind_gusts_10m=6,
    )
    cloudy_west = SunsetCloud(
        cloud_cover=90,
        cloud_cover_low=80,
        cloud_cover_mid=60,
        cloud_cover_high=90,
    )

    # sunset_cloud 無し = 逗子基準で超快晴(総雲量10%・低層0%) → 例外天井の90
    assert calculate_sunset_score(comfortable_clear_zushi) == 90
    # 西が厚い雲 → 低層雲ペナルティ+総雲量85%以上キャップで 30 以下
    assert calculate_sunset_score(comfortable_clear_zushi, cloudy_west) <= 30

    split_scores = calculate_scores(comfortable_clear_zushi, cloudy_west)
    # Sunset は西の雲で低下する
    assert split_scores.sunset_score <= 30
    # Chill の雲キャップは逗子(快晴)基準なので、西が厚くても 65 上限は掛からない
    assert split_scores.chill_score > 65
