from __future__ import annotations

import bz2
import math
import struct
from datetime import UTC, datetime

from zushi_chill.himawari import (
    OUTSIDE_COUNT,
    geo_to_image,
    read_hsd,
    scan_url,
    timeline_floor,
)

# 2026-08-01 08:00 B13 JP01 の実ヘッダー値。
SUB_LON = 140.7
CFAC = LFAC = 20466275
SLOPE = -0.0037525074318633814
INTERCEPT = 15.197657722429469
C0, C1, C2 = -0.118260812197365, 1.00101143081895, -1.80800453227613e-06
LIGHT, PLANCK, BOLTZMANN = 299792458.0, 6.62606957e-34, 1.3806488e-23
WAVELENGTH = 10.4074
HEADER = 1543
ZUSHI = (35.2938, 139.5786)


def _hsd(columns: int, lines: int, coff: float, loff: float, counts: list[int]) -> bytes:
    """仕様書 Table 6 の位置に必要な欄だけを書いた最小のHSD(リトルエンディアン)。"""
    data = bytearray(HEADER)
    for block, offset in ((1, 0), (2, 282), (3, 332), (5, 598), (7, 1004)):
        data[offset] = block
    struct.pack_into("<d", data, 46, 61253.3335)
    struct.pack_into("<I", data, 70, HEADER)
    struct.pack_into("<HH", data, 282 + 5, columns, lines)
    struct.pack_into("<dIIff", data, 332 + 3, SUB_LON, CFAC, LFAC, coff, loff)
    struct.pack_into("<Hd", data, 598 + 3, 13, WAVELENGTH)
    struct.pack_into("<dd", data, 598 + 19, SLOPE, INTERCEPT)
    struct.pack_into("<ddd", data, 598 + 35, C0, C1, C2)
    struct.pack_into("<ddd", data, 598 + 83, LIGHT, PLANCK, BOLTZMANN)
    struct.pack_into("<H", data, 1004 + 5, 1)
    return bytes(data) + struct.pack(f"<{len(counts)}H", *counts)


def _count_for(temperature: float) -> int:
    """輝度温度(c0〜c2 は恒等に近いので無視)に対応するカウント。"""
    wavelength = WAVELENGTH * 1e-6
    radiance = (2 * PLANCK * LIGHT**2 / wavelength**5) / (
        math.exp(PLANCK * LIGHT / (BOLTZMANN * wavelength * temperature)) - 1
    )
    return round((radiance / 1e6 - INTERCEPT) / SLOPE)


def test_projection_maps_the_sub_satellite_point_to_the_image_centre():
    column, line = geo_to_image(
        0.0, SUB_LON, sub_lon=SUB_LON, cfac=CFAC, lfac=LFAC, coff=1075.5, loff=2300.5
    )
    assert (column, line) == (1075.5, 2300.5)
    # 北・東ほど行が小さく列が大きい。
    north_column, north_line = geo_to_image(
        *ZUSHI, sub_lon=SUB_LON, cfac=CFAC, lfac=LFAC, coff=1075.5, loff=2300.5
    )
    assert north_line < 2300.5
    assert north_column < 1075.5  # 逗子は衛星直下(140.7E)より西


def test_read_hsd_samples_the_pixel_and_calibrates_to_brightness_temperature():
    # 逗子が 3x3 画像の中央(1始まりで列2・行2)に来るよう COFF/LOFF を決める。
    column, line = geo_to_image(*ZUSHI, sub_lon=SUB_LON, cfac=CFAC, lfac=LFAC, coff=0, loff=0)
    counts = [OUTSIDE_COUNT] * 9
    counts[4] = _count_for(290.0)
    image = read_hsd(bz2.compress(_hsd(3, 3, 2 - column, 2 - line, counts)))

    assert image.pixel(*ZUSHI) == (1, 1)
    assert math.isclose(image.brightness_temperature(*ZUSHI), 290.0, abs_tol=0.5)
    assert image.observation_start.date().isoformat() == "2026-08-01"
    # 走査範囲外のカウントと、画像の外は None。
    assert image.brightness_temperature(ZUSHI[0] + 0.03, ZUSHI[1]) is None
    assert image.brightness_temperature(ZUSHI[0] + 1.0, ZUSHI[1]) is None


def test_scan_url_and_timeline_follow_the_aws_layout():
    moment = datetime(2026, 10, 9, 16, 59, tzinfo=UTC)
    timeline = timeline_floor(moment)
    assert timeline == datetime(2026, 10, 9, 16, 50, tzinfo=UTC)
    assert scan_url(timeline, 13) == (
        "https://noaa-himawari9.s3.amazonaws.com/AHI-L1b-Japan/2026/10/09/1650/"
        "HS_H09_20261009_1650_B13_JP01_R20_S0101.DAT.bz2"
    )
