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
    line_channel_secret: str
    line_bot_user_id: str
    storage_backend: str
    csv_path: str
    google_sheets_spreadsheet_id: str
    google_sheets_worksheet: str
    google_service_account_json: str
    dry_run: bool
    log_level: str
    allow_missing_hourly_fields: frozenset[str]
    live_camera_image_base_url: str = ""
    live_camera_image_url: str = ""
    live_camera_preview_image_url: str = ""
    live_camera_url: str = ""
    live_camera_video_id: str = ""
    live_camera_public_dir: str = "public"
    live_camera_capture_timeout_seconds: int = 20
    webhook_host: str = "127.0.0.1"
    webhook_port: int = 8080
    vision_enabled: bool = False
    vision_api_key: str = ""
    vision_model: str = "gemini-2.5-flash"
    vision_timeout_seconds: int = 30
    vision_target_hours: frozenset[int] = frozenset({16, 17, 18, 19})
    sunset_cloud_offset_km: float = 40.0
    sunset_vision_blend_weight: float = 0.8
    sunsethue_enabled: bool = False
    sunsethue_api_key: str = ""
    sunsethue_timeout_seconds: int = 20

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
        live_camera_capture_timeout_seconds = _positive_int_from_env(
            "LIVE_CAMERA_CAPTURE_TIMEOUT_SECONDS",
            default=20,
        )
        webhook_port = _positive_int_from_env("WEBHOOK_PORT", default=8080)
        if webhook_port > 65535:
            raise ConfigError("WEBHOOK_PORT must be between 1 and 65535")
        vision_timeout_seconds = _positive_int_from_env("VISION_TIMEOUT_SECONDS", default=30)
        vision_target_hours = _hours_from_env(
            "VISION_TARGET_HOURS",
            legacy_name="VISION_TARGET_HOUR",
            default=frozenset({16, 17, 18, 19}),
        )
        sunset_cloud_offset_km = _non_negative_float_from_env(
            "SUNSET_CLOUD_OFFSET_KM", default=40.0
        )
        sunset_vision_blend_weight = _unit_interval_float_from_env(
            "SUNSET_VISION_BLEND_WEIGHT", default=0.8
        )
        sunsethue_timeout_seconds = _positive_int_from_env("SUNSETHUE_TIMEOUT_SECONDS", default=20)

        return cls(
            location_name=_env("LOCATION_NAME", "逗子海岸"),
            latitude=lat,
            longitude=lon,
            timezone=timezone,
            line_channel_access_token=_env("LINE_CHANNEL_ACCESS_TOKEN", ""),
            line_target_id=_env("LINE_TARGET_ID", ""),
            line_channel_secret=_env("LINE_CHANNEL_SECRET", ""),
            line_bot_user_id=_env("LINE_BOT_USER_ID", ""),
            storage_backend=storage_backend,
            csv_path=_env("CSV_PATH", "logs/chill_predictions.csv"),
            google_sheets_spreadsheet_id=_env("GOOGLE_SHEETS_SPREADSHEET_ID", ""),
            google_sheets_worksheet=google_sheets_worksheet,
            google_service_account_json=_env("GOOGLE_SERVICE_ACCOUNT_JSON", ""),
            dry_run=_bool_from_env(_env("DRY_RUN", "")),
            log_level=log_level,
            allow_missing_hourly_fields=allow_missing_hourly_fields,
            live_camera_image_base_url=_env("LIVE_CAMERA_IMAGE_BASE_URL", ""),
            live_camera_image_url=_env("LIVE_CAMERA_IMAGE_URL", ""),
            live_camera_preview_image_url=_env("LIVE_CAMERA_PREVIEW_IMAGE_URL", ""),
            live_camera_url=_env("LIVE_CAMERA_URL", ""),
            live_camera_video_id=_env("LIVE_CAMERA_VIDEO_ID", ""),
            live_camera_public_dir=_env("LIVE_CAMERA_PUBLIC_DIR", "public"),
            live_camera_capture_timeout_seconds=live_camera_capture_timeout_seconds,
            webhook_host=_env("WEBHOOK_HOST", "127.0.0.1"),
            webhook_port=webhook_port,
            vision_enabled=_bool_from_env(_env("VISION_ENABLED", "")),
            vision_api_key=_env("VISION_API_KEY", ""),
            vision_model=_env("VISION_MODEL", "gemini-2.5-flash"),
            vision_timeout_seconds=vision_timeout_seconds,
            vision_target_hours=vision_target_hours,
            sunset_cloud_offset_km=sunset_cloud_offset_km,
            sunset_vision_blend_weight=sunset_vision_blend_weight,
            sunsethue_enabled=_bool_from_env(_env("SUNSETHUE_ENABLED", "")),
            sunsethue_api_key=_env("SUNSETHUE_API_KEY", ""),
            sunsethue_timeout_seconds=sunsethue_timeout_seconds,
        )

    def require_line(self) -> None:
        if not self.line_channel_access_token or not self.line_target_id:
            raise ConfigError("LINE_CHANNEL_ACCESS_TOKEN and LINE_TARGET_ID are required")

    def require_webhook(self) -> None:
        if not self.line_channel_access_token or not self.line_channel_secret:
            raise ConfigError("LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET are required")
        if not self.live_camera_url and not self.live_camera_video_id:
            raise ConfigError("LIVE_CAMERA_URL or LIVE_CAMERA_VIDEO_ID is required")
        if not self.live_camera_image_base_url:
            raise ConfigError("LIVE_CAMERA_IMAGE_BASE_URL is required")


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


def _hours_from_env(
    name: str, *, legacy_name: str, default: frozenset[int]
) -> frozenset[int]:
    raw = _env(name, "") or _env(legacy_name, "")
    if not raw:
        return default
    hours: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            hour = int(item)
        except ValueError as exc:
            raise ConfigError(
                f"{name} must be comma-separated hours between 0 and 23"
            ) from exc
        if not 0 <= hour <= 23:
            raise ConfigError(f"{name} must be comma-separated hours between 0 and 23")
        hours.add(hour)
    if not hours:
        return default
    return frozenset(hours)


def _positive_int_from_env(name: str, *, default: int) -> int:
    value = _env(name, str(default))
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise ConfigError(f"{name} must be a positive integer")
    return parsed


def _non_negative_float_from_env(name: str, *, default: float) -> float:
    value = _env(name, str(default))
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a non-negative number") from exc
    if parsed < 0:
        raise ConfigError(f"{name} must be a non-negative number")
    return parsed


def _unit_interval_float_from_env(name: str, *, default: float) -> float:
    value = _env(name, str(default))
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number between 0 and 1") from exc
    if not 0.0 <= parsed <= 1.0:
        raise ConfigError(f"{name} must be a number between 0 and 1")
    return parsed
