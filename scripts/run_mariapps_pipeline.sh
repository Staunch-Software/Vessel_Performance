#!/usr/bin/env bash
# ============================================================
# MariApps pipeline runner — for cron (Linux VM)
# ============================================================
# Runs the MariApps ingestion pipeline once. Requires the SSO account
# (MARIAPPS_USERNAME / MARIAPPS_PASSWORD in .env) to have MFA disabled so
# the automated Microsoft login can run headless. Uses flock so a slow run
# never overlaps the next scheduled run. Logs to logs/mariapps_cron.log.
#
# Setup on the VM:
#   1. Edit PROJECT_DIR below to the checkout path (contains backend/, venv/, .env).
#   2. chmod +x scripts/run_mariapps_pipeline.sh
#   3. Add the crontab entry (see scripts/CRON_SETUP.md).
# ============================================================
set -euo pipefail

# --- EDIT THIS to your deployment path on the VM ---
PROJECT_DIR="/opt/vessel_pipeline"

cd "$PROJECT_DIR"

mkdir -p logs
LOG_FILE="$PROJECT_DIR/logs/mariapps_cron.log"

# Prevent overlapping runs: if a previous run is still going, skip this one.
exec 9>"$PROJECT_DIR/logs/mariapps_pipeline.lock"
if ! flock -n 9; then
    echo "$(date '+%Y-%m-%d %H:%M:%S')  SKIP: previous MariApps run still active" >> "$LOG_FILE"
    exit 0
fi

{
    echo "============================================================"
    echo "$(date '+%Y-%m-%d %H:%M:%S')  MariApps pipeline START"
} >> "$LOG_FILE"

# Activate venv and run. .env is read by backend.config.
source "$PROJECT_DIR/venv/bin/activate"
python -m backend.mariapps_pipeline.mariapps_pipeline >> "$LOG_FILE" 2>&1
STATUS=$?

echo "$(date '+%Y-%m-%d %H:%M:%S')  MariApps pipeline END (exit=$STATUS)" >> "$LOG_FILE"
exit $STATUS
