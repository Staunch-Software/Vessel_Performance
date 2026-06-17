import logging
from playwright.sync_api import Page

log = logging.getLogger(__name__)


class MariAppsHeaderScanner:
    """
    Scans the Daily Log detail page header section.

    The header contains these fields (from screenshots):
      Leg Number | Log Number | Log Type | Sub Log Type
      Date (Local) | Time Zone | Date (UTC) | Loading Condition
      Duration (Hrs / Mins) | Departure Port (Last Leg) | Arrival Port (Current Leg)
      Date line crossed (toggle)

    Strategy:
      1. JS ViewModel read (Kendo MVVM / KnockoutJS)
      2. Direct input[data-bind] reads
      3. Full label scan (for/parent sibling approach)
    """

    # Fields we always want to try to capture explicitly
    PRIORITY_FIELDS = [
        "Leg Number", "Log Number", "Log Type", "Sub Log Type",
        "Date (Local)", "Date (UTC)", "Time Zone",
        "Loading Condition", "Duration",
        "Departure Port", "Departure Port (Last Leg)",
        "Arrival Port", "Arrival Port (Current Leg)",
    ]

    def __init__(self, page: Page):
        self.page = page

    def scan(self, page: Page) -> dict:
        """
        Scans the provided detail page for header fields.
        Returns: { "Field Label": "Value", ... }
        """
        log.info("  Scanning header fields...")
        header_data = {}

        try:
            # --- PASS 1: Direct input reads by known IDs / data-bind attributes ---
            direct_fields = {
                "Leg Number":                   "input[data-bind*='legNo'], input[data-bind*='legNumber'], #legNo",
                "Log Number":                   "input[data-bind*='logNo'], input[data-bind*='logNumber'], #logNo",
                "Log Type":                     "input[data-bind*='logType'], #logType",
                "Sub Log Type":                 "input[data-bind*='subLogType'], #subLogType",
                "Date (Local)":                 "input[data-bind*='dateLocal'], #txtDateLocal, input[data-bind*='localDate']",
                "Date (UTC)":                   "input[data-bind*='dateUTC'], input[data-bind*='utcDate'], #txtDateUTC",
                "Time Zone":                    "input[data-bind*='timeZone'], input[data-bind*='timezone'], #timeZone",
                "Loading Condition":            "input[data-bind*='loadCond'], input[data-bind*='loadingCondition'], #loadingCondition",
                "Duration":                     "input[data-bind*='duration'], #duration",
                "Departure Port (Last Leg)":    "input[data-bind*='depPort'], input[data-bind*='departurePort'], #depPort",
                "Arrival Port (Current Leg)":   "input[data-bind*='arrPort'], input[data-bind*='arrivalPort'], #arrPort",
            }

            for field_name, selectors in direct_fields.items():
                for sel in selectors.split(","):
                    sel = sel.strip()
                    try:
                        el = page.locator(sel).first
                        if el.count() > 0:
                            val = self._extract_value(el)
                            if val:
                                header_data[field_name] = val
                                break
                    except Exception:
                        continue

            # --- PASS 2: JS ViewModel read (catches Kendo MVVM / KO bound values) ---
            js_vm_fields = {
                "Leg Number":                 ["headerData.legNo", "viewModel.legNo", "viewModel.headerData.legNo"],
                "Log Number":                 ["headerData.logNo", "viewModel.logNo"],
                "Log Type":                   ["headerData.logType", "viewModel.logType"],
                "Date (UTC)":                 ["headerData.utcDate", "headerData.dateUTC", "viewModel.utcDate"],
                "Time Zone":                  ["headerData.timeZone", "viewModel.timeZone"],
                "Loading Condition":          ["headerData.loadCond", "headerData.loadingCondition", "viewModel.loadCond"],
                "Departure Port (Last Leg)":  ["headerData.depPort", "viewModel.depPort"],
                "Arrival Port (Current Leg)": ["headerData.arrPort", "viewModel.arrPort"],
            }

            for field_name, js_paths in js_vm_fields.items():
                if header_data.get(field_name):
                    continue  # already captured
                for js_path in js_paths:
                    try:
                        val = page.evaluate(f"() => {{ try {{ return {js_path}; }} catch(e) {{ return null; }} }}")
                        if val:
                            header_data[field_name] = str(val).strip()
                            break
                    except Exception:
                        continue

            # --- PASS 3: Full label scan (catches anything missed above) ---
            labels = page.locator("label").all()
            for label_loc in labels:
                try:
                    label_text = label_loc.inner_text().strip().rstrip(":").strip()
                    if not label_text:
                        continue

                    # Normalise to match our priority field names
                    normalised = label_text.replace("*", "").strip()

                    # Skip if already captured
                    if any(normalised.lower() in k.lower() or k.lower() in normalised.lower()
                           for k in header_data):
                        continue

                    value = None

                    # Try for= attribute
                    for_id = label_loc.get_attribute("for")
                    if for_id:
                        el = page.locator(f"#{for_id}").first
                        if el.count() > 0:
                            value = self._extract_value(el)

                    # Try parent sibling
                    if value is None:
                        parent = label_loc.locator("xpath=..")
                        el = parent.locator("input, select, span.form-control-static, div.form-control-static").first
                        if el.count() > 0:
                            value = self._extract_value(el)

                    if value:
                        header_data[normalised] = value

                except Exception as lbl_err:
                    log.debug(f"  Label scan error: {lbl_err}")
                    continue

            log.info(f"  Header fields captured: {list(header_data.keys())}")
            return header_data

        except Exception as e:
            log.error(f"  Header scan failed: {e}")
            return {}

    def _extract_value(self, element_locator) -> str | None:
        """Extracts value from input / select / span using a single JS evaluate."""
        try:
            result = element_locator.evaluate("""el => {
                const tag = el.tagName.toLowerCase();
                if (tag === 'input' || tag === 'textarea') {
                    return el.value || el.getAttribute('value') || '';
                } else if (tag === 'select') {
                    return el.options[el.selectedIndex]?.text || '';
                } else {
                    return el.innerText || el.textContent || '';
                }
            }""")
            return result.strip() if result else None
        except Exception:
            return None