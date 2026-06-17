import logging
import time
import pandas as pd
import numpy as np
import json
from playwright.sync_api import Page

log = logging.getLogger(__name__)

MONTH_MAP = {
    "Jan": "Jan", "Feb": "Feb", "Mar": "Mar",
    "Apr": "Apr", "May": "May", "Jun": "Jun",
    "Jul": "Jul", "Aug": "Aug", "Sep": "Sep",
    "Oct": "Oct", "Nov": "Nov", "Dec": "Dec"
}

class MariAppsFilterHandler:
    def __init__(self, page: Page):
        self.page = page

    def _get_active_frame(self):
        for _ in range(20):
            for frame in self.page.frames:
                try:
                    if frame.get_by_text("From (UTC)").count() > 0:
                        return frame
                except:
                    continue
            time.sleep(1)
        return None

    def _select_date_from_calendar(self, target, input_id: str, day, month, year):
        """
        Sets a KendoDateTimePicker to a specific date.

        Confirmed from debug output:
          - Input IDs: txtFromDate, txtToDate
          - Widget type: kendoDateTimePicker (has date + time buttons)
          - Must use Kendo JS API to open: w.open('date')
          - Popup class: k-calendar-container k-popup

        After selecting day/month/year via the calendar popup, we also:
          - Set time to 00:00 for fromDate, 23:59 for toDate
          - Trigger change() so the MVVM binding (fromDate/toDate viewModel)
            actually updates — without this the UI may ignore the selection
        """
        try:
            log.info(f"📅 Setting {day}-{month}-{year} for #{input_id}")

            # STEP 1: Open calendar pane via Kendo widget API
            opened = target.evaluate(f"""() => {{
                const input = document.getElementById('{input_id}');
                if (!input) return 'NO_INPUT';
                if (typeof $ !== 'undefined') {{
                    const w = $(input).data('kendoDateTimePicker');
                    if (w) {{ w.open('date'); return 'KENDO_OPEN'; }}
                }}
                const btn = input.parentElement && input.parentElement.querySelector('.k-link-date');
                if (btn) {{ btn.click(); return 'BTN_CLICK'; }}
                return 'FAILED';
            }}""")
            log.info(f"  ↳ Open method: {opened}")
            if opened == 'FAILED' or opened == 'NO_INPUT':
                raise Exception(f"Could not open calendar for #{input_id}: {opened}")
            time.sleep(0.8)

            # STEP 2: Find which k-calendar-container popup is now visible
            popup_index = target.evaluate("""() => {
                const popups = document.querySelectorAll('.k-calendar-container.k-popup');
                for (let i = 0; i < popups.length; i++) {
                    if (popups[i].style.display !== 'none' && popups[i].offsetParent !== null)
                        return i;
                }
                // Fallback: any visible popup containing a calendar
                const all = document.querySelectorAll('.k-popup, .k-animation-container');
                for (let i = 0; i < all.length; i++) {
                    if (all[i].offsetParent !== null && all[i].style.display !== 'none'
                        && all[i].querySelector('.k-calendar'))
                        return 1000 + i;
                }
                return -1;
            }""")

            if popup_index == -1:
                raise Exception(f"Calendar popup not visible after open() for #{input_id}")
            log.info(f"  ↳ Popup index: {popup_index}")

            # Helper: scope all JS to the correct popup element
            def js(inner):
                if popup_index >= 1000:
                    sel = '.k-popup, .k-animation-container'
                    idx = popup_index - 1000
                else:
                    sel = '.k-calendar-container.k-popup'
                    idx = popup_index
                return f"""() => {{
                    const popup = document.querySelectorAll('{sel}')[{idx}];
                    if (!popup) return false;
                    {inner}
                }}"""

            # STEP 3+4: Click nav header twice to reach year view
            target.evaluate(js("const h = popup.querySelector('.k-header .k-nav-fast, .k-calendar-header .k-title'); if(h) h.click(); return true;"))
            time.sleep(0.4)
            target.evaluate(js("const h = popup.querySelector('.k-header .k-nav-fast, .k-calendar-header .k-title'); if(h) h.click(); return true;"))
            time.sleep(0.4)

            # STEP 5: Click year
            year_str = str(year)
            ok = target.evaluate(js(f"""
                for (const c of popup.querySelectorAll('td[role="gridcell"]'))
                    if (c.innerText.trim() === '{year_str}') {{ c.click(); return true; }}
                return false;
            """))
            if not ok:
                raise Exception(f"Year {year_str} not found in popup")
            log.info(f"  ↳ Clicked year {year_str}")
            time.sleep(0.4)

            # STEP 6: Click month (prefix match: 'Nov' matches 'November')
            mp = str(month)[:3].lower()
            ok = target.evaluate(js(f"""
                for (const c of popup.querySelectorAll('td[role="gridcell"]'))
                    if (c.innerText.trim().toLowerCase().startsWith('{mp}')) {{ c.click(); return true; }}
                return false;
            """))
            if not ok:
                raise Exception(f"Month {month} not found in popup")
            log.info(f"  ↳ Clicked month {month}")
            time.sleep(0.4)

            # STEP 7: Click day
            day_str = str(int(day))  # '04' -> '4'
            ok = target.evaluate(js(f"""
                for (const a of popup.querySelectorAll('a.k-link'))
                    if (a.innerText.trim() === '{day_str}') {{ a.click(); return true; }}
                for (const c of popup.querySelectorAll('td[role="gridcell"]'))
                    if (c.innerText.trim() === '{day_str}') {{ c.click(); return true; }}
                return false;
            """))
            if not ok:
                raise Exception(f"Day {day_str} not found in popup")
            log.info(f"  ↳ Clicked day {day_str}")
            time.sleep(0.4)

            # STEP 8: Set time and trigger MVVM binding update
            # fromDate = 00:00 (start of day), toDate = 23:59 (end of day)
            # Without triggering change(), the Kendo MVVM viewModel binding
            # (fromDate/toDate) does NOT update and the search returns wrong range
            time_str = "00:00" if "from" in input_id.lower() else "23:59"
            target.evaluate(f"""() => {{
                const input = document.getElementById('{input_id}');
                if (!input) return;
                if (typeof $ !== 'undefined') {{
                    const w = $(input).data('kendoDateTimePicker');
                    if (w) {{
                        const v = w.value();
                        if (v) {{
                            const parts = '{time_str}'.split(':');
                            v.setHours(parseInt(parts[0]), parseInt(parts[1]), 0, 0);
                            w.value(v);
                            w.trigger('change');
                        }}
                    }}
                }}
            }}""")
            time.sleep(0.3)

            # Verify what value is actually set in the input
            actual_value = target.evaluate(f"() => document.getElementById('{input_id}').value")
            log.info(f"  ✅ #{input_id} final value: '{actual_value}'")

        except Exception as e:
            log.error(f"❌ Calendar failed for #{input_id}: {e}")
            raise

    def download_grid_data(self, target) -> list:
        try:
            log.info("⬇️  Downloading Excel export...")
            
            # 1. Ensure the loading mask is gone before interacting with the export button
            # This prevents the "intercepts pointer events" error
            try:
                target.locator("#loading-container").wait_for(state="hidden", timeout=30000)
            except:
                log.warning("  ↳ Loading mask did not disappear, proceeding anyway...")

            export_btn = target.locator("button.btn-icon-export").first
            export_btn.wait_for(state="visible", timeout=10000)
            export_btn.scroll_into_view_if_needed()

            # 2. Use force=True if the element is still being intercepted by the UI framework
            with self.page.expect_download(timeout=90000) as download_info:
                export_btn.click(force=True)

            path = download_info.value.path()
            df = pd.read_excel(path, header=None, dtype=str, keep_default_na=False, engine='openpyxl')

            if len(df) < 2:
                log.warning("Excel file appears empty.")
                return []

            row0 = df.iloc[0].replace("", np.nan).ffill().fillna("")
            row1 = df.iloc[1].fillna("")
            headers = []
            for c0, c1 in zip(row0, row1):
                c0, c1 = str(c0).strip(), str(c1).strip()
                if c0 and c1 and c0 != c1:
                    headers.append(f"{c0} - {c1}")
                elif c1:
                    headers.append(c1)
                else:
                    headers.append(c0)

            df.columns = headers
            df = df.iloc[2:].dropna(how='all').reset_index(drop=True)
            log.info(f"📊 Excel contains {len(df)} records.")
            return json.loads(df.to_json(orient='records', date_format='iso'))

        except Exception as e:
            log.error(f"❌ Excel download failed: {e}")
            return []
    def apply_filters_and_export(self, vessel_name: str, from_date: str, to_date: str):
        """
        Selects vessel, sets From/To dates via calendar, clicks Search.

        Date format: 'DD-Mon-YYYY'  e.g. '30-Nov-2025'
        fromDate = 30-Nov-2025 00:00  (start of range)
        toDate   = today's date 23:59 (end of range — captures full day)
        """
        try:
            log.info(f"🔍 Vessel={vessel_name} | From={from_date} | To={to_date}")

            vessel_input = self.page.locator("input[aria-owns='vesselSearchBox_listbox']").first
            vessel_input.wait_for(state="visible")
            vessel_input.click()
            self.page.keyboard.press("Control+A")
            self.page.keyboard.press("Backspace")
            vessel_input.press_sequentially(vessel_name, delay=100)
            self.page.locator(f"ul#vesselSearchBox_listbox li:has-text('{vessel_name}')").first.click()
            time.sleep(0.5)

            target = self._get_active_frame()
            if not target:
                raise Exception("Frame not found")

            # from_date: '30-Nov-2025' -> ['30', 'Nov', '2025']
            fp = from_date.split('-')
            if len(fp) == 3:
                self._select_date_from_calendar(target, "txtFromDate", fp[0], fp[1], fp[2])

            tp = to_date.split('-')
            if len(tp) == 3:
                self._select_date_from_calendar(target, "txtToDate", tp[0], tp[1], tp[2])

            search_btn = target.locator("button#btnSearch").first
            search_btn.wait_for(state="visible", timeout=8000)
            search_btn.click()
            log.info("  ↳ Search clicked...")

            try:
                target.locator(".k-loading-mask").wait_for(state="hidden", timeout=30000)
            except:
                pass

            time.sleep(1.5)
            log.info("  ✅ Filters applied.")
            return "success"

        except Exception as e:
            log.error(f"❌ Filter failed for {vessel_name}: {e}")
            return "error"