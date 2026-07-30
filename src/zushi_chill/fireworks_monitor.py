from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from zushi_chill.comment_variants import select_comment_variant
from zushi_chill.comment_voice import apply_comment_voice
from zushi_chill.line_client import LineClient, observation_retry_key
from zushi_chill.vision_client import GEMINI_API_BASE

LOGGER = logging.getLogger(__name__)

EVENT_DATE = "2026-07-30"
EVENT_LABEL = "逗子海岸シークレット花火"
DEFAULT_TIMEZONE = "Asia/Tokyo"
DEFAULT_SAMPLE_FPS = 2.0
DETECTION_WIDTH = 96
DETECTION_HEIGHT = 54
SKY_FRACTION = 0.82
BRIGHTNESS_DELTA = 45
BRIGHTNESS_FLOOR = 145
MIN_CHANGED_PIXELS = 5
GLOBAL_CHANGE_DELTA = 38
MAX_GLOBAL_CHANGE_RATIO = 0.42
BURST_QUIET_SECONDS = 3.0
BURST_MAX_SECONDS = 8.0
MIN_ANALYSIS_INTERVAL_SECONDS = 8.0
MIN_SEND_INTERVAL_SECONDS = 20.0
MAX_ANALYSES = 120
MAX_IMAGES = 6
FRAME_CLEANUP_LAG = 24
MIN_VISION_CONFIDENCE = 70
MIN_VISION_QUALITY = 35

_FIREWORKS_COMMENT_VARIANTS = (
    "わあっ、逗子の夜空に大きな花火が咲いたっピ！",
    "やったっピ！海の上がきらきらの花火でいっぱいっピ！",
    "おおっ、夜空にまんまるの花火を見つけたっピ！",
    "海辺の空がぱっと明るくなったっピ！すごい花火っピ！",
    "きれいな花火が夜空いっぱいに広がったっピ！",
    "見つけたっピ！逗子の海に大きな花火が上がったっピ！",
)

_FIREWORKS_PROMPT_TEMPLATE = """\
以下は逗子海岸ライブカメラから自動抽出した画像です。
実際の打ち上げ花火が明瞭に写っているかを厳しく判定してください。

次のJSONだけを返してください（説明やコードブロックを付けない）:
{{
  "fireworks_visible": true または false,
  "confidence": 判定確信度を表す0-100の整数,
  "quality_score": 花火写真としての見栄えを表す0-100の整数,
  "comment": 花火が写っている場合だけ50文字以内の日本語コメント。写っていなければ空文字
}}

判定基準:
- 空中で開いた光の球、放射状の光跡、打ち上げ花火の破裂が確認できる場合だけ true
- 街灯、船の灯り、水面反射、月、夕焼け、稲妻、圧縮ノイズは false
- 小さな光点だけで花火と断定しない

comment の書き方:
- 既存の定期通知と同じ、無邪気で親しみのある口調にする
- 画像から確認できる事実だけを書く
- すべての文末を「っピ」にする
- 「っピ！」、「っピ。」、「っピ……。」のように書き、句点を重ねない
- 今回の話し方は「{tone}」。ただし、画像の事実や判定は変えない
"""

_FIREWORKS_TONE_VARIANTS = (
    "花火を見つけて思わず声が出たように、明るく驚いて話す",
    "画像を一生懸命に観察して、見つけた花火をうれしそうに報告する",
    "海辺の夜空をじっと眺めてから、発見を無邪気に喜ぶ",
)


class FireworksMonitorError(RuntimeError):
    """Raised when the one-off fireworks monitor cannot continue."""


@dataclass(frozen=True)
class FrameScore:
    score: int
    changed_pixels: int
    peak_delta: int
    global_change_ratio: float


@dataclass(frozen=True)
class BurstCandidate:
    frame_index: int
    score: int


@dataclass(frozen=True)
class FireworksAnalysis:
    fireworks_visible: bool
    confidence: int
    quality_score: int
    comment: str


@dataclass(frozen=True)
class MonitorResult:
    frames_seen: int
    candidates_analyzed: int
    images_sent: int


class BurstTracker:
    """Group consecutive bright-change frames and retain the strongest frame."""

    def __init__(
        self,
        *,
        sample_fps: float,
        quiet_seconds: float,
        max_burst_seconds: float = BURST_MAX_SECONDS,
    ) -> None:
        if sample_fps <= 0:
            raise ValueError("sample_fps must be positive")
        if quiet_seconds <= 0:
            raise ValueError("quiet_seconds must be positive")
        if max_burst_seconds <= 0:
            raise ValueError("max_burst_seconds must be positive")
        self.quiet_frames = max(1, round(sample_fps * quiet_seconds))
        self.max_burst_frames = max(1, round(sample_fps * max_burst_seconds))
        self._best: BurstCandidate | None = None
        self._burst_start_frame: int | None = None
        self._last_trigger_frame: int | None = None

    @property
    def protected_frame_index(self) -> int | None:
        return self._best.frame_index if self._best is not None else None

    def observe(self, frame_index: int, frame_score: int) -> BurstCandidate | None:
        if frame_score > 0:
            if self._burst_start_frame is None:
                self._burst_start_frame = frame_index
            if self._best is None or frame_score > self._best.score:
                self._best = BurstCandidate(frame_index=frame_index, score=frame_score)
            self._last_trigger_frame = frame_index
            if frame_index - self._burst_start_frame + 1 >= self.max_burst_frames:
                return self.flush()
            return None
        if (
            self._best is not None
            and self._last_trigger_frame is not None
            and frame_index - self._last_trigger_frame >= self.quiet_frames
        ):
            return self.flush()
        return None

    def flush(self) -> BurstCandidate | None:
        candidate = self._best
        self._best = None
        self._burst_start_frame = None
        self._last_trigger_frame = None
        return candidate


def score_fireworks_frame(
    previous_frame: bytes,
    current_frame: bytes,
    *,
    width: int = DETECTION_WIDTH,
    height: int = DETECTION_HEIGHT,
    sky_fraction: float = SKY_FRACTION,
) -> FrameScore:
    """Score newly bright pixels in the sky while rejecting global exposure changes."""
    expected_length = width * height
    if len(previous_frame) != expected_length or len(current_frame) != expected_length:
        raise ValueError(f"grayscale frames must contain exactly {expected_length} bytes")
    if not 0 < sky_fraction <= 1:
        raise ValueError("sky_fraction must be between 0 and 1")

    sky_length = width * max(1, min(height, round(height * sky_fraction)))
    changed_pixels = 0
    global_change_pixels = 0
    weighted_brightness = 0
    peak_delta = 0

    for previous, current in zip(
        previous_frame[:sky_length],
        current_frame[:sky_length],
        strict=True,
    ):
        delta = current - previous
        if abs(delta) >= GLOBAL_CHANGE_DELTA:
            global_change_pixels += 1
        if delta >= BRIGHTNESS_DELTA and current >= BRIGHTNESS_FLOOR:
            changed_pixels += 1
            weighted_brightness += delta + max(0, current - BRIGHTNESS_FLOOR)
            peak_delta = max(peak_delta, delta)

    global_change_ratio = global_change_pixels / sky_length
    if (
        changed_pixels < MIN_CHANGED_PIXELS
        or global_change_ratio > MAX_GLOBAL_CHANGE_RATIO
    ):
        score = 0
    else:
        score = weighted_brightness + changed_pixels * 50 + peak_delta * 2
    return FrameScore(
        score=score,
        changed_pixels=changed_pixels,
        peak_delta=peak_delta,
        global_change_ratio=global_change_ratio,
    )


def build_fireworks_prompt(captured_at: datetime) -> str:
    tone = select_comment_variant(
        captured_at.date().isoformat(),
        captured_at.strftime("%H:%M"),
        "fireworks-vision-tone",
        _FIREWORKS_TONE_VARIANTS,
    )
    return _FIREWORKS_PROMPT_TEMPLATE.format(tone=tone)


def build_fireworks_comment(captured_at: datetime, ordinal: int) -> str:
    selected = select_comment_variant(
        captured_at.date().isoformat(),
        captured_at.strftime("%H:%M"),
        f"fireworks-comment-{ordinal}",
        _FIREWORKS_COMMENT_VARIANTS,
    )
    return apply_comment_voice(selected)


def build_line_text(captured_at: datetime, comment: str) -> str:
    voiced_comment = apply_comment_voice(comment)
    return (
        f"🎆 {EVENT_LABEL}\n"
        f"{captured_at.strftime('%H:%M:%S')} 撮影\n"
        f"{voiced_comment}"
    )


def analyze_fireworks_image(
    *,
    image_path: Path,
    captured_at: datetime,
    api_key: str,
    model: str = "gemini-2.5-flash",
    timeout_seconds: int = 30,
) -> FireworksAnalysis:
    if not api_key.strip():
        raise FireworksMonitorError("VISION_API_KEY is required")
    try:
        image_bytes = image_path.read_bytes()
    except OSError as exc:
        raise FireworksMonitorError(f"Failed to read candidate image: {exc}") from exc
    if not image_bytes:
        raise FireworksMonitorError("Candidate image is empty")

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    },
                    {"text": build_fireworks_prompt(captured_at)},
                ]
            }
        ],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    request = Request(
        f"{GEMINI_API_BASE}/{model}:generateContent?key={api_key.strip()}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if response.status >= 400:
                body = response.read().decode("utf-8", errors="replace")
                raise FireworksMonitorError(
                    f"Gemini returned HTTP {response.status}: {body}"
                )
            raw = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise FireworksMonitorError(f"Gemini fireworks analysis failed: {exc}") from exc
    return _parse_fireworks_analysis(raw)


def _parse_fireworks_analysis(raw: Any) -> FireworksAnalysis:
    try:
        text = raw["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise FireworksMonitorError(
            f"Unexpected Gemini fireworks response: {raw}"
        ) from exc

    visible = parsed.get("fireworks_visible")
    if not isinstance(visible, bool):
        raise FireworksMonitorError(
            f"Gemini fireworks_visible must be boolean: {parsed}"
        )
    confidence = _bounded_score(parsed, "confidence")
    quality_score = _bounded_score(parsed, "quality_score")
    raw_comment = str(parsed.get("comment", "")).strip()
    comment = apply_comment_voice(raw_comment) if raw_comment else ""
    return FireworksAnalysis(
        fireworks_visible=visible,
        confidence=confidence,
        quality_score=quality_score,
        comment=comment,
    )


def _bounded_score(parsed: dict[str, Any], key: str) -> int:
    try:
        value = int(parsed[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise FireworksMonitorError(
            f"Gemini fireworks response has invalid {key}: {parsed}"
        ) from exc
    return max(0, min(100, value))


def _ffmpeg_command(
    *,
    stream_url: str,
    frames_dir: Path,
    duration_seconds: int,
    sample_fps: float,
) -> list[str]:
    filter_graph = (
        "[0:v:0]split=2[archive][detect];"
        f"[archive]fps={sample_fps},"
        "scale=1280:-2:force_original_aspect_ratio=decrease[archive_out];"
        f"[detect]fps={sample_fps},"
        f"scale={DETECTION_WIDTH}:{DETECTION_HEIGHT}:flags=area,"
        "format=gray[detect_out]"
    )
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "5",
        "-i",
        stream_url,
        "-filter_complex",
        filter_graph,
        "-map",
        "[archive_out]",
        "-t",
        str(duration_seconds),
        "-q:v",
        "4",
        "-fps_mode",
        "vfr",
        str(frames_dir / "%08d.jpg"),
        "-map",
        "[detect_out]",
        "-t",
        str(duration_seconds),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "pipe:1",
    ]


def _resolve_fireworks_stream_url(
    live_camera_url: str,
    *,
    timeout_seconds: int,
) -> str:
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
        raise FireworksMonitorError(
            f"Could not run yt-dlp for the fireworks stream: {exc}"
        ) from exc
    if completed.returncode != 0:
        raise FireworksMonitorError(
            f"Could not resolve the fireworks stream: {completed.stderr.strip()}"
        )
    return completed.stdout.splitlines()[0].strip() if completed.stdout.splitlines() else ""


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def _iter_detection_frames(
    *,
    stream_url: str,
    frames_dir: Path,
    duration_seconds: int,
    sample_fps: float,
) -> Iterator[tuple[int, bytes]]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    command = _ffmpeg_command(
        stream_url=stream_url,
        frames_dir=frames_dir,
        duration_seconds=duration_seconds,
        sample_fps=sample_fps,
    )
    LOGGER.info("Starting fireworks frame monitor for %s seconds", duration_seconds)
    frame_size = DETECTION_WIDTH * DETECTION_HEIGHT
    with tempfile.TemporaryFile() as error_log:
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=error_log,
            )
        except OSError as exc:
            raise FireworksMonitorError(f"Failed to start ffmpeg: {exc}") from exc
        assert process.stdout is not None
        frame_index = 0
        stream_ended = False
        try:
            while True:
                frame = _read_exact(process.stdout, frame_size)
                if not frame:
                    stream_ended = True
                    break
                if len(frame) != frame_size:
                    raise FireworksMonitorError(
                        f"ffmpeg returned a partial detection frame ({len(frame)} bytes)"
                    )
                frame_index += 1
                yield frame_index, frame
        finally:
            process.stdout.close()
            if not stream_ended and process.poll() is None:
                process.terminate()
                try:
                    return_code = process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    return_code = process.wait(timeout=10)
            else:
                return_code = process.wait()
        if stream_ended and return_code != 0:
            error_log.seek(0)
            error_text = error_log.read().decode("utf-8", errors="replace").strip()
            raise FireworksMonitorError(
                f"ffmpeg fireworks monitor failed with exit {return_code}: {error_text}"
            )


def _frame_path(frames_dir: Path, frame_index: int) -> Path:
    return frames_dir / f"{frame_index:08d}.jpg"


def _wait_for_frame_file(
    frames_dir: Path,
    frame_index: int,
    *,
    timeout_seconds: float = 8.0,
) -> Path:
    path = _frame_path(frames_dir, frame_index)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return path
        time.sleep(0.1)
    raise FireworksMonitorError(f"High-resolution candidate frame is missing: {path}")


def _cleanup_frame(frames_dir: Path, frame_index: int) -> None:
    path = _frame_path(frames_dir, frame_index)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        LOGGER.warning("Failed to delete temporary frame %s: %s", path, exc)


def _candidate_time(
    capture_started_at: datetime,
    frame_index: int,
    sample_fps: float,
) -> datetime:
    return capture_started_at + timedelta(seconds=(frame_index - 1) / sample_fps)


def _public_image_url(base_url: str, relative_path: str) -> str:
    normalized_base = base_url.strip().rstrip("/")
    normalized_path = relative_path.strip().lstrip("/")
    if not normalized_base.startswith("https://"):
        raise FireworksMonitorError("FIREWORKS_IMAGE_BASE_URL must start with https://")
    return f"{normalized_base}/{normalized_path}"


def _publish_candidate(
    *,
    source: Path,
    pages_dir: Path,
    relative_path: str,
    captured_at: datetime,
) -> Path:
    destination = pages_dir / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if destination.stat().st_size > 1_000_000:
        raise FireworksMonitorError(
            f"Candidate image exceeds LINE preview limit: {destination.stat().st_size} bytes"
        )

    commands = [
        ["git", "-C", str(pages_dir), "add", relative_path],
        [
            "git",
            "-C",
            str(pages_dir),
            "commit",
            "-m",
            f"archive: fireworks {captured_at.strftime('%Y-%m-%d %H:%M:%S')}",
        ],
        ["git", "-C", str(pages_dir), "push", "origin", "HEAD:pages-images"],
    ]
    for command in commands:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if completed.returncode != 0:
            raise FireworksMonitorError(
                f"Failed to publish fireworks capture: {completed.stderr.strip()}"
            )
    return destination


def _wait_for_public_image(image_url: str, *, timeout_seconds: int = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        request = Request(image_url, headers={"Range": "bytes=0-0"})
        try:
            with urlopen(request, timeout=10) as response:
                if response.status in {200, 206} and response.read(1):
                    return
                last_error = f"HTTP {response.status}"
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise FireworksMonitorError(
        f"Published fireworks image did not become available: {last_error}"
    )


def _send_candidate(
    *,
    line_client: LineClient,
    target_id: str,
    captured_at: datetime,
    comment: str,
    image_url: str,
) -> None:
    line_client.push_text_with_image(
        build_line_text(captured_at, comment),
        image_url=image_url,
        retry_key=observation_retry_key(
            observation_id=(
                f"{EVENT_DATE}:fireworks:{captured_at.strftime('%H%M%S')}"
            ),
            target_id=target_id,
        ),
    )


def _notify_no_capture(line_client: LineClient) -> None:
    line_client.push_text(
        "🎆 逗子海岸シークレット花火\n"
        "監視時間内に、花火がはっきり写った画像を確認できなかったっピ……。",
        retry_key=observation_retry_key(
            observation_id=f"{EVENT_DATE}:fireworks:no-capture",
            target_id=line_client.target_id,
        ),
    )


def _notify_monitor_error(line_client: LineClient, error: Exception) -> None:
    LOGGER.error("Fireworks monitor failed: %s", error)
    line_client.push_text(
        "🎆 逗子海岸シークレット花火\n"
        "ライブ映像の監視中にエラーが起きたっピ……。"
        "GitHub Actionsのログを確認してほしいっピ。",
        retry_key=observation_retry_key(
            observation_id=f"{EVENT_DATE}:fireworks:monitor-error",
            target_id=line_client.target_id,
        ),
    )


def monitor_fireworks(
    *,
    stream_url: str,
    capture_started_at: datetime,
    duration_seconds: int,
    sample_fps: float,
    frames_dir: Path,
    accepted_dir: Path,
    pages_dir: Path,
    image_base_url: str,
    api_key: str,
    vision_model: str,
    line_client: LineClient | None,
    dry_run: bool,
    max_images: int = MAX_IMAGES,
) -> MonitorResult:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if max_images <= 0:
        raise ValueError("max_images must be positive")
    if not dry_run and line_client is None:
        raise FireworksMonitorError("LINE settings are required outside dry-run mode")

    accepted_dir.mkdir(parents=True, exist_ok=True)
    tracker = BurstTracker(
        sample_fps=sample_fps,
        quiet_seconds=BURST_QUIET_SECONDS,
    )
    previous_frame: bytes | None = None
    frames_seen = 0
    analyses = 0
    images_sent = 0
    last_analysis_at: datetime | None = None
    last_sent_at: datetime | None = None
    cleanup_index = 1

    def handle_candidate(candidate: BurstCandidate) -> None:
        nonlocal analyses, images_sent, last_analysis_at, last_sent_at
        captured_at = _candidate_time(
            capture_started_at,
            candidate.frame_index,
            sample_fps,
        )
        if (
            last_analysis_at is not None
            and (captured_at - last_analysis_at).total_seconds()
            < MIN_ANALYSIS_INTERVAL_SECONDS
        ):
            LOGGER.info("Skipping closely spaced candidate at %s", captured_at.isoformat())
            return
        if analyses >= MAX_ANALYSES:
            LOGGER.warning("Reached the fireworks analysis limit")
            return

        candidate_path = _wait_for_frame_file(frames_dir, candidate.frame_index)
        saved_candidate = accepted_dir / (
            f"candidate-{captured_at.strftime('%H%M%S')}-{candidate.frame_index:08d}.jpg"
        )
        shutil.copy2(candidate_path, saved_candidate)
        analyses += 1
        last_analysis_at = captured_at
        try:
            analysis = analyze_fireworks_image(
                image_path=saved_candidate,
                captured_at=captured_at,
                api_key=api_key,
                model=vision_model,
            )
        except FireworksMonitorError as exc:
            LOGGER.warning(
                "Could not analyze fireworks candidate at %s; keeping it for recovery: %s",
                captured_at.isoformat(),
                exc,
            )
            return
        LOGGER.info(
            "Candidate %s: visible=%s confidence=%s quality=%s",
            captured_at.isoformat(),
            analysis.fireworks_visible,
            analysis.confidence,
            analysis.quality_score,
        )
        if (
            not analysis.fireworks_visible
            or analysis.confidence < MIN_VISION_CONFIDENCE
            or analysis.quality_score < MIN_VISION_QUALITY
        ):
            return
        if (
            last_sent_at is not None
            and (captured_at - last_sent_at).total_seconds()
            < MIN_SEND_INTERVAL_SECONDS
        ):
            LOGGER.info("Keeping but not sending closely spaced confirmed fireworks frame")
            return

        comment = analysis.comment or build_fireworks_comment(
            captured_at,
            images_sent + 1,
        )
        if dry_run:
            LOGGER.info(
                "Dry run confirmed fireworks at %s: %s",
                captured_at.isoformat(),
                comment,
            )
        else:
            assert line_client is not None
            relative_path = (
                f"fireworks/{EVENT_DATE}/{captured_at.strftime('%H%M%S')}.jpg"
            )
            _publish_candidate(
                source=saved_candidate,
                pages_dir=pages_dir,
                relative_path=relative_path,
                captured_at=captured_at,
            )
            image_url = _public_image_url(image_base_url, relative_path)
            _wait_for_public_image(image_url)
            _send_candidate(
                line_client=line_client,
                target_id=line_client.target_id,
                captured_at=captured_at,
                comment=comment,
                image_url=image_url,
            )
        images_sent += 1
        last_sent_at = captured_at

    for frame_index, frame in _iter_detection_frames(
        stream_url=stream_url,
        frames_dir=frames_dir,
        duration_seconds=duration_seconds,
        sample_fps=sample_fps,
    ):
        frames_seen = frame_index
        if previous_frame is None:
            previous_frame = frame
            continue
        frame_score = score_fireworks_frame(previous_frame, frame)
        previous_frame = frame
        candidate = tracker.observe(frame_index, frame_score.score)
        if frame_score.score > 0:
            LOGGER.info(
                "Bright sky change at frame %s: score=%s pixels=%s ratio=%.3f",
                frame_index,
                frame_score.score,
                frame_score.changed_pixels,
                frame_score.global_change_ratio,
            )
        if candidate is not None:
            handle_candidate(candidate)
        protected_index = tracker.protected_frame_index
        cleanup_before = frame_index - FRAME_CLEANUP_LAG
        while cleanup_index <= cleanup_before:
            if cleanup_index != protected_index:
                _cleanup_frame(frames_dir, cleanup_index)
            cleanup_index += 1
        if images_sent >= max_images:
            LOGGER.info("Collected the requested %s fireworks images", max_images)
            break

    if images_sent < max_images:
        final_candidate = tracker.flush()
        if final_candidate is not None:
            handle_candidate(final_candidate)
    return MonitorResult(
        frames_seen=frames_seen,
        candidates_analyzed=analyses,
        images_sent=images_sent,
    )


def _parse_datetime(value: str, *, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise FireworksMonitorError(f"{name} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None:
        raise FireworksMonitorError(f"{name} must include a timezone offset")
    return parsed


def _wait_until(start_at: datetime) -> None:
    while True:
        remaining = (start_at - datetime.now(start_at.tzinfo)).total_seconds()
        if remaining <= 0:
            return
        LOGGER.info("Waiting %.0f seconds for the fireworks watch window", remaining)
        time.sleep(min(30, remaining))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-off 2026-07-30 Zushi fireworks watcher."
    )
    parser.add_argument("--start-at", default="")
    parser.add_argument("--end-at", default="")
    parser.add_argument("--duration-seconds", type=int, default=0)
    parser.add_argument("--sample-fps", type=float, default=DEFAULT_SAMPLE_FPS)
    parser.add_argument("--max-images", type=int, default=MAX_IMAGES)
    parser.add_argument("--frames-dir", default="")
    parser.add_argument("--accepted-dir", default="")
    parser.add_argument("--pages-dir", default="public")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
    )
    timezone = ZoneInfo(os.getenv("TIMEZONE", DEFAULT_TIMEZONE))
    now = datetime.now(timezone)
    start_at = (
        _parse_datetime(args.start_at, name="--start-at").astimezone(timezone)
        if args.start_at
        else now
    )
    if args.end_at:
        end_at = _parse_datetime(args.end_at, name="--end-at").astimezone(timezone)
    elif args.duration_seconds > 0:
        end_at = start_at + timedelta(seconds=args.duration_seconds)
    else:
        raise FireworksMonitorError(
            "Either --end-at or a positive --duration-seconds is required"
        )
    if end_at <= start_at:
        raise FireworksMonitorError("The fireworks watch end must be after its start")
    if datetime.now(timezone) >= end_at:
        raise FireworksMonitorError("The fireworks watch window has already ended")

    line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    line_target = os.getenv("LINE_TARGET_ID", "")
    line_client = (
        None
        if args.dry_run
        else LineClient(
            channel_access_token=line_token,
            target_id=line_target,
        )
    )
    if not args.dry_run and (not line_token.strip() or not line_target.strip()):
        raise FireworksMonitorError(
            "LINE_CHANNEL_ACCESS_TOKEN and LINE_TARGET_ID are required"
        )

    image_base_url = os.getenv("FIREWORKS_IMAGE_BASE_URL", "")
    api_key = os.getenv("VISION_API_KEY", "")
    if not api_key.strip():
        raise FireworksMonitorError("VISION_API_KEY is required")
    if not args.dry_run and not image_base_url.strip():
        raise FireworksMonitorError("FIREWORKS_IMAGE_BASE_URL is required")

    _wait_until(start_at)
    capture_started_at = datetime.now(timezone)
    remaining_seconds = max(
        1,
        round((end_at - capture_started_at).total_seconds()),
    )
    live_camera_url = os.getenv(
        "LIVE_CAMERA_URL",
        "https://www.youtube.com/watch?v=Q5AAi9KOjG0",
    )
    try:
        stream_url = _resolve_fireworks_stream_url(
            live_camera_url,
            timeout_seconds=30,
        )
        if not stream_url:
            raise FireworksMonitorError("Could not resolve the live camera stream URL")

        with tempfile.TemporaryDirectory(prefix="zushi-fireworks-") as temp_dir:
            temporary_root = Path(temp_dir)
            frames_dir = (
                Path(args.frames_dir) if args.frames_dir else temporary_root / "frames"
            )
            accepted_dir = (
                Path(args.accepted_dir)
                if args.accepted_dir
                else temporary_root / "accepted"
            )
            result = monitor_fireworks(
                stream_url=stream_url,
                capture_started_at=capture_started_at,
                duration_seconds=remaining_seconds,
                sample_fps=args.sample_fps,
                frames_dir=frames_dir,
                accepted_dir=accepted_dir,
                pages_dir=Path(args.pages_dir),
                image_base_url=image_base_url,
                api_key=api_key,
                vision_model=os.getenv("VISION_MODEL", "gemini-2.5-flash"),
                line_client=line_client,
                dry_run=args.dry_run,
                max_images=args.max_images,
            )
    except Exception as exc:
        if line_client is not None:
            try:
                _notify_monitor_error(line_client, exc)
            except Exception:
                LOGGER.exception("Failed to send the fireworks monitor error")
        raise

    LOGGER.info(
        "Fireworks watch complete: frames=%s analyses=%s images=%s",
        result.frames_seen,
        result.candidates_analyzed,
        result.images_sent,
    )
    if line_client is not None and result.images_sent == 0:
        _notify_no_capture(line_client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
