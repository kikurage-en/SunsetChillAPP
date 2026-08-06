from __future__ import annotations

import subprocess
from datetime import datetime, timedelta
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
    live_camera.capture_live_camera_image(
        live_camera_url="https://youtube.example/watch",
        live_camera_video_id="video-id",
        output_path=output_path,
        youtube_cookies_path="/var/lib/zushi-chill/secrets/youtube.txt",
    )

    assert output_path.read_bytes() == b"jpeg"
    assert calls[0][0] == "yt-dlp"
    assert calls[0][1:5] == [
        "--remote-components",
        "ejs:github",
        "--js-runtimes",
        "node",
    ]
    assert calls[0][calls[0].index("--cookies") + 1] == (
        "/var/lib/zushi-chill/secrets/youtube.txt"
    )
    assert calls[0][calls[0].index("--extractor-args") + 1] == (
        "youtube:player_client=mweb"
    )
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
    live_camera.capture_live_camera_image(
        live_camera_url="https://youtube.example/watch",
        live_camera_video_id="video-id",
        output_path=output_path,
    )

    assert output_path.read_bytes() == b"thumbnail"


def test_capture_live_camera_sequence_samples_one_stream_every_minute(
    tmp_path,
    monkeypatch,
):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "yt-dlp":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="https://stream.example/live.m3u8\n",
            )
        pattern = command[-1]
        frame_count = int(command[command.index("-frames:v") + 1])
        for index in range(1, frame_count + 1):
            Path(pattern.replace("%03d", f"{index:03d}")).write_bytes(
                f"jpeg-{index}".encode()
            )
        return subprocess.CompletedProcess(command, 0, stderr="")

    monkeypatch.setattr(live_camera.subprocess, "run", fake_run)
    started_at = datetime(2026, 7, 26, 19, 5, tzinfo=ZoneInfo("Asia/Tokyo"))

    frames = live_camera.capture_live_camera_sequence(
        live_camera_url="https://youtube.example/watch",
        live_camera_video_id="video-id",
        output_directory=tmp_path / "candidates",
        capture_started_at=started_at,
        duration_seconds=600,
        interval_seconds=60,
    )

    assert len(frames) == 11
    assert frames[0].captured_at == started_at
    assert frames[-1].captured_at == started_at + timedelta(minutes=10)
    ffmpeg_command, ffmpeg_kwargs = calls[1]
    assert ffmpeg_command[ffmpeg_command.index("-vf") + 1] == "fps=1/60"
    assert ffmpeg_command[ffmpeg_command.index("-frames:v") + 1] == "11"
    assert ffmpeg_kwargs["timeout"] > 600


def test_capture_live_camera_sequence_falls_back_to_cache_busted_thumbnails(
    tmp_path,
    monkeypatch,
):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stderr="stream blocked")

    class FakeResponse:
        def __init__(self, image):
            self.image = image

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def read(self):
            return self.image

    urls = []

    def fake_urlopen(url, timeout):
        urls.append(url)
        return FakeResponse(f"thumbnail-{len(urls)}".encode())

    monkeypatch.setattr(live_camera.subprocess, "run", fake_run)
    monkeypatch.setattr(live_camera, "urlopen", fake_urlopen)
    monkeypatch.setattr(live_camera.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(live_camera.time, "sleep", lambda seconds: None)
    started_at = datetime(2026, 7, 26, 19, 5, tzinfo=ZoneInfo("Asia/Tokyo"))

    frames = live_camera.capture_live_camera_sequence(
        live_camera_url="https://youtube.example/watch",
        live_camera_video_id="video-id",
        output_directory=tmp_path / "candidates",
        capture_started_at=started_at,
        duration_seconds=60,
        interval_seconds=30,
        fallback_interval_seconds=60,
    )

    assert [frame.path.read_bytes() for frame in frames] == [
        b"thumbnail-1",
        b"thumbnail-2",
    ]
    assert [frame.captured_at for frame in frames] == [
        started_at,
        started_at + timedelta(seconds=60),
    ]
    cache_busters = [url.rsplit("=", 1)[-1] for url in urls]
    assert len(cache_busters) == 2
    assert len(set(cache_busters)) == 2
