from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from zushi_chill.config import ConfigError, Settings
from zushi_chill.weather_client import OpenMeteoClient, parse_forecast

LOGGER = logging.getLogger(__name__)


def compute_sunset_eta(
    settings: Settings,
    *,
    target_date: date,
    offset_minutes: int,
    client: OpenMeteoClient | None = None,
) -> datetime:
    """Return the local datetime ``offset_minutes`` after the day's sunset.

    Uses the same Open-Meteo fetch + parse path as the main run so the sunset
    time matches what the scoring run will see.
    """
    client = client or OpenMeteoClient()
    payload = client.fetch_forecast(
        latitude=settings.latitude,
        longitude=settings.longitude,
        timezone=settings.timezone,
        target_date=target_date,
    )
    summary = parse_forecast(
        payload,
        location_name=settings.location_name,
        latitude=settings.latitude,
        longitude=settings.longitude,
        timezone=settings.timezone,
        allow_missing_fields=settings.allow_missing_hourly_fields,
    )
    return summary.sunset_time + timedelta(minutes=offset_minutes)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        settings = Settings.from_env()
        logging.basicConfig(
            level=getattr(logging, settings.log_level.upper(), logging.INFO),
            format="%(levelname)s:%(name)s:%(message)s",
        )
        tz = ZoneInfo(settings.timezone)
        if args.date:
            try:
                target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
            except ValueError as exc:
                raise ConfigError("--date must be YYYY-MM-DD") from exc
        else:
            target_date = datetime.now(tz).date()

        eta = compute_sunset_eta(
            settings,
            target_date=target_date,
            offset_minutes=args.minutes,
        )
        # stdout には HH:MM のみを出す(VPS の at 予約が $() で取り込むため)。
        print(eta.strftime("%H:%M"))
        return 0
    except Exception as exc:
        logging.getLogger(__name__).exception("Sunset ETA computation failed: %s", exc)
        return 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print HH:MM at the given offset after today's sunset in Zushi."
    )
    parser.add_argument("--date", help="Target date in YYYY-MM-DD. Defaults to today in TIMEZONE.")
    parser.add_argument(
        "--minutes",
        type=int,
        default=20,
        help="Minutes after sunset to schedule the live-camera capture. Defaults to 20.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())
