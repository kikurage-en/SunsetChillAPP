import io
import json
from urllib.error import HTTPError

from zushi_chill import github_capture_store
from zushi_chill.github_capture_store import GitHubCaptureStore, _git_blob_sha


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


def test_archive_capture_creates_data_ref_and_uploads_exact_blob(tmp_path, monkeypatch):
    image = b"exact-camera-image"
    image_path = tmp_path / "capture.jpg"
    image_path.write_bytes(image)
    requests = []
    responses = [
        _not_found("missing data ref"),
        FakeResponse({"object": {"sha": "base-commit"}}),
        FakeResponse({"ref": "refs/heads/observation-data"}),
        _not_found("missing content"),
        FakeResponse({"content": {"sha": _git_blob_sha(image)}}),
    ]

    def fake_urlopen(request, timeout):
        requests.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(github_capture_store, "urlopen", fake_urlopen)
    store = GitHubCaptureStore(repository="owner/repo", token="token")

    result = store.archive_capture(
        local_path=image_path,
        repository_path="observations/2026-07-26/sunset/capture.jpg",
        data_ref="observation-data",
        base_ref="main",
        observation_id="2026-07-26:sunset",
    )

    assert result == _git_blob_sha(image)
    assert [request.method for request in requests] == ["GET", "GET", "POST", "GET", "PUT"]
    create_ref = json.loads(requests[2].data)
    assert create_ref == {"ref": "refs/heads/observation-data", "sha": "base-commit"}
    upload = json.loads(requests[4].data)
    assert upload["branch"] == "observation-data"
    assert upload["message"] == "archive: 2026-07-26:sunset"


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


def _not_found(message):
    return HTTPError(
        url="https://api.github.test",
        code=404,
        msg=message,
        hdrs=None,
        fp=io.BytesIO(message.encode()),
    )
