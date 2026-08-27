# ===========================================================================
# main_entry.py
# Location: backend/main_entry.py
# Run from project root: python -m backend.main_entry
# ===========================================================================

from backend.mariapps_pipeline import mariapps_pipeline, bunker_report_scraper
from backend.excel_processing.excel_converter import clean_excel_report

if __name__ == "__main__":
    print(">>> Starting MariApps scrape...")
    mariapps_pipeline.run()

    print(">>> Starting MariApps Bunker Report scrape...")
    bunker_report_scraper.run()

    print(">>> Processing legacy Excel reports...")
    clean_excel_report()