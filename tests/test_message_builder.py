from __future__ import annotations

from dataclasses import replace

from zushi_chill.message_builder import build_comment, build_line_message, wind_direction_label
from zushi_chill.models import ScoreResult, SunsetCloud, VisionResult


def test_headline_shows_blended_final_sunset_score(sample_summary):
    """本文の Sunset期待度 見出しは、渡されたブレンド値(final_*)を表示する。
    純式スコア(scores.sunset_score)ではなく、Vision反映後の値を staff に見せる。
    """
    scores = ScoreResult(sunset_score=40, sunset_label="C", chill_score=70, chill_label="A")

    blended = build_line_message(
        sample_summary, scores, final_sunset_score=68, final_sunset_label="B"
    )
    assert "Sunset期待度【 B 】68 / 100" in blended
    assert "Sunset期待度【 C 】40 / 100" not in blended

    # final 未指定なら純式スコアをそのまま表示(後方互換)
    plain = build_line_message(sample_summary, scores)
    assert "Sunset期待度【 C 】40 / 100" in plain


def test_message_and_comment_use_western_sunset_cloud(sample_summary):
    """本文の雲量とコメントの雲判定は、Sunset期待度を駆動する西の日没方向の雲を使う。

    逗子の真上が晴れていても、陽の沈む先(西の水平線)が厚い雲なら、表示雲量・
    コメントともにその西空の雲を反映しないと、Sunset期待度と本文が食い違う。
    """
    scores = ScoreResult(sunset_score=30, sunset_label="D", chill_score=72, chill_label="A")
    zushi_clear = replace(
        sample_summary,
        cloud_cover=10,
        cloud_cover_low=5,
        cloud_cover_mid=10,
        cloud_cover_high=15,
    )
    west_cloudy = SunsetCloud(
        cloud_cover=90,
        cloud_cover_low=80,
        cloud_cover_mid=60,
        cloud_cover_high=90,
    )

    message = build_line_message(zushi_clear, scores, sunset_cloud=west_cloudy)
    # 雲量ブロックは西空の値で、見出しで方角を明示する
    assert "夕焼け方向の雲" in message
    assert "低層 80% / 中層 60% / 高層 90%" in message
    assert "低層 5%" not in message
    # コメントの雲判定も西空の低層雲(80%)で行う
    comment = build_comment(zushi_clear, scores, west_cloudy)
    assert "低層雲が多く" in comment


def test_line_message_contains_required_fields(sample_summary):
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    message = build_line_message(
        sample_summary,
        replace(scores, comment=build_comment(sample_summary, scores)),
    )

    assert "【逗子サンセットチル指数｜2026-06-01 13:00】" in message
    assert "Sunset期待度【 S 】90 / 100" in message
    assert "Chill指数【 S 】88 / 100" in message
    assert "日没：18:51" in message
    assert "対象時間帯：17:21〜19:21" in message
    assert "体感温度：" in message
    assert "湿度：" in message
    assert "風：" in message
    assert "突風：" in message
    assert "降水確率（最大）：" in message
    assert "夕焼け方向の雲" in message
    assert "低層 " in message
    assert "中層 " in message
    assert "高層 " in message
    assert "視程：" in message
    assert "コメント：" in message
    assert "検証メモ" not in message
    assert "Googleフォーム" not in message


def test_line_message_includes_vision_section_when_present(sample_summary):
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")
    vision = VisionResult(
        sunset_score=75,
        sky_condition="partly_cloudy",
        comment="薄い夕焼け",
        model="gemini-2.5-flash",
    )

    message = build_line_message(
        sample_summary,
        replace(scores, comment=build_comment(sample_summary, scores)),
        vision=vision,
    )

    assert "ライブカメラ実況評価" in message
    # Vision スコアも本文スコアと同じランク基準(score_label)で読めるようラベルを併記する
    assert "【 A 】75 / 100（partly_cloudy）" in message
    assert "薄い夕焼け" in message


def test_line_message_labels_vision_as_prediction_in_predict_mode(sample_summary):
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")
    vision = VisionResult(
        sunset_score=55,
        sky_condition="partly_cloudy",
        comment="水平線付近に抜けがあります",
        model="gemini-2.5-flash",
    )

    message = build_line_message(
        sample_summary,
        replace(scores, comment=build_comment(sample_summary, scores)),
        vision=vision,
        vision_mode="predict",
    )

    assert "カメラAI予測" in message
    assert "カメラ実況評価" not in message


def test_line_message_omits_vision_section_when_absent(sample_summary):
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    message = build_line_message(
        sample_summary,
        replace(scores, comment=build_comment(sample_summary, scores)),
    )

    assert "カメラ実況評価" not in message


def test_line_message_uses_internal_validation_wording(sample_summary):
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    message = build_line_message(
        sample_summary,
        replace(scores, comment=build_comment(sample_summary, scores)),
    )

    assert "予報" not in message
    assert "確実" not in message
    assert "時点" not in message
    assert "発表" not in message
    assert "対象時間帯" in message
    assert "検証メモ" not in message


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
