from __future__ import annotations

from datetime import date, datetime, timedelta
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


def observation_times(
    *,
    target_date: date,
    latitude: float,
    longitude: float,
    timezone: str,
    afterglow_offset_minutes: int = 20,
) -> dict[str, datetime]:
    if afterglow_offset_minutes <= 0:
        raise ValueError("afterglow_offset_minutes must be positive")
    sunset_time = local_sunset_time(
        target_date=target_date,
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
    )
    return {
        "sunset": sunset_time,
        "afterglow": sunset_time + timedelta(minutes=afterglow_offset_minutes),
    }
