from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from zushi_chill import fireworks_monitor
from zushi_chill.fireworks_monitor import (
    BurstTracker,
    FireworksAnalysis,
    FireworksMonitorError,
    _ffmpeg_command,
    _parse_fireworks_analysis,
    _public_image_url,
    _resolve_fireworks_stream_url,
    analyze_fireworks_image,
    build_fireworks_comment,
    build_fireworks_prompt,
    build_line_text,
    monitor_fireworks,
    score_fireworks_frame,
)

JST = ZoneInfo("Asia/Tokyo")
CAPTURED_AT = datetime(2026, 7, 30, 19, 42, 13, tzinfo=JST)


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self.body = body
        self.status = status

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _vision_response(
    *,
    visible: bool = True,
    confidence: int = 94,
    quality: int = 82,
    comment: str = "夜空に大きな花火が咲きました！",
) -> bytes:
    parsed = {
        "fireworks_visible": visible,
        "confidence": confidence,
        "quality_score": quality,
        "comment": comment,
    }
    return json.dumps(
        {
            "candidates": [
                {"content": {"parts": [{"text": json.dumps(parsed, ensure_ascii=False)}]}}
            ]
        }
    ).encode()


def test_score_fireworks_frame_detects_local_new_bright_pixels():
    previous = bytearray(fireworks_monitor.DETECTION_WIDTH * fireworks_monitor.DETECTION_HEIGHT)
    current = bytearray(previous)
    for index in range(100, 108):
        current[index] = 230

    result = score_fireworks_frame(bytes(previous), bytes(current))

    assert result.score > 0
    assert result.changed_pixels == 8
    assert result.peak_delta == 230


def test_score_fireworks_frame_rejects_global_exposure_change():
    length = fireworks_monitor.DETECTION_WIDTH * fireworks_monitor.DETECTION_HEIGHT
    previous = bytes([20]) * length
    current = bytes([200]) * length

    result = score_fireworks_frame(previous, current)

    assert result.score == 0
    assert result.global_change_ratio > fireworks_monitor.MAX_GLOBAL_CHANGE_RATIO


def test_score_fireworks_frame_rejects_wrong_frame_size():
    with pytest.raises(ValueError, match="exactly"):
        score_fireworks_frame(b"\x00", b"\xff")


def test_burst_tracker_groups_frames_and_keeps_highest_score():
    tracker = BurstTracker(sample_fps=2, quiet_seconds=2)

    assert tracker.observe(10, 100) is None
    assert tracker.observe(11, 250) is None
    assert tracker.observe(12, 120) is None
    assert tracker.observe(13, 0) is None
    assert tracker.observe(14, 0) is None
    assert tracker.observe(15, 0) is None
    candidate = tracker.observe(16, 0)

    assert candidate is not None
    assert candidate.frame_index == 11
    assert candidate.score == 250


def test_fireworks_prompt_requires_existing_voice_and_strict_detection():
    prompt = build_fireworks_prompt(CAPTURED_AT)

    assert "すべての文末を「っピ」にする" in prompt
    assert "街灯、船の灯り、水面反射" in prompt
    assert "今回の話し方は" in prompt


def test_fallback_fireworks_comment_uses_existing_voice():
    comment = build_fireworks_comment(CAPTURED_AT, 1)

    assert "花火" in comment
    for sentence in comment.replace("！", "。").split("。"):
        if sentence:
            assert sentence.endswith("っピ")


def test_line_text_only_applies_voice_to_comment():
    message = build_line_text(CAPTURED_AT, "大きな花火が見えました！")

    assert message.startswith("🎆 逗子海岸シークレット花火\n19:42:13 撮影\n")
    assert message.endswith("大きな花火が見えましたっピ！")


def test_parse_fireworks_analysis_applies_existing_voice():
    raw = json.loads(_vision_response().decode())

    result = _parse_fireworks_analysis(raw)

    assert result.fireworks_visible is True
    assert result.confidence == 94
    assert result.quality_score == 82
    assert result.comment == "夜空に大きな花火が咲きましたっピ！"


def test_parse_fireworks_analysis_requires_boolean_visible():
    raw = json.loads(_vision_response().decode())
    parsed = json.loads(raw["candidates"][0]["content"]["parts"][0]["text"])
    parsed["fireworks_visible"] = "true"
    raw["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(parsed)

    with pytest.raises(FireworksMonitorError, match="boolean"):
        _parse_fireworks_analysis(raw)


def test_analyze_fireworks_image_sends_inline_image_and_prompt(monkeypatch, tmp_path):
    image = tmp_path / "candidate.jpg"
    image.write_bytes(b"jpeg-data")
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return FakeResponse(_vision_response())

    monkeypatch.setattr(fireworks_monitor, "urlopen", fake_urlopen)

    result = analyze_fireworks_image(
        image_path=image,
        captured_at=CAPTURED_AT,
        api_key="key",
    )

    assert result.fireworks_visible is True
    payload = json.loads(requests[0].data)
    parts = payload["contents"][0]["parts"]
    assert parts[0]["inline_data"]["data"] == base64.b64encode(b"jpeg-data").decode()
    assert "すべての文末を「っピ」にする" in parts[1]["text"]


def test_monitor_groups_burst_confirms_image_and_keeps_voiced_comment(
    monkeypatch,
    tmp_path,
):
    frame_size = fireworks_monitor.DETECTION_WIDTH * fireworks_monitor.DETECTION_HEIGHT
    dark = bytes(frame_size)
    bright = bytearray(dark)
    for index in range(100, 108):
        bright[index] = 230
    frames = [dark, bytes(bright), *([dark] * 7)]
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "00000002.jpg").write_bytes(b"candidate-jpeg")

    monkeypatch.setattr(
        fireworks_monitor,
        "_iter_detection_frames",
        lambda **kwargs: iter(enumerate(frames, start=1)),
    )
    monkeypatch.setattr(
        fireworks_monitor,
        "analyze_fireworks_image",
        lambda **kwargs: FireworksAnalysis(
            fireworks_visible=True,
            confidence=95,
            quality_score=80,
            comment="花火を見つけましたっピ！",
        ),
    )

    result = monitor_fireworks(
        stream_url="https://stream.example/live.m3u8",
        capture_started_at=CAPTURED_AT,
        duration_seconds=10,
        sample_fps=2,
        frames_dir=frames_dir,
        accepted_dir=tmp_path / "accepted",
        pages_dir=tmp_path / "public",
        image_base_url="",
        api_key="key",
        vision_model="model",
        line_client=None,
        dry_run=True,
    )

    assert result.frames_seen == len(frames)
    assert result.candidates_analyzed == 1
    assert result.images_sent == 1
    assert len(list((tmp_path / "accepted").glob("*.jpg"))) == 1


def test_ffmpeg_command_splits_high_resolution_and_detection_outputs(tmp_path):
    command = _ffmpeg_command(
        stream_url="https://stream.example/live.m3u8",
        frames_dir=tmp_path,
        duration_seconds=60,
        sample_fps=2,
    )

    assert command[0] == "ffmpeg"
    assert "[0:v:0]split=2" in command[command.index("-filter_complex") + 1]
    assert str(tmp_path / "%08d.jpg") in command
    assert command.count("-t") == 2
    assert command[-1] == "pipe:1"


def test_fireworks_stream_resolver_enables_current_youtube_challenge_solver(
    monkeypatch,
):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return fireworks_monitor.subprocess.CompletedProcess(
            command,
            0,
            stdout="https://stream.example/live.m3u8\n",
            stderr="",
        )

    monkeypatch.setattr(fireworks_monitor.subprocess, "run", fake_run)

    result = _resolve_fireworks_stream_url(
        "https://youtube.example/live",
        timeout_seconds=30,
    )

    assert result == "https://stream.example/live.m3u8"
    assert calls[0][1:3] == ["--remote-components", "ejs:github"]
    assert "--js-runtimes" in calls[0]


def test_public_image_url_requires_https():
    assert (
        _public_image_url(
            "https://raw.githubusercontent.com/example/repo/pages-images/",
            "/fireworks/2026-07-30/194213.jpg",
        )
        == "https://raw.githubusercontent.com/example/repo/pages-images/"
        "fireworks/2026-07-30/194213.jpg"
    )
    with pytest.raises(FireworksMonitorError, match="https"):
        _public_image_url("http://example.test", "capture.jpg")


def test_workflow_is_separate_one_day_job_with_safe_manual_default():
    workflow = Path(".github/workflows/fireworks_watch_20260730.yml").read_text(
        encoding="utf-8"
    )

    assert "Fireworks Watch 2026-07-30" in workflow
    assert 'cron: "45 9 30 7 *"' in workflow
    assert 'EVENT_DATE: "2026-07-30"' in workflow
    assert 'default: "dry_run"' in workflow
    assert "- send_line" in workflow
    assert 'if [[ "$EVENT_NAME" == "schedule" ]]' in workflow
    assert "LINE_CHANNEL_ACCESS_TOKEN" in workflow
    assert "VISION_API_KEY" in workflow
    assert "python -m zushi_chill.fireworks_monitor" in workflow
