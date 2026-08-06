from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from zushi_chill.message_builder import (
    _uncertain_prediction_comment,
    build_comment,
    build_line_message,
    wind_direction_label,
)
from zushi_chill.models import (
    JmaPrecipitationForecast,
    ScoreResult,
    SunsetCloud,
    SunsetPredictionReference,
    VisionResult,
)


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


def test_comment_uses_displayed_final_sunset_score(sample_summary):
    scores = ScoreResult(sunset_score=80, sunset_label="A", chill_score=80, chill_label="A")

    message = build_line_message(
        sample_summary,
        scores,
        final_sunset_score=40,
        final_sunset_label="C",
    )

    assert "夕焼け条件は元気がないっピ" in message
    comment = message.split("コメント：\n", 1)[1].split("\n\n--\n", 1)[0]
    assert len(comment.splitlines()) == 1
    assert "海辺" not in comment
    assert "大当たり" not in comment


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
    assert "水平線のあたりが雲でぎゅうぎゅうっピ" in comment


def test_line_message_contains_required_fields(sample_summary):
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    message = build_line_message(
        sample_summary,
        replace(scores, comment=build_comment(sample_summary, scores)),
    )

    assert message.startswith("2026-06-01 13:00\n")
    assert "逗子サンセットチル指数｜" not in message
    assert "Sunset期待度【 S 】90 / 100" in message
    assert "Chill指数【 S 】88 / 100" in message
    assert "日没：18:51" in message
    assert "気温：26.0℃" in message
    assert "湿度：" in message
    assert "風：" in message
    assert "降水確率：" in message
    assert "対象時間帯：" not in message
    assert "体感温度：" not in message
    assert "突風：" not in message
    assert "夕焼け方向の雲" in message
    assert "低層 " in message
    assert "中層 " in message
    assert "高層 " in message
    assert "視程：" in message
    assert "コメント：" in message
    assert "検証メモ" not in message
    assert "Googleフォーム" not in message


def test_line_message_uses_jma_six_hour_probability_when_available(sample_summary):
    scores = ScoreResult(sunset_score=70, sunset_label="A", chill_score=72, chill_label="A")
    period_start = sample_summary.sunset_time.replace(hour=18, minute=0)
    jma = JmaPrecipitationForecast(
        probability=20,
        period_start=period_start,
        period_end=period_start + timedelta(hours=6),
        area_name="東部",
        report_time=period_start.replace(hour=17),
    )

    message = build_line_message(
        sample_summary,
        scores,
        jma_precipitation=jma,
    )

    assert "降水確率：20%" in message
    assert "Open-Meteo" not in message


def test_line_message_uses_temperature_nearest_to_run_time(sample_summary):
    scores = ScoreResult(sunset_score=70, sunset_label="A", chill_score=72, chill_label="A")
    summary = replace(
        sample_summary,
        temperature_2m=30.0,
        temperature_2m_at_run_time=24.5,
    )

    message = build_line_message(summary, scores)

    assert "気温：24.5℃" in message
    assert "気温：30.0℃" not in message


def test_prediction_message_uses_weather_nearest_to_sunset(sample_summary):
    scores = ScoreResult(sunset_score=70, sunset_label="A", chill_score=72, chill_label="A")
    summary = replace(
        sample_summary,
        temperature_2m=30.0,
        relative_humidity_2m=60.0,
        visibility=5000.0,
        wind_speed_10m=2.0,
        wind_direction_10m=0.0,
        temperature_2m_at_run_time=31.0,
        temperature_2m_at_sunset=24.5,
        relative_humidity_2m_at_sunset=82.0,
        visibility_at_sunset_snapshot=15000.0,
        wind_speed_10m_at_sunset=4.5,
        wind_direction_10m_at_sunset=202.0,
    )
    sunset_cloud = SunsetCloud(
        cloud_cover=90,
        cloud_cover_low=80,
        cloud_cover_mid=70,
        cloud_cover_high=60,
        cloud_cover_low_at_sunset=20,
        cloud_cover_mid_at_sunset=30,
        cloud_cover_high_at_sunset=40,
    )

    message = build_line_message(
        summary,
        scores,
        vision_mode="predict",
        sunset_cloud=sunset_cloud,
    )

    assert "日没：18:51" in message
    assert "最寄り予報" not in message
    assert "気温：24.5℃" in message
    assert "湿度：82%" in message
    assert "風：南南西 4.5m/s" in message
    assert "低層 20% / 中層 30% / 高層 40%" in message
    assert "視程：15.0km" in message
    assert "気温：31.0℃" not in message
    assert "低層 80%" not in message


def test_line_message_includes_vision_section_when_present(sample_summary):
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")
    vision = VisionResult(
        sunset_score=75,
        sky_condition="partly_cloudy",
        comment="薄い夕焼け",
        model="gemini-2.5-flash",
    )

    message = build_line_message(sample_summary, scores, vision=vision)

    assert "ライブカメラ実況評価" in message
    # Vision スコアも本文スコアと同じランク基準(score_label)で読めるようラベルを併記する
    assert "【 A 】75 / 100（partly_cloudy）" in message
    camera_section = message.split("📷", 1)[1].split("コメント：", 1)[0]
    assert "薄い夕焼け" not in camera_section
    assert "薄い夕焼けっピ。" in message
    assert message.index("📷") < message.index("コメント：")


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


def test_line_message_shows_separate_sunset_image_scores(sample_summary):
    scores = ScoreResult(sunset_score=70, sunset_label="A", chill_score=75, chill_label="A")
    vision = VisionResult(
        sunset_score=68,
        sky_condition="golden_hour",
        comment="太陽と発色を確認",
        model="gemini-2.5-flash",
        evaluation_phase="sunset",
        sun_disk_visibility=80,
        sunset_color_score=65,
    )

    message = build_line_message(sample_summary, scores, vision=vision)

    assert "ライブカメラ日没時評価" in message
    assert "太陽ディスク：80 / 100" in message
    assert "日没時の発色：65 / 100" in message


def test_line_message_does_not_repeat_afterglow_score(sample_summary):
    scores = ScoreResult(sunset_score=70, sunset_label="A", chill_score=75, chill_label="A")
    vision = VisionResult(
        sunset_score=55,
        sky_condition="partly_cloudy",
        comment="雲に残照あり",
        model="gemini-2.5-flash",
        evaluation_phase="afterglow",
        afterglow_score=55,
    )

    message = build_line_message(sample_summary, scores, vision=vision)

    assert "ライブカメラ夕焼け評価" in message
    assert "【 B 】55 / 100（partly_cloudy）" in message
    assert "残照：55 / 100" not in message
    assert message.count("55 / 100") == 1
    assert "残照" not in message


def test_actual_message_uses_prior_prediction_and_integrates_camera_comment(sample_summary):
    summary = replace(sample_summary, run_time="19:01")
    scores = ScoreResult(sunset_score=80, sunset_label="A", chill_score=94, chill_label="S")
    vision = VisionResult(
        sunset_score=68,
        sky_condition="overcast",
        comment="うーん……雲が多い空でも、橙色の残照が見える",
        model="gemini-2.5-flash",
        evaluation_phase="afterglow",
        afterglow_score=68,
    )
    prior = SunsetPredictionReference(run_time="17:00", score=80, label="A")

    message = build_line_message(
        summary,
        scores,
        vision=vision,
        prior_sunset_prediction=prior,
    )

    assert "Sunset期待度【 A 】80 / 100" in message
    assert (
        "Chill指数【 S 】94 / 100\n\n"
        "📷 ライブカメラ夕焼け評価\n"
        "【 B 】68 / 100（overcast）\n\n"
        "コメント：\n"
    ) in message
    assert message.index("📷 ライブカメラ夕焼け評価") < message.index("コメント：")
    assert "残照：68 / 100" not in message
    camera_section = message.split("📷", 1)[1].split("コメント：", 1)[0]
    assert "橙色" not in camera_section
    comment = message.split("コメント：\n", 1)[1].split("\n\n--\n", 1)[0]
    assert any(word in comment for word in ("控えめ", "おとなしい", "伸びなかった"))
    assert "橙色の光が見えるっピ" in comment
    assert all(word not in comment for word in ("17時", "期待度", "残照", "実際の"))
    assert "うーん" not in comment
    assert "\n\n--\n日没：" in message


def test_actual_message_without_prior_prediction_describes_camera_result_directly(
    sample_summary,
):
    scores = ScoreResult(sunset_score=80, sunset_label="A", chill_score=75, chill_label="A")
    vision = VisionResult(
        sunset_score=55,
        sky_condition="partly_cloudy",
        comment="雲の間に少し色が見える",
        model="gemini-2.5-flash",
        evaluation_phase="afterglow",
        afterglow_score=55,
    )

    comment = build_comment(sample_summary, scores, prediction=False, vision=vision)

    assert "夕焼け" in comment
    assert all(
        word not in comment
        for word in ("気象条件の評価", "期待", "予想", "17時", "残照")
    )


def test_actual_favorable_outlook_and_vivid_result_is_concise(sample_summary):
    summary = replace(sample_summary, date="2026-08-05", run_time="19:00")
    scores = ScoreResult(sunset_score=76, sunset_label="A", chill_score=82, chill_label="A")
    vision = VisionResult(
        sunset_score=82,
        sky_condition="partly_cloudy",
        comment="富士山と空が燃えるように光ってる",
        model="gemini-2.5-flash",
        evaluation_phase="afterglow",
        afterglow_score=82,
    )
    prior = SunsetPredictionReference(run_time="17:00", score=76, label="A")

    comment = build_comment(
        summary,
        scores,
        prediction=False,
        vision=vision,
        prior_sunset_prediction=prior,
    ).splitlines()[0]

    assert comment.startswith("期待どおりの夕焼けだっピ！")
    assert all(word not in comment for word in ("17時", "期待度", "残照", "実際の"))


def test_actual_a_camera_result_adds_encouragement_after_blank_line(sample_summary):
    summary = replace(
        sample_summary,
        date="2026-08-05",
        run_time="19:00",
        apparent_temperature_at_run_time=30.0,
        relative_humidity_2m_at_run_time=80,
        temperature_2m_daytime_max=33,
        temperature_2m_at_run_time=27.0,
        wind_speed_10m_at_run_time=3.5,
    )
    scores = ScoreResult(sunset_score=76, sunset_label="A", chill_score=82, chill_label="A")
    vision = VisionResult(
        sunset_score=82,
        sky_condition="partly_cloudy",
        comment="富士山と空が燃えるように光ってる",
        model="gemini-2.5-flash",
        evaluation_phase="afterglow",
        afterglow_score=82,
    )
    prior = SunsetPredictionReference(run_time="17:00", score=76, label="A")

    comment = build_comment(
        summary,
        scores,
        prediction=False,
        vision=vision,
        prior_sunset_prediction=prior,
    )
    result_and_comfort, encouragement = comment.split("\n\n", maxsplit=1)

    assert len(result_and_comfort.splitlines()) == 2
    assert result_and_comfort.splitlines()[0].startswith("期待どおりの夕焼けだっピ！")
    assert "風" in result_and_comfort.splitlines()[1]
    assert encouragement.endswith(("っピ。", "っピ！"))
    assert all(word not in encouragement for word in ("風", "暑", "湿", "涼"))

    message = build_line_message(
        summary,
        scores,
        vision=vision,
        prior_sunset_prediction=prior,
    )
    assert f"{result_and_comfort}\n\n{encouragement}\n\n--\n" in message


def test_encouragement_requires_actual_a_or_better_camera_result(sample_summary):
    scores = ScoreResult(sunset_score=76, sunset_label="A", chill_score=82, chill_label="A")
    prior = SunsetPredictionReference(run_time="17:00", score=76, label="A")

    for vision_score, expected in ((69, False), (70, True), (90, True)):
        vision = VisionResult(
            sunset_score=vision_score,
            sky_condition="partly_cloudy",
            comment="空がきれいに染まってる",
            model="test",
            evaluation_phase="afterglow",
            afterglow_score=vision_score,
        )
        comment = build_comment(
            sample_summary,
            scores,
            prediction=False,
            vision=vision,
            prior_sunset_prediction=prior,
        )

        assert ("\n\n" in comment) is expected


def test_prediction_a_camera_result_does_not_add_encouragement(sample_summary):
    scores = ScoreResult(sunset_score=80, sunset_label="A", chill_score=75, chill_label="A")
    vision = VisionResult(
        sunset_score=82,
        sky_condition="partly_cloudy",
        comment="水平線の近くに良い雲がある",
        model="test",
        evaluation_phase="predict",
    )

    comment = build_comment(sample_summary, scores, prediction=True, vision=vision)

    assert "\n\n" not in comment


def test_general_encouragement_does_not_repeat_for_24_days(sample_summary):
    scores = ScoreResult(sunset_score=80, sunset_label="A", chill_score=75, chill_label="A")
    vision = VisionResult(
        sunset_score=82,
        sky_condition="partly_cloudy",
        comment="空がきれいに染まってる",
        model="test",
        evaluation_phase="afterglow",
        afterglow_score=82,
    )
    prior = SunsetPredictionReference(run_time="17:00", score=80, label="A")
    encouragements = {
        build_comment(
            replace(
                sample_summary,
                date=f"2026-09-{day:02d}",
                run_time="19:00",
                apparent_temperature_at_run_time=30.0,
                relative_humidity_2m_at_run_time=80,
                temperature_2m_daytime_max=33,
                temperature_2m_at_run_time=27.0,
                wind_speed_10m_at_run_time=3.5,
            ),
            scores,
            prediction=False,
            vision=vision,
            prior_sunset_prediction=prior,
        ).rsplit("\n\n", maxsplit=1)[1]
        for day in range(1, 25)
    }

    assert len(encouragements) == 24


def test_weather_encouragement_is_available_without_comfort_line(sample_summary):
    scores = ScoreResult(sunset_score=80, sunset_label="A", chill_score=75, chill_label="A")
    vision = VisionResult(
        sunset_score=82,
        sky_condition="partly_cloudy",
        comment="空がきれいに染まってる",
        model="test",
        evaluation_phase="afterglow",
        afterglow_score=82,
    )
    prior = SunsetPredictionReference(run_time="17:00", score=80, label="A")
    comments = [
        build_comment(
            replace(
                sample_summary,
                date=f"2026-10-{day:02d}",
                run_time="19:00",
                apparent_temperature_at_run_time=27.0,
                relative_humidity_2m_at_run_time=60,
                temperature_2m_daytime_max=27.5,
                temperature_2m_at_run_time=27.2,
                wind_speed_10m_at_run_time=4.0,
            ),
            scores,
            prediction=False,
            vision=vision,
            prior_sunset_prediction=prior,
        )
        for day in range(1, 13)
    ]

    assert all(len(comment.split("\n\n", maxsplit=1)[0].splitlines()) == 1 for comment in comments)
    assert any(
        "風" in comment.rsplit("\n\n", maxsplit=1)[1] for comment in comments
    )


def test_actual_pessimistic_outlook_and_absent_result_does_not_say_expected(
    sample_summary,
):
    summary = replace(sample_summary, date="2026-08-05", run_time="19:00")
    scores = ScoreResult(sunset_score=30, sunset_label="D", chill_score=75, chill_label="A")
    vision = VisionResult(
        sunset_score=30,
        sky_condition="overcast",
        comment="雲が多く、空はほとんど染まっていない",
        model="gemini-2.5-flash",
        evaluation_phase="afterglow",
        afterglow_score=30,
    )
    prior = SunsetPredictionReference(run_time="17:00", score=30, label="D")

    comment = build_comment(
        summary,
        scores,
        prediction=False,
        vision=vision,
        prior_sunset_prediction=prior,
    ).splitlines()[0]

    assert comment.startswith("心配してたとおり、空はほとんど染まらなかったっピ……。")
    assert "期待" not in comment


def test_prediction_camera_comments_do_not_repeat_across_seven_dates(sample_summary):
    days = tuple(f"2026-08-{day:02d}" for day in range(5, 12))
    scenarios = (
        (80, 80, 85),
        (60, 60, 60),
        (40, 40, 40),
        (70, 90, 60),
        (65, 80, 60),
        (45, 70, 40),
        (70, 40, 85),
        (60, 40, 65),
        (50, 30, 55),
    )

    for displayed_score, formula_score, vision_score in scenarios:
        scores = ScoreResult(
            sunset_score=displayed_score,
            sunset_label="test",
            chill_score=75,
            chill_label="A",
        )
        vision = VisionResult(
            sunset_score=vision_score,
            sky_condition="partly_cloudy",
            comment="雲の様子を確認",
            model="test",
        )
        comments = {
            build_comment(
                replace(sample_summary, date=day, run_time="17:00"),
                scores,
                vision=vision,
                formula_sunset_score=formula_score,
            ).splitlines()[0]
            for day in days
        }

        assert len(comments) == 7, (formula_score, vision_score, displayed_score)
        assert all(len(comment) <= 40 for comment in comments)
        assert all(comment.count("っピ") == 1 for comment in comments)
        assert all(
            all(
                wording not in comment
                for wording in (
                    "総合すると",
                    "合わせて見ると",
                    "両方を合わせると",
                    "総合判断では",
                    "ライブカメラの空",
                )
            )
            for comment in comments
        )


def test_actual_comparison_comments_do_not_repeat_across_seven_dates(sample_summary):
    days = tuple(f"2026-08-{day:02d}" for day in range(5, 12))
    scenarios = (
        (80, "A", 80),
        (80, "A", 55),
        (80, "A", 30),
        (55, "B", 80),
        (55, "B", 55),
        (55, "B", 30),
        (30, "D", 80),
        (30, "D", 55),
        (30, "D", 30),
    )

    for prior_score, prior_label, vision_score in scenarios:
        scores = ScoreResult(
            sunset_score=prior_score,
            sunset_label=prior_label,
            chill_score=75,
            chill_label="A",
        )
        vision = VisionResult(
            sunset_score=vision_score,
            sky_condition="overcast",
            comment="雲の多い空に橙色の光が見える",
            model="test",
            evaluation_phase="afterglow",
            afterglow_score=vision_score,
        )
        prior = SunsetPredictionReference(
            run_time="17:00",
            score=prior_score,
            label=prior_label,
        )
        comments = {
            build_comment(
                replace(sample_summary, date=day, run_time="19:01"),
                scores,
                prediction=False,
                vision=vision,
                prior_sunset_prediction=prior,
            ).splitlines()[0]
            for day in days
        }

        assert len(comments) == 7, (prior_score, vision_score)
        assert all(
            all(word not in comment for word in ("17時", "期待度", "残照", "実際の"))
            for comment in comments
        )
        if prior_score < 40:
            assert all("期待" not in comment for comment in comments)


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
    assert "対象時間帯" not in message
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

    assert "夕焼け" in build_comment(sample_summary, good)
    assert "海辺" not in build_comment(sample_summary, good).splitlines()[0]
    assert "期待薄っピ" in build_comment(sample_summary, comfortable_but_low_sunset)
    assert "海辺" not in build_comment(sample_summary, comfortable_but_low_sunset).splitlines()[0]
    assert "期待薄っピ" in build_comment(sample_summary, bad)
    assert "水平線のあたりが雲でぎゅうぎゅうっピ" in build_comment(low_cloud, good).splitlines()[0]
    assert "キャンバスになりそうっピ" in build_comment(high_cloud, good).splitlines()[0]
    assert "海風が元気すぎるかもっピ" in build_comment(windy, good).splitlines()[1]


def test_comment_omits_comfort_line_without_noteworthy_condition(sample_summary):
    scores = ScoreResult(sunset_score=75, sunset_label="A", chill_score=40, chill_label="C")

    comment = build_comment(sample_summary, scores)

    assert len(comment.splitlines()) == 1
    assert "海辺" not in comment


def test_comment_interprets_scores_and_high_apparent_temperature(sample_summary):
    summary = replace(sample_summary, apparent_temperature=34.4)
    scores = ScoreResult(sunset_score=75, sunset_label="A", chill_score=60, chill_label="B")

    comment = build_comment(summary, scores)

    sunset_line, comfort_line = comment.splitlines()
    assert "夕焼け" in sunset_line
    assert "海辺" not in sunset_line
    assert "気温" in comfort_line or "暑さ" in comfort_line
    assert "日中" in comfort_line or "昼間" in comfort_line
    assert "海風" in comfort_line or "風" in comfort_line
    assert "むしむし" not in comfort_line
    assert "確認してください" not in comment


def test_high_humidity_comment_combines_cooling_and_breeze(sample_summary):
    summary = replace(
        sample_summary,
        apparent_temperature=34.4,
        relative_humidity_2m_at_sunset=84,
        temperature_2m_daytime_max=34,
        temperature_2m_at_sunset=29,
        wind_speed_10m_at_sunset=4.5,
    )
    scores = ScoreResult(sunset_score=75, sunset_label="A", chill_score=50, chill_label="C")

    comfort_line = build_comment(summary, scores).splitlines()[1]

    assert any(word in comfort_line for word in ("湿度", "湿気", "むし暑"))
    assert "日中" in comfort_line or "昼間" in comfort_line or "夕方" in comfort_line
    assert "海風" in comfort_line or "風" in comfort_line


def test_actual_high_humidity_comment_uses_current_cooling_and_breeze(sample_summary):
    summary = replace(
        sample_summary,
        run_time="19:20",
        apparent_temperature=34.4,
        apparent_temperature_at_run_time=34.4,
        relative_humidity_2m_at_sunset=84,
        relative_humidity_2m_at_run_time=84,
        temperature_2m_daytime_max=34,
        temperature_2m_at_run_time=29,
        wind_speed_10m_at_sunset=4.5,
        wind_speed_10m_at_run_time=4.5,
    )
    scores = ScoreResult(sunset_score=40, sunset_label="C", chill_score=45, chill_label="C")

    comfort_line = build_comment(summary, scores, prediction=False).splitlines()[1]

    assert any(word in comfort_line for word in ("湿度", "湿気", "むし暑"))
    assert "日中" in comfort_line or "昼間" in comfort_line
    assert "海風" in comfort_line or "風" in comfort_line
    assert "なりそう" not in comfort_line
    assert "ありそう" not in comfort_line


def test_high_temperature_with_lower_humidity_does_not_claim_mugginess(sample_summary):
    summary = replace(
        sample_summary,
        apparent_temperature=34.4,
        relative_humidity_2m_at_sunset=60,
        temperature_2m_daytime_max=30,
        temperature_2m_at_sunset=29,
        wind_speed_10m=2,
        wind_speed_10m_at_sunset=2,
    )
    scores = ScoreResult(sunset_score=75, sunset_label="A", chill_score=55, chill_label="C")

    comfort_line = build_comment(summary, scores).splitlines()[1]

    assert "気温" in comfort_line or "暑さ" in comfort_line or "熱気" in comfort_line
    assert all(word not in comfort_line for word in ("湿度", "湿気", "むし", "むわ"))


def test_high_heat_and_strong_wind_are_combined(sample_summary):
    summary = replace(
        sample_summary,
        apparent_temperature=34.4,
        relative_humidity_2m_at_sunset=82,
        wind_speed_10m=9,
    )
    scores = ScoreResult(sunset_score=75, sunset_label="A", chill_score=40, chill_label="C")

    comfort_line = build_comment(summary, scores).splitlines()[1]

    assert any(word in comfort_line for word in ("湿度", "湿気", "むし暑"))
    assert "風" in comfort_line
    assert "助か" not in comfort_line


def test_high_heat_and_rain_are_combined(sample_summary):
    summary = replace(
        sample_summary,
        apparent_temperature=34.4,
        relative_humidity_2m_at_sunset=82,
        precipitation=1.5,
        weather_code=61,
        wind_speed_10m=2,
        wind_speed_10m_at_sunset=2,
    )
    scores = ScoreResult(sunset_score=40, sunset_label="C", chill_score=35, chill_label="D")

    comfort_line = build_comment(summary, scores).splitlines()[1]

    assert any(word in comfort_line for word in ("湿度", "湿気", "むし暑"))
    assert "雨" in comfort_line


def test_same_day_comfort_comments_vary_and_keep_multiple_factors(sample_summary):
    scores = ScoreResult(sunset_score=70, sunset_label="A", chill_score=45, chill_label="C")
    observations = (
        ("13:00", True),
        ("17:00", True),
        ("19:20", False),
    )
    comments = [
        build_comment(
            replace(
                sample_summary,
                date="2026-08-01",
                run_time=run_time,
                apparent_temperature=34.4,
                apparent_temperature_at_run_time=34.4,
                relative_humidity_2m_at_sunset=84,
                relative_humidity_2m_at_run_time=84,
                temperature_2m_daytime_max=34,
                temperature_2m_at_sunset=29,
                temperature_2m_at_run_time=29,
                wind_speed_10m_at_sunset=4.5,
                wind_speed_10m_at_run_time=4.5,
            ),
            scores,
            prediction=prediction,
        ).splitlines()[1]
        for run_time, prediction in observations
    ]

    assert len(set(comments)) == 3
    assert all(any(word in comment for word in ("湿度", "湿気", "むし暑")) for comment in comments)
    assert all(any(word in comment for word in ("日中", "昼間", "夕方")) for comment in comments)
    assert all("海風" in comment or "風" in comment for comment in comments)


def test_moderate_humid_relief_comments_stay_short_across_recent_schedule(
    sample_summary,
):
    scores = ScoreResult(sunset_score=70, sunset_label="A", chill_score=45, chill_label="C")
    observations = (
        ("2026-08-01", "13:00", True),
        ("2026-08-01", "17:00", True),
        ("2026-08-01", "19:20", False),
        ("2026-08-02", "13:00", True),
        ("2026-08-02", "17:00", True),
        ("2026-08-02", "19:20", False),
        ("2026-08-03", "13:00", True),
    )
    comments = [
        build_comment(
            replace(
                sample_summary,
                date=day,
                run_time=run_time,
                apparent_temperature=30.0,
                apparent_temperature_at_run_time=30.0,
                relative_humidity_2m_at_sunset=84,
                relative_humidity_2m_at_run_time=84,
                temperature_2m_daytime_max=34,
                temperature_2m_at_sunset=29,
                temperature_2m_at_run_time=29,
                wind_speed_10m_at_sunset=4.5,
                wind_speed_10m_at_run_time=4.5,
            ),
            scores,
            prediction=prediction,
        ).splitlines()[1]
        for day, run_time, prediction in observations
    ]

    assert len(set(comments)) == len(comments)
    assert all(len(comment) <= 35 for comment in comments)
    assert all(
        any(word in comment for word in ("湿気", "湿度", "むし", "蒸し", "むわ"))
        for comment in comments
    )
    assert all(
        any(word in comment for word in ("日中", "昼間", "夕方"))
        for comment in comments
    )
    assert all("海風" in comment or "風" in comment for comment in comments)


def test_after_sunset_comment_uses_actual_state_wording(sample_summary):
    summary = replace(
        sample_summary,
        run_time="19:20",
        apparent_temperature=34.4,
        apparent_temperature_at_run_time=34.4,
        temperature_2m_at_run_time=29,
        temperature_2m_at_sunset=29,
    )
    scores = ScoreResult(sunset_score=40, sunset_label="C", chill_score=45, chill_label="C")

    comment = build_comment(summary, scores, prediction=False)

    sunset_line, comfort_line = comment.splitlines()
    assert "夕焼け条件は元気がないっピ" in sunset_line
    assert "海辺" not in sunset_line
    assert "海辺" in comfort_line
    assert "暑" in comfort_line or "むしむし" in comfort_line
    assert "見込み" not in comment


def test_after_sunset_25_degree_comment_prioritizes_current_temperature(
    sample_summary,
):
    summary = replace(
        sample_summary,
        date="2026-08-03",
        run_time="19:20",
        apparent_temperature=30.2,
        apparent_temperature_at_run_time=30.2,
        temperature_2m_daytime_max=33.4,
        temperature_2m_at_run_time=25.6,
        temperature_2m_at_sunset=25.8,
        relative_humidity_2m_at_sunset=84,
        relative_humidity_2m_at_run_time=84,
        wind_speed_10m=3.5,
        wind_speed_10m_at_sunset=4.0,
        wind_speed_10m_at_run_time=4.0,
    )
    scores = ScoreResult(sunset_score=40, sunset_label="C", chill_score=60, chill_label="B")

    comfort_line = build_comment(summary, scores, prediction=False).splitlines()[1]

    assert "25℃台" in comfort_line
    assert "涼し" in comfort_line
    assert "風" in comfort_line
    assert "湿" in comfort_line
    assert "涼しさは控えめ" not in comfort_line
    assert "気温は高め" not in comfort_line


def test_after_sunset_25_degree_humid_breeze_comments_rotate_for_seven_days(
    sample_summary,
):
    scores = ScoreResult(sunset_score=40, sunset_label="C", chill_score=60, chill_label="B")
    comments = {
        build_comment(
            replace(
                sample_summary,
                date=f"2026-08-{day:02d}",
                run_time="19:20",
                apparent_temperature=30.2,
                apparent_temperature_at_run_time=30.2,
                temperature_2m_daytime_max=33.4,
                temperature_2m_at_run_time=25.6,
                temperature_2m_at_sunset=25.8,
                relative_humidity_2m_at_sunset=84,
                relative_humidity_2m_at_run_time=84,
                wind_speed_10m_at_run_time=4.0,
            ),
            scores,
            prediction=False,
        ).splitlines()[1]
        for day in range(3, 10)
    }

    assert len(comments) == 7
    assert all("25℃台" in comment for comment in comments)
    assert all("涼し" in comment for comment in comments)
    assert all("風" in comment for comment in comments)
    assert all("湿" in comment for comment in comments)


def test_after_sunset_cool_comment_and_message_explain_gust_cap(sample_summary):
    summary = replace(
        sample_summary,
        date="2026-08-03",
        run_time="18:59",
        temperature_2m_at_run_time=25.3,
        apparent_temperature_at_run_time=27.6,
        relative_humidity_2m_at_run_time=78,
        precipitation_probability_at_run_time=0,
        precipitation_at_run_time=0,
        weather_code_at_run_time=2,
        visibility_at_run_time=26220,
        wind_speed_10m_at_run_time=4.17,
        wind_direction_10m_at_run_time=32,
        wind_gusts_10m_at_run_time=13.1,
    )
    scores = ScoreResult(
        sunset_score=40,
        sunset_label="C",
        chill_score=50,
        chill_label="C",
        chill_weather_basis="run_time",
    )
    period_start = summary.sunset_time.replace(hour=18, minute=0)
    jma = JmaPrecipitationForecast(
        probability=20,
        period_start=period_start,
        period_end=period_start + timedelta(hours=6),
        area_name="東部",
        report_time=period_start.replace(hour=17),
    )

    comment = build_comment(summary, scores, prediction=False)
    message = build_line_message(
        summary,
        replace(scores, comment=comment),
        vision_mode="actual",
        jma_precipitation=jma,
    )

    comfort_line = comment.splitlines()[1]
    assert "25℃台" in comfort_line
    assert "涼し" in comfort_line
    assert "風" in comfort_line
    assert "気温：25.3℃" in message
    assert "湿度：78%" in message
    assert "風：北北東 4.2m/s" in message
    assert "突風：13.1m/s" in message
    assert "降水確率：0%" in message
    assert "降水確率：20%" not in message


def test_after_sunset_high_heat_comment_changes_on_consecutive_dates(sample_summary):
    scores = ScoreResult(sunset_score=40, sunset_label="C", chill_score=45, chill_label="C")
    dates = (
        "2026-07-28",
        "2026-07-29",
        "2026-07-30",
        "2026-07-31",
        "2026-08-01",
        "2026-08-02",
    )
    summaries = [
        replace(
            sample_summary,
            date=day,
            run_time="19:20",
            apparent_temperature=34.4,
            apparent_temperature_at_run_time=34.4,
            temperature_2m_at_run_time=29,
            temperature_2m_at_sunset=29,
        )
        for day in dates
    ]
    details = [
        build_comment(summary, scores, prediction=False).splitlines()[1] for summary in summaries
    ]
    repeated = build_comment(summaries[0], scores, prediction=False).splitlines()[1]

    assert details[0] == repeated
    assert len(set(details)) == 6
    assert all(detail.endswith(("っピ。", "っピ……。")) for detail in details)
    assert all("見込み" not in detail for detail in details)


def test_comment_marks_dry_high_precipitation_conflict_as_uncertain(sample_summary):
    summary = replace(
        sample_summary,
        precipitation_probability=87,
        precipitation=0,
        weather_code=0,
    )
    cloud = SunsetCloud(
        cloud_cover=17,
        cloud_cover_low=10,
        cloud_cover_mid=13.3,
        cloud_cover_high=0,
    )
    scores = ScoreResult(sunset_score=75, sunset_label="A", chill_score=40, chill_label="C")

    comment = build_comment(summary, scores, cloud)

    assert "夕焼けは" in comment
    assert "西の空" in comment
    assert "自信は控えめっピ" in comment
    assert "予報" not in comment
    assert "数字" not in comment


def test_13_comment_becomes_hesitant_when_rain_timing_changes(sample_summary):
    summary = replace(
        sample_summary,
        precipitation_probability_before_sunset=10,
        precipitation_probability_at_sunset=70,
    )
    scores = ScoreResult(sunset_score=75, sunset_label="A", chill_score=80, chill_label="A")

    comment = build_comment(summary, scores)

    assert len(comment.splitlines()) == 1
    assert "夕焼けはすっごく期待できそうっピ" in comment
    assert " でも、" in comment
    assert "天気が変わりやすそうっピ" in comment
    assert "予報" not in comment
    assert "数字" not in comment


def test_17_comment_integrates_camera_and_formula_when_they_diverge(sample_summary):
    summary = replace(sample_summary, run_time="17:00")
    scores = ScoreResult(sunset_score=70, sunset_label="A", chill_score=75, chill_label="A")
    vision = VisionResult(
        sunset_score=85,
        sky_condition="clear",
        comment="よく晴れている",
        model="test",
    )

    comment = build_comment(
        summary,
        scores,
        vision=vision,
        formula_sunset_score=40,
    )

    assert len(comment.splitlines()) == 1
    assert "条件" in comment
    assert "今の空" in comment or "目の前の空" in comment
    assert "けど" in comment or "でも" in comment
    assert len(comment) <= 40
    assert comment.count("っピ") == 1
    assert all(
        wording not in comment
        for wording in (
            "総合すると",
            "合わせて見ると",
            "両方を合わせると",
            "総合判断では",
            "ライブカメラの空",
        )
    )
    assert "予報" not in comment
    assert "数字" not in comment


def test_good_weather_and_medium_camera_uses_one_concise_conclusion(sample_summary):
    summary = replace(sample_summary, date="2026-08-06", run_time="17:00")
    scores = ScoreResult(sunset_score=60, sunset_label="B", chill_score=75, chill_label="A")
    vision = VisionResult(
        sunset_score=60,
        sky_condition="partly_cloudy",
        comment="雲の様子を確認",
        model="test",
    )

    comment = build_comment(
        summary,
        scores,
        vision=vision,
        formula_sunset_score=80,
    ).splitlines()[0]

    assert "条件" in comment
    assert "今の空" in comment or "目の前" in comment
    assert any(
        word in comment
        for word in ("五分五分", "様子見", "半々", "慎重", "微妙", "もうひと声")
    )
    assert comment.count("夕焼け") <= 1
    assert comment.count("っピ") == 1
    assert len(comment) <= 40


def test_non_scheduled_prediction_keeps_normal_confident_comment(sample_summary):
    summary = replace(
        sample_summary,
        run_time="16:00",
        precipitation_probability_before_sunset=10,
        precipitation_probability_at_sunset=70,
    )
    scores = ScoreResult(sunset_score=75, sunset_label="A", chill_score=80, chill_label="A")

    comment = build_comment(summary, scores)

    assert "夕焼け" in comment
    assert "海辺" not in comment.splitlines()[0]
    assert "自信ない" not in comment


def test_all_score_headlines_rotate_across_three_dates(sample_summary):
    band_scores = {"good": 75, "medium": 60, "low": 40}
    dates = ("2026-07-29", "2026-07-30", "2026-07-31")

    for prediction in (True, False):
        run_time = "16:00" if prediction else "19:20"
        for sunset_band, sunset_score in band_scores.items():
            for chill_band, chill_score in band_scores.items():
                headlines = {
                    build_comment(
                        replace(sample_summary, date=day, run_time=run_time),
                        ScoreResult(
                            sunset_score=sunset_score,
                            sunset_label="test",
                            chill_score=chill_score,
                            chill_label="test",
                        ),
                        prediction=prediction,
                    ).splitlines()[0]
                    for day in dates
                }

                assert len(headlines) == 3, (
                    prediction,
                    sunset_band,
                    chill_band,
                    headlines,
                )
                assert all("っピ" in headline for headline in headlines)
                assert all(
                    not any(
                        comfort_word in headline
                        for comfort_word in ("海辺", "過ごしやすさ", "居心地", "快適さ")
                    )
                    for headline in headlines
                )


def test_sunset_and_comfort_details_rotate_across_three_dates(sample_summary):
    scores = ScoreResult(sunset_score=60, sunset_label="B", chill_score=60, chill_label="B")
    dates = ("2026-07-29", "2026-07-30", "2026-07-31")
    sunset_conditions = (
        replace(sample_summary, cloud_cover_low=80),
        replace(sample_summary, cloud_cover_low=20, cloud_cover_high=50),
    )
    comfort_conditions = (
        replace(sample_summary, apparent_temperature=29),
        replace(sample_summary, apparent_temperature=34),
        replace(sample_summary, wind_speed_10m=8),
    )

    for prediction in (True, False):
        run_time = "16:00" if prediction else "19:20"
        for condition in sunset_conditions:
            comments = {
                build_comment(
                    replace(
                        condition,
                        date=day,
                        run_time=run_time,
                        temperature_2m_at_run_time=condition.temperature_2m,
                        apparent_temperature_at_run_time=(condition.apparent_temperature),
                        relative_humidity_2m_at_run_time=(condition.relative_humidity_2m),
                        wind_speed_10m_at_run_time=condition.wind_speed_10m,
                        wind_gusts_10m_at_run_time=condition.wind_gusts_10m,
                    ),
                    scores,
                    prediction=prediction,
                )
                for day in dates
            }

            assert len(comments) == 3
            assert all(len(comment.splitlines()) == 1 for comment in comments)
            assert all("海辺" not in comment for comment in comments)

        for condition in comfort_conditions:
            details = {
                build_comment(
                    replace(
                        condition,
                        date=day,
                        run_time=run_time,
                        temperature_2m_at_run_time=(
                            29 if condition.apparent_temperature >= 28 else condition.temperature_2m
                        ),
                        apparent_temperature_at_run_time=(condition.apparent_temperature),
                        relative_humidity_2m_at_run_time=(condition.relative_humidity_2m),
                        wind_speed_10m_at_run_time=condition.wind_speed_10m,
                    ),
                    scores,
                    prediction=prediction,
                ).splitlines()[1]
                for day in dates
            }

            assert len(details) == 3
            assert all("っピ" in detail for detail in details)
            assert all(
                not any(
                    sunset_word in detail for sunset_word in ("夕焼け", "夕陽", "高い雲", "低い雲")
                )
                for detail in details
            )


def test_uncertainty_direction_and_caveat_rotate_across_dates(sample_summary):
    scores = ScoreResult(sunset_score=70, sunset_label="A", chill_score=75, chill_label="A")
    vision = VisionResult(
        sunset_score=85,
        sky_condition="clear",
        comment="よく晴れている",
        model="test",
    )
    comments = [
        build_comment(
            replace(sample_summary, date=day, run_time="17:00"),
            scores,
            vision=vision,
            formula_sunset_score=40,
        ).splitlines()
        for day in ("2026-07-29", "2026-07-30", "2026-07-31")
    ]

    assert len({lines[0] for lines in comments}) == 3
    assert all(len(lines) == 1 for lines in comments)
    assert all("海辺" not in lines[0] for lines in comments)
    assert all("夕焼け" in lines[0] or "空の色" in lines[0] for lines in comments)
    assert all("予報" not in lines[0] for lines in comments)
    assert all("数字" not in lines[0] for lines in comments)


def test_every_uncertainty_reason_has_five_user_facing_variants(sample_summary):
    uncertainty_reasons = (
        "missing_values",
        "convective_weather",
        "rain_timing_shift",
        "dry_high_precipitation_conflict",
        "precipitation_forecast_disagreement",
        "vision_more_optimistic",
        "vision_more_pessimistic",
        "borderline_precipitation",
    )

    for reason in uncertainty_reasons:
        details = {
            _uncertain_prediction_comment(
                reason,
                replace(sample_summary, date=day, run_time="17:00"),
            )
            for day in (
                "2026-07-29",
                "2026-07-30",
                "2026-07-31",
                "2026-08-01",
                "2026-08-02",
            )
        }

        assert len(details) == 5, (reason, details)
        assert all("っピ" in detail for detail in details)
        assert all("予報" not in detail for detail in details)
        assert all("数字" not in detail for detail in details)


def test_precipitation_disagreement_keeps_direction_and_uses_sky_language(
    sample_summary,
):
    summary = replace(sample_summary, run_time="17:00", precipitation_probability=53)
    scores = ScoreResult(sunset_score=76, sunset_label="A", chill_score=66, chill_label="B")
    period_start = summary.sunset_time.replace(hour=18, minute=0)
    jma = JmaPrecipitationForecast(
        probability=10,
        period_start=period_start,
        period_end=period_start + timedelta(hours=6),
        area_name="東部",
        report_time=period_start.replace(hour=17),
    )

    comment = build_comment(summary, scores, jma_precipitation=jma)

    assert "夕焼け" in comment or "空の色" in comment
    assert " でも、" in comment
    assert any(word in comment for word in ("空模様", "天気", "空が"))
    assert "予報" not in comment
    assert "数字" not in comment
    assert "言い切れない" not in comment


def test_precipitation_disagreement_does_not_repeat_between_adjacent_runs(
    sample_summary,
):
    period_start = sample_summary.sunset_time.replace(hour=18, minute=0)
    jma = JmaPrecipitationForecast(
        probability=10,
        period_start=period_start,
        period_end=period_start + timedelta(hours=6),
        area_name="東部",
        report_time=period_start.replace(hour=17),
    )
    observations = (
        ("2026-07-31", "17:00", 76),
        ("2026-08-01", "13:00", 80),
        ("2026-08-01", "17:00", 75),
        ("2026-08-02", "13:00", 72),
    )
    comments = [
        build_comment(
            replace(
                sample_summary,
                date=day,
                run_time=run_time,
                precipitation_probability=53,
            ),
            ScoreResult(
                sunset_score=score,
                sunset_label="A",
                chill_score=66,
                chill_label="B",
            ),
            jma_precipitation=jma,
        ).splitlines()[0]
        for day, run_time, score in observations
    ]

    assert all(
        current != following for current, following in zip(comments, comments[1:], strict=False)
    )
    assert all("予報" not in comment for comment in comments)


def test_wind_direction_label_boundaries():
    assert wind_direction_label(0) == "北"
    assert wind_direction_label(360) == "北"
    assert wind_direction_label(348.75) == "北"
    assert wind_direction_label(11.24) == "北"
    assert wind_direction_label(11.25) == "北北東"
    assert wind_direction_label(90) == "東"
    assert wind_direction_label(180) == "南"
    assert wind_direction_label(270) == "西"
