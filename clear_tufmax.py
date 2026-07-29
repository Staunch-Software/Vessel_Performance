import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

print("Clearing old TUFMAX data to allow re-processing with new mapping logic...")

# 1. Clear ProcessedEmails for TUFMAX
del_emails = db.execute(text("DELETE FROM processed_emails WHERE lower(vessel_name) LIKE '%tufmax%'"))
print(f"Cleared {del_emails.rowcount} processed email memory records for TUFMAX.")

# 2. Clear old DB records for TUFMAX (IMO: 9486295)
imo = '9486295'
for table in [
    "expanded_wni_data",
    "noon_report_data",
    "data_quality_logs",
    "analysis_data",
    "raw_noon_reports"
]:
    res = db.execute(text(f"DELETE FROM {table} WHERE vessel_imo = :imo"), {"imo": imo})
    print(f"Cleared {res.rowcount} records from {table}")

db.commit()
db.close()
print("Successfully cleared! Ready for a clean scrape. Run: python -m backend.pipeline.email_scraper --full")
