from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Protocol

from zushi_chill.config import ConfigError, Settings
from zushi_chill.models import PredictionRecord

CSV_COLUMNS = [
    "date",
    "run_time",
    "location_name",
    "latitude",
    "longitude",
    "sunset_time",
    "target_window_start",
    "target_window_end",
    "chill_score",
    "chill_label",
    "sunset_score",
    "sunset_label",
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation_probability",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "visibility",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "comment",
    "line_sent",
    "error_message",
]


class Storage(Protocol):
    def save(self, record: PredictionRecord) -> None:
        pass

    def replace_latest(self, record: PredictionRecord) -> None:
        pass


class CsvStorage:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def save(self, record: PredictionRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        has_header = self._has_expected_header()
        with self.path.open("a", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            if not has_header:
                writer.writeheader()
            writer.writerow(record.to_row())

    def replace_latest(self, record: PredictionRecord) -> None:
        if not self.path.exists():
            self.save(record)
            return
        self._has_expected_header()

        with self.path.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))

        replacement = record.to_row()
        for index in range(len(rows) - 1, -1, -1):
            row = rows[index]
            if (
                row.get("date") == str(replacement["date"])
                and row.get("run_time") == str(replacement["run_time"])
                and row.get("location_name") == str(replacement["location_name"])
            ):
                rows[index] = {column: replacement.get(column, "") for column in CSV_COLUMNS}
                break
        else:
            rows.append({column: replacement.get(column, "") for column in CSV_COLUMNS})

        with self.path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def _has_expected_header(self) -> bool:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return False
        with self.path.open(encoding="utf-8", newline="") as file:
            reader = csv.reader(file)
            header = next(reader, [])
        if header != CSV_COLUMNS:
            raise ConfigError("CSV header does not match expected prediction log columns")
        return True


class GoogleSheetsStorage:
    def __init__(self, *, spreadsheet_id: str, worksheet: str, service_account_json: str):
        self.spreadsheet_id = spreadsheet_id
        self.worksheet = worksheet
        self.service_account_json = service_account_json
        self._service = None

    def save(self, record: PredictionRecord) -> None:
        self._ensure_header()
        self._append_row(record)

    def replace_latest(self, record: PredictionRecord) -> None:
        self._ensure_header()
        existing_row = self._find_existing_row(record)
        if existing_row is None:
            self._append_row(record)
            return

        end_column = _column_letter(len(CSV_COLUMNS))
        range_name = _sheet_range(self.worksheet, f"A{existing_row}:{end_column}{existing_row}")
        self._service_client().spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            body={"values": [_record_values(record)]},
        ).execute()

    def _service_client(self):
        if self._service is not None:
            return self._service
        if not self.spreadsheet_id:
            raise ConfigError("GOOGLE_SHEETS_SPREADSHEET_ID is required for Google Sheets storage")
        if not self.service_account_json:
            raise ConfigError("GOOGLE_SERVICE_ACCOUNT_JSON is required for Google Sheets storage")

        try:
            service_account_info = json.loads(self.service_account_json)
        except json.JSONDecodeError as exc:
            raise ConfigError("GOOGLE_SERVICE_ACCOUNT_JSON must be a JSON object string") from exc
        if not isinstance(service_account_info, dict):
            raise ConfigError("GOOGLE_SERVICE_ACCOUNT_JSON must be a JSON object string")

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise ConfigError(
                "Google Sheets dependencies are missing. Install with `pip install -e .`."
            ) from exc

        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        self._service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        return self._service

    def _ensure_header(self) -> None:
        service = self._service_client()
        self._ensure_worksheet()
        range_name = _sheet_range(self.worksheet, f"A1:{_column_letter(len(CSV_COLUMNS))}1")
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=range_name)
            .execute()
        )
        values = result.get("values", [])
        if values and values[0] == CSV_COLUMNS:
            return
        if values:
            raise ConfigError(
                "Google Sheets header does not match expected prediction log columns"
            )
        service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            body={"values": [CSV_COLUMNS]},
        ).execute()

    def _ensure_worksheet(self) -> None:
        service = self._service_client()
        result = service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        sheets = result.get("sheets", [])
        titles = {
            sheet.get("properties", {}).get("title")
            for sheet in sheets
            if isinstance(sheet, dict)
        }
        if self.worksheet in titles:
            return

        service.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": self.worksheet,
                            }
                        }
                    }
                ]
            },
        ).execute()

    def _append_row(self, record: PredictionRecord) -> None:
        self._service_client().spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=_sheet_range(self.worksheet, f"A:{_column_letter(len(CSV_COLUMNS))}"),
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [_record_values(record)]},
        ).execute()

    def _find_existing_row(self, record: PredictionRecord) -> int | None:
        result = (
            self._service_client()
            .spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=_sheet_range(self.worksheet, "A:C"),
            )
            .execute()
        )
        values = result.get("values", [])
        replacement = record.to_row()
        for index in range(len(values) - 1, 0, -1):
            row = values[index]
            if len(row) >= 3 and row[:3] == [
                str(replacement["date"]),
                str(replacement["run_time"]),
                str(replacement["location_name"]),
            ]:
                return index + 1
        return None


def storage_from_settings(settings: Settings) -> Storage:
    if settings.storage_backend == "csv":
        return CsvStorage(settings.csv_path)
    return GoogleSheetsStorage(
        spreadsheet_id=settings.google_sheets_spreadsheet_id,
        worksheet=settings.google_sheets_worksheet,
        service_account_json=settings.google_service_account_json,
    )


def _record_values(record: PredictionRecord) -> list[str | int | float | bool]:
    row = record.to_row()
    return [row.get(column, "") for column in CSV_COLUMNS]


def _column_letter(index: int) -> str:
    if index < 1:
        raise ValueError("index must be positive")
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _sheet_range(worksheet: str, cell_range: str) -> str:
    escaped = worksheet.replace("'", "''")
    return f"'{escaped}'!{cell_range}"
