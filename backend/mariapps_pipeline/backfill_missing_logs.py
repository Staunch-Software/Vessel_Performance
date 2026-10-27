"""
One-off targeted re-scrape for a vessel whose EARLIEST MariApps log(s) never
made it into our database at all — confirmed 2026-10 on AM TARANG log
07L/01/01 (EOSP, 2025-12-30): present and "Submitted" in MariApps' own Log
Validation Review grid, but absent from raw_mariapps_logs entirely.

ROOT CAUSE: mariapps_pipeline.py's FROM_DATE/TO_DATE are hardcoded module
constants, NOT per-vessel or dynamically re-opened — every regular cron run
(4x daily) only ever requests MariApps data from the CURRENT FROM_DATE
forward (currently "01-JUN-2026"). Whatever full-history backfill originally
populated a vessel's earlier months apparently missed this one log at the
very edge of whatever range was used at the time, and since FROM_DATE has
since moved forward, no regular run will ever reach back far enough to
notice or recover it — it's permanently invisible to the normal pipeline.

WHY A SEPARATE SCRIPT, not editing mariapps_pipeline.py's FROM_DATE/
VESSEL_LIST directly: that file is also what the live cron job
(run_mariapps_pipeline.sh, 4x daily) runs unmodified. Editing its module
constants on disk — even temporarily — risks a cron firing mid-edit and
re-scraping the full historical range for every vessel instead of just the
one being backfilled here. This script monkey-patches those constants in
memory only, for this process, and never touches the file.

Safe to re-run: existing logs are skipped via the normal is_already_processed
check (recheck-window logic still applies for anything within
RECHECK_WINDOW_DAYS of today) — only genuinely-missing logs get scraped.

Usage:
    python -m backend.mariapps_pipeline.backfill_missing_logs "AM TARANG" "25-DEC-2025" "15-JAN-2026"

    vessel name   : exact MariApps vessel name (as in VESSEL_LIST)
    from_date     : "DD-MON-YYYY", should predate the gap by a few days
    to_date       : "DD-MON-YYYY", should extend a little past the gap —
                    NOT all the way to today (that would reopen this
                    vessel's ENTIRE history; is_already_processed() will
                    skip anything already in the DB either way, but keeping
                    the range narrow keeps this fast and the MariApps UI
                    export small).
"""
import sys

from . import mariapps_pipeline
from .. import database as database_module


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)

    vessel_name, from_date, to_date = sys.argv[1], sys.argv[2], sys.argv[3]

    mariapps_pipeline.FROM_DATE = from_date
    mariapps_pipeline.TO_DATE = to_date
    mariapps_pipeline.VESSEL_LIST = [vessel_name]

    # run() re-derives its own vessel list from the DB (vessels.mari_enabled)
    # every call, ignoring the module-level VESSEL_LIST above unless the DB
    # query returns nothing — AM TARANG (and every other active vessel) IS
    # mari_enabled, so without this patch run() would silently scrape all
    # ~14 enabled vessels across our narrow date range instead of just this
    # one. Patched at the database module itself, since mariapps_pipeline.run()
    # does `from ..database import get_scrape_vessels` as a fresh LOCAL import
    # each call — patching mariapps_pipeline's own (non-existent, never
    # imported at module level) attribute would do nothing.
    database_module.get_scrape_vessels = lambda source: [vessel_name]

    mariapps_pipeline.run()


if __name__ == "__main__":
    main()
