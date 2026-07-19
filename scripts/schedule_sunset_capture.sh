#!/usr/bin/env bash
# 当日の日没時と「日没 + N分」に、ライブカメラ評価のトリガーを at で予約する。
#
# Contabo の cron から朝に1回呼ぶ。日没時刻は季節で変動するため、固定時刻ではなく
# zushi-chill-sunset-eta で当日の日没時刻から実行時刻 (HH:MM) を動的に算出する。
# Open-Meteo 取得に失敗した場合は zushi-chill-sunset-eta が非ゼロ終了し、set -e と
# パイプ前段の失敗で at 予約は行われない (その日の画像評価はスキップされる)。
#
# 日没時は検証専用(dry_run)でLINE送信せず、日没+N分は従来どおりLINE送信する。
# 使い方: schedule_sunset_capture.sh [AFTERGLOW_OFFSET_MINUTES]   (既定 20)
set -euo pipefail

REPO_DIR="/opt/SunsetChillAPP"
VENV_BIN="${REPO_DIR}/.venv/bin"
LOG="/var/log/zushi-chill-actions-trigger.log"
AFTERGLOW_OFFSET_MINUTES="${1:-20}"

cd "${REPO_DIR}"
RUN_DATE="$(TZ=Asia/Tokyo date +%F)"
SUNSET_TIME="$("${VENV_BIN}/zushi-chill-sunset-eta" --date "${RUN_DATE}" --minutes 0)"
AFTERGLOW_TIME="$("${VENV_BIN}/zushi-chill-sunset-eta" --date "${RUN_DATE}" --minutes "${AFTERGLOW_OFFSET_MINUTES}")"

SUNSET_JOB="cd ${REPO_DIR} && ${VENV_BIN}/zushi-chill-trigger-actions --date ${RUN_DATE} --run-time ${SUNSET_TIME} --manual-mode dry_run >> ${LOG} 2>&1"
echo "${SUNSET_JOB}" | at "${SUNSET_TIME}"
echo "$(TZ=Asia/Tokyo date '+%F %T') scheduled sunset evaluation at ${SUNSET_TIME}" >> "${LOG}"

if [ "${AFTERGLOW_OFFSET_MINUTES}" -ne 0 ]; then
  AFTERGLOW_JOB="cd ${REPO_DIR} && ${VENV_BIN}/zushi-chill-trigger-actions --date ${RUN_DATE} --run-time ${AFTERGLOW_TIME} --manual-mode send_line >> ${LOG} 2>&1"
  echo "${AFTERGLOW_JOB}" | at "${AFTERGLOW_TIME}"
  echo "$(TZ=Asia/Tokyo date '+%F %T') scheduled afterglow evaluation at ${AFTERGLOW_TIME} (sunset + ${AFTERGLOW_OFFSET_MINUTES}m)" >> "${LOG}"
fi
