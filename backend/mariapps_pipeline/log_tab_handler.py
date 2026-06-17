import logging
import time
from playwright.sync_api import Page

log = logging.getLogger(__name__)

class MariAppsLogTabHandler:
    def __init__(self, page: Page):
        self.page = page

    def open_log_tab(self, row_data: dict):
        """
        Opens the detail page for a given log by clicking its hyperlink.
        Waits for the new tab to fully load before returning it.

        Returns the new Page object, or None if it could not be opened.
        """
        log_number = row_data.get("log_number")
        if not log_number:
            log.warning("open_log_tab called with no log_number in row_data.")
            return None

        try:
            # Find the frame that contains the grid links
            target = self.page
            for frame in self.page.frames:
                try:
                    if frame.locator("a#toLogBook").count() > 0:
                        target = frame
                        break
                except Exception:
                    continue

            # Locate the specific link for this log number
            log_link = target.locator("a#toLogBook", has_text=log_number).first

            if log_link.count() == 0:
                log.warning(f"  Link for log {log_number} not found in grid — may be off-screen.")
                return None

            # Scroll the element into view before clicking
            log_link.evaluate("el => el.scrollIntoView({ block: 'center', behavior: 'auto' })")
            time.sleep(0.5)  # short settle time

            # Open the link in a new tab by catching the popup
            with self.page.context.expect_page(timeout=30000) as new_page_info:
                log_link.evaluate("el => el.click()")

            new_page = new_page_info.value
            new_page.wait_for_load_state("domcontentloaded", timeout=30000)

            # Wait for the Performance tab to be present — confirms the detail page loaded
            new_page.locator("a[href='#Weather']").wait_for(state="visible", timeout=20000)

            log.info(f"  ↳ Detail tab opened for log {log_number}.")
            return new_page

        except Exception as e:
            log.error(f"  ❌ Error opening tab for log {log_number}: {e}")
            return None