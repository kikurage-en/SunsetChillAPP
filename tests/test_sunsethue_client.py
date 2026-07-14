from __future__ import annotations

from datetime import date

import pytest
from zushi_chill.sunsethue_client import SunsethueError, _parse_event, fetch_sunset_quality


def test_parse_event_scales_quality_and_cloud_cover_to_0_100():
    # 実 API の raw レスポンス形(逗子・2026-07-14 で実取得した構造)
    payload = {
        "data": {
            "type": "sunset",
            "quality": 0.3,
            "cloud_cover": 0.13,
            "quality_text": "Fair",
            "direction": 297.7,
        }
    }
    result = _parse_event(payload)
    # 0〜1 を 0〜100 整数へ(式 sunset_score・Vision と同じ土俵)
    assert result.quality == 30
    assert result.cloud_cover == 13
    assert result.quality_text == "Fair"


def test_parse_event_rejects_missing_or_non_numeric_data():
    with pytest.raises(SunsethueError):
        _parse_event({"time": "..."})  # data 欠落
    with pytest.raises(SunsethueError):
        _parse_event({"data": {"quality": "high", "cloud_cover": 0.1}})  # 非数値


def test_fetch_requires_api_key():
    with pytest.raises(SunsethueError, match="SUNSETHUE_API_KEY"):
        fetch_sunset_quality(
            latitude=35.2956,
            longitude=139.5736,
            target_date=date(2026, 7, 14),
            api_key="",
        )
