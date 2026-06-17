# ===========================================================================
# main_entry.py
# Location: backend/main_entry.py
# Run from project root: python -m backend.main_entry
# ===========================================================================

from backend.mariapps_pipeline import mariapps_pipeline
from backend.excel_processing.excel_converter import clean_excel_report

if __name__ == "__main__":
    print(">>> Starting MariApps scrape...")
    mariapps_pipeline.run()

    print(">>> Processing legacy Excel reports...")
    clean_excel_report() 