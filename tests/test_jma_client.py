from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from zushi_chill.jma_client import JmaForecastError, parse_jma_precipitation_probability


def _payload() -> list[dict]:
    return [
        {
            "reportDatetime": "2026-07-21T17:00:00+09:00",
            "timeSeries": [
                {
                    "timeDefines": [
                        "2026-07-21T18:00:00+09:00",
                        "2026-07-22T00:00:00+09:00",
                        "2026-07-22T06:00:00+09:00",
                    ],
                    "areas": [
                        {
                            "area": {"name": "東部", "code": "140010"},
                            "pops": ["20", "0", "10"],
                        }
                    ],
                }
            ],
        }
    ]


def test_parse_jma_probability_selects_period_containing_sunset():
    result = parse_jma_precipitation_probability(
        _payload(),
        area_code="140010",
        target_time=datetime(2026, 7, 21, 18, 54, tzinfo=ZoneInfo("Asia/Tokyo")),
    )

    assert result.probability == 20
    assert result.period_start.isoformat() == "2026-07-21T18:00:00+09:00"
    assert result.period_end.isoformat() == "2026-07-22T00:00:00+09:00"
    assert result.area_name == "東部"
    assert result.report_time.isoformat() == "2026-07-21T17:00:00+09:00"


def test_parse_jma_probability_rejects_missing_target_period():
    with pytest.raises(JmaForecastError, match="no precipitation period"):
        parse_jma_precipitation_probability(
            _payload(),
            area_code="140010",
            target_time=datetime(2026, 7, 22, 13, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
        )


def test_parse_jma_probability_rejects_invalid_probability():
    payload = _payload()
    payload[0]["timeSeries"][0]["areas"][0]["pops"][0] = "unknown"

    with pytest.raises(JmaForecastError, match="probability is invalid"):
        parse_jma_precipitation_probability(
            payload,
            area_code="140010",
            target_time=datetime(2026, 7, 21, 18, 54, tzinfo=ZoneInfo("Asia/Tokyo")),
        )
