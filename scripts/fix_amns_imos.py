"""
fix_amns_imos.py
================
One-time migration script to correct the IMO numbers for the three AMNS
vessels in the database.

Background
----------
The Wartsila FOS scraper uses the correct real-world IMO numbers for these
vessels, but the 'vessels' table was seeded with incorrect IMOs.  This
mismatch caused AMNS POLAR, AMNSI MAXIMUS and AMNSI STALLION to be
invisible on the Fleet Status page because the Ozellar fleet filter joins
fleet_status_data.imo -> vessels.imo_number.

Correction map (wrong -> correct)
----------------------------------
  AMNS POLAR     : 9521813 -> 9961609
  AMNSI MAXIMUS  : 9628893 -> 9942768
  AMNSI STALLION : 9628910 -> 9942770

Strategy (no superuser required)
---------------------------------
  1. INSERT a new vessels row with the correct IMO (copy of the old row).
  2. UPDATE all child/FK tables to point to the new IMO.
  3. DELETE the old vessels row (now safe -- nothing references it).

Usage
-----
  python3 scripts/fix_amns_imos.py

Safe to re-run: already-corrected vessels are skipped automatically.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

import psycopg2

# -- Connection settings (read from .env or environment) ----------------------
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "vessel_perf")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASSWORD", "")

# -- IMO corrections: old (wrong) -> new (correct) ----------------------------
IMO_CORRECTIONS = {
    "9521813": "9961609",   # AMNS POLAR
    "9628893": "9942768",   # AMNSI MAXIMUS
    "9628910": "9942770",   # AMNSI STALLION
}

# -- All child tables that reference vessels.imo_number via FK ----------------
CHILD_TABLES = [
    ("analysis_data",             "vessel_imo"),
    ("cp_vessel_description",     "vessel_imo"),
    ("iso19030_results",          "vessel_imo"),
    ("mariapps_bunker_reports",   "vessel_imo"),
    ("mariapps_reports_data",     "vessel_imo"),
    ("noon_report_data",          "vessel_imo"),
    ("raw_mariapps_logs",         "vessel_imo"),
    ("raw_noon_reports",          "vessel_imo"),
    ("vessel_baseline_curves",    "vessel_imo"),
    ("vessel_column_defaults",    "vessel_imo"),
    ("vessel_cp_config",          "vessel_imo"),
    ("vessel_design_data",        "vessel_imo"),
    ("vessel_iso_config",         "vessel_imo"),
    ("vessel_maintenance_events", "vessel_imo"),
    ("vessel_particulars",        "vessel_imo"),
]


def main():
    print("=" * 60)
    print("  AMNS Vessel IMO Correction Script")
    print("=" * 60)
    print(f"  Connecting to {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME} ...")

    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT,
            dbname=DB_NAME, user=DB_USER, password=DB_PASS
        )
    except Exception as e:
        print(f"\n  ERROR: Could not connect to database: {e}")
        sys.exit(1)

    conn.autocommit = False
    cur = conn.cursor()

    try:
        total_updated = 0

        for old_imo, new_imo in IMO_CORRECTIONS.items():

            # -- Check if old IMO still exists --------------------------------
            cur.execute(
                "SELECT imo_number, vessel_id, vessel_name, wni_enabled, mari_enabled, owner_group "
                "FROM vessels WHERE imo_number = %s",
                (old_imo,)
            )
            old_row = cur.fetchone()

            if not old_row:
                cur.execute(
                    "SELECT vessel_name FROM vessels WHERE imo_number = %s", (new_imo,)
                )
                already = cur.fetchone()
                if already:
                    print(f"\n  [SKIP] {already[0]}: already corrected "
                          f"({old_imo} -> {new_imo})")
                else:
                    print(f"\n  [SKIP] IMO {old_imo} not found -- skipping")
                continue

            _, vessel_id, vessel_name, wni_enabled, mari_enabled, owner_group = old_row
            print(f"\n  Fixing {vessel_name}: {old_imo} -> {new_imo}")

            # Step 1: INSERT new parent row with correct IMO
            # (ON CONFLICT DO NOTHING makes re-runs safe)
            cur.execute(
                "INSERT INTO vessels "
                "  (imo_number, vessel_id, vessel_name, wni_enabled, mari_enabled, owner_group) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (imo_number) DO NOTHING",
                (new_imo, vessel_id, vessel_name, wni_enabled, mari_enabled, owner_group)
            )
            print(f"    vessels (INSERT correct IMO) : done")

            # Step 2: UPDATE all child tables -- now the new parent row exists
            for table, col in CHILD_TABLES:
                cur.execute(
                    f"UPDATE {table} SET {col} = %s WHERE {col} = %s",
                    (new_imo, old_imo)
                )
                if cur.rowcount > 0:
                    print(f"    {table:<30}: {cur.rowcount} row(s) re-pointed")
                    total_updated += cur.rowcount

            # Step 3: DELETE old parent row -- safe now, nothing references it
            cur.execute(
                "DELETE FROM vessels WHERE imo_number = %s", (old_imo,)
            )
            print(f"    vessels (DELETE wrong IMO)   : done")
            total_updated += 1

        conn.commit()

        print()
        print("=" * 60)
        if total_updated > 0:
            print(f"  SUCCESS: {total_updated} total row(s) corrected.")
        else:
            print("  No rows updated -- IMOs are already correct.")
        print("=" * 60)

        # -- Final verification ------------------------------------------------
        print("\n  Verifying fleet_status_data link ...")
        cur.execute("""
            SELECT v.vessel_name, fsd.imo, MAX(fsd.scraped_at) AS latest_scrape
            FROM vessels v
            JOIN fleet_status_data fsd ON fsd.imo = v.imo_number
            WHERE v.vessel_name IN ('AMNS POLAR', 'AMNSI MAXIMUS', 'AMNSI STALLION')
            GROUP BY v.vessel_name, fsd.imo
            ORDER BY v.vessel_name
        """)
        rows = cur.fetchall()
        if rows:
            print()
            for r in rows:
                print(f"    {r[0]:<20} IMO: {r[1]}  last scrape: {r[2]}")
            print()
            print("  Fleet Status data is now linked correctly.")
            print("  Run the Wartsila scraper to refresh live positions:")
            print("    python3 -m backend.pipeline.wartsila_scraper")
        else:
            print("  No fleet_status_data rows found yet.")
            print("  Run the Wartsila scraper to populate live positions:")
            print("    python3 -m backend.pipeline.wartsila_scraper")

    except Exception as e:
        conn.rollback()
        print(f"\n  ERROR (rolled back): {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
