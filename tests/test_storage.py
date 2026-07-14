from __future__ import annotations

import csv
from dataclasses import replace

import pytest
from zushi_chill.config import ConfigError, Settings
from zushi_chill.models import PredictionRecord, ScoreResult, VisionResult
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


def test_csv_columns_include_vision_fields_after_error_message():
    for column in (
        "vision_sunset_score",
        "vision_sky_condition",
        "vision_comment",
        "vision_model",
    ):
        assert column in CSV_COLUMNS
        assert CSV_COLUMNS.index(column) > CSV_COLUMNS.index("error_message")


def test_csv_storage_writes_vision_fields_when_present(tmp_path, sample_summary):
    path = tmp_path / "predictions.csv"
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")
    vision = VisionResult(
        sunset_score=82,
        sky_condition="golden_hour",
        comment="美しい夕焼け",
        model="gemini-2.5-flash",
    )

    CsvStorage(path).save(
        PredictionRecord(summary=sample_summary, scores=scores, line_sent=True, vision=vision)
    )

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows[0]["vision_sunset_score"] == "82"
    assert rows[0]["vision_sky_condition"] == "golden_hour"
    assert rows[0]["vision_comment"] == "美しい夕焼け"
    assert rows[0]["vision_model"] == "gemini-2.5-flash"


def test_csv_storage_writes_empty_vision_fields_when_absent(tmp_path, sample_summary):
    path = tmp_path / "predictions.csv"
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    CsvStorage(path).save(
        PredictionRecord(summary=sample_summary, scores=scores, line_sent=False)
    )

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows[0]["vision_sunset_score"] == ""
    assert rows[0]["vision_model"] == ""


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


def test_csv_storage_detects_sent_record(tmp_path, sample_summary):
    path = tmp_path / "predictions.csv"
    storage = CsvStorage(path)
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    storage.save(PredictionRecord(summary=sample_summary, scores=scores, line_sent=False))

    assert (
        storage.has_sent(
            date="2026-06-01",
            run_time="13:00",
            location_name="逗子海岸",
        )
        is False
    )

    storage.replace_latest(PredictionRecord(summary=sample_summary, scores=scores, line_sent=True))

    assert (
        storage.has_sent(
            date="2026-06-01",
            run_time="13:00",
            location_name="逗子海岸",
        )
        is True
    )
    assert (
        storage.has_sent(
            date="2026-06-01",
            run_time="17:00",
            location_name="逗子海岸",
        )
        is False
    )


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


def test_google_sheets_storage_migrates_legacy_header(sample_summary):
    legacy_header = CSV_COLUMNS[:-4]  # vision 4カラム追加前の旧ヘッダ
    fake_service = FakeSheetsService(
        get_values=[legacy_header, ["2026-06-01", "13:00", "逗子海岸"]],
        sheet_titles=["predictions"],
    )
    storage = GoogleSheetsStorage(
        spreadsheet_id="sheet-id",
        worksheet="predictions",
        service_account_json="{}",
    )
    storage._service = fake_service
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    storage.save(PredictionRecord(summary=sample_summary, scores=scores, line_sent=False))

    # 旧ヘッダ（新構成の prefix）は raise せず、ヘッダ行が新構成へ更新される
    assert any(update["body"]["values"] == [CSV_COLUMNS] for update in fake_service.updates)
    assert fake_service.appends[0]["body"]["values"][0][0:3] == ["2026-06-01", "13:00", "逗子海岸"]


def test_google_sheets_storage_rejects_unrelated_header(sample_summary):
    fake_service = FakeSheetsService(
        get_values=[["date", "unexpected_column"]],
        sheet_titles=["predictions"],
    )
    storage = GoogleSheetsStorage(
        spreadsheet_id="sheet-id",
        worksheet="predictions",
        service_account_json="{}",
    )
    storage._service = fake_service
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    with pytest.raises(ConfigError, match="Google Sheets header"):
        storage.save(PredictionRecord(summary=sample_summary, scores=scores, line_sent=False))


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

    assert fake_service.updates[-1]["range"] == "'predictions'!A2:AK2"
    assert fake_service.updates[-1]["body"]["values"][0][CSV_COLUMNS.index("line_sent")] is True
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

    assert fake_service.updates[-1]["range"] == "'predictions'!A3:AK3"
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


def test_google_sheets_storage_detects_sent_record():
    sent_row = [""] * len(CSV_COLUMNS)
    sent_row[0:3] = ["2026-06-01", "17:00", "逗子海岸"]
    sent_row[CSV_COLUMNS.index("line_sent")] = "TRUE"
    fake_service = FakeSheetsService(
        get_values=[CSV_COLUMNS, sent_row],
        sheet_titles=["predictions"],
    )
    storage = GoogleSheetsStorage(
        spreadsheet_id="sheet-id",
        worksheet="predictions",
        service_account_json="{}",
    )
    storage._service = fake_service

    assert (
        storage.has_sent(
            date="2026-06-01",
            run_time="17:00",
            location_name="逗子海岸",
        )
        is True
    )
    assert fake_service.last_get["range"] == "'predictions'!A:AK"


def test_google_sheets_storage_ignores_unsent_record():
    unsent_row = [""] * len(CSV_COLUMNS)
    unsent_row[0:3] = ["2026-06-01", "17:00", "逗子海岸"]
    unsent_row[CSV_COLUMNS.index("line_sent")] = "FALSE"
    fake_service = FakeSheetsService(
        get_values=[CSV_COLUMNS, unsent_row],
        sheet_titles=["predictions"],
    )
    storage = GoogleSheetsStorage(
        spreadsheet_id="sheet-id",
        worksheet="predictions",
        service_account_json="{}",
    )
    storage._service = fake_service

    assert (
        storage.has_sent(
            date="2026-06-01",
            run_time="17:00",
            location_name="逗子海岸",
        )
        is False
    )


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
    assert fake_service.updates[-1]["range"] == "'June''s predictions'!A2:AK2"


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
        "line_channel_secret": "",
        "line_bot_user_id": "",
        "storage_backend": "csv",
        "csv_path": "logs/chill_predictions.csv",
        "google_sheets_spreadsheet_id": "",
        "google_sheets_worksheet": "predictions",
        "google_service_account_json": "",
        "dry_run": False,
        "log_level": "INFO",
        "allow_missing_hourly_fields": frozenset(),
        "live_camera_image_base_url": "",
        "live_camera_image_url": "",
        "live_camera_preview_image_url": "",
        "live_camera_url": "",
        "live_camera_video_id": "",
        "live_camera_public_dir": "public",
        "live_camera_capture_timeout_seconds": 20,
        "webhook_host": "127.0.0.1",
        "webhook_port": 8080,
    }
    values.update(overrides)
    return Settings(**values)
