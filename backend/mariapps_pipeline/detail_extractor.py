import logging
import time
from playwright.sync_api import Page

log = logging.getLogger(__name__)


class MariAppsDetailExtractor:
    """
    Extracts data from ALL 6 tabs on the MariApps Daily Log detail page:
      - Position    (div#Position     / a[href='#Position'])
      - Operation   (div#Operations   / a[href='#Operations'])
      - Consumption (div#Consumptions / a[href='#Consumptions'])
      - Performance (div#Weather      / a[href='#Weather'])
      - Machinery   (div#NewMachinery / a[href='#NewMachinery'])
      - Fuel Stock  (div#FuelStock    / a[href='#FuelStock'])
      - KPI         (div#Performance  / a[href='#Performance'])

    Returns a dict keyed exactly as:
        Position, Operation, Consumption, Performance, Machinery, Fuel Stock, KPI

    These keys are used by build_full_row_data() in mariapps_persistence.py
    to store data under Position_Data, Operation_Data, etc.
    """

    def __init__(self, page: Page):
        self.page = page

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def extract_details(self) -> dict:
        """
        Returns a dict with exactly these 7 keys (one per tab):
            Position, Operation, Consumption, Performance,
            Machinery, Fuel Stock, KPI
        Each value is a flat { "Field Name": "Value" } dict.
        """
        results = {
            "Position":    {},
            "Operation":   {},
            "Consumption": {},
            "Performance": {},
            "Machinery":   {},
            "Fuel Stock":  {},
            "KPI":         {},
        }

        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass

        # result_key must match the keys in results{} above exactly
        tab_configs = [
            ("Position",    "a[href='#Position']",     "div#Position",       self._extract_standard_tab),
            ("Operation",   "a[href='#Operations']",   "div#Operations",     self._extract_operation_tab),
            ("Consumption", "a[href='#Consumptions']", "div#Consumptions",   self._extract_consumption_tab),
            ("Performance", "a[href='#Weather']",      "div#Weather",        self._extract_standard_tab),
            ("Machinery",   "a[href='#NewMachinery']", "div#NewMachinery",   self._extract_standard_tab),
            ("Fuel Stock",  "a[href='#FuelStock']",    "div#FuelStock",      self._extract_standard_tab),
            ("KPI",         "a[href='#Performance']",  "div#Performance",    self._extract_standard_tab),
        ]

        for result_key, link_sel, pane_sel, extractor_fn in tab_configs:
            try:
                results[result_key] = extractor_fn(
                    tab_name=result_key,
                    link_selector=link_sel,
                    pane_selector=pane_sel,
                )
            except Exception as e:
                log.error(f"  Error on tab '{result_key}': {e}")

        return results

    # ------------------------------------------------------------------
    # Shared: click tab and wait for pane
    # ------------------------------------------------------------------
    def _click_tab_and_wait(self, tab_name: str, link_selector: str, pane_selector: str):
        tab_link = self.page.locator(link_selector).first
        if tab_link.count() == 0:
            log.warning(f"  Tab link '{link_selector}' not found — skipping {tab_name}.")
            return None

        tab_link.evaluate("el => el.click()")
        time.sleep(1.2)

        pane = self.page.locator(pane_selector).first
        try:
            pane.wait_for(state="attached", timeout=10000)
        except Exception:
            log.warning(f"  Pane '{pane_selector}' did not attach for {tab_name}.")
            return None

        # Trigger lazy-load by scrolling any Kendo grid inside the pane
        scrollable = pane.locator(".k-grid-content").first
        if scrollable.count() > 0:
            scrollable.evaluate("el => el.scrollTop = el.scrollHeight")
            time.sleep(0.8)
            scrollable.evaluate("el => el.scrollTop = 0")
            time.sleep(0.5)

        return pane

    # ------------------------------------------------------------------
    # Extractor 1: Standard 3-column tab  [Variable | Unit | Value]
    # Used for: Position, Performance, Machinery, Fuel Stock, KPI
    # ------------------------------------------------------------------
    def _extract_standard_tab(self, tab_name: str, link_selector: str, pane_selector: str) -> dict:
        tab_data = {}
        pane = self._click_tab_and_wait(tab_name, link_selector, pane_selector)
        if pane is None:
            return tab_data

        rows = pane.locator("tr[role='row']").all()
        if not rows:
            log.warning(f"  No data rows in {tab_name}.")
            return tab_data

        for row in rows:
            try:
                cells = row.locator("td").all()
                if len(cells) >= 3:
                    raw_name   = cells[0].inner_text().strip()
                    value      = cells[2].inner_text().strip()
                    clean_name = raw_name.replace("*", "").strip()
                    if clean_name and clean_name.lower() not in ("variable", ""):
                        tab_data[clean_name] = value
            except Exception:
                continue

        log.info(f"  {tab_name}: {len(tab_data)} fields.")
        return tab_data

    # ------------------------------------------------------------------
    # Extractor 2: Operation tab
    # Sub-sections:
    #   Main Engine        → [Variable | Unit | Value]
    #   Auxiliary Engines  → [Variable | Unit | No1 | No2 | No3]
    #   Other Equipment    → [Variable | Unit | Value]
    #   Power Packs        → [Variable | Unit | No1]
    # Keys become: "AE Running Hours - No 1", etc.
    # ------------------------------------------------------------------
    def _extract_operation_tab(self, tab_name: str, link_selector: str, pane_selector: str) -> dict:
        tab_data = {}
        pane = self._click_tab_and_wait(tab_name, link_selector, pane_selector)
        if pane is None:
            return tab_data

        grids = pane.locator(".k-grid").all()
        if not grids:
            return self._extract_standard_tab(tab_name, link_selector, pane_selector)

        for grid in grids:
            try:
                header_cells = grid.locator("th").all()
                col_headers  = [h.inner_text().strip() for h in header_cells]
                # value_cols = everything after "Variable" and "Unit"
                value_cols = [h for h in col_headers if h not in ("Variable", "Unit", "")]

                rows = grid.locator("tr[role='row']").all()
                for row in rows:
                    try:
                        cells = row.locator("td").all()
                        if len(cells) < 2:
                            continue
                        raw_name = cells[0].inner_text().strip().replace("*", "").strip()
                        if not raw_name or raw_name.lower() == "variable":
                            continue

                        if len(value_cols) <= 1:
                            value = cells[2].inner_text().strip() if len(cells) >= 3 else ""
                            tab_data[raw_name] = value
                        else:
                            for i, col_label in enumerate(value_cols):
                                cell_idx = 2 + i
                                value = cells[cell_idx].inner_text().strip() if len(cells) > cell_idx else ""
                                tab_data[f"{raw_name} - {col_label}"] = value
                    except Exception:
                        continue
            except Exception as e:
                log.debug(f"  Grid parse error in Operation tab: {e}")
                continue

        log.info(f"  Operation: {len(tab_data)} fields.")
        return tab_data

    # ------------------------------------------------------------------
    # Extractor 3: Consumption tab
    # Complex multi-grid layout. Each grid is prefixed with its section
    # title: "Fuel Oil::Main Engine::HFO::Mass", etc.
    # ------------------------------------------------------------------
    def _extract_consumption_tab(self, tab_name: str, link_selector: str, pane_selector: str) -> dict:
        tab_data = {}
        pane = self._click_tab_and_wait(tab_name, link_selector, pane_selector)
        if pane is None:
            return tab_data

        grids = pane.locator(".k-grid").all()
        for grid_idx, grid in enumerate(grids):
            try:
                section_title = self._find_grid_section_title(grid, grid_idx)
                col_headers   = [
                    th.inner_text().strip()
                    for th in grid.locator("th").all()
                    if th.inner_text().strip()
                ]

                rows = grid.locator("tr[role='row']").all()
                for row in rows:
                    try:
                        cells = row.locator("td").all()
                        if len(cells) == 0:
                            continue
                        row_key = cells[0].inner_text().strip().replace("*", "").strip()
                        if not row_key:
                            continue

                        if len(cells) == 2:
                            val = cells[1].inner_text().strip()
                            full_key = f"{section_title}::{row_key}" if section_title else row_key
                            tab_data[full_key] = val
                        elif len(cells) >= 3:
                            for col_i in range(1, len(cells)):
                                col_label = col_headers[col_i] if col_i < len(col_headers) else f"Col{col_i}"
                                val = cells[col_i].inner_text().strip()
                                full_key = (
                                    f"{section_title}::{row_key}::{col_label}"
                                    if section_title else f"{row_key}::{col_label}"
                                )
                                tab_data[full_key] = val
                    except Exception:
                        continue
            except Exception as e:
                log.debug(f"  Consumption grid {grid_idx} error: {e}")
                continue

        # Also capture plain (non-Kendo) tables — Fresh Water, Sludge sections
        try:
            plain_tables = pane.locator("table:not(.k-grid table)").all()
            for tbl_idx, tbl in enumerate(plain_tables):
                rows = tbl.locator("tr").all()
                for row in rows:
                    cells = row.locator("td").all()
                    if len(cells) == 2:
                        label = cells[0].inner_text().strip().replace("*", "")
                        val   = cells[1].inner_text().strip()
                        if label:
                            tab_data[f"Table{tbl_idx}::{label}"] = val
        except Exception:
            pass

        log.info(f"  Consumption: {len(tab_data)} fields.")
        return tab_data

    # ------------------------------------------------------------------
    # Helper: find nearest section heading for a grid element
    # ------------------------------------------------------------------
    def _find_grid_section_title(self, grid_locator, fallback_index: int) -> str:
        try:
            title = grid_locator.evaluate("""el => {
                let sib = el.previousElementSibling;
                while (sib) {
                    const tag = sib.tagName.toLowerCase();
                    if (['h1','h2','h3','h4','h5','h6'].includes(tag))
                        return sib.innerText.trim();
                    const pt = sib.querySelector('.panel-title, .k-header');
                    if (pt) return pt.innerText.trim();
                    sib = sib.previousElementSibling;
                }
                const parent = el.parentElement;
                if (parent) {
                    let psib = parent.previousElementSibling;
                    while (psib) {
                        const tag = psib.tagName.toLowerCase();
                        if (['h1','h2','h3','h4','h5','h6'].includes(tag))
                            return psib.innerText.trim();
                        psib = psib.previousElementSibling;
                    }
                }
                return null;
            }""")
            if title:
                return title.replace("\n", " ").strip()
        except Exception:
            pass
        return f"Section{fallback_index}"