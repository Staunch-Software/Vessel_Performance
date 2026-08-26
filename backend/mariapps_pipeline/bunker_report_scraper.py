# ===========================================================================
# backend/mariapps_pipeline/bunker_report_scraper.py
#
# Scrapes MariApps' smartOps Basic > Reports > Bunker Report page — a
# separate module from the Logs & Events page the rest of this package
# scrapes. Pulls bunker delivery records (fuel grade, quantity, density,
# viscosity, BDN reference) and, for rows that have one, downloads the
# attached Bunker Delivery Note PDF and uploads it to Azure Blob Storage.
#
# Confirmed working end-to-end (2026-08-26) against real data for GCL SABARMATI:
# 13/13 bunker transactions extracted correctly (real BDN references, real
# transactionDtId), 11/13 attachments downloaded and uploaded to Azure Blob
# Storage with zero errors. See the locked+scrollable table split and the
# hardcoded field-index map in _extract_grid_rows for why this couldn't be
# done via header-text column mapping (the header <th> layout doesn't
# correspond 1:1 to the body <td> layout in this grid).
# ===========================================================================
import hashlib
import logging
import os
import time
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from ..config import config
from ..database import SessionLocal, get_scrape_vessels
from ..models import Vessel, MariAppsBunkerReport
from .blob_storage import upload_bunker_attachment

log = logging.getLogger(__name__)

# Fixed start date per the client's request; end date is always "today" so
# every run re-scans the whole window — fingerprint dedup (see below) is what
# actually keeps re-runs cheap, same convention as the rest of the pipeline.
FROM_DATE = "01-Jul-2025"


def _to_kendo_date(dt: datetime) -> str:
    """MariApps date fields display as e.g. '01-Jul-2025' — match that format
    when typing into the filter inputs."""
    return dt.strftime("%d-%b-%Y")


def _fingerprint(vessel_imo: str, transaction_dt_id: str, bdn_reference_no: str, file_name: str) -> str:
    """Prefers MariApps' own internal transactionDtId (unique per grid row) when
    present — confirmed present in the live grid. Falls back to the old composite
    key only if transactionDtId is ever missing, but that fallback is known-weak
    (BDN reference is blank for non-'Bunkering' transaction types, and file_name is
    blank whenever there's no attachment or the download failed) — a first live run
    without transactionDtId capture collapsed 286 distinct rows down to 83 saved
    because of exactly this collision."""
    if transaction_dt_id:
        # file_name still included so multiple attachments on the SAME row (rare, but
        # possible) don't collapse into one another.
        raw = f"{vessel_imo}|txn:{transaction_dt_id}|{file_name or ''}"
    else:
        raw = f"{vessel_imo}|{bdn_reference_no or ''}|{file_name or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _num(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# PAGE INTERACTIONS
# ---------------------------------------------------------------------------

def _select_vessel(page, vessel_name: str):
    """Same top-nav vessel-switcher widget used on the Log Validation page
    (filter_handler.py) — confirmed shared across MariApps pages."""
    vessel_input = page.locator("input[aria-owns='vesselSearchBox_listbox']").first
    vessel_input.wait_for(state="visible", timeout=15000)
    vessel_input.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    vessel_input.press_sequentially(vessel_name, delay=100)
    time.sleep(0.5)  # let the Kendo filter/re-render settle before clicking the option —
    # a real run hit "<ul> intercepts pointer events" on GCL SABARMATI, i.e. the list was
    # still animating/re-rendering under the click.
    option = page.locator(f"ul#vesselSearchBox_listbox li:has-text('{vessel_name}')").first
    try:
        option.click(timeout=10000)
    except Exception:
        # Fall back to a forced click (skips the actionability/stability checks) if the
        # list is still intercepting pointer events after the extra settle time.
        option.click(force=True, timeout=5000)
    time.sleep(1.0)


def _set_date_range_and_search(page, from_date_str: str, to_date_str: str):
    """Sets From Date / To Date and clicks the search (magnifying-glass)
    button. [SELECTOR] first-pass guess: located by the nearest label text
    since the actual input id is unknown ahead of time — if this breaks,
    inspect the real input id (like txtFromDate/txtToDate on the Log
    Validation page) and swap to an id selector instead."""
    from_input = page.locator("label:has-text('From Date')").locator("xpath=following::input[1]").first
    to_input   = page.locator("label:has-text('To Date')").locator("xpath=following::input[1]").first

    for inp, val in [(from_input, from_date_str), (to_input, to_date_str)]:
        inp.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        inp.type(val, delay=50)
        page.keyboard.press("Tab")
        time.sleep(0.3)

    # [SELECTOR] the search trigger next to the date fields (magnifying-glass icon).
    search_btn = page.locator("button:has(.k-i-search)").first
    if search_btn.count() == 0:
        search_btn = page.get_by_role("button").filter(has=page.locator("svg, i")).first
    search_btn.click()
    time.sleep(2.0)


def _extract_grid_rows(page, debug_dump=False) -> list:
    """Reads the Bunker Report 'Fuels' grid. Returns row dicts with a
    `has_attachment` flag (paperclip icon present) and `row_index` for
    re-locating the row later (index into the LOCKED table specifically —
    see _download_attachments_for_row).

    CONFIRMED from two real runs (2026-08-26): this grid uses Kendo's
    locked/frozen-columns feature — Transaction Type/Voyage Leg/Port stay
    pinned while the rest scrolls horizontally, which Kendo renders as TWO
    SEPARATE <table> elements (a '.k-grid-content-locked' one and a
    '.k-grid-content' one), each with their own <tbody><tr> per transaction,
    kept in sync by row order. Reading only '.k-grid-content table tbody tr'
    (as an earlier version of this function did) returned the locked rows
    (6 cells: 2 icon columns + Transaction Type/Vessel/Voyage Leg/Port) AND
    the scrollable rows (29 cells) as 2N separate flat entries instead of N
    real transactions — confirmed via a real run showing exactly 13+13=26
    "rows" for a vessel with 13 actual bunker transactions. That bug also
    meant every previously-reported 'BDN reference' value was WRONG — it was
    actually reading the Flash Point column by coincidence of index maths,
    not a real BDN reference (which is a long code like 'IOCLVT1908202602089',
    never a bare 2-3 digit number like the '91'/'65' etc. logged before).

    Field positions below are hardcoded from a real fully-dumped 29-cell
    scrollable row (not guessed from header text) — the header <th> count/
    order does NOT correspond 1:1 to the body <td> layout in this grid (extra
    group-header cells like 'BDN Data'/'Analysis Data' throw off any index
    derived from counting <th> elements), so header-based column mapping is
    abandoned here in favor of this confirmed fixed layout. col_map is still
    logged for reference/future debugging, just not used to extract fields."""
    grid = page.locator(".k-grid-content, table").first
    grid.wait_for(state="visible", timeout=15000)

    header_cells = page.locator(".k-grid-header th, thead th").all()
    col_map = {}
    for i, th in enumerate(header_cells):
        text = th.inner_text().strip().replace("\n", " ")
        if text:
            col_map.setdefault(text, []).append(i)
    log.info(f"[SELECTOR] Bunker Report column map (reference only, not used for extraction): {col_map}")

    locked_rows = page.locator(".k-grid-content-locked table tbody tr").all()
    scroll_rows = page.locator(".k-grid-content table tbody tr").all()

    if locked_rows and len(locked_rows) == len(scroll_rows):
        log.info(f"[SELECTOR] Locked+scrollable grid confirmed: {len(locked_rows)} row(s) each, combining by index.")
        row_pairs = list(zip(locked_rows, scroll_rows))
    else:
        log.warning(f"[SELECTOR] No matching locked/scrollable row-count split (locked={len(locked_rows)}, "
                    f"scroll={len(scroll_rows)}) — falling back to scrollable table alone; "
                    f"locked-only fields (Transaction Type/Voyage Leg/Port) will be blank.")
        row_pairs = [(None, r) for r in scroll_rows]

    if debug_dump:
        counts = [
            (len(lr.locator('td').all()) if lr else 0) + len(sr.locator('td').all())
            for lr, sr in row_pairs
        ]
        log.info(f"[DEBUG]    Combined cell counts for all {len(row_pairs)} row(s): {counts}")

    # Fixed field->index map into the COMBINED cell list (locked cells first, then
    # scrollable cells) — confirmed from a real 6-locked + 29-scrollable row pair.
    IDX = {
        "transaction_type": 2, "voyage_leg": 4, "port": 5,
        "fuel_type": 6, "imo_fuel_grade": 7, "bdn_reference_no": 8, "rob_after_mt": 9,
        "category": 10, "quantity_mt": 11, "sulphur_content": 12, "density_15c": 13,
        "lcv_mj_kg": 14, "kinematic_viscosity": 15, "flash_point_c": 16, "time_zone": 17,
        "marpol_sample_no": 18, "begin_of_bunkering": 19, "end_of_bunkering": 20,
        "supplier_company": 21, "methane_number": 22, "comments": 23,
        "bunker_analysis_status": 24, "delayed": 26, "delayed_remarks": 27,
        "transaction_dt_id": 28, "lab_report_date": 29, "lab_density_15c": 30,
        "lab_sulphur_content": 31, "lab_kinematic_viscosity": 32, "lab_lcv_mj_kg": 33,
        "fuel_quantity_fa_report": 34,
    }

    rows = []
    for i, (locked_row, scroll_row) in enumerate(row_pairs):
        locked_cells = locked_row.locator("td").all() if locked_row else []
        scroll_cells = scroll_row.locator("td").all()
        cells = locked_cells + scroll_cells
        if len(cells) < 5:
            continue

        if debug_dump and i < 2:
            dump = [c.inner_text().strip().replace("\n", " ") for c in cells]
            log.info(f"[DEBUG]    Combined row {i} ({len(dump)} cells): {list(enumerate(dump))}")

        def get(field, default=""):
            idx = IDX.get(field)
            if idx is None or idx >= len(cells):
                return default
            try:
                v = cells[idx].inner_text().strip()
                if v:
                    return v
                # Some cells (e.g. transactionDtId) can be hidden-but-populated —
                # inner_text() returns "" for non-rendered elements, text_content()
                # reads the raw DOM text regardless of visibility.
                return cells[idx].text_content().strip()
            except Exception:
                return default

        has_attachment = (locked_row or scroll_row).locator(
            "button.grid-btn-icon-attachment, i.attachmentClick, [title*='Attachment' i]"
        ).count() > 0

        rows.append({
            "row_index": i,
            "has_attachment": has_attachment,
            "transaction_dt_id": get("transaction_dt_id"),
            "transaction_type": get("transaction_type"),
            "voyage_leg": get("voyage_leg"),
            "port": get("port"),
            "fuel_type": get("fuel_type"),
            "imo_fuel_grade": get("imo_fuel_grade"),
            "bdn_reference_no": get("bdn_reference_no"),
            "rob_after_mt": get("rob_after_mt"),
            "quantity_mt": get("quantity_mt"),
            "sulphur_content": get("sulphur_content"),
            "density_15c": get("density_15c"),
            "kinematic_viscosity": get("kinematic_viscosity"),
            "flash_point_c": get("flash_point_c"),
            # BDN Data group
            "time_zone": get("time_zone"),
            "marpol_sample_no": get("marpol_sample_no"),
            "begin_of_bunkering": get("begin_of_bunkering"),
            "end_of_bunkering": get("end_of_bunkering"),
            "supplier_company": get("supplier_company"),
            "methane_number": get("methane_number"),
            "comments": get("comments"),
            "bunker_analysis_status": get("bunker_analysis_status"),
            # Analysis Data group (lab values)
            "lab_report_date": get("lab_report_date"),
            "lab_density_15c": get("lab_density_15c"),
            "lab_sulphur_content": get("lab_sulphur_content"),
            "lab_kinematic_viscosity": get("lab_kinematic_viscosity"),
            "lcv_mj_kg": get("lcv_mj_kg"),
            "lab_lcv_mj_kg": get("lab_lcv_mj_kg"),
            "fuel_quantity_fa_report": get("fuel_quantity_fa_report"),
        })
    return rows


def _download_attachments_for_row(page, row_index: int, debug_dump=False) -> list:
    """Clicks a row's attachment (paperclip) icon, opens the 'Attachment
    Details' modal, downloads every listed file via Playwright's download
    interception, and returns [{"file_name", "file_size", "bytes"}, ...].
    Closes the modal (or the new tab, if one opened) before returning either way.

    The click might open an in-page modal OR a brand new browser tab — some
    Kendo-based apps do the latter for document viewers. We don't know which
    this app does yet, so we watch for a new tab for a few seconds; if none
    shows up we fall back to looking for an in-page modal on the same page.

    row_index indexes into the LOCKED table specifically (where the paperclip
    icon actually lives — see _extract_grid_rows' locked+scrollable table
    split), falling back to the scrollable table if no locked table exists."""
    locked_row = page.locator(".k-grid-content-locked table tbody tr").nth(row_index)
    row = locked_row if locked_row.count() > 0 else page.locator(".k-grid-content table tbody tr").nth(row_index)
    # Confirmed real selector from a live DOM dump: <button class="... grid-btn-icon-attachment ..."><i class="attachmentClick"></i></button>
    paperclip = row.locator(
        "button.grid-btn-icon-attachment, i.attachmentClick, [title*='Attachment' i]"
    ).first

    if debug_dump:
        try:
            log.info(f"[DEBUG]    Row {row_index} paperclip outerHTML before click: {paperclip.evaluate('el => el.outerHTML')}")
        except Exception as e:
            log.info(f"[DEBUG]    Row {row_index} paperclip outerHTML fetch failed: {e}")

    context = page.context
    new_page = None
    try:
        with context.expect_page(timeout=3000) as new_page_info:
            paperclip.click()
        new_page = new_page_info.value
        new_page.wait_for_load_state("load", timeout=10000)
        log.info(f"[DEBUG]    Row {row_index} attachment click opened a NEW TAB: {new_page.url}")
    except PlaywrightTimeoutError:
        pass  # no new tab within 3s — proceed to look for an in-page modal on `page`

    target = new_page if new_page else page
    if not new_page:
        time.sleep(1.0)  # give an in-page modal time to render before we go looking for it

    # CONFIRMED real bug (found via a live modal HTML dump): this is a plain Bootstrap
    # modal (<div class="modal-header ui-draggable-handle">...<h4 class="modal-title">
    # Attachment Details</h4></div>), not a Kendo window. The old broad
    # contains(@class,'modal') check matched 'modal-header' ITSELF (its own class
    # literally contains the substring "modal"), stopping the ancestor search one
    # level too early — so `modal` was really just the header bar, never the actual
    # .modal-content wrapper that holds the file-list body. That's why every past
    # attempt "found" a modal (no warning) yet always came up with zero file rows.
    modal = target.locator("text=Attachment Details").first.locator(
        "xpath=ancestor::*[contains(@class,'modal-content')][1]"
    )
    try:
        modal.wait_for(state="visible", timeout=10000)
    except Exception:
        # A new tab IS its own "modal" in a sense — if it opened and loaded a real
        # document viewer, treat the whole tab as the container rather than failing
        # just because there's no 'Attachment Details' k-window wrapper inside it.
        if new_page:
            modal = target.locator("body")
        else:
            log.warning(f"[SELECTOR] Attachment Details modal did not appear for row {row_index}.")
            if debug_dump:
                # Was "Attachment Details" text found anywhere at all (unscoped), just not
                # inside a k-window/modal/dialog ancestor? Or did nothing open at all?
                anywhere = page.locator("text=Attachment Details")
                count = anywhere.count()
                log.info(f"[DEBUG]    'Attachment Details' text found {count} time(s) anywhere on page after click.")
                if count > 0:
                    try:
                        log.info(f"[DEBUG]    Its container chain (up 3 levels) outerHTML: "
                                  f"{anywhere.first.evaluate('''el => { let n = el; for (let i=0;i<3 && n.parentElement;i++) n = n.parentElement; return n.outerHTML.slice(0, 2000); }''')}")
                    except Exception as e:
                        log.info(f"[DEBUG]    Container dump failed: {e}")
            return []

    if debug_dump:
        # The modal WAS found (no warning above) — dump exactly what matched, since
        # every attachment attempt this run resolved to "(no attachment)" despite no
        # "modal did not appear" warning ever firing, meaning something IS matching
        # 'Attachment Details' + a k-window/modal/dialog ancestor, but the file-list
        # table inside it isn't where we're looking for it.
        try:
            log.info(f"[DEBUG]    Row {row_index} modal FOUND — outerHTML (first 3000 chars): "
                      f"{modal.evaluate('el => el.outerHTML.slice(0, 3000)')}")
        except Exception as e:
            log.info(f"[DEBUG]    Row {row_index} modal outerHTML dump failed: {e}")

    files = []
    try:
        file_rows = modal.locator("table tbody tr").all()
        for fr in file_rows:
            cells = fr.locator("td").all()
            if len(cells) < 3:
                continue
            # The File Name cell can carry a trailing status line (e.g. "BDN.pdf\n\nAttached")
            # below the actual filename — take just the first non-empty line, otherwise the
            # raw multi-line text ends up in the Azure blob path and gets rejected as an
            # invalid URI (confirmed: 5/13 real uploads failed with exactly this error).
            file_name_raw = cells[1].inner_text().strip()
            file_name = next((line.strip() for line in file_name_raw.splitlines() if line.strip()), file_name_raw)
            file_size = cells[2].inner_text().strip()

            download_icon = fr.locator(
                "[class*='download' i], .k-icon.k-i-download, [title*='Download' i]"
            ).first
            if download_icon.count() == 0:
                log.warning(f"[SELECTOR] No download icon found for attachment '{file_name}' — skipping.")
                continue

            try:
                with target.expect_download(timeout=15000) as dl_info:
                    download_icon.click()
                download = dl_info.value
                path = download.path()
                with open(path, "rb") as f:
                    file_bytes = f.read()
                files.append({"file_name": file_name, "file_size": file_size, "bytes": file_bytes})
            except Exception as e:
                log.error(f"[DOWNLOAD]  Failed to download '{file_name}': {e}")
    finally:
        if new_page:
            try:
                new_page.close()
            except Exception:
                pass
        else:
            # [SELECTOR] modal close button — best-effort, Escape as a fallback.
            try:
                close_btn = modal.locator("[class*='close' i], .k-window-actions button").first
                if close_btn.count() > 0:
                    close_btn.click()
                else:
                    page.keyboard.press("Escape")
            except Exception:
                pass
        time.sleep(0.3)

    return files


# ---------------------------------------------------------------------------
# MAIN RUNNER
# ---------------------------------------------------------------------------

def run():
    auth_file = str(config.MARIAPPS_AUTH_JSON)
    if not os.path.exists(auth_file):
        log.error("[AUTH]     auth.json not found — run generate_auth.py first.")
        return

    headless = os.getenv("MARIAPPS_HEADLESS", "true").lower() != "false"
    vessel_names = get_scrape_vessels("mari_apps")
    if not vessel_names:
        log.warning("[CONFIG]   No mari_enabled vessels found — nothing to do.")
        return

    to_date_str = _to_kendo_date(datetime.now())
    log.info("=" * 60)
    log.info("  MariApps Bunker Report — Starting")
    log.info(f"[CONFIG]   Date range   : {FROM_DATE}  →  {to_date_str}")
    log.info(f"[CONFIG]   Vessels      : {len(vessel_names)} — {', '.join(vessel_names)}")
    log.info("=" * 60)

    db = SessionLocal()
    total_saved = total_skipped = total_errors = 0

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(storage_state=auth_file)
            page = context.new_page()

            log.info(f"[NAV]      Navigating to: {config.MARIAPPS_BUNKER_REPORT_URL}")
            page.goto(config.MARIAPPS_BUNKER_REPORT_URL, wait_until="load", timeout=60000)

            if "Account/Index" in page.url or "Login" in page.url:
                log.error("[NAV]      Session expired — run generate_auth.py.")
                browser.close()
                return

            for v_idx, vessel_name in enumerate(vessel_names, start=1):
                if page.is_closed():
                    log.error("[BROWSER]  Page closed unexpectedly. Aborting.")
                    break

                vessel_ref = db.query(Vessel).filter(
                    Vessel.vessel_name.ilike(f"%{vessel_name}%")
                ).first()
                if not vessel_ref:
                    log.warning(f"[VESSEL]   '{vessel_name}' not found in vessels table — skipping.")
                    continue
                vessel_imo = vessel_ref.imo_number

                log.info(f"[VESSEL]   [{v_idx}/{len(vessel_names)}] {vessel_name} (IMO {vessel_imo})")

                try:
                    _select_vessel(page, vessel_name)
                    _set_date_range_and_search(page, FROM_DATE, to_date_str)
                except Exception as e:
                    log.error(f"[FILTER]   Failed to apply filters for '{vessel_name}': {e}")
                    total_errors += 1
                    continue

                # Debug dump (raw cell text, attachment icon HTML, modal-detection
                # diagnostics) — opt-in via env var, off by default so normal runs
                # stay clean. Set MARIAPPS_BUNKER_DEBUG=true and it applies to the
                # first 2 vessels of the run (enough to catch a real data row without
                # flooding the log for all 14 vessels).
                debug_dump = os.getenv("MARIAPPS_BUNKER_DEBUG", "false").lower() == "true" and v_idx <= 2

                try:
                    grid_rows = _extract_grid_rows(page, debug_dump=debug_dump)
                except Exception as e:
                    log.error(f"[GRID]     Failed to extract rows for '{vessel_name}': {e}")
                    total_errors += 1
                    continue

                log.info(f"[GRID]     {len(grid_rows)} bunker record(s) found for {vessel_name}.")

                for r in grid_rows:
                    files = []
                    if r["has_attachment"]:
                        try:
                            files = _download_attachments_for_row(page, r["row_index"], debug_dump=debug_dump)
                        except Exception as e:
                            log.error(f"[DOWNLOAD]  Attachment fetch failed for row {r['row_index']}: {e}")

                    if not files:
                        # No attachment (e.g. "Inventory Adjustment" rows never have one) —
                        # still save the bunker record itself, just with no blob reference.
                        files = [{"file_name": None, "file_size": None, "bytes": None}]

                    for f in files:
                        fp = _fingerprint(vessel_imo, r["transaction_dt_id"], r["bdn_reference_no"], f["file_name"])
                        existing = db.query(MariAppsBunkerReport).filter(
                            MariAppsBunkerReport.fingerprint == fp
                        ).first()
                        if existing:
                            total_skipped += 1
                            continue

                        blob_info = {}
                        if f["bytes"]:
                            try:
                                blob_info = upload_bunker_attachment(
                                    vessel_imo, r["bdn_reference_no"], f["file_name"], f["bytes"]
                                )
                            except Exception as e:
                                log.error(f"[BLOB]     Upload failed for '{f['file_name']}': {e}")
                                total_errors += 1

                        record = MariAppsBunkerReport(
                            vessel_imo=vessel_imo,
                            vessel_name=vessel_name,
                            transaction_dt_id=r["transaction_dt_id"] or None,
                            transaction_type=r["transaction_type"] or None,
                            voyage_leg=r["voyage_leg"] or None,
                            port=r["port"] or None,
                            fuel_type=r["fuel_type"] or None,
                            imo_fuel_grade=r["imo_fuel_grade"] or None,
                            bdn_reference_no=r["bdn_reference_no"] or None,
                            rob_after_mt=_num(r["rob_after_mt"]),
                            quantity_mt=_num(r["quantity_mt"]),
                            sulphur_content=_num(r["sulphur_content"]),
                            density_15c=_num(r["density_15c"]),
                            kinematic_viscosity=_num(r["kinematic_viscosity"]),
                            flash_point_c=_num(r["flash_point_c"]),
                            # BDN Data group
                            time_zone=r["time_zone"] or None,
                            marpol_sample_no=r["marpol_sample_no"] or None,
                            begin_of_bunkering=r["begin_of_bunkering"] or None,
                            end_of_bunkering=r["end_of_bunkering"] or None,
                            supplier_company=r["supplier_company"] or None,
                            methane_number=_num(r["methane_number"]),
                            comments=r["comments"] or None,
                            bunker_analysis_status=r["bunker_analysis_status"] or None,
                            # Analysis Data group (lab values)
                            lab_report_date=r["lab_report_date"] or None,
                            lab_density_15c=_num(r["lab_density_15c"]),
                            lab_sulphur_content=_num(r["lab_sulphur_content"]),
                            lab_kinematic_viscosity=_num(r["lab_kinematic_viscosity"]),
                            lab_lcv_mj_kg=_num(r["lab_lcv_mj_kg"]),
                            lcv_mj_kg=_num(r["lcv_mj_kg"]),
                            fuel_quantity_fa_report=r["fuel_quantity_fa_report"] or None,
                            attachment_file_name=f["file_name"],
                            attachment_file_size=f["file_size"],
                            blob_url=blob_info.get("blob_url"),
                            blob_path=blob_info.get("blob_path"),
                            raw_json=r,
                            fingerprint=fp,
                        )
                        db.add(record)
                        db.commit()
                        total_saved += 1
                        log.info(
                            f"[SAVE]     {vessel_name} — txn={r['transaction_dt_id'] or '(none)'} "
                            f"BDN {r['bdn_reference_no'] or '(none)'} "
                            f"{'| ' + f['file_name'] if f['file_name'] else '(no attachment)'}"
                        )

            browser.close()
    finally:
        db.close()

    log.info("=" * 60)
    log.info(f"  Bunker Report scrape complete — saved={total_saved} skipped={total_skipped} errors={total_errors}")
    log.info("=" * 60)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run()
