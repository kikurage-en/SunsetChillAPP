from __future__ import annotations

import tomllib
from pathlib import Path

from zushi_chill.storage import CSV_COLUMNS


def test_prediction_log_columns_match_requirements():
    expected_columns = [
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
    assert expected_columns == CSV_COLUMNS


def test_github_actions_schedule_and_manual_dispatch_are_configured():
    workflow = Path(".github/workflows/daily_chill.yml").read_text(encoding="utf-8")

    assert 'cron: "0 4 * * *"' in workflow
    assert 'cron: "0 8 * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "dry_run:" in workflow
    assert "python-version: \"3.12\"" in workflow
    assert 'run: pip install -e ".[dev]"' in workflow
    assert "run: ruff check ." in workflow
    assert "run: pytest" in workflow
    assert "CSV_PATH: ${{ secrets.CSV_PATH || 'logs/chill_predictions.csv' }}" in workflow
    assert "path: ${{ env.CSV_PATH }}" in workflow
    assert "if: always() && env.STORAGE_BACKEND == 'csv'" in workflow
    assert "uses: actions/upload-artifact@v4" in workflow
    assert "if-no-files-found: ignore" in workflow
    assert "TIMEZONE: ${{ secrets.TIMEZONE || 'Asia/Tokyo' }}" in workflow
    assert (
        "ALLOW_MISSING_HOURLY_FIELDS: ${{ secrets.ALLOW_MISSING_HOURLY_FIELDS || '' }}"
        in workflow
    )
    assert "LOG_LEVEL: ${{ secrets.LOG_LEVEL || 'INFO' }}" in workflow
    assert "SCHEDULE: ${{ github.event.schedule || '' }}" in workflow
    assert '"0 4 * * *") RUN_TIME="13:00"' in workflow
    assert '"0 8 * * *") RUN_TIME="17:00"' in workflow
    assert "python -m zushi_chill.main" in workflow


def test_pyproject_declares_runtime_and_cli_contracts():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["requires-python"] == ">=3.12"
    assert pyproject["project"]["scripts"]["zushi-chill"] == "zushi_chill.main:main"
    assert pyproject["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
    assert pyproject["tool"]["pytest"]["ini_options"]["pythonpath"] == ["src"]
    assert pyproject["tool"]["ruff"]["target-version"] == "py312"


def test_readme_documents_runtime_configuration():
    readme = Path("README.md").read_text(encoding="utf-8")

    for setting in [
        "LOCATION_NAME=逗子海岸",
        "LATITUDE=35.2956",
        "LONGITUDE=139.5736",
        "TIMEZONE=Asia/Tokyo",
        "LINE_CHANNEL_ACCESS_TOKEN=...",
        "LINE_TARGET_ID=...",
        "GOOGLE_FORM_URL=...",
        "STORAGE_BACKEND=csv",
        "CSV_PATH=logs/chill_predictions.csv",
        "GOOGLE_SHEETS_SPREADSHEET_ID=...",
        "GOOGLE_SHEETS_WORKSHEET=predictions",
        "GOOGLE_SERVICE_ACCOUNT_JSON=",
        "DRY_RUN=false",
        "LOG_LEVEL=INFO",
        "ALLOW_MISSING_HOURLY_FIELDS=",
    ]:
        assert setting in readme


def test_readme_documents_score_formulas_and_caps():
    readme = Path("README.md").read_text(encoding="utf-8")

    for text in [
        "低層雲ペナルティ",
        "降水ペナルティ",
        "視程ペナルティ",
        "強風ペナルティ",
        "中層雲ボーナス",
        "高層雲ボーナス",
        "体感温度スコア * 0.30",
        "湿度スコア * 0.20",
        "風スコア * 0.20",
        "降水リスクスコア * 0.20",
        "Sunset期待度 * 0.10",
        "降水確率70%以上でChill指数40",
        "降水量1.0mm以上で45",
        "平均風速8m/s以上で55",
        "最大突風12m/s以上で50",
        "S=85〜100",
        "D=0〜39",
    ]:
        assert text in readme


def test_readme_documents_error_handling():
    readme = Path("README.md").read_text(encoding="utf-8")

    for text in [
        "Open-Meteo API取得は最大3回リトライ",
        "最終失敗時は異常終了してLINE送信しません",
        "必須変数の欠損",
        "line_sent=false",
        "error_message",
        "保存に失敗した場合、LINE送信前であればLINE送信しません",
        "LINE送信後の保存更新に失敗した場合",
    ]:
        assert text in readme


def test_mvp_does_not_add_out_of_scope_dependencies_or_modules():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = "\n".join(pyproject["project"].get("dependencies", []))
    optional_dependencies = "\n".join(
        dependency
        for group in pyproject["project"].get("optional-dependencies", {}).values()
        for dependency in group
    )
    dependency_text = f"{dependencies}\n{optional_dependencies}".lower()
    source_text = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in Path("src/zushi_chill").glob("*.py")
    )

    for forbidden in [
        "openai",
        "anthropic",
        "instagram",
        "tiktok",
        "twitter",
        "fastapi",
        "flask",
        "django",
        "streamlit",
        "gradio",
    ]:
        assert forbidden not in dependency_text
        assert forbidden not in source_text
