from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from zushi_chill.models import VisionResult

LOGGER = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_PROMPT = """以下は逗子海岸のライブカメラ画像です。夕焼け・空模様を評価してください。
次のJSONだけを返してください（前後に説明やコードブロックを付けない）:
{
  "sunset_score": 0-100の整数,
  "sky_condition": "clear" | "partly_cloudy" | "overcast" | "golden_hour" | "rain",
  "comment": "50文字以内の日本語コメント"
}

sunset_score の基準:
- 80-100: 鮮やかな橙・赤・紫の夕焼け
- 60-79: 薄い夕焼け色、期待できる空模様
- 40-59: 雲が多いが部分的に色が出ている
- 0-39: 曇天・雨・夕焼けなし"""


class VisionError(RuntimeError):
    """Raised when the live-camera image cannot be analyzed."""


def analyze_image(
    *,
    image_path: Path | None = None,
    image_url: str = "",
    api_key: str,
    model: str = "gemini-2.5-flash",
    timeout_seconds: int = 30,
) -> VisionResult:
    """Analyze a live-camera image with the Gemini vision API.

    Prefers a locally saved image (sent inline as base64) over the public URL,
    because the saved file is guaranteed to exist on the same runner and does
    not depend on GitHub Pages deployment timing. When only a URL is available
    the image is downloaded and sent inline as well (``file_data`` with an
    arbitrary public URL is not reliably supported by the Gemini API).
    """
    if not api_key:
        raise VisionError("VISION_API_KEY is required to analyze images")

    image_bytes = _load_image_bytes(
        image_path=image_path,
        image_url=image_url,
        timeout_seconds=timeout_seconds,
    )
    encoded = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "contents": [
            {
                "parts": [
                    {"inline_data": {"mime_type": "image/jpeg", "data": encoded}},
                    {"text": _PROMPT},
                ]
            }
        ],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    url = f"{GEMINI_API_BASE}/{model}:generateContent?key={api_key}"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if response.status >= 400:
                body = response.read().decode("utf-8", errors="replace")
                raise VisionError(f"Gemini returned HTTP {response.status}: {body}")
            raw = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise VisionError(f"Gemini request failed: {exc}") from exc

    return _parse_response(raw, model=model)


def _load_image_bytes(
    *,
    image_path: Path | None,
    image_url: str,
    timeout_seconds: int,
) -> bytes:
    if image_path is not None and image_path.exists():
        try:
            return image_path.read_bytes()
        except OSError as exc:
            raise VisionError(f"Failed to read image file {image_path}: {exc}") from exc
    if image_url:
        try:
            with urlopen(image_url, timeout=timeout_seconds) as response:
                if response.status >= 400:
                    raise VisionError(
                        f"Image URL returned HTTP {response.status}: {image_url}"
                    )
                return response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            raise VisionError(f"Failed to download image {image_url}: {exc}") from exc
    raise VisionError("Either image_path or image_url is required")


def _parse_response(raw: Any, *, model: str) -> VisionResult:
    try:
        text = raw["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise VisionError(f"Unexpected Gemini response shape: {raw}") from exc
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise VisionError(f"Gemini did not return valid JSON: {text!r}") from exc
    try:
        sunset_score = int(parsed["sunset_score"])
        sky_condition = str(parsed["sky_condition"])
        comment = str(parsed["comment"])
    except (KeyError, TypeError, ValueError) as exc:
        raise VisionError(f"Gemini JSON missing expected fields: {parsed}") from exc

    sunset_score = max(0, min(100, sunset_score))
    return VisionResult(
        sunset_score=sunset_score,
        sky_condition=sky_condition,
        comment=comment,
        model=model,
    )
