from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from zushi_chill.weather_client import HOURLY_FIELDS


class ConfigError(ValueError):
    """Raised when required runtime configuration is missing or invalid."""


LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def _bool_from_env(value: str | None, *, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ConfigError("DRY_RUN must be one of: 1, true, yes, on, 0, false, no, off")


@dataclass(frozen=True)
class Settings:
    location_name: str
    latitude: float
    longitude: float
    timezone: str
    line_channel_access_token: str
    line_target_id: str
    google_form_url: str
    storage_backend: str
    csv_path: str
    google_sheets_spreadsheet_id: str
    google_sheets_worksheet: str
    google_service_account_json: str
    dry_run: bool
    log_level: str
    allow_missing_hourly_fields: frozenset[str]

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        latitude = _env("LATITUDE", "35.2956")
        longitude = _env("LONGITUDE", "139.5736")
        try:
            lat = float(latitude)
            lon = float(longitude)
        except ValueError as exc:
            raise ConfigError("LATITUDE and LONGITUDE must be numeric") from exc
        if not -90 <= lat <= 90:
            raise ConfigError("LATITUDE must be between -90 and 90")
        if not -180 <= lon <= 180:
            raise ConfigError("LONGITUDE must be between -180 and 180")

        storage_backend = _env("STORAGE_BACKEND", "csv").strip().lower()
        if storage_backend not in {"csv", "google_sheets"}:
            raise ConfigError("STORAGE_BACKEND must be 'csv' or 'google_sheets'")
        google_sheets_worksheet = _env("GOOGLE_SHEETS_WORKSHEET", "predictions").strip()
        if any(char in google_sheets_worksheet for char in "[]:*?/\\"):
            raise ConfigError("GOOGLE_SHEETS_WORKSHEET contains invalid characters")
        if len(google_sheets_worksheet) > 100:
            raise ConfigError("GOOGLE_SHEETS_WORKSHEET must be 100 characters or fewer")
        timezone = _env("TIMEZONE", "Asia/Tokyo").strip()
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError(f"TIMEZONE is not valid: {timezone}") from exc
        allow_missing_hourly_fields = _csv_set(_env("ALLOW_MISSING_HOURLY_FIELDS", ""))
        unknown_missing_fields = allow_missing_hourly_fields - frozenset(HOURLY_FIELDS)
        if unknown_missing_fields:
            raise ConfigError(
                "ALLOW_MISSING_HOURLY_FIELDS contains unknown fields: "
                + ", ".join(sorted(unknown_missing_fields))
            )
        log_level = _env("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in LOG_LEVELS:
            raise ConfigError(
                "LOG_LEVEL must be one of: " + ", ".join(sorted(LOG_LEVELS))
            )

        return cls(
            location_name=_env("LOCATION_NAME", "逗子海岸"),
            latitude=lat,
            longitude=lon,
            timezone=timezone,
            line_channel_access_token=_env("LINE_CHANNEL_ACCESS_TOKEN", ""),
            line_target_id=_env("LINE_TARGET_ID", ""),
            google_form_url=_env("GOOGLE_FORM_URL", ""),
            storage_backend=storage_backend,
            csv_path=_env("CSV_PATH", "logs/chill_predictions.csv"),
            google_sheets_spreadsheet_id=_env("GOOGLE_SHEETS_SPREADSHEET_ID", ""),
            google_sheets_worksheet=google_sheets_worksheet,
            google_service_account_json=_env("GOOGLE_SERVICE_ACCOUNT_JSON", ""),
            dry_run=_bool_from_env(_env("DRY_RUN", "")),
            log_level=log_level,
            allow_missing_hourly_fields=allow_missing_hourly_fields,
        )

    def require_line(self) -> None:
        if not self.line_channel_access_token or not self.line_target_id:
            raise ConfigError("LINE_CHANNEL_ACCESS_TOKEN and LINE_TARGET_ID are required")


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        existing_value = os.environ.get(key)
        if existing_value is not None and existing_value.strip():
            continue
        os.environ[key] = _strip_quotes(value.strip())


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _csv_set(value: str) -> frozenset[str]:
    return frozenset(item.strip() for item in value.split(",") if item.strip())
