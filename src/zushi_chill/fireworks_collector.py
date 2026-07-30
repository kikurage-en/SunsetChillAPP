from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from zushi_chill.fireworks_monitor import (
    BURST_QUIET_SECONDS,
    DEFAULT_SAMPLE_FPS,
    DEFAULT_TIMEZONE,
    EVENT_DATE,
    FRAME_CLEANUP_LAG,
    BurstCandidate,
    BurstTracker,
    FireworksMonitorError,
    _candidate_time,
    _cleanup_frame,
    _iter_detection_frames,
    _resolve_fireworks_stream_url,
    _wait_for_frame_file,
    _wait_until,
    score_fireworks_frame,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_CANDIDATES = 30
DEFAULT_REPOSITORY = "kikurage-en/SunsetChillAPP"
DEFAULT_WORKFLOW = "fireworks_watch_20260730.yml"
CAPTURE_RETRY_DELAY_SECONDS = 5.0

_COLLECTED_CANDIDATE_PATH = re.compile(
    r"^(?P<time>\d{6})-(?P<score>\d{8})-(?P<frame>\d{8})\.jpg$"
)


@dataclass(frozen=True)
class CollectedCandidate:
    captured_at: datetime
    score: int
    path: Path


@dataclass(frozen=True)
class CollectionResult:
    frames_seen: int
    candidates: tuple[CollectedCandidate, ...]


@dataclass(frozen=True)
class CollectionWindowResult:
    frames_seen: int
    candidates: tuple[CollectedCandidate, ...]
    attempts: int
    failures: int
    premature_ends: int

    @property
    def incomplete(self) -> bool:
        return self.failures > 0 or self.premature_ends > 0


def load_collected_candidates(
    *,
    candidates_dir: Path,
    timezone: ZoneInfo,
    max_candidates: int,
) -> tuple[CollectedCandidate, ...]:
    """Load and globally prune candidates retained across capture retries."""
    if max_candidates <= 0:
        raise ValueError("max_candidates must be positive")
    candidates_dir.mkdir(parents=True, exist_ok=True)
    candidates: list[CollectedCandidate] = []
    for path in candidates_dir.glob("*.jpg"):
        match = _COLLECTED_CANDIDATE_PATH.fullmatch(path.name)
        if match is None:
            LOGGER.warning("Ignoring unrecognized fireworks candidate: %s", path)
            continue
        captured_at = datetime.strptime(
            f"{EVENT_DATE} {match.group('time')}",
            "%Y-%m-%d %H%M%S",
        ).replace(tzinfo=timezone)
        candidates.append(
            CollectedCandidate(
                captured_at=captured_at,
                score=int(match.group("score")),
                path=path,
            )
        )

    ranked = sorted(
        candidates,
        key=lambda item: (-item.score, item.captured_at, item.path.name),
    )
    for dropped in ranked[max_candidates:]:
        dropped.path.unlink(missing_ok=True)
    return tuple(
        sorted(
            ranked[:max_candidates],
            key=lambda item: (item.captured_at, -item.score, item.path.name),
        )
    )


def collect_fireworks_candidates(
    *,
    stream_url: str,
    capture_started_at: datetime,
    duration_seconds: int,
    sample_fps: float,
    frames_dir: Path,
    candidates_dir: Path,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> CollectionResult:
    """Keep the strongest burst frames without needing LINE or Vision credentials."""
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if max_candidates <= 0:
        raise ValueError("max_candidates must be positive")

    timezone = capture_started_at.tzinfo
    if not isinstance(timezone, ZoneInfo):
        raise ValueError("capture_started_at must use a ZoneInfo timezone")
    candidates = list(
        load_collected_candidates(
            candidates_dir=candidates_dir,
            timezone=timezone,
            max_candidates=max_candidates,
        )
    )
    tracker = BurstTracker(
        sample_fps=sample_fps,
        quiet_seconds=BURST_QUIET_SECONDS,
    )
    previous_frame: bytes | None = None
    frames_seen = 0
    cleanup_index = 1

    def retain_candidate(candidate: BurstCandidate) -> None:
        captured_at = _candidate_time(
            capture_started_at,
            candidate.frame_index,
            sample_fps,
        )
        source = _wait_for_frame_file(frames_dir, candidate.frame_index)
        destination = candidates_dir / (
            f"{captured_at.strftime('%H%M%S')}-{candidate.score:08d}-"
            f"{candidate.frame_index:08d}.jpg"
        )
        shutil.copy2(source, destination)
        candidates[:] = [item for item in candidates if item.path != destination]
        candidates.append(
            CollectedCandidate(
                captured_at=captured_at,
                score=candidate.score,
                path=destination,
            )
        )
        if len(candidates) > max_candidates:
            weakest = min(candidates, key=lambda item: (item.score, item.captured_at))
            candidates.remove(weakest)
            weakest.path.unlink(missing_ok=True)
        LOGGER.info(
            "Retained fireworks candidate at %s with score %s (%s/%s)",
            captured_at.isoformat(),
            candidate.score,
            len(candidates),
            max_candidates,
        )

    try:
        for frame_index, frame in _iter_detection_frames(
            stream_url=stream_url,
            frames_dir=frames_dir,
            duration_seconds=duration_seconds,
            sample_fps=sample_fps,
        ):
            frames_seen = frame_index
            if previous_frame is None:
                previous_frame = frame
                continue
            frame_score = score_fireworks_frame(previous_frame, frame)
            previous_frame = frame
            candidate = tracker.observe(frame_index, frame_score.score)
            if candidate is not None:
                retain_candidate(candidate)

            protected_index = tracker.protected_frame_index
            cleanup_before = frame_index - FRAME_CLEANUP_LAG
            while cleanup_index <= cleanup_before:
                if cleanup_index != protected_index:
                    _cleanup_frame(frames_dir, cleanup_index)
                cleanup_index += 1
    except Exception:
        final_candidate = tracker.flush()
        if final_candidate is not None:
            retain_candidate(final_candidate)
        raise
    else:
        final_candidate = tracker.flush()
        if final_candidate is not None:
            retain_candidate(final_candidate)

    return CollectionResult(
        frames_seen=frames_seen,
        candidates=tuple(sorted(candidates, key=lambda item: item.captured_at)),
    )


def collect_fireworks_window(
    *,
    live_camera_url: str,
    start_at: datetime,
    end_at: datetime,
    sample_fps: float,
    candidates_dir: Path,
    max_candidates: int,
    now: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> CollectionWindowResult:
    """Capture until the end of the window, re-resolving HLS after interruptions."""
    if end_at <= start_at:
        raise ValueError("end_at must be after start_at")
    timezone = start_at.tzinfo
    if not isinstance(timezone, ZoneInfo):
        raise ValueError("start_at must use a ZoneInfo timezone")
    now = now or (lambda: datetime.now(timezone))
    frames_seen = 0
    attempts = 0
    failures = 0
    premature_ends = 0

    while True:
        capture_started_at = now()
        if capture_started_at >= end_at:
            break
        attempts += 1
        duration_seconds = max(
            1,
            math.ceil((end_at - capture_started_at).total_seconds()),
        )
        attempt_failed = False
        attempt_frames = 0
        try:
            stream_url = _resolve_fireworks_stream_url(
                live_camera_url,
                timeout_seconds=30,
            )
            if not stream_url:
                raise FireworksMonitorError(
                    "Could not resolve the live camera stream URL"
                )
            with tempfile.TemporaryDirectory(
                prefix="zushi-fireworks-frames-"
            ) as temp_dir:
                result = collect_fireworks_candidates(
                    stream_url=stream_url,
                    capture_started_at=capture_started_at,
                    duration_seconds=duration_seconds,
                    sample_fps=sample_fps,
                    frames_dir=Path(temp_dir),
                    candidates_dir=candidates_dir,
                    max_candidates=max_candidates,
                )
            frames_seen += result.frames_seen
            attempt_frames = result.frames_seen
        except Exception as exc:
            attempt_failed = True
            failures += 1
            LOGGER.exception(
                "Fireworks capture attempt %s failed; retrying until %s: %s",
                attempts,
                end_at.isoformat(),
                exc,
            )

        finished_at = now()
        if finished_at >= end_at:
            break
        if not attempt_failed:
            expected_frames = max(
                1,
                math.floor(duration_seconds * sample_fps * 0.9),
            )
            if attempt_frames < expected_frames:
                premature_ends += 1
                LOGGER.warning(
                    "Fireworks stream ended after %s/%s expected frames; "
                    "re-resolving the HLS URL",
                    attempt_frames,
                    expected_frames,
                )
            else:
                LOGGER.info(
                    "Fireworks media duration completed before wall-clock end; "
                    "continuing from a fresh HLS URL"
                )
                sleep(min(1.0, (end_at - finished_at).total_seconds()))
                continue
        remaining_seconds = (end_at - finished_at).total_seconds()
        sleep(min(CAPTURE_RETRY_DELAY_SECONDS, remaining_seconds))

    candidates = load_collected_candidates(
        candidates_dir=candidates_dir,
        timezone=timezone,
        max_candidates=max_candidates,
    )
    return CollectionWindowResult(
        frames_seen=frames_seen,
        candidates=candidates,
        attempts=attempts,
        failures=failures,
        premature_ends=premature_ends,
    )


def publish_candidates(
    *,
    candidates: tuple[CollectedCandidate, ...],
    pages_dir: Path,
) -> list[str]:
    if not candidates:
        return []
    _run_checked(
        ["git", "-C", str(pages_dir), "pull", "--rebase", "origin", "pages-images"]
    )

    relative_paths: list[str] = []
    for candidate in candidates:
        relative_path = (
            f"fireworks-candidates/{EVENT_DATE}/"
            f"{candidate.captured_at.strftime('%H%M%S')}-{candidate.score:08d}.jpg"
        )
        destination = pages_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate.path, destination)
        if destination.stat().st_size > 1_000_000:
            raise FireworksMonitorError(
                f"Candidate image exceeds LINE preview limit: {destination}"
            )
        relative_paths.append(relative_path)

    _run_checked(["git", "-C", str(pages_dir), "add", *relative_paths])
    _run_checked(
        [
            "git",
            "-C",
            str(pages_dir),
            "commit",
            "-m",
            f"archive: fireworks candidates {EVENT_DATE}",
        ]
    )
    first_push = subprocess.run(
        ["git", "-C", str(pages_dir), "push", "origin", "HEAD:pages-images"],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if first_push.returncode != 0:
        LOGGER.warning("Candidate push raced another archive; rebasing once")
        _run_checked(
            ["git", "-C", str(pages_dir), "pull", "--rebase", "origin", "pages-images"]
        )
        _run_checked(
            ["git", "-C", str(pages_dir), "push", "origin", "HEAD:pages-images"]
        )
    return relative_paths


def _run_checked(command: list[str]) -> None:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise FireworksMonitorError(
            f"Command failed ({' '.join(command[:3])}): {completed.stderr.strip()}"
        )


def dispatch_candidate_workflow(
    *,
    candidate_paths: list[str],
    status: str,
    repository: str,
    workflow: str = DEFAULT_WORKFLOW,
) -> None:
    if status not in {"ok", "partial", "monitor_error"}:
        raise ValueError("status must be ok, partial, or monitor_error")
    command = [
        "gh",
        "workflow",
        "run",
        workflow,
        "--repo",
        repository,
        "--ref",
        "main",
        "-f",
        "mode=send_line",
        "-f",
        f"status={status}",
        "-f",
        f"candidate_paths={json.dumps(candidate_paths, separators=(',', ':'))}",
    ]
    _run_checked(command)


def _parse_datetime(value: str, *, name: str, timezone: ZoneInfo) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise FireworksMonitorError(f"{name} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None:
        raise FireworksMonitorError(f"{name} must include a timezone offset")
    return parsed.astimezone(timezone)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect one-off Zushi fireworks frames on a non-datacenter IP."
    )
    parser.add_argument("--start-at", required=True)
    parser.add_argument("--end-at", required=True)
    parser.add_argument("--sample-fps", type=float, default=DEFAULT_SAMPLE_FPS)
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    parser.add_argument("--candidates-dir", required=True)
    parser.add_argument("--pages-dir", required=True)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
    )
    timezone = ZoneInfo(os.getenv("TIMEZONE", DEFAULT_TIMEZONE))
    start_at = _parse_datetime(args.start_at, name="--start-at", timezone=timezone)
    end_at = _parse_datetime(args.end_at, name="--end-at", timezone=timezone)
    if end_at <= start_at:
        raise FireworksMonitorError("The collection end must be after its start")
    if datetime.now(timezone) >= end_at:
        raise FireworksMonitorError("The fireworks collection window has already ended")
    if not 1 <= args.max_candidates <= DEFAULT_MAX_CANDIDATES:
        raise FireworksMonitorError(
            f"--max-candidates must be between 1 and {DEFAULT_MAX_CANDIDATES}"
        )

    pages_dir = Path(args.pages_dir).resolve()
    if not (pages_dir / ".git").exists():
        raise FireworksMonitorError(f"pages-images checkout is missing: {pages_dir}")
    candidates_dir = Path(args.candidates_dir).resolve()
    live_camera_url = os.getenv(
        "LIVE_CAMERA_URL",
        "https://www.youtube.com/watch?v=Q5AAi9KOjG0",
    )

    _wait_until(start_at)
    try:
        result = collect_fireworks_window(
            live_camera_url=live_camera_url,
            start_at=start_at,
            end_at=end_at,
            sample_fps=args.sample_fps,
            candidates_dir=candidates_dir,
            max_candidates=args.max_candidates,
        )
        LOGGER.info(
            "Collection complete: frames=%s candidates=%s attempts=%s "
            "failures=%s premature_ends=%s",
            result.frames_seen,
            len(result.candidates),
            result.attempts,
            result.failures,
            result.premature_ends,
        )
        if args.dry_run:
            return 0
        candidate_paths = publish_candidates(
            candidates=result.candidates,
            pages_dir=pages_dir,
        )
        dispatch_candidate_workflow(
            candidate_paths=candidate_paths,
            status="partial" if result.incomplete else "ok",
            repository=args.repository,
        )
    except Exception:
        LOGGER.exception("Fireworks collection failed")
        if not args.dry_run:
            try:
                dispatch_candidate_workflow(
                    candidate_paths=[],
                    status="monitor_error",
                    repository=args.repository,
                )
            except Exception:
                LOGGER.exception("Failed to dispatch the monitor error")
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
