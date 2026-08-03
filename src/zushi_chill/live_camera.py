from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

LOGGER = logging.getLogger(__name__)


class LiveCameraError(RuntimeError):
    """Raised when a live camera image cannot be captured."""


@dataclass(frozen=True)
class LiveCameraFrame:
    path: Path
    captured_at: datetime


def build_capture_relative_path(run_time: datetime) -> str:
    return f"live-camera/{run_time.date().isoformat()}/{run_time.strftime('%H%M')}.jpg"


def build_capture_url(base_url: str, relative_path: str) -> str:
    normalized_base_url = base_url.strip().rstrip("/")
    normalized_path = relative_path.strip().lstrip("/")
    if not normalized_base_url:
        return ""
    return f"{normalized_base_url}/{normalized_path}"


def capture_live_camera_image(
    *,
    live_camera_url: str,
    output_path: str | Path,
    live_camera_video_id: str = "",
    timeout_seconds: int = 20,
    youtube_cookies_path: str = "",
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    stream_url = _resolve_stream_url(
        live_camera_url,
        timeout_seconds=timeout_seconds,
        youtube_cookies_path=youtube_cookies_path,
    )
    if stream_url and _capture_stream_frame(
        stream_url,
        output_path=output,
        timeout_seconds=timeout_seconds,
    ):
        return

    if live_camera_video_id and _capture_youtube_thumbnail(
        live_camera_video_id,
        output_path=output,
        timeout_seconds=timeout_seconds,
    ):
        return

    raise LiveCameraError("Live camera image capture failed")


def capture_live_camera_sequence(
    *,
    live_camera_url: str,
    output_directory: str | Path,
    capture_started_at: datetime,
    duration_seconds: int,
    interval_seconds: int,
    fallback_interval_seconds: int | None = None,
    live_camera_video_id: str = "",
    timeout_seconds: int = 20,
    youtube_cookies_path: str = "",
) -> tuple[LiveCameraFrame, ...]:
    """Capture live-camera frames throughout one bounded observation window.

    The stream URL is resolved once and one ffmpeg process samples it at the
    requested interval. If the stream is unavailable, live thumbnails are
    fetched at ``fallback_interval_seconds`` (or the stream cadence when it is
    omitted). Existing ``frame-*.jpg`` files in the target directory are
    generated retry artifacts and are replaced.
    """
    if capture_started_at.tzinfo is None:
        raise ValueError("capture_started_at must include a timezone")
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if fallback_interval_seconds is not None and fallback_interval_seconds <= 0:
        raise ValueError("fallback_interval_seconds must be positive")

    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    for old_frame in output.glob("frame-*.jpg"):
        old_frame.unlink(missing_ok=True)

    stream_frame_count = max(1, round(duration_seconds / interval_seconds) + 1)
    stream_url = _resolve_stream_url(
        live_camera_url,
        timeout_seconds=timeout_seconds,
        youtube_cookies_path=youtube_cookies_path,
    )
    if stream_url:
        frames = _capture_stream_sequence(
            stream_url,
            output_directory=output,
            capture_started_at=capture_started_at,
            frame_count=stream_frame_count,
            interval_seconds=interval_seconds,
            timeout_seconds=timeout_seconds,
        )
        if frames:
            return frames

    if live_camera_video_id:
        thumbnail_interval_seconds = fallback_interval_seconds or interval_seconds
        thumbnail_frame_count = max(
            1,
            round(duration_seconds / thumbnail_interval_seconds) + 1,
        )
        frames = _capture_thumbnail_sequence(
            live_camera_video_id,
            output_directory=output,
            capture_started_at=capture_started_at,
            frame_count=thumbnail_frame_count,
            interval_seconds=thumbnail_interval_seconds,
            duration_seconds=duration_seconds,
            timeout_seconds=timeout_seconds,
        )
        if frames:
            return frames

    raise LiveCameraError("Live camera sequence capture failed")


def _resolve_stream_url(
    live_camera_url: str,
    *,
    timeout_seconds: int,
    youtube_cookies_path: str = "",
) -> str:
    if not live_camera_url.strip():
        return ""
    command = [
        "yt-dlp",
        "--remote-components",
        "ejs:github",
        "--js-runtimes",
        "node",
        "--no-playlist",
        "--format",
        "best[protocol^=m3u8]/best",
        "--get-url",
    ]
    if youtube_cookies_path:
        command.extend(
            [
                "--cookies",
                youtube_cookies_path,
                "--extractor-args",
                "youtube:player_client=mweb",
            ]
        )
    command.append(live_camera_url.strip())
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOGGER.warning("Live camera stream URL could not be resolved: %s", exc)
        return ""
    if completed.returncode != 0:
        LOGGER.warning(
            "Live camera stream URL could not be resolved: %s",
            completed.stderr.strip(),
        )
        return ""
    return completed.stdout.splitlines()[0].strip() if completed.stdout.splitlines() else ""


def _capture_stream_frame(
    stream_url: str, *, output_path: Path, timeout_seconds: int
) -> bool:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        stream_url,
        "-frames:v",
        "1",
        str(output_path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOGGER.warning("Live camera stream capture failed: %s", exc)
        return False
    if completed.returncode != 0:
        LOGGER.warning("Live camera stream capture failed: %s", completed.stderr.strip())
        return False
    return output_path.exists() and output_path.stat().st_size > 0


def _capture_stream_sequence(
    stream_url: str,
    *,
    output_directory: Path,
    capture_started_at: datetime,
    frame_count: int,
    interval_seconds: int,
    timeout_seconds: int,
) -> tuple[LiveCameraFrame, ...]:
    output_directory.mkdir(parents=True, exist_ok=True)
    pattern = output_directory / "frame-%03d.jpg"
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        stream_url,
        "-vf",
        f"fps=1/{interval_seconds}",
        "-frames:v",
        str(frame_count),
        "-q:v",
        "2",
        str(pattern),
    ]
    capture_duration = (frame_count - 1) * interval_seconds
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=capture_duration + interval_seconds + timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOGGER.warning("Live camera stream sequence capture failed: %s", exc)
        paths = _captured_sequence_paths(output_directory)
        return _sequence_frames(
            paths,
            capture_started_at=capture_started_at,
            interval_seconds=interval_seconds,
        )
    paths = _captured_sequence_paths(output_directory)
    if completed.returncode != 0:
        LOGGER.warning(
            "Live camera stream sequence capture returned %s after %s frame(s): %s",
            completed.returncode,
            len(paths),
            completed.stderr.strip(),
        )
    return _sequence_frames(
        paths,
        capture_started_at=capture_started_at,
        interval_seconds=interval_seconds,
    )


def _capture_thumbnail_sequence(
    video_id: str,
    *,
    output_directory: Path,
    capture_started_at: datetime,
    frame_count: int,
    interval_seconds: int,
    duration_seconds: int,
    timeout_seconds: int,
) -> tuple[LiveCameraFrame, ...]:
    started = time.monotonic()
    captured: list[LiveCameraFrame] = []
    for index in range(frame_count):
        target_elapsed = min(index * interval_seconds, duration_seconds)
        remaining = target_elapsed - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)
        output_path = output_directory / f"frame-{index + 1:03d}.jpg"
        if _capture_youtube_thumbnail(
            video_id,
            output_path=output_path,
            timeout_seconds=timeout_seconds,
            cache_buster=str(time.time_ns()),
        ):
            captured.append(
                LiveCameraFrame(
                    path=output_path,
                    captured_at=capture_started_at
                    + timedelta(seconds=index * interval_seconds),
                )
            )
    return tuple(captured)


def _captured_sequence_paths(output_directory: Path) -> list[Path]:
    return [
        path
        for path in sorted(output_directory.glob("frame-*.jpg"))
        if path.is_file() and path.stat().st_size > 0
    ]


def _sequence_frames(
    paths: list[Path], *, capture_started_at: datetime, interval_seconds: int
) -> tuple[LiveCameraFrame, ...]:
    return tuple(
        LiveCameraFrame(
            path=path,
            captured_at=capture_started_at + timedelta(seconds=index * interval_seconds),
        )
        for index, path in enumerate(paths)
    )


def _capture_youtube_thumbnail(
    video_id: str,
    *,
    output_path: Path,
    timeout_seconds: int,
    cache_buster: str = "",
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    for thumbnail_url in _youtube_thumbnail_urls(video_id):
        if cache_buster:
            thumbnail_url = f"{thumbnail_url}?zushi_chill={cache_buster}"
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            break
        try:
            with urlopen(thumbnail_url, timeout=remaining_seconds) as response:
                image = response.read()
        except (URLError, TimeoutError, OSError) as exc:
            LOGGER.warning("YouTube thumbnail fetch failed for %s: %s", thumbnail_url, exc)
            continue
        if image:
            output_path.write_bytes(image)
            LOGGER.info("Captured fallback thumbnail: %s", thumbnail_url)
            return True
    return False


def _youtube_thumbnail_urls(video_id: str) -> list[str]:
    normalized_video_id = video_id.strip()
    if not normalized_video_id:
        return []
    return [
        f"https://i.ytimg.com/vi/{normalized_video_id}/maxresdefault_live.jpg",
        f"https://i.ytimg.com/vi/{normalized_video_id}/hqdefault_live.jpg",
        f"https://i.ytimg.com/vi/{normalized_video_id}/maxresdefault.jpg",
        f"https://i.ytimg.com/vi/{normalized_video_id}/hqdefault.jpg",
    ]
