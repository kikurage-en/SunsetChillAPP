#!/usr/bin/env bash
# 互換用ラッパー。永続観測スケジューラへ当日のジョブ作成・期限超過確認を委譲する。
#
# 旧cronが残っていても一時的なOpen-Meteo障害で当日分が欠測しないよう、ネットワーク
# 非依存の日没計算とSQLiteジョブを使う。通常運用はsystemd timerが毎分呼び出す。
# 使い方: schedule_sunset_capture.sh [AFTERGLOW_OFFSET_MINUTES]（既定20）
set -euo pipefail

REPO_DIR="/opt/SunsetChillAPP"
VENV_BIN="${REPO_DIR}/.venv/bin"
AFTERGLOW_OFFSET_MINUTES="${1:-20}"

cd "${REPO_DIR}"
export AFTERGLOW_OFFSET_MINUTES
exec "${VENV_BIN}/zushi-chill-observation-scheduler"
