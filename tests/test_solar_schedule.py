from datetime import date

from zushi_chill.solar_schedule import local_sunset_time, observation_times


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
