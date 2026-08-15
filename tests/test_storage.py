from __future__ import annotations

import csv
from dataclasses import replace
from datetime import timedelta

import pytest

from zushi_chill.config import ConfigError, Settings
from zushi_chill.models import (
    JmaPrecipitationForecast,
    PredictionRecord,
    ScoreResult,
    SunsetCloud,
    VisionResult,
)
from zushi_chill.storage import CSV_COLUMNS, CsvStorage, GoogleSheetsStorage, storage_from_settings


def test_csv_storage_writes_prediction_record(tmp_path, sample_summary):
    path = tmp_path / "predictions.csv"
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    CsvStorage(path).save(
        PredictionRecord(
            summary=sample_summary,
            scores=scores,
            line_sent=False,
            sunset_cloud=SunsetCloud.from_summary(sample_summary),
        )
    )

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-06-01"
    assert rows[0]["chill_score"] == "88"
    assert rows[0]["line_sent"] == "False"
    assert rows[0]["precipitation_probability_before_sunset"] == "10.0"
    assert rows[0]["precipitation_before_sunset"] == "0.0"
    assert rows[0]["weather_code_before_sunset"] == "1"
    assert rows[0]["visibility_before_sunset"] == "18000.0"
    assert rows[0]["precipitation_probability_at_sunset"] == "10.0"
    assert rows[0]["precipitation_at_sunset"] == "0.0"
    assert rows[0]["weather_code_at_sunset"] == "1"
    assert rows[0]["visibility_at_sunset"] == "18000.0"
    assert rows[0]["sunset_snapshot_time"].endswith("19:00+09:00")
    assert rows[0]["temperature_2m_at_sunset"] == "22.0"
    assert rows[0]["relative_humidity_2m_at_sunset"] == "72.0"
    assert rows[0]["visibility_at_sunset_snapshot"] == "18000.0"
    assert rows[0]["wind_speed_10m_at_sunset"] == "4.0"
    assert rows[0]["wind_direction_10m_at_sunset"] == "190.0"
    assert rows[0]["sunset_cloud_cover_low_at_sunset"] == "25.0"
    assert rows[0]["sunset_cloud_cover_mid_at_sunset"] == "40.0"
    assert rows[0]["sunset_cloud_cover_high_at_sunset"] == "55.0"
    assert rows[0]["chill_weather_basis"] == "target_window"
    assert rows[0]["run_time_snapshot_time"].endswith("13:00+09:00")
    assert rows[0]["temperature_2m_at_run_time"] == "26.0"
    assert rows[0]["apparent_temperature_at_run_time"] == "26.0"
    assert rows[0]["relative_humidity_2m_at_run_time"] == "60.0"
    assert rows[0]["wind_gusts_10m_at_run_time"] == "6.0"


def test_csv_columns_include_vision_fields_after_error_message():
    for column in (
        "vision_sunset_score",
        "vision_sky_condition",
        "vision_comment",
        "vision_model",
        "vision_evaluation_phase",
        "vision_sun_disk_visibility",
        "vision_sunset_color_score",
        "vision_afterglow_score",
    ):
        assert column in CSV_COLUMNS
        assert CSV_COLUMNS.index(column) > CSV_COLUMNS.index("error_message")


def test_csv_columns_append_sunset_diagnostics_jma_and_display_snapshot():
    diagnostics_start = CSV_COLUMNS.index("precipitation_probability_before_sunset")
    assert CSV_COLUMNS[diagnostics_start : diagnostics_start + 22] == [
        "precipitation_probability_before_sunset",
        "precipitation_before_sunset",
        "weather_code_before_sunset",
        "visibility_before_sunset",
        "precipitation_probability_at_sunset",
        "precipitation_at_sunset",
        "weather_code_at_sunset",
        "visibility_at_sunset",
        "jma_precipitation_probability",
        "jma_precipitation_period_start",
        "jma_precipitation_period_end",
        "jma_precipitation_area",
        "jma_report_time",
        "sunset_snapshot_time",
        "temperature_2m_at_sunset",
        "relative_humidity_2m_at_sunset",
        "visibility_at_sunset_snapshot",
        "wind_speed_10m_at_sunset",
        "wind_direction_10m_at_sunset",
        "sunset_cloud_cover_low_at_sunset",
        "sunset_cloud_cover_mid_at_sunset",
        "sunset_cloud_cover_high_at_sunset",
    ]
    observation_start = CSV_COLUMNS.index("observation_id")
    assert CSV_COLUMNS[observation_start : observation_start + 6] == [
        "observation_id",
        "observation_phase",
        "scheduled_at",
        "captured_at",
        "capture_delay_seconds",
        "observation_data_quality",
    ]
    assert CSV_COLUMNS[observation_start + 6 :] == [
        "chill_weather_basis",
        "run_time_snapshot_time",
        "temperature_2m_at_run_time",
        "apparent_temperature_at_run_time",
        "relative_humidity_2m_at_run_time",
        "precipitation_probability_at_run_time",
        "precipitation_at_run_time",
        "weather_code_at_run_time",
        "cloud_cover_at_run_time",
        "cloud_cover_low_at_run_time",
        "cloud_cover_mid_at_run_time",
        "cloud_cover_high_at_run_time",
        "visibility_at_run_time",
        "wind_speed_10m_at_run_time",
        "wind_direction_10m_at_run_time",
        "wind_gusts_10m_at_run_time",
    ]
    assert len(CSV_COLUMNS) == 90


def test_csv_storage_writes_jma_precipitation_forecast(tmp_path, sample_summary):
    path = tmp_path / "predictions.csv"
    scores = ScoreResult(sunset_score=70, sunset_label="A", chill_score=75, chill_label="A")
    period_start = sample_summary.sunset_time.replace(hour=18, minute=0)
    jma = JmaPrecipitationForecast(
        probability=20,
        period_start=period_start,
        period_end=period_start + timedelta(hours=6),
        area_name="東部",
        report_time=period_start.replace(hour=17),
    )

    CsvStorage(path).save(
        PredictionRecord(
            summary=sample_summary,
            scores=scores,
            line_sent=False,
            jma_precipitation=jma,
        )
    )

    row = next(csv.DictReader(path.open(encoding="utf-8")))
    assert row["jma_precipitation_probability"] == "20"
    assert row["jma_precipitation_period_start"].endswith("18:00+09:00")
    assert row["jma_precipitation_period_end"].endswith("00:00+09:00")
    assert row["jma_precipitation_area"] == "東部"
    assert row["jma_report_time"].endswith("17:00+09:00")


def test_csv_storage_writes_vision_fields_when_present(tmp_path, sample_summary):
    path = tmp_path / "predictions.csv"
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")
    vision = VisionResult(
        sunset_score=82,
        sky_condition="golden_hour",
        comment="美しい夕焼け",
        model="gemini-2.5-flash",
        evaluation_phase="sunset",
        sun_disk_visibility=70,
        sunset_color_score=82,
    )

    CsvStorage(path).save(
        PredictionRecord(summary=sample_summary, scores=scores, line_sent=True, vision=vision)
    )

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows[0]["vision_sunset_score"] == "82"
    assert rows[0]["vision_sky_condition"] == "golden_hour"
    assert rows[0]["vision_comment"] == "美しい夕焼け"
    assert rows[0]["vision_model"] == "gemini-2.5-flash"
    assert rows[0]["vision_evaluation_phase"] == "sunset"
    assert rows[0]["vision_sun_disk_visibility"] == "70"
    assert rows[0]["vision_sunset_color_score"] == "82"
    assert rows[0]["vision_afterglow_score"] == ""


def test_csv_storage_writes_empty_vision_fields_when_absent(tmp_path, sample_summary):
    path = tmp_path / "predictions.csv"
    scores = ScoreResult(sunset_score=90, sunset_label="S", chill_score=88, chill_label="S")

    CsvStorage(path).save(PredictionRecord(summary=sample_summary, scores=scores, line_sent=False))

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows[0]["vision_sunset_score"] == ""
    assert rows[0]["vision_model"] == ""
    assert rows[0]["vision_evaluation_phase"] == ""
    assert rows[0]["vision_sun_disk_visibility"] == ""
    assert rows[0]["vision_sunset_color_score"] == ""
    assert rows[0]["vision_afterglow_score"] == ""


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


def test_google_sheets_execute_retries_transient_timeout(monkeypatch):
    storage = GoogleSheetsStorage(
        spreadsheet_id="sheet",
        worksheet="predictions",
        service_account_json="{}",
        request_retries=3,
    )
    attempts = []

    class Request:
        def execute(self):
            attempts.append(True)
            if len(attempts) < 3:
                raise TimeoutError("temporary timeout")
            return {"ok": True}

    monkeypatch.setattr("zushi_chill.storage.time.sleep", lambda _: None)

    assert storage._execute(Request()) == {"ok": True}
    assert attempts == [True, True, True]


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
    storage.replace_latest(PredictionRecord(summary=afternoon_summary, scores=sent, line_sent=True))

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


def test_csv_storage_finds_sent_sunset_prediction(tmp_path, sample_summary):
    path = tmp_path / "predictions.csv"
    storage = CsvStorage(path)
    afternoon_summary = replace(sample_summary, run_time="17:00")
    scores = ScoreResult(sunset_score=40, sunset_label="C", chill_score=70, chill_label="A")

    storage.save(
        PredictionRecord(
            summary=afternoon_summary,
            scores=scores,
            line_sent=True,
            final_sunset_score=68,
            final_sunset_label="B",
        )
    )

    prediction = storage.find_sent_sunset_prediction(
        date="2026-06-01",
        run_time="17:00",
        location_name="逗子海岸",
    )

    assert prediction is not None
    assert prediction.run_time == "17:00"
    assert prediction.score == 68
    assert prediction.label == "B"


def test_csv_storage_ignores_unsent_sunset_prediction(tmp_path, sample_summary):
    path = tmp_path / "predictions.csv"
    storage = CsvStorage(path)
    afternoon_summary = replace(sample_summary, run_time="17:00")
    scores = ScoreResult(sunset_score=40, sunset_label="C", chill_score=70, chill_label="A")
    storage.save(PredictionRecord(summary=afternoon_summary, scores=scores, line_sent=False))

    assert (
        storage.find_sent_sunset_prediction(
            date="2026-06-01",
            run_time="17:00",
            location_name="逗子海岸",
        )
        is None
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


def test_google_sheets_storage_finds_sent_sunset_prediction():
    row = [""] * len(CSV_COLUMNS)
    values = {
        "date": "2026-06-01",
        "run_time": "17:00",
        "location_name": "逗子海岸",
        "sunset_score": 40,
        "sunset_label": "C",
        "line_sent": True,
        "final_sunset_score": 68,
        "final_sunset_label": "B",
    }
    for column, value in values.items():
        row[CSV_COLUMNS.index(column)] = value
    fake_service = FakeSheetsService(
        get_values=[CSV_COLUMNS, row],
        sheet_titles=["predictions"],
    )
    storage = GoogleSheetsStorage(
        spreadsheet_id="sheet-id",
        worksheet="predictions",
        service_account_json="{}",
    )
    storage._service = fake_service

    prediction = storage.find_sent_sunset_prediction(
        date="2026-06-01",
        run_time="17:00",
        location_name="逗子海岸",
    )

    assert prediction is not None
    assert prediction.score == 68
    assert prediction.label == "B"
    assert fake_service.last_get["range"] == "'predictions'!A:AM"


@pytest.mark.parametrize("legacy_size", [46, 59])
def test_google_sheets_storage_migrates_legacy_header(sample_summary, legacy_size):
    legacy_header = CSV_COLUMNS[:legacy_size]
    fake_service = FakeSheetsService(
        get_values=[legacy_header, ["2026-06-01", "13:00", "逗子海岸"]],
        sheet_titles=["predictions"],
        column_count=legacy_size,
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
    assert any(
        update["body"]
        == {
            "requests": [
                {
                    "appendDimension": {
                        "sheetId": 0,
                        "dimension": "COLUMNS",
                        "length": len(CSV_COLUMNS) - len(legacy_header),
                    }
                }
            ]
        }
        for update in fake_service.batch_updates
    )


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

    assert fake_service.updates[-1]["range"] == "'predictions'!A2:CL2"
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

    assert fake_service.updates[-1]["range"] == "'predictions'!A3:CL3"
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
    assert fake_service.last_get["range"] == "'predictions'!A:CL"


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
    assert fake_service.updates[-1]["range"] == "'June''s predictions'!A2:CL2"


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
    def __init__(self, *, get_values, sheet_titles, column_count=None):
        self.get_values = get_values
        self.sheet_titles = sheet_titles
        self.column_count = column_count
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
            sheets = []
            for index, title in enumerate(self.sheet_titles):
                properties = {"title": title}
                if self.column_count is not None:
                    properties.update(
                        {
                            "sheetId": index,
                            "gridProperties": {"columnCount": self.column_count},
                        }
                    )
                sheets.append({"properties": properties})
            return FakeExecute({"sheets": sheets})
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
