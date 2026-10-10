from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from zushi_chill.config import Settings
from zushi_chill.shadow_satellite import (
    GRID_COLUMNS,
    GRID_ROWS,
    CloudRule,
    box_cloud,
    box_indices,
    build_features,
    clear_reference,
    cloud_layer,
    grid_point,
    series_timeline,
)

JST = ZoneInfo("Asia/Tokyo")
RULE = CloudRule()


def _record(day: str, value: float) -> dict:
    return {"date": day, "b13": [value] * (GRID_ROWS * GRID_COLUMNS)}


def test_series_timelines_match_the_forecast_information_time():
    sunset = datetime(2026, 10, 9, 17, 14, tzinfo=JST)
    target = date(2026, 10, 9)
    # 16:50 JST = 07:50 UTC。日没−65分(16:09)までの最新は16:00。日没に最も近いのは17:10。
    assert series_timeline("t17", target, sunset) == datetime(2026, 10, 9, 7, 50, tzinfo=UTC)
    assert series_timeline("t60", target, sunset) == datetime(2026, 10, 9, 7, 0, tzinfo=UTC)
    assert series_timeline("t0", target, sunset) == datetime(2026, 10, 9, 8, 10, tzinfo=UTC)


def test_cloud_layer_uses_the_clear_margin_then_the_cloud_top_temperature():
    assert cloud_layer(296.0, 300.0, RULE) == "clear"
    assert cloud_layer(290.0, 300.0, RULE) == "low"
    assert cloud_layer(260.0, 300.0, RULE) == "mid"
    assert cloud_layer(230.0, 300.0, RULE) == "high"
    assert cloud_layer(None, 300.0, RULE) is None


def test_box_indices_cover_plus_minus_the_box_size():
    latitude, longitude = grid_point(30, 30)
    indices = box_indices(latitude, longitude, 0.05)
    # ±0.05° は格子 0.02° で中心±2点 = 5x5。
    assert len(indices) == 25
    assert 30 * GRID_COLUMNS + 30 in indices


def test_clear_reference_needs_enough_history_and_takes_the_maximum():
    records = {
        f"2026-09-{day:02d}": _record(f"2026-09-{day:02d}", 280.0 + day) for day in range(1, 10)
    }
    # 前日までの15日に9日しかない。
    assert clear_reference(records, date(2026, 9, 10), RULE) is None
    records["2026-09-10"] = _record("2026-09-10", 250.0)
    reference = clear_reference(records, date(2026, 9, 11), RULE)
    assert reference is not None
    assert reference[0] == 289.0


def test_box_cloud_reports_layer_shares_like_the_forecast_columns():
    record = _record("2026-09-20", 296.0)
    reference = [300.0] * len(record["b13"])
    latitude, longitude = grid_point(30, 30)
    for index in box_indices(latitude, longitude, 0.05)[:10]:
        record["b13"][index] = 240.0
    cloud = box_cloud(record, reference, latitude, longitude, RULE)
    assert cloud == {
        "cloud_cover": 40.0,
        "cloud_cover_low": 0.0,
        "cloud_cover_mid": 0.0,
        "cloud_cover_high": 40.0,
    }


def test_build_features_skips_days_without_a_clear_reference(monkeypatch):
    for name in ("SUNSET_CLOUD_OFFSET_KM", "SUNSET_CLOUD_NEAR_OFFSET_KM"):
        monkeypatch.delenv(name, raising=False)
    records = {
        f"2026-09-{day:02d}": _record(f"2026-09-{day:02d}", 296.0) for day in range(1, 17)
    }
    features = build_features(records, Settings.from_env(), RULE)
    assert sorted(features) == [f"2026-09-{day:02d}" for day in range(11, 17)]
    assert features["2026-09-16"]["sat_path_max"] == 0.0
