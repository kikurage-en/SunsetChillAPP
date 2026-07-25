"""雨シグナルSunsetキャップ(SUNSET_RAIN_CAP)のバックテスト再現スクリプト。

使い方:
    python scripts/backtest_rain_cap.py <predictions.csv>

入力は SunsetChillログ(Google Sheets)の `predictions` シートを CSV エクスポート
したもの。STATUS.md「雨シグナルのSunsetキャップとVision上方修正無効 —
2026-07-25 実装」の採用根拠(母集団・MAE・順位相関・悪化日)を再現する。

ルール(本番 `zushi_chill.scoring` と同じ判定軸):
    雨シグナル = 代表天気コードが雨・雷雨系 or 窓内予想雨量合計 >= 1.0mm
    新表示 = min(旧表示, min(純式, CAP))  # Vision上方修正無効+キャップ

真値プロキシは同一 date の日没時 `vision_sunset_color_score`(発色、7/20以降)を
優先し、無ければ 18時以降の行の `vision_sunset_score`(指標分離前の旧+20分値)。
同一AIの画像採点であり独立真値ではない。同一日の 13:00/17:00 は同じプロキシと
比較される非独立サンプルである点に注意(実効Nはユニーク日数)。
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from zushi_chill.constants import RAIN_WEATHER_CODES  # noqa: E402

START_DATE = "2026-06-01"
PREDICT_RUN_TIMES = ("13:00", "17:00")
CAPS = (30, 40)


def load_rows(csv_path: str) -> list[dict[str, str]]:
    with open(csv_path, encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    # 同一 (date, run_time) の重複記録(送信リトライ等)は最後の行を採用する
    dedup: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        if row["date"] >= START_DATE:
            dedup[(row["date"], row["run_time"])] = row
    return list(dedup.values())


def _float(row: dict[str, str], key: str) -> float | None:
    value = row.get(key, "")
    return float(value) if value not in ("", None) else None


def build_proxies(rows: list[dict[str, str]]) -> dict[str, tuple[str, float]]:
    proxies: dict[str, tuple[str, float]] = {}
    for row in rows:
        color = _float(row, "vision_sunset_color_score")
        if row.get("vision_evaluation_phase") == "sunset" and color is not None:
            proxies[row["date"]] = ("発色", color)
    for row in rows:
        legacy = _float(row, "vision_sunset_score")
        if (
            row["date"] not in proxies
            and row["run_time"] >= "18:00"
            and legacy is not None
            and not row.get("vision_evaluation_phase")
        ):
            proxies[row["date"]] = ("旧+20分", legacy)
    return proxies


def has_rain_signal(row: dict[str, str]) -> bool:
    code = _float(row, "weather_code")
    precipitation = _float(row, "precipitation") or 0.0
    return (code is not None and int(code) in RAIN_WEATHER_CODES) or precipitation >= 1.0


def spearman(pairs: list[tuple[float, float]]) -> float:
    def rank(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            average = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = average
            i = j + 1
        return ranks

    xs = rank([p[0] for p in pairs])
    ys = rank([p[1] for p in pairs])
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(xs, ys, strict=True))
    denominator = (
        sum((a - mean_x) ** 2 for a in xs) * sum((b - mean_y) ** 2 for b in ys)
    ) ** 0.5
    return numerator / denominator


def main(csv_path: str) -> None:
    rows = load_rows(csv_path)
    proxies = build_proxies(rows)
    predict_rows = [r for r in rows if r["run_time"] in PREDICT_RUN_TIMES]
    fired_rows = [r for r in predict_rows if has_rain_signal(r)]
    amount_only = [
        r
        for r in fired_rows
        if int(_float(r, "weather_code") or 0) not in RAIN_WEATHER_CODES
    ]
    fired_with_proxy = [r for r in fired_rows if r["date"] in proxies]

    print(f"母集団: {START_DATE}以降の13:00/17:00 全{len(predict_rows)}行(重複記録排除後)")
    print(
        f"雨シグナル発動: {len(fired_rows)}行"
        f" / 雨量条件のみで発動(雨コードなし): {len(amount_only)}行"
    )
    print(
        f"発動行のうち画像プロキシ有: {len(fired_with_proxy)}行"
        f"(ユニーク日数 {len({r['date'] for r in fired_with_proxy})}日 = 実効N)"
    )

    amount_vs_proxy = [
        (_float(r, "precipitation") or 0.0, proxies[r["date"]][1]) for r in fired_with_proxy
    ]
    print(f"予想雨量 vs プロキシの順位相関(発動行): {spearman(amount_vs_proxy):+.3f}")

    for cap in CAPS:
        total_old = total_new = covered = 0.0
        fired_old = fired_new = 0.0
        worsened: list[str] = []
        for row in predict_rows:
            proxy = proxies.get(row["date"])
            if proxy is None:
                continue
            pure = _float(row, "sunset_score")
            if pure is None:
                continue
            display_old = _float(row, "final_sunset_score")
            display_old = display_old if display_old is not None else pure
            display_new = (
                min(display_old, min(pure, cap)) if has_rain_signal(row) else display_old
            )
            covered += 1
            total_old += abs(display_old - proxy[1])
            total_new += abs(display_new - proxy[1])
            if has_rain_signal(row):
                fired_old += abs(display_old - proxy[1])
                fired_new += abs(display_new - proxy[1])
                if abs(display_new - proxy[1]) > abs(display_old - proxy[1]):
                    worsened.append(
                        f"{row['date']} {row['run_time']}"
                        f" 表示{display_old:.0f}→{display_new:.0f} vs {proxy[0]}{proxy[1]:.0f}"
                    )
        n_fired = len(fired_with_proxy)
        print(f"--- CAP={cap}")
        print(
            f"  プロキシ有 全{covered:.0f}行 MAE:"
            f" {total_old / covered:.1f} -> {total_new / covered:.1f}"
        )
        print(f"  発動{n_fired}行 MAE: {fired_old / n_fired:.1f} -> {fired_new / n_fired:.1f}")
        print(f"  悪化した行: {worsened if worsened else 'なし'}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
