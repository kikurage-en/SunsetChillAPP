from __future__ import annotations

import base64
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from zushi_chill import main as main_module
from zushi_chill import vision_client
from zushi_chill.config import Settings
from zushi_chill.vision_client import VisionError, analyze_image


class FakeResponse:
    def __init__(self, *, status: int = 200, body: bytes = b""):
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _gemini_body(score=72, condition="partly_cloudy", comment="薄い夕焼け") -> bytes:
    inner = json.dumps(
        {"sunset_score": score, "sky_condition": condition, "comment": comment}
    )
    return json.dumps(
        {"candidates": [{"content": {"parts": [{"text": inner}]}}]}
    ).encode("utf-8")


def _fake_urlopen(responses: list[FakeResponse], calls: list):
    def _urlopen(target, timeout=None):
        calls.append(target)
        return responses.pop(0)

    return _urlopen


def _settings(monkeypatch, **env) -> Settings:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings.from_env()


_RUN_17 = datetime(2026, 6, 1, 17, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
_RUN_13 = datetime(2026, 6, 1, 13, 0, tzinfo=ZoneInfo("Asia/Tokyo"))


# --- _should_run_vision: gates analysis to the configured hour and enablement ---


def test_should_run_vision_true_at_target_hour(monkeypatch):
    settings = _settings(monkeypatch, VISION_ENABLED="true", VISION_API_KEY="key")
    assert main_module._should_run_vision(_RUN_17, settings) is True


def test_should_run_vision_false_off_target_hour(monkeypatch):
    settings = _settings(monkeypatch, VISION_ENABLED="true", VISION_API_KEY="key")
    assert main_module._should_run_vision(_RUN_13, settings) is False


def test_should_run_vision_false_when_disabled(monkeypatch):
    settings = _settings(monkeypatch, VISION_ENABLED="false", VISION_API_KEY="key")
    assert main_module._should_run_vision(_RUN_17, settings) is False


def test_should_run_vision_false_without_api_key(monkeypatch):
    settings = _settings(monkeypatch, VISION_ENABLED="true")
    assert main_module._should_run_vision(_RUN_17, settings) is False


# --- analyze_image: response parsing + local-path-first wiring (Codex BLOCK1/BLOCK3) ---


def test_analyze_image_parses_response_and_records_model(monkeypatch, tmp_path):
    image = tmp_path / "1700.jpg"
    image.write_bytes(b"fakejpeg")
    calls: list = []
    monkeypatch.setattr(
        vision_client, "urlopen", _fake_urlopen([FakeResponse(body=_gemini_body())], calls)
    )

    result = analyze_image(
        image_path=image,
        image_url="https://pages.example/x.jpg",
        api_key="key",
        model="gemini-2.5-flash",
    )

    assert result.sunset_score == 72
    assert result.sky_condition == "partly_cloudy"
    assert result.comment == "薄い夕焼け"
    assert result.model == "gemini-2.5-flash"


def test_analyze_image_prefers_local_file_as_inline_base64(monkeypatch, tmp_path):
    image = tmp_path / "1700.jpg"
    image.write_bytes(b"fakejpeg")
    calls: list = []
    monkeypatch.setattr(
        vision_client, "urlopen", _fake_urlopen([FakeResponse(body=_gemini_body())], calls)
    )

    analyze_image(
        image_path=image,
        image_url="https://pages.example/x.jpg",
        api_key="key",
    )

    # Only the Gemini POST is made; the public URL is NOT downloaded when a local file exists.
    assert len(calls) == 1
    payload = json.loads(calls[0].data)
    parts = payload["contents"][0]["parts"]
    assert parts[0]["inline_data"]["data"] == base64.b64encode(b"fakejpeg").decode("ascii")
    assert parts[0]["inline_data"]["mime_type"] == "image/jpeg"
    assert all("file_data" not in part for part in parts)


def test_analyze_image_falls_back_to_downloading_url(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        vision_client,
        "urlopen",
        _fake_urlopen(
            [FakeResponse(body=b"downloaded-bytes"), FakeResponse(body=_gemini_body())], calls
        ),
    )

    analyze_image(
        image_path=None,
        image_url="https://pages.example/x.jpg",
        api_key="key",
    )

    # First call downloads the image URL, second call posts inline base64 of those bytes.
    assert calls[0] == "https://pages.example/x.jpg"
    payload = json.loads(calls[1].data)
    parts = payload["contents"][0]["parts"]
    assert parts[0]["inline_data"]["data"] == base64.b64encode(b"downloaded-bytes").decode("ascii")


def test_analyze_image_raises_on_non_json_text(monkeypatch, tmp_path):
    image = tmp_path / "1700.jpg"
    image.write_bytes(b"fakejpeg")
    body = json.dumps(
        {"candidates": [{"content": {"parts": [{"text": "評価できません"}]}}]}
    ).encode("utf-8")
    monkeypatch.setattr(vision_client, "urlopen", _fake_urlopen([FakeResponse(body=body)], []))

    with pytest.raises(VisionError, match="JSON"):
        analyze_image(image_path=image, api_key="key")


def test_analyze_image_raises_on_unexpected_shape(monkeypatch, tmp_path):
    image = tmp_path / "1700.jpg"
    image.write_bytes(b"fakejpeg")
    body = json.dumps({"unexpected": True}).encode("utf-8")
    monkeypatch.setattr(vision_client, "urlopen", _fake_urlopen([FakeResponse(body=body)], []))

    with pytest.raises(VisionError):
        analyze_image(image_path=image, api_key="key")


def test_analyze_image_requires_an_image_source(monkeypatch):
    monkeypatch.setattr(vision_client, "urlopen", _fake_urlopen([], []))
    with pytest.raises(VisionError):
        analyze_image(image_path=None, image_url="", api_key="key")


def test_analyze_image_clamps_score_into_range(monkeypatch, tmp_path):
    image = tmp_path / "1700.jpg"
    image.write_bytes(b"fakejpeg")
    monkeypatch.setattr(
        vision_client, "urlopen", _fake_urlopen([FakeResponse(body=_gemini_body(score=150))], [])
    )

    result = analyze_image(image_path=image, api_key="key")
    assert result.sunset_score == 100
