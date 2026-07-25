from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from zushi_chill import live_camera
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


def test_capture_live_camera_image_uses_stream_frame(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[0] == "yt-dlp":
            return subprocess.CompletedProcess(command, 0, stdout="https://stream.example/live.m3u8\n")
        Path(command[-1]).write_bytes(b"jpeg")
        return subprocess.CompletedProcess(command, 0, stderr="")

    monkeypatch.setattr(live_camera.subprocess, "run", fake_run)

    output_path = tmp_path / "public/live.jpg"
    capture_source = live_camera.capture_live_camera_image(
        live_camera_url="https://youtube.example/watch",
        live_camera_video_id="video-id",
        output_path=output_path,
    )

    assert output_path.read_bytes() == b"jpeg"
    assert capture_source == "stream"
    assert calls[0][0] == "yt-dlp"
    assert calls[1][0] == "ffmpeg"


def test_capture_live_camera_image_falls_back_to_youtube_thumbnail(tmp_path, monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stderr="failed")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def read(self):
            return b"thumbnail"

    monkeypatch.setattr(live_camera.subprocess, "run", fake_run)
    monkeypatch.setattr(live_camera, "urlopen", lambda url, timeout: FakeResponse())

    output_path = tmp_path / "public/live.jpg"
    capture_source = live_camera.capture_live_camera_image(
        live_camera_url="https://youtube.example/watch",
        live_camera_video_id="video-id",
        output_path=output_path,
    )

    assert output_path.read_bytes() == b"thumbnail"
    assert capture_source == "youtube_live_thumbnail"
