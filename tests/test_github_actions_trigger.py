from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest
from zushi_chill.github_actions_trigger import (
    GITHUB_API_BASE_URL,
    GitHubActionsTriggerError,
    dispatch_workflow,
    main,
)


def test_dispatch_workflow_posts_workflow_dispatch_payload(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["authorization"] = request.headers["Authorization"]
        captured["api_version"] = request.headers["X-github-api-version"]
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(status=204)

    monkeypatch.setattr("zushi_chill.github_actions_trigger.urlopen", fake_urlopen)

    dispatch_workflow(
        repository="owner/repo",
        workflow="daily_chill.yml",
        ref="main",
        inputs={"manual_mode": "send_line", "date": "2026-06-01", "run_time": "17:00"},
        token="token",
        timeout=7,
    )

    assert captured["url"] == (
        f"{GITHUB_API_BASE_URL}/repos/owner/repo/actions/workflows/daily_chill.yml/dispatches"
    )
    assert captured["timeout"] == 7
    assert captured["authorization"] == "Bearer token"
    assert captured["api_version"] == "2022-11-28"
    assert captured["body"] == {
        "ref": "main",
        "inputs": {"manual_mode": "send_line", "date": "2026-06-01", "run_time": "17:00"},
    }


def test_dispatch_workflow_raises_on_github_http_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise HTTPError(
            url=request.full_url,
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=FakeErrorBody(b'{"message":"Not Found"}'),
        )

    monkeypatch.setattr("zushi_chill.github_actions_trigger.urlopen", fake_urlopen)

    with pytest.raises(GitHubActionsTriggerError, match="HTTP 404"):
        dispatch_workflow(
            repository="owner/repo",
            workflow="missing.yml",
            ref="main",
            inputs={},
            token="token",
        )


def test_main_dry_run_prints_dispatch_payload(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_WORKFLOW", raising=False)
    monkeypatch.delenv("GITHUB_REF", raising=False)

    exit_code = main(["--dry-run", "--date", "2026-06-01", "--run-time", "13:00"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output == {
        "repository": "owner/repo",
        "workflow": "daily_chill.yml",
        "ref": "main",
        "inputs": {"manual_mode": "send_line", "date": "2026-06-01", "run_time": "13:00"},
    }


class FakeResponse:
    def __init__(self, *, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def read(self):
        return b""


class FakeErrorBody:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def close(self):
        return None
