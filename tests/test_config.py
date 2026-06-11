from __future__ import annotations

import pytest
from zushi_chill.config import ConfigError, Settings


def test_settings_loads_dotenv_without_overriding_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LOCATION_NAME=env file location",
                "LATITUDE=35.1",
                "LONGITUDE=139.2",
                "GOOGLE_FORM_URL='https://forms.example/dotenv'",
                "ALLOW_MISSING_HOURLY_FIELDS=visibility, wind_gusts_10m",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCATION_NAME", "real environment location")

    settings = Settings.from_env()

    assert settings.location_name == "real environment location"
    assert settings.latitude == 35.1
    assert settings.longitude == 139.2
    assert settings.google_form_url == "https://forms.example/dotenv"
    assert settings.allow_missing_hourly_fields == frozenset({"visibility", "wind_gusts_10m"})


def test_settings_loads_dotenv_over_blank_environment_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LOCATION_NAME=dotenv location",
                "LATITUDE=35.4",
                "LONGITUDE=139.6",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCATION_NAME", "")
    monkeypatch.setenv("LATITUDE", "")
    monkeypatch.setenv("LONGITUDE", " ")

    settings = Settings.from_env()

    assert settings.location_name == "dotenv location"
    assert settings.latitude == 35.4
    assert settings.longitude == 139.6


def test_settings_treats_blank_environment_values_as_missing(monkeypatch):
    monkeypatch.setenv("LOCATION_NAME", "")
    monkeypatch.setenv("LATITUDE", "")
    monkeypatch.setenv("LONGITUDE", "   ")
    monkeypatch.setenv("TIMEZONE", "")
    monkeypatch.setenv("STORAGE_BACKEND", "")
    monkeypatch.setenv("CSV_PATH", "")
    monkeypatch.setenv("GOOGLE_SHEETS_WORKSHEET", "")
    monkeypatch.setenv("DRY_RUN", "")
    monkeypatch.setenv("LOG_LEVEL", "")

    settings = Settings.from_env()

    assert settings.location_name == "逗子海岸"
    assert settings.latitude == 35.2956
    assert settings.longitude == 139.5736
    assert settings.timezone == "Asia/Tokyo"
    assert settings.storage_backend == "csv"
    assert settings.csv_path == "logs/chill_predictions.csv"
    assert settings.google_sheets_worksheet == "predictions"
    assert settings.dry_run is False
    assert settings.log_level == "INFO"


def test_settings_strips_string_environment_values(monkeypatch):
    monkeypatch.setenv("LOCATION_NAME", " 逗子海岸 ")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", " token ")
    monkeypatch.setenv("LINE_TARGET_ID", " group-id ")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", " secret ")
    monkeypatch.setenv("LINE_BOT_USER_ID", " bot-user-id ")
    monkeypatch.setenv("GOOGLE_FORM_URL", " https://forms.example/test ")
    monkeypatch.setenv("LIVE_CAMERA_IMAGE_BASE_URL", " https://pages.example/repo ")
    monkeypatch.setenv("LIVE_CAMERA_IMAGE_URL", " https://pages.example/repo/live.jpg ")
    monkeypatch.setenv("LIVE_CAMERA_PREVIEW_IMAGE_URL", " https://pages.example/repo/preview.jpg ")
    monkeypatch.setenv("LIVE_CAMERA_URL", " https://youtube.example/watch ")
    monkeypatch.setenv("LIVE_CAMERA_VIDEO_ID", " video-id ")
    monkeypatch.setenv("LIVE_CAMERA_PUBLIC_DIR", " /var/www/zushi-chill/public ")
    monkeypatch.setenv("CSV_PATH", " logs/test.csv ")
    monkeypatch.setenv("GOOGLE_SHEETS_SPREADSHEET_ID", " sheet-id ")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", ' {"type":"service_account"} ')

    settings = Settings.from_env()

    assert settings.location_name == "逗子海岸"
    assert settings.line_channel_access_token == "token"
    assert settings.line_target_id == "group-id"
    assert settings.line_channel_secret == "secret"
    assert settings.line_bot_user_id == "bot-user-id"
    assert settings.google_form_url == "https://forms.example/test"
    assert settings.live_camera_image_base_url == "https://pages.example/repo"
    assert settings.live_camera_image_url == "https://pages.example/repo/live.jpg"
    assert settings.live_camera_preview_image_url == "https://pages.example/repo/preview.jpg"
    assert settings.live_camera_url == "https://youtube.example/watch"
    assert settings.live_camera_video_id == "video-id"
    assert settings.live_camera_public_dir == "/var/www/zushi-chill/public"
    assert settings.csv_path == "logs/test.csv"
    assert settings.google_sheets_spreadsheet_id == "sheet-id"
    assert settings.google_service_account_json == '{"type":"service_account"}'


def test_settings_validates_dry_run_bool(monkeypatch):
    monkeypatch.setenv("DRY_RUN", " yes ")

    settings = Settings.from_env()

    assert settings.dry_run is True

    monkeypatch.setenv("DRY_RUN", "maybe")

    with pytest.raises(ConfigError, match="DRY_RUN"):
        Settings.from_env()


def test_settings_rejects_out_of_range_coordinates(monkeypatch):
    monkeypatch.setenv("LATITUDE", "91")

    with pytest.raises(ConfigError, match="LATITUDE"):
        Settings.from_env()

    monkeypatch.setenv("LATITUDE", "35.2956")
    monkeypatch.setenv("LONGITUDE", "181")

    with pytest.raises(ConfigError, match="LONGITUDE"):
        Settings.from_env()


def test_settings_rejects_invalid_google_sheets_worksheet_name(monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEETS_WORKSHEET", "bad/name")

    with pytest.raises(ConfigError, match="GOOGLE_SHEETS_WORKSHEET"):
        Settings.from_env()


def test_settings_normalizes_and_limits_google_sheets_worksheet_name(monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEETS_WORKSHEET", " predictions ")

    settings = Settings.from_env()

    assert settings.google_sheets_worksheet == "predictions"

    monkeypatch.setenv("GOOGLE_SHEETS_WORKSHEET", "x" * 101)

    with pytest.raises(ConfigError, match="GOOGLE_SHEETS_WORKSHEET"):
        Settings.from_env()


def test_settings_rejects_invalid_timezone(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "Not/AZone")

    with pytest.raises(ConfigError, match="TIMEZONE"):
        Settings.from_env()


def test_settings_normalizes_timezone(monkeypatch):
    monkeypatch.setenv("TIMEZONE", " Asia/Tokyo ")

    settings = Settings.from_env()

    assert settings.timezone == "Asia/Tokyo"


def test_settings_rejects_unknown_allow_missing_hourly_field(monkeypatch):
    monkeypatch.setenv("ALLOW_MISSING_HOURLY_FIELDS", "visibility,not_a_field")

    with pytest.raises(ConfigError, match="ALLOW_MISSING_HOURLY_FIELDS"):
        Settings.from_env()


def test_settings_normalizes_and_validates_log_level(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", " debug ")

    settings = Settings.from_env()

    assert settings.log_level == "DEBUG"

    monkeypatch.setenv("LOG_LEVEL", "verbose")

    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        Settings.from_env()


def test_settings_validates_positive_integer_runtime_values(monkeypatch):
    monkeypatch.setenv("LIVE_CAMERA_CAPTURE_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("WEBHOOK_PORT", "9000")

    settings = Settings.from_env()

    assert settings.live_camera_capture_timeout_seconds == 30
    assert settings.webhook_port == 9000

    monkeypatch.setenv("LIVE_CAMERA_CAPTURE_TIMEOUT_SECONDS", "0")

    with pytest.raises(ConfigError, match="LIVE_CAMERA_CAPTURE_TIMEOUT_SECONDS"):
        Settings.from_env()

    monkeypatch.setenv("LIVE_CAMERA_CAPTURE_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("WEBHOOK_PORT", "70000")

    with pytest.raises(ConfigError, match="WEBHOOK_PORT"):
        Settings.from_env()


def test_settings_parses_vision_target_hours(monkeypatch):
    monkeypatch.setenv("VISION_TARGET_HOURS", "17,19")

    assert Settings.from_env().vision_target_hours == frozenset({17, 19})

    monkeypatch.setenv("VISION_TARGET_HOURS", " 17 , 19 ,")

    assert Settings.from_env().vision_target_hours == frozenset({17, 19})


def test_settings_vision_target_hours_defaults_and_legacy_fallback(monkeypatch):
    monkeypatch.delenv("VISION_TARGET_HOURS", raising=False)
    monkeypatch.delenv("VISION_TARGET_HOUR", raising=False)

    assert Settings.from_env().vision_target_hours == frozenset({17, 19})

    monkeypatch.setenv("VISION_TARGET_HOUR", "16")

    assert Settings.from_env().vision_target_hours == frozenset({16})


def test_settings_rejects_invalid_vision_target_hours(monkeypatch):
    monkeypatch.setenv("VISION_TARGET_HOURS", "17,abc")

    with pytest.raises(ConfigError, match="VISION_TARGET_HOURS"):
        Settings.from_env()

    monkeypatch.setenv("VISION_TARGET_HOURS", "24")

    with pytest.raises(ConfigError, match="VISION_TARGET_HOURS"):
        Settings.from_env()
