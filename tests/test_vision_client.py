from __future__ import annotations

import base64
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from zushi_chill import main as main_module
from zushi_chill import vision_client
from zushi_chill.config import Settings
from zushi_chill.vision_client import (
    VisionError,
    analyze_image,
    select_best_afterglow_image,
)


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


def _gemini_body(
    score=72,
    condition="partly_cloudy",
    comment="薄い夕焼け",
    **extra,
) -> bytes:
    result = {"sunset_score": score, "sky_condition": condition, "comment": comment}
    result.update(extra)
    inner = json.dumps(result)
    return json.dumps(
        {"candidates": [{"content": {"parts": [{"text": inner}]}}]}
    ).encode("utf-8")


def _selection_body(best_index: int) -> bytes:
    inner = json.dumps({"best_index": best_index})
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
    assert result.comment == "薄い夕焼けっピ。"
    assert result.model == "gemini-2.5-flash"


def test_analyze_image_removes_suffix_from_standalone_interjection(monkeypatch, tmp_path):
    image = tmp_path / "afterglow.jpg"
    image.write_bytes(b"fakejpeg")
    monkeypatch.setattr(
        vision_client,
        "urlopen",
        _fake_urlopen([FakeResponse(body=_gemini_body(comment="わぁっピ！"))], []),
    )

    result = analyze_image(image_path=image, api_key="key")

    assert result.comment == "わあっ！"


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


# --- vision_mode / build_prompt: predict before sunset, actual at or after sunset ---

_RUN_1920 = datetime(2026, 6, 10, 19, 20, tzinfo=ZoneInfo("Asia/Tokyo"))
_SUNSET_1855 = datetime(2026, 6, 10, 18, 55, tzinfo=ZoneInfo("Asia/Tokyo"))
_RUN_1700_0610 = datetime(2026, 6, 10, 17, 0, tzinfo=ZoneInfo("Asia/Tokyo"))


def test_should_run_vision_true_at_post_sunset_hour(monkeypatch):
    settings = _settings(monkeypatch, VISION_ENABLED="true", VISION_API_KEY="key")
    run_19 = datetime(2026, 6, 1, 19, 20, tzinfo=ZoneInfo("Asia/Tokyo"))

    assert main_module._should_run_vision(run_19, settings) is True


def test_vision_mode_boundaries():
    assert vision_client.vision_mode(_RUN_1700_0610, _SUNSET_1855) == "predict"
    assert vision_client.vision_mode(_SUNSET_1855, _SUNSET_1855) == "actual"
    assert vision_client.vision_mode(_RUN_1920, _SUNSET_1855) == "actual"


def test_vision_evaluation_phase_boundaries():
    ten_minutes_after = datetime(
        2026, 6, 10, 19, 5, tzinfo=ZoneInfo("Asia/Tokyo")
    )

    assert (
        vision_client.vision_evaluation_phase(_RUN_1700_0610, _SUNSET_1855)
        == "predict"
    )
    assert (
        vision_client.vision_evaluation_phase(_SUNSET_1855, _SUNSET_1855)
        == "sunset"
    )
    assert (
        vision_client.vision_evaluation_phase(ten_minutes_after, _SUNSET_1855)
        == "sunset"
    )
    assert (
        vision_client.vision_evaluation_phase(_RUN_1920, _SUNSET_1855)
        == "afterglow"
    )


def test_build_prompt_predicts_sunset_from_pre_sunset_sky():
    prompt = vision_client.build_prompt(
        capture_time=_RUN_1700_0610, sunset_time=_SUNSET_1855
    )

    assert "17:00" in prompt
    assert "18:55" in prompt
    assert "予測して採点" in prompt
    assert "雲の構造" in prompt
    # 撮影時点の色の有無で採点させない(6/10のカメラ実況30過小の再発防止)
    assert "現在の夕焼け色の有無ではなく" in prompt
    assert "説明する文の文末を「っピ」にする" in prompt
    assert "独立した感嘆詞には「っピ」を付けない" in prompt
    assert "今回の話し方は" in prompt


def test_build_prompt_evaluates_actual_sky_after_sunset():
    prompt = vision_client.build_prompt(capture_time=_RUN_1920, sunset_time=_SUNSET_1855)

    assert "19:20" in prompt
    assert "18:55" in prompt
    assert "残照だけを評価" in prompt
    assert "afterglow_score" in prompt
    assert "予測して採点" not in prompt
    assert "説明する文の文末を「っピ」にする" in prompt
    assert "独立した感嘆詞には「っピ」を付けない" in prompt


def test_build_prompt_separates_disk_and_color_at_sunset():
    prompt = vision_client.build_prompt(
        capture_time=_SUNSET_1855, sunset_time=_SUNSET_1855
    )

    assert "太陽ディスク" in prompt
    assert "sun_disk_visibility" in prompt
    assert "sunset_color_score" in prompt


def test_build_prompt_falls_back_to_generic_prompt_without_times():
    assert vision_client.build_prompt() == vision_client._PROMPT


def test_comment_voice_tone_changes_on_consecutive_dates():
    first = vision_client._comment_voice(_RUN_1700_0610)
    next_day = vision_client._comment_voice(_RUN_1700_0610.replace(day=11))

    assert first != next_day
    assert "画像の事実や採点は変えない" in first
    assert "画像の事実や採点は変えない" in next_day


def test_analyze_image_sends_mode_specific_prompt(monkeypatch, tmp_path):
    image = tmp_path / "1700.jpg"
    image.write_bytes(b"fakejpeg")
    calls: list = []
    monkeypatch.setattr(
        vision_client, "urlopen", _fake_urlopen([FakeResponse(body=_gemini_body())], calls)
    )

    analyze_image(
        image_path=image,
        api_key="key",
        capture_time=_RUN_1700_0610,
        sunset_time=_SUNSET_1855,
    )

    payload = json.loads(calls[0].data)
    prompt_text = payload["contents"][0]["parts"][1]["text"]
    assert "予測して採点" in prompt_text


def test_analyze_image_records_separate_sunset_metrics(monkeypatch, tmp_path):
    image = tmp_path / "sunset.jpg"
    image.write_bytes(b"fakejpeg")
    response = _gemini_body(
        score=76,
        sun_disk_visibility=68,
        sunset_color_score=84,
    )
    monkeypatch.setattr(
        vision_client, "urlopen", _fake_urlopen([FakeResponse(body=response)], [])
    )

    result = analyze_image(
        image_path=image,
        api_key="key",
        capture_time=_SUNSET_1855,
        sunset_time=_SUNSET_1855,
    )

    assert result.evaluation_phase == "sunset"
    assert result.sun_disk_visibility == 68
    assert result.sunset_color_score == 84
    assert result.afterglow_score is None


def test_analyze_image_uses_legacy_score_as_afterglow_fallback(monkeypatch, tmp_path):
    image = tmp_path / "afterglow.jpg"
    image.write_bytes(b"fakejpeg")
    monkeypatch.setattr(
        vision_client,
        "urlopen",
        _fake_urlopen([FakeResponse(body=_gemini_body(score=63))], []),
    )

    result = analyze_image(
        image_path=image,
        api_key="key",
        capture_time=_RUN_1920,
        sunset_time=_SUNSET_1855,
    )

    assert result.evaluation_phase == "afterglow"
    assert result.afterglow_score == 63
    assert result.sunset_color_score is None


def test_select_best_afterglow_image_compares_candidates_in_one_request(
    monkeypatch,
    tmp_path,
):
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first-jpeg")
    second.write_bytes(b"second-jpeg")
    calls: list = []
    monkeypatch.setattr(
        vision_client,
        "urlopen",
        _fake_urlopen([FakeResponse(body=_selection_body(2))], calls),
    )

    selected = select_best_afterglow_image(
        image_paths=[first, second],
        capture_times=[_RUN_1920, _RUN_1920.replace(second=30)],
        api_key="key",
    )

    assert selected == 1
    assert len(calls) == 1
    payload = json.loads(calls[0].data)
    parts = payload["contents"][0]["parts"]
    inline_images = [part["inline_data"]["data"] for part in parts if "inline_data" in part]
    assert inline_images == [
        base64.b64encode(b"first-jpeg").decode("ascii"),
        base64.b64encode(b"second-jpeg").decode("ascii"),
    ]
    assert "撮影時刻の早い遅い自体は評価理由にしない" in parts[0]["text"]


def test_select_best_afterglow_image_rejects_out_of_range_choice(
    monkeypatch,
    tmp_path,
):
    image = tmp_path / "only.jpg"
    image.write_bytes(b"jpeg")
    monkeypatch.setattr(
        vision_client,
        "urlopen",
        _fake_urlopen([FakeResponse(body=_selection_body(2))], []),
    )

    with pytest.raises(VisionError, match="expected 1-1"):
        select_best_afterglow_image(
            image_paths=[image],
            capture_times=[_RUN_1920],
            api_key="key",
        )
