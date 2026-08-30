"""
set_default_performance_columns.py
-----------------------------------
One-off script: sets the GLOBAL (all-vessels) admin column default for the
Performance category on the MariApps source in `vessel_column_defaults`
(vessel_imo = NULL row), per the manager's explicit 18-column selection +
order request.

What it does, safely and idempotently:
  1. Reads the existing global default row for (source='mari_apps',
     vessel_imo=NULL), if any. If none exists yet, falls back to "every
     currently is_active column" as the starting visible set — mirroring
     ColumnPicker.jsx's own fallback logic, so this script produces the same
     result the UI would if an admin opened the picker fresh and hit "Default"
     on every category before touching Performance.
  2. Drops every column currently tagged `performance=True` from that visible
     set (so stale/undesired Performance picks don't linger), and the 4 CP
     Warranty direct columns too (Speed / Speed Tolerance / Warranted
     Consumption / Consumption Tolerance), so re-running this script is safe.
  3. Adds back exactly the manager's 18 Performance columns, plus the 4 CP
     Warranty columns (matching the client's separate "add CP Warranted Speed
     and Consumption fields into the Performance category" request — they are
     tagged performance=True in expander.py, so they now live there too).
  4. Every OTHER category's existing visible columns are left untouched.

  Column ORDER for Performance is a separate, code-level fix — see
  `_PERFORMANCE_DEFAULT_ORDER` / `_PERFORMANCE_DEFAULT_RANK` in
  backend/pipeline/expander.py, which forces sort_order on every backend
  restart regardless of this script.

Run once per environment (local, then production) after deploying the
expander.py changes:

    python set_default_performance_columns.py

Safe to re-run — upserts the same target state every time.
"""

from sqlalchemy import text
from backend.database import SessionLocal
from backend.models import VesselColumnDefault

SOURCE = "mari_apps"

# Manager's exact 18-column Performance default + order (matches
# _PERFORMANCE_DEFAULT_ORDER in backend/pipeline/expander.py).
TARGET_PERFORMANCE_COLUMNS = [
    "VoyageMeta_to_port_operational_LF",
    "VoyageMeta_log_durationh_operational_LF",
    "ME_RHME_dCnt_operational_LF",
    "Vessel_SOG_avg_operational_LF",
    "Vessel_SOGcal_avg_operational_LF",
    "Vessel_STW_avg_operational_LF",
    "VoyageMeta_real_slip_operational_LF",
    "ME_FO_mFOCME_dCnt_operational_LF",
    "AE_FO_mFOCAE_dCnt_operational_LF",
    "AuxBoiler_mFOCBL_dCnt_operational_LF",
    "ME_NME_avg_operational_LF",
    "ME_mcrcalME_avg_operational_LF",
    "ME_PSME_avg_operational_LF",
    "ME_DESME_dCnt_operational_LF",
    "ME_PeffcalME_avg_operational_LF",
    "ME_PeffestME_avg_operational_LF",
    "VoyageMeta_trimm_operational_LF",
    "Vessel_DISP_avg_operational_LF",
]

# The 4 CP Warranty direct columns (matches _CP_WARRANTY_DIRECT_COLS) —
# category="Emission" but performance=True, so they belong here too per the
# manager's "additionally add CP Warranted Speed and Consumption into the
# Performance category" request.
CP_WARRANTY_COLUMNS = [
    "mariappsx_cp_warranted_speed_kn",
    "mariappsx_cp_speed_tolerance_kn",
    "mariappsx_cp_warranted_consumption_mtday",
    "mariappsx_cp_consumption_tolerance_pct",
]


def main():
    db = SessionLocal()
    try:
        perf_cols = {
            r[0] for r in db.execute(
                text("SELECT db_column FROM expanded_column_metadata WHERE source=:s AND performance=TRUE"),
                {"s": SOURCE},
            ).fetchall()
        }

        rec = db.query(VesselColumnDefault).filter(
            VesselColumnDefault.source == SOURCE,
            VesselColumnDefault.vessel_imo.is_(None),
        ).first()

        if rec and isinstance(rec.column_prefs, dict) and rec.column_prefs.get("visible"):
            visible = set(rec.column_prefs["visible"])
            print(f"Existing global default found: {len(visible)} columns visible.")
        else:
            visible = {
                r[0] for r in db.execute(
                    text("SELECT db_column FROM expanded_column_metadata WHERE source=:s AND is_active=TRUE"),
                    {"s": SOURCE},
                ).fetchall()
            }
            print(f"No existing global default — seeding from {len(visible)} is_active=TRUE columns.")

        before = len(visible)
        visible -= perf_cols
        visible |= set(TARGET_PERFORMANCE_COLUMNS)
        visible |= set(CP_WARRANTY_COLUMNS)

        new_prefs = dict(rec.column_prefs) if rec and isinstance(rec.column_prefs, dict) else {}
        new_prefs["visible"] = sorted(visible)

        if rec:
            rec.column_prefs = new_prefs
        else:
            db.add(VesselColumnDefault(vessel_imo=None, source=SOURCE, column_prefs=new_prefs))
        db.commit()

        print(
            f"Done. {SOURCE}: global default now has {len(visible)} visible columns "
            f"(was {before}) — Performance category set to the manager's "
            f"{len(TARGET_PERFORMANCE_COLUMNS)} columns + {len(CP_WARRANTY_COLUMNS)} CP Warranty columns."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
