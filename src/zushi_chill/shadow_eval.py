"""影の検証(shadow)のオフライン評価: 正解ラベルの作成と、既存予測との比較。

入力はすべてファイル(予測ログのCSV、Pagesに保存した画像、影の記録)なので、Contabo
でも手元でも後から実行できる。本番のスコアや通知には影響しない。
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from zushi_chill.sky_color import score_image

FORECAST_RUN_TIMES = frozenset({"13:00", "17:00"})


def load_rows(path: Path) -> list[dict[str, str]]:
    """予測ログCSVを読み、(date, run_time) ごとに最後の行だけを残す。"""
    latest: dict[tuple[str, str], dict[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row.get("date", ""), row.get("run_time", ""))
            latest.pop(key, None)
            latest[key] = row
    return list(latest.values())


def minutes_from_sunset(row: dict[str, str]) -> float | None:
    if not row.get("sunset_time"):
        return None
    sunset = datetime.fromisoformat(row["sunset_time"])
    reference = row.get("captured_at") or f"{row['date']}T{row['run_time']}:00+09:00"
    return round((datetime.fromisoformat(reference) - sunset).total_seconds() / 60.0, 2)


def slot_of(row: dict[str, str]) -> str:
    """観測枠。明示フェーズを優先し、旧行は実行時刻と日没の差から推定する。"""
    phase = row.get("observation_phase", "")
    if phase in {"forecast", "sunset", "afterglow"}:
        return phase
    offset = minutes_from_sunset(row)
    if row.get("run_time") in FORECAST_RUN_TIMES or (offset is not None and offset < -5):
        return "forecast"
    if offset is not None and offset <= 10:
        return "sunset"
    return "afterglow"


def gemini_label(row: dict[str, str], slot: str) -> str:
    """その枠としてGeminiが採点した値。予測モードで誤採点された行は空にする。"""
    phase = row.get("vision_evaluation_phase", "")
    if slot == "sunset" and phase == "sunset":
        return row.get("vision_sunset_color_score", "")
    if slot == "afterglow" and phase == "afterglow":
        return row.get("vision_afterglow_score", "")
    return ""


def build_labels(rows: Iterable[dict[str, str]], images_dir: Path) -> list[dict[str, object]]:
    """日没時・残照の各枠について、空の色の画素スコアとGemini採点を並べる。"""
    labels: list[dict[str, object]] = []
    for row in rows:
        slot = slot_of(row)
        if slot not in {"sunset", "afterglow"}:
            continue
        image = images_dir / "live-camera" / row["date"] / f"{row['run_time'].replace(':', '')}.jpg"
        if not image.exists():
            continue
        try:
            sky = score_image(image)
        except (RuntimeError, ValueError):
            continue
        labels.append(
            {
                "date": row["date"],
                "slot": slot,
                "run_time": row["run_time"],
                "minutes_from_sunset": minutes_from_sunset(row),
                "sky_color_score": sky,
                "gemini_score": gemini_label(row, slot),
            }
        )
    return labels


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"No rows to write to {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
