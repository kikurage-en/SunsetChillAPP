"""影の検証: ひまわり赤外の実況を日没方位の格子で記録し、事前登録した雲特徴を作る。

予報ではなく衛星の実況で日没方位の雲を見たとき、既存の予報雲量より夕焼けを当てられるかを
後から比べる。画像はAWSに保存され続けるので前向きに記録する必要はなく、過去分をいつでも
作れる。判定の閾値は2026-10-10に結果を見る前に固定した(STATUS「衛星実況の影の検証」)。
赤外は最上層の雲しか見えないため、上層雲の下の下層雲は数えられない。
"""

from __future__ import annotations

import gzip
import json
import logging
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from zushi_chill.config import Settings
from zushi_chill.himawari import HimawariImage, download, read_hsd, scan_url, timeline_floor
from zushi_chill.main import SUNSET_CLOUD_PATH_DISTANCES_KM
from zushi_chill.solar_schedule import local_sunset_time
from zushi_chill.sunset_geometry import sunset_cloud_point

LOGGER = logging.getLogger(__name__)

# 日没方位(冬241°〜夏300°)の0〜100kmと、診断用の固定箱を覆う緯度経度格子。
GRID_SOUTH = 34.70
GRID_WEST = 138.40
GRID_STEP = 0.02
GRID_ROWS = 61  # 34.70〜35.90
GRID_COLUMNS = 71  # 138.40〜139.80
# 晴天参照の誤判定を海と陸で比べる診断用の固定箱(相模湾中央・丹沢)。
SEA_BOX = (35.15, 139.40)
LAND_BOX = (35.45, 139.15)
CLOUD_BAND = 13
CIRRUS_BAND = 15
SERIES = ("t17", "t60", "t0")

Download = Callable[[str], bytes]


@dataclass(frozen=True)
class CloudRule:
    """2026-10-10に事前登録した雲判定。感度分析以外で値を変えない。"""

    clear_margin_k: float = 5.0
    box_deg: float = 0.05
    history_days: int = 15
    min_history_days: int = 10
    high_below_k: float = 255.0
    mid_below_k: float = 273.0
    cirrus_split_k: float = 2.5


def series_timeline(series: str, target_date: date, sunset: datetime) -> datetime:
    """時刻系列のタイムライン(UTC)。

    t17: 本番の17:00予測と同じ情報時点(16:50)。t60: 日没60分前の予測で使える最新
    (取得遅延5分)。t0: 日没に最も近い(観測そのものに情報があるかの診断用)。
    """
    if series == "t17":
        return timeline_floor(datetime.combine(target_date, time(16, 50), tzinfo=sunset.tzinfo))
    if series == "t60":
        return timeline_floor(sunset - timedelta(minutes=65))
    if series == "t0":
        return timeline_floor(sunset + timedelta(minutes=5))
    raise ValueError(f"Unknown satellite series: {series}")


def grid_index(row: int, column: int) -> int:
    return row * GRID_COLUMNS + column


def grid_point(row: int, column: int) -> tuple[float, float]:
    return round(GRID_SOUTH + row * GRID_STEP, 4), round(GRID_WEST + column * GRID_STEP, 4)


def sample_grid(image: HimawariImage) -> list[float | None]:
    values: list[float | None] = []
    for row in range(GRID_ROWS):
        for column in range(GRID_COLUMNS):
            value = image.brightness_temperature(*grid_point(row, column))
            values.append(None if value is None else round(value, 2))
    return values


def record_path(shadow_dir: Path, series: str, target_date: date) -> Path:
    return shadow_dir / "satellite" / series / f"{target_date.isoformat()}.json.gz"


def record_satellite(
    settings: Settings,
    *,
    target_date: date,
    series: str,
    shadow_dir: Path,
    cirrus: bool,
    fetch: Download = download,
) -> Path | None:
    """その日・系列の輝度温度格子を保存する。既にあれば取得しない。欠測タイムラインは None。"""
    path = record_path(shadow_dir, series, target_date)
    if path.exists():
        return path
    sunset = local_sunset_time(
        target_date=target_date,
        latitude=settings.latitude,
        longitude=settings.longitude,
        timezone=settings.timezone,
    )
    timeline = series_timeline(series, target_date, sunset)
    record: dict[str, Any] = {
        "date": target_date.isoformat(),
        "series": series,
        "timeline": timeline.isoformat(),
        "sunset": sunset.isoformat(timespec="minutes"),
        "grid": {
            "south": GRID_SOUTH,
            "west": GRID_WEST,
            "step": GRID_STEP,
            "rows": GRID_ROWS,
            "columns": GRID_COLUMNS,
        },
    }
    for band in (CLOUD_BAND, CIRRUS_BAND) if cirrus else (CLOUD_BAND,):
        url = scan_url(timeline, band)
        try:
            image = read_hsd(fetch(url))
        except FileNotFoundError:
            LOGGER.warning("Himawari scan missing: %s", url)
            if band == CLOUD_BAND:
                return None
            continue
        record[f"b{band}"] = sample_grid(image)
        record[f"b{band}_observation_start"] = image.observation_start.isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(gzip.compress(json.dumps(record).encode("utf-8")))
    os.replace(temporary, path)
    return path


def load_records(shadow_dir: Path, series: str) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in sorted((shadow_dir / "satellite" / series).glob("*.json.gz")):
        record = json.loads(gzip.decompress(path.read_bytes()))
        records[record["date"]] = record
    return records


def clear_reference(
    records: dict[str, dict[str, Any]], target_date: date, rule: CloudRule
) -> list[float | None] | None:
    """各格子点の晴天参照 = 前日までの history_days 日の B13 最大値。日数不足なら None。"""
    history = []
    for days_before in range(1, rule.history_days + 1):
        record = records.get((target_date - timedelta(days=days_before)).isoformat())
        if record is not None:
            history.append(record["b13"])
    if len(history) < rule.min_history_days:
        return None
    reference: list[float | None] = []
    for values in zip(*history, strict=True):
        present = [value for value in values if value is not None]
        reference.append(max(present) if present else None)
    return reference


def cloud_layer(value: float | None, reference: float | None, rule: CloudRule) -> str | None:
    """雲頂の層。晴天参照より clear_margin_k 以上冷たい画素を雲とし、雲頂温度で分ける。"""
    if value is None or reference is None:
        return None
    if value >= reference - rule.clear_margin_k:
        return "clear"
    if value < rule.high_below_k:
        return "high"
    if value < rule.mid_below_k:
        return "mid"
    return "low"


def box_indices(latitude: float, longitude: float, box_deg: float) -> list[int]:
    """中心から緯度・経度とも ±box_deg 以内の格子点。"""
    first_row = max(0, math.ceil((latitude - box_deg - GRID_SOUTH) / GRID_STEP - 1e-6))
    last_row = min(GRID_ROWS - 1, math.floor((latitude + box_deg - GRID_SOUTH) / GRID_STEP + 1e-6))
    first_column = max(0, math.ceil((longitude - box_deg - GRID_WEST) / GRID_STEP - 1e-6))
    last_column = min(
        GRID_COLUMNS - 1, math.floor((longitude + box_deg - GRID_WEST) / GRID_STEP + 1e-6)
    )
    return [
        grid_index(row, column)
        for row in range(first_row, last_row + 1)
        for column in range(first_column, last_column + 1)
    ]


def box_cloud(
    record: dict[str, Any],
    reference: list[float | None],
    latitude: float,
    longitude: float,
    rule: CloudRule,
) -> dict[str, float] | None:
    """箱内の雲画素の割合(%)を、本番の層別雲量と同じ名前で返す。"""
    layers = [
        cloud_layer(record["b13"][index], reference[index], rule)
        for index in box_indices(latitude, longitude, rule.box_deg)
    ]
    valid = [layer for layer in layers if layer is not None]
    if not valid:
        return None

    def share(*names: str) -> float:
        return round(100.0 * sum(layer in names for layer in valid) / len(valid), 1)

    return {
        "cloud_cover": share("low", "mid", "high"),
        "cloud_cover_low": share("low"),
        "cloud_cover_mid": share("mid"),
        "cloud_cover_high": share("high"),
    }


def cirrus_share(
    record: dict[str, Any],
    reference: list[float | None],
    latitude: float,
    longitude: float,
    rule: CloudRule,
) -> float | None:
    """B13では晴天だが BT13−BT15 が大きい(薄い巻雲の疑い)画素の割合(%)。診断専用。"""
    if "b15" not in record:
        return None
    flags = []
    for index in box_indices(latitude, longitude, rule.box_deg):
        b13, b15 = record["b13"][index], record["b15"][index]
        layer = cloud_layer(b13, reference[index], rule)
        if layer is None or b15 is None:
            continue
        flags.append(layer == "clear" and b13 - b15 >= rule.cirrus_split_k)
    if not flags:
        return None
    return round(100.0 * sum(flags) / len(flags), 1)


def day_features(
    record: dict[str, Any],
    reference: list[float | None],
    settings: Settings,
    rule: CloudRule,
) -> dict[str, float | None] | None:
    """本番と同じ地点(近地点・遠地点・経路)の衛星雲量と診断値。必要な箱が欠ければ None。"""
    target_date = date.fromisoformat(record["date"])

    def at_distance(distance_km: float) -> dict[str, float] | None:
        latitude, longitude = sunset_cloud_point(
            settings.latitude, settings.longitude, target_date, distance_km
        )
        return box_cloud(record, reference, latitude, longitude, rule)

    near = at_distance(settings.sunset_cloud_near_offset_km)
    far = at_distance(settings.sunset_cloud_offset_km)
    path = [far] + [
        at_distance(distance)
        for distance in SUNSET_CLOUD_PATH_DISTANCES_KM
        if distance > settings.sunset_cloud_offset_km
    ]
    if near is None or far is None or any(box is None for box in path):
        return None
    path_cover = [box["cloud_cover"] for box in path if box is not None]
    sea = box_cloud(record, reference, *SEA_BOX, rule)
    land = box_cloud(record, reference, *LAND_BOX, rule)
    near_lat, near_lon = sunset_cloud_point(
        settings.latitude, settings.longitude, target_date, settings.sunset_cloud_near_offset_km
    )
    return {
        "sat_cloud_cover_far": far["cloud_cover"],
        "sat_cloud_cover_low_far": far["cloud_cover_low"],
        "sat_cloud_cover_mid_near": near["cloud_cover_mid"],
        "sat_cloud_cover_high_near": near["cloud_cover_high"],
        "sat_path_max": max(path_cover),
        "sat_path_mean": round(sum(path_cover) / len(path_cover), 1),
        "sat_low_sea": None if sea is None else sea["cloud_cover_low"],
        "sat_low_land": None if land is None else land["cloud_cover_low"],
        "sat_cirrus_near": cirrus_share(record, reference, near_lat, near_lon, rule),
    }


def build_features(
    records: dict[str, dict[str, Any]], settings: Settings, rule: CloudRule
) -> dict[str, dict[str, float | None]]:
    features: dict[str, dict[str, float | None]] = {}
    for day, record in sorted(records.items()):
        reference = clear_reference(records, date.fromisoformat(day), rule)
        if reference is None:
            continue
        values = day_features(record, reference, settings, rule)
        if values is not None:
            features[day] = values
    return features
