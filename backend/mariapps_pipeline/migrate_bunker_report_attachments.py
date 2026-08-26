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
# only touches (vessel_imo, transaction_dt_id) groups that still have >1 row.
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
        groups = defaultdict(list)
        for r in rows:
            # Only rows with a real transaction_dt_id can be reliably grouped —
            # rows without one were already unique under the old fingerprint scheme.
            if r.transaction_dt_id:
                groups[(r.vessel_imo, r.transaction_dt_id)].append(r)

        merged_groups = 0
        deleted_rows = 0
        touched_rows = 0

        for (vessel_imo, txn_id), group_rows in groups.items():
            if len(group_rows) == 1:
                r = group_rows[0]
                if r.attachments is None and r.attachment_file_name:
                    r.attachments = [{
                        "file_name": r.attachment_file_name,
                        "file_size": r.attachment_file_size,
                        "blob_url": r.blob_url,
                        "blob_path": r.blob_path,
                    }]
                    touched_rows += 1
                continue

            # Multiple rows for the same transaction — collapse into the earliest (keeper).
            keeper = group_rows[0]
            others = group_rows[1:]

            attachments = []
            for r in group_rows:
                if r.attachment_file_name or r.blob_path:
                    attachments.append({
                        "file_name": r.attachment_file_name,
                        "file_size": r.attachment_file_size,
                        "blob_url": r.blob_url,
                        "blob_path": r.blob_path,
                    })

            keeper.attachments = attachments or None
            if attachments:
                keeper.attachment_file_name = attachments[0]["file_name"]
                keeper.attachment_file_size = attachments[0]["file_size"]
                keeper.blob_url = attachments[0]["blob_url"]
                keeper.blob_path = attachments[0]["blob_path"]
            keeper.fingerprint = _fingerprint(vessel_imo, txn_id, keeper.bdn_reference_no, keeper.begin_of_bunkering)

            for r in others:
                db.delete(r)
                deleted_rows += 1

            merged_groups += 1
            log.info(f"[MERGE]    {vessel_imo} txn={txn_id}: {len(group_rows)} rows -> 1, "
                      f"{len(attachments)} attachment(s) merged.")

        db.commit()
        log.info(f"✅ Merged {merged_groups} duplicate transaction group(s), "
                 f"deleted {deleted_rows} redundant row(s), "
                 f"backfilled attachments on {touched_rows} single-file row(s).")
    finally:
        db.close()


if __name__ == "__main__":
    _ensure_column()
    _merge_duplicates()
