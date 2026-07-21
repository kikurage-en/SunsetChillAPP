from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from zushi_chill.models import JmaPrecipitationForecast

JMA_FORECAST_URL = "https://www.jma.go.jp/bosai/forecast/data/forecast/{office_code}.json"


class JmaForecastError(RuntimeError):
    """気象庁の短期予報を安全に取得・解釈できない場合に送出する。"""


class JmaForecastClient:
    def __init__(self, *, timeout: int = 20, retries: int = 3, backoff_seconds: float = 1.0):
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds

    def fetch_precipitation_probability(
        self,
        *,
        office_code: str,
        area_code: str,
        target_time: datetime,
    ) -> JmaPrecipitationForecast:
        url = JMA_FORECAST_URL.format(office_code=office_code)
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                with urlopen(url, timeout=self.timeout) as response:
                    if response.status >= 400:
                        raise JmaForecastError(
                            f"JMA forecast returned HTTP {response.status}"
                        )
                    payload = json.loads(response.read().decode("utf-8"))
                return parse_jma_precipitation_probability(
                    payload,
                    area_code=area_code,
                    target_time=target_time,
                )
            except (
                HTTPError,
                URLError,
                TimeoutError,
                json.JSONDecodeError,
                JmaForecastError,
            ) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
        raise JmaForecastError(
            f"JMA forecast fetch failed after {self.retries} attempts"
        ) from last_error


def parse_jma_precipitation_probability(
    payload: Any,
    *,
    area_code: str,
    target_time: datetime,
) -> JmaPrecipitationForecast:
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)) or not payload:
        raise JmaForecastError("JMA forecast payload must be a non-empty list")
    short_term = payload[0]
    if not isinstance(short_term, Mapping):
        raise JmaForecastError("JMA short-term forecast must be an object")
    report_time = _parse_datetime(short_term.get("reportDatetime"), "reportDatetime")
    for series in short_term.get("timeSeries", []):
        if not isinstance(series, Mapping):
            continue
        starts_raw = series.get("timeDefines")
        if not isinstance(starts_raw, list):
            continue
        starts = [_parse_datetime(value, "timeDefines") for value in starts_raw]
        for item in series.get("areas", []):
            if not isinstance(item, Mapping):
                continue
            area = item.get("area")
            if not isinstance(area, Mapping) or str(area.get("code")) != area_code:
                continue
            pops = item.get("pops")
            if not isinstance(pops, list) or len(pops) != len(starts):
                continue
            for index, period_start in enumerate(starts):
                period_end = period_start + timedelta(hours=6)
                if period_start <= target_time < period_end:
                    try:
                        probability = int(pops[index])
                    except (TypeError, ValueError) as exc:
                        raise JmaForecastError("JMA precipitation probability is invalid") from exc
                    if not 0 <= probability <= 100:
                        raise JmaForecastError(
                            "JMA precipitation probability must be between 0 and 100"
                        )
                    return JmaPrecipitationForecast(
                        probability=probability,
                        period_start=period_start,
                        period_end=period_end,
                        area_name=str(area.get("name") or area_code),
                        report_time=report_time,
                    )
    raise JmaForecastError(
        "JMA forecast has no precipitation period for area "
        f"{area_code} at {target_time.isoformat()}"
    )


def _parse_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise JmaForecastError(f"JMA {field_name} must be an ISO datetime string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise JmaForecastError(f"JMA {field_name} is invalid: {value}") from exc
    if parsed.tzinfo is None:
        raise JmaForecastError(f"JMA {field_name} must include a timezone")
    return parsed
