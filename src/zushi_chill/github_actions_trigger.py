from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from zushi_chill.config import ConfigError, Settings

LOGGER = logging.getLogger(__name__)
GITHUB_API_BASE_URL = "https://api.github.com"


class GitHubActionsTriggerError(RuntimeError):
    """Raised when GitHub Actions workflow dispatch fails."""


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        settings = Settings.from_env()
        logging.basicConfig(
            level=getattr(logging, settings.log_level.upper(), logging.INFO),
            format="%(levelname)s:%(name)s:%(message)s",
        )
        run_date = args.date or datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
        _validate_date(run_date)
        _validate_time(args.run_time)

        repository = _required_value(args.repository or os.getenv("GITHUB_REPOSITORY", ""))
        workflow = args.workflow or os.getenv("GITHUB_WORKFLOW", "daily_chill.yml")
        ref = args.ref or os.getenv("GITHUB_REF", "main")
        scheduled_at = datetime.fromisoformat(
            f"{run_date}T{args.run_time}"
        ).replace(tzinfo=ZoneInfo(settings.timezone)).isoformat()
        inputs = {
            "manual_mode": args.manual_mode,
            "date": run_date,
            "run_time": args.run_time,
            "observation_id": f"{run_date}:forecast",
            "observation_phase": "forecast",
            "scheduled_at": scheduled_at,
            "captured_at": scheduled_at,
        }
        if args.dry_run:
            print(
                json.dumps(
                    {"repository": repository, "workflow": workflow, "ref": ref, "inputs": inputs}
                )
            )
            return 0
        token = _required_value(os.getenv("GITHUB_TOKEN", ""))
        dispatch_workflow(
            repository=repository,
            workflow=workflow,
            ref=ref,
            inputs=inputs,
            token=token,
        )
        LOGGER.info("Triggered %s %s on %s with %s", repository, workflow, ref, inputs)
        return 0
    except Exception as exc:
        logging.getLogger(__name__).exception("GitHub Actions trigger failed: %s", exc)
        return 1


def dispatch_workflow(
    *,
    repository: str,
    workflow: str,
    ref: str,
    inputs: dict[str, str],
    token: str,
    timeout: int = 20,
) -> None:
    if "/" not in repository.strip():
        raise ConfigError("GITHUB_REPOSITORY must be in owner/repo format")
    if not workflow.strip():
        raise ConfigError("GITHUB_WORKFLOW is required")
    if not ref.strip():
        raise ConfigError("GITHUB_REF is required")
    if not token.strip():
        raise ConfigError("GITHUB_TOKEN is required")

    url = (
        f"{GITHUB_API_BASE_URL}/repos/{repository.strip()}/actions/workflows/"
        f"{workflow.strip()}/dispatches"
    )
    payload = {"ref": ref.strip(), "inputs": inputs}
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token.strip()}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 204:
                body = response.read().decode("utf-8", errors="replace")
                raise GitHubActionsTriggerError(
                    f"GitHub returned HTTP {response.status}: {body}"
                )
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise GitHubActionsTriggerError(f"GitHub returned HTTP {exc.code}: {body}") from exc
    except (URLError, TimeoutError) as exc:
        raise GitHubActionsTriggerError(f"GitHub workflow dispatch failed: {exc}") from exc


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trigger the Zushi Chill GitHub Actions workflow.")
    parser.add_argument("--date", help="Run date in YYYY-MM-DD. Defaults to today in TIMEZONE.")
    parser.add_argument("--run-time", required=True, help="Displayed run time in HH:MM.")
    parser.add_argument(
        "--manual-mode",
        choices=["send_line", "dry_run"],
        default="send_line",
        help="workflow_dispatch manual_mode input.",
    )
    parser.add_argument("--repository", help="GitHub repository in owner/repo format.")
    parser.add_argument("--workflow", help="Workflow file name or workflow id.")
    parser.add_argument("--ref", help="Git ref to dispatch. Defaults to main.")
    parser.add_argument("--dry-run", action="store_true", help="Print dispatch payload only.")
    return parser.parse_args(argv)


def _required_value(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ConfigError("GITHUB_REPOSITORY and GITHUB_TOKEN are required")
    return normalized


def _validate_date(value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ConfigError("--date must be YYYY-MM-DD") from exc


def _validate_time(value: str) -> None:
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ConfigError("--run-time must be HH:MM") from exc


if __name__ == "__main__":
    sys.exit(main())
