# ===========================================================================
# backend/fix_duplicate_raw_and_expanded.py
#
# One-off remediation for the 2026-10 duplicate-raw-row bug (see CLAUDE.md /
# session notes): processor.py (WNI) and mariapps_persistence.py (MariApps)
# used to insert a fresh raw_noon_reports / raw_mariapps_logs row every time
# an already-seen report was re-scraped, instead of skipping the insert.
# backfill_wni()/backfill_mariapps() then replayed EVERY raw row (including
# every duplicate) into expanded_wni_data / expanded_mariapps_data with no
# dedup filter, fanning a single real report out into dozens/hundreds of
# expanded rows and inflating every SUM built from them (distance, fuel,
# hours) by ~100x. Both root causes are already fixed in processor.py /
# mariapps_persistence.py / expander.py — this script cleans up the data
# that was already written before that fix shipped.
#
# What this does, in order:
#   0. VERIFY — confirm analysis_data / noon_report_data / mariapps_report_data
#      were NOT corrupted by this bug (they have their own, separate
#      duplicate guard that returns before writing them — this just proves
#      that guard actually held). Read-only, always runs.
#   1. MARK   — for every fingerprint in raw_noon_reports / raw_mariapps_logs
#      with more than one row, keep the earliest (lowest id) and set
#      is_duplicate = true on the rest. Nothing is deleted — the raw JSON
#      audit trail is preserved, just flagged so later backfills skip it.
#      Idempotent: safe to re-run.
#   2. REBUILD — truncate expanded_wni_data / expanded_mariapps_data and
#      re-run the now-duplicate-aware backfill_wni()/backfill_mariapps() to
#      repopulate them from ONLY the non-duplicate raw rows.
#   3. OP STATUS — re-run the now per-vessel-resilient _backfill_op_status()
#      against the freshly rebuilt (much smaller, clean) tables.
#   4. REPORT — print before/after row counts per table so the fix can be
#      confirmed without a separate manual query.
#
# USAGE:
#   python -m backend.fix_duplicate_raw_and_expanded              # dry run — step 0 + step 1's counts only, no writes
#   python -m backend.fix_duplicate_raw_and_expanded --apply       # actually marks duplicates, truncates, and rebuilds
# ===========================================================================
import argparse
import logging

from sqlalchemy import text

from .database import SessionLocal, engine
from .pipeline.expander import backfill_wni, backfill_mariapps, _backfill_op_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)


def _verify_analysis_tables_clean(db):
    """Read-only sanity check: do analysis_data / noon_report_data /
    mariapps_report_data have more than one row pointing at raw rows that
    share the same fingerprint? If their own duplicate guard worked (it
    returns before these tables are written, independent of the raw-insert
    bug), this should come back empty or near-empty."""
    log.info("=== Step 0: verifying analysis_data / noon_report_data / mariapps_report_data are clean ===")

    wni_dupe_groups = db.execute(text("""
        SELECT r.fingerprint, count(*) AS n
        FROM analysis_data a
        JOIN raw_noon_reports r ON r.id = a.raw_report_id
        WHERE a.source_id = 'wni'
        GROUP BY r.fingerprint HAVING count(*) > 1
        ORDER BY n DESC LIMIT 10
    """)).fetchall()
    log.info(f"analysis_data (wni) rows sharing a duplicated raw fingerprint: {len(wni_dupe_groups)} group(s)"
              + (f" — e.g. {wni_dupe_groups[:3]}" if wni_dupe_groups else " (clean)"))

    noon_dupe_groups = db.execute(text("""
        SELECT r.fingerprint, count(*) AS n
        FROM noon_report_data n
        JOIN raw_noon_reports r ON r.id = n.raw_report_id
        GROUP BY r.fingerprint HAVING count(*) > 1
        ORDER BY n DESC LIMIT 10
    """)).fetchall()
    log.info(f"noon_report_data rows sharing a duplicated raw fingerprint: {len(noon_dupe_groups)} group(s)"
              + (f" — e.g. {noon_dupe_groups[:3]}" if noon_dupe_groups else " (clean)"))

    mariapps_dupe_groups = db.execute(text("""
        SELECT r.fingerprint, count(*) AS n
        FROM mariapps_reports_data m
        JOIN raw_mariapps_logs r ON r.id = m.raw_report_id
        GROUP BY r.fingerprint HAVING count(*) > 1
        ORDER BY n DESC LIMIT 10
    """)).fetchall()
    log.info(f"mariapps_reports_data rows sharing a duplicated raw fingerprint: {len(mariapps_dupe_groups)} group(s)"
              + (f" — e.g. {mariapps_dupe_groups[:3]}" if mariapps_dupe_groups else " (clean)"))

    analysis_mariapps_dupe_groups = db.execute(text("""
        SELECT r.fingerprint, count(*) AS n
        FROM analysis_data a
        JOIN raw_mariapps_logs r ON r.id = a.raw_mariapps_id
        WHERE a.source_id = 'mari_apps'
        GROUP BY r.fingerprint HAVING count(*) > 1
        ORDER BY n DESC LIMIT 10
    """)).fetchall()
    log.info(f"analysis_data (mari_apps) rows sharing a duplicated raw fingerprint: {len(analysis_mariapps_dupe_groups)} group(s)"
              + (f" — e.g. {analysis_mariapps_dupe_groups[:3]}" if analysis_mariapps_dupe_groups else " (clean)"))

    any_dupes = any([wni_dupe_groups, noon_dupe_groups, mariapps_dupe_groups, analysis_mariapps_dupe_groups])
    if any_dupes:
        log.warning(
            "At least one analysis/160-col table has rows built from duplicated raw fingerprints — "
            "the original duplicate guard did NOT fully hold. Investigate before trusting CII/ISO19030/CP "
            "results, not just the Emission Log pages, and widen the fix beyond expanded_* tables."
        )
    else:
        log.info("All analysis/160-col tables are clean — the bug was confined to raw staging + expanded_* tables.")
    return not any_dupes


def _row_counts(db):
    counts = {}
    for label, sql in [
        ("raw_noon_reports (total)", "SELECT count(*) FROM raw_noon_reports"),
        ("raw_noon_reports (is_duplicate=true)", "SELECT count(*) FROM raw_noon_reports WHERE is_duplicate = true"),
        ("raw_mariapps_logs (total)", "SELECT count(*) FROM raw_mariapps_logs"),
        ("raw_mariapps_logs (is_duplicate=true)", "SELECT count(*) FROM raw_mariapps_logs WHERE is_duplicate = true"),
        ("expanded_wni_data", "SELECT count(*) FROM expanded_wni_data"),
        ("expanded_mariapps_data", "SELECT count(*) FROM expanded_mariapps_data"),
    ]:
        counts[label] = db.execute(text(sql)).scalar()
    return counts


def _mark_duplicates(db, table, fingerprint_col="fingerprint"):
    """For every fingerprint with >1 row, keep the earliest id and flag the
    rest is_duplicate = true. Idempotent — only ever moves false/NULL -> true,
    never touches already-flagged rows."""
    result = db.execute(text(f"""
        UPDATE {table} t
        SET is_duplicate = true
        FROM (
            SELECT id, {fingerprint_col},
                   MIN(id) OVER (PARTITION BY {fingerprint_col}) AS keep_id
            FROM {table}
        ) d
        WHERE t.id = d.id
          AND d.id <> d.keep_id
          AND COALESCE(t.is_duplicate, false) = false
    """))
    return result.rowcount


def main(apply: bool):
    db = SessionLocal()
    try:
        clean = _verify_analysis_tables_clean(db)

        log.info("\n=== Before ===")
        for label, n in _row_counts(db).items():
            log.info(f"  {label}: {n}")

        if not apply:
            log.info(
                "\nDry run only (no changes made). Re-run with --apply to mark duplicates, "
                "truncate expanded_wni_data/expanded_mariapps_data, and rebuild them."
            )
            return

        log.info("\n=== Step 1: marking duplicate raw rows ===")
        n_wni = _mark_duplicates(db, "raw_noon_reports")
        n_mariapps = _mark_duplicates(db, "raw_mariapps_logs")
        db.commit()
        log.info(f"Flagged {n_wni} raw_noon_reports rows and {n_mariapps} raw_mariapps_logs rows as is_duplicate=true.")

        log.info("\n=== Step 2: truncating and rebuilding expanded_wni_data / expanded_mariapps_data ===")
        db.execute(text("TRUNCATE TABLE expanded_wni_data"))
        db.execute(text("TRUNCATE TABLE expanded_mariapps_data"))
        db.commit()
        db.close()  # backfill_* take a raw engine, not this session

        backfill_mariapps(engine)
        backfill_wni(engine)

        log.info("\n=== Step 3: rebuilding emissionx_op_status ===")
        _backfill_op_status(engine)

        db = SessionLocal()
        log.info("\n=== After ===")
        for label, n in _row_counts(db).items():
            log.info(f"  {label}: {n}")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually mark duplicates, truncate, and rebuild (default: dry run / report only).")
    args = parser.parse_args()
    main(apply=args.apply)
