from __future__ import annotations

from dataclasses import replace

from zushi_chill.scoring import (
    apparent_temperature_score,
    calculate_chill_score,
    calculate_scores,
    calculate_sunset_score,
    humidity_score,
    precipitation_risk_score,
    score_label,
    wind_score,
)


def test_scores_are_clamped(sample_summary):
    scores = calculate_scores(sample_summary)

    assert 0 <= scores.sunset_score <= 100
    assert 0 <= scores.chill_score <= 100


def test_low_cloud_reduces_sunset_score(sample_summary):
    clear = replace(sample_summary, cloud_cover_low=20)
    cloudy = replace(sample_summary, cloud_cover_low=90)

    assert calculate_sunset_score(cloudy) < calculate_sunset_score(clear)


def test_high_cloud_bonus_increases_sunset_score(sample_summary):
    without_bonus = replace(sample_summary, cloud_cover_low=50, cloud_cover_high=5)
    with_bonus = replace(sample_summary, cloud_cover_low=50, cloud_cover_high=50)

    assert calculate_sunset_score(with_bonus) > calculate_sunset_score(without_bonus)


def test_sunset_score_low_cloud_penalty_table(sample_summary):
    baseline = replace(
        sample_summary,
        cloud_cover_mid=0,
        cloud_cover_high=0,
        precipitation_probability=0,
        visibility=20000,
        wind_speed_10m=3,
    )

    assert calculate_sunset_score(replace(baseline, cloud_cover_low=29)) == 100
    assert calculate_sunset_score(replace(baseline, cloud_cover_low=30)) == 90
    assert calculate_sunset_score(replace(baseline, cloud_cover_low=50)) == 80
    assert calculate_sunset_score(replace(baseline, cloud_cover_low=70)) == 65
    assert calculate_sunset_score(replace(baseline, cloud_cover_low=85)) == 50


def test_sunset_score_precipitation_penalty_table(sample_summary):
    baseline = replace(
        sample_summary,
        cloud_cover_low=0,
        cloud_cover_mid=0,
        cloud_cover_high=0,
        visibility=20000,
        wind_speed_10m=3,
    )

    assert calculate_sunset_score(replace(baseline, precipitation_probability=19)) == 100
    assert calculate_sunset_score(replace(baseline, precipitation_probability=20)) == 90
    assert calculate_sunset_score(replace(baseline, precipitation_probability=40)) == 75
    assert calculate_sunset_score(replace(baseline, precipitation_probability=60)) == 60
    assert calculate_sunset_score(replace(baseline, precipitation_probability=80)) == 40


def test_sunset_score_visibility_wind_and_cloud_bonus_tables(sample_summary):
    baseline = replace(
        sample_summary,
        cloud_cover_low=0,
        cloud_cover_mid=0,
        cloud_cover_high=0,
        precipitation_probability=0,
    )

    assert calculate_sunset_score(replace(baseline, visibility=15000, wind_speed_10m=3)) == 100
    assert calculate_sunset_score(replace(baseline, visibility=10000, wind_speed_10m=3)) == 95
    assert calculate_sunset_score(replace(baseline, visibility=5000, wind_speed_10m=3)) == 85
    assert calculate_sunset_score(replace(baseline, visibility=4999, wind_speed_10m=3)) == 50
    assert calculate_sunset_score(replace(baseline, visibility=20000, wind_speed_10m=6)) == 95
    assert calculate_sunset_score(replace(baseline, visibility=20000, wind_speed_10m=8)) == 90
    assert calculate_sunset_score(
        replace(baseline, visibility=20000, wind_speed_10m=3, cloud_cover_mid=20)
    ) == 100
    assert calculate_sunset_score(
        replace(
            baseline,
            visibility=20000,
            wind_speed_10m=3,
            cloud_cover_low=50,
            cloud_cover_mid=20,
        )
    ) == 85
    assert calculate_sunset_score(
        replace(
            baseline,
            visibility=20000,
            wind_speed_10m=3,
            cloud_cover_low=50,
            cloud_cover_high=20,
        )
    ) == 90


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
    assert calculate_sunset_score(overcast) == 45


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

    assert calculate_sunset_score(thick_cloud_deck) == 45


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

    # -10(低層雲) +5(中層雲) +10(高層雲) = 105 だが、ペナルティありの空は上限95
    assert calculate_sunset_score(penalized_with_bonuses) == 95


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
    # 旧実装では 100。降水確率20%以上の上限90が効く
    assert calculate_sunset_score(record_20260610_1700) == 90

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
    # ペナルティゼロの晴天は引き続き 100
    assert calculate_sunset_score(record_20260531_1700) == 100

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
    # 総雲量70%以上の既存上限65は不変
    assert calculate_sunset_score(record_20260609_1700) == 65


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

    assert scores.sunset_score == 45
    assert scores.sunset_label == "C"
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
