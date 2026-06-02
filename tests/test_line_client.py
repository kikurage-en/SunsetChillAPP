from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest
from zushi_chill.line_client import LINE_PUSH_URL, LINE_REPLY_URL, LineClient, LineSendError


def test_line_client_pushes_text_payload(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["authorization"] = request.headers["Authorization"]
        captured["content_type"] = request.headers["Content-type"]
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(status=200)

    monkeypatch.setattr("zushi_chill.line_client.urlopen", fake_urlopen)

    LineClient(channel_access_token="token", target_id="group-id", timeout=5).push_text("hello")

    assert captured["url"] == LINE_PUSH_URL
    assert captured["timeout"] == 5
    assert captured["authorization"] == "Bearer token"
    assert captured["content_type"] == "application/json"
    assert captured["body"] == {
        "to": "group-id",
        "messages": [{"type": "text", "text": "hello"}],
    }


def test_line_client_pushes_text_and_image_payload(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(status=200)

    monkeypatch.setattr("zushi_chill.line_client.urlopen", fake_urlopen)

    LineClient(channel_access_token="token", target_id="group-id").push_text_with_image(
        "hello",
        image_url="https://example.com/live.jpg",
        preview_image_url="https://example.com/preview.jpg",
    )

    assert captured["body"] == {
        "to": "group-id",
        "messages": [
            {"type": "text", "text": "hello"},
            {
                "type": "image",
                "originalContentUrl": "https://example.com/live.jpg",
                "previewImageUrl": "https://example.com/preview.jpg",
            },
        ],
    }


def test_line_client_replies_with_image_payload(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(status=200)

    monkeypatch.setattr("zushi_chill.line_client.urlopen", fake_urlopen)

    LineClient(channel_access_token="token", target_id="").reply_image(
        "reply-token",
        image_url="https://example.com/live.jpg",
    )

    assert captured["url"] == LINE_REPLY_URL
    assert captured["body"] == {
        "replyToken": "reply-token",
        "messages": [
            {
                "type": "image",
                "originalContentUrl": "https://example.com/live.jpg",
                "previewImageUrl": "https://example.com/live.jpg",
            }
        ],
    }


def test_line_client_rejects_non_https_image_url(monkeypatch):
    def fail_urlopen(request, timeout):
        raise AssertionError("LINE API should not be called")

    monkeypatch.setattr("zushi_chill.line_client.urlopen", fail_urlopen)

    with pytest.raises(LineSendError, match="https"):
        LineClient(channel_access_token="token", target_id="group-id").push_text_with_image(
            "hello",
            image_url="http://example.com/live.jpg",
        )


def test_line_client_rejects_missing_required_settings(monkeypatch):
    def fail_urlopen(request, timeout):
        raise AssertionError("LINE API should not be called")

    monkeypatch.setattr("zushi_chill.line_client.urlopen", fail_urlopen)

    with pytest.raises(LineSendError, match="access token"):
        LineClient(channel_access_token=" ", target_id="group-id").push_text("hello")

    with pytest.raises(LineSendError, match="target id"):
        LineClient(channel_access_token="token", target_id=" ").push_text("hello")


def test_line_client_raises_on_http_error(monkeypatch, caplog):
    def fake_urlopen(request, timeout):
        raise HTTPError(
            url=request.full_url,
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=FakeErrorBody(b'{"message":"invalid token"}'),
        )

    monkeypatch.setattr("zushi_chill.line_client.urlopen", fake_urlopen)

    with pytest.raises(LineSendError, match="HTTP 401"):
        LineClient(channel_access_token="bad", target_id="group-id").push_text("hello")

    assert "HTTP 401" in caplog.text
    assert "invalid token" in caplog.text


def test_line_client_logs_non_error_response_status_failures(monkeypatch, caplog):
    def fake_urlopen(request, timeout):
        return FakeResponse(status=500, body=b'{"message":"server error"}')

    monkeypatch.setattr("zushi_chill.line_client.urlopen", fake_urlopen)

    with pytest.raises(LineSendError, match="HTTP 500"):
        LineClient(channel_access_token="token", target_id="group-id").push_text("hello")

    assert "HTTP 500" in caplog.text
    assert "server error" in caplog.text


def test_line_client_wraps_timeout_errors(monkeypatch, caplog):
    def fake_urlopen(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr("zushi_chill.line_client.urlopen", fake_urlopen)

    with pytest.raises(LineSendError, match="timed out"):
        LineClient(channel_access_token="token", target_id="group-id").push_text("hello")

    assert "timed out" in caplog.text


class FakeResponse:
    def __init__(self, *, status, body=b""):
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.body


class FakeErrorBody:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def close(self):
        pass
