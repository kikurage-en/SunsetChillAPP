from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from zushi_chill.config import ConfigError
from zushi_chill.github_actions_trigger import dispatch_workflow

GITHUB_API_BASE_URL = "https://api.github.com"


class GitHubCaptureStoreError(RuntimeError):
    """Raised when an observation workflow cannot be inspected on GitHub."""


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
