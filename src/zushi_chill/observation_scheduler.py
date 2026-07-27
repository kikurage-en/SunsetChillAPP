from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import sqlite3
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from zushi_chill.config import ConfigError, Settings
from zushi_chill.github_capture_store import GitHubCaptureStore, WorkflowRun
from zushi_chill.live_camera import capture_live_camera_image
from zushi_chill.solar_schedule import observation_times

LOGGER = logging.getLogger(__name__)
ACTIVE_PHASES = frozenset({"sunset", "afterglow"})
LINE_RETRY_KEY_LIFETIME = timedelta(hours=24)
LINE_RECOVERY_MARGIN = timedelta(hours=1)


@dataclass(frozen=True)
class SchedulerSettings:
    database_path: Path
    spool_directory: Path
    data_ref: str
    afterglow_offset_minutes: int
    capture_max_delay_minutes: int
    run_visibility_grace_seconds: int
    retry_max_seconds: int

    @classmethod
    def from_env(cls) -> SchedulerSettings:
        return cls(
            database_path=Path(
                os.getenv(
                    "OBSERVATION_DB_PATH",
                    "/var/lib/zushi-chill/observation_jobs.sqlite3",
                )
            ),
            spool_directory=Path(
                os.getenv("OBSERVATION_SPOOL_DIR", "/var/lib/zushi-chill/spool")
            ),
            data_ref=_env("OBSERVATION_DATA_REF", "observation-data"),
            afterglow_offset_minutes=_positive_int(
                "AFTERGLOW_OFFSET_MINUTES",
                default=20,
            ),
            capture_max_delay_minutes=_positive_int(
                "OBSERVATION_CAPTURE_MAX_DELAY_MINUTES",
                default=60,
            ),
            run_visibility_grace_seconds=_positive_int(
                "OBSERVATION_RUN_VISIBILITY_GRACE_SECONDS",
                default=120,
            ),
            retry_max_seconds=_positive_int(
                "OBSERVATION_RETRY_MAX_SECONDS",
                default=1800,
            ),
        )


@dataclass(frozen=True)
class ObservationJob:
    observation_id: str
    target_date: str
    phase: str
    scheduled_at: datetime
    manual_mode: str
    status: str
    capture_path: str = ""
    captured_at: datetime | None = None
    capture_sha256: str = ""
    repository_path: str = ""
    dispatch_attempts: int = 0
    last_dispatch_at: datetime | None = None
    next_attempt_at: datetime | None = None
    github_run_id: int | None = None
    github_run_url: str = ""
    last_error: str = ""
    completed_at: datetime | None = None


class ObservationJobStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS observation_jobs (
                    observation_id TEXT PRIMARY KEY,
                    target_date TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    manual_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    capture_path TEXT NOT NULL DEFAULT '',
                    captured_at TEXT,
                    capture_sha256 TEXT NOT NULL DEFAULT '',
                    repository_path TEXT NOT NULL DEFAULT '',
                    dispatch_attempts INTEGER NOT NULL DEFAULT 0,
                    last_dispatch_at TEXT,
                    next_attempt_at TEXT,
                    github_run_id INTEGER,
                    github_run_url TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(target_date, phase)
                )
                """
            )

    def ensure_job(
        self,
        *,
        target_date: date,
        phase: str,
        scheduled_at: datetime,
        manual_mode: str,
        now: datetime,
    ) -> None:
        if phase not in ACTIVE_PHASES:
            raise ValueError(f"Unknown observation phase: {phase}")
        observation_id = f"{target_date.isoformat()}:{phase}"
        timestamp = _iso(now)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO observation_jobs (
                    observation_id, target_date, phase, scheduled_at, manual_mode,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'planned', ?, ?)
                ON CONFLICT(observation_id) DO UPDATE SET
                    scheduled_at = excluded.scheduled_at,
                    manual_mode = excluded.manual_mode,
                    updated_at = excluded.updated_at
                WHERE observation_jobs.status = 'planned'
                """,
                (
                    observation_id,
                    target_date.isoformat(),
                    phase,
                    _iso(scheduled_at),
                    manual_mode,
                    timestamp,
                    timestamp,
                ),
            )

    def get(self, observation_id: str) -> ObservationJob:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM observation_jobs WHERE observation_id = ?",
                (observation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(observation_id)
        return _job_from_row(row)

    def due_jobs(self, now: datetime) -> list[ObservationJob]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM observation_jobs
                WHERE status NOT IN ('completed', 'capture_missed')
                  AND scheduled_at <= ?
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ORDER BY scheduled_at DESC, observation_id
                """,
                (_iso(now), _iso(now)),
            ).fetchall()
        return [_job_from_row(row) for row in rows]

    def incomplete_jobs(self, target_date: date) -> list[ObservationJob]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM observation_jobs
                WHERE target_date = ? AND status != 'completed'
                ORDER BY scheduled_at
                """,
                (target_date.isoformat(),),
            ).fetchall()
        return [_job_from_row(row) for row in rows]

    def update(self, observation_id: str, *, now: datetime, **fields: object) -> None:
        allowed = {
            "status",
            "capture_path",
            "captured_at",
            "capture_sha256",
            "repository_path",
            "dispatch_attempts",
            "last_dispatch_at",
            "next_attempt_at",
            "github_run_id",
            "github_run_url",
            "last_error",
            "completed_at",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown observation job fields: {', '.join(sorted(unknown))}")
        normalized = {
            key: _iso(value) if isinstance(value, datetime) else value
            for key, value in fields.items()
        }
        normalized["updated_at"] = _iso(now)
        assignments = ", ".join(f"{key} = ?" for key in normalized)
        values = [*normalized.values(), observation_id]
        with self._connect() as connection:
            connection.execute(
                f"UPDATE observation_jobs SET {assignments} WHERE observation_id = ?",
                values,
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()


class ObservationScheduler:
    def __init__(
        self,
        *,
        app_settings: Settings,
        scheduler_settings: SchedulerSettings,
        store: ObservationJobStore,
        github: GitHubCaptureStore,
        now: Callable[[], datetime] | None = None,
        capture: Callable[..., None] = capture_live_camera_image,
    ):
        self.app_settings = app_settings
        self.scheduler_settings = scheduler_settings
        self.store = store
        self.github = github
        self.tz = ZoneInfo(app_settings.timezone)
        self._now = now or (lambda: datetime.now(self.tz))
        self._capture = capture

    def ensure_daily_jobs(self, target_date: date, *, now: datetime | None = None) -> None:
        current = now or self._now()
        times = observation_times(
            target_date=target_date,
            latitude=self.app_settings.latitude,
            longitude=self.app_settings.longitude,
            timezone=self.app_settings.timezone,
            afterglow_offset_minutes=self.scheduler_settings.afterglow_offset_minutes,
        )
        self.store.ensure_job(
            target_date=target_date,
            phase="sunset",
            scheduled_at=times["sunset"],
            manual_mode="dry_run",
            now=current,
        )
        self.store.ensure_job(
            target_date=target_date,
            phase="afterglow",
            scheduled_at=times["afterglow"],
            manual_mode="send_line",
            now=current,
        )

    def tick(self, *, now: datetime | None = None) -> list[ObservationJob]:
        current = now or self._now()
        self.ensure_daily_jobs(current.date(), now=current)
        advanced: list[ObservationJob] = []
        for job in self.store.due_jobs(current):
            try:
                self._advance(job, current)
            except Exception as exc:
                LOGGER.exception("Observation %s failed: %s", job.observation_id, exc)
                retry_at = current + timedelta(
                    seconds=_retry_seconds(
                        max(job.dispatch_attempts, 1),
                        self.scheduler_settings.retry_max_seconds,
                    )
                )
                self.store.update(
                    job.observation_id,
                    now=current,
                    next_attempt_at=retry_at,
                    last_error=str(exc),
                )
            advanced.append(self.store.get(job.observation_id))
        return advanced

    def audit(self, target_date: date, *, now: datetime | None = None) -> list[ObservationJob]:
        current = now or self._now()
        self.ensure_daily_jobs(target_date, now=current)
        return self.store.incomplete_jobs(target_date)

    def _advance(self, initial_job: ObservationJob, current: datetime) -> None:
        job = initial_job
        if job.status == "planned":
            if current > job.scheduled_at + timedelta(
                minutes=self.scheduler_settings.capture_max_delay_minutes
            ):
                self.store.update(
                    job.observation_id,
                    now=current,
                    status="capture_missed",
                    last_error=(
                        "Capture window expired before an image was saved "
                        f"(scheduled {job.scheduled_at.isoformat()})"
                    ),
                    next_attempt_at=None,
                )
                return
            self._capture_job(job, current)
            job = self.store.get(job.observation_id)

        if job.status == "captured":
            self._archive_job(job, current)
            job = self.store.get(job.observation_id)

        if job.status == "uploaded":
            self._dispatch_job(job, current)
            return

        if job.status == "dispatched":
            self._reconcile_run(job, current)

    def _capture_job(self, job: ObservationJob, current: datetime) -> None:
        target_directory = (
            self.scheduler_settings.spool_directory / job.target_date / job.phase
        )
        target_directory.mkdir(parents=True, exist_ok=True)
        captured_at = self._now()
        filename = captured_at.strftime("%Y%m%dT%H%M%S%z") + ".jpg"
        final_path = target_directory / filename
        temporary_path = target_directory / f".{filename}.tmp.jpg"
        try:
            self._capture(
                live_camera_url=self.app_settings.live_camera_url,
                live_camera_video_id=self.app_settings.live_camera_video_id,
                output_path=temporary_path,
                timeout_seconds=self.app_settings.live_camera_capture_timeout_seconds,
            )
            if not temporary_path.exists() or temporary_path.stat().st_size == 0:
                raise RuntimeError("Capture command returned without a non-empty image")
            os.replace(temporary_path, final_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        digest = hashlib.sha256(final_path.read_bytes()).hexdigest()
        repository_path = (
            f"observations/{job.target_date}/{job.phase}/{final_path.name}"
        )
        self.store.update(
            job.observation_id,
            now=current,
            status="captured",
            capture_path=str(final_path),
            captured_at=captured_at,
            capture_sha256=digest,
            repository_path=repository_path,
            next_attempt_at=None,
            last_error="",
        )
        LOGGER.info("Captured %s at %s", job.observation_id, captured_at.isoformat())

    def _archive_job(self, job: ObservationJob, current: datetime) -> None:
        capture_path = Path(job.capture_path)
        actual_digest = hashlib.sha256(capture_path.read_bytes()).hexdigest()
        if actual_digest != job.capture_sha256:
            raise RuntimeError(
                f"Captured image checksum changed before archive: {job.observation_id}"
            )
        self.github.archive_capture(
            local_path=capture_path,
            repository_path=job.repository_path,
            data_ref=self.scheduler_settings.data_ref,
            base_ref=_env("GITHUB_REF", "main"),
            observation_id=job.observation_id,
        )
        self.store.update(
            job.observation_id,
            now=current,
            status="uploaded",
            next_attempt_at=None,
            last_error="",
        )
        LOGGER.info(
            "Archived %s to %s:%s",
            job.observation_id,
            self.scheduler_settings.data_ref,
            job.repository_path,
        )

    def _dispatch_job(self, job: ObservationJob, current: datetime) -> None:
        if job.captured_at is None:
            raise RuntimeError(f"{job.observation_id} has no captured_at")
        manual_mode = job.manual_mode
        if (
            manual_mode == "send_line"
            and current
            >= job.captured_at + LINE_RETRY_KEY_LIFETIME - LINE_RECOVERY_MARGIN
        ):
            manual_mode = "dry_run"
            LOGGER.warning(
                "Recovering log for %s without a late LINE retry after 23 hours",
                job.observation_id,
            )
        self.github.dispatch_observation(
            workflow=_env("GITHUB_WORKFLOW", "daily_chill.yml"),
            ref=_env("GITHUB_REF", "main"),
            inputs={
                "manual_mode": manual_mode,
                "date": job.target_date,
                "run_time": job.captured_at.astimezone(self.tz).strftime("%H:%M"),
                "observation_id": job.observation_id,
                "observation_phase": job.phase,
                "scheduled_at": job.scheduled_at.isoformat(timespec="seconds"),
                "captured_at": job.captured_at.isoformat(timespec="seconds"),
                "capture_ref": self.scheduler_settings.data_ref,
                "capture_path": job.repository_path,
                "capture_sha256": job.capture_sha256,
            },
        )
        attempts = job.dispatch_attempts + 1
        self.store.update(
            job.observation_id,
            now=current,
            status="dispatched",
            dispatch_attempts=attempts,
            last_dispatch_at=current,
            next_attempt_at=current
            + timedelta(seconds=self.scheduler_settings.run_visibility_grace_seconds),
            last_error="",
        )
        LOGGER.info("Dispatched %s (attempt %s)", job.observation_id, attempts)

    def _reconcile_run(self, job: ObservationJob, current: datetime) -> None:
        run = self.github.latest_observation_run(
            workflow=_env("GITHUB_WORKFLOW", "daily_chill.yml"),
            ref=_env("GITHUB_REF", "main"),
            observation_id=job.observation_id,
        )
        if run is None or not _is_current_run(run, job):
            retry_at = current + timedelta(
                seconds=_retry_seconds(
                    max(job.dispatch_attempts, 1),
                    self.scheduler_settings.retry_max_seconds,
                )
            )
            self.store.update(
                job.observation_id,
                now=current,
                status="uploaded",
                next_attempt_at=retry_at,
                last_error="GitHub workflow run was not visible after dispatch",
            )
            return
        if run.status != "completed":
            self.store.update(
                job.observation_id,
                now=current,
                github_run_id=run.run_id,
                github_run_url=run.url,
                next_attempt_at=current + timedelta(seconds=60),
            )
            return
        if run.conclusion == "success":
            self.store.update(
                job.observation_id,
                now=current,
                status="completed",
                github_run_id=run.run_id,
                github_run_url=run.url,
                completed_at=current,
                next_attempt_at=None,
                last_error="",
            )
            LOGGER.info("Completed %s in %s", job.observation_id, run.url)
            return
        retry_at = current + timedelta(
            seconds=_retry_seconds(
                max(job.dispatch_attempts, 1),
                self.scheduler_settings.retry_max_seconds,
            )
        )
        self.store.update(
            job.observation_id,
            now=current,
            status="uploaded",
            github_run_id=run.run_id,
            github_run_url=run.url,
            next_attempt_at=retry_at,
            last_error=f"GitHub workflow concluded with {run.conclusion or 'unknown'}",
        )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        app_settings = Settings.from_env()
        scheduler_settings = SchedulerSettings.from_env()
        logging.basicConfig(
            level=getattr(logging, app_settings.log_level.upper(), logging.INFO),
            format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
        )
        scheduler_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        with _process_lock(scheduler_settings.database_path.with_suffix(".lock")) as acquired:
            if not acquired:
                LOGGER.info("Another observation scheduler process is active; skipping")
                return 0
            store = ObservationJobStore(scheduler_settings.database_path)
            github = GitHubCaptureStore(
                repository=_required_env("GITHUB_REPOSITORY"),
                token=_required_env("GITHUB_TOKEN"),
            )
            scheduler = ObservationScheduler(
                app_settings=app_settings,
                scheduler_settings=scheduler_settings,
                store=store,
                github=github,
            )
            if args.audit:
                target_date = (
                    datetime.strptime(args.date, "%Y-%m-%d").date()
                    if args.date
                    else datetime.now(ZoneInfo(app_settings.timezone)).date()
                )
                incomplete = scheduler.audit(target_date)
                print(
                    json.dumps(
                        [
                            {
                                "observation_id": job.observation_id,
                                "status": job.status,
                                "scheduled_at": job.scheduled_at.isoformat(),
                                "captured_at": (
                                    job.captured_at.isoformat() if job.captured_at else None
                                ),
                                "last_error": job.last_error,
                            }
                            for job in incomplete
                        ],
                        ensure_ascii=False,
                    )
                )
                return 1 if incomplete else 0
            scheduler.tick()
            return 0
    except Exception as exc:
        logging.getLogger(__name__).exception("Observation scheduler failed: %s", exc)
        return 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Persist, capture, and reconcile sunset observation jobs."
    )
    parser.add_argument("--audit", action="store_true", help="Report incomplete jobs and exit.")
    parser.add_argument("--date", help="Audit date in YYYY-MM-DD. Defaults to today.")
    args = parser.parse_args(argv)
    if args.date:
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError as exc:
            parser.error("--date must be YYYY-MM-DD")
            raise AssertionError from exc
    if args.date and not args.audit:
        parser.error("--date requires --audit")
    return args


@contextmanager
def _process_lock(path: Path) -> Iterator[bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _job_from_row(row: sqlite3.Row) -> ObservationJob:
    return ObservationJob(
        observation_id=str(row["observation_id"]),
        target_date=str(row["target_date"]),
        phase=str(row["phase"]),
        scheduled_at=_parse_datetime(row["scheduled_at"]),
        manual_mode=str(row["manual_mode"]),
        status=str(row["status"]),
        capture_path=str(row["capture_path"]),
        captured_at=_parse_optional_datetime(row["captured_at"]),
        capture_sha256=str(row["capture_sha256"]),
        repository_path=str(row["repository_path"]),
        dispatch_attempts=int(row["dispatch_attempts"]),
        last_dispatch_at=_parse_optional_datetime(row["last_dispatch_at"]),
        next_attempt_at=_parse_optional_datetime(row["next_attempt_at"]),
        github_run_id=(
            int(row["github_run_id"]) if row["github_run_id"] is not None else None
        ),
        github_run_url=str(row["github_run_url"]),
        last_error=str(row["last_error"]),
        completed_at=_parse_optional_datetime(row["completed_at"]),
    )


def _is_current_run(run: WorkflowRun, job: ObservationJob) -> bool:
    if job.last_dispatch_at is None:
        return True
    return run.created_at >= job.last_dispatch_at.astimezone(run.created_at.tzinfo) - timedelta(
        minutes=1
    )


def _retry_seconds(attempts: int, maximum: int) -> int:
    return min(60 * (2 ** max(attempts - 1, 0)), maximum)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"Stored datetime is missing timezone: {value}")
    return parsed


def _parse_optional_datetime(value: object) -> datetime | None:
    return _parse_datetime(str(value)) if value else None


def _env(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _required_env(name: str) -> str:
    value = _env(name, "")
    if not value:
        raise ConfigError(f"{name} is required")
    return value


def _positive_int(name: str, *, default: int) -> int:
    value = _env(name, str(default))
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise ConfigError(f"{name} must be a positive integer")
    return parsed


if __name__ == "__main__":
    sys.exit(main())
