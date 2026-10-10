from __future__ import annotations

import csv

from zushi_chill.shadow_eval import gemini_label, load_rows, slot_of


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
