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
    assert apparent_temperature_score(20) == 80
    assert apparent_temperature_score(30.1) == 60
    assert apparent_temperature_score(16) == 40
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
