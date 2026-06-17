# ============================================================
# WNI AUTOMATED DATA PIPELINE
# ============================================================
# Purpose: Automated daily download of vessel noon reports from WNI portal
# 
# Process Flow:
# 1. Login to Weathernews portal using Playwright
# 2. Navigate to Logbook+ section
# 3. For each vessel in vessels.txt:
#    - Select vessel
#    - Set date filters to yesterday
#    - Download CSV report
#    - Parse multi-row headers
#    - Save to database
# 4. Log all operations for audit trail
# ============================================================

import os
import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from ..config import config
from ..database import init_db
from .processor import save_to_db
import logging
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# LOGGING CONFIGURATION
# ============================================================

load_dotenv()

LOG_FILE = config.PIPELINE_LOG

# 2. Configure logging: Using the centralized path and UTF-8 for Windows safety
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'), # Saves to logs/ folder
        logging.StreamHandler() # Also prints to your terminal
    ]
)

log = logging.getLogger(__name__)


# ============================================================
# CSV HEADER PROCESSING
# ============================================================

def clean_header(text):
    """
    Cleans Excel/CSV header text by removing formatting artifacts
    
    Removes:
    - Excel line break codes (_x000D_)
    - Newline and carriage return characters
    - Extra whitespace
    - Quotes and special characters
    
    Args:
        text: Raw header text from CSV
        
    Returns:
        Cleaned header string
    """
    text = str(text)

    # Remove Excel garbage characters
    text = text.replace("_x000D_", " ")
    text = text.replace("\n", " ")
    text = text.replace("\r", " ")

    # Normalize spacing (collapse multiple spaces)
    text = re.sub(r"\s+", " ", text)

    # Strip quotes and junk
    text = text.strip(" '\"")

    return text.strip()


def get_wni_headers(temp_csv):
    """
    Extracts and constructs proper column headers from WNI CSV files
    
    WNI CSV Structure:
    - Row 1: Group headers (e.g., "Engine", "Fuel Consumption")
    - Row 2: Item headers (e.g., "RPM", "HFO (mt)")
    
    This function combines them into: "Engine_RPM", "Fuel Consumption_HFO (mt)"
    
    Args:
        temp_csv: Path to downloaded CSV file
        
    Returns:
        List of cleaned, combined column headers
    """
    # Read first 2 rows without headers
    hdr = pd.read_csv(temp_csv, nrows=2, header=None)

    # Forward-fill group headers (they span multiple columns)
    groups = hdr.iloc[0].ffill().fillna("")
    items = hdr.iloc[1].fillna("")

    # Combine group and item headers
    combined = []
    for g, i in zip(groups, items):
        g_clean = clean_header(g)
        i_clean = clean_header(i)

        # Only combine if both exist and are different
        if g_clean and i_clean and g_clean.lower() != i_clean.lower():
            combined.append(f"{g_clean}_{i_clean}")
        else:
            combined.append(i_clean or g_clean)

    # Final normalization pass
    def final_normalize(header):
        header = str(header)
        # Remove any remaining newlines / carriage returns
        header = header.replace("\n", " ").replace("\r", " ")
        # Collapse ALL whitespace (this covers embedded newlines too)
        header = re.sub(r"\s+", " ", header)
        return header.strip()

    columns = [final_normalize(c) for c in combined]
    columns = [re.sub(r"\s+", " ", c).strip() for c in columns]

    return columns


# ============================================================
# DATE PICKER AUTOMATION
# ============================================================

def navigate_to_month(page, target_year, target_month):
    """
    Navigates the Logbook+ month picker to the target year/month.
    Returns True if target month reached, False if back button was disabled
    (meaning portal has no data before current displayed month — skip the target).
    """
    MONTH_MAP = {
        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
        "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
        "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12
    }

    max_clicks = 24
    clicks = 0

    while clicks < max_clicks:
        label = page.locator(r'text=/[A-Z][a-z]{2} \d{4}/').first.inner_text()
        parts = label.strip().split()
        current_month = MONTH_MAP.get(parts[0], 0)
        current_year = int(parts[1])

        if current_year == target_year and current_month == target_month:
            return True  # Reached target

        current_total = current_year * 12 + current_month
        target_total  = target_year  * 12 + target_month

        if target_total < current_total:
            back_btn = page.locator("button:has-text('<'), button[aria-label*='prev'], .month-prev").first
            if not back_btn.is_enabled():
                log.warning(
                    "Back button disabled — portal data starts at %s %d, skipping target %d/%d",
                    parts[0], current_year, target_month, target_year
                )
                return False  # Target month unavailable — tell caller to skip
            back_btn.click()
        else:
            next_btn = page.locator("button:has-text('>'), button[aria-label*='next'], .month-next").first
            try:
                next_btn.wait_for(state="visible", timeout=5000)
                next_btn.click()
            except Exception as e:
                log.warning("Next button click failed: %s — retrying after wait", e)
                page.wait_for_timeout(1000)
                next_btn.click()

        page.wait_for_timeout(800)
        clicks += 1

    if clicks == max_clicks:
        log.warning("Month navigation hit max clicks | target=%d/%d", target_month, target_year)

    return True


# ============================================================
# MAIN PIPELINE EXECUTION
# ============================================================

def run():
    init_db()
    log.info("Starting WNI pipeline")

    # Define dynamic date range
    # HISTORICAL_START_DATE = datetime(2026, 3, 31)
    # HISTORICAL_START_DATE = datetime(2025, 8, 1)
    HISTORICAL_START_DATE = datetime(2025, 12, 1)
    end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Build list of (month_start, month_end) tuples from Aug 1 → today
    month_ranges = []
    cursor = HISTORICAL_START_DATE
    while cursor <= end_date:
        month_start = cursor
        month_end = (cursor + relativedelta(months=1)) - relativedelta(days=1)
        if month_end > end_date:
            month_end = end_date
        month_ranges.append((month_start, month_end))
        cursor += relativedelta(months=1)

    # Output directory
    # --- LOCAL (original hardcoded path — uncomment to use) ---
    # EXCEL_OUTPUT_DIR = r"C:\Users\Seenu Maheshwaran\Documents\OZELLAR\WNI"
    # --- VM / CROSS-PLATFORM (env var, default <project_root>/data/wni) ---
    from ..config import config as _cfg
    EXCEL_OUTPUT_DIR = os.getenv("WNI_OUTPUT_DIR", str(_cfg.ROOT_DIR / "data" / "wni"))
    os.makedirs(EXCEL_OUTPUT_DIR, exist_ok=True)

    # Counters for summary report
    vessels_processed = 0
    vessels_failed = 0

    # ============================================================
    # BROWSER INITIALIZATION
    # ============================================================
    
    with sync_playwright() as p:
        # Launch headless Chromium browser
        browser = p.chromium.launch(
            headless=True, 
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        # Set timeouts for stability
        page.set_default_timeout(30000)
        page.set_default_navigation_timeout(60000)

        # ============================================================
        # WNI PORTAL LOGIN
        # ============================================================
        
        log.info("Opening Weathernews login page")
        page.goto(config.WNI_LOGIN_URL)

        # Click login button
        page.locator("#login_buttom").click()
        
        # Enter username
        page.get_by_role("textbox", name="Username or email address").fill(
            config.WNI_USERNAME
        )
        page.get_by_role("button", name="Continue").click()
        
        # Enter password
        page.get_by_role("textbox", name="Password").fill(
            config.WNI_PASSWORD
        )
        page.get_by_role("button", name="Continue").click()
        
        # Wait for login to complete
        page.wait_for_load_state("networkidle")
        log.info("Login successful")

        # ============================================================
        # NAVIGATE TO LOGBOOK+
        # ============================================================
        
        page.wait_for_selector("a", timeout=20000)
        
        # Find and click Logbook+ link using JavaScript
        page.evaluate("""
            [...document.querySelectorAll('a')]
              .find(a => a.innerText.includes('Logbook+'))
              .click()
        """)
        page.wait_for_load_state("networkidle")
        log.info("Logbook+ opened")

        # ============================================================
        # LOAD VESSEL LIST
        # ============================================================
        
        vessels_file = os.path.join(config.BASE_DIR, "vessels.txt")
        with open(vessels_file, "r", encoding="utf-8") as f:
            vessels = [v.strip() for v in f.readlines() if v.strip()]

        # ============================================================
        # --- DATE ITERATION LOGIC (Vessel-first, Month by Month) ---
        # ============================================================

        # Outer loop: one vessel at a time
        for vessel in vessels:
            # Extract clean vessel name (before any "/" character)
            v_name_clean = vessel.split("/")[0].strip()
            safe_vessel = v_name_clean.replace(" ", "_")

            # Excel filename: VESSEL_NAME_WNI.xlsx (all months combined)
            excel_filename = f"{safe_vessel}_WNI.xlsx"
            excel_path = os.path.join(EXCEL_OUTPUT_DIR, excel_filename)

            log.info("Processing vessel | name=%s | output=%s", v_name_clean, excel_filename)

            # Collect monthly DataFrames for this vessel
            all_months_df = []

            # Inner loop: month by month for this vessel
            for current_start_date, _ in month_ranges:
                month_label = current_start_date.strftime("%b %Y")

                try:
                    # ---- VESSEL SELECTION ----
                    vessel_box = page.get_by_role("textbox", name="Vessel Name")
                    vessel_box.fill("")  # Clear existing selection
                    vessel_box.type(vessel)  # Type vessel name
                    page.wait_for_timeout(1000)  # Wait for dropdown
                    page.locator(f"text='{vessel}'").first.click()  # Select from dropdown

                    # ---- NAVIGATE TO CORRECT MONTH ----
                    # Returns False if portal has no data for this month (back button disabled)
                    if not navigate_to_month(page, current_start_date.year, current_start_date.month):
                        log.info("Skipping unavailable month | vessel=%s | month=%s", v_name_clean, month_label)
                        continue
                    page.wait_for_load_state("networkidle")

                    # ---- DOWNLOAD CSV ----
                    with page.expect_download() as d:
                        page.get_by_role(
                            "button",
                            name="Download Table as CSV"
                        ).click()

                    download = d.value

                    # Save the download as a temporary CSV first
                    temp_csv = os.path.join(EXCEL_OUTPUT_DIR, f"{safe_vessel}_temp.csv")
                    download.save_as(temp_csv)

                    # Parse the CSV data
                    headers = get_wni_headers(temp_csv)
                    df = pd.read_csv(temp_csv, skiprows=2, names=headers)

                    # Clean up the temporary CSV
                    if os.path.exists(temp_csv):
                        os.remove(temp_csv)

                    # Skip if no data
                    if df.empty:
                        log.info("No data | vessel=%s | month=%s", v_name_clean, month_label)
                        continue

                    # Log what date range the portal actually returned
                    if "Date" in df.columns:
                        dates = pd.to_datetime(df["Date"], errors="coerce").dropna()
                        if not dates.empty:
                            log.info(
                                "Downloaded | vessel=%s | month=%s | rows=%d | date_range=%s to %s",
                                v_name_clean, month_label, len(df),
                                dates.min().date(), dates.max().date()
                            )

                    all_months_df.append(df)

                except Exception:
                    log.exception(
                        "Vessel processing failed | vessel=%s | month=%s | stage=processing",
                        v_name_clean,
                        month_label
                    )

            # ---- COMBINE ALL MONTHS & WRITE EXCEL ----
            if all_months_df:
                combined_df = pd.concat(all_months_df, ignore_index=True)

                # Deduplicate only on Date + Event Type (not all columns)
                dedup_cols = [c for c in ["Date", "Event Type"] if c in combined_df.columns]
                if dedup_cols:
                    combined_df.drop_duplicates(subset=dedup_cols, keep="first", inplace=True)
                else:
                    combined_df.drop_duplicates(inplace=True)

                # SAVE AS EXCEL (.xlsx) PERMANENTLY
                combined_df.to_excel(excel_path, index=False)
                log.info("Excel saved | vessel=%s | file=%s | rows=%d", v_name_clean, excel_filename, len(combined_df))

                # ---- DATA QUALITY CHECK ----
                csv_dup_count = combined_df.duplicated().sum()
                if csv_dup_count > 0:
                    log.warning(
                        "CSV-level duplicates | vessel=%s | count=%d",
                        v_name_clean,
                        csv_dup_count
                    )

                # Clean NaN values for database
                db_df = combined_df.replace({pd.NA: None, np.nan: None})

                # ---- SAVE TO DATABASE ----
                total_rows = len(db_df)
                inserted = 0
                duplicates = 0
                failed = 0

                # Process each row
                for _, row in db_df.iterrows():
                    result = save_to_db(
                        v_name_clean,
                        row.to_dict(),
                        excel_filename  # Pass the Excel filename for auditing
                    )

                    # Track results
                    if result == "success":
                        inserted += 1
                    elif result == "duplicate":
                        duplicates += 1
                    else:
                        failed += 1

                # Log summary for this vessel
                log.info(
                    "DB write summary | vessel=%s | total=%d | inserted=%d | duplicates=%d | failed=%d",
                    v_name_clean,
                    total_rows,
                    inserted,
                    duplicates,
                    failed
                )

                vessels_processed += 1

            else:
                log.warning("No data found across all months | vessel=%s", v_name_clean)
                vessels_failed += 1

        # Close browser
        browser.close()

    # ============================================================
    # PIPELINE COMPLETION
    # ============================================================
    
    log.info(
        "Pipeline completed | vessels_processed=%d | vessels_failed=%d",
        vessels_processed,
        vessels_failed
    )


# ============================================================
# DIRECT EXECUTION
# ============================================================

if __name__ == "__main__":
    run()