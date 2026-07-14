from __future__ import annotations

import math
from datetime import date

from zushi_chill.sunset_geometry import (
    offset_point,
    sunset_azimuth_deg,
    sunset_cloud_point,
)

ZUSHI_LAT = 35.2956
ZUSHI_LON = 139.5736


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def test_sunset_azimuth_tracks_season_at_zushi():
    """逗子の日没方位は夏至にWNW(≈299°)、冬至にWSW(≈241°)へ動く。

    固定方位でサンプルすると季節で狙いがずれるため、日付から都度計算する根拠。
    """
    summer = sunset_azimuth_deg(date(2026, 6, 21), ZUSHI_LAT)
    midjuly = sunset_azimuth_deg(date(2026, 7, 12), ZUSHI_LAT)
    winter = sunset_azimuth_deg(date(2026, 12, 21), ZUSHI_LAT)

    assert 297 <= summer <= 301
    assert 296 <= midjuly <= 300
    assert 238 <= winter <= 244
    # 夏は北寄り(西より大きい方位)、冬は南寄り
    assert summer > midjuly > winter


def test_offset_point_is_the_requested_distance_and_bearing():
    dest_lat, dest_lon = offset_point(ZUSHI_LAT, ZUSHI_LON, 298.0, 40.0)
    # 距離が約40km
    assert abs(_haversine_km(ZUSHI_LAT, ZUSHI_LON, dest_lat, dest_lon) - 40.0) < 0.5
    # WNW(298°)なので北かつ西へ動く
    assert dest_lat > ZUSHI_LAT
    assert dest_lon < ZUSHI_LON


def test_sunset_cloud_point_is_west_of_zushi_in_summer():
    lat, lon = sunset_cloud_point(ZUSHI_LAT, ZUSHI_LON, date(2026, 7, 12), 40.0)
    assert abs(_haversine_km(ZUSHI_LAT, ZUSHI_LON, lat, lon) - 40.0) < 0.5
    # 夏の日没方位(WNW)へ離れる=逗子より西
    assert lon < ZUSHI_LON
    assert lat > ZUSHI_LAT
