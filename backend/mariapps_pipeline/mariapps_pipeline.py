# ===========================================================================
# backend/mariapps_pipeline/mariapps_pipeline.py
# ===========================================================================

import logging
import time
import os
from datetime import datetime
from playwright.sync_api import sync_playwright

# Internal Imports (Adjusted for your folder structure)
from ..config import config
from .navigator import MariAppsNavigator
from .filter_handler import MariAppsFilterHandler
from .grid_extractor import MariAppsGridExtractor
from .log_tab_handler import MariAppsLogTabHandler
from .header_form_scanner import MariAppsHeaderScanner
from .detail_extractor import MariAppsDetailExtractor
from .mariapps_persistence import MariAppsPersistenceHandler
from .mariapps_exporter import export_analysis_data

# --- NEAT LOGGER CONFIGURATION ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
VESSEL_LIST = [
    "AM KIRTI",
    "AM TARANG", "AM UMANG",
    "AMNS POLAR", "AMNS TUFMAX",
    "AMNSI STALLION", "GCL FOS",
    "GCL GANGA",
    "GCL TAPI",
    "GCL NARMADA",
    "GCL SABARMATI", "GCL SARASWATI",
    "AMNSI MAXIMUS", "OZELLAR OFFICE", "GCL YAMUNA",
]

# --- Previous ranges (uncomment to reuse) ---
# FROM_DATE = "31-JAN-2026"; TO_DATE = "01-MAR-2026"
# FROM_DATE = "01-APR-2026"; TO_DATE = datetime.now().strftime("%d-%b-%Y")
# FROM_DATE = "01-JAN-2026"; TO_DATE = "01-APR-2026"
FROM_DATE = "01-JUN-2026"
TO_DATE = datetime.now().strftime("%d-%b-%Y")   # today (dynamic)

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _normalize_log_date(raw: str) -> str:
    if not raw:
        return raw
    date_part = str(raw).strip().split(' ')[0].strip()
    for fmt in ("%d-%b-%Y", "%d/%b/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_part, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_part

def _build_excel_index(excel_data_list: list) -> dict:
    index = {}
    for row in excel_data_list:
        log_key = next(
            (k for k in row.keys() if "log" in k.lower() and "num" in k.lower()), None
        )
        if log_key:
            ln = str(row[log_key]).strip()
            if ln:
                index[ln] = row
    return index

# ---------------------------------------------------------------------------
# MAIN PIPELINE RUNNER
# ---------------------------------------------------------------------------

def run():
    pipeline_start = datetime.now()

    log.info("=" * 60)
    log.info("  MariApps Data Ingestion Pipeline — Starting")
    log.info("=" * 60)
    log.info(f"[CONFIG]   Date range   : {FROM_DATE}  →  {TO_DATE}")
    log.info(f"[CONFIG]   Vessels      : {len(VESSEL_LIST)}")

    # Database initialization (Uncomment if you have an init_db function)
    # from ..database import init_db
    # init_db()
    # log.info("[DB]       Database ready.")

    auth_file = str(config.MARIAPPS_AUTH_JSON)

    # --- LOCAL (original — uncomment to always show the browser window) ---
    # headless = False
    # --- VM / CROSS-PLATFORM: env var, defaults True (no display on server); set MARIAPPS_HEADLESS=false locally ---
    headless = os.getenv("MARIAPPS_HEADLESS", "true").lower() != "false"

    with sync_playwright() as p:
        log.info("[BROWSER]  Launching Chromium browser (headless=%s)...", headless)
        browser = p.chromium.launch(headless=headless)

        log.info("[AUTH]     Restoring authentication session...")
        context = browser.new_context(storage_state=auth_file)
        main_page = context.new_page()
        log.info("[AUTH]     Authentication successful.")

        navigator      = MariAppsNavigator(main_page)
        filter_handler = MariAppsFilterHandler(main_page)
        grid_extractor = MariAppsGridExtractor(main_page)
        tab_handler    = MariAppsLogTabHandler(main_page)
        persistence    = MariAppsPersistenceHandler()
        header_scanner = MariAppsHeaderScanner(main_page)

        log.info("[NAV]      Navigating to MariApps Log Validation page...")
        try:
            navigator.navigate_to_log_validation()
            log.info("[NAV]      Page loaded — login verified successfully.")
        except Exception:
            log.warning("[NAV]      Session expired. Please login manually in the browser window.")
            print("\n==================================================")
            print("ACTION REQUIRED:")
            print("1. Log in to MariApps manually in the open browser.")
            print("2. Once Dashboard is visible, press ENTER.")
            print("==================================================\n")
            input("Press ENTER after successful login...")
            main_page.context.storage_state(path=auth_file)
            log.info("[AUTH]     New session saved.")
            try:
                navigator.navigate_to_log_validation()
            except Exception as e2:
                log.error(f"[NAV]      Login failed again: {e2}")
                browser.close()
                return

        log.info("-" * 60)

        total_processed = total_skipped = total_errors = 0

        for vessel_index, vessel_name in enumerate(VESSEL_LIST, start=1):
            if main_page.is_closed():
                log.error("[BROWSER]  Main page closed unexpectedly. Aborting pipeline.")
                break

            log.info(f"[VESSEL]   [{vessel_index}/{len(VESSEL_LIST)}] Processing : {vessel_name}")
            log.info(f"[FILTER]   Applying filters  : {FROM_DATE} → {TO_DATE}")

            status = filter_handler.apply_filters_and_export(vessel_name, FROM_DATE, TO_DATE)
            if status != "success":
                log.error(f"[FILTER]   Failed to apply filters for '{vessel_name}'. Skipping.")
                try:
                    main_page.goto(navigator.target_url)
                    time.sleep(2)
                except Exception:
                    break
                continue

            log.info("[EXPORT]   Downloading Excel export...")
            target_frame = filter_handler._get_active_frame()

            excel_data_list = []
            if target_frame:
                excel_data_list = filter_handler.download_grid_data(target_frame)

            if not excel_data_list:
                log.warning(f"[EXPORT]   No records found for '{vessel_name}'. Skipping.")
                try:
                    main_page.goto(navigator.target_url)
                    time.sleep(2)
                except Exception:
                    break
                continue

            log.info(f"[EXPORT]   {len(excel_data_list)} record(s) downloaded.")
            excel_index = _build_excel_index(excel_data_list)

            log.info("[GRID]     Extracting UI grid rows...")
            raw_grid_rows = grid_extractor.extract_rows(vessel_name)

            unique_ui_logs = {}
            for row in raw_grid_rows:
                ln = row.get("log_number")
                if ln and ln not in unique_ui_logs:
                    row["log_date"] = _normalize_log_date(row.get("log_date", ""))
                    unique_ui_logs[ln] = row
            grid_rows = list(unique_ui_logs.values())

            log.info(f"[GRID]     UI rows: {len(grid_rows)}  |  Excel records: {len(excel_data_list)}")
            if len(excel_data_list) > len(grid_rows):
                log.warning(
                    f"[GRID]     Mismatch — {len(excel_data_list) - len(grid_rows)} record(s) "
                    f"in Excel not visible in UI grid (virtual scroll limitation)."
                )

            processed = skipped = errors = 0

            for row_data in grid_rows:
                if main_page.is_closed():
                    log.error("[BROWSER]  Main page closed during log processing.")
                    break

                ui_log_num = str(row_data.get("log_number", "")).strip()
                log_date   = row_data.get("log_date", "")

                if not ui_log_num:
                    continue

                if persistence.is_already_processed(ui_log_num, vessel_name, log_date):
                    log.info(f"[SKIP]     Log {ui_log_num} — already in database.")
                    skipped += 1
                    continue

                log.info(f"[FETCH]    Log {ui_log_num}  ({log_date}) — opening detail page...")
                matching_excel_row = excel_index.get(ui_log_num, {})

                detail_page = tab_handler.open_log_tab(row_data)
                if not detail_page:
                    log.error(f"[FETCH]    Log {ui_log_num} — failed to open detail tab.")
                    errors += 1
                    continue

                detail_page_closed = False
                try:
                    if detail_page.is_closed():
                        continue

                    header_data = header_scanner.scan(detail_page)
                    detail_extractor = MariAppsDetailExtractor(detail_page)
                    all_tab_data = detail_extractor.extract_details()

                    log.info(
                        f"[EXTRACT]  Log {ui_log_num} — "
                        f"Position:{len(all_tab_data.get('Position', {}))} "
                        f"Operation:{len(all_tab_data.get('Operation', {}))} "
                        f"Consumption:{len(all_tab_data.get('Consumption', {}))} "
                        f"Performance:{len(all_tab_data.get('Performance', {}))} "
                        f"Machinery:{len(all_tab_data.get('Machinery', {}))} "
                        f"KPI:{len(all_tab_data.get('KPI', {}))} fields."
                    )

                    try:
                        if not detail_page.is_closed():
                            detail_page.close()
                            detail_page_closed = True
                    except Exception:
                        detail_page_closed = True

                    full_json_payload = {
                        "log_number":         ui_log_num,
                        "vessel":             vessel_name,
                        "log_date":           log_date,
                        "Excel_Data":         matching_excel_row,
                        "Header_Data":        header_data,
                        "Position_Data":      all_tab_data.get("Position", {}),
                        "Operation_Data":     all_tab_data.get("Operation", {}),
                        "Consumption_Data":   all_tab_data.get("Consumption", {}),
                        "Performance_Data":   all_tab_data.get("Performance", {}),
                        "Machinery_Data":     all_tab_data.get("Machinery", {}),
                        "KPI_Data":           all_tab_data.get("KPI", {}),
                    }

                    persistence.save_log(
                        row_data=full_json_payload,
                        excel_data=matching_excel_row,
                        header_data=header_data,
                        tab_data=all_tab_data
                    )
                    log.info(f"[SAVE]     Log {ui_log_num} — saved successfully.")
                    processed += 1

                except Exception as e:
                    log.error(f"[ERROR]    Log {ui_log_num} — {e}")
                    errors += 1
                finally:
                    if not detail_page_closed:
                        try:
                            if detail_page and not detail_page.is_closed():
                                detail_page.close()
                        except Exception:
                            pass

                time.sleep(0.8)

            total_processed += processed
            total_skipped   += skipped
            total_errors    += errors

            log.info(
                f"[SUMMARY]  {vessel_name} — "
                f"Saved: {processed}  |  Skipped: {skipped}  |  Errors: {errors}"
            )
            log.info("-" * 60)

            try:
                main_page.goto(navigator.target_url)
                time.sleep(1.5)
            except Exception:
                break

        # Save session state at the end to keep login fresh
        main_page.context.storage_state(path=auth_file)
        browser.close()
        log.info("[BROWSER]  Browser closed.")
        log.info("[EXPORT]   Exporting analysis_data to Excel...")
        try:
            export_path = export_analysis_data(
                from_date=datetime.strptime(FROM_DATE, "%d-%b-%Y").strftime("%Y-%m-%d"),
                to_date=datetime.strptime(TO_DATE, "%d-%b-%Y").strftime("%Y-%m-%d"),
            )
            if export_path:
                log.info(f"[EXPORT]   ✅ Excel ready: {export_path}")
        except Exception as export_err:
            log.error(f"[EXPORT]   ❌ Export failed: {export_err}")

        elapsed_str = str(datetime.now() - pipeline_start).split('.')[0]

        elapsed_str = str(datetime.now() - pipeline_start).split('.')[0]

        log.info("=" * 60)
        log.info("  MariApps Data Ingestion Pipeline — Complete")
        log.info("=" * 60)
        log.info(f"[RESULT]   Date range   : {FROM_DATE} → {TO_DATE}")
        log.info(f"[RESULT]   Vessels      : {len(VESSEL_LIST)}")
        log.info(f"[RESULT]   Total saved  : {total_processed}")
        log.info(f"[RESULT]   Total skipped: {total_skipped}")
        log.info(f"[RESULT]   Total errors : {total_errors}")
        log.info(f"[RESULT]   Time elapsed : {elapsed_str}")
        log.info("=" * 60)

if __name__ == "__main__":
    run()