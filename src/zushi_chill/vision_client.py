from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from zushi_chill.comment_variants import select_comment_variant
from zushi_chill.comment_voice import apply_comment_voice
from zushi_chill.models import VisionResult

LOGGER = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_JSON_SPEC = """次のJSONだけを返してください（前後に説明やコードブロックを付けない）:
{
  "sunset_score": 0-100の整数,
  "sky_condition": "clear" | "partly_cloudy" | "overcast" | "golden_hour" | "rain",
  "comment": "50文字以内の日本語コメント"
}"""

_SUNSET_JSON_SPEC = """次のJSONだけを返してください（前後に説明やコードブロックを付けない）:
{
  "sunset_score": 日没時の総合品質を表す0-100の整数,
  "sun_disk_visibility": 太陽ディスクの見えやすさを表す0-100の整数,
  "sunset_color_score": 日没時の橙・赤・紫の発色を表す0-100の整数,
  "sky_condition": "clear" | "partly_cloudy" | "overcast" | "golden_hour" | "rain",
  "comment": "50文字以内の日本語コメント"
}"""

_AFTERGLOW_JSON_SPEC = """次のJSONだけを返してください（前後に説明やコードブロックを付けない）:
{
  "sunset_score": 残照の品質と同じ0-100の整数,
  "afterglow_score": 日没後の橙・赤・紫の残照を表す0-100の整数,
  "sky_condition": "clear" | "partly_cloudy" | "overcast" | "golden_hour" | "rain",
  "comment": "50文字以内の日本語コメント"
}"""

_SCORE_RUBRIC = """- 80-100: 鮮やかな橙・赤・紫の夕焼け
- 60-79: 薄い夕焼け色、期待できる空模様
- 40-59: 雲が多いが部分的に色が出ている
- 0-39: 曇天・雨・夕焼けなし"""

_COMMENT_VOICE = """comment の書き方:
- 画像から確認できる事実を優先し、50文字以内の自然な日本語にする
- 無邪気で親しみのある口調にし、説明する文の文末を「っピ」にする
- 「わあっ！」「やった！」「うーん……」など、独立した感嘆詞には「っピ」を付けない
- 「わぁっ」は使わず「わあっ」と書く（例:「わあっ！空が赤く光ってるっピ！」）
- 高得点では明るく喜び、低得点では「うーん……」など静かな調子にする
- 「っピ！」、「っピ。」、「っピ……。」のように書き、句点を重ねない"""

_COMMENT_TONE_VARIANTS = (
    "驚きや感嘆を少し多めにし、空を見て思わず声が出たように話す",
    "画像を一生懸命に観察して、見つけたことを報告するように話す",
    "おっとりした間やためらいを少し入れ、空をじっと眺めるように話す",
)

_PROMPT = f"""以下は逗子海岸のライブカメラ画像です。夕焼け・空模様を評価してください。
{_JSON_SPEC}

sunset_score の基準:
{_SCORE_RUBRIC}

{_COMMENT_VOICE}"""


def vision_mode(capture_time: datetime, sunset_time: datetime) -> str:
    """Return "predict" before sunset and "actual" at or after sunset."""
    return "predict" if capture_time < sunset_time else "actual"


def vision_evaluation_phase(capture_time: datetime, sunset_time: datetime) -> str:
    """画像が予測・日没時・残照のどの評価に使われるかを返す。"""
    if capture_time < sunset_time:
        return "predict"
    if capture_time <= sunset_time + timedelta(minutes=10):
        return "sunset"
    return "afterglow"


def _comment_voice(capture_time: datetime) -> str:
    tone = select_comment_variant(
        capture_time.date().isoformat(),
        capture_time.strftime("%H:%M"),
        "vision-comment-tone",
        _COMMENT_TONE_VARIANTS,
    )
    return (
        f"{_COMMENT_VOICE}\n"
        f"- 今回の話し方は「{tone}」。ただし、画像の事実や採点は変えない"
    )


def build_prompt(
    *,
    capture_time: datetime | None = None,
    sunset_time: datetime | None = None,
) -> str:
    if capture_time is None or sunset_time is None:
        return _PROMPT
    capture_label = capture_time.strftime("%H:%M")
    sunset_label = sunset_time.strftime("%H:%M")
    header = (
        f"以下は逗子海岸のライブカメラ画像です。"
        f"撮影時刻は{capture_label}、本日の日没時刻は{sunset_label}です。"
    )
    phase = vision_evaluation_phase(capture_time, sunset_time)
    if phase == "predict":
        return (
            f"{header}\n"
            "日没前の画像なので、現在の夕焼け色の有無ではなく、"
            "雲の構造（低層雲の厚み、水平線付近の抜け、中・高層雲の広がり）から、"
            "今夜の日没時にどの程度の夕焼けになりそうかを予測して採点してください。\n"
            f"{_JSON_SPEC}\n\n"
            f"sunset_score の基準（日没時に予測される夕焼けとして採点）:\n"
            f"{_SCORE_RUBRIC}\n\n"
            f"{_comment_voice(capture_time)}"
        )
    if phase == "sunset":
        return (
            f"{header}\n"
            "日没時の画像です。太陽ディスクが雲や地形で隠れていないかと、"
            "空に実際に出ている夕焼け色を別々に評価してください。"
            "太陽が画角外の場合は、水平線付近の直射光の見え方から判断してください。\n"
            f"{_SUNSET_JSON_SPEC}\n\n"
            f"sunset_score と sunset_color_score の基準:\n{_SCORE_RUBRIC}\n"
            "sun_disk_visibility は色の鮮やかさではなく、太陽ディスクまたは直射光の"
            "見えやすさだけを採点してください。\n\n"
            f"{_comment_voice(capture_time)}"
        )
    return (
        f"{header}\n"
        "日没から10分以上経過した画像です。太陽ディスクではなく、中・高層雲や空に"
        "残っている橙・赤・紫の残照だけを評価してください。\n"
        f"{_AFTERGLOW_JSON_SPEC}\n\n"
        f"sunset_score と afterglow_score の基準:\n{_SCORE_RUBRIC}\n\n"
        f"{_comment_voice(capture_time)}"
    )


class VisionError(RuntimeError):
    """Raised when the live-camera image cannot be analyzed."""


def analyze_image(
    *,
    image_path: Path | None = None,
    image_url: str = "",
    api_key: str,
    model: str = "gemini-2.5-flash",
    timeout_seconds: int = 30,
    capture_time: datetime | None = None,
    sunset_time: datetime | None = None,
) -> VisionResult:
    """Analyze a live-camera image with the Gemini vision API.

    When both ``capture_time`` and ``sunset_time`` are given, the prompt
    switches between sunset prediction (before sunset) and live evaluation
    (at or after sunset). Without them the legacy generic prompt is used.

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
                    {"text": build_prompt(capture_time=capture_time, sunset_time=sunset_time)},
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

    phase = (
        vision_evaluation_phase(capture_time, sunset_time)
        if capture_time is not None and sunset_time is not None
        else ""
    )
    return _parse_response(raw, model=model, evaluation_phase=phase)


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


def _parse_response(
    raw: Any, *, model: str, evaluation_phase: str = ""
) -> VisionResult:
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
        comment = apply_comment_voice(str(parsed["comment"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise VisionError(f"Gemini JSON missing expected fields: {parsed}") from exc

    sunset_score = max(0, min(100, sunset_score))
    sun_disk_visibility = _optional_score(parsed, "sun_disk_visibility")
    sunset_color_score = _optional_score(parsed, "sunset_color_score")
    afterglow_score = _optional_score(parsed, "afterglow_score")
    # 旧形式の応答でも、日没時の発色・残照は従来の総合スコアを代理値として保存できる。
    if evaluation_phase == "sunset" and sunset_color_score is None:
        sunset_color_score = sunset_score
    if evaluation_phase == "afterglow" and afterglow_score is None:
        afterglow_score = sunset_score
    return VisionResult(
        sunset_score=sunset_score,
        sky_condition=sky_condition,
        comment=comment,
        model=model,
        evaluation_phase=evaluation_phase,
        sun_disk_visibility=sun_disk_visibility,
        sunset_color_score=sunset_color_score,
        afterglow_score=afterglow_score,
    )


def _optional_score(parsed: dict[str, Any], key: str) -> int | None:
    value = parsed.get(key)
    if value is None or value == "":
        return None
    try:
        score = int(value)
    except (TypeError, ValueError) as exc:
        raise VisionError(f"Gemini JSON contains invalid {key}: {parsed}") from exc
    return max(0, min(100, score))
