import logging
import time
from playwright.sync_api import Page

log = logging.getLogger(__name__)

class MariAppsGridExtractor:
    """
    Extracts log metadata rows from the MariApps UI grid.

    IMPORTANT: The UI grid uses Kendo virtual scrolling — it only renders
    the visible rows in the DOM. This means scrolling alone does NOT guarantee
    all rows are extracted. The grid_extractor is used ONLY to get the clickable
    log links. The Excel download (filter_handler.download_grid_data) is the
    authoritative source for ALL log records.
    """

    def __init__(self, page: Page):
        self.page = page

    def _get_target(self):
        """Returns the frame or page that contains the Kendo grid."""
        for frame in self.page.frames:
            try:
                if frame.locator(".k-grid-content").count() > 0:
                    return frame
            except Exception:
                continue
        return self.page

    def extract_rows(self, current_vessel_name: str) -> list:
        """
        Extracts ALL log rows from the grid by scrolling in chunks.

        Because the grid is virtually rendered, we:
          1. Scroll a small amount
          2. Capture newly visible rows
          3. De-duplicate by log_number
          4. Repeat until no new rows appear

        Returns a list of dicts with keys:
            log_number, log_type, log_date, status, vessel, row_index
        """
        log.info(f"📋 Extracting grid rows for {current_vessel_name}...")
        target = self._get_target()

        # --- Wait for data to load ---
        rows_locator = target.locator(".k-grid-content table tr")
        data_found = False
        for attempt in range(8):
            row_count = rows_locator.count()
            if row_count > 0:
                first_row_text = rows_locator.first.inner_text()
                if "No records found" not in first_row_text and first_row_text.strip():
                    log.info(f"  ↳ Grid has data (attempt {attempt + 1}).")
                    data_found = True
                    break
            time.sleep(2)

        if not data_found:
            log.warning(f"  ⚠️  No data rows found in grid for {current_vessel_name}.")
            return []

        # --- Get column index map ---
        header_elements = target.locator(".k-grid-header th").all()
        col_map = {}
        for i, th in enumerate(header_elements):
            text = th.inner_text().strip().replace("\n", " ")
            if text:
                col_map[text] = i

        log.info(f"  ↳ Column map: {col_map}")

        # --- Scroll-and-collect strategy for virtual grid ---
        scroll_box = target.locator(".k-grid-content").first
        all_log_numbers = {}  # log_number → row_data (de-duplication key)
        last_captured_count = 0
        stale_rounds = 0
        MAX_STALE_ROUNDS = 3  # stop if no new rows appear after 3 scroll attempts

        scroll_step = 800  # pixels per scroll step
        current_scroll = 0

        log.info("  ↳ Beginning scroll-and-capture loop...")

        while True:
            # Capture currently visible rows
            visible_rows = rows_locator.all()
            for row in visible_rows:
                try:
                    cells = row.locator("td")
                    if cells.count() < 3:
                        continue

                    # Prefer the hyperlink text as the log number (most reliable)
                    log_link = row.locator("a#toLogBook").first
                    if log_link.count() > 0:
                        log_num = log_link.inner_text().strip()
                    else:
                        idx = col_map.get("Log Number", 3)
                        log_num = cells.nth(idx).inner_text().strip()

                    if not log_num or log_num in all_log_numbers:
                        continue  # skip empty or already-seen rows

                    def get_val(col_name):
                        if col_name in col_map:
                            try:
                                return cells.nth(col_map[col_name]).inner_text().strip()
                            except Exception:
                                return ""
                        return ""

                    row_data = {
                        "log_number": log_num,
                        "log_type":   get_val("Log Type"),
                        "log_date":   get_val("Log Date"),
                        "status":     get_val("Status"),
                        "vessel":     current_vessel_name,
                    }
                    all_log_numbers[log_num] = row_data

                except Exception as e:
                    log.debug(f"  Row parse error (non-fatal): {e}")
                    continue

            new_count = len(all_log_numbers)
            if new_count > last_captured_count:
                log.info(f"  ↳ Captured {new_count} unique rows so far (scroll_pos={current_scroll}px)...")
                last_captured_count = new_count
                stale_rounds = 0
            else:
                stale_rounds += 1
                log.debug(f"  ↳ No new rows at scroll_pos={current_scroll}px (stale round {stale_rounds}/{MAX_STALE_ROUNDS})")

            if stale_rounds >= MAX_STALE_ROUNDS:
                log.info(f"  ↳ Scroll complete — no new rows after {MAX_STALE_ROUNDS} attempts.")
                break

            # Scroll down
            try:
                current_scroll += scroll_step
                scroll_box.evaluate(f"el => el.scrollTop = {current_scroll}")
                time.sleep(1.2)  # give virtual renderer time to paint new rows
            except Exception:
                break

        result = list(all_log_numbers.values())
        log.info(f"  ✅ Grid extraction complete: {len(result)} unique rows captured for {current_vessel_name}.")
        return result