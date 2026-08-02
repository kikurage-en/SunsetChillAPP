from __future__ import annotations

import colorsys
import hashlib
import logging
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

from zushi_chill.live_camera import LiveCameraFrame

LOGGER = logging.getLogger(__name__)
SCORE_WIDTH = 64
SCORE_HEIGHT = 36


@dataclass(frozen=True)
class RankedAfterglowCandidate:
    frame: LiveCameraFrame
    local_score: float
    sha256: str


class AfterglowSelectionError(RuntimeError):
    """Raised when no captured afterglow image can be ranked."""


def rank_afterglow_candidates(
    frames: Sequence[LiveCameraFrame],
) -> tuple[RankedAfterglowCandidate, ...]:
    """Deduplicate and rank captured frames by visible sunset color.

    Decoding failures receive a zero local score instead of aborting the
    observation. This still lets the Vision comparison choose among readable
    JPEG files when ffmpeg-based local scoring is unavailable.
    """
    ranked: list[RankedAfterglowCandidate] = []
    seen_digests: set[str] = set()
    for frame in frames:
        try:
            image = frame.path.read_bytes()
        except OSError as exc:
            LOGGER.warning("Skipping unreadable afterglow candidate %s: %s", frame.path, exc)
            continue
        if not image:
            continue
        digest = hashlib.sha256(image).hexdigest()
        if digest in seen_digests:
            LOGGER.info("Skipping duplicate afterglow candidate: %s", frame.path)
            continue
        seen_digests.add(digest)
        try:
            pixels = _decode_rgb(frame)
            local_score = _sunset_color_score(pixels)
        except Exception as exc:
            LOGGER.warning(
                "Local afterglow scoring failed for %s; retaining with score 0: %s",
                frame.path,
                exc,
            )
            local_score = 0.0
        ranked.append(
            RankedAfterglowCandidate(
                frame=frame,
                local_score=local_score,
                sha256=digest,
            )
        )
    if not ranked:
        raise AfterglowSelectionError("No non-empty afterglow candidates were captured")
    return tuple(
        sorted(
            ranked,
            key=lambda candidate: (
                -candidate.local_score,
                -candidate.frame.captured_at.timestamp(),
                candidate.frame.path.name,
            ),
        )
    )


def _decode_rgb(frame: LiveCameraFrame) -> bytes:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(frame.path),
        "-vf",
        f"scale={SCORE_WIDTH}:{SCORE_HEIGHT}",
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "pipe:1",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AfterglowSelectionError(f"Candidate decode failed: {exc}") from exc
    expected_bytes = SCORE_WIDTH * SCORE_HEIGHT * 3
    if completed.returncode != 0 or len(completed.stdout) != expected_bytes:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        raise AfterglowSelectionError(
            f"Candidate decode returned {completed.returncode}: {error}"
        )
    return completed.stdout


def _sunset_color_score(pixels: bytes) -> float:
    """Return a deterministic 0-100 proxy for vivid orange/red/purple coverage."""
    if not pixels or len(pixels) % 3:
        raise ValueError("RGB pixel data must contain complete pixels")
    color_strength = 0.0
    vivid_pixels = 0
    pixel_count = len(pixels) // 3
    for offset in range(0, len(pixels), 3):
        red, green, blue = (channel / 255.0 for channel in pixels[offset : offset + 3])
        hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
        hue_weight = _sunset_hue_weight(hue)
        shadow_weight = min(value / 0.3, 1.0) ** 2
        exposure_weight = shadow_weight * min((1.05 - value) / 0.15, 1.0)
        exposure_weight = max(0.0, exposure_weight)
        strength = hue_weight * saturation * exposure_weight
        color_strength += strength
        if strength >= 0.3:
            vivid_pixels += 1
    mean_strength = color_strength / pixel_count
    vivid_coverage = vivid_pixels / pixel_count
    return round(min(100.0, 100.0 * (2.2 * mean_strength + 0.35 * vivid_coverage)), 3)


def _sunset_hue_weight(hue: float) -> float:
    # HSV hue is normalized to 0-1. Favor red/orange and magenta/purple while
    # excluding ordinary blue sky and green foregrounds.
    if hue >= 0.94 or hue <= 0.04:
        return 1.0
    if hue <= 0.13:
        return 1.0 - ((hue - 0.04) / 0.09) * 0.25
    if 0.72 <= hue <= 0.94:
        return 0.75 + ((hue - 0.72) / 0.22) * 0.25
    return 0.0
