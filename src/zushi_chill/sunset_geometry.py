"""日没方位と、その方角の観測地点を求める幾何ユーティリティ。

Sunset期待度は「陽が沈む方角(西の水平線)の雲」で決まる。逗子海岸の真上の雲
(Chill指数が使う値)ではなく、日没方位へ一定距離離れた地点の雲量を使うために、
当日の日没方位角と、そこへ ``offset_km`` 離れた地点の緯度経度を算出する。

日没方位は季節で大きく動く(逗子で夏至≈299°、冬至≈241°)ため、固定値ではなく
日付から都度計算する。方位計算は太陽赤緯の近似で足りる(格子解像度≈11kmに対し
数度の誤差は無視できる)。外部APIには依存しない。
"""

from __future__ import annotations

import math
from datetime import date

EARTH_RADIUS_KM = 6371.0


def solar_declination_deg(target_date: date) -> float:
    """太陽赤緯(度)の近似。春分(通日81)を基準にした正弦近似。"""
    day_of_year = target_date.timetuple().tm_yday
    return 23.44 * math.sin(math.radians(360.0 / 365.0 * (day_of_year - 81)))


def sunset_azimuth_deg(target_date: date, latitude: float) -> float:
    """日没方位角(真北基準・時計回り、度)を返す。

    地平線(高度0)での方位角 ``A`` は cos(A) = sin(decl) / cos(lat)。これは日の出
    (東側)の方位で、日没は西側なので ``360 - A`` を返す。高緯度で白夜に近い等の
    退化ケースでは cos をクランプする。
    """
    decl = math.radians(solar_declination_deg(target_date))
    lat = math.radians(latitude)
    cos_a = math.sin(decl) / math.cos(lat)
    cos_a = max(-1.0, min(1.0, cos_a))
    sunrise_azimuth = math.degrees(math.acos(cos_a))
    return 360.0 - sunrise_azimuth


def offset_point(
    latitude: float, longitude: float, bearing_deg: float, distance_km: float
) -> tuple[float, float]:
    """``(latitude, longitude)`` から方位 ``bearing_deg`` へ ``distance_km`` 離れた地点。"""
    bearing = math.radians(bearing_deg)
    lat1 = math.radians(latitude)
    lon1 = math.radians(longitude)
    angular = distance_km / EARTH_RADIUS_KM

    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular)
        + math.cos(lat1) * math.sin(angular) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular) * math.cos(lat1),
        math.cos(angular) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def sunset_cloud_point(
    latitude: float, longitude: float, target_date: date, offset_km: float
) -> tuple[float, float]:
    """当日の日没方位へ ``offset_km`` 離れた、Sunset期待度用の雲観測地点。"""
    bearing = sunset_azimuth_deg(target_date, latitude)
    return offset_point(latitude, longitude, bearing, offset_km)
