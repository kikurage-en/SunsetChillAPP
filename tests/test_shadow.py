from __future__ import annotations

import gzip
import json
from datetime import date, datetime
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from zushi_chill.config import Settings
from zushi_chill.shadow import log_forecasts, shadow_points

JST = ZoneInfo("Asia/Tokyo")


def _settings(monkeypatch) -> Settings:
    for name in (
        "SUNSET_CLOUD_OFFSET_KM",
        "SUNSET_CLOUD_NEAR_OFFSET_KM",
        "SUNSET_CLOUD_PATH_MAX_KM",
    ):
        monkeypatch.delenv(name, raising=False)
    return Settings.from_env()


def test_shadow_points_follow_production_geometry(monkeypatch):
    points = shadow_points(_settings(monkeypatch), date(2026, 10, 10))

    assert [point["name"] for point in points] == [
        "zushi",
        "near",
        "far",
        "path50",
        "path60",
        "path80",
        "path100",
    ]
    assert [point["distance_km"] for point in points] == [0, 20, 40, 50, 60, 80, 100]
    # 10月の日没方位は西南西なので、遠い地点ほど西(経度が小さい)へ並ぶ。
    longitudes = [point["longitude"] for point in points]
    assert longitudes == sorted(longitudes, reverse=True)


def test_log_forecasts_saves_each_kind_and_survives_one_failure(monkeypatch, tmp_path):
    settings = _settings(monkeypatch)
    requested: list[str] = []

    def fetch(url: str):
        requested.append(url)
        if "ensemble-api" in url:
            raise RuntimeError("ensemble unavailable")
        return [{"hourly": {"time": ["2026-10-10T17:00"], "cloud_cover_jma_seamless": [12]}}]

    written = log_forecasts(
        settings,
        target_date=date(2026, 10, 10),
        shadow_dir=tmp_path,
        now=datetime(2026, 10, 10, 14, 30, tzinfo=JST),
        fetch=fetch,
    )

    assert [path.name for path in written] == ["deterministic-1430.json.gz"]
    saved = json.loads(gzip.decompress(written[0].read_bytes()))
    assert saved["date"] == "2026-10-10"
    assert saved["sunset"] == "2026-10-10T17:13+09:00"
    assert len(saved["points"]) == 7
    assert saved["payload"][0]["hourly"]["cloud_cover_jma_seamless"] == [12]

    ensemble_query = parse_qs(urlparse(requested[0]).query)
    assert ensemble_query["models"] == ["ecmwf_ifs025,gfs025,icon_seamless"]
    assert ensemble_query["start_date"] == ["2026-10-10"]
    assert len(ensemble_query["latitude"][0].split(",")) == 7
    deterministic_query = parse_qs(urlparse(requested[1]).query)
    assert deterministic_query["models"] == [
        "jma_seamless,ecmwf_ifs025,gfs_seamless,icon_seamless"
    ]
    assert deterministic_query["hourly"] == [
        "cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high"
    ]
