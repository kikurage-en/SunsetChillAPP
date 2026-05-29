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
    monkeypatch.setenv("GOOGLE_FORM_URL", " https://forms.example/test ")
    monkeypatch.setenv("CSV_PATH", " logs/test.csv ")
    monkeypatch.setenv("GOOGLE_SHEETS_SPREADSHEET_ID", " sheet-id ")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", ' {"type":"service_account"} ')

    settings = Settings.from_env()

    assert settings.location_name == "逗子海岸"
    assert settings.line_channel_access_token == "token"
    assert settings.line_target_id == "group-id"
    assert settings.google_form_url == "https://forms.example/test"
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
