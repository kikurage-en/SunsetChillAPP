"""本番の予測と並行する影の検証(shadow)用コマンド。

本番のスコア・LINE通知・保存には一切触れない。前向きにしか集められない入力を記録し、
後からオフラインで既存の予測と比較するために使う。

- ``labels``: Pagesに保存した日没時・残照の画像から、空の領域の夕焼け色(``sky_color``)を
  計算し、Geminiの採点と並べたCSVを作る。予測扱いで採点が欠けた日没時の画像も含む。
- ``log``: 当日の日没窓について、ECMWF/GFS/ICONのアンサンブル予報と、気象庁・ECMWF・
  GFS・ICONの決定論予報を本番と同じ地点(逗子、日没方位の20/40km、50〜100km)で取得し、
  JSONで保存する。Open-Meteoの過去予報APIは各ランの初期時刻付近をつないだ値で、
  アンサンブルは過去日を取得できないため、予測時点に実際に使えた値はこの記録でしか残らない。
- ``satellite``: ひまわり赤外(B13、t17系列はB15も)の輝度温度を日没方位の格子で保存する。
  AWSに保存され続けるので、過去の期間をまとめて作れる。
- ``evaluate``: 衛星の雲特徴で作った事前登録の候補を、既存の予測(ログ)とラベルに対して比べ、
  Markdownのレポートを書く。
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from zushi_chill.config import Settings
from zushi_chill.main import SUNSET_CLOUD_PATH_DISTANCES_KM
from zushi_chill.shadow_eval import (
    build_labels,
    forecast_rows,
    load_label_csv,
    load_rows,
    satellite_report,
    write_csv,
    write_days_csv,
)
from zushi_chill.shadow_satellite import (
    SERIES,
    CloudRule,
    build_features,
    load_records,
    record_satellite,
)
from zushi_chill.solar_schedule import local_sunset_time
from zushi_chill.sunset_geometry import sunset_azimuth_deg, sunset_cloud_point

LOGGER = logging.getLogger(__name__)

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
CLOUD_FIELDS = ("cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high")
ENSEMBLE_MODELS = ("ecmwf_ifs025", "gfs025", "icon_seamless")
DETERMINISTIC_MODELS = ("jma_seamless", "ecmwf_ifs025", "gfs_seamless", "icon_seamless")
DEFAULT_SHADOW_DIR = "/var/lib/zushi-chill/shadow"

Fetch = Callable[[str], Any]


def shadow_points(settings: Settings, target_date: date) -> list[dict[str, float | str]]:
    """本番と同じ地点: 逗子、近地点(中・高層雲)、遠地点(低層雲・総雲量)、経路上の地点。"""
    distances: list[tuple[str, float]] = [
        ("near", settings.sunset_cloud_near_offset_km),
        ("far", settings.sunset_cloud_offset_km),
        *(
            (f"path{distance:g}", distance)
            for distance in SUNSET_CLOUD_PATH_DISTANCES_KM
            if distance > settings.sunset_cloud_offset_km
        ),
    ]
    points: list[dict[str, float | str]] = [
        {
            "name": "zushi",
            "distance_km": 0.0,
            "latitude": settings.latitude,
            "longitude": settings.longitude,
        }
    ]
    for name, distance in distances:
        if distance <= 0:
            continue
        latitude, longitude = sunset_cloud_point(
            settings.latitude, settings.longitude, target_date, distance
        )
        points.append(
            {
                "name": name,
                "distance_km": distance,
                "latitude": round(latitude, 4),
                "longitude": round(longitude, 4),
            }
        )
    return points


def build_url(
    base_url: str,
    points: list[dict[str, float | str]],
    *,
    models: tuple[str, ...],
    target_date: date,
    timezone: str,
) -> str:
    params = {
        "latitude": ",".join(f"{point['latitude']}" for point in points),
        "longitude": ",".join(f"{point['longitude']}" for point in points),
        "hourly": ",".join(CLOUD_FIELDS),
        "models": ",".join(models),
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "timezone": timezone,
    }
    return f"{base_url}?{urlencode(params)}"


def fetch_json(url: str, *, timeout: int = 60, retries: int = 3) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urlopen(url, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(5 * attempt)
    raise RuntimeError(f"Open-Meteo shadow fetch failed: {last_error}") from last_error


def log_forecasts(
    settings: Settings,
    *,
    target_date: date,
    shadow_dir: Path,
    now: datetime,
    fetch: Fetch = fetch_json,
) -> list[Path]:
    """当日の日没窓の予報を取得し、取得時刻つきのJSONとして保存する。"""
    points = shadow_points(settings, target_date)
    sunset = local_sunset_time(
        target_date=target_date,
        latitude=settings.latitude,
        longitude=settings.longitude,
        timezone=settings.timezone,
    )
    meta = {
        "date": target_date.isoformat(),
        "fetched_at": now.isoformat(timespec="seconds"),
        "sunset": sunset.isoformat(timespec="minutes"),
        "sunset_azimuth_deg": round(sunset_azimuth_deg(target_date, settings.latitude), 2),
        "points": points,
    }
    directory = shadow_dir / target_date.isoformat()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%H%M")
    written: list[Path] = []
    for kind, base_url, models in (
        ("ensemble", ENSEMBLE_URL, ENSEMBLE_MODELS),
        ("deterministic", FORECAST_URL, DETERMINISTIC_MODELS),
    ):
        url = build_url(
            base_url,
            points,
            models=models,
            target_date=target_date,
            timezone=settings.timezone,
        )
        try:
            payload = fetch(url)
        except Exception as exc:
            # 片方の取得失敗で、もう片方の記録まで失わない。
            LOGGER.warning("Shadow %s fetch failed: %s", kind, exc)
            continue
        path = directory / f"{kind}-{stamp}.json.gz"
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(
            gzip.compress(
                json.dumps(
                    {**meta, "kind": kind, "models": models, "url": url, "payload": payload}
                ).encode("utf-8")
            )
        )
        os.replace(temporary, path)
        written.append(path)
        LOGGER.info("Saved shadow %s forecast to %s", kind, path)
    return written


def record_satellite_range(
    settings: Settings,
    *,
    start: date,
    end: date,
    series: tuple[str, ...],
    cirrus_series: tuple[str, ...],
    shadow_dir: Path,
    workers: int,
) -> int:
    """期間内の各日・各系列の衛星格子を保存し、保存できた件数を返す。"""
    tasks = [
        (start + timedelta(days=offset), name)
        for offset in range((end - start).days + 1)
        for name in series
    ]

    def run(task: tuple[date, str]) -> bool:
        target_date, name = task
        try:
            path = record_satellite(
                settings,
                target_date=target_date,
                series=name,
                shadow_dir=shadow_dir,
                cirrus=name in cirrus_series,
            )
        except Exception as exc:
            LOGGER.warning("Satellite %s %s failed: %s", target_date, name, exc)
            return False
        return path is not None

    with ThreadPoolExecutor(max_workers=workers) as executor:
        saved = sum(executor.map(run, tasks))
    LOGGER.info("Saved %d/%d satellite grids under %s", saved, len(tasks), shadow_dir)
    return saved


def evaluate(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    shadow_dir = Path(args.shadow_dir)
    rows = forecast_rows(load_rows(Path(args.predictions)))
    labels = load_label_csv(Path(args.labels))
    records = {series: load_records(shadow_dir, series) for series in SERIES}
    rule = CloudRule()
    features = {series: build_features(records[series], settings, rule) for series in SERIES}
    # 感度分析は事前登録した変化幅だけ。候補の選択には使わない。
    sensitivity = {
        name: build_features(records["t17"], settings, variant)
        for name, variant in (
            ("ΔT=3K", replace(rule, clear_margin_k=3.0)),
            ("ΔT=7K", replace(rule, clear_margin_k=7.0)),
            ("箱±0.03°", replace(rule, box_deg=0.03)),
            ("箱±0.08°", replace(rule, box_deg=0.08)),
        )
    }
    report = satellite_report(rows, labels, features, sensitivity, split_date=args.split_date)
    Path(args.out).write_text(report + "\n", encoding="utf-8")
    if args.days_out:
        write_days_csv(Path(args.days_out), rows, labels, features["t17"])
    LOGGER.info("Wrote satellite shadow report to %s", args.out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Shadow-validation logging (log-only).")
    subcommands = parser.add_subparsers(dest="command", required=True)
    log_parser = subcommands.add_parser("log", help="Save today's forecasts for later comparison.")
    log_parser.add_argument("--date", help="Target date YYYY-MM-DD (default: today).")
    log_parser.add_argument(
        "--shadow-dir",
        default=os.getenv("SHADOW_DIR", DEFAULT_SHADOW_DIR),
        help="Directory for shadow logs.",
    )
    labels_parser = subcommands.add_parser(
        "labels", help="Score archived camera images with the sky-colour label."
    )
    labels_parser.add_argument("--predictions", required=True, help="Prediction log CSV.")
    labels_parser.add_argument(
        "--images-dir",
        required=True,
        help="Checkout of the pages-images branch (contains live-camera/).",
    )
    labels_parser.add_argument("--out", required=True, help="Output CSV path.")
    satellite_parser = subcommands.add_parser(
        "satellite", help="Save Himawari infrared grids along the sunset path."
    )
    satellite_parser.add_argument("--start", help="First date YYYY-MM-DD (default: today).")
    satellite_parser.add_argument("--end", help="Last date YYYY-MM-DD (default: --start).")
    satellite_parser.add_argument(
        "--series", default=",".join(SERIES), help="Comma-separated: t17,t60,t0."
    )
    satellite_parser.add_argument(
        "--cirrus-series", default="t17", help="Series that also save band 15."
    )
    satellite_parser.add_argument("--workers", type=int, default=6)
    satellite_parser.add_argument(
        "--shadow-dir",
        default=os.getenv("SHADOW_DIR", DEFAULT_SHADOW_DIR),
        help="Directory for shadow logs.",
    )
    evaluate_parser = subcommands.add_parser(
        "evaluate", help="Compare satellite-based candidates with the logged predictions."
    )
    evaluate_parser.add_argument("--predictions", required=True, help="Prediction log CSV.")
    evaluate_parser.add_argument("--labels", required=True, help="CSV from the labels command.")
    evaluate_parser.add_argument(
        "--shadow-dir",
        default=os.getenv("SHADOW_DIR", DEFAULT_SHADOW_DIR),
        help="Directory for shadow logs.",
    )
    evaluate_parser.add_argument("--out", required=True, help="Markdown report path.")
    evaluate_parser.add_argument("--days-out", help="Optional per-day CSV (t17 series).")
    evaluate_parser.add_argument(
        "--split-date", default="2026-09-01", help="First date of the second half."
    )
    args = parser.parse_args(argv)

    if args.command == "evaluate":
        logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
        return evaluate(args)
    if args.command == "labels":
        logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
        labels = build_labels(load_rows(Path(args.predictions)), Path(args.images_dir))
        write_csv(Path(args.out), labels)
        LOGGER.info("Wrote %d image labels to %s", len(labels), args.out)
        return 0

    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
    )
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    if args.command == "satellite":
        start = date.fromisoformat(args.start) if args.start else now.date()
        end = date.fromisoformat(args.end) if args.end else start
        series = tuple(name for name in args.series.split(",") if name)
        unknown = set(series) - set(SERIES)
        if unknown:
            parser.error(f"Unknown series: {', '.join(sorted(unknown))}")
        saved = record_satellite_range(
            settings,
            start=start,
            end=end,
            series=series,
            cirrus_series=tuple(args.cirrus_series.split(",")),
            shadow_dir=Path(args.shadow_dir),
            workers=args.workers,
        )
        return 0 if saved else 1
    target_date = date.fromisoformat(args.date) if args.date else now.date()
    written = log_forecasts(
        settings,
        target_date=target_date,
        shadow_dir=Path(args.shadow_dir),
        now=now,
    )
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
