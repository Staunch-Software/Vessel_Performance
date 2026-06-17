import os
import hashlib
import logging
from backend.database import SessionLocal
from backend.models import Vessel, RawNoonReport, NoonReportData, AnalysisData
from .excel_converter import clean_excel_report
from .column_mapping import map_old_to_160, map_old_to_analysis

log = logging.getLogger(__name__)

def process_historical_reports():
    folder_path = os.path.abspath("backend/data/old_reports")
    db = SessionLocal()

    for file in os.listdir(folder_path):
        if not file.endswith(".xlsx"): continue
        
        file_path = os.path.join(folder_path, file)
        print(f">>> Processing: {file}")
        
        df = clean_excel_report(file_path)

        for _, row in df.iterrows():
            try:
                data_dict = row.to_dict()
                
                # 1. Identify Vessel
                v_name = data_dict.get("Vessel Name") or file.split("-")[0].strip()
                vessel = db.query(Vessel).filter(Vessel.vessel_name.ilike(f"%{v_name}%")).first()
                
                if not vessel:
                    print(f"Skip: Vessel {v_name} not found")
                    continue

                # 2. Create Fingerprint (To prevent duplicates if script runs twice)
                date_str = str(data_dict.get("Date of Report"))
                fp_base = f"{vessel.imo_number}_{date_str}_{data_dict.get('Report Type')}"
                fingerprint = hashlib.sha256(fp_base.encode()).hexdigest()

                if db.query(RawNoonReport).filter_by(fingerprint=fingerprint).first():
                    continue

                # 3. Save to Staging (RawNoonReport)
                raw_entry = RawNoonReport(
                    vessel_imo=vessel.imo_number,
                    source_id="old_data",
                    raw_json=data_dict,
                    file_name=file,
                    fingerprint=fingerprint
                )
                db.add(raw_entry)
                db.flush()

                # 4. Map and Save to 160-column table
                mapped_160 = map_old_to_160(data_dict)
                report_entry = NoonReportData(
                    **mapped_160,
                    vessel_imo=vessel.imo_number,
                    source_id="old_data",
                    raw_report_id=raw_entry.id
                )
                db.add(report_entry)

                # 5. Map and Save to 57-column Analysis table
                mapped_57 = map_old_to_analysis(mapped_160)
                analysis_entry = AnalysisData(
                    **mapped_57,
                    vessel_imo=vessel.imo_number,
                    source_id="old_data",
                    raw_report_id=raw_entry.id
                )
                db.add(analysis_entry)
                
                db.commit()

            except Exception as e:
                db.rollback()
                print(f"Error in row: {e}")

    db.close()
    print("Historical processing complete.")