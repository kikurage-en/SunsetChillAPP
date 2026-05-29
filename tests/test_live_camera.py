from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from zushi_chill.live_camera import build_capture_relative_path, build_capture_url


def test_build_capture_relative_path_uses_run_date_and_time():
    run_time = datetime(2026, 6, 1, 17, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    assert build_capture_relative_path(run_time) == "live-camera/2026-06-01/1700.jpg"


def test_build_capture_url_normalizes_slashes():
    assert (
        build_capture_url(" https://example.github.io/SunsetChillAPP/ ", "/live-camera/test.jpg")
        == "https://example.github.io/SunsetChillAPP/live-camera/test.jpg"
    )


def test_build_capture_url_returns_blank_without_base_url():
    assert build_capture_url(" ", "live-camera/test.jpg") == ""
