"""
add_emission_log_columns_to_default.py
---------------------------------------
One-off script: adds every Emission Log column — all emissionx_* columns
(fuel-by-grade + Op. Status + the Navigation additions: Voyage No.,
Country/EU Port? From+To, BDN Ref), AND the 13 pre-existing columns that are
dual-tagged into Emission (From/To Port, Lat/Long, Distance, Hours, Speed,
Draft F/A, Cargo OB, ME/AE/Boiler totals) — to the existing Global admin
column default in `vessel_column_defaults`.

Background: is_active=True alone doesn't make a new column show by default —
a user's/admin's saved `visible` list is a fixed snapshot, so a column stays
invisible until explicitly added to it, whether it's brand new (emissionx_*)
or pre-existing but never included in that particular saved snapshot (the
13 dual-tagged fields — same gap hit with the Performance-tab default
columns earlier). This script does that without touching anything else
already in the default.

Safe to re-run — a column already present in `visible` is a no-op.

Run once on production after deploying the expander.py changes and running
the normal Emission Log backfill (which happens automatically on the next
backend restart, gated by _EMISSION_LOG_SENTINEL):

    python add_emission_log_columns_to_default.py
"""

from sqlalchemy import text
from backend.database import SessionLocal
from backend.models import VesselColumnDefault

SOURCE = "mari_apps"

# Pre-existing columns dual-tagged into Emission (see _EMISSION_EXTRA_COLUMNS
# in backend/pipeline/expander.py) — kept in sync manually, small/stable list.
_EMISSION_DUAL_COLUMNS = {
    "VoyageMeta_departure_port_last_leg_operational_LF",
    "VoyageMeta_to_port_operational_LF",
    "VoyageMeta_latitude_operational_LF",
    "VoyageMeta_longitude_operational_LF",
    "Vessel_DOG_dCnt_operational_LF",
    "VoyageMeta_log_durationh_operational_LF",
    "Vessel_SOG_avg_operational_LF",
    "Vessel_Tf_avg_operational_LF",
    "Vessel_Ta_avg_operational_LF",
    "Vessel_Cargo_onboard_operational_LF",
    "ME_FO_mFOCME_dCnt_operational_LF",
    "AE_FO_mFOCAE_dCnt_operational_LF",
    "AuxBoiler_mFOCBL_dCnt_operational_LF",
}


def main():
    db = SessionLocal()
    try:
        new_cols = {
            r[0] for r in db.execute(
                text(
                    "SELECT db_column FROM expanded_column_metadata "
                    "WHERE source = :s AND db_column LIKE 'emissionx_%'"
                ),
                {"s": SOURCE},
            ).fetchall()
        }
        if not new_cols:
            print("No emissionx_* columns found in expanded_column_metadata — "
                  "has the Emission Log migration/backfill run yet?")
            return
        new_cols |= _EMISSION_DUAL_COLUMNS

        rec = db.query(VesselColumnDefault).filter(
            VesselColumnDefault.source == SOURCE,
            VesselColumnDefault.vessel_imo.is_(None),
        ).first()

        if not rec:
            print(f"No global default row exists yet for source={SOURCE} — nothing to update. "
                  "Run set_default_performance_columns.py first if you want a global default seeded.")
            return

        visible = set(rec.column_prefs.get("visible", []))
        before = len(visible)
        visible |= new_cols

        new_prefs = dict(rec.column_prefs)
        new_prefs["visible"] = sorted(visible)
        rec.column_prefs = new_prefs
        db.commit()

        print(f"Done. {SOURCE} global default: {before} -> {len(visible)} visible columns "
              f"({len(new_cols)} total Emission Log columns ensured present: "
              f"{len(new_cols) - len(_EMISSION_DUAL_COLUMNS)} new emissionx_* + "
              f"{len(_EMISSION_DUAL_COLUMNS)} pre-existing dual-tagged).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
