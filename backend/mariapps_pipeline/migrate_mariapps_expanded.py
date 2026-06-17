# ===========================================================================
# migrate_mariapps_expanded.py
#
# WHAT THIS DOES:
#   1. Reads every row from raw_mariapps_logs
#   2. Scans ALL keys inside raw_json (including nested dicts)
#   3. Creates table mariapps_logs_expanded with ONE COLUMN PER KEY
#   4. Fills all rows into the new table
#
# USAGE:
#   python migrate_mariapps_expanded.py
# ===========================================================================

import os
import re
import logging
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker

load_dotenv()

# ============================================================
# YOUR DATABASE URL
# ============================================================
# --- LOCAL (original hardcoded URL — uncomment to use) ---
# DATABASE_URL = "postgresql://postgres:root@localhost:5432/noon_reports_db"
# --- VM / CROSS-PLATFORM (reads DATABASE_URL from .env) ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:root@localhost:5432/vessel_perf")

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)

engine        = create_engine(DATABASE_URL)
SessionLocal  = sessionmaker(bind=engine)


# ============================================================
# HELPERS
# ============================================================

def to_col_name(key: str) -> str:
    """
    Convert any raw_json key into a safe postgres column name.
    Examples:
      'Cargo On Board'                 -> cargo_on_board
      'AE Running Hours - No 1'        -> ae_running_hours_no_1
      'Fuel Oil::Main Engine::HFO'     -> fuel_oil_main_engine_hfo
      'Latitude Degree'                -> latitude_degree
    """
    s = str(key)
    s = s.replace("::", "_").replace("-", "_").replace(" ", "_")
    s = re.sub(r"[^a-zA-Z0-9_]", "", s)
    s = re.sub(r"_+", "_", s).strip("_").lower()
    return s or "unknown_field"


def flatten(raw_json: dict) -> dict:
    """
    Completely flatten raw_json.
    - Top-level scalars  (log_number, vessel, log_date …) → column directly
    - Top-level dicts    (Position_Data, KPI_Data …)      → each inner key
                                                             becomes its OWN column
    - No prefixes. No grouping. 1 key = 1 column.
    """
    result = {}

    def _walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                col = to_col_name(k)
                if isinstance(v, dict):
                    # one more level deep (e.g. nested section inside a section)
                    _walk(v)
                else:
                    result[col] = v

    for key, value in raw_json.items():
        if isinstance(value, dict):
            _walk(value)           # flatten the section's contents directly
        else:
            result[to_col_name(key)] = value   # top-level scalar

    return result


# ============================================================
# STEP 1 — scan every row to discover ALL column names
# ============================================================

def discover_all_columns(db) -> list:
    log.info("Scanning all rows to discover every key inside raw_json ...")
    rows = db.execute(
        text("SELECT raw_json FROM raw_mariapps_logs WHERE raw_json IS NOT NULL")
    )
    all_cols = set()
    count = 0
    for (raw_json,) in rows:
        flat = flatten(raw_json)
        all_cols.update(flat.keys())
        count += 1
    log.info(f"  Scanned {count} rows — found {len(all_cols)} unique columns.")
    return sorted(all_cols)


# ============================================================
# STEP 2 — drop old table if exists, create fresh one
# ============================================================

def create_expanded_table(db, columns: list):
    insp = inspect(engine)
    if "mariapps_logs_expanded" in insp.get_table_names():
        log.info("Dropping existing mariapps_logs_expanded ...")
        db.execute(text("DROP TABLE mariapps_logs_expanded"))
        db.commit()

    col_defs = ",\n    ".join(f'"{c}" TEXT' for c in columns)
    create_sql = f"""
    CREATE TABLE mariapps_logs_expanded (
        id               SERIAL PRIMARY KEY,
        raw_mariapps_id  INTEGER UNIQUE,
        vessel_imo       VARCHAR(20),
        created_at       TIMESTAMP DEFAULT NOW(),
        {col_defs}
    )
    """
    db.execute(text(create_sql))
    db.commit()
    log.info(f"Table mariapps_logs_expanded created with {len(columns)} columns.")


# ============================================================
# STEP 3 — insert every row
# ============================================================

def migrate_rows(db, all_columns: list, batch_size: int = 200):
    col_set = set(all_columns)
    total   = db.execute(text("SELECT COUNT(*) FROM raw_mariapps_logs")).scalar()
    log.info(f"Inserting {total} rows ...")

    processed = errors = 0
    offset = 0

    while True:
        rows = db.execute(
            text("""
                SELECT id, vessel_imo, raw_json
                FROM raw_mariapps_logs
                ORDER BY id
                LIMIT :lim OFFSET :off
            """),
            {"lim": batch_size, "off": offset}
        ).fetchall()

        if not rows:
            break

        for (raw_id, vessel_imo, raw_json) in rows:
            try:
                if not raw_json:
                    continue

                flat = flatten(raw_json)

                # Build the data dict — only columns that exist in the table
                data = {}
                for k, v in flat.items():
                    if k in col_set:
                        data[k] = str(v) if v is not None else None

                data["raw_mariapps_id"] = raw_id
                data["vessel_imo"]      = vessel_imo
                data["created_at"]      = datetime.utcnow().isoformat()

                # sqlalchemy bind params cannot have special characters
                # so we map each column name to a safe param name
                col_to_param = {}
                for col in data.keys():
                    safe = re.sub(r"[^a-zA-Z0-9]", "_", col)
                    col_to_param[col] = safe

                cols_sql = ", ".join(f'"{c}"' for c in data.keys())
                vals_sql = ", ".join(f":{col_to_param[c]}" for c in data.keys())

                # Build ON CONFLICT update clause (skip PK and raw_mariapps_id)
                update_parts = []
                for c in data.keys():
                    if c not in ("raw_mariapps_id", "id", "created_at"):
                        update_parts.append(f'"{c}" = EXCLUDED."{c}"')

                sql = f"""
                    INSERT INTO mariapps_logs_expanded ({cols_sql})
                    VALUES ({vals_sql})
                    ON CONFLICT (raw_mariapps_id) DO UPDATE SET
                    {", ".join(update_parts)}
                """

                # Rebuild params with safe names
                safe_data = {col_to_param[c]: v for c, v in data.items()}
                db.execute(text(sql), safe_data)
                processed += 1

            except Exception as e:
                log.error(f"  ERROR row id={raw_id}: {e}")
                errors += 1

        db.commit()
        offset += batch_size
        log.info(f"  {min(offset, total)}/{total} rows done | saved={processed} errors={errors}")

    return processed, errors


# ============================================================
# MAIN
# ============================================================

def run():
    log.info("=" * 60)
    log.info("  mariapps_logs_expanded  —  Migration Starting")
    log.info("=" * 60)

    db = SessionLocal()
    try:
        all_columns = discover_all_columns(db)
        create_expanded_table(db, all_columns)
        processed, errors = migrate_rows(db, all_columns)

        log.info("=" * 60)
        log.info(f"  DONE — Rows saved : {processed}  |  Errors : {errors}")
        log.info(f"  Total columns     : {len(all_columns)}")
        log.info("=" * 60)

    finally:
        db.close()


if __name__ == "__main__":
    run()