#!/usr/bin/env bash
# ============================================================
# WNI pipeline runner — for cron (Linux VM)
# ============================================================
# Runs the Weathernews (WNI) ingestion pipeline once. Designed to be
# invoked by cron every 6 hours. Uses flock so a slow run never overlaps
# the next scheduled run. Logs each run to logs/wni_cron.log.
#
# Setup on the VM:
#   1. Edit PROJECT_DIR below to the checkout path (the folder that
#      contains backend/, venv/, and .env).
#   2. chmod +x scripts/run_wni_pipeline.sh
#   3. Add the crontab entry (see scripts/CRON_SETUP.md).
# ============================================================
set -euo pipefail

# --- EDIT THIS to your deployment path on the VM ---
PROJECT_DIR="/opt/vessel_pipeline"

cd "$PROJECT_DIR"

mkdir -p logs
LOG_FILE="$PROJECT_DIR/logs/wni_cron.log"

# Prevent overlapping runs: if a previous run is still going, skip this one.
exec 9>"$PROJECT_DIR/logs/wni_pipeline.lock"
if ! flock -n 9; then
    echo "$(date '+%Y-%m-%d %H:%M:%S')  SKIP: previous WNI run still active" >> "$LOG_FILE"
    exit 0
fi

{
    echo "============================================================"
    echo "$(date '+%Y-%m-%d %H:%M:%S')  WNI pipeline START"
} >> "$LOG_FILE"

# Activate venv and run. .env is read by backend.config, no need to source it.
source "$PROJECT_DIR/venv/bin/activate"
python -m backend.pipeline.main_pipeline >> "$LOG_FILE" 2>&1
STATUS=$?

echo "$(date '+%Y-%m-%d %H:%M:%S')  WNI pipeline END (exit=$STATUS)" >> "$LOG_FILE"
exit $STATUS
