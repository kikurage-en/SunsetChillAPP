#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/opt/SunsetChillAPP"
UNIT_SOURCE="${REPO_DIR}/deploy/systemd"
UNIT_TARGET="/etc/systemd/system"

if [[ ! -x "${REPO_DIR}/.venv/bin/zushi-chill-observation-scheduler" ]]; then
  echo "Run .venv/bin/pip install -e . before installing the systemd units." >&2
  exit 1
fi
if [[ ! -x "${REPO_DIR}/.venv/bin/yt-dlp" ]]; then
  echo "Install yt-dlp in the project virtual environment before installation." >&2
  exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Warning: ffmpeg is absent; observation capture will use YouTube thumbnails." >&2
fi

install -d -m 0700 /var/lib/zushi-chill /var/lib/zushi-chill/spool
install -m 0644 \
  "${UNIT_SOURCE}/zushi-chill-observation-scheduler.service" \
  "${UNIT_SOURCE}/zushi-chill-observation-scheduler.timer" \
  "${UNIT_SOURCE}/zushi-chill-observation-audit.service" \
  "${UNIT_SOURCE}/zushi-chill-observation-audit.timer" \
  "${UNIT_TARGET}/"

systemctl daemon-reload
systemctl enable --now zushi-chill-observation-scheduler.timer
systemctl enable --now zushi-chill-observation-audit.timer
systemctl start zushi-chill-observation-scheduler.service
