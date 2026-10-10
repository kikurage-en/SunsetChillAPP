"""ひまわり標準データ(HSD)の最小リーダー。赤外バンドの輝度温度を緯度経度で引く。

影の検証で、日没方位の雲を予報ではなく衛星の実況で見るために使う。依存を増やさない
ため標準ライブラリだけで読む。ヘッダーの位置・型は気象庁「Himawari Standard Data
User's Guide」v1.3 の Table 6、地図投影は同書3章が参照する CGMS「LRIT/HRIT Global
Specification」4.4 の正規化静止衛星投影に従う。データは JMA が作成し NOAA が AWS
(noaa-himawari9、アカウント不要)で配信しているものを使う。
"""

from __future__ import annotations

import bz2
import math
import struct
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

AWS_JAPAN_URL = "https://noaa-himawari9.s3.amazonaws.com/AHI-L1b-Japan"
MJD_EPOCH = datetime(1858, 11, 17, tzinfo=UTC)
# 各ヘッダーブロックの長さ(Table 6 の固定値)。ブロック10だけ長さ欄が4バイト。
_BLOCK1, _BLOCK2, _BLOCK3, _BLOCK5, _BLOCK7 = 0, 282, 332, 598, 1004
ERROR_COUNT = 65535
OUTSIDE_COUNT = 65534


@dataclass(frozen=True)
class HimawariImage:
    band: int
    wavelength_um: float
    observation_start: datetime
    columns: int
    lines: int
    first_line: int
    sub_lon: float
    cfac: int
    lfac: int
    coff: float
    loff: float
    slope: float
    intercept: float
    c0: float
    c1: float
    c2: float
    light_speed: float
    planck: float
    boltzmann: float
    counts: bytes
    byte_order: str

    def pixel(self, latitude: float, longitude: float) -> tuple[int, int] | None:
        """緯度経度を画像の(列, 行)へ。0始まり。範囲外・地球外なら None。"""
        column, line = geo_to_image(
            latitude,
            longitude,
            sub_lon=self.sub_lon,
            cfac=self.cfac,
            lfac=self.lfac,
            coff=self.coff,
            loff=self.loff,
        )
        col_index = round(column) - 1
        line_index = round(line) - self.first_line
        if not (0 <= col_index < self.columns and 0 <= line_index < self.lines):
            return None
        return col_index, line_index

    def brightness_temperature(self, latitude: float, longitude: float) -> float | None:
        """その地点の輝度温度[K]。欠測・走査範囲外は None。"""
        position = self.pixel(latitude, longitude)
        if position is None:
            return None
        column, line = position
        offset = (line * self.columns + column) * 2
        (count,) = struct.unpack(self.byte_order + "H", self.counts[offset : offset + 2])
        if count in (ERROR_COUNT, OUTSIDE_COUNT):
            return None
        return self.count_to_brightness_temperature(count)

    def count_to_brightness_temperature(self, count: int) -> float | None:
        radiance = self.slope * count + self.intercept  # W / (m2 sr um)
        if radiance <= 0:
            return None
        wavelength = self.wavelength_um * 1e-6
        radiance_per_m = radiance * 1e6
        effective = (self.planck * self.light_speed / (self.boltzmann * wavelength)) / math.log(
            2 * self.planck * self.light_speed**2 / (wavelength**5 * radiance_per_m) + 1
        )
        return self.c0 + self.c1 * effective + self.c2 * effective**2


def geo_to_image(
    latitude: float,
    longitude: float,
    *,
    sub_lon: float,
    cfac: int,
    lfac: int,
    coff: float,
    loff: float,
) -> tuple[float, float]:
    """正規化静止衛星投影(CGMS LRIT/HRIT 4.4.4)で、緯度経度を1始まりの(列, 行)へ。"""
    lat = math.radians(latitude)
    dlon = math.radians(longitude - sub_lon)
    c_lat = math.atan(0.993305616 * math.tan(lat))
    rl = 6356.7523 / math.sqrt(1 - 0.00669438444 * math.cos(c_lat) ** 2)
    r1 = 42164.0 - rl * math.cos(c_lat) * math.cos(dlon)
    r2 = -rl * math.cos(c_lat) * math.sin(dlon)
    r3 = rl * math.sin(c_lat)
    rn = math.sqrt(r1**2 + r2**2 + r3**2)
    x = math.degrees(math.atan(-r2 / r1))
    y = math.degrees(math.asin(-r3 / rn))
    return coff + x * 2**-16 * cfac, loff + y * 2**-16 * lfac


def read_hsd(data: bytes) -> HimawariImage:
    """HSDファイル(bz2圧縮のままでも可)を読む。"""
    if data[:3] == b"BZh":
        data = bz2.decompress(data)
    order = "<" if data[_BLOCK1 + 5] == 0 else ">"

    def unpack(fmt: str, offset: int) -> tuple:
        return struct.unpack_from(order + fmt, data, offset)

    for block, offset in ((1, _BLOCK1), (2, _BLOCK2), (3, _BLOCK3), (5, _BLOCK5), (7, _BLOCK7)):
        if data[offset] != block:
            raise ValueError(f"Unexpected HSD header layout at block {block}")
    (start_mjd,) = unpack("d", _BLOCK1 + 46)
    (total_header,) = unpack("I", _BLOCK1 + 70)
    columns, lines = unpack("HH", _BLOCK2 + 5)
    if data[_BLOCK2 + 9] != 0:
        raise ValueError("Compressed HSD data blocks are not supported")
    sub_lon, cfac, lfac, coff, loff = unpack("dIIff", _BLOCK3 + 3)
    band, wavelength = unpack("Hd", _BLOCK5 + 3)
    slope, intercept = unpack("dd", _BLOCK5 + 19)
    if band < 7:
        raise ValueError("Only infrared bands (7-16) are supported")
    c0, c1, c2 = unpack("ddd", _BLOCK5 + 35)
    light_speed, planck, boltzmann = unpack("ddd", _BLOCK5 + 83)
    (first_line,) = unpack("H", _BLOCK7 + 5)
    counts = data[total_header : total_header + columns * lines * 2]
    if len(counts) != columns * lines * 2:
        raise ValueError("HSD data block is truncated")
    return HimawariImage(
        band=band,
        wavelength_um=wavelength,
        observation_start=MJD_EPOCH + timedelta(days=start_mjd),
        columns=columns,
        lines=lines,
        first_line=first_line,
        sub_lon=sub_lon,
        cfac=cfac,
        lfac=lfac,
        coff=coff,
        loff=loff,
        slope=slope,
        intercept=intercept,
        c0=c0,
        c1=c1,
        c2=c2,
        light_speed=light_speed,
        planck=planck,
        boltzmann=boltzmann,
        counts=counts,
        byte_order=order,
    )


def timeline_floor(moment: datetime) -> datetime:
    """その時刻を含む10分タイムライン(UTC)。日本域の JP01 は開始から約15秒後に始まる。"""
    moment = moment.astimezone(UTC)
    return moment.replace(minute=moment.minute - moment.minute % 10, second=0, microsecond=0)


def scan_url(timeline: datetime, band: int, *, segment: str = "JP01") -> str:
    """赤外バンド(2km、R20)の日本域HSDのURL。"""
    t = timeline.astimezone(UTC)
    return (
        f"{AWS_JAPAN_URL}/{t:%Y/%m/%d/%H%M}/"
        f"HS_H09_{t:%Y%m%d_%H%M}_B{band:02d}_{segment}_R20_S0101.DAT.bz2"
    )


def download(url: str, *, timeout: int = 60, retries: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urlopen(url, timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(url) from exc
            last_error = exc
        except (URLError, TimeoutError) as exc:
            last_error = exc
        if attempt < retries:
            time.sleep(5 * attempt)
    raise RuntimeError(f"Himawari download failed: {last_error}") from last_error
