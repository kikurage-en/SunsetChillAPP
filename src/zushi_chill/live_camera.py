from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

LOGGER = logging.getLogger(__name__)


class LiveCameraError(RuntimeError):
    """Raised when a live camera image cannot be captured."""


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
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    stream_url = _resolve_stream_url(live_camera_url, timeout_seconds=timeout_seconds)
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


def _resolve_stream_url(live_camera_url: str, *, timeout_seconds: int) -> str:
    if not live_camera_url.strip():
        return ""
    command = [
        "yt-dlp",
        "--no-playlist",
        "--format",
        "best[protocol^=m3u8]/best",
        "--get-url",
        live_camera_url.strip(),
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


def _capture_youtube_thumbnail(
    video_id: str, *, output_path: Path, timeout_seconds: int
) -> bool:
    for thumbnail_url in _youtube_thumbnail_urls(video_id):
        try:
            with urlopen(thumbnail_url, timeout=timeout_seconds) as response:
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
