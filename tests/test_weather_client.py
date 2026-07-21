from __future__ import annotations

import json
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import pytest

from zushi_chill.weather_client import OpenMeteoClient, WeatherDataError, parse_forecast


def test_parse_forecast_extracts_sunset_and_target_window(sample_summary):
    assert sample_summary.sunset_time.strftime("%H:%M") == "18:51"
    assert sample_summary.target_window_start.strftime("%H:%M") == "17:21"
    assert sample_summary.target_window_end.strftime("%H:%M") == "19:21"
    assert sample_summary.precipitation_probability == 10
    assert sample_summary.precipitation == 0
    assert sample_summary.visibility == 18000


def test_parse_forecast_includes_hourly_rows_that_overlap_target_window(sample_payload):
    sample_payload["hourly"]["precipitation_probability"][17] = 55

    summary = parse_forecast(
        sample_payload,
        location_name="逗子海岸",
        latitude=35.2956,
        longitude=139.5736,
        timezone="Asia/Tokyo",
    )

    assert summary.target_window_start.strftime("%H:%M") == "17:21"
    assert summary.precipitation_probability == 55


def test_parse_forecast_aggregates_target_window_fields_by_requirement(sample_payload):
    hourly = sample_payload["hourly"]
    indexes = [17, 18, 19]
    values_by_field = {
        "temperature_2m": [20, 22, 24],
        "apparent_temperature": [21, 23, 25],
        "relative_humidity_2m": [60, 70, 80],
        "precipitation_probability": [10, 60, 30],
        "precipitation": [0.2, 0.3, 0.4],
        "weather_code": [1, 2, 3],
        "cloud_cover": [20, 40, 60],
        "cloud_cover_low": [10, 30, 50],
        "cloud_cover_mid": [30, 50, 70],
        "cloud_cover_high": [40, 60, 80],
        "visibility": [12000, 8000, 15000],
        "wind_speed_10m": [2, 4, 6],
        "wind_direction_10m": [90, 90, 90],
        "wind_gusts_10m": [5, 9, 7],
    }
    for field, values in values_by_field.items():
        for index, value in zip(indexes, values, strict=True):
            hourly[field][index] = value

    summary = parse_forecast(
        sample_payload,
        location_name="逗子海岸",
        latitude=35.2956,
        longitude=139.5736,
        timezone="Asia/Tokyo",
    )

    assert summary.temperature_2m == 22.0
    assert summary.apparent_temperature == 23.0
    assert summary.relative_humidity_2m == 70.0
    assert summary.precipitation_probability == 60.0
    assert summary.precipitation == 0.9
    assert summary.weather_code == 3
    assert summary.cloud_cover == 40.0
    assert summary.cloud_cover_low == 30.0
    assert summary.cloud_cover_mid == 50.0
    assert summary.cloud_cover_high == 60.0
    assert summary.visibility == 8000.0
    assert summary.wind_speed_10m == 4.0
    assert summary.wind_direction_10m == 90.0
    assert summary.wind_gusts_10m == 9.0
    # 日没18:51を挟む18:00 / 19:00の値を、集計値とは別に校正用へ残す。
    assert summary.precipitation_probability_before_sunset == 60.0
    assert summary.precipitation_before_sunset == 0.3
    assert summary.weather_code_before_sunset == 2
    assert summary.visibility_before_sunset == 8000.0
    assert summary.precipitation_probability_at_sunset == 30.0
    assert summary.precipitation_at_sunset == 0.4
    assert summary.weather_code_at_sunset == 3
    assert summary.visibility_at_sunset == 15000.0


def test_parse_forecast_uses_circular_mean_for_wind_direction(sample_payload):
    sample_payload["hourly"]["wind_direction_10m"][17] = 350
    sample_payload["hourly"]["wind_direction_10m"][18] = 10
    sample_payload["hourly"]["wind_direction_10m"][19] = 0

    summary = parse_forecast(
        sample_payload,
        location_name="逗子海岸",
        latitude=35.2956,
        longitude=139.5736,
        timezone="Asia/Tokyo",
    )

    assert summary.wind_direction_10m in {0.0, 360.0}


def test_parse_forecast_preserves_rain_weather_code_in_target_window(sample_payload):
    sample_payload["hourly"]["weather_code"][17] = 1
    sample_payload["hourly"]["weather_code"][18] = 61
    sample_payload["hourly"]["weather_code"][19] = 1

    summary = parse_forecast(
        sample_payload,
        location_name="逗子海岸",
        latitude=35.2956,
        longitude=139.5736,
        timezone="Asia/Tokyo",
    )

    assert summary.weather_code == 61


def test_parse_forecast_raises_on_missing_required_data(sample_payload):
    sample_payload["hourly"]["cloud_cover_low"][18] = None

    with pytest.raises(WeatherDataError):
        parse_forecast(
            sample_payload,
            location_name="逗子海岸",
            latitude=35.2956,
            longitude=139.5736,
            timezone="Asia/Tokyo",
        )


def test_parse_forecast_can_ignore_configured_missing_values(sample_payload):
    sample_payload["hourly"]["visibility"][18] = None
    sample_payload["hourly"]["visibility"][19] = 12000

    summary = parse_forecast(
        sample_payload,
        location_name="逗子海岸",
        latitude=35.2956,
        longitude=139.5736,
        timezone="Asia/Tokyo",
        allow_missing_fields=frozenset({"visibility"}),
    )

    assert summary.visibility == 12000


def test_parse_forecast_raises_when_allowed_field_has_no_usable_data(sample_payload):
    sample_payload["hourly"]["visibility"][17] = None
    sample_payload["hourly"]["visibility"][18] = None
    sample_payload["hourly"]["visibility"][19] = None

    with pytest.raises(WeatherDataError, match="no usable data"):
        parse_forecast(
            sample_payload,
            location_name="逗子海岸",
            latitude=35.2956,
            longitude=139.5736,
            timezone="Asia/Tokyo",
            allow_missing_fields=frozenset({"visibility"}),
        )


def test_parse_forecast_raises_on_unknown_allowed_missing_field(sample_payload):
    with pytest.raises(WeatherDataError, match="Unknown"):
        parse_forecast(
            sample_payload,
            location_name="逗子海岸",
            latitude=35.2956,
            longitude=139.5736,
            timezone="Asia/Tokyo",
            allow_missing_fields=frozenset({"not_a_field"}),
        )


def test_parse_forecast_raises_on_invalid_datetime(sample_payload):
    sample_payload["daily"]["sunset"][0] = "not-a-datetime"

    with pytest.raises(WeatherDataError, match="daily.sunset"):
        parse_forecast(
            sample_payload,
            location_name="逗子海岸",
            latitude=35.2956,
            longitude=139.5736,
            timezone="Asia/Tokyo",
        )


def test_parse_forecast_raises_when_no_hourly_rows_overlap_target_window(sample_payload):
    sample_payload["daily"]["sunset"][0] = "2026-06-02T18:51"

    with pytest.raises(WeatherDataError, match="No hourly rows"):
        parse_forecast(
            sample_payload,
            location_name="逗子海岸",
            latitude=35.2956,
            longitude=139.5736,
            timezone="Asia/Tokyo",
        )


def test_parse_forecast_raises_on_hourly_length_mismatch(sample_payload):
    sample_payload["hourly"]["temperature_2m"] = sample_payload["hourly"]["temperature_2m"][:-1]

    with pytest.raises(WeatherDataError, match="length"):
        parse_forecast(
            sample_payload,
            location_name="逗子海岸",
            latitude=35.2956,
            longitude=139.5736,
            timezone="Asia/Tokyo",
        )


def test_parse_forecast_raises_on_non_numeric_hourly_value(sample_payload):
    sample_payload["hourly"]["temperature_2m"][18] = "warm"

    with pytest.raises(WeatherDataError, match="non-numeric"):
        parse_forecast(
            sample_payload,
            location_name="逗子海岸",
            latitude=35.2956,
            longitude=139.5736,
            timezone="Asia/Tokyo",
        )


def test_open_meteo_client_uses_start_and_end_date_when_target_date(monkeypatch):
    captured = {}

    def fake_urlopen(url, timeout):
        captured["query"] = parse_qs(urlparse(url).query)
        captured["timeout"] = timeout
        return FakeResponse({"hourly": {"time": []}, "daily": {"sunset": []}})

    monkeypatch.setattr("zushi_chill.weather_client.urlopen", fake_urlopen)

    OpenMeteoClient(timeout=7).fetch_forecast(
        latitude=35.2956,
        longitude=139.5736,
        timezone="Asia/Tokyo",
        target_date=date(2026, 6, 1),
    )

    assert captured["timeout"] == 7
    assert captured["query"]["start_date"] == ["2026-06-01"]
    assert captured["query"]["end_date"] == ["2026-06-01"]
    assert "forecast_days" not in captured["query"]


def test_open_meteo_client_uses_required_forecast_parameters(monkeypatch):
    captured = {}

    def fake_urlopen(url, timeout):
        captured["query"] = parse_qs(urlparse(url).query)
        return FakeResponse({"hourly": {"time": []}, "daily": {"sunset": []}})

    monkeypatch.setattr("zushi_chill.weather_client.urlopen", fake_urlopen)

    OpenMeteoClient().fetch_forecast(
        latitude=35.2956,
        longitude=139.5736,
        timezone="Asia/Tokyo",
    )

    query = captured["query"]
    assert query["latitude"] == ["35.2956"]
    assert query["longitude"] == ["139.5736"]
    assert query["timezone"] == ["Asia/Tokyo"]
    assert query["forecast_days"] == ["1"]
    assert query["wind_speed_unit"] == ["ms"]
    assert query["daily"] == ["sunset"]
    assert set(query["hourly"][0].split(",")) == {
        "temperature_2m",
        "relative_humidity_2m",
        "apparent_temperature",
        "precipitation_probability",
        "precipitation",
        "weather_code",
        "cloud_cover",
        "cloud_cover_low",
        "cloud_cover_mid",
        "cloud_cover_high",
        "visibility",
        "wind_speed_10m",
        "wind_direction_10m",
        "wind_gusts_10m",
    }


def test_open_meteo_client_retries_with_exponential_backoff(monkeypatch):
    attempts = []
    sleeps = []

    def fake_urlopen(url, timeout):
        attempts.append((url, timeout))
        if len(attempts) < 3:
            raise URLError("temporary failure")
        return FakeResponse({"ok": True})

    monkeypatch.setattr("zushi_chill.weather_client.urlopen", fake_urlopen)
    monkeypatch.setattr("zushi_chill.weather_client.time.sleep", sleeps.append)

    payload = OpenMeteoClient(timeout=9, retries=3, backoff_seconds=1).fetch_forecast(
        latitude=35.2956,
        longitude=139.5736,
        timezone="Asia/Tokyo",
    )

    assert payload == {"ok": True}
    assert len(attempts) == 3
    assert sleeps == [1, 2]


def test_open_meteo_client_logs_http_error_body(monkeypatch, caplog):
    def fake_urlopen(url, timeout):
        raise HTTPError(
            url=url,
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=FakeErrorBody(b'{"reason":"rate limited"}'),
        )

    monkeypatch.setattr("zushi_chill.weather_client.urlopen", fake_urlopen)
    monkeypatch.setattr("zushi_chill.weather_client.time.sleep", lambda seconds: None)

    with pytest.raises(WeatherDataError, match="after 1 attempts") as exc_info:
        OpenMeteoClient(retries=1).fetch_forecast(
            latitude=35.2956,
            longitude=139.5736,
            timezone="Asia/Tokyo",
        )

    assert "HTTP 429" in caplog.text
    assert "rate limited" in caplog.text
    assert "rate limited" in str(exc_info.value.__cause__)


def test_open_meteo_client_logs_non_success_response_body(monkeypatch, caplog):
    def fake_urlopen(url, timeout):
        return FakeResponse({"reason": "bad request"}, status=400)

    monkeypatch.setattr("zushi_chill.weather_client.urlopen", fake_urlopen)

    with pytest.raises(WeatherDataError, match="after 1 attempts") as exc_info:
        OpenMeteoClient(retries=1).fetch_forecast(
            latitude=35.2956,
            longitude=139.5736,
            timezone="Asia/Tokyo",
        )

    assert "HTTP 400" in caplog.text
    assert "bad request" in caplog.text
    assert "bad request" in str(exc_info.value.__cause__)


def test_open_meteo_client_raises_after_final_retry(monkeypatch):
    sleeps = []

    def fake_urlopen(url, timeout):
        raise URLError("still down")

    monkeypatch.setattr("zushi_chill.weather_client.urlopen", fake_urlopen)
    monkeypatch.setattr("zushi_chill.weather_client.time.sleep", sleeps.append)

    with pytest.raises(WeatherDataError, match="after 3 attempts"):
        OpenMeteoClient(retries=3, backoff_seconds=0.5).fetch_forecast(
            latitude=35.2956,
            longitude=139.5736,
            timezone="Asia/Tokyo",
        )

    assert sleeps == [0.5, 1.0]


class FakeResponse:
    def __init__(self, payload, *, status=200):
        self.status = status
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FakeErrorBody:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def close(self):
        pass
