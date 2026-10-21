#!/usr/bin/env bash
# ============================================================
# MariApps Bunker Report scraper runner — for cron (Linux VM)
# ============================================================
# Runs the MariApps Bunker Report scrape once (bunker_report_scraper.run()).
# Separate from run_mariapps_pipeline.sh's cron entry because that script
# calls backend.mariapps_pipeline.mariapps_pipeline directly, not
# backend.main_entry — so the Bunker Report scrape was never actually
# scheduled before this. Same flock/logging conventions as the other script.
#
# Setup on the VM:
#   1. Edit PROJECT_DIR below if different from the MariApps script's.
#   2. chmod +x scripts/run_bunker_report_scraper.sh
#   3. Add a crontab entry (see scripts/CRON_SETUP.md).
# ============================================================
set -euo pipefail

# --- EDIT THIS to your deployment path on the VM ---
PROJECT_DIR="/opt/vessel_pipeline"

cd "$PROJECT_DIR"

mkdir -p logs
LOG_FILE="$PROJECT_DIR/logs/bunker_report_cron.log"

# Prevent overlapping runs: if a previous run is still going, skip this one.
exec 9>"$PROJECT_DIR/logs/bunker_report_scraper.lock"
if ! flock -n 9; then
    echo "$(date '+%Y-%m-%d %H:%M:%S')  SKIP: previous Bunker Report run still active" >> "$LOG_FILE"
    exit 0
fi

{
    echo "============================================================"
    echo "$(date '+%Y-%m-%d %H:%M:%S')  Bunker Report scraper START"
} >> "$LOG_FILE"

# Activate venv and run. .env is read by backend.config.
source "$PROJECT_DIR/venv/bin/activate"
python -m backend.mariapps_pipeline.bunker_report_scraper >> "$LOG_FILE" 2>&1
STATUS=$?

echo "$(date '+%Y-%m-%d %H:%M:%S')  Bunker Report scraper END (exit=$STATUS)" >> "$LOG_FILE"
exit $STATUS
