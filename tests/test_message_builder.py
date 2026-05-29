from __future__ import annotations

from dataclasses import replace

from zushi_chill.message_builder import build_comment, build_line_message, wind_direction_label
from zushi_chill.models import ScoreResult


def test_line_message_contains_required_fields(sample_summary):
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    message = build_line_message(
        sample_summary,
        replace(scores, comment=build_comment(sample_summary, scores)),
        google_form_url="https://forms.example/test",
    )

    assert "【逗子サンセットチル指数｜2026-06-01 13:00発表】" in message
    assert "Chill指数：88 / 100（S）" in message
    assert "Sunset期待度：90 / 100（S）" in message
    assert "日没：18:51" in message
    assert "対象時間帯：17:21〜19:21" in message
    assert "体感温度（平均）：" in message
    assert "湿度（平均）：" in message
    assert "風（平均）：" in message
    assert "突風（最大）：" in message
    assert "降水確率（最大）：" in message
    assert "低層雲（平均）：" in message
    assert "中層雲（平均）：" in message
    assert "高層雲（平均）：" in message
    assert "視程（最小）：" in message
    assert "コメント：" in message
    assert "検証メモ：" in message
    assert "Googleフォーム：" in message
    assert "https://forms.example/test" in message


def test_line_message_uses_internal_validation_wording(sample_summary):
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    message = build_line_message(
        sample_summary,
        replace(scores, comment=build_comment(sample_summary, scores)),
        google_form_url="https://forms.example/test",
    )

    assert "予報" not in message
    assert "確実" not in message
    assert "時点" not in message
    assert "発表" in message
    assert "対象時間帯" in message
    assert "検証メモ" in message
    assert "実際の空模様" in message


def test_comment_changes_by_scores_and_weather(sample_summary):
    good = ScoreResult(sunset_score=75, sunset_label="A", chill_score=82, chill_label="A")
    comfortable_but_low_sunset = ScoreResult(
        sunset_score=45,
        sunset_label="C",
        chill_score=72,
        chill_label="A",
    )
    bad = ScoreResult(sunset_score=40, sunset_label="C", chill_score=45, chill_label="C")
    low_cloud = replace(sample_summary, cloud_cover_low=80)
    high_cloud = replace(sample_summary, cloud_cover_low=20, cloud_cover_high=50)
    windy = replace(sample_summary, wind_speed_10m=8)

    assert "夕方の滞在環境" in build_comment(sample_summary, good)
    assert "体感は良さそう" in build_comment(sample_summary, comfortable_but_low_sunset)
    assert "ネック" in build_comment(sample_summary, bad)
    assert "低層雲が多く" in build_comment(low_cloud, good)
    assert "高層雲がほどよく" in build_comment(high_cloud, good)
    assert "風が強め" in build_comment(windy, good)


def test_wind_direction_label_boundaries():
    assert wind_direction_label(0) == "北"
    assert wind_direction_label(360) == "北"
    assert wind_direction_label(348.75) == "北"
    assert wind_direction_label(11.24) == "北"
    assert wind_direction_label(11.25) == "北北東"
    assert wind_direction_label(90) == "東"
    assert wind_direction_label(180) == "南"
    assert wind_direction_label(270) == "西"
