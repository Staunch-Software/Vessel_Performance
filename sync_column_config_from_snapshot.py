"""
sync_column_config_from_snapshot.py
------------------------------------
One-off script: applies the curated Configure Columns state (which column
column-config admin work was done against a database that never made it to
production) — `is_active` flags, the built-in Performance/Emission
calculation categories, their column lists/order, and the "All" mode's
category display order — from `column_config_snapshot.json` onto whichever
database this is run against.

Background: `ColumnConfigPage.jsx` (the "Configure Columns" 3-section admin
page) reads/writes `expanded_column_metadata.is_active`,
`calculation_categories`, `calculation_category_columns`, and
`category_order`. That curated state (only ~165/1032 MariApps columns
active; the manager-approved Performance/Emission column lists and their
order) was built up locally and never applied to production — production's
own history predates ColumnConfigPage and instead has data in the OLD
ColumnPicker-era `vessel_column_defaults` table via
`set_default_performance_columns.py` / `add_emission_log_columns_to_default.py`,
which the currently-deployed frontend no longer reads at all. This script
brings production's ColumnConfigPage-backing tables in line with the
already-correct local state instead.

What it does, safely and idempotently:
  1. `is_active` — for every (source, db_column) row in the snapshot, sets
     expanded_column_metadata.is_active to match. Rows not present in the
     snapshot (e.g. a column that exists on this DB but not the source DB)
     are left untouched.
  2. Categories — ensures each snapshot category (source, name, is_builtin)
     exists in calculation_categories (creates if missing; does not delete
     any extra admin-created category already on this DB).
  3. Category columns — REPLACES the full column list for each snapshot
     category (deletes existing calculation_category_columns rows for that
     category, inserts the snapshot's rows) so re-running always converges
     to exactly the snapshot state for Performance/Emission.
  4. category_order — upserts sort_order per (source, category) to match
     the snapshot; does not remove any extra category present only on this
     DB (e.g. one added by a local admin after the snapshot was taken).

Safe to re-run — every step is upsert/replace, not additive-only.

Run once per environment that needs this (production):

    python sync_column_config_from_snapshot.py
"""

import json
from pathlib import Path

from sqlalchemy import text

from backend.database import SessionLocal
from backend.models import CalculationCategory, CalculationCategoryColumn, CategoryOrder

SNAPSHOT_PATH = Path(__file__).parent / "column_config_snapshot.json"


def main():
    with open(SNAPSHOT_PATH) as f:
        data = json.load(f)

    db = SessionLocal()
    try:
        # ── 1. is_active ────────────────────────────────────────────────
        updated = 0
        for row in data["is_active"]:
            res = db.execute(
                text(
                    "UPDATE expanded_column_metadata SET is_active = :active "
                    "WHERE source = :source AND db_column = :col"
                ),
                {"active": row["is_active"], "source": row["source"], "col": row["db_column"]},
            )
            updated += res.rowcount
        db.commit()
        print(f"is_active: {updated} rows updated ({len(data['is_active'])} in snapshot).")

        # ── 2. Categories (create if missing) ──────────────────────────
        cat_id_by_key = {}
        created = 0
        for cat in data["categories"]:
            rec = db.query(CalculationCategory).filter(
                CalculationCategory.source == cat["source"],
                CalculationCategory.name == cat["name"],
            ).first()
            if not rec:
                rec = CalculationCategory(
                    source=cat["source"], name=cat["name"], is_builtin=cat["is_builtin"]
                )
                db.add(rec)
                db.flush()
                created += 1
            cat_id_by_key[(cat["source"], cat["name"])] = rec.id
        db.commit()
        print(f"categories: {created} created, {len(data['categories'])} total in snapshot.")

        # ── 3. Category columns (replace per category) ─────────────────
        by_cat = {}
        for cc in data["category_columns"]:
            by_cat.setdefault((cc["source"], cc["category"]), []).append(cc)

        total_cols = 0
        for (source, category), cols in by_cat.items():
            cat_id = cat_id_by_key.get((source, category))
            if cat_id is None:
                rec = db.query(CalculationCategory).filter(
                    CalculationCategory.source == source,
                    CalculationCategory.name == category,
                ).first()
                if not rec:
                    print(f"  SKIP {source}/{category}: category not found even after step 2 — unexpected.")
                    continue
                cat_id = rec.id

            db.query(CalculationCategoryColumn).filter(
                CalculationCategoryColumn.calculation_category_id == cat_id
            ).delete()
            for cc in cols:
                db.add(CalculationCategoryColumn(
                    calculation_category_id=cat_id,
                    db_column=cc["db_column"],
                    sort_order=cc["sort_order"],
                ))
            total_cols += len(cols)
        db.commit()
        print(f"category_columns: {total_cols} rows written across {len(by_cat)} categories.")

        # ── 4. category_order (upsert) ──────────────────────────────────
        order_updated = 0
        for co in data["category_order"]:
            rec = db.query(CategoryOrder).filter(
                CategoryOrder.source == co["source"],
                CategoryOrder.category == co["category"],
            ).first()
            if rec:
                rec.sort_order = co["sort_order"]
            else:
                db.add(CategoryOrder(
                    source=co["source"], category=co["category"], sort_order=co["sort_order"]
                ))
            order_updated += 1
        db.commit()
        print(f"category_order: {order_updated} rows upserted.")

        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
