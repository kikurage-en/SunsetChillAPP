"""本番の予測と並行する影の検証(shadow)用コマンド。

本番のスコア・LINE通知・保存には一切触れない。前向きにしか集められない入力を記録し、
後からオフラインで既存の予測と比較するために使う。

- ``log``: 当日の日没窓について、ECMWF/GFS/ICONのアンサンブル予報と、気象庁・ECMWF・
  GFS・ICONの決定論予報を本番と同じ地点(逗子、日没方位の20/40km、50〜100km)で取得し、
  JSONで保存する。Open-Meteoの過去予報APIは各ランの初期時刻付近をつないだ値で、
  アンサンブルは過去日を取得できないため、予測時点に実際に使えた値はこの記録でしか残らない。
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
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from zushi_chill.config import Settings
from zushi_chill.main import SUNSET_CLOUD_PATH_DISTANCES_KM
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
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
    )
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
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
