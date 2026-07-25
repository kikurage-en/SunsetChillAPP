from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from zushi_chill import config as config_module
from zushi_chill.models import WeatherSummary
from zushi_chill.weather_client import parse_forecast


@pytest.fixture(autouse=True)
def restore_os_environ():
    # Settings.from_env() -> load_dotenv() は os.environ へ直接書き込む(monkeypatch
    # 管理外)ため、.env を読むテストの値が後続テストへ漏れる。各テスト後にスナップ
    # ショットへ復元して分離する(2026-07-14: test_config の LONGITUDE 漏れを検知)。
    snapshot = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snapshot)


@pytest.fixture(autouse=True)
def isolate_ci_job_env(monkeypatch):
    # daily_chill.yml はjobレベルenvを全ステップ(pytest含む)に注入するため、
    # 隔離しないとローカルとCIでテスト結果が割れる(2026-06-11の17時実行失敗の原因)
    for name in (
        "STORAGE_BACKEND",
        "CSV_PATH",
        "LIVE_CAMERA_URL",
        "LIVE_CAMERA_VIDEO_ID",
        "LIVE_CAMERA_IMAGE_BASE_URL",
        "LIVE_CAMERA_IMAGE_URL",
        "LIVE_CAMERA_CAPTURE_SOURCE",
        "LIVE_CAMERA_CAPTURED_AT",
        "LIVE_CAMERA_IMAGE_SHA256",
        "JMA_FORECAST_ENABLED",
        "JMA_OFFICE_CODE",
        "JMA_AREA_CODE",
        "JMA_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


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
