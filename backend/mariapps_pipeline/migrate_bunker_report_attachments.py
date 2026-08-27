# ===========================================================================
# One-off migration — run manually, once, after pulling the "one row per
# transaction" change to bunker_report_scraper.py.
#
# Problem this fixes: the original scraper saved one MariAppsBunkerReport row
# PER ATTACHMENT FILE, so a transaction with 3 files (BDN + Note of Protest +
# LOP) showed up as 3 rows with the same port/BDN/quantity repeated — which
# read as duplicated data (confirmed live for AM UMANG transactions
# 123/126/127). The scraper now saves one row per transaction with an
# `attachments` JSONB list, but:
#   1. init_db()'s create_all() does NOT add new columns to an EXISTING table
#      (it only creates missing tables), so the server's mariapps_bunker_reports
#      table needs `attachments` added manually.
#   2. The old duplicate-per-file rows already sitting in the table need to be
#      collapsed into one row each, with their files merged into `attachments`.
#
# Safe to run multiple times — step 1 uses ADD COLUMN IF NOT EXISTS, and step 2
# recomputes the canonical fingerprint for every row (not just rows already in
# a duplicate group) and merges any that collide.
#
# v2 fix (confirmed live: AM TARANG had 30 rows in the DB for a vessel that
# only has 15 on MariApps' own grid — exactly doubled): v1 only recomputed
# fingerprint for rows it found sitting in an already-duplicate group. Rows
# left over from the earlier "one row per file" scraper that happened to NOT
# collide with anything else (AM TARANG's debug-test rows were 1 file per
# transaction, so nothing about them looked like a duplicate) kept their OLD
# fingerprint. The next full scrape then computed the NEW fingerprint format
# for the same transactions, didn't recognize the old rows as already-saved,
# and inserted a second full set. v2 recomputes+merges by the canonical
# fingerprint for EVERY row, closing that gap regardless of group size.
#
# Usage (from Data_ingestion_pipeline/):
#   python -m backend.mariapps_pipeline.migrate_bunker_report_attachments
# ===========================================================================
import logging
from collections import defaultdict

from sqlalchemy import text

from ..database import engine, SessionLocal
from ..models import MariAppsBunkerReport
from .bunker_report_scraper import _fingerprint

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def _ensure_column():
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE mariapps_bunker_reports ADD COLUMN IF NOT EXISTS attachments JSONB"
        ))
        conn.commit()
    log.info("✅ attachments column present on mariapps_bunker_reports.")


def _merge_duplicates():
    db = SessionLocal()
    try:
        rows = db.query(MariAppsBunkerReport).order_by(MariAppsBunkerReport.id.asc()).all()

        # Group by the CANONICAL fingerprint every row would get if scraped fresh
        # right now — not by transaction_dt_id alone — so rows carrying a stale
        # fingerprint from an older code version still land in the same bucket as
        # their up-to-date counterpart.
        groups = defaultdict(list)
        for r in rows:
            canonical_fp = _fingerprint(r.vessel_imo, r.transaction_dt_id, r.bdn_reference_no, r.begin_of_bunkering)
            groups[canonical_fp].append(r)

        merged_groups = 0
        deleted_rows = 0
        restamped = 0

        for canonical_fp, group_rows in groups.items():
            # Prefer a row that's already in the new one-row-per-transaction shape
            # (has an `attachments` list) as the keeper, over an older leftover row
            # from the "one row per file" scraper — falls back to the lowest id.
            keeper = next((r for r in group_rows if r.attachments), group_rows[0])
            others = [r for r in group_rows if r is not keeper]

            attachments = []
            seen_paths = set()
            for r in group_rows:
                # Prefer the row's own `attachments` list (new-format rows already
                # have it); fall back to the singular columns (old-format rows).
                candidates = r.attachments if r.attachments else (
                    [{"file_name": r.attachment_file_name, "file_size": r.attachment_file_size,
                      "blob_url": r.blob_url, "blob_path": r.blob_path}]
                    if (r.attachment_file_name or r.blob_path) else []
                )
                for a in candidates:
                    key = a.get("blob_path") or a.get("file_name")
                    if key and key not in seen_paths:
                        seen_paths.add(key)
                        attachments.append(a)

            keeper.attachments = attachments or None
            if attachments:
                keeper.attachment_file_name = attachments[0].get("file_name")
                keeper.attachment_file_size = attachments[0].get("file_size")
                keeper.blob_url = attachments[0].get("blob_url")
                keeper.blob_path = attachments[0].get("blob_path")

            # CONFIRMED real bug: deleting `others` and restamping `keeper.fingerprint`
            # in the same flush can collide — Postgres checks the UNIQUE constraint
            # immediately (not deferred), and SQLAlchemy's unit-of-work flushes ALL
            # pending UPDATEs before any DELETEs. When `others` already holds the
            # canonical fingerprint value (a fresh new-format row) and `keeper` is
            # being restamped to that same value, the UPDATE fires before the
            # DELETE physically frees it up -> UniqueViolation. Flush the deletes
            # first, per group, before touching keeper.fingerprint.
            for r in others:
                db.delete(r)
                deleted_rows += 1
            if others:
                db.flush()

            if keeper.fingerprint != canonical_fp:
                keeper.fingerprint = canonical_fp
                restamped += 1

            if others:
                merged_groups += 1
                log.info(f"[MERGE]    {keeper.vessel_imo} txn={keeper.transaction_dt_id}: "
                          f"{len(group_rows)} rows -> 1, {len(attachments)} attachment(s) merged.")

        db.commit()
        log.info(f"✅ Merged {merged_groups} duplicate transaction group(s), "
                 f"deleted {deleted_rows} redundant row(s), "
                 f"restamped {restamped} row(s) with a stale fingerprint.")
    finally:
        db.close()


if __name__ == "__main__":
    _ensure_column()
    _merge_duplicates()
