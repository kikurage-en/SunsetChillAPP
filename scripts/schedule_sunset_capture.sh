#!/usr/bin/env bash
# 当日の「日没 + N分」に、日没後ライブカメラ実況評価のトリガーを at で予約する。
#
# Contabo の cron から朝に1回呼ぶ。日没時刻は季節で変動するため、固定時刻ではなく
# zushi-chill-sunset-eta で当日の日没時刻から実行時刻 (HH:MM) を動的に算出する。
# Open-Meteo 取得に失敗した場合は zushi-chill-sunset-eta が非ゼロ終了し、set -e と
# パイプ前段の失敗で at 予約は行われない (その日の実況評価はスキップされる)。
#
# 使い方: schedule_sunset_capture.sh [OFFSET_MINUTES]   (既定 20)
set -euo pipefail

REPO_DIR="/opt/SunsetChillAPP"
VENV_BIN="${REPO_DIR}/.venv/bin"
LOG="/var/log/zushi-chill-actions-trigger.log"
OFFSET_MINUTES="${1:-20}"

cd "${REPO_DIR}"
RUN_DATE="$(TZ=Asia/Tokyo date +%F)"
RUN_TIME="$("${VENV_BIN}/zushi-chill-sunset-eta" --date "${RUN_DATE}" --minutes "${OFFSET_MINUTES}")"

JOB="cd ${REPO_DIR} && ${VENV_BIN}/zushi-chill-trigger-actions --date ${RUN_DATE} --run-time ${RUN_TIME} >> ${LOG} 2>&1"
echo "${JOB}" | at "${RUN_TIME}"
echo "$(TZ=Asia/Tokyo date '+%F %T') scheduled sunset capture at ${RUN_TIME} (sunset + ${OFFSET_MINUTES}m)" >> "${LOG}"
