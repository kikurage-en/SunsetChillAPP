from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from zushi_chill.afterglow_selector import RankedAfterglowCandidate
from zushi_chill.config import Settings
from zushi_chill.github_capture_store import WorkflowRun
from zushi_chill.live_camera import LiveCameraFrame
from zushi_chill.observation_scheduler import (
    ObservationJobStore,
    ObservationScheduler,
    SchedulerSettings,
    _normalize_capture,
)

JST = ZoneInfo("Asia/Tokyo")


class FakeGitHub:
    def __init__(self):
        self.dispatched = []
        self.run = None

    def dispatch_observation(self, **kwargs):
        self.dispatched.append(kwargs)

    def latest_observation_run(self, **kwargs):
        return self.run


def test_scheduler_captures_dispatches_exact_image_and_reconciles(tmp_path):
    clock = [datetime(2026, 7, 26, 18, 50, tzinfo=JST)]
    github = FakeGitHub()
    store = ObservationJobStore(tmp_path / "jobs.sqlite3")

    def capture(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"sunset-image")

    scheduler = ObservationScheduler(
        app_settings=_app_settings(),
        scheduler_settings=_scheduler_settings(tmp_path),
        store=store,
        github=github,
        now=lambda: clock[0],
        capture=capture,
    )

    scheduler.tick(now=clock[0])

    job = store.get("2026-07-26:sunset")
    assert job.status == "dispatched"
    assert Path(job.capture_path).read_bytes() == b"sunset-image"
    assert job.captured_at == clock[0]
    inputs = github.dispatched[0]["inputs"]
    assert inputs["observation_id"] == "2026-07-26:sunset"
    assert inputs["scheduled_at"] == "2026-07-26T18:50:00+09:00"
    assert inputs["captured_at"] == "2026-07-26T18:50:00+09:00"
    assert inputs["capture_window_minutes"] == "10"
    assert inputs["capture_sha256"] == job.capture_sha256
    assert base64.b64decode(inputs["capture_base64"]) == b"sunset-image"

    clock[0] += timedelta(minutes=3)
    github.run = WorkflowRun(
        run_id=123,
        status="completed",
        conclusion="success",
        created_at=datetime(2026, 7, 26, 9, 51, tzinfo=ZoneInfo("UTC")),
        url="https://github.example/runs/123",
    )
    scheduler.tick(now=clock[0])

    completed = store.get("2026-07-26:sunset")
    assert completed.status == "completed"
    assert completed.github_run_id == 123


def test_scheduler_retries_capture_then_marks_expired_window(tmp_path):
    clock = [datetime(2026, 7, 26, 18, 50, tzinfo=JST)]
    store = ObservationJobStore(tmp_path / "jobs.sqlite3")

    def capture(**kwargs):
        raise RuntimeError("camera unavailable")

    scheduler = ObservationScheduler(
        app_settings=_app_settings(),
        scheduler_settings=_scheduler_settings(tmp_path, capture_max_delay_minutes=10),
        store=store,
        github=FakeGitHub(),
        now=lambda: clock[0],
        capture=capture,
    )

    scheduler.tick(now=clock[0])
    failed = store.get("2026-07-26:sunset")
    assert failed.status == "planned"
    assert "camera unavailable" in failed.last_error
    assert failed.next_attempt_at == clock[0] + timedelta(minutes=1)
    store.update(
        "2026-07-26:afterglow",
        now=clock[0],
        status="completed",
        completed_at=clock[0],
    )

    clock[0] += timedelta(minutes=11)
    scheduler.tick(now=clock[0])
    expired = store.get("2026-07-26:sunset")
    assert expired.status == "capture_missed"
    assert "Capture window expired" in expired.last_error


def test_scheduler_captures_freshest_phase_first_when_both_are_due(tmp_path):
    clock = [datetime(2026, 7, 26, 19, 10, tzinfo=JST)]
    captured_phases = []

    def capture(**kwargs):
        output_path = Path(kwargs["output_path"])
        captured_phases.append(output_path.parent.name)
        output_path.write_bytes(b"image")

    scheduler = ObservationScheduler(
        app_settings=_app_settings(),
        scheduler_settings=_scheduler_settings(tmp_path),
        store=ObservationJobStore(tmp_path / "jobs.sqlite3"),
        github=FakeGitHub(),
        now=lambda: clock[0],
        capture=capture,
    )

    scheduler.tick(now=clock[0])

    assert captured_phases == ["afterglow", "sunset"]


def test_scheduler_samples_afterglow_window_and_dispatches_vision_winner(tmp_path):
    clock = [datetime(2026, 7, 26, 19, 0, tzinfo=JST)]
    github = FakeGitHub()
    store = ObservationJobStore(tmp_path / "jobs.sqlite3")
    sequence_calls = []
    vision_calls = []

    def capture_sequence(**kwargs):
        sequence_calls.append(kwargs)
        candidate_dir = Path(kwargs["output_directory"])
        candidate_dir.mkdir(parents=True)
        frames = []
        for index, image in enumerate((b"orange", b"purple", b"gray")):
            path = candidate_dir / f"frame-{index + 1:03d}.jpg"
            path.write_bytes(image)
            frames.append(
                LiveCameraFrame(
                    path=path,
                    captured_at=clock[0] + timedelta(seconds=index * 60),
                )
            )
        return tuple(frames)

    def rank_afterglow(frames):
        return tuple(
            RankedAfterglowCandidate(
                frame=frame,
                local_score=90 - index * 10,
                sha256=hashlib.sha256(frame.path.read_bytes()).hexdigest(),
            )
            for index, frame in enumerate(frames)
        )

    def select_best_afterglow(**kwargs):
        vision_calls.append(kwargs)
        return 1

    scheduler = ObservationScheduler(
        app_settings=replace(
            _app_settings(),
            vision_enabled=True,
            vision_api_key="vision-key",
        ),
        scheduler_settings=_scheduler_settings(tmp_path),
        store=store,
        github=github,
        now=lambda: clock[0],
        capture_sequence=capture_sequence,
        rank_afterglow=rank_afterglow,
        select_best_afterglow=select_best_afterglow,
    )
    scheduler.ensure_daily_jobs(clock[0].date(), now=clock[0])
    store.update(
        "2026-07-26:sunset",
        now=clock[0],
        status="completed",
        completed_at=clock[0],
    )

    scheduler.tick(now=clock[0])

    job = store.get("2026-07-26:afterglow")
    assert job.scheduled_at == datetime(2026, 7, 26, 19, 10, tzinfo=JST)
    assert job.captured_at == clock[0] + timedelta(seconds=60)
    assert Path(job.capture_path).read_bytes() == b"purple"
    assert sequence_calls[0]["duration_seconds"] == 600
    assert sequence_calls[0]["interval_seconds"] == 60
    assert sequence_calls[0]["fallback_interval_seconds"] == 60
    assert [path.read_bytes() for path in vision_calls[0]["image_paths"]] == [
        b"orange",
        b"purple",
        b"gray",
    ]
    assert base64.b64decode(github.dispatched[0]["inputs"]["capture_base64"]) == b"purple"
    manifest = json.loads(
        (tmp_path / "spool/2026-07-26/afterglow/selection.json").read_text()
    )
    assert manifest["selection_method"] == "vision_comparison"
    assert manifest["selected_sha256"] == hashlib.sha256(b"purple").hexdigest()


def test_scheduler_uses_local_afterglow_winner_when_vision_comparison_fails(tmp_path):
    now = datetime(2026, 7, 26, 19, 0, tzinfo=JST)
    store = ObservationJobStore(tmp_path / "jobs.sqlite3")

    def capture_sequence(**kwargs):
        candidate_dir = Path(kwargs["output_directory"])
        candidate_dir.mkdir(parents=True)
        frames = []
        for index, image in enumerate((b"local-winner", b"runner-up")):
            path = candidate_dir / f"frame-{index + 1:03d}.jpg"
            path.write_bytes(image)
            frames.append(
                LiveCameraFrame(
                    path=path,
                    captured_at=now + timedelta(seconds=index * 60),
                )
            )
        return tuple(frames)

    def rank_afterglow(frames):
        return tuple(
            RankedAfterglowCandidate(
                frame=frame,
                local_score=90 - index * 20,
                sha256=hashlib.sha256(frame.path.read_bytes()).hexdigest(),
            )
            for index, frame in enumerate(frames)
        )

    def fail_vision_comparison(**kwargs):
        raise RuntimeError("vision unavailable")

    scheduler = ObservationScheduler(
        app_settings=replace(
            _app_settings(),
            vision_enabled=True,
            vision_api_key="vision-key",
        ),
        scheduler_settings=_scheduler_settings(tmp_path),
        store=store,
        github=FakeGitHub(),
        now=lambda: now,
        capture_sequence=capture_sequence,
        rank_afterglow=rank_afterglow,
        select_best_afterglow=fail_vision_comparison,
    )
    scheduler.ensure_daily_jobs(now.date(), now=now)
    store.update(
        "2026-07-26:sunset",
        now=now,
        status="completed",
        completed_at=now,
    )

    scheduler.tick(now=now)

    job = store.get("2026-07-26:afterglow")
    assert Path(job.capture_path).read_bytes() == b"local-winner"
    manifest = json.loads(
        (tmp_path / "spool/2026-07-26/afterglow/selection.json").read_text()
    )
    assert manifest["selection_method"] == "local_color"


def test_scheduler_refuses_to_dispatch_a_capture_whose_checksum_changed(tmp_path):
    now = datetime(2026, 7, 26, 18, 50, tzinfo=JST)
    github = FakeGitHub()
    store = ObservationJobStore(tmp_path / "jobs.sqlite3")
    scheduler = ObservationScheduler(
        app_settings=_app_settings(),
        scheduler_settings=_scheduler_settings(tmp_path),
        store=store,
        github=github,
        now=lambda: now,
    )
    scheduler.ensure_daily_jobs(now.date(), now=now)
    capture_path = tmp_path / "changed.jpg"
    capture_path.write_bytes(b"changed-image")
    store.update(
        "2026-07-26:sunset",
        now=now,
        status="captured",
        capture_path=str(capture_path),
        captured_at=now,
        capture_sha256=hashlib.sha256(b"original-image").hexdigest(),
    )

    scheduler.tick(now=now)

    failed = store.get("2026-07-26:sunset")
    assert failed.status == "captured"
    assert "checksum changed" in failed.last_error


def test_capture_normalization_replaces_large_image_with_dispatch_sized_jpeg(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "large.jpg"
    path.write_bytes(b"x" * 50_000)

    def fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(b"j" * 40_000)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("zushi_chill.observation_scheduler.subprocess.run", fake_run)

    _normalize_capture(path)

    assert path.read_bytes() == b"j" * 40_000


def test_scheduler_retries_failed_workflow_without_recapturing(tmp_path):
    clock = [datetime(2026, 7, 26, 19, 10, tzinfo=JST)]
    github = FakeGitHub()
    store = ObservationJobStore(tmp_path / "jobs.sqlite3")
    capture_count = 0

    def capture(**kwargs):
        nonlocal capture_count
        capture_count += 1
        Path(kwargs["output_path"]).write_bytes(b"afterglow-image")

    scheduler = ObservationScheduler(
        app_settings=_app_settings(),
        scheduler_settings=_scheduler_settings(tmp_path),
        store=store,
        github=github,
        now=lambda: clock[0],
        capture=capture,
    )
    scheduler.ensure_daily_jobs(clock[0].date(), now=clock[0])
    store.update(
        "2026-07-26:sunset",
        now=clock[0],
        status="completed",
        completed_at=clock[0],
    )
    scheduler.tick(now=clock[0])

    clock[0] += timedelta(minutes=3)
    github.run = WorkflowRun(
        run_id=456,
        status="completed",
        conclusion="failure",
        created_at=datetime(2026, 7, 26, 10, 11, tzinfo=ZoneInfo("UTC")),
        url="https://github.example/runs/456",
    )
    scheduler.tick(now=clock[0])
    failed = store.get("2026-07-26:afterglow")
    assert failed.status == "uploaded"
    assert failed.capture_path

    clock[0] = failed.next_attempt_at
    github.run = None
    scheduler.tick(now=clock[0])
    assert capture_count == 1
    assert len(github.dispatched) == 2


def test_job_store_survives_reopen_and_audit_reports_missing_phase(tmp_path):
    now = datetime(2026, 7, 26, 21, 30, tzinfo=JST)
    path = tmp_path / "jobs.sqlite3"
    first_store = ObservationJobStore(path)
    scheduler = ObservationScheduler(
        app_settings=_app_settings(),
        scheduler_settings=_scheduler_settings(tmp_path),
        store=first_store,
        github=FakeGitHub(),
        now=lambda: now,
        capture=lambda **kwargs: None,
    )
    scheduler.ensure_daily_jobs(now.date(), now=now)
    first_store.update(
        "2026-07-26:sunset",
        now=now,
        status="completed",
        completed_at=now,
    )

    reopened_store = ObservationJobStore(path)
    reopened_scheduler = ObservationScheduler(
        app_settings=_app_settings(),
        scheduler_settings=_scheduler_settings(tmp_path),
        store=reopened_store,
        github=FakeGitHub(),
        now=lambda: now,
    )

    incomplete = reopened_scheduler.audit(now.date(), now=now)
    assert [job.observation_id for job in incomplete] == ["2026-07-26:afterglow"]


def test_afterglow_retry_becomes_log_only_before_line_retry_key_expires(tmp_path):
    clock = [datetime(2026, 7, 26, 19, 10, tzinfo=JST)]
    github = FakeGitHub()
    store = ObservationJobStore(tmp_path / "jobs.sqlite3")

    def capture(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"afterglow-image")

    scheduler = ObservationScheduler(
        app_settings=_app_settings(),
        scheduler_settings=_scheduler_settings(tmp_path),
        store=store,
        github=github,
        now=lambda: clock[0],
        capture=capture,
    )
    scheduler.ensure_daily_jobs(clock[0].date(), now=clock[0])
    store.update(
        "2026-07-26:sunset",
        now=clock[0],
        status="completed",
        completed_at=clock[0],
    )
    scheduler.tick(now=clock[0])

    clock[0] += timedelta(minutes=3)
    github.run = WorkflowRun(
        run_id=789,
        status="completed",
        conclusion="failure",
        created_at=datetime(2026, 7, 26, 10, 11, tzinfo=ZoneInfo("UTC")),
        url="https://github.example/runs/789",
    )
    scheduler.tick(now=clock[0])

    captured_at = store.get("2026-07-26:afterglow").captured_at
    assert captured_at is not None
    clock[0] = captured_at + timedelta(hours=23)
    github.run = None
    scheduler.tick(now=clock[0])

    assert github.dispatched[-1]["inputs"]["manual_mode"] == "dry_run"


def test_scheduler_settings_parse_afterglow_window(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSERVATION_DB_PATH", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setenv("OBSERVATION_SPOOL_DIR", str(tmp_path / "spool"))
    monkeypatch.setenv("AFTERGLOW_PREFILTER_CANDIDATES", "3")

    settings = SchedulerSettings.from_env()

    assert settings.afterglow_offset_minutes == 20
    assert settings.afterglow_window_minutes == 10
    assert settings.afterglow_capture_interval_seconds == 60
    assert settings.afterglow_thumbnail_interval_seconds == 60
    assert settings.afterglow_prefilter_candidates == 3

    monkeypatch.setenv("AFTERGLOW_WINDOW_MINUTES", "21")
    with pytest.raises(ValueError, match="cannot exceed AFTERGLOW_OFFSET_MINUTES"):
        SchedulerSettings.from_env()


def _scheduler_settings(tmp_path, *, capture_max_delay_minutes=60):
    return SchedulerSettings(
        database_path=tmp_path / "jobs.sqlite3",
        spool_directory=tmp_path / "spool",
        afterglow_offset_minutes=20,
        afterglow_window_minutes=10,
        afterglow_capture_interval_seconds=60,
        afterglow_thumbnail_interval_seconds=60,
        afterglow_prefilter_candidates=3,
        capture_max_delay_minutes=capture_max_delay_minutes,
        run_visibility_grace_seconds=120,
        retry_max_seconds=1800,
    )


def _app_settings():
    return Settings(
        location_name="逗子海岸",
        latitude=35.2956,
        longitude=139.5736,
        timezone="Asia/Tokyo",
        line_channel_access_token="",
        line_target_id="",
        line_channel_secret="",
        line_bot_user_id="",
        storage_backend="csv",
        csv_path="logs/test.csv",
        google_sheets_spreadsheet_id="",
        google_sheets_worksheet="predictions",
        google_service_account_json="",
        dry_run=False,
        log_level="INFO",
        allow_missing_hourly_fields=frozenset(),
        live_camera_url="https://camera.example/live",
        live_camera_video_id="video-id",
        live_camera_capture_timeout_seconds=20,
    )
