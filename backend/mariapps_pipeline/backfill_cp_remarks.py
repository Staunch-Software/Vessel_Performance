"""
One-off historical backfill for the "Remarks" field on MariApps' Position
tab (the per-day CP speed/consumption instruction text — see
pipeline/expander.py's _mariapps_remarks_field and cp/cp_remarks_parser.py).

WHY A SEPARATE SCRIPT, not the normal mariapps_pipeline.py run(): that
pipeline's dedup check (persistence.is_already_processed) SKIPS any log
already in the DB — correct for day-to-day scraping, wrong here. This
script exists specifically to REVISIT logs already ingested before the
scraper captured Remarks, and pull just that one field — not a full 6-tab
re-scrape (only the Position tab is opened per log, far cheaper than a
normal ingest pass).

Idempotent / resumable: only visits logs whose stored raw_json still lacks
Position_Data.Remarks, so re-running after an interruption just picks up
where it left off (already-recovered logs are skipped on the next run).

Usage:
    python -m backend.mariapps_pipeline.backfill_cp_remarks                  # all mari_enabled vessels
    python -m backend.mariapps_pipeline.backfill_cp_remarks "AM TARANG"      # one vessel
    python -m backend.mariapps_pipeline.backfill_cp_remarks "AM TARANG" "AM KIRTI"
"""
import logging
import os
import sys
import time
from datetime import datetime

from playwright.sync_api import sync_playwright
from sqlalchemy import text

from ..config import config
from ..database import engine, get_scrape_vessels, SessionLocal
from ..models import RawMariAppsLog
from .navigator import MariAppsNavigator
from .filter_handler import MariAppsFilterHandler
from .grid_extractor import MariAppsGridExtractor
from .log_tab_handler import MariAppsLogTabHandler
from .detail_extractor import MariAppsDetailExtractor
from .generate_auth import run_automated_login
from ..pipeline.expander import write_expanded_mariapps

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def _normalize_log_date(raw: str) -> str:
    if not raw:
        return raw
    date_part = str(raw).strip().split(" ")[0].strip()
    for fmt in ("%d-%b-%Y", "%d/%b/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_part, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_part


def _vessel_imo_by_name(conn, vessel_name):
    row = conn.execute(
        text("SELECT imo_number FROM vessels WHERE vessel_name = :n"), {"n": vessel_name}
    ).fetchone()
    return row[0] if row else None


def _rows_missing_remarks(conn, vessel_imo):
    """{log_number: (raw_log_id, log_date, log_type, raw_json)} for rows on
    this vessel whose stored raw_json doesn't have Position_Data.Remarks yet."""
    rows = conn.execute(text(
        "SELECT id, log_number, log_date, log_type, raw_json FROM raw_mariapps_logs "
        "WHERE vessel_imo = :imo"
    ), {"imo": vessel_imo}).fetchall()
    out = {}
    for rid, log_number, log_date, log_type, raw_json in rows:
        pos = (raw_json or {}).get("Position_Data") or {}
        if not str(pos.get("Remarks") or "").strip():
            out[str(log_number).strip()] = (rid, log_date, log_type, raw_json)
    return out


def _earliest_log_date(conn):
    row = conn.execute(text(
        "SELECT MIN(log_date) FROM raw_mariapps_logs WHERE log_date IS NOT NULL AND log_date != ''"
    )).fetchone()
    return row[0] if row and row[0] else None


def run(vessel_names=None):
    auth_file = str(config.MARIAPPS_AUTH_JSON)
    if not os.path.exists(auth_file):
        log.warning("auth.json not found! Running login first...")
    run_automated_login()

    all_vessels = vessel_names or (get_scrape_vessels("mari_apps") or [])
    if not all_vessels:
        log.error("No vessels to process (get_scrape_vessels returned nothing and none passed in).")
        return

    with engine.connect() as conn:
        earliest = _earliest_log_date(conn)
    from_date_dt = None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            from_date_dt = datetime.strptime(str(earliest).split(" ")[0], fmt)
            break
        except (ValueError, TypeError):
            continue
    from_date = from_date_dt.strftime("%d-%b-%Y") if from_date_dt else "01-JAN-2026"
    to_date = datetime.now().strftime("%d-%b-%Y")

    log.info("=" * 60)
    log.info("  CP Remarks Historical Backfill — Starting")
    log.info("=" * 60)
    log.info(f"[CONFIG]   Date range   : {from_date} → {to_date}")
    log.info(f"[CONFIG]   Vessels      : {len(all_vessels)} — {', '.join(all_vessels)}")

    headless = os.getenv("MARIAPPS_HEADLESS", "true").lower() != "false"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        # ignore_https_errors: DeploymentVM01's CA trust store is missing the
        # root that signed smartpal.ozellar.com's cert chain (see
        # generate_auth.py's own note on this same issue) — mariapps_pipeline.py
        # already sets this on its equivalent context; this one was missing it,
        # which meant every page.goto() here failed on a TLS handshake error,
        # not an actually-invalid session — surfacing as the same generic
        # "Session invalid" warning and masking the real cause.
        context = browser.new_context(storage_state=auth_file, ignore_https_errors=True)
        main_page = context.new_page()

        navigator = MariAppsNavigator(main_page)
        filter_handler = MariAppsFilterHandler(main_page)
        grid_extractor = MariAppsGridExtractor(main_page)
        tab_handler = MariAppsLogTabHandler(main_page)

        try:
            navigator.navigate_to_log_validation()
        except Exception:
            if sys.stdin and sys.stdin.isatty():
                log.warning("Session invalid. Please log in manually in the browser window.")
                input("Press ENTER after successful login...")
                main_page.context.storage_state(path=auth_file)
                navigator.navigate_to_log_validation()
            else:
                log.error("MariApps session invalid and no terminal available for manual login — aborting.")
                browser.close()
                return

        total_recovered = total_unparsed_pos = total_missing_link = total_errors = 0

        for vessel_index, vessel_name in enumerate(all_vessels, start=1):
            if main_page.is_closed():
                log.error("Main page closed unexpectedly. Aborting.")
                break

            with engine.connect() as conn:
                vessel_imo = _vessel_imo_by_name(conn, vessel_name)
            if not vessel_imo:
                log.warning(f"[{vessel_name}] No vessel_imo found — skipping.")
                continue

            with engine.connect() as conn:
                missing = _rows_missing_remarks(conn, vessel_imo)
            if not missing:
                log.info(f"[{vessel_index}/{len(all_vessels)}] {vessel_name} — nothing missing, skipping.")
                continue

            log.info(f"[{vessel_index}/{len(all_vessels)}] {vessel_name} — {len(missing)} log(s) missing Remarks.")

            status = filter_handler.apply_filters_and_export(vessel_name, from_date, to_date)
            if status != "success":
                log.error(f"[{vessel_name}] Failed to apply filters — skipping vessel.")
                try:
                    main_page.goto(navigator.target_url)
                    time.sleep(2)
                except Exception:
                    break
                continue

            raw_grid_rows = grid_extractor.extract_rows(vessel_name)
            unique_ui_logs = {}
            for row in raw_grid_rows:
                ln = row.get("log_number")
                if ln and ln not in unique_ui_logs:
                    row["log_date"] = _normalize_log_date(row.get("log_date", ""))
                    unique_ui_logs[ln] = row

            recovered = unparsed_pos = missing_link = errors = 0

            for ui_log_num, row_data in unique_ui_logs.items():
                if ui_log_num not in missing:
                    continue  # already has Remarks, or not in our DB at all — not this script's job
                if main_page.is_closed():
                    log.error("Main page closed during processing.")
                    break

                rid, log_date, log_type, raw_json = missing[ui_log_num]

                # Belt-and-suspenders against the popup-leak class of bug fixed in
                # log_tab_handler.py: if anything else ever leaves a stray tab open
                # in this context, close it before opening the next one rather than
                # let extra tabs silently accumulate over hundreds of iterations.
                for stray in list(main_page.context.pages):
                    if stray is not main_page and not stray.is_closed():
                        try:
                            stray.close()
                        except Exception:
                            pass

                detail_page = tab_handler.open_log_tab(row_data)
                if not detail_page:
                    missing_link += 1
                    continue

                try:
                    extractor = MariAppsDetailExtractor(detail_page)
                    position_data = extractor._extract_standard_tab(
                        tab_name="Position", link_selector="a[href='#Position']", pane_selector="div#Position",
                    )
                    remarks = str(position_data.get("Remarks") or "").strip()

                    if not remarks:
                        unparsed_pos += 1
                    else:
                        merged_raw_json = dict(raw_json or {})
                        merged_raw_json["Position_Data"] = {**(merged_raw_json.get("Position_Data") or {}), "Remarks": remarks}

                        # ORM update (not raw SQL) so SQLAlchemy's JSONB adapter
                        # handles serialization — a plain text() UPDATE would need
                        # an explicit ::jsonb cast to avoid a type mismatch.
                        db = SessionLocal()
                        try:
                            db_row = db.query(RawMariAppsLog).filter(RawMariAppsLog.id == rid).first()
                            if db_row:
                                db_row.raw_json = merged_raw_json
                                db.commit()
                        finally:
                            db.close()

                        with engine.connect() as conn:
                            write_expanded_mariapps(conn, rid, vessel_imo, log_date, log_type, ui_log_num, merged_raw_json)
                            conn.commit()
                        recovered += 1
                        log.info(f"  ↳ {ui_log_num}: recovered — {remarks[:70]}{'…' if len(remarks) > 70 else ''}")
                except Exception as e:
                    log.error(f"  ↳ {ui_log_num}: error — {e}")
                    errors += 1
                finally:
                    try:
                        if not detail_page.is_closed():
                            detail_page.close()
                    except Exception:
                        pass
                    time.sleep(0.6)

            log.info(
                f"[{vessel_name}] Recovered: {recovered}  |  Position tab blank: {unparsed_pos}  "
                f"|  Link not found: {missing_link}  |  Errors: {errors}"
            )
            total_recovered += recovered
            total_unparsed_pos += unparsed_pos
            total_missing_link += missing_link
            total_errors += errors

            try:
                main_page.goto(navigator.target_url)
                time.sleep(1.5)
            except Exception:
                break

        main_page.context.storage_state(path=auth_file)
        browser.close()

        log.info("=" * 60)
        log.info("  CP Remarks Historical Backfill — Complete")
        log.info(f"[RESULT]   Recovered           : {total_recovered}")
        log.info(f"[RESULT]   Position tab blank  : {total_unparsed_pos}")
        log.info(f"[RESULT]   Grid link not found : {total_missing_link}")
        log.info(f"[RESULT]   Errors              : {total_errors}")
        log.info("=" * 60)


if __name__ == "__main__":
    run(sys.argv[1:] or None)
