from __future__ import annotations

import csv
from dataclasses import replace

import pytest
from zushi_chill.config import ConfigError, Settings
from zushi_chill.models import PredictionRecord, ScoreResult
from zushi_chill.storage import CSV_COLUMNS, CsvStorage, GoogleSheetsStorage, storage_from_settings


def test_csv_storage_writes_prediction_record(tmp_path, sample_summary):
    path = tmp_path / "predictions.csv"
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    CsvStorage(path).save(PredictionRecord(summary=sample_summary, scores=scores, line_sent=False))

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-06-01"
    assert rows[0]["chill_score"] == "88"
    assert rows[0]["line_sent"] == "False"


def test_csv_storage_writes_header_when_file_exists_but_empty(tmp_path, sample_summary):
    path = tmp_path / "predictions.csv"
    path.touch()
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    CsvStorage(path).save(PredictionRecord(summary=sample_summary, scores=scores, line_sent=False))

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-06-01"
    assert rows[0]["line_sent"] == "False"


def test_csv_storage_rejects_mismatched_header_on_save(tmp_path, sample_summary):
    path = tmp_path / "predictions.csv"
    path.write_text("date,unexpected\n", encoding="utf-8")
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    with pytest.raises(ConfigError, match="CSV header"):
        CsvStorage(path).save(
            PredictionRecord(summary=sample_summary, scores=scores, line_sent=False)
        )


def test_csv_storage_rejects_mismatched_header_on_replace(tmp_path, sample_summary):
    path = tmp_path / "predictions.csv"
    path.write_text("date,unexpected\n2026-06-01,value\n", encoding="utf-8")
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    with pytest.raises(ConfigError, match="CSV header"):
        CsvStorage(path).replace_latest(
            PredictionRecord(summary=sample_summary, scores=scores, line_sent=True)
        )


def test_storage_from_settings_selects_csv_backend(tmp_path):
    settings = _settings(storage_backend="csv", csv_path=str(tmp_path / "predictions.csv"))

    storage = storage_from_settings(settings)

    assert isinstance(storage, CsvStorage)
    assert storage.path == tmp_path / "predictions.csv"


def test_csv_storage_replaces_latest_prediction_result(tmp_path, sample_summary):
    path = tmp_path / "predictions.csv"
    storage = CsvStorage(path)
    pending = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")
    sent = ScoreResult(sunset_score=91, sunset_label="S", chill_score=89, chill_label="S")

    storage.save(PredictionRecord(summary=sample_summary, scores=pending, line_sent=False))
    storage.replace_latest(PredictionRecord(summary=sample_summary, scores=sent, line_sent=True))

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["chill_score"] == "89"
    assert rows[0]["line_sent"] == "True"


def test_csv_storage_replaces_last_matching_prediction_result(tmp_path, sample_summary):
    path = tmp_path / "predictions.csv"
    storage = CsvStorage(path)
    old = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")
    pending = ScoreResult(sunset_score=91, sunset_label="S", chill_score=89, chill_label="S")
    sent = ScoreResult(sunset_score=92, sunset_label="S", chill_score=90, chill_label="S")

    storage.save(PredictionRecord(summary=sample_summary, scores=old, line_sent=False))
    storage.save(PredictionRecord(summary=sample_summary, scores=pending, line_sent=False))
    storage.replace_latest(PredictionRecord(summary=sample_summary, scores=sent, line_sent=True))

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 2
    assert rows[0]["chill_score"] == "88"
    assert rows[0]["line_sent"] == "False"
    assert rows[1]["chill_score"] == "90"
    assert rows[1]["line_sent"] == "True"


def test_csv_storage_replaces_only_matching_run_time(tmp_path, sample_summary):
    path = tmp_path / "predictions.csv"
    storage = CsvStorage(path)
    pending = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")
    sent = ScoreResult(sunset_score=91, sunset_label="S", chill_score=89, chill_label="S")
    afternoon_summary = replace(sample_summary, run_time="17:00")

    storage.save(PredictionRecord(summary=sample_summary, scores=pending, line_sent=False))
    storage.save(PredictionRecord(summary=afternoon_summary, scores=pending, line_sent=False))
    storage.replace_latest(
        PredictionRecord(summary=afternoon_summary, scores=sent, line_sent=True)
    )

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 2
    assert rows[0]["run_time"] == "13:00"
    assert rows[0]["line_sent"] == "False"
    assert rows[0]["chill_score"] == "88"
    assert rows[1]["run_time"] == "17:00"
    assert rows[1]["line_sent"] == "True"
    assert rows[1]["chill_score"] == "89"


def test_google_sheets_storage_appends_with_header(sample_summary):
    fake_service = FakeSheetsService(get_values=[], sheet_titles=["predictions"])
    storage = GoogleSheetsStorage(
        spreadsheet_id="sheet-id",
        worksheet="predictions",
        service_account_json="{}",
    )
    storage._service = fake_service
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    storage.save(PredictionRecord(summary=sample_summary, scores=scores, line_sent=False))

    assert fake_service.updates[0]["body"]["values"] == [CSV_COLUMNS]
    assert fake_service.appends[0]["body"]["values"][0][0:3] == [
        "2026-06-01",
        "13:00",
        "逗子海岸",
    ]
    assert fake_service.batch_updates == []


def test_storage_from_settings_selects_google_sheets_backend():
    settings = _settings(
        storage_backend="google_sheets",
        google_sheets_spreadsheet_id="sheet-id",
        google_sheets_worksheet="predictions",
        google_service_account_json='{"type":"service_account"}',
    )

    storage = storage_from_settings(settings)

    assert isinstance(storage, GoogleSheetsStorage)
    assert storage.spreadsheet_id == "sheet-id"
    assert storage.worksheet == "predictions"
    assert storage.service_account_json == '{"type":"service_account"}'


def test_google_sheets_storage_creates_missing_worksheet(sample_summary):
    fake_service = FakeSheetsService(get_values=[], sheet_titles=["Sheet1"])
    storage = GoogleSheetsStorage(
        spreadsheet_id="sheet-id",
        worksheet="predictions",
        service_account_json="{}",
    )
    storage._service = fake_service
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    storage.save(PredictionRecord(summary=sample_summary, scores=scores, line_sent=False))

    assert fake_service.batch_updates[0]["body"] == {
        "requests": [{"addSheet": {"properties": {"title": "predictions"}}}]
    }
    assert fake_service.updates[0]["body"]["values"] == [CSV_COLUMNS]


def test_google_sheets_storage_rejects_mismatched_header(sample_summary):
    fake_service = FakeSheetsService(
        get_values=[["date", "unexpected"]],
        sheet_titles=["predictions"],
    )
    storage = GoogleSheetsStorage(
        spreadsheet_id="sheet-id",
        worksheet="predictions",
        service_account_json="{}",
    )
    storage._service = fake_service
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    with pytest.raises(ConfigError, match="header"):
        storage.save(PredictionRecord(summary=sample_summary, scores=scores, line_sent=False))

    assert fake_service.appends == []


def test_google_sheets_storage_replaces_existing_row(sample_summary):
    fake_service = FakeSheetsService(
        get_values=[
            CSV_COLUMNS,
            ["2026-06-01", "13:00", "逗子海岸"],
        ],
        sheet_titles=["predictions"],
    )
    storage = GoogleSheetsStorage(
        spreadsheet_id="sheet-id",
        worksheet="predictions",
        service_account_json="{}",
    )
    storage._service = fake_service
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    storage.replace_latest(PredictionRecord(summary=sample_summary, scores=scores, line_sent=True))

    assert fake_service.updates[-1]["range"] == "'predictions'!A2:AC2"
    assert fake_service.updates[-1]["body"]["values"][0][-2] is True
    assert fake_service.appends == []


def test_google_sheets_storage_replaces_last_matching_row(sample_summary):
    fake_service = FakeSheetsService(
        get_values=[
            CSV_COLUMNS,
            ["2026-06-01", "13:00", "逗子海岸"],
            ["2026-06-01", "13:00", "逗子海岸"],
        ],
        sheet_titles=["predictions"],
    )
    storage = GoogleSheetsStorage(
        spreadsheet_id="sheet-id",
        worksheet="predictions",
        service_account_json="{}",
    )
    storage._service = fake_service
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    storage.replace_latest(PredictionRecord(summary=sample_summary, scores=scores, line_sent=True))

    assert fake_service.updates[-1]["range"] == "'predictions'!A3:AC3"
    assert fake_service.appends == []


def test_google_sheets_storage_appends_when_run_time_does_not_match(sample_summary):
    fake_service = FakeSheetsService(
        get_values=[
            CSV_COLUMNS,
            ["2026-06-01", "13:00", "逗子海岸"],
        ],
        sheet_titles=["predictions"],
    )
    storage = GoogleSheetsStorage(
        spreadsheet_id="sheet-id",
        worksheet="predictions",
        service_account_json="{}",
    )
    storage._service = fake_service
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")
    afternoon_summary = replace(sample_summary, run_time="17:00")

    storage.replace_latest(
        PredictionRecord(summary=afternoon_summary, scores=scores, line_sent=True)
    )

    assert fake_service.updates == []
    assert fake_service.appends[-1]["body"]["values"][0][0:3] == [
        "2026-06-01",
        "17:00",
        "逗子海岸",
    ]


def test_google_sheets_storage_quotes_worksheet_name_in_ranges(sample_summary):
    fake_service = FakeSheetsService(
        get_values=[
            CSV_COLUMNS,
            ["2026-06-01", "13:00", "逗子海岸"],
        ],
        sheet_titles=["June's predictions"],
    )
    storage = GoogleSheetsStorage(
        spreadsheet_id="sheet-id",
        worksheet="June's predictions",
        service_account_json="{}",
    )
    storage._service = fake_service
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    storage.replace_latest(PredictionRecord(summary=sample_summary, scores=scores, line_sent=True))

    assert fake_service.last_get["range"] == "'June''s predictions'!A:C"
    assert fake_service.updates[-1]["range"] == "'June''s predictions'!A2:AC2"


def test_google_sheets_storage_requires_spreadsheet_id(sample_summary):
    storage = GoogleSheetsStorage(
        spreadsheet_id="",
        worksheet="predictions",
        service_account_json="{}",
    )
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    with pytest.raises(ConfigError, match="GOOGLE_SHEETS_SPREADSHEET_ID"):
        storage.save(PredictionRecord(summary=sample_summary, scores=scores, line_sent=False))


def test_google_sheets_storage_requires_service_account_json(sample_summary):
    storage = GoogleSheetsStorage(
        spreadsheet_id="sheet-id",
        worksheet="predictions",
        service_account_json="",
    )
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    with pytest.raises(ConfigError, match="GOOGLE_SERVICE_ACCOUNT_JSON"):
        storage.save(PredictionRecord(summary=sample_summary, scores=scores, line_sent=False))


def test_google_sheets_storage_rejects_invalid_service_account_json(sample_summary):
    storage = GoogleSheetsStorage(
        spreadsheet_id="sheet-id",
        worksheet="predictions",
        service_account_json="{not json",
    )
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    with pytest.raises(ConfigError, match="JSON object string"):
        storage.save(PredictionRecord(summary=sample_summary, scores=scores, line_sent=False))


def test_google_sheets_storage_rejects_non_object_service_account_json(sample_summary):
    storage = GoogleSheetsStorage(
        spreadsheet_id="sheet-id",
        worksheet="predictions",
        service_account_json="[]",
    )
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    with pytest.raises(ConfigError, match="JSON object string"):
        storage.save(PredictionRecord(summary=sample_summary, scores=scores, line_sent=False))


class FakeSheetsService:
    def __init__(self, *, get_values, sheet_titles):
        self.get_values = get_values
        self.sheet_titles = sheet_titles
        self.updates = []
        self.appends = []
        self.batch_updates = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kwargs):
        self.last_get = kwargs
        if "range" not in kwargs:
            return FakeExecute(
                {
                    "sheets": [
                        {"properties": {"title": title}} for title in self.sheet_titles
                    ]
                }
            )
        return FakeExecute({"values": self.get_values})

    def update(self, **kwargs):
        self.updates.append(kwargs)
        return FakeExecute({})

    def batchUpdate(self, **kwargs):
        self.batch_updates.append(kwargs)
        return FakeExecute({})

    def append(self, **kwargs):
        self.appends.append(kwargs)
        return FakeExecute({})


class FakeExecute:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


def _settings(**overrides):
    values = {
        "location_name": "逗子海岸",
        "latitude": 35.2956,
        "longitude": 139.5736,
        "timezone": "Asia/Tokyo",
        "line_channel_access_token": "",
        "line_target_id": "",
        "google_form_url": "",
        "storage_backend": "csv",
        "csv_path": "logs/chill_predictions.csv",
        "google_sheets_spreadsheet_id": "",
        "google_sheets_worksheet": "predictions",
        "google_service_account_json": "",
        "dry_run": False,
        "log_level": "INFO",
        "allow_missing_hourly_fields": frozenset(),
    }
    values.update(overrides)
    return Settings(**values)
