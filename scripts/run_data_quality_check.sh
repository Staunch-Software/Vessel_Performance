#!/usr/bin/env bash
# ============================================================
# Data Quality daily check runner — for cron (Linux VM)
# ============================================================
# Runs backend.data_quality.daily_job once. Checks yesterday's data (plus any
# previously-open finding's date, to catch late corrections) for the 3
# confirmed mandatory-field gaps (missing weather, missing CP instruction,
# missing fuel on a steaming day) and emails a per-vessel digest to the
# recipients in vessel_notification_recipients. Scheduled at 14:00 IST
# (after the 13:00/13:30 WNI+MariApps scrape), not right after the first
# overnight scrape — a report dated "yesterday" can still be entered into
# MariApps with some lag during today's business hours, so running too early
# risked flagging it as missing before it had actually landed (manager
# request 2026-10: run it in the afternoon, not the middle of the night).
# Same flock/logging conventions as the other cron runners.
#
# Setup on the VM:
#   1. Edit PROJECT_DIR below if different from the other scripts'.
#   2. chmod +x scripts/run_data_quality_check.sh
#   3. Add a crontab entry (see scripts/CRON_SETUP.md).
#   4. One-time: seed recipients first — python -m import_notification_recipients
# ============================================================
set -euo pipefail

# --- EDIT THIS to your deployment path on the VM ---
PROJECT_DIR="/opt/vessel_pipeline"

cd "$PROJECT_DIR"

mkdir -p logs
LOG_FILE="$PROJECT_DIR/logs/data_quality_cron.log"

# Prevent overlapping runs: if a previous run is still going, skip this one.
exec 9>"$PROJECT_DIR/logs/data_quality_check.lock"
if ! flock -n 9; then
    echo "$(date '+%Y-%m-%d %H:%M:%S')  SKIP: previous Data Quality check still active" >> "$LOG_FILE"
    exit 0
fi

{
    echo "============================================================"
    echo "$(date '+%Y-%m-%d %H:%M:%S')  Data Quality daily check START"
} >> "$LOG_FILE"

# Activate venv and run. .env is read by backend.config.
source "$PROJECT_DIR/venv/bin/activate"
python -m backend.data_quality.daily_job >> "$LOG_FILE" 2>&1
STATUS=$?

echo "$(date '+%Y-%m-%d %H:%M:%S')  Data Quality daily check END (exit=$STATUS)" >> "$LOG_FILE"
exit $STATUS
