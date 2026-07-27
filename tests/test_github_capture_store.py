import json

from zushi_chill import github_capture_store
from zushi_chill.github_capture_store import GitHubCaptureStore


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        if self.payload is None:
            return b""
        return json.dumps(self.payload).encode()


def test_latest_observation_run_ignores_other_dispatches(monkeypatch):
    payload = {
        "workflow_runs": [
            {
                "id": 1,
                "display_title": "SunsetChill other-job",
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-07-26T09:00:00Z",
                "html_url": "https://example/1",
            },
            {
                "id": 2,
                "display_title": "SunsetChill 2026-07-26:sunset",
                "status": "in_progress",
                "conclusion": None,
                "created_at": "2026-07-26T09:50:30Z",
                "html_url": "https://example/2",
            },
        ]
    }
    monkeypatch.setattr(
        github_capture_store,
        "urlopen",
        lambda request, timeout: FakeResponse(payload),
    )
    store = GitHubCaptureStore(repository="owner/repo", token="token")

    run = store.latest_observation_run(
        workflow="daily_chill.yml",
        ref="main",
        observation_id="2026-07-26:sunset",
    )

    assert run is not None
    assert run.run_id == 2
    assert run.status == "in_progress"
    assert run.conclusion == ""
