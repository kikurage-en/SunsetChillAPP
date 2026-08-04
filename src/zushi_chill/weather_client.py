from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from zushi_chill.constants import RAIN_WEATHER_CODES
from zushi_chill.models import WeatherSummary

LOGGER = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_FIELDS = (
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
)
PRECEDING_HOUR_FIELDS = frozenset(
    {"precipitation_probability", "precipitation", "wind_gusts_10m"}
)


class WeatherDataError(RuntimeError):
    """Raised when weather data cannot be fetched or parsed safely."""


class OpenMeteoClient:
    def __init__(self, *, timeout: int = 20, retries: int = 3, backoff_seconds: float = 1.0):
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds

    def fetch_forecast(
        self,
        *,
        latitude: float,
        longitude: float,
        timezone: str,
        target_date: date | None = None,
    ) -> dict[str, Any]:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": timezone,
            "wind_speed_unit": "ms",
            "hourly": ",".join(HOURLY_FIELDS),
            "daily": "sunset",
        }
        if target_date is None:
            params["forecast_days"] = 1
        else:
            date_value = target_date.isoformat()
            params["start_date"] = date_value
            params["end_date"] = date_value
        url = f"{OPEN_METEO_URL}?{urlencode(params)}"
        last_error: Exception | None = None

        for attempt in range(1, self.retries + 1):
            try:
                with urlopen(url, timeout=self.timeout) as response:
                    if response.status >= 400:
                        body = response.read().decode("utf-8", errors="replace")
                        raise WeatherDataError(
                            f"Open-Meteo returned HTTP {response.status}: {body}"
                        )
                    return json.loads(response.read().decode("utf-8"))
            except (
                HTTPError,
                URLError,
                TimeoutError,
                json.JSONDecodeError,
                WeatherDataError,
            ) as exc:
                last_error = _fetch_error(exc)
                LOGGER.warning(
                    "Open-Meteo fetch failed on attempt %s/%s: %s",
                    attempt,
                    self.retries,
                    last_error,
                )
                if attempt < self.retries:
                    time.sleep(self.backoff_seconds * (2 ** (attempt - 1)))

        raise WeatherDataError(
            f"Open-Meteo fetch failed after {self.retries} attempts"
        ) from last_error


def parse_forecast(
    payload: Mapping[str, Any],
    *,
    location_name: str,
    latitude: float,
    longitude: float,
    timezone: str,
    run_time: datetime | None = None,
    allow_missing_fields: set[str] | frozenset[str] | None = None,
) -> WeatherSummary:
    hourly = payload.get("hourly")
    daily = payload.get("daily")
    if not isinstance(hourly, Mapping) or not isinstance(daily, Mapping):
        raise WeatherDataError("Open-Meteo payload must contain hourly and daily objects")

    times_raw = hourly.get("time")
    sunsets_raw = daily.get("sunset")
    if not isinstance(times_raw, list) or not times_raw:
        raise WeatherDataError("hourly.time is missing or empty")
    if not isinstance(sunsets_raw, list) or not sunsets_raw:
        raise WeatherDataError("daily.sunset is missing or empty")

    tz = ZoneInfo(timezone)
    times = [_parse_local_datetime(value, tz, "hourly.time") for value in times_raw]
    sunset_time = _parse_local_datetime(sunsets_raw[0], tz, "daily.sunset")
    window_start = sunset_time - timedelta(minutes=90)
    window_end = sunset_time + timedelta(minutes=30)
    indexes = _target_window_indexes(times, window_start, window_end)
    if not indexes:
        raise WeatherDataError("No hourly rows found in the sunset target window")
    preceding_hour_indexes = _preceding_hour_window_indexes(
        times, window_start, window_end
    )
    if not preceding_hour_indexes:
        raise WeatherDataError("No preceding-hour rows found in the sunset target window")

    allow_missing_fields = allow_missing_fields or frozenset()
    unknown_allowed_fields = set(allow_missing_fields) - set(HOURLY_FIELDS)
    if unknown_allowed_fields:
        raise WeatherDataError(
            "Unknown ALLOW_MISSING_HOURLY_FIELDS entries: "
            + ", ".join(sorted(unknown_allowed_fields))
        )

    values = {
        field: _values_for_indexes(
            hourly,
            field,
            preceding_hour_indexes if field in PRECEDING_HOUR_FIELDS else indexes,
            len(times),
            allow_missing=field in allow_missing_fields,
        )
        for field in HOURLY_FIELDS
    }
    before_sunset_index, at_sunset_index = _sunset_diagnostic_indexes(times, sunset_time)
    before_sunset = {
        field: _value_for_index(
            hourly,
            field,
            before_sunset_index,
            len(times),
            allow_missing=field in allow_missing_fields,
        )
        for field in (
            "precipitation_probability",
            "precipitation",
            "weather_code",
            "visibility",
        )
    }
    at_sunset = {
        field: _value_for_index(
            hourly,
            field,
            at_sunset_index,
            len(times),
            allow_missing=field in allow_missing_fields,
        )
        for field in (
            "precipitation_probability",
            "precipitation",
            "weather_code",
            "visibility",
        )
    }
    sunset_snapshot_index = _nearest_time_index(times, sunset_time)
    sunset_snapshot = {
        field: _value_for_index(
            hourly,
            field,
            sunset_snapshot_index,
            len(times),
            allow_missing=field in allow_missing_fields,
        )
        for field in (
            "temperature_2m",
            "relative_humidity_2m",
            "cloud_cover_low",
            "cloud_cover_mid",
            "cloud_cover_high",
            "visibility",
            "wind_speed_10m",
            "wind_direction_10m",
        )
    }
    run_time = datetime.now(tz) if run_time is None else run_time.astimezone(tz)
    run_time_snapshot_index = _nearest_time_index(times, run_time)
    run_time_snapshot = {
        field: _value_for_index(
            hourly,
            field,
            run_time_snapshot_index,
            len(times),
            allow_missing=field in allow_missing_fields,
        )
        for field in HOURLY_FIELDS
    }
    daytime_indexes = [
        index
        for index, item_time in enumerate(times)
        if item_time.date() == sunset_time.date()
        and item_time.hour >= 6
        and item_time <= sunset_time
    ]
    daytime_temperatures = _values_for_indexes(
        hourly,
        "temperature_2m",
        daytime_indexes,
        len(times),
        allow_missing="temperature_2m" in allow_missing_fields,
    )

    return WeatherSummary(
        date=sunset_time.date().isoformat(),
        run_time=run_time.strftime("%H:%M"),
        location_name=location_name,
        latitude=latitude,
        longitude=longitude,
        sunset_time=sunset_time,
        target_window_start=window_start,
        target_window_end=window_end,
        temperature_2m=_mean(values["temperature_2m"]),
        apparent_temperature=_mean(values["apparent_temperature"]),
        relative_humidity_2m=_mean(values["relative_humidity_2m"]),
        precipitation_probability=max(values["precipitation_probability"]),
        precipitation=sum(values["precipitation"]),
        weather_code=_representative_weather_code(values["weather_code"]),
        cloud_cover=_mean(values["cloud_cover"]),
        cloud_cover_low=_mean(values["cloud_cover_low"]),
        cloud_cover_mid=_mean(values["cloud_cover_mid"]),
        cloud_cover_high=_mean(values["cloud_cover_high"]),
        visibility=min(values["visibility"]),
        wind_speed_10m=_mean(values["wind_speed_10m"]),
        wind_direction_10m=_circular_mean_degrees(values["wind_direction_10m"]),
        wind_gusts_10m=max(values["wind_gusts_10m"]),
        precipitation_probability_before_sunset=before_sunset[
            "precipitation_probability"
        ],
        precipitation_before_sunset=before_sunset["precipitation"],
        weather_code_before_sunset=_optional_int(before_sunset["weather_code"]),
        visibility_before_sunset=before_sunset["visibility"],
        precipitation_probability_at_sunset=at_sunset["precipitation_probability"],
        precipitation_at_sunset=at_sunset["precipitation"],
        weather_code_at_sunset=_optional_int(at_sunset["weather_code"]),
        visibility_at_sunset=at_sunset["visibility"],
        run_time_snapshot_time=times[run_time_snapshot_index],
        temperature_2m_at_run_time=run_time_snapshot["temperature_2m"],
        apparent_temperature_at_run_time=run_time_snapshot["apparent_temperature"],
        relative_humidity_2m_at_run_time=run_time_snapshot[
            "relative_humidity_2m"
        ],
        precipitation_probability_at_run_time=run_time_snapshot[
            "precipitation_probability"
        ],
        precipitation_at_run_time=run_time_snapshot["precipitation"],
        weather_code_at_run_time=_optional_int(run_time_snapshot["weather_code"]),
        cloud_cover_at_run_time=run_time_snapshot["cloud_cover"],
        cloud_cover_low_at_run_time=run_time_snapshot["cloud_cover_low"],
        cloud_cover_mid_at_run_time=run_time_snapshot["cloud_cover_mid"],
        cloud_cover_high_at_run_time=run_time_snapshot["cloud_cover_high"],
        visibility_at_run_time=run_time_snapshot["visibility"],
        wind_speed_10m_at_run_time=run_time_snapshot["wind_speed_10m"],
        wind_direction_10m_at_run_time=run_time_snapshot["wind_direction_10m"],
        wind_gusts_10m_at_run_time=run_time_snapshot["wind_gusts_10m"],
        temperature_2m_daytime_max=max(daytime_temperatures),
        sunset_snapshot_time=times[sunset_snapshot_index],
        temperature_2m_at_sunset=sunset_snapshot["temperature_2m"],
        relative_humidity_2m_at_sunset=sunset_snapshot["relative_humidity_2m"],
        cloud_cover_low_at_sunset=sunset_snapshot["cloud_cover_low"],
        cloud_cover_mid_at_sunset=sunset_snapshot["cloud_cover_mid"],
        cloud_cover_high_at_sunset=sunset_snapshot["cloud_cover_high"],
        visibility_at_sunset_snapshot=sunset_snapshot["visibility"],
        wind_speed_10m_at_sunset=sunset_snapshot["wind_speed_10m"],
        wind_direction_10m_at_sunset=sunset_snapshot["wind_direction_10m"],
    )


def _fetch_error(exc: Exception) -> Exception:
    if isinstance(exc, HTTPError):
        body = exc.read().decode("utf-8", errors="replace")
        return WeatherDataError(f"Open-Meteo returned HTTP {exc.code}: {body}")
    return exc


def _parse_local_datetime(value: Any, tz: ZoneInfo, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise WeatherDataError(f"{field_name} must contain ISO datetime strings")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise WeatherDataError(f"{field_name} contains invalid datetime: {value}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _target_window_indexes(
    times: list[datetime], window_start: datetime, window_end: datetime
) -> list[int]:
    indexes = []
    for index, item_time in enumerate(times):
        item_end = item_time + timedelta(hours=1)
        if item_time < window_end and item_end > window_start:
            indexes.append(index)
    return indexes


def _preceding_hour_window_indexes(
    times: list[datetime], window_start: datetime, window_end: datetime
) -> list[int]:
    """Return rows whose preceding one-hour interval overlaps the target window."""
    indexes = []
    for index, item_time in enumerate(times):
        item_start = item_time - timedelta(hours=1)
        if item_time > window_start and item_start < window_end:
            indexes.append(index)
    return indexes


def _sunset_diagnostic_indexes(
    times: list[datetime], sunset_time: datetime
) -> tuple[int, int]:
    before = [index for index, item_time in enumerate(times) if item_time < sunset_time]
    at_or_after = [index for index, item_time in enumerate(times) if item_time >= sunset_time]
    if not before or not at_or_after:
        raise WeatherDataError("Hourly rows do not bracket sunset time")
    return before[-1], at_or_after[0]


def _nearest_time_index(times: list[datetime], target_time: datetime) -> int:
    return min(
        range(len(times)),
        key=lambda index: abs((times[index] - target_time).total_seconds()),
    )


def _values_for_indexes(
    hourly: Mapping[str, Any],
    field: str,
    indexes: list[int],
    expected_len: int,
    *,
    allow_missing: bool = False,
) -> list[float]:
    raw_values = hourly.get(field)
    if not isinstance(raw_values, list) or len(raw_values) != expected_len:
        raise WeatherDataError(f"hourly.{field} is missing or length does not match hourly.time")
    selected = [raw_values[i] for i in indexes]
    if any(value is None for value in selected) and not allow_missing:
        raise WeatherDataError(f"hourly.{field} contains missing data in target window")
    selected = [value for value in selected if value is not None]
    if not selected:
        raise WeatherDataError(f"hourly.{field} contains no usable data in target window")
    try:
        return [float(value) for value in selected]
    except (TypeError, ValueError) as exc:
        raise WeatherDataError(f"hourly.{field} contains non-numeric data") from exc


def _value_for_index(
    hourly: Mapping[str, Any],
    field: str,
    index: int,
    expected_len: int,
    *,
    allow_missing: bool = False,
) -> float | None:
    raw_values = hourly.get(field)
    if not isinstance(raw_values, list) or len(raw_values) != expected_len:
        raise WeatherDataError(f"hourly.{field} is missing or length does not match hourly.time")
    value = raw_values[index]
    if value is None:
        if allow_missing:
            return None
        raise WeatherDataError(f"hourly.{field} contains missing data around sunset")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise WeatherDataError(f"hourly.{field} contains non-numeric data") from exc


def _optional_int(value: float | None) -> int | None:
    return None if value is None else int(value)


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 1)


def _circular_mean_degrees(values: list[float]) -> float:
    sin_sum = sum(math.sin(math.radians(value)) for value in values)
    cos_sum = sum(math.cos(math.radians(value)) for value in values)
    if abs(sin_sum) < 1e-12 and abs(cos_sum) < 1e-12:
        return round(values[-1] % 360, 1)
    angle = math.degrees(math.atan2(sin_sum, cos_sum)) % 360
    return round(angle, 1)


def _representative_weather_code(values: list[float]) -> int:
    codes = [int(value) for value in values]
    rain_codes = [code for code in codes if code in RAIN_WEATHER_CODES]
    if rain_codes:
        return max(rain_codes)
    return max(codes)
