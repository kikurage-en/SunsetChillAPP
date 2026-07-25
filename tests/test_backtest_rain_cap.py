from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "backtest_rain_cap",
    Path(__file__).resolve().parents[1] / "scripts" / "backtest_rain_cap.py",
)
backtest = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(backtest)

COLUMNS = [
    "date",
    "run_time",
    "sunset_score",
    "final_sunset_score",
    "vision_sunset_score",
    "vision_evaluation_phase",
    "vision_sunset_color_score",
    "weather_code",
    "precipitation",
]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> str:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows({c: r.get(c, "") for c in COLUMNS} for r in rows)
    return str(path)


def test_load_rows_dedups_and_respects_through(tmp_path):
    """同一(date, run_time)は最後の行を採用し、--through より後の行は証跡に混ぜない。"""
    path = _write_csv(
        tmp_path / "p.csv",
        [
            {"date": "2026-06-10", "run_time": "17:00", "sunset_score": "10"},
            {"date": "2026-06-10", "run_time": "17:00", "sunset_score": "20"},
            {"date": "2026-07-26", "run_time": "17:00", "sunset_score": "30"},
        ],
    )
    rows = backtest.load_rows(path, "2026-07-25")
    assert len(rows) == 1
    assert rows[0]["sunset_score"] == "20"


def test_build_proxies_prefers_sunset_color_over_legacy(tmp_path):
    """発色(phase=sunset)が旧+20分値(phaseなし夕方行)より優先される。"""
    path = _write_csv(
        tmp_path / "p.csv",
        [
            {
                "date": "2026-07-24",
                "run_time": "18:50",
                "vision_evaluation_phase": "sunset",
                "vision_sunset_color_score": "80",
                "vision_sunset_score": "70",
            },
            {"date": "2026-07-24", "run_time": "19:10", "vision_sunset_score": "20"},
            {"date": "2026-06-20", "run_time": "19:20", "vision_sunset_score": "10"},
        ],
    )
    proxies = backtest.build_proxies(backtest.load_rows(path, "2026-07-25"))
    assert proxies["2026-07-24"] == ("発色", 80.0)
    assert proxies["2026-06-20"] == ("旧+20分", 10.0)


def test_has_rain_signal_matches_production_axis():
    assert backtest.has_rain_signal({"weather_code": "61", "precipitation": "0"}) is True
    assert backtest.has_rain_signal({"weather_code": "3", "precipitation": "1.0"}) is True
    assert backtest.has_rain_signal({"weather_code": "3", "precipitation": "0.9"}) is False


def test_spearman_known_values():
    assert backtest.spearman([(1, 10), (2, 20), (3, 30)]) == pytest.approx(1.0)
    assert backtest.spearman([(1, 30), (2, 20), (3, 10)]) == pytest.approx(-1.0)


def test_counterfactual_display_matches_production_blend():
    """反実仮想は本番と同順(純式CAP→再ブレンド→上方修正禁止)で計算する。

    codexレビュー(2026-07-26)の指摘例: 旧純式65・Vision20(下方)のブレンド行は、
    min(旧表示29, CAP後純式40)=29 ではなく、CAP後純式40と再ブレンドした24が本番の値。
    """
    assert (
        backtest.counterfactual_display(65, 29, 20, was_blended=True, cap=40) == 24
    )
    # 2026-07-25 17:00 実例: 楽観Vision(65)は上方修正禁止で CAP後純式40 に一致
    assert (
        backtest.counterfactual_display(45, 61, 65, was_blended=True, cap=40) == 40
    )
    # ブレンドされていない行(final列なし)は min(旧表示, CAP後純式)
    assert backtest.counterfactual_display(90, 90, None, was_blended=False, cap=40) == 40
    assert backtest.counterfactual_display(10, 10, None, was_blended=False, cap=40) == 10


def test_evaluate_reports_mae_and_worsened_rows(tmp_path):
    """発動行だけが変化し、プロキシより下へ抜けた行が悪化として列挙される。"""
    path = _write_csv(
        tmp_path / "p.csv",
        [
            # 雨コード・純式80 → CAP40。プロキシ70なので誤差10→30に悪化する行
            {
                "date": "2026-07-01",
                "run_time": "17:00",
                "sunset_score": "80",
                "weather_code": "61",
                "precipitation": "2.0",
            },
            {"date": "2026-07-01", "run_time": "19:20", "vision_sunset_score": "70"},
            # 雨コード・純式80 → CAP40。プロキシ10なので誤差70→30に改善する行
            {
                "date": "2026-07-02",
                "run_time": "17:00",
                "sunset_score": "80",
                "weather_code": "61",
                "precipitation": "2.0",
            },
            {"date": "2026-07-02", "run_time": "19:20", "vision_sunset_score": "10"},
            # 雨シグナルなしの行は変化しない
            {
                "date": "2026-07-03",
                "run_time": "13:00",
                "sunset_score": "80",
                "weather_code": "1",
                "precipitation": "0",
            },
            {"date": "2026-07-03", "run_time": "19:20", "vision_sunset_score": "80"},
        ],
    )
    rows = backtest.load_rows(path, "2026-07-25")
    proxies = backtest.build_proxies(rows)
    predict_rows = [r for r in rows if r["run_time"] in backtest.PREDICT_RUN_TIMES]
    result = backtest.evaluate(predict_rows, proxies, cap=40)

    assert result["covered"] == 3
    assert result["fired_covered"] == 2
    # 旧: |80-70|+|80-10|+|80-80| = 80/3、新: |40-70|+|40-10|+|80-80| = 60/3
    assert result["mae_old"] == pytest.approx(80 / 3)
    assert result["mae_new"] == pytest.approx(60 / 3)
    assert len(result["worsened"]) == 1
    assert result["worsened"][0].startswith("2026-07-01 17:00")
