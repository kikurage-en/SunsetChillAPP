"""影の検証(shadow)のオフライン評価: 正解ラベルの作成と、既存予測との比較。

入力はすべてファイル(予測ログのCSV、Pagesに保存した画像、影の記録)なので、Contabo
でも手元でも後から実行できる。本番のスコアや通知には影響しない。
"""

from __future__ import annotations

import csv
import math
import random
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from zushi_chill.models import SunsetCloud
from zushi_chill.scoring import calculate_sunset_score
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


# ---------------------------------------------------------------- 衛星実況の比較
# 2026-10-10に結果を見る前に固定した比較(STATUS「衛星実況の影の検証」)。
# C1・C2は雲の入力だけを替えた差を見るため、ログの本番雲量で現行式を再計算した値と比べる。
# C3は既存の純式スコア(ログ値)に上限を足すだけなので、ログ値と比べる。
CANDIDATES = (
    ("C1 置換", "c1", "base"),
    ("C2 経路max", "c2", "base"),
    ("C3 遮蔽キャップ", "c3", "logged"),
)
SIGNAL_NAMES = {
    "base": "現行式+ログ雲量",
    "logged": "ログ純式",
    "final": "ログ表示値",
    "c1": "C1",
    "c2": "C2",
    "c3": "C3",
}
LABELS = (("sky", "空の色(AI不使用)"), ("gemini", "Gemini"))
SLOTS = (("sunset", "日没時"), ("afterglow", "残照"))
GEMINI_VIVID = 70.0
SKY_VIVID_QUANTILE = 0.8
BOOTSTRAP_REPS = 2000


@dataclass(frozen=True)
class FormulaInputs:
    """本番のSunset式が雲以外に使う入力。ログ行から復元する。"""

    precipitation_probability: float
    precipitation: float
    weather_code: int
    visibility: float
    wind_speed_10m: float


def _number(row: dict[str, str], key: str) -> float | None:
    value = row.get(key, "")
    if value in ("", None):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def forecast_rows(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
    """日付ごとの比較相手の予測行。17:00、無ければ13:00。"""
    by_date: dict[str, dict[str, str]] = {}
    rows = list(rows)
    for run_time in ("13:00", "17:00"):
        for row in rows:
            if row.get("run_time") == run_time:
                by_date[row["date"]] = row
    return by_date


def formula_inputs(row: dict[str, str]) -> FormulaInputs | None:
    keys = (
        "precipitation_probability",
        "precipitation",
        "weather_code",
        "visibility",
        "wind_speed_10m",
    )
    values = [_number(row, key) for key in keys]
    if any(value is None for value in values):
        return None
    probability, precipitation, code, visibility, wind = values
    return FormulaInputs(probability, precipitation, int(code), visibility, wind)


def logged_cloud(row: dict[str, str]) -> SunsetCloud | None:
    values = [
        _number(row, f"sunset_cloud_cover{suffix}") for suffix in ("", "_low", "_mid", "_high")
    ]
    if any(value is None for value in values):
        return None
    return SunsetCloud(*values)


def path_cap(score: float, path_mean: float) -> float:
    """C3: 経路の雲量平均に本番の総雲量キャップと同じ閾値を当てる。"""
    if path_mean >= 85:
        return min(score, 30)
    if path_mean >= 70:
        return min(score, 65)
    return score


def day_signals(
    row: dict[str, str], features: dict[str, float | None]
) -> dict[str, float | None] | None:
    inputs = formula_inputs(row)
    cloud = logged_cloud(row)
    logged = _number(row, "sunset_score")
    if inputs is None or cloud is None or logged is None:
        return None
    satellite = SunsetCloud(
        cloud_cover=features["sat_cloud_cover_far"],
        cloud_cover_low=features["sat_cloud_cover_low_far"],
        cloud_cover_mid=features["sat_cloud_cover_mid_near"],
        cloud_cover_high=features["sat_cloud_cover_high_near"],
    )
    return {
        "base": calculate_sunset_score(inputs, cloud),
        "logged": logged,
        "final": _number(row, "final_sunset_score"),
        "c1": calculate_sunset_score(inputs, satellite),
        "c2": calculate_sunset_score(
            inputs, replace(satellite, cloud_cover=features["sat_path_max"])
        ),
        "c3": path_cap(logged, features["sat_path_mean"]),
    }


def load_label_csv(path: Path) -> dict[tuple[str, str], dict[str, float | None]]:
    labels: dict[tuple[str, str], dict[str, float | None]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            labels[(row["date"], row["slot"])] = {
                "sky": _number(row, "sky_color_score"),
                "gemini": _number(row, "gemini_score"),
            }
    return labels


def rankdata(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for position in range(start, end + 1):
            ranks[order[position]] = (start + end) / 2 + 1
        start = end + 1
    return ranks


def spearman(first: list[float], second: list[float]) -> float:
    if len(first) < 3:
        return math.nan
    a, b = rankdata(first), rankdata(second)
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    spread_a = math.sqrt(sum((x - mean_a) ** 2 for x in a))
    spread_b = math.sqrt(sum((y - mean_b) ** 2 for y in b))
    if spread_a == 0 or spread_b == 0:
        return math.nan
    return sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True)) / (
        spread_a * spread_b
    )


def auc(scores: list[float], positives: list[bool]) -> float:
    """鮮やかな日を上位に並べられるか(Mann-Whitney、同点は0.5)。"""
    pos = [score for score, flag in zip(scores, positives, strict=True) if flag]
    neg = [score for score, flag in zip(scores, positives, strict=True) if not flag]
    if not pos or not neg:
        return math.nan
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def bootstrap_delta(
    candidate: list[float], baseline: list[float], truth: list[float]
) -> tuple[float, float]:
    """Δρ(候補−基準)の日単位ペアブートストラップ95%CI。"""
    rng = random.Random(20261010)
    size = len(truth)
    deltas = []
    for _ in range(BOOTSTRAP_REPS):
        sample = [rng.randrange(size) for _ in range(size)]
        delta = spearman([candidate[i] for i in sample], [truth[i] for i in sample]) - spearman(
            [baseline[i] for i in sample], [truth[i] for i in sample]
        )
        if not math.isnan(delta):
            deltas.append(delta)
    deltas.sort()
    if not deltas:
        return math.nan, math.nan
    return deltas[int(0.025 * len(deltas))], deltas[int(0.975 * len(deltas)) - 1]


def _fmt(value: float | None, digits: int = 2, *, signed: bool = False) -> str:
    if value is None or math.isnan(value):
        return "–"
    return f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"


def paired_days(
    signals: dict[str, dict[str, float | None]],
    labels: dict[tuple[str, str], dict[str, float | None]],
    slot: str,
    label: str,
) -> list[tuple[str, dict[str, float | None], float]]:
    days = []
    for day, values in sorted(signals.items()):
        truth = labels.get((day, slot), {}).get(label)
        if truth is not None:
            days.append((day, values, truth))
    return days


def _vivid_flags(truths: list[float], label: str) -> list[bool]:
    if label == "gemini":
        return [truth >= GEMINI_VIVID for truth in truths]
    threshold = sorted(truths)[int(SKY_VIVID_QUANTILE * (len(truths) - 1))]
    return [truth > threshold for truth in truths]


def _delta(days, key: str, baseline: str) -> float:
    usable = [(values, truth) for _, values, truth in days if values[baseline] is not None]
    truths = [truth for _, truth in usable]
    return spearman([values[key] for values, _ in usable], truths) - spearman(
        [values[baseline] for values, _ in usable], truths
    )


def comparison_table(
    signals: dict[str, dict[str, float | None]],
    labels: dict[tuple[str, str], dict[str, float | None]],
    split_date: str,
) -> tuple[list[str], dict[tuple[str, str], str]]:
    """各枠・各ラベルの ρ・AUC と、候補の Δρ・判定。"""
    lines = [
        "| 枠 | ラベル | N | 鮮やか | "
        + " | ".join(f"ρ {SIGNAL_NAMES[key]}" for key in SIGNAL_NAMES)
        + " | "
        + " | ".join(f"Δρ {name} [95%CI] (前半/後半)" for name, _, _ in CANDIDATES)
        + " |",
        "|" + "---|" * (4 + len(SIGNAL_NAMES) + len(CANDIDATES)),
    ]
    auc_lines = [
        "| 枠 | ラベル | " + " | ".join(f"AUC {SIGNAL_NAMES[key]}" for key in SIGNAL_NAMES) + " |",
        "|" + "---|" * (2 + len(SIGNAL_NAMES)),
    ]
    checks: dict[tuple[str, str], list[tuple[bool, bool]]] = {}
    for slot, slot_name in SLOTS:
        for label, label_name in LABELS:
            days = paired_days(signals, labels, slot, label)
            if len(days) < 5:
                continue
            truths = [truth for _, _, truth in days]
            vivid = _vivid_flags(truths, label)
            rhos, aucs = [], []
            for key in SIGNAL_NAMES:
                usable = [
                    (values[key], truth, flag)
                    for (_, values, truth), flag in zip(days, vivid, strict=True)
                    if values[key] is not None
                ]
                rhos.append(_fmt(spearman([u[0] for u in usable], [u[1] for u in usable])))
                aucs.append(_fmt(auc([u[0] for u in usable], [u[2] for u in usable])))
            deltas = []
            for name, key, baseline in CANDIDATES:
                usable = [
                    (values, truth) for _, values, truth in days if values[baseline] is not None
                ]
                delta = _delta(days, key, baseline)
                low, high = bootstrap_delta(
                    [values[key] for values, _ in usable],
                    [values[baseline] for values, _ in usable],
                    [truth for _, truth in usable],
                )
                first = _delta([d for d in days if d[0] < split_date], key, baseline)
                second = _delta([d for d in days if d[0] >= split_date], key, baseline)
                interval = f"[{_fmt(low, signed=True)}, {_fmt(high, signed=True)}]"
                halves = f"({_fmt(first, signed=True)}/{_fmt(second, signed=True)})"
                deltas.append(f"{_fmt(delta, signed=True)} {interval} {halves}")
                consistent = delta > 0 and first > 0 and second > 0
                checks.setdefault((slot, name), []).append((consistent, low > 0))
            lines.append(
                f"| {slot_name} | {label_name} | {len(days)} | {sum(vivid)} | "
                + " | ".join(rhos)
                + " | "
                + " | ".join(deltas)
                + " |"
            )
            auc_lines.append(f"| {slot_name} | {label_name} | " + " | ".join(aucs) + " |")
    verdicts = {}
    for key, results in checks.items():
        promising = (
            len(results) == len(LABELS)
            and all(consistent for consistent, _ in results)
            and any(ci_clear for _, ci_clear in results)
        )
        verdicts[key] = "有望" if promising else "根拠なし"
    return lines + [""] + auc_lines, verdicts


def build_signals(
    rows: dict[str, dict[str, str]], features: dict[str, dict[str, float | None]]
) -> dict[str, dict[str, float | None]]:
    signals = {}
    for day, values in features.items():
        row = rows.get(day)
        if row is None:
            continue
        computed = day_signals(row, values)
        if computed is not None:
            signals[day] = computed
    return signals


def satellite_report(
    rows: dict[str, dict[str, str]],
    labels: dict[tuple[str, str], dict[str, float | None]],
    features_by_series: dict[str, dict[str, dict[str, float | None]]],
    sensitivity: dict[str, dict[str, dict[str, float | None]]],
    *,
    split_date: str,
) -> str:
    """事前登録した比較のMarkdownレポート。"""
    titles = {
        "t17": "T17(主): 16:50の衛星 — 本番17:00予測と同じ情報時点",
        "t60": "T60(副): 日没65分前までの最新の衛星",
        "t0": "T0(診断のみ): 日没時の衛星 — 観測そのものに情報があるかの上限",
    }
    out = [
        "# 衛星(ひまわり)実況の影の検証",
        "",
        "事前登録(2026-10-10)どおりの比較。ρ = Spearman 順位相関、Δρ = 候補 − 基準"
        "(C1・C2 は現行式+ログ雲量、C3 はログ純式)。CI は日単位ペアブートストラップ"
        f"{BOOTSTRAP_REPS}回。前半/後半 = {split_date} より前/以降。"
        f"鮮やか = Gemini ≥ {GEMINI_VIVID:g}、空の色は上位20%。",
        "判定「有望」= 両ラベルで Δρ・前半・後半とも正、かつ一方以上で CI 下限 > 0。"
        "どちらでも本番採用はこの結果だけでは行わない。",
        "",
    ]
    for series, title in titles.items():
        features = features_by_series.get(series)
        if not features:
            continue
        signals = build_signals(rows, features)
        lines, verdicts = comparison_table(signals, labels, split_date)
        out += [
            f"## {title}",
            "",
            f"衛星特徴のある日 {len(features)}、予測行と揃う日 " f"{len(signals)}。",
            "",
            *lines,
            "",
        ]
        if series != "t0":
            out += [
                "| 枠 | " + " | ".join(name for name, _, _ in CANDIDATES) + " |",
                "|" + "---|" * (1 + len(CANDIDATES)),
            ]
            for slot, slot_name in SLOTS:
                out.append(
                    f"| {slot_name} | "
                    + " | ".join(verdicts.get((slot, name), "–") for name, _, _ in CANDIDATES)
                    + " |"
                )
            out.append("")
    out += _diagnostics(features_by_series.get("t17", {}), labels, split_date)
    if sensitivity:
        out += [
            "## 感度分析(T17、選択には使わない): Δρ",
            "",
            "| 規則 | 枠 | ラベル | " + " | ".join(name for name, _, _ in CANDIDATES) + " |",
            "|" + "---|" * (3 + len(CANDIDATES)),
        ]
        for rule_name, features in sensitivity.items():
            signals = build_signals(rows, features)
            for slot, slot_name in SLOTS:
                for label, label_name in LABELS:
                    days = paired_days(signals, labels, slot, label)
                    if len(days) < 5:
                        continue
                    out.append(
                        f"| {rule_name} | {slot_name} | {label_name} | "
                        + " | ".join(
                            _fmt(_delta(days, key, baseline), signed=True)
                            for _, key, baseline in CANDIDATES
                        )
                        + " |"
                    )
        out.append("")
    return "\n".join(out)


def _diagnostics(
    features: dict[str, dict[str, float | None]],
    labels: dict[tuple[str, str], dict[str, float | None]],
    split_date: str,
) -> list[str]:
    if not features:
        return []
    out = [
        "## 診断(T17)",
        "",
        "下層雲判定率(%)の平均。陸上箱(丹沢)だけが高ければ、晴天参照による誤判定の疑い。",
        "",
        "| 期間 | N | 海上箱(相模湾) | 陸上箱(丹沢) | near箱の薄い巻雲疑い |",
        "|---|---|---|---|---|",
    ]
    for name, chosen in (
        ("全期間", list(features.items())),
        ("前半", [(d, f) for d, f in features.items() if d < split_date]),
        ("後半", [(d, f) for d, f in features.items() if d >= split_date]),
    ):

        def mean(key: str, chosen=chosen) -> float:
            values = [f[key] for _, f in chosen if f.get(key) is not None]
            return sum(values) / len(values) if values else math.nan

        out.append(
            f"| {name} | {len(chosen)} | {_fmt(mean('sat_low_sea'), 1)} | "
            f"{_fmt(mean('sat_low_land'), 1)} | {_fmt(mean('sat_cirrus_near'), 1)} |"
        )
    out += [
        "",
        "薄い巻雲疑い(B13で晴天・BT13−BT15≥2.5K)の割合と真値の ρ"
        "(本番式の上層雲ボーナスの対象を B13 が見落としているかの目安):",
        "",
    ]
    for slot, slot_name in SLOTS:
        for label, label_name in LABELS:
            pairs = [
                (f["sat_cirrus_near"], labels[(d, slot)][label])
                for d, f in features.items()
                if f.get("sat_cirrus_near") is not None
                and labels.get((d, slot), {}).get(label) is not None
            ]
            if len(pairs) >= 5:
                out.append(
                    f"- {slot_name}・{label_name}: N={len(pairs)}, ρ="
                    f"{_fmt(spearman([p[0] for p in pairs], [p[1] for p in pairs]))}"
                )
    out.append("")
    return out


def write_days_csv(
    path: Path,
    rows: dict[str, dict[str, str]],
    labels: dict[tuple[str, str], dict[str, float | None]],
    features: dict[str, dict[str, float | None]],
) -> None:
    """日ごとの入力・信号・真値(目視確認用)。"""
    signals = build_signals(rows, features)
    out = []
    for day, values in sorted(signals.items()):
        record: dict[str, object] = {"date": day, **features[day], **values}
        for slot, _ in SLOTS:
            for label, _ in LABELS:
                record[f"{slot}_{label}"] = labels.get((day, slot), {}).get(label)
        out.append(record)
    write_csv(path, out)
