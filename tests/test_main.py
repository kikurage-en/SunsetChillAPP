from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from zushi_chill import main as main_module
from zushi_chill import vision_client
from zushi_chill.line_client import LineSendError
from zushi_chill.models import (
    JmaPrecipitationForecast,
    SunsetPredictionReference,
    VisionResult,
)
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
    assert output.startswith("2026-06-01 13:00\n")
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
    assert "Chill指数【" in output
    assert "Sunset期待度【" in output
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["line_sent"] == "False"
    assert rows[0]["chill_weather_basis"] == "target_window"


def test_observation_run_uses_capture_time_metadata_and_line_retry_key(
    monkeypatch,
):
    fake_storage = MemoryStorage()
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: FakeWeatherClient())
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)

    exit_code = main_module.main(
        [
            "--date",
            "2026-06-01",
            "--run-time",
            "19:11",
            "--observation-id",
            "2026-06-01:afterglow",
            "--observation-phase",
            "afterglow",
            "--scheduled-at",
            "2026-06-01T19:11:00+09:00",
            "--captured-at",
            "2026-06-01T19:18:00+09:00",
        ]
    )

    assert exit_code == 0
    assert fake_storage.has_sent_queries[0]["observation_id"] == "2026-06-01:afterglow"
    record = fake_storage.records[-1]
    assert record.summary.run_time == "19:18"
    assert record.summary.run_time_snapshot_time.strftime("%H:%M") == "19:00"
    assert record.scores.chill_weather_basis == "run_time"
    assert record.scheduled_at == datetime(
        2026,
        6,
        1,
        19,
        11,
        tzinfo=ZoneInfo("Asia/Tokyo"),
    )
    assert record.captured_at == datetime(
        2026,
        6,
        1,
        19,
        18,
        tzinfo=ZoneInfo("Asia/Tokyo"),
    )
    assert fake_line_client.retry_keys[0]


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
    assert output.startswith("2026-06-01 13:00\n")
    assert len(fake_storage.records) == 1
    assert fake_storage.records[0].line_sent is False
    assert fake_line_client.sent_messages == []


def test_dry_run_uses_jma_probability_for_message_and_record(monkeypatch, capsys):
    fake_storage = MemoryStorage()
    period_start = datetime(2026, 6, 1, 18, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    class FakeJmaClient:
        def __init__(self, *, timeout):
            assert timeout == 20

        def fetch_precipitation_probability(self, **kwargs):
            assert kwargs["office_code"] == "140000"
            assert kwargs["area_code"] == "140010"
            return JmaPrecipitationForecast(
                probability=20,
                period_start=period_start,
                period_end=period_start + timedelta(hours=6),
                area_name="東部",
                report_time=period_start.replace(hour=17),
            )

    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("JMA_FORECAST_ENABLED", "true")
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: FakeWeatherClient())
    monkeypatch.setattr(main_module, "JmaForecastClient", FakeJmaClient)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "13:00"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "降水確率：20%" in output
    assert fake_storage.records[0].jma_precipitation is not None
    assert fake_storage.records[0].jma_precipitation.probability == 20


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


def test_17_message_integrates_camera_and_formula_when_they_diverge(monkeypatch):
    fake_weather_client = FakeWeatherClient()
    fake_storage = MemoryStorage()
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setenv("LIVE_CAMERA_IMAGE_BASE_URL", "https://pages.example/SunsetChillAPP")
    monkeypatch.setenv("VISION_ENABLED", "true")
    monkeypatch.setenv("VISION_API_KEY", "key")
    pessimistic_vision = VisionResult(
        sunset_score=20,
        sky_condition="overcast",
        comment="厚い雲",
        model="gemini-2.5-flash",
    )
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)
    monkeypatch.setattr(main_module, "analyze_image", lambda **kwargs: pessimistic_vision)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "17:00"])

    assert exit_code == 0
    message = fake_line_client.sent_messages[0]["text"]
    comment = message.split("コメント：\n", 1)[1].split("\n\n--\n", 1)[0]
    assert len(comment.splitlines()) == 1
    assert "海辺" not in comment
    assert "夕焼け" in comment
    assert "けれど、" in comment
    assert any(
        wording in comment
        for wording in (
            "今の空",
            "いま見えている空",
            "ライブカメラ",
            "カメラの空",
            "目の前の空",
            "目の前の雲",
        )
    )
    assert "予報" not in comment
    assert "数字" not in comment
    assert "大当たり" not in message


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
        evaluation_phase="afterglow",
        afterglow_score=55,
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
    # 日没(18:51)後の19:20実行は夕焼け評価のラベルになり、撮影/日没時刻が渡される
    assert "カメラ夕焼け評価" in fake_line_client.sent_messages[0]
    assert captured_kwargs["capture_time"].strftime("%H:%M") == "19:20"
    assert captured_kwargs["sunset_time"].strftime("%H:%M") == "18:51"


def test_after_sunset_message_compares_sent_17_prediction_with_camera_result(monkeypatch):
    prior = SunsetPredictionReference(run_time="17:00", score=80, label="A")
    fake_storage = MemoryStorage(prior_prediction=prior)
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setenv("VISION_ENABLED", "true")
    monkeypatch.setenv("VISION_API_KEY", "key")
    vision = VisionResult(
        sunset_score=68,
        sky_condition="overcast",
        comment="うーん……雲が多い空でも、橙色の残照が見える",
        model="gemini-2.5-flash",
        evaluation_phase="afterglow",
        afterglow_score=68,
    )
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: FakeWeatherClient())
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)
    monkeypatch.setattr(main_module, "analyze_image", lambda **kwargs: vision)

    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "19:20"])

    assert exit_code == 0
    message = fake_line_client.sent_messages[0]
    assert "Sunset期待度【 A 】80 / 100" in message
    assert message.index("📷 ライブカメラ夕焼け評価") < message.index("コメント：")
    assert "残照：68 / 100" not in message
    comment = message.split("コメント：\n", 1)[1].split("\n\n--\n", 1)[0]
    assert any(word in comment for word in ("控えめ", "おとなしい", "伸びなかった"))
    assert "橙色の光が見えるっピ" in comment
    assert all(word not in comment for word in ("17時", "期待度", "残照", "実際の"))
    assert fake_storage.prediction_queries == [
        {
            "date": "2026-06-01",
            "run_time": "17:00",
            "location_name": "逗子海岸",
        }
    ]


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
    def __init__(self, *, already_sent=False, prior_prediction=None):
        self.records = []
        self.already_sent = already_sent
        self.prior_prediction = prior_prediction
        self.has_sent_queries = []
        self.prediction_queries = []

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

    def find_sent_sunset_prediction(self, **kwargs):
        self.prediction_queries.append(kwargs)
        return self.prior_prediction


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
        self.retry_keys = []

    def push_text(self, message, *, retry_key=None):
        self.sent_messages.append(message)
        self.retry_keys.append(retry_key)
        if self.error is not None:
            raise self.error

    def push_text_with_image(
        self,
        message,
        *,
        image_url,
        preview_image_url=None,
        retry_key=None,
    ):
        self.sent_messages.append(
            {
                "text": message,
                "image_url": image_url,
                "preview_image_url": preview_image_url,
            }
        )
        self.retry_keys.append(retry_key)
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
    # 逗子が超快晴(総雲量10%・低層0%)なので例外天井の90
    assert int(row["sunset_score"]) == 90


def test_vision_prediction_blends_into_displayed_sunset_score(monkeypatch):
    from zushi_chill.scoring import blend_sunset_score, score_label

    fake_weather_client = FakeWeatherClient()
    fake_storage = MemoryStorage()
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setenv("VISION_ENABLED", "true")
    monkeypatch.setenv("VISION_API_KEY", "key")
    vision = VisionResult(
        sunset_score=20, sky_condition="overcast", comment="曇り", model="gemini-2.5-flash"
    )
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)
    monkeypatch.setattr(main_module, "analyze_image", lambda **kwargs: vision)

    # 日没(18:51)前の17:00=予測モード → ブレンド適用(既定 weight 0.8)
    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "17:00"])
    assert exit_code == 0

    record = fake_storage.records[-1]
    formula = record.scores.sunset_score
    expected = blend_sunset_score(formula, 20, 0.8)
    # 純式スコアは上書きされず、ブレンド結果は別値として保持
    assert record.final_sunset_score == expected
    assert expected != formula  # Vision(20)が式を引き下げている
    # LINE本文の Sunset期待度 見出しはブレンド値
    assert (
        f"Sunset期待度【 {score_label(expected)} 】{expected} / 100"
        in fake_line_client.sent_messages[0]
    )


def _fixture_payload_with_window_rain(*, precipitation: float, weather_code: int) -> dict:
    path = Path(__file__).parent / "fixtures" / "open_meteo_sample.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    hourly = payload["hourly"]
    n = len(hourly["time"])
    hourly["precipitation"] = [precipitation] * n
    hourly["weather_code"] = [weather_code] * n
    return payload


class StaticPayloadWeatherClient:
    def __init__(self, payload: dict):
        self.payload = payload

    def fetch_forecast(self, *, latitude, longitude, timezone, target_date=None) -> dict:
        return self.payload


def test_rain_signal_disables_vision_uplift(tmp_path, monkeypatch):
    """雨シグナル時はVisionによる表示の上方修正を無効化する(下方修正は維持)。

    2026-07-25 17:00: 窓内4.7mm・コード61の予報を受け取りながら、サムネイル画像の
    見かけ(partly_cloudy 65)がブレンド0.8で表示を式45→61(B)へ持ち上げ、実際の日没時
    発色は0だった。カメラは「これから来る雨」を見えないため、雨予報時は式を上回る
    方向のブレンドを許可しない。
    """
    csv_path = tmp_path / "rain_uplift.csv"
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("CSV_PATH", str(csv_path))
    monkeypatch.setenv("VISION_ENABLED", "true")
    monkeypatch.setenv("VISION_API_KEY", "key")
    fake_storage = MemoryStorage()
    rainy = _fixture_payload_with_window_rain(precipitation=1.5, weather_code=61)
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: StaticPayloadWeatherClient(rainy))
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)

    optimistic_vision = VisionResult(
        sunset_score=65, sky_condition="partly_cloudy", comment="晴れ間", model="gemini-2.5-flash"
    )
    monkeypatch.setattr(main_module, "analyze_image", lambda **kwargs: optimistic_vision)
    assert main_module.main(["--dry-run", "--date", "2026-06-01", "--run-time", "17:00"]) == 0
    record = fake_storage.records[-1]
    # 純式は雨キャップで40以下、Vision(65)による上方修正はされない
    assert record.scores.sunset_score <= 40
    assert record.final_sunset_score == record.scores.sunset_score

    pessimistic_vision = VisionResult(
        sunset_score=10, sky_condition="overcast", comment="厚い雲", model="gemini-2.5-flash"
    )
    monkeypatch.setattr(main_module, "analyze_image", lambda **kwargs: pessimistic_vision)
    assert main_module.main(["--dry-run", "--date", "2026-06-01", "--run-time", "17:00"]) == 0
    record = fake_storage.records[-1]
    # 下方修正(悪い空を写すカメラ)は雨シグナル下でも有効
    assert record.final_sunset_score < record.scores.sunset_score


def test_post_sunset_vision_is_not_blended(monkeypatch):
    fake_weather_client = FakeWeatherClient()
    fake_storage = MemoryStorage()
    fake_line_client = FakeLineClient()
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINE_TARGET_ID", "group-id")
    monkeypatch.setenv("VISION_ENABLED", "true")
    monkeypatch.setenv("VISION_API_KEY", "key")
    vision = VisionResult(
        sunset_score=20,
        sky_condition="overcast",
        comment="画像代理評価",
        model="gemini-2.5-flash",
        evaluation_phase="afterglow",
        afterglow_score=20,
    )
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)
    monkeypatch.setattr(main_module, "storage_from_settings", lambda settings: fake_storage)
    monkeypatch.setattr(main_module, "LineClient", lambda **kwargs: fake_line_client)
    monkeypatch.setattr(main_module, "analyze_image", lambda **kwargs: vision)

    # 日没(18:51)後の19:20=残照画像評価フェーズなのでブレンドしない
    exit_code = main_module.main(["--date", "2026-06-01", "--run-time", "19:20"])
    assert exit_code == 0

    record = fake_storage.records[-1]
    assert record.final_sunset_score == record.scores.sunset_score
    from zushi_chill.scoring import score_label

    assert (
        f"Sunset期待度【 {score_label(record.scores.sunset_score)} 】"
        f"{record.scores.sunset_score} / 100" in fake_line_client.sent_messages[0]
    )


def test_run_without_vision_keeps_formula_as_final(tmp_path, monkeypatch):
    csv_path = tmp_path / "novision.csv"
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("CSV_PATH", str(csv_path))
    fake_weather_client = FakeWeatherClient()
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)

    # 13:00 は VISION_TARGET_HOURS 外で Vision 無し → final = 式スコア
    exit_code = main_module.main(["--dry-run", "--date", "2026-06-01", "--run-time", "13:00"])
    assert exit_code == 0

    row = list(csv.DictReader(csv_path.open(encoding="utf-8")))[0]
    assert row["final_sunset_score"] == row["sunset_score"]
    assert row["final_sunset_label"] == row["sunset_label"]


def test_sunsethue_logged_when_enabled(tmp_path, monkeypatch):
    from zushi_chill.models import SunsethueResult

    csv_path = tmp_path / "sunsethue.csv"
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("CSV_PATH", str(csv_path))
    monkeypatch.setenv("SUNSETHUE_ENABLED", "true")
    monkeypatch.setenv("SUNSETHUE_API_KEY", "key")
    fake_weather_client = FakeWeatherClient()
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)
    monkeypatch.setattr(
        main_module,
        "fetch_sunset_quality",
        lambda **kwargs: SunsethueResult(quality=30, cloud_cover=13, quality_text="Fair"),
    )

    exit_code = main_module.main(["--dry-run", "--date", "2026-06-01", "--run-time", "13:00"])
    assert exit_code == 0

    row = list(csv.DictReader(csv_path.open(encoding="utf-8")))[0]
    assert row["sunsethue_quality"] == "30"
    assert row["sunsethue_cloud_cover"] == "13"
    assert row["sunsethue_quality_text"] == "Fair"


def test_sunsethue_disabled_leaves_columns_empty(tmp_path, monkeypatch):
    csv_path = tmp_path / "sunsethue_off.csv"
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("CSV_PATH", str(csv_path))
    fake_weather_client = FakeWeatherClient()
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)

    exit_code = main_module.main(["--dry-run", "--date", "2026-06-01", "--run-time", "13:00"])
    assert exit_code == 0

    row = list(csv.DictReader(csv_path.open(encoding="utf-8")))[0]
    assert row["sunsethue_quality"] == ""
    assert row["sunsethue_quality_text"] == ""


def test_sunsethue_fetch_failure_is_non_fatal(tmp_path, monkeypatch):
    from zushi_chill.sunsethue_client import SunsethueError

    csv_path = tmp_path / "sunsethue_fail.csv"
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("CSV_PATH", str(csv_path))
    monkeypatch.setenv("SUNSETHUE_ENABLED", "true")
    monkeypatch.setenv("SUNSETHUE_API_KEY", "key")
    fake_weather_client = FakeWeatherClient()
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: fake_weather_client)

    def boom(**kwargs):
        raise SunsethueError("boom")

    monkeypatch.setattr(main_module, "fetch_sunset_quality", boom)

    # Sunsethue が失敗しても実行は止まらず、列は空でメインは継続
    exit_code = main_module.main(["--dry-run", "--date", "2026-06-01", "--run-time", "13:00"])
    assert exit_code == 0
    row = list(csv.DictReader(csv_path.open(encoding="utf-8")))[0]
    assert row["sunsethue_quality"] == ""


class ThreeZoneWeatherClient:
    """逗子(lon>139.5) / 近20km地点(139.3<lon<=139.5) / 遠40km地点(lon<=139.3)で
    別々の雲量を返す。夏の日没方位(WNW)では 20km≈lon139.38、40km≈lon139.18。"""

    def __init__(self, zushi: dict, near: dict, far: dict, fail_near: bool = False):
        self.zushi = zushi
        self.near = near
        self.far = far
        self.fail_near = fail_near

    def fetch_forecast(self, *, latitude, longitude, timezone, target_date=None):
        if longitude > 139.5:
            return self.zushi
        if longitude > 139.3:
            if self.fail_near:
                raise WeatherDataError("near fetch failed")
            return self.near
        return self.far


def test_sunset_cloud_layers_split_between_near_and_far_points(tmp_path, monkeypatch):
    csv_path = tmp_path / "layered.csv"
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("CSV_PATH", str(csv_path))
    zushi = _fixture_payload_with_clouds(low=5, mid=5, high=5, total=10)
    near = _fixture_payload_with_clouds(low=50, mid=60, high=70, total=80)
    far = _fixture_payload_with_clouds(low=90, mid=10, high=20, total=95)
    client = ThreeZoneWeatherClient(zushi, near, far)
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: client)

    exit_code = main_module.main(["--dry-run", "--date", "2026-06-01", "--run-time", "13:00"])
    assert exit_code == 0

    row = list(csv.DictReader(csv_path.open(encoding="utf-8")))[0]
    # 遮蔽側(低層雲・総雲量)は遠40km地点、発色源(中・高層雲)は近20km地点の値
    assert float(row["sunset_cloud_cover"]) == 95
    assert float(row["sunset_cloud_cover_low"]) == 90
    assert float(row["sunset_cloud_cover_mid"]) == 60
    assert float(row["sunset_cloud_cover_high"]) == 70
    assert float(row["sunset_cloud_cover_low_at_sunset"]) == 90
    assert float(row["sunset_cloud_cover_mid_at_sunset"]) == 60
    assert float(row["sunset_cloud_cover_high_at_sunset"]) == 70
    # Chill用の雲は逗子のまま
    assert float(row["cloud_cover"]) == 10


def test_near_point_fetch_failure_falls_back_to_far_values(tmp_path, monkeypatch):
    csv_path = tmp_path / "layered_nearfail.csv"
    monkeypatch.setenv("STORAGE_BACKEND", "csv")
    monkeypatch.setenv("CSV_PATH", str(csv_path))
    zushi = _fixture_payload_with_clouds(low=5, mid=5, high=5, total=10)
    near = _fixture_payload_with_clouds(low=50, mid=60, high=70, total=80)
    far = _fixture_payload_with_clouds(low=90, mid=10, high=20, total=95)
    client = ThreeZoneWeatherClient(zushi, near, far, fail_near=True)
    monkeypatch.setattr(main_module, "OpenMeteoClient", lambda: client)

    exit_code = main_module.main(["--dry-run", "--date", "2026-06-01", "--run-time", "13:00"])
    assert exit_code == 0

    row = list(csv.DictReader(csv_path.open(encoding="utf-8")))[0]
    # near失敗時は mid/high も far地点の値へフォールバック(実行は止めない)
    assert float(row["sunset_cloud_cover_mid"]) == 10
    assert float(row["sunset_cloud_cover_high"]) == 20
    assert float(row["sunset_cloud_cover_low"]) == 90
