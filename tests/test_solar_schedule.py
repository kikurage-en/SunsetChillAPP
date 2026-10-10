from datetime import date, time

from zushi_chill.solar_schedule import (
    evening_forecast_time,
    local_sunset_time,
    observation_times,
)


def test_local_sunset_matches_recorded_zushi_time_without_network():
    sunset = local_sunset_time(
        target_date=date(2026, 7, 26),
        latitude=35.2956,
        longitude=139.5736,
        timezone="Asia/Tokyo",
    )

    assert sunset.isoformat() == "2026-07-26T18:50:00+09:00"


def test_observation_times_include_twenty_minute_afterglow():
    times = observation_times(
        target_date=date(2026, 7, 26),
        latitude=35.2956,
        longitude=139.5736,
        timezone="Asia/Tokyo",
        afterglow_offset_minutes=20,
    )

    assert times["sunset"].strftime("%H:%M") == "18:50"
    assert times["afterglow"].strftime("%H:%M") == "19:10"


def test_evening_forecast_tracks_sunset_and_can_be_capped():
    times = observation_times(
        target_date=date(2026, 10, 10),
        latitude=35.2956,
        longitude=139.5736,
        timezone="Asia/Tokyo",
        evening_forecast_lead_minutes=60,
    )
    assert times["forecast"] == times["sunset"].replace(hour=times["sunset"].hour - 1)

    summer_sunset = local_sunset_time(
        target_date=date(2026, 6, 21),
        latitude=35.2956,
        longitude=139.5736,
        timezone="Asia/Tokyo",
    )
    assert evening_forecast_time(summer_sunset, lead_minutes=60).strftime("%H:%M") == "17:59"
    assert (
        evening_forecast_time(summer_sunset, lead_minutes=60, latest=time(17, 0)).strftime(
            "%H:%M"
        )
        == "17:00"
    )


def test_observation_times_omit_forecast_when_disabled():
    times = observation_times(
        target_date=date(2026, 10, 10),
        latitude=35.2956,
        longitude=139.5736,
        timezone="Asia/Tokyo",
    )
    assert "forecast" not in times
