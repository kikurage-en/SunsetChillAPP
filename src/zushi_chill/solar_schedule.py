from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import sunset


def local_sunset_time(
    *,
    target_date: date,
    latitude: float,
    longitude: float,
    timezone: str,
) -> datetime:
    """Return the network-independent geometric sunset, rounded down to a minute."""
    value = sunset(
        Observer(latitude=latitude, longitude=longitude),
        date=target_date,
        tzinfo=ZoneInfo(timezone),
    )
    return value.replace(second=0, microsecond=0)


def evening_forecast_time(
    sunset_time: datetime,
    *,
    lead_minutes: int,
    latest: time | None = None,
) -> datetime:
    """日没 ``lead_minutes`` 分前の夕方予測時刻。``latest`` があればそれより遅くしない。

    固定17:00の予測は2026-10-21〜2027-01-23に日没後になり、10月上旬でも日没15分前
    だった。2026-10-09の再評価ではVision予測が純式に勝つのは日没90分以内だけだった。
    """
    if lead_minutes <= 0:
        raise ValueError("lead_minutes must be positive")
    forecast_time = sunset_time - timedelta(minutes=lead_minutes)
    if latest is not None and forecast_time.timetz().replace(tzinfo=None) > latest:
        forecast_time = forecast_time.replace(
            hour=latest.hour, minute=latest.minute, second=0, microsecond=0
        )
    return forecast_time


def observation_times(
    *,
    target_date: date,
    latitude: float,
    longitude: float,
    timezone: str,
    afterglow_offset_minutes: int = 20,
    evening_forecast_lead_minutes: int | None = None,
    evening_forecast_latest: time | None = None,
) -> dict[str, datetime]:
    if afterglow_offset_minutes <= 0:
        raise ValueError("afterglow_offset_minutes must be positive")
    sunset_time = local_sunset_time(
        target_date=target_date,
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
    )
    times = {
        "sunset": sunset_time,
        "afterglow": sunset_time + timedelta(minutes=afterglow_offset_minutes),
    }
    if evening_forecast_lead_minutes:
        times["forecast"] = evening_forecast_time(
            sunset_time,
            lead_minutes=evening_forecast_lead_minutes,
            latest=evening_forecast_latest,
        )
    return times
