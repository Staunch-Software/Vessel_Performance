import datetime
import hashlib
import logging
import pandas as pd
from ..database import SessionLocal
from ..models import Vessel, RawNoonReport, NoonReportData, AnalysisData, DataQualityLog, VesselParticulars
from .mapping import map_row, map_analysis_row

def clean_dict(d):
    """Replaces NaN with None so Postgres accepts JSONB"""
    return {k: (None if pd.isna(v) else v) for k, v in d.items()}

def get_audit_label(source_id):
    """Generates a label like 'WNI-FEB-W1-2026'"""
    now = datetime.datetime.now() # Use full datetime module
    source_tag = str(source_id).upper()
    month = now.strftime('%b').upper()
    week_of_month = (now.day - 1) // 7 + 1
    year = now.year
    return f"{source_tag}-{month}-W{week_of_month}-{year}"

def save_to_db(vessel_name_raw, raw_data_dict, file_name):
    db = SessionLocal()
    try:
        # 1. Vessel Lookup
        clean_name = vessel_name_raw.split("/")[0].strip()
        vessel = db.query(Vessel).filter(Vessel.vessel_name.ilike(clean_name)).first()
        if not vessel:
            logging.error(f"Vessel '{clean_name}' not found in DB.")
            return "error"

        cleaned_json = clean_dict(raw_data_dict)
        
        # 1. CREATE PRECISE FINGERPRINT
        # We use the full Date string (Time included) and Event Type
        raw_date_str = str(cleaned_json.get("Date", "")).strip()
        event_type = str(cleaned_json.get("Event Type", "")).strip().upper()
        
        fp_str = f"{vessel.imo_number}|{raw_date_str}|{event_type}"
        fingerprint = hashlib.sha256(fp_str.encode()).hexdigest()

        # 3. CHECK IF DUPLICATE
        is_duplicate = db.query(RawNoonReport).filter(RawNoonReport.fingerprint == fingerprint).first() is not None

        # 4. SAVE RAW (The Staging layer - always save)
        raw_rec = RawNoonReport(
            vessel_imo=vessel.imo_number, 
            source_id="wni",
            raw_json=cleaned_json, 
            file_name=file_name, 
            fingerprint=fingerprint
        )
        db.add(raw_rec)
        db.flush() 

        
        if is_duplicate:
            # LOG TO QUALITY TABLE AND STOP
            db.add(DataQualityLog(
                raw_report_id=raw_rec.id,
                source_id="wni",
                vessel_name=vessel.vessel_name, 
                vessel_imo=vessel.imo_number,
                issue_type="DUPLICATE_REPORT", 
                event_type=cleaned_json.get('Event Type'),
                report_date=pd.to_datetime(cleaned_json.get('Date'), errors='coerce'),  
                audit_period=get_audit_label("wni") # FIXED: Passed "wni" string directly
            ))
            db.commit()
            return "duplicate"

        # 5. SAVE NOON REPORT (160 Columns)
        noon_data = map_row(cleaned_json).to_dict()
        
        print(f"DEBUG: log_date_utc value: {noon_data.get('log_date_utc')}")
        print(f"DEBUG: log_type value: {noon_data.get('log_type')}")
        
        # MANDATORY FIELD CHECK
        if not noon_data.get('log_date_utc') or not noon_data.get('log_type'):
            logging.error(f"Mandatory fields missing for {vessel.vessel_name}")
            db.rollback()
            return "error"
        
        db.add(NoonReportData(
            **clean_dict(noon_data), 
            vessel_imo=vessel.imo_number, 
            source_id="wni", 
            raw_report_id=raw_rec.id
        ))

         # 6. FETCH VESSEL SPECS AND SAVE ANALYSIS DATA
        specs = db.query(VesselParticulars).filter(VesselParticulars.vessel_imo == vessel.imo_number).first()
        
        if not specs:
            logging.warning(f"No VesselParticulars found for IMO {vessel.imo_number}. Using defaults.")

        analysis_data = map_analysis_row(cleaned_json, specs=specs)
        
        db.add(AnalysisData(
            **clean_dict(analysis_data), 
            vessel_imo=vessel.imo_number, 
            source_id="wni",
            raw_report_id=raw_rec.id
        ))

        db.commit()

        # ── Live-sync to expanded_wni_data (non-critical) ────────────────────
        try:
            from ..pipeline.expander import write_expanded_wni
            write_expanded_wni(db, raw_rec.id, vessel.imo_number, cleaned_json)
            db.commit()
        except Exception as exc:
            logging.warning(f"Expanded WNI write failed (non-critical): {exc}")

        # ── ISO 19030 calculation for this record (non-critical) ──────────────
        try:
            from ..iso19030.runner import run_single
            # Find the analysis_data id just inserted
            ad = db.query(AnalysisData).filter(
                AnalysisData.raw_report_id == raw_rec.id
            ).first()
            if ad:
                run_single(ad.id, db)
                db.commit()
        except Exception as exc:
            logging.warning(f"ISO 19030 calc failed (non-critical): {exc}")

        return "success"

    except Exception as e:
        db.rollback()
        logging.error(f"DB Error for {vessel_name_raw}: {e}")
        return "error"
    
    finally:
        db.close()