from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Protocol

from zushi_chill.config import ConfigError, Settings
from zushi_chill.models import PredictionRecord, SunsetPredictionReference

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
    "vision_sunset_score",
    "vision_sky_condition",
    "vision_comment",
    "vision_model",
    "sunset_cloud_cover",
    "sunset_cloud_cover_low",
    "sunset_cloud_cover_mid",
    "sunset_cloud_cover_high",
    "final_sunset_score",
    "final_sunset_label",
    "sunsethue_quality",
    "sunsethue_cloud_cover",
    "sunsethue_quality_text",
    "vision_evaluation_phase",
    "vision_sun_disk_visibility",
    "vision_sunset_color_score",
    "vision_afterglow_score",
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
    "observation_id",
    "observation_phase",
    "scheduled_at",
    "captured_at",
    "capture_delay_seconds",
    "observation_data_quality",
    # 74列の旧スキーマをprefixとして維持し、日没後Chill指数の再現入力を末尾追加する。
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


class Storage(Protocol):
    def save(self, record: PredictionRecord) -> None:
        pass

    def replace_latest(self, record: PredictionRecord) -> None:
        pass

    def has_sent(
        self,
        *,
        date: str,
        run_time: str,
        location_name: str,
        observation_id: str = "",
    ) -> bool:
        pass

    def find_sent_sunset_prediction(
        self,
        *,
        date: str,
        run_time: str,
        location_name: str,
    ) -> SunsetPredictionReference | None:
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
            if _same_record(row, replacement):
                rows[index] = {column: replacement.get(column, "") for column in CSV_COLUMNS}
                break
        else:
            rows.append({column: replacement.get(column, "") for column in CSV_COLUMNS})

        with self.path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def has_sent(
        self,
        *,
        date: str,
        run_time: str,
        location_name: str,
        observation_id: str = "",
    ) -> bool:
        if not self.path.exists():
            return False
        self._has_expected_header()
        with self.path.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        for row in reversed(rows):
            if observation_id and row.get("observation_id") == observation_id:
                return _is_truthy(row.get("line_sent", ""))
            if (
                not observation_id
                and
                row.get("date") == date
                and row.get("run_time") == run_time
                and row.get("location_name") == location_name
            ):
                return _is_truthy(row.get("line_sent", ""))
        return False

    def find_sent_sunset_prediction(
        self,
        *,
        date: str,
        run_time: str,
        location_name: str,
    ) -> SunsetPredictionReference | None:
        if not self.path.exists():
            return None
        self._has_expected_header()
        with self.path.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        for row in reversed(rows):
            if (
                row.get("date") == date
                and row.get("run_time") == run_time
                and row.get("location_name") == location_name
                and _is_truthy(row.get("line_sent", ""))
            ):
                prediction = _prediction_reference_from_mapping(row)
                if prediction is not None:
                    return prediction
        return None

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

    def has_sent(
        self,
        *,
        date: str,
        run_time: str,
        location_name: str,
        observation_id: str = "",
    ) -> bool:
        self._ensure_header()
        result = (
            self._service_client()
            .spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=_sheet_range(self.worksheet, f"A:{_column_letter(len(CSV_COLUMNS))}"),
            )
            .execute()
        )
        values = result.get("values", [])
        line_sent_index = CSV_COLUMNS.index("line_sent")
        observation_id_index = CSV_COLUMNS.index("observation_id")
        for row in reversed(values[1:]):
            if (
                observation_id
                and len(row) > observation_id_index
                and row[observation_id_index] == observation_id
            ):
                return len(row) > line_sent_index and _is_truthy(str(row[line_sent_index]))
            if (
                not observation_id
                and len(row) >= 3
                and row[:3] == [date, run_time, location_name]
            ):
                return len(row) > line_sent_index and _is_truthy(
                    str(row[line_sent_index])
                )
        return False

    def find_sent_sunset_prediction(
        self,
        *,
        date: str,
        run_time: str,
        location_name: str,
    ) -> SunsetPredictionReference | None:
        self._ensure_header()
        last_index = max(
            CSV_COLUMNS.index("line_sent"),
            CSV_COLUMNS.index("final_sunset_label"),
        )
        result = (
            self._service_client()
            .spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=_sheet_range(
                    self.worksheet,
                    f"A:{_column_letter(last_index + 1)}",
                ),
            )
            .execute()
        )
        values = result.get("values", [])
        for row in reversed(values[1:]):
            if (
                _sheet_value(row, "date") == date
                and _sheet_value(row, "run_time") == run_time
                and _sheet_value(row, "location_name") == location_name
                and _is_truthy(_sheet_value(row, "line_sent"))
            ):
                prediction = _prediction_reference_from_mapping(
                    {column: _sheet_value(row, column) for column in CSV_COLUMNS}
                )
                if prediction is not None:
                    return prediction
        return None

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
        self._ensure_column_capacity(len(CSV_COLUMNS))
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
        if values and values[0] != CSV_COLUMNS[: len(values[0])]:
            raise ConfigError(
                "Google Sheets header does not match expected prediction log columns"
            )
        # ヘッダが無い、または旧カラム（新構成の prefix）の場合は、ヘッダ行のみ新構成へ更新して
        # 移行する。既存データ行は末尾が空欄のまま保持され、既存カラムの位置も変わらない。
        service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            body={"values": [CSV_COLUMNS]},
        ).execute()

    def _ensure_column_capacity(self, required_columns: int) -> None:
        service = self._service_client()
        result = service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        for sheet in result.get("sheets", []):
            properties = sheet.get("properties", {})
            if properties.get("title") != self.worksheet:
                continue
            sheet_id = properties.get("sheetId")
            column_count = properties.get("gridProperties", {}).get("columnCount")
            if not isinstance(sheet_id, int) or not isinstance(column_count, int):
                return
            if column_count >= required_columns:
                return
            service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "requests": [
                        {
                            "appendDimension": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "length": required_columns - column_count,
                            }
                        }
                    ]
                },
            ).execute()
            return

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
        replacement = record.to_row()
        observation_id = str(replacement.get("observation_id", ""))
        columns = (
            f"A:{_column_letter(len(CSV_COLUMNS))}"
            if observation_id
            else "A:C"
        )
        result = (
            self._service_client()
            .spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=_sheet_range(self.worksheet, columns),
            )
            .execute()
        )
        values = result.get("values", [])
        observation_id_index = CSV_COLUMNS.index("observation_id")
        for index in range(len(values) - 1, 0, -1):
            row = values[index]
            if (
                observation_id
                and len(row) > observation_id_index
                and row[observation_id_index] == observation_id
            ):
                return index + 1
            if len(row) >= 3 and row[:3] == [
                str(replacement["date"]),
                str(replacement["run_time"]),
                str(replacement["location_name"]),
            ] and not observation_id:
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


def _same_record(
    row: dict[str, str],
    replacement: dict[str, str | int | float | bool],
) -> bool:
    observation_id = str(replacement.get("observation_id", ""))
    if observation_id:
        return row.get("observation_id") == observation_id
    return (
        row.get("date") == str(replacement["date"])
        and row.get("run_time") == str(replacement["run_time"])
        and row.get("location_name") == str(replacement["location_name"])
    )


def _prediction_reference_from_mapping(
    row: dict[str, str],
) -> SunsetPredictionReference | None:
    score_value = row.get("final_sunset_score") or row.get("sunset_score")
    label = row.get("final_sunset_label") or row.get("sunset_label")
    if not score_value or not label:
        return None
    try:
        score = int(float(score_value))
    except ValueError:
        return None
    return SunsetPredictionReference(
        run_time=row.get("run_time", ""),
        score=score,
        label=label,
    )


def _sheet_value(row: list, column: str) -> str:
    index = CSV_COLUMNS.index(column)
    return str(row[index]) if len(row) > index else ""


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


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes", "y"}
