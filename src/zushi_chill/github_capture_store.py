from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from zushi_chill.config import ConfigError
from zushi_chill.github_actions_trigger import dispatch_workflow

GITHUB_API_BASE_URL = "https://api.github.com"


class GitHubCaptureStoreError(RuntimeError):
    """Raised when an observation cannot be archived or inspected on GitHub."""


@dataclass(frozen=True)
class WorkflowRun:
    run_id: int
    status: str
    conclusion: str
    created_at: datetime
    url: str


class GitHubCaptureStore:
    def __init__(self, *, repository: str, token: str, timeout: int = 20):
        if "/" not in repository.strip():
            raise ConfigError("GITHUB_REPOSITORY must be in owner/repo format")
        if not token.strip():
            raise ConfigError("GITHUB_TOKEN is required")
        self.repository = repository.strip()
        self.token = token.strip()
        self.timeout = timeout

    def archive_capture(
        self,
        *,
        local_path: str | Path,
        repository_path: str,
        data_ref: str,
        base_ref: str,
        observation_id: str,
    ) -> str:
        capture_path = Path(local_path)
        image = capture_path.read_bytes()
        if not image:
            raise GitHubCaptureStoreError(f"Capture is empty: {capture_path}")
        if len(image) > 5 * 1024 * 1024:
            raise GitHubCaptureStoreError("Capture exceeds the 5 MiB archive limit")

        self._ensure_ref(data_ref=data_ref, base_ref=base_ref)
        existing = self._get_content(repository_path=repository_path, ref=data_ref)
        expected_blob_sha = _git_blob_sha(image)
        if existing and existing.get("sha") == expected_blob_sha:
            return expected_blob_sha

        payload: dict[str, object] = {
            "message": f"archive: {observation_id}",
            "content": base64.b64encode(image).decode("ascii"),
            "branch": data_ref,
        }
        if existing and isinstance(existing.get("sha"), str):
            payload["sha"] = existing["sha"]
        result = self._request_json(
            "PUT",
            f"/repos/{self.repository}/contents/{quote(repository_path, safe='/')}",
            payload=payload,
        )
        content = result.get("content", {}) if isinstance(result, dict) else {}
        archived_sha = content.get("sha") if isinstance(content, dict) else None
        if archived_sha != expected_blob_sha:
            raise GitHubCaptureStoreError("GitHub returned an unexpected capture blob SHA")
        return expected_blob_sha

    def dispatch_observation(
        self,
        *,
        workflow: str,
        ref: str,
        inputs: dict[str, str],
    ) -> None:
        dispatch_workflow(
            repository=self.repository,
            workflow=workflow,
            ref=ref,
            inputs=inputs,
            token=self.token,
            timeout=self.timeout,
        )

    def latest_observation_run(
        self,
        *,
        workflow: str,
        ref: str,
        observation_id: str,
    ) -> WorkflowRun | None:
        query = urlencode({"event": "workflow_dispatch", "branch": ref, "per_page": 50})
        result = self._request_json(
            "GET",
            (
                f"/repos/{self.repository}/actions/workflows/"
                f"{quote(workflow, safe='')}/runs?{query}"
            ),
        )
        expected_title = f"SunsetChill {observation_id}"
        runs = result.get("workflow_runs", []) if isinstance(result, dict) else []
        for item in runs:
            if not isinstance(item, dict) or item.get("display_title") != expected_title:
                continue
            created_at = item.get("created_at")
            if not isinstance(created_at, str):
                continue
            return WorkflowRun(
                run_id=int(item["id"]),
                status=str(item.get("status", "")),
                conclusion=str(item.get("conclusion") or ""),
                created_at=datetime.fromisoformat(created_at.replace("Z", "+00:00")),
                url=str(item.get("html_url", "")),
            )
        return None

    def _ensure_ref(self, *, data_ref: str, base_ref: str) -> None:
        normalized_data_ref = _validate_ref(data_ref)
        normalized_base_ref = _validate_ref(base_ref)
        if self._get_ref(normalized_data_ref) is not None:
            return
        base = self._get_ref(normalized_base_ref)
        if base is None:
            raise GitHubCaptureStoreError(f"Base ref does not exist: {normalized_base_ref}")
        obj = base.get("object", {})
        sha = obj.get("sha") if isinstance(obj, dict) else None
        if not isinstance(sha, str) or not sha:
            raise GitHubCaptureStoreError(f"Base ref has no SHA: {normalized_base_ref}")
        try:
            self._request_json(
                "POST",
                f"/repos/{self.repository}/git/refs",
                payload={"ref": f"refs/heads/{normalized_data_ref}", "sha": sha},
            )
        except GitHubCaptureStoreError:
            if self._get_ref(normalized_data_ref) is None:
                raise

    def _get_ref(self, ref: str) -> dict | None:
        return self._request_json(
            "GET",
            f"/repos/{self.repository}/git/ref/heads/{quote(ref, safe='')}",
            allow_not_found=True,
        )

    def _get_content(self, *, repository_path: str, ref: str) -> dict | None:
        return self._request_json(
            "GET",
            (
                f"/repos/{self.repository}/contents/{quote(repository_path, safe='/')}"
                f"?{urlencode({'ref': ref})}"
            ),
            allow_not_found=True,
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        allow_not_found: bool = False,
    ) -> dict | None:
        request = Request(
            f"{GITHUB_API_BASE_URL}{path}",
            data=(json.dumps(payload).encode("utf-8") if payload is not None else None),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "SunsetChillAPP-observation-scheduler",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except HTTPError as exc:
            if allow_not_found and exc.code == 404:
                return None
            body = exc.read().decode("utf-8", errors="replace")
            raise GitHubCaptureStoreError(f"GitHub returned HTTP {exc.code}: {body}") from exc
        except (URLError, TimeoutError) as exc:
            raise GitHubCaptureStoreError(f"GitHub request failed: {exc}") from exc
        if not body:
            return {}
        try:
            decoded = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise GitHubCaptureStoreError("GitHub returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise GitHubCaptureStoreError("GitHub returned an unexpected JSON payload")
        return decoded


def _validate_ref(value: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or normalized.startswith(("/", "."))
        or normalized.endswith(("/", "."))
        or ".." in normalized
        or any(char.isspace() for char in normalized)
    ):
        raise ConfigError("Git refs must be non-empty branch names without whitespace or '..'")
    return normalized


def _git_blob_sha(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()
