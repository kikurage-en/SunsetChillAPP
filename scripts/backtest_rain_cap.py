"""雨シグナルSunsetキャップ(SUNSET_RAIN_CAP)のバックテスト再現スクリプト。

使い方:
    python scripts/backtest_rain_cap.py <predictions.csv> [--through 2026-07-25]

入力は SunsetChillログ(Google Sheets)の `predictions` シートを CSV エクスポート
したもの。既定の対象期間は 2026-06-01〜2026-07-25 に固定してあり、STATUS.md
「雨シグナルのSunsetキャップとVision上方修正無効 — 2026-07-25 実装」の採用根拠
(母集団107/発動21/プロキシ17行=12日・順位相関+0.072・MAE・悪化行)を再現する。
以後のデータを含めた継続評価は `--through` で明示的に期間を延ばす(証跡の再現とは
別モード)。母集団のフィンガープリントを出力するので、過去行の遡及編集も検知できる。

反実仮想は本番ロジックと同一に計算する:
    1. 純式を min(純式, CAP) に制限(`zushi_chill.scoring.calculate_sunset_score` と同順)
    2. その行で実際にVisionブレンドが行われた場合(final列とVision列が両方ある場合)は
       CAP後純式とVisionを `blend_sunset_score` で再ブレンドし、雨シグナル時は
       min(ブレンド, CAP後純式) で上方修正を禁止(`main._blend_final_sunset` と同じ)
    3. ブレンドされていない行は min(旧表示, CAP後純式)

注意: 2026-07-25以降の保存 `sunset_score` は既にCAP適用後の値。CAP水準や時刻ゲートの
変種比較では、保存された気象入力・雲値からCAP前純式を再計算すること。
真値プロキシは同一AIの画像採点であり独立真値ではない。同一日の 13:00/17:00 は同じ
プロキシと比較される非独立サンプル(実効N=ユニーク日数)。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from zushi_chill.constants import RAIN_WEATHER_CODES  # noqa: E402
from zushi_chill.scoring import blend_sunset_score  # noqa: E402

START_DATE = "2026-06-01"
# STATUS.md 採用根拠の証跡を固定する既定終端。継続評価は --through で延長する。
EVIDENCE_END_DATE = "2026-07-25"
PREDICT_RUN_TIMES = ("13:00", "17:00")
CAPS = (30, 40)
# 本番 SUNSET_VISION_BLEND_WEIGHT の既定値。実行時の実値はSheetsに保存されないため、
# 全期間で既定値のままだったという運用事実(STATUS.md 層3)を仮定する。
BLEND_WEIGHT = 0.8


def load_rows(csv_path: str, through: str) -> list[dict[str, str]]:
    with open(csv_path, encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    # 同一 (date, run_time) の重複記録(送信リトライ等)は最後の行を採用する
    dedup: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        if START_DATE <= row["date"] <= through:
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


def counterfactual_display(
    pure: float,
    display_old: float,
    vision: float | None,
    was_blended: bool,
    cap: int,
) -> float:
    """雨シグナル行へ本番の新ロジックを適用した場合の表示値を返す。"""
    capped_pure = min(pure, cap)
    if was_blended and vision is not None:
        blended = blend_sunset_score(int(round(capped_pure)), int(round(vision)), BLEND_WEIGHT)
        return min(blended, capped_pure)
    return min(display_old, capped_pure)


def fingerprint(rows: list[dict[str, str]]) -> str:
    """母集団の遡及編集検知用ハッシュ(証跡数値に効く列のみ)。"""
    keys = (
        "date",
        "run_time",
        "sunset_score",
        "final_sunset_score",
        "vision_sunset_score",
        "weather_code",
        "precipitation",
    )
    digest = hashlib.md5()
    for row in sorted(rows, key=lambda r: (r["date"], r["run_time"])):
        digest.update("|".join(row.get(k, "") for k in keys).encode("utf-8"))
    return digest.hexdigest()[:12]


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


def evaluate(
    rows: list[dict[str, str]], proxies: dict[str, tuple[str, float]], cap: int
) -> dict[str, object]:
    total_old = total_new = covered = 0.0
    fired_old = fired_new = 0.0
    fired_covered = 0
    worsened: list[str] = []
    for row in rows:
        proxy = proxies.get(row["date"])
        pure = _float(row, "sunset_score")
        if proxy is None or pure is None:
            continue
        final = _float(row, "final_sunset_score")
        vision = _float(row, "vision_sunset_score")
        display_old = final if final is not None else pure
        if has_rain_signal(row):
            display_new = counterfactual_display(
                pure, display_old, vision, was_blended=final is not None, cap=cap
            )
        else:
            display_new = display_old
        covered += 1
        total_old += abs(display_old - proxy[1])
        total_new += abs(display_new - proxy[1])
        if has_rain_signal(row):
            fired_covered += 1
            fired_old += abs(display_old - proxy[1])
            fired_new += abs(display_new - proxy[1])
            if abs(display_new - proxy[1]) > abs(display_old - proxy[1]):
                worsened.append(
                    f"{row['date']} {row['run_time']}"
                    f" 表示{display_old:.0f}→{display_new:.0f} vs {proxy[0]}{proxy[1]:.0f}"
                )
    return {
        "covered": int(covered),
        "mae_old": total_old / covered,
        "mae_new": total_new / covered,
        "fired_covered": fired_covered,
        "fired_mae_old": fired_old / fired_covered,
        "fired_mae_new": fired_new / fired_covered,
        "worsened": worsened,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", help="SunsetChillログ predictions シートのCSVエクスポート")
    parser.add_argument(
        "--through",
        default=EVIDENCE_END_DATE,
        help=f"対象期間の終端日(既定 {EVIDENCE_END_DATE} = STATUS.md 証跡の固定期間)",
    )
    args = parser.parse_args(argv)

    rows = load_rows(args.csv_path, args.through)
    proxies = build_proxies(rows)
    predict_rows = [r for r in rows if r["run_time"] in PREDICT_RUN_TIMES]
    fired_rows = [r for r in predict_rows if has_rain_signal(r)]
    amount_only = [
        r
        for r in fired_rows
        if int(_float(r, "weather_code") or 0) not in RAIN_WEATHER_CODES
    ]
    fired_with_proxy = [r for r in fired_rows if r["date"] in proxies]

    print(f"期間: {START_DATE}〜{args.through} / フィンガープリント: {fingerprint(predict_rows)}")
    print(f"母集団: 13:00/17:00 全{len(predict_rows)}行(重複記録排除後)")
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
        result = evaluate(predict_rows, proxies, cap)
        print(f"--- CAP={cap}")
        print(
            f"  プロキシ有 全{result['covered']}行 MAE:"
            f" {result['mae_old']:.1f} -> {result['mae_new']:.1f}"
        )
        print(
            f"  発動{result['fired_covered']}行 MAE:"
            f" {result['fired_mae_old']:.1f} -> {result['fired_mae_new']:.1f}"
        )
        print(f"  悪化した行: {result['worsened'] if result['worsened'] else 'なし'}")


if __name__ == "__main__":
    main()
