from __future__ import annotations

import csv
import math

from zushi_chill.shadow_eval import (
    auc,
    day_signals,
    forecast_rows,
    gemini_label,
    load_rows,
    path_cap,
    slot_of,
    spearman,
)


def _row(**values):
    base = {
        "date": "2026-10-09",
        "run_time": "17:14",
        "sunset_time": "2026-10-09T17:15+09:00",
        "captured_at": "",
        "observation_phase": "",
        "vision_evaluation_phase": "",
        "vision_sunset_color_score": "",
        "vision_afterglow_score": "",
    }
    base.update(values)
    return base


def test_slot_prefers_explicit_phase_and_infers_legacy_rows():
    assert slot_of(_row(observation_phase="sunset")) == "sunset"
    assert slot_of(_row(run_time="17:00")) == "forecast"
    assert slot_of(_row(run_time="17:20")) == "sunset"
    assert slot_of(_row(run_time="17:35")) == "afterglow"


def test_gemini_label_is_blank_when_the_slot_was_scored_as_a_prediction():
    # 2026-07-28〜10-09: 日没時の撮影が予測として採点された行は真値に使わない。
    mis_phased = _row(
        observation_phase="sunset",
        vision_evaluation_phase="predict",
        vision_sunset_color_score="70",
    )
    assert gemini_label(mis_phased, "sunset") == ""
    scored = _row(
        observation_phase="afterglow",
        vision_evaluation_phase="afterglow",
        vision_afterglow_score="68",
    )
    assert gemini_label(scored, "afterglow") == "68"


def test_load_rows_keeps_the_last_write_per_run(tmp_path):
    path = tmp_path / "log.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "run_time", "line_sent"])
        writer.writeheader()
        writer.writerow({"date": "2026-10-09", "run_time": "13:00", "line_sent": "False"})
        writer.writerow({"date": "2026-10-09", "run_time": "13:00", "line_sent": "True"})

    rows = load_rows(path)

    assert rows == [{"date": "2026-10-09", "run_time": "13:00", "line_sent": "True"}]


def _forecast_row(**values):
    row = {
        "date": "2026-10-08",
        "run_time": "17:00",
        "precipitation_probability": "0",
        "precipitation": "0",
        "weather_code": "1",
        "visibility": "24000",
        "wind_speed_10m": "3",
        "sunset_cloud_cover": "10",
        "sunset_cloud_cover_low": "8",
        "sunset_cloud_cover_mid": "5",
        "sunset_cloud_cover_high": "0",
        "sunset_score": "80",
        "final_sunset_score": "75",
    }
    row.update(values)
    return row


def _features(**values):
    features = {
        "sat_cloud_cover_far": 0.0,
        "sat_cloud_cover_low_far": 0.0,
        "sat_cloud_cover_mid_near": 0.0,
        "sat_cloud_cover_high_near": 0.0,
        "sat_path_max": 0.0,
        "sat_path_mean": 0.0,
    }
    features.update(values)
    return features


def test_forecast_rows_take_the_latest_forecast_before_sunset():
    rows = [
        _forecast_row(run_time="13:00", sunset_score="60"),
        _forecast_row(run_time="17:00", sunset_score="80"),
        _forecast_row(
            date="2026-10-09",
            run_time="13:00",
            sunset_time="2026-10-09T17:14+09:00",
            sunset_score="70",
        ),
        _forecast_row(
            date="2026-10-09",
            run_time="17:16",
            sunset_time="2026-10-09T17:14+09:00",
            observation_phase="sunset",
            sunset_score="10",
        ),
        # 2026-10-10以降の夕方予測は日没60分前で、run_timeが日ごとに変わる。
        _forecast_row(
            date="2026-10-11",
            run_time="13:00",
            sunset_time="2026-10-11T17:11+09:00",
            sunset_score="50",
        ),
        _forecast_row(
            date="2026-10-11",
            run_time="16:11",
            sunset_time="2026-10-11T17:11+09:00",
            observation_phase="forecast",
            sunset_score="65",
        ),
    ]
    chosen = forecast_rows(rows)
    assert chosen["2026-10-08"]["sunset_score"] == "80"
    assert chosen["2026-10-09"]["sunset_score"] == "70"
    assert chosen["2026-10-11"]["sunset_score"] == "65"


def test_day_signals_swap_only_the_cloud_inputs():
    signals = day_signals(_forecast_row(), _features(sat_path_max=96.0, sat_path_mean=88.0))
    # ログ雲量の現行式と、衛星の快晴(総雲量<15・低層雲<5)の超快晴天井90。
    assert signals["base"] == 80
    assert signals["c1"] == 90
    assert signals["c2"] == 30  # 経路maxの総雲量85%以上キャップ
    assert signals["c3"] == 30  # ログ純式に経路平均のキャップ
    assert signals["logged"] == 80
    assert signals["final"] == 75


def test_day_signals_skip_rows_without_logged_clouds():
    assert day_signals(_forecast_row(sunset_cloud_cover=""), _features()) is None


def test_rank_metrics_handle_ties():
    assert math.isclose(spearman([1, 2, 2, 3], [1, 2, 2, 3]), 1.0)
    assert auc([90, 80, 80, 10], [True, True, False, False]) == 0.875
    assert path_cap(80, 75) == 65
    assert path_cap(80, 50) == 80
