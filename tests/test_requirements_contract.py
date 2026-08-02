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
    ]
    assert expected_columns == CSV_COLUMNS
    requirements = Path("REQUIREMENTS.md").read_text(encoding="utf-8")
    assert "保存スキーマは次の74列" in requirements
    for column in expected_columns:
        assert column in requirements


def test_requirements_document_current_automated_image_evaluation():
    requirements = Path("REQUIREMENTS.md").read_text(encoding="utf-8")

    for text in (
        "日没時と日没後の画像を自動取得",
        "vision_sunset_color_score",
        "vision_afterglow_score",
        "日没+15〜+20分",
        "30秒間隔で最大11枚",
        "SHA-256で重複除外",
        "独立したground truthとは扱わない",
        "GitHub Actions自身には `schedule` を持たせず",
    ):
        assert text in requirements
    for obsolete in (
        "実測ログはGoogleフォームで収集する想定",
        "MVP段階ではLLMに依存しない",
        "Webカメラ画像解析",
    ):
        assert obsolete not in requirements


def test_github_actions_manual_dispatch_is_configured():
    workflow = Path(".github/workflows/daily_chill.yml").read_text(encoding="utf-8")

    assert "schedule:" not in workflow
    assert "group: daily-zushi-chill-${{ github.ref }}" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "workflow_dispatch:" in workflow
    assert "run-name: SunsetChill ${{ inputs.observation_id || github.run_id }}" in workflow
    assert "observation_id:" in workflow
    assert "scheduled_at:" in workflow
    assert "captured_at:" in workflow
    assert "capture_ref:" in workflow
    assert "capture_path:" in workflow
    assert "capture_base64:" in workflow
    assert "capture_sha256:" in workflow
    assert "manual_mode:" in workflow
    assert "type: choice" in workflow
    assert "default: \"dry_run\"" in workflow
    assert "- send_line" in workflow
    assert "contents: write" in workflow
    assert "pages: write" in workflow
    assert "id-token: write" in workflow
    assert "python-version: \"3.12\"" in workflow
    assert 'run: pip install -e ".[dev]" yt-dlp' in workflow
    assert "run: ruff check ." in workflow
    assert "run: pytest" in workflow
    assert "CSV_PATH: ${{ secrets.CSV_PATH || 'logs/chill_predictions.csv' }}" in workflow
    assert "LIVE_CAMERA_URL:" in workflow
    assert "LIVE_CAMERA_VIDEO_ID:" in workflow
    assert "LIVE_CAMERA_IMAGE_BASE_URL:" in workflow
    assert 'JMA_FORECAST_ENABLED: "true"' in workflow
    assert 'JMA_OFFICE_CODE: "140000"' in workflow
    assert 'JMA_AREA_CODE: "140010"' in workflow
    assert 'LIVE_CAMERA_IMAGE_BASE_URL: ""' in workflow
    assert "echo \"Live camera image URL: ${LIVE_CAMERA_IMAGE_URL:-none}\"" in workflow
    assert "Capture live camera image" in workflow
    assert 'git fetch --no-tags --depth=1 origin "$CAPTURE_REF"' in workflow
    assert 'git show "FETCH_HEAD:$CAPTURE_PATH" > "$IMAGE_PATH"' in workflow
    assert "Archived observation image could not be read" in workflow
    assert 'printf \'%s\' "$INPUT_CAPTURE_BASE64" | base64 --decode' in workflow
    assert "Inline observation image checksum does not match" in workflow
    assert 'ACTUAL_CAPTURE_SHA256="$(sha256sum "$IMAGE_PATH"' in workflow
    assert "Archived observation image checksum does not match" in workflow
    assert "yt-dlp --js-runtimes node --no-playlist" in workflow
    assert "ffmpeg -hide_banner" in workflow
    assert "Falling back to YouTube live thumbnail" in workflow
    assert "maxresdefault_live.jpg" in workflow
    assert "hqdefault_live.jpg" in workflow
    assert "curl --fail --location --silent --show-error" in workflow
    assert "Archive live camera image" in workflow
    assert "uses: actions/checkout@v7" in workflow
    assert "uses: actions/setup-python@v7" in workflow
    assert "uses: actions/upload-artifact@v7" in workflow
    assert "retention-days: 90" in workflow
    assert "uses: actions/configure-pages@v6" in workflow
    assert "uses: actions/upload-pages-artifact@v5" in workflow
    assert "uses: actions/deploy-pages@v5" in workflow
    assert "Restore published image history" in workflow
    assert "ref: pages-images" in workflow
    assert "Verify immutable image history" in workflow
    assert "Published image path already contains different bytes" in workflow
    assert "Persist published image history" in workflow
    assert "git push origin HEAD:pages-images" in workflow
    assert "LIVE_CAMERA_IMAGE_RELATIVE_PATH=live-camera/$RUN_DATE/$RUN_TIME_COMPACT.jpg" in workflow
    assert (
        "LIVE_CAMERA_IMAGE_URL=$LIVE_CAMERA_IMAGE_BASE_URL/$LIVE_CAMERA_IMAGE_RELATIVE_PATH"
        in workflow
    )
    assert "path: ${{ env.CSV_PATH }}" in workflow
    assert "if: always() && env.STORAGE_BACKEND == 'csv'" in workflow
    assert "uses: actions/upload-artifact@v7" in workflow
    assert "if-no-files-found: ignore" in workflow
    assert "TIMEZONE: ${{ secrets.TIMEZONE || 'Asia/Tokyo' }}" in workflow
    assert (
        "ALLOW_MISSING_HOURLY_FIELDS: ${{ secrets.ALLOW_MISSING_HOURLY_FIELDS || '' }}"
        in workflow
    )
    assert (
        "DRY_RUN: ${{ github.event_name == 'workflow_dispatch' && "
        "github.event.inputs.manual_mode != 'send_line' && 'true' || 'false' }}"
        in workflow
    )
    assert "LOG_LEVEL: ${{ secrets.LOG_LEVEL || 'INFO' }}" in workflow
    assert 'RUN_TIME="$(TZ=Asia/Tokyo date +%H:%M)"' in workflow
    assert "python -m zushi_chill.main" in workflow
    assert (
        "if: ${{ failure() && (github.event_name != 'workflow_dispatch' || "
        "github.event.inputs.manual_mode != 'dry_run') }}"
        in workflow
    )


def test_sunset_capture_scheduler_collects_sunset_and_afterglow_images():
    script = Path("scripts/schedule_sunset_capture.sh").read_text(encoding="utf-8")

    assert "zushi-chill-observation-scheduler" in script
    assert "AFTERGLOW_OFFSET_MINUTES" in script
    assert " | at " not in script


def test_systemd_observation_scheduler_runs_and_audits_persistent_jobs():
    scheduler_timer = Path(
        "deploy/systemd/zushi-chill-observation-scheduler.timer"
    ).read_text(encoding="utf-8")
    scheduler_service = Path(
        "deploy/systemd/zushi-chill-observation-scheduler.service"
    ).read_text(encoding="utf-8")
    audit_timer = Path("deploy/systemd/zushi-chill-observation-audit.timer").read_text(
        encoding="utf-8"
    )
    audit_service = Path(
        "deploy/systemd/zushi-chill-observation-audit.service"
    ).read_text(encoding="utf-8")
    installer = Path("scripts/install_observation_scheduler.sh").read_text(
        encoding="utf-8"
    )

    assert "OnCalendar=*-*-* *:*:00" in scheduler_timer
    assert "Persistent=true" in scheduler_timer
    assert "zushi-chill-observation-scheduler" in scheduler_service
    assert "TimeoutStartSec=10min" in scheduler_service
    assert "ReadWritePaths=/var/lib/zushi-chill" in scheduler_service
    assert "OnCalendar=*-*-* 21:30:00 Asia/Tokyo" in audit_timer
    assert "zushi-chill-observation-scheduler --audit" in audit_service
    assert (
        "install -d -m 0700 /var/lib/zushi-chill /var/lib/zushi-chill/spool"
        in installer
    )


def test_pyproject_declares_runtime_and_cli_contracts():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["requires-python"] == ">=3.12"
    assert pyproject["project"]["scripts"]["zushi-chill"] == "zushi_chill.main:main"
    assert (
        pyproject["project"]["scripts"]["zushi-chill-contabo-daily"]
        == "zushi_chill.contabo_daily:main"
    )
    assert (
        pyproject["project"]["scripts"]["zushi-chill-trigger-actions"]
        == "zushi_chill.github_actions_trigger:main"
    )
    assert (
        pyproject["project"]["scripts"]["zushi-chill-observation-scheduler"]
        == "zushi_chill.observation_scheduler:main"
    )
    assert (
        pyproject["project"]["scripts"]["zushi-chill-webhook"]
        == "zushi_chill.webhook_server:main"
    )
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
        "LINE_CHANNEL_SECRET=...",
        "LINE_BOT_USER_ID=...",
        "LIVE_CAMERA_URL=https://www.youtube.com/watch?v=Q5AAi9KOjG0",
        "LIVE_CAMERA_VIDEO_ID=Q5AAi9KOjG0",
        "LIVE_CAMERA_IMAGE_BASE_URL=https://<owner>.github.io/<repo>",
        "LIVE_CAMERA_IMAGE_URL=",
        "LIVE_CAMERA_PREVIEW_IMAGE_URL=",
        "LIVE_CAMERA_PUBLIC_DIR=public",
        "LIVE_CAMERA_CAPTURE_TIMEOUT_SECONDS=20",
        "STORAGE_BACKEND=csv",
        "CSV_PATH=logs/chill_predictions.csv",
        "GOOGLE_SHEETS_SPREADSHEET_ID=...",
        "GOOGLE_SHEETS_WORKSHEET=predictions",
        "GOOGLE_SERVICE_ACCOUNT_JSON=",
        "DRY_RUN=false",
        "LOG_LEVEL=INFO",
        "ALLOW_MISSING_HOURLY_FIELDS=",
        "WEBHOOK_HOST=127.0.0.1",
        "WEBHOOK_PORT=8080",
        "GITHUB_REPOSITORY=kikurage-en/SunsetChillAPP",
        "GITHUB_WORKFLOW=daily_chill.yml",
        "GITHUB_REF=main",
        "GITHUB_TOKEN=",
    ]:
        assert setting in readme


def test_readme_does_not_describe_implemented_vision_as_future_scope():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "## 前向き検証運用" in readme
    assert "保存画像を別モデルで一括再採点する専用CLIは現時点では未実装" in readme
    assert "## 6月の検証運用" not in readme
    assert "LLM、画像生成、SNS投稿、自動最適化はMVPに含めていません" not in readme
    assert "Webカメラ画像解析や複数地点対応の検討" not in readme


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


def test_publish_image_history_workflow_is_configured():
    workflow = Path(".github/workflows/publish_image_history.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "contents: read" in workflow
    assert "pages: write" in workflow
    assert "id-token: write" in workflow
    assert "group: daily-zushi-chill-${{ github.ref }}" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "uses: actions/checkout@v7" in workflow
    assert "ref: pages-images" in workflow
    assert "uses: actions/configure-pages@v6" in workflow
    assert "uses: actions/upload-pages-artifact@v5" in workflow
    assert "uses: actions/deploy-pages@v5" in workflow
    assert "path: public" in workflow


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


def test_readme_documents_live_camera_pages_flow():
    readme = Path("README.md").read_text(encoding="utf-8")

    for text in [
        "LINE本文に続けて画像メッセージも送信",
        "画像URLはLINEから取得できるHTTPS URL",
        "GitHub Pagesへ `live-camera/YYYY-MM-DD/HHMM.jpg`",
        "YouTubeのライブサムネイルを取得してフォールバック",
        "取得に成功した場合のみ",
        "Sourceを「GitHub Actions」",
        "`pages-images` branchへ累積保存",
    ]:
        assert text in readme


def test_readme_documents_contabo_github_actions_flow():
    readme = Path("README.md").read_text(encoding="utf-8")

    for text in [
        "Contabo + GitHub Actions運用",
        "ContaboのcronからGitHub Actionsを起動",
        "zushi-chill-trigger-actions",
        "manual_mode=send_line",
        "GitHub Pages側",
        "https://<domain>/line/webhook",
        "固定HTTPS URLを提供するトンネル/外部Webhook基盤",
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
