import csv
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from zushi_chill.models import PredictionRecord, ScoreResult
from zushi_chill.storage import CsvStorage


def test_observation_metadata_records_actual_delay(sample_summary):
    scheduled = datetime(2026, 6, 1, 18, 50, tzinfo=ZoneInfo("Asia/Tokyo"))
    captured = datetime(2026, 6, 1, 18, 57, tzinfo=ZoneInfo("Asia/Tokyo"))
    record = PredictionRecord(
        summary=sample_summary,
        scores=ScoreResult(60, "B", 55, "B"),
        line_sent=False,
        observation_id="2026-06-01:sunset",
        observation_phase="sunset",
        scheduled_at=scheduled,
        captured_at=captured,
    )

    row = record.to_row()

    assert row["scheduled_at"] == "2026-06-01T18:50:00+09:00"
    assert row["captured_at"] == "2026-06-01T18:57:00+09:00"
    assert row["capture_delay_seconds"] == 420
    assert row["observation_data_quality"] == "delayed"


def test_csv_observation_upsert_and_sent_check_use_stable_id(tmp_path, sample_summary):
    path = tmp_path / "observations.csv"
    storage = CsvStorage(path)
    scheduled = datetime(2026, 6, 1, 18, 50, tzinfo=ZoneInfo("Asia/Tokyo"))
    captured = datetime(2026, 6, 1, 18, 51, tzinfo=ZoneInfo("Asia/Tokyo"))
    initial = PredictionRecord(
        summary=sample_summary,
        scores=ScoreResult(60, "B", 55, "B"),
        line_sent=False,
        observation_id="2026-06-01:sunset",
        observation_phase="sunset",
        scheduled_at=scheduled,
        captured_at=captured,
    )
    changed_summary = replace(sample_summary, run_time="18:52")
    completed = replace(initial, summary=changed_summary, line_sent=True)

    storage.replace_latest(initial)
    storage.replace_latest(completed)

    with path.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 1
    assert rows[0]["run_time"] == "18:52"
    assert rows[0]["observation_id"] == "2026-06-01:sunset"
    assert storage.has_sent(
        date="2026-06-01",
        run_time="18:51",
        location_name="逗子海岸",
        observation_id="2026-06-01:sunset",
    )
