from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from zushi_chill import config as config_module
from zushi_chill.models import WeatherSummary
from zushi_chill.weather_client import parse_forecast


@pytest.fixture(autouse=True)
def ignore_repository_dotenv(monkeypatch):
    repository_dotenv = Path(__file__).resolve().parents[1] / ".env"
    real_load_dotenv = config_module.load_dotenv

    def guarded_load_dotenv(path=".env"):
        dotenv_path = Path(path)
        if not dotenv_path.is_absolute():
            dotenv_path = Path.cwd() / dotenv_path
        if dotenv_path.resolve() == repository_dotenv:
            return
        real_load_dotenv(path)

    monkeypatch.setattr(config_module, "load_dotenv", guarded_load_dotenv)


@pytest.fixture
def sample_payload() -> dict:
    path = Path(__file__).parent / "fixtures" / "open_meteo_sample.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def sample_summary(sample_payload: dict) -> WeatherSummary:
    return parse_forecast(
        sample_payload,
        location_name="逗子海岸",
        latitude=35.2956,
        longitude=139.5736,
        timezone="Asia/Tokyo",
        run_time=datetime(2026, 6, 1, 13, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
    )
