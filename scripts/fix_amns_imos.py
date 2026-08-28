"""
fix_amns_imos.py
================
One-time migration script to correct the IMO numbers for the three AMNS
vessels in the database.

Background
----------
The Wartsila FOS scraper uses the correct real-world IMO numbers for these
vessels, but the `vessels` table was seeded with incorrect IMOs.  This
mismatch caused AMNS POLAR, AMNSI MAXIMUS and AMNSI STALLION to be
invisible on the Fleet Status page because the Ozellar fleet filter joins
fleet_status_data.imo -> vessels.imo_number.

Correction map (wrong -> correct)
----------------------------------
  AMNS POLAR     : 9521813 -> 9961609
  AMNSI MAXIMUS  : 9628893 -> 9942768
  AMNSI STALLION : 9628910 -> 9942770

Usage
-----
  python scripts/fix_amns_imos.py

Run this ONCE on any environment where the wrong IMOs are still present.
The script is safe to re-run -- it will simply report 0 rows updated if the
correction has already been applied.
"""

import sys
import os

# Make sure project root is on the path so we can use backend.database
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
        # Temporarily disable FK trigger checks so we can update the parent
        # (vessels) and all child tables freely within one transaction.
        cur.execute("SET session_replication_role = 'replica'")

        total_updated = 0

        for old_imo, new_imo in IMO_CORRECTIONS.items():
            # Resolve vessel name for display
            cur.execute("SELECT vessel_name FROM vessels WHERE imo_number = %s", (old_imo,))
            row = cur.fetchone()
            if not row:
                # Check if already corrected
                cur.execute("SELECT vessel_name FROM vessels WHERE imo_number = %s", (new_imo,))
                row2 = cur.fetchone()
                if row2:
                    print(f"\n  [SKIP] {row2[0]}: already corrected ({old_imo} -> {new_imo})")
                else:
                    print(f"\n  [SKIP] IMO {old_imo} not found in vessels table")
                continue

            vessel_name = row[0]
            print(f"\n  Fixing {vessel_name}: {old_imo} -> {new_imo}")

            # 1. Update parent table
            cur.execute(
                "UPDATE vessels SET imo_number = %s WHERE imo_number = %s",
                (new_imo, old_imo)
            )
            print(f"    vessels                        : {cur.rowcount} row(s) updated")
            total_updated += cur.rowcount

            # 2. Update all child tables
            for table, col in CHILD_TABLES:
                cur.execute(
                    f"UPDATE {table} SET {col} = %s WHERE {col} = %s",
                    (new_imo, old_imo)
                )
                if cur.rowcount > 0:
                    print(f"    {table:<30}: {cur.rowcount} row(s) updated")
                    total_updated += cur.rowcount

        # Re-enable FK checks then commit
        cur.execute("SET session_replication_role = 'origin'")
        conn.commit()

        print()
        print("=" * 60)
        if total_updated > 0:
            print(f"  SUCCESS: {total_updated} total row(s) updated across all tables.")
        else:
            print("  No rows updated -- IMOs may already be correct.")
        print("=" * 60)

        # -- Final verification ------------------------------------------------
        print("\n  Verifying fleet_status_data match ...")
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
            print("    python -m backend.pipeline.wartsila_scraper")
        else:
            print("  No fleet_status_data rows found yet.")
            print("  Run the Wartsila scraper to populate live positions:")
            print("    python -m backend.pipeline.wartsila_scraper")

    except Exception as e:
        conn.rollback()
        print(f"\n  ERROR (rolled back): {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
