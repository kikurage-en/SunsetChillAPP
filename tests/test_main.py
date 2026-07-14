from __future__ import annotations

import csv
import json
from pathlib import Path

from zushi_chill import main as main_module
from zushi_chill import vision_client
from zushi_chill.line_client import LineSendError
from zushi_chill.models import VisionResult
from zushi_chill.weather_client import WeatherDataError


class FakeWeatherClient:
    def fetch_forecast(
        self, *, latitude: float, longitude: float, timezone: str, target_date=None
    ) -> dict:
        self.target_date = target_date
        path = Path(__file__).parent / "fixtures" / "open_meteo_sample.json"
        return json.loads(path.read_text(encoding="utf-8"))


class FailIfCalledWeatherClient:
    def fetch_forecast(self, **kwargs):
        raise AssertionError("Open-Meteo API should not be called")


class FailingWeatherClient:
    def fetch_forecast(self, **kwargs):
        raise WeatherDataError("Open-Meteo fetch failed after 3 attempts")


def test_dry_run_prints_message_and_does_not_send_line(tmp_path, monkeypatch, capsys):
    csv_path = tmp_path / "dry_run.csv"
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("CSV_PATH", str(csv_path))
    fake_weather_client = FakeWeatherClient()
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)

    exit_code = main_module.main(["--dry-run", "--date", "2026-06-01", "--run-time", "13:00"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "逗子サンセットチル指数" in output
    assert csv_path.exists()
    assert fake_weather_client.target_date.isoformat() == "2026-06-01"


def test_dry_run_can_use_fixture_input_json_without_api(tmp_path, monkeypatch, capsys):
    csv_path = tmp_path / "fixture_run.csv"
    fixture_path = Path(__file__).parent / "fixtures" / "open_meteo_sample.json"
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("CSV_PATH", str(csv_path))
    monkeypatch.setattr(main_module, "OpenMeteoClient", FailIfCalledWeatherClient)

    exit_code = main_module.main(
        [
            "--dry-run",
            "--input-json",
            str(fixture_path),
            "--date",
            "2026-06-01",
            "--run-time",
            "13:00",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Chill指数：" in output
    assert "Sunset期待度：" in output
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["line_sent"] == "False"


def test_dry_run_environment_value_prevents_line_send(monkeypatch, capsys):
    fake_weather_client = FakeWeatherClient()
    fake_storage = MemoryStorage()
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "13:00"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "逗子サンセットチル指数" in output
    assert len(fake_storage.records) == 1
    assert fake_storage.records[0].line_sent is False
    assert fake_line_client.sent_messages == []


def test_input_json_missing_file_returns_error(tmp_path, monkeypatch):
    csv_path = tmp_path / "missing.csv"
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("CSV_PATH", str(csv_path))

    exit_code = main_module.main(
        [
            "--dry-run",
            "--input-json",
            str(tmp_path / "missing.json"),
            "--date",
            "2026-06-01",
            "--run-time",
            "13:00",
        ]
    )

    assert exit_code == 1
    assert not csv_path.exists()


def test_input_json_invalid_json_returns_error(tmp_path, monkeypatch):
    csv_path = tmp_path / "invalid.csv"
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("CSV_PATH", str(csv_path))

    exit_code = main_module.main(
        [
            "--dry-run",
            "--input-json",
            str(invalid_json),
            "--date",
            "2026-06-01",
            "--run-time",
            "13:00",
        ]
    )

    assert exit_code == 1
    assert not csv_path.exists()


def test_weather_fetch_failure_prevents_storage_and_line_send(monkeypatch):
    fake_storage = MemoryStorage()
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setattr(main_module, "OpenMeteoClient", FailingWeatherClient)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "13:00"])

    assert exit_code == 1
    assert fake_storage.records == []
    assert fake_line_client.sent_messages == []


def test_invalid_date_or_run_time_prevents_weather_fetch_storage_and_line(monkeypatch):
    fake_storage = MemoryStorage()
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setattr(main_module, "OpenMeteoClient", FailIfCalledWeatherClient)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)

    bad_date_exit = main_module.main(["--date", "2026/06/01", "--run-time", "13:00"])
    bad_time_exit = main_module.main(["--date", "2026-06-01", "--run-time", "13時"])
    non_padded_date_exit = main_module.main(["--date", "2026-6-1", "--run-time", "13:00"])
    seconds_time_exit = main_module.main(["--date", "2026-06-01", "--run-time", "13:00:30"])
    non_padded_time_exit = main_module.main(["--date", "2026-06-01", "--run-time", "3:00"])

    assert bad_date_exit == 1
    assert bad_time_exit == 1
    assert non_padded_date_exit == 1
    assert seconds_time_exit == 1
    assert non_padded_time_exit == 1
    assert fake_storage.records == []
    assert fake_line_client.sent_messages == []


def test_storage_failure_prevents_line_send(monkeypatch):
    fake_weather_client = FakeWeatherClient()
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: FailingStorage())
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "17:00"])

    assert exit_code == 1
    assert fake_line_client.sent_messages == []


def test_line_failure_updates_saved_record_with_error(monkeypatch):
    fake_weather_client = FakeWeatherClient()
    fake_storage = MemoryStorage()
    fake_line_client = FakeLineClient(error=LineSendError("LINE returned HTTP 401: invalid token"))
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "17:00"])

    assert exit_code == 1
    assert len(fake_line_client.sent_messages) == 1
    assert fake_storage.records[0].line_sent is False
    assert fake_storage.records[-1].line_sent is False
    assert "HTTP 401" in fake_storage.records[-1].error_message


def test_line_failure_logs_when_error_record_update_fails(monkeypatch, caplog):
    fake_weather_client = FakeWeatherClient()
    fake_storage = ReplaceFailingStorage()
    fake_line_client = FakeLineClient(error=LineSendError("LINE returned HTTP 401: invalid token"))
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "17:00"])

    assert exit_code == 1
    assert len(fake_line_client.sent_messages) == 1
    assert len(fake_storage.records) == 1
    assert fake_storage.records[0].line_sent is False
    assert "LINE failed and failed to update storage with the error" in caplog.text


def test_missing_line_settings_updates_saved_record_with_error(monkeypatch):
    fake_weather_client = FakeWeatherClient()
    fake_storage = MemoryStorage()
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LINE_TARGET_ID", raising=False)
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "17:00"])

    assert exit_code == 1
    assert fake_line_client.sent_messages == []
    assert len(fake_storage.records) == 1
    assert fake_storage.records[0].line_sent is False
    assert "LINE_CHANNEL_ACCESS_TOKEN" in fake_storage.records[0].error_message


def test_line_success_updates_saved_record_as_sent(monkeypatch):
    fake_weather_client = FakeWeatherClient()
    fake_storage = MemoryStorage()
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "17:00"])

    assert exit_code == 0
    assert len(fake_line_client.sent_messages) == 1
    assert fake_storage.records[-1].line_sent is True
    assert fake_storage.records[-1].error_message == ""


def test_duplicate_sent_record_skips_weather_storage_and_line(monkeypatch):
    fake_storage = MemoryStorage(already_sent=True)
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setattr(main_module, "OpenMeteoClient", FailIfCalledWeatherClient)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "17:00"])

    assert exit_code == 0
    assert fake_storage.has_sent_queries == [
        {
            "date": "2026-06-01",
            "run_time": "17:00",
            "location_name": "逗子海岸",
        }
    ]
    assert fake_storage.records == []
    assert fake_line_client.sent_messages == []


def test_line_success_can_attach_live_camera_image_from_base_url(monkeypatch):
    fake_weather_client = FakeWeatherClient()
    fake_storage = MemoryStorage()
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setenv("LIVE_CAMERA_IMAGE_BASE_URL", "https://pages.example/SunsetChillAPP")
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "17:00"])

    assert exit_code == 0
    assert fake_line_client.sent_messages == [
        {
            "text": fake_line_client.sent_messages[0]["text"],
            "image_url": "https://pages.example/SunsetChillAPP/live-camera/2026-06-01/1700.jpg",
            "preview_image_url": (
                "https://pages.example/SunsetChillAPP/live-camera/2026-06-01/1700.jpg"
            ),
        }
    ]
    assert fake_storage.records[-1].line_sent is True


def test_line_success_logs_when_storage_update_fails(monkeypatch, caplog):
    fake_weather_client = FakeWeatherClient()
    fake_storage = ReplaceFailingStorage()
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "17:00"])

    assert exit_code == 1
    assert len(fake_line_client.sent_messages) == 1
    assert len(fake_storage.records) == 1
    assert fake_storage.records[0].line_sent is False
    assert "LINE sent but failed to update storage" in caplog.text


def test_vision_analysis_runs_at_target_hour_and_is_recorded(monkeypatch):
    fake_weather_client = FakeWeatherClient()
    fake_storage = MemoryStorage()
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setenv("LIVE_CAMERA_IMAGE_BASE_URL", "https://pages.example/SunsetChillAPP")
    monkeypatch.setenv("VISION_ENABLED", "true")
    monkeypatch.setenv("VISION_API_KEY", "key")
    vision = VisionResult(
        sunset_score=80, sky_condition="golden_hour", comment="鮮やか", model="gemini-2.5-flash"
    )
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)
    monkeypatch.setattr(main_module, "analyze_image", lambda **kwargs: vision)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "17:00"])

    assert exit_code == 0
    assert fake_storage.records[-1].vision == vision
    # 日没(18:51)前の17:00実行は予測モードのラベルになる
    assert "カメラAI予測" in fake_line_client.sent_messages[0]["text"]


def test_vision_analysis_after_sunset_uses_actual_label(monkeypatch):
    fake_weather_client = FakeWeatherClient()
    fake_storage = MemoryStorage()
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setenv("VISION_ENABLED", "true")
    monkeypatch.setenv("VISION_API_KEY", "key")
    vision = VisionResult(
        sunset_score=55,
        sky_condition="partly_cloudy",
        comment="部分的な色",
        model="gemini-2.5-flash",
    )
    captured_kwargs: dict = {}

    def capture_analyze(**kwargs):
        captured_kwargs.update(kwargs)
        return vision

    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)
    monkeypatch.setattr(main_module, "analyze_image", capture_analyze)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "19:20"])

    assert exit_code == 0
    assert fake_storage.records[-1].vision == vision
    # 日没(18:51)後の19:20実行は実況評価のラベルになり、撮影/日没時刻が渡される
    assert "カメラ実況評価" in fake_line_client.sent_messages[0]
    assert captured_kwargs["capture_time"].strftime("%H:%M") == "19:20"
    assert captured_kwargs["sunset_time"].strftime("%H:%M") == "18:51"


def test_vision_analysis_skipped_off_target_hour(monkeypatch):
    fake_weather_client = FakeWeatherClient()
    fake_storage = MemoryStorage()
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setenv("VISION_ENABLED", "true")
    monkeypatch.setenv("VISION_API_KEY", "key")

    def fail_analyze(**kwargs):
        raise AssertionError("analyze_image must not run at 13:00")

    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)
    monkeypatch.setattr(main_module, "analyze_image", fail_analyze)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "13:00"])

    assert exit_code == 0
    assert fake_storage.records[-1].vision is None


def test_vision_failure_does_not_block_line_send(monkeypatch):
    fake_weather_client = FakeWeatherClient()
    fake_storage = MemoryStorage()
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setenv("VISION_ENABLED", "true")
    monkeypatch.setenv("VISION_API_KEY", "key")

    def boom(**kwargs):
        raise vision_client.VisionError("Gemini request failed")

    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)
    monkeypatch.setattr(main_module, "analyze_image", boom)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "17:00"])

    assert exit_code == 0
    assert len(fake_line_client.sent_messages) == 1
    assert fake_storage.records[-1].vision is None


class MemoryStorage:
    def __init__(self, *, already_sent=False):
        self.records = []
        self.already_sent = already_sent
        self.has_sent_queries = []

    def save(self, record):
        self.records.append(record)

    def replace_latest(self, record):
        if self.records:
            self.records[-1] = record
        else:
            self.records.append(record)

    def has_sent(self, **kwargs):
        self.has_sent_queries.append(kwargs)
        return self.already_sent


class FailingStorage:
    def has_sent(self, **kwargs):
        return False

    def save(self, record):
        raise RuntimeError("storage unavailable")

    def replace_latest(self, record):
        raise RuntimeError("storage unavailable")


class ReplaceFailingStorage:
    def __init__(self):
        self.records = []

    def save(self, record):
        self.records.append(record)

    def replace_latest(self, record):
        raise RuntimeError("replace failed")

    def has_sent(self, **kwargs):
        return False


class FakeLineClient:
    def __init__(self, error=None):
        self.error = error
        self.sent_messages = []

    def push_text(self, message):
        self.sent_messages.append(message)
        if self.error is not None:
            raise self.error

    def push_text_with_image(self, message, *, image_url, preview_image_url=None):
        self.sent_messages.append(
            {
                "text": message,
                "image_url": image_url,
                "preview_image_url": preview_image_url,
            }
        )
        if self.error is not None:
            raise self.error


def _fixture_payload_with_clouds(*, low: float, mid: float, high: float, total: float) -> dict:
    path = Path(__file__).parent / "fixtures" / "open_meteo_sample.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    hourly = payload["hourly"]
    n = len(hourly["time"])
    hourly["cloud_cover"] = [total] * n
    hourly["cloud_cover_low"] = [low] * n
    hourly["cloud_cover_mid"] = [mid] * n
    hourly["cloud_cover_high"] = [high] * n
    return payload


class SplitByLongitudeWeatherClient:
    """逗子(経度139.5736)と、その西の日没方位地点で別々の雲量を返す。"""

    def __init__(self, zushi_payload: dict, west_payload: dict):
        self.zushi_payload = zushi_payload
        self.west_payload = west_payload
        self.calls: list[tuple[float, float]] = []

    def fetch_forecast(self, *, latitude, longitude, timezone, target_date=None):
        self.calls.append((round(latitude, 3), round(longitude, 3)))
        return self.west_payload if longitude < 139.5 else self.zushi_payload


class WestFetchFailsWeatherClient:
    """西の日没方位地点だけ取得に失敗する。逗子(フォールバック先)は成功する。"""

    def __init__(self, zushi_payload: dict):
        self.zushi_payload = zushi_payload

    def fetch_forecast(self, *, latitude, longitude, timezone, target_date=None):
        if longitude < 139.5:
            raise WeatherDataError("west fetch failed")
        return self.zushi_payload


def test_sunset_uses_western_clouds_while_chill_uses_zushi(tmp_path, monkeypatch):
    csv_path = tmp_path / "split.csv"
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("CSV_PATH", str(csv_path))
    zushi = _fixture_payload_with_clouds(low=0, mid=5, high=5, total=10)
    west = _fixture_payload_with_clouds(low=90, mid=60, high=90, total=95)
    client = SplitByLongitudeWeatherClient(zushi, west)
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: client)

    exit_code = main_module.main(["--dry-run", "--date", "2026-06-01", "--run-time", "13:00"])
    assert exit_code == 0

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    row = rows[0]
    # 逗子と、その西(経度<139.5)の両方が取得された
    assert any(longitude < 139.5 for _, longitude in client.calls)
    # Sunset期待度用の雲は西の値でログされる
    assert float(row["sunset_cloud_cover"]) == 95
    assert float(row["sunset_cloud_cover_low"]) == 90
    # Chill指数用の cloud_cover は逗子(快晴)の値
    assert float(row["cloud_cover"]) == 10
    # 西が厚い雲なので Sunset期待度は大きく下がる(低層雲ペナルティ+総雲量85%以上キャップ)
    assert int(row["sunset_score"]) <= 30


def test_western_cloud_fetch_failure_falls_back_to_zushi(tmp_path, monkeypatch):
    csv_path = tmp_path / "fallback.csv"
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("CSV_PATH", str(csv_path))
    zushi = _fixture_payload_with_clouds(low=0, mid=5, high=5, total=10)
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: WestFetchFailsWeatherClient(zushi))

    # 西の取得が失敗しても実行は止まらず、逗子の雲へフォールバックする
    exit_code = main_module.main(["--dry-run", "--date", "2026-06-01", "--run-time", "13:00"])
    assert exit_code == 0

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    row = rows[0]
    # フォールバックにより Sunset用の雲=逗子の値
    assert float(row["sunset_cloud_cover"]) == 10
    # 逗子が快晴なので Sunset期待度は高いまま
    assert int(row["sunset_score"]) == 100
