import hashlib
import logging
import pandas as pd
from datetime import datetime
from sqlalchemy import text

# ===========================================================================
# IMPORTS
# Location of this file: backend/mariapps_pipeline/mariapps_persistence.py
#
# ".."  goes up one level → backend/
# So "..database"  resolves to backend/database.py
#    "..models"    resolves to backend/models.py
#    ".mariapps_mapping" resolves to backend/mariapps_pipeline/mariapps_mapping.py
# ===========================================================================
from ..database import SessionLocal
from ..models import (
    Vessel, VesselParticulars, RawMariAppsLog, MariAppsReportData,
    AnalysisData, DataQualityLog,
)
from ..mapping import map_mariapps_to_160, map_mariapps_to_analysis

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------------------------

def clean_dict(d: dict) -> dict:
    """Replace NaN / blank strings with None so PostgreSQL accepts them."""
    cleaned = {}
    for k, v in d.items():
        try:
            if pd.isna(v) or (isinstance(v, str) and v.strip() == ""):
                cleaned[k] = None
            else:
                cleaned[k] = v
        except Exception:
            cleaned[k] = v
    return cleaned


def get_audit_label(source_id: str) -> str:
    now = datetime.now()
    month = now.strftime('%b').upper()
    week_of_month = (now.day - 1) // 7 + 1
    return f"{str(source_id).upper()}-{month}-W{week_of_month}-{now.year}"


def _normalize_date(raw_date_str: str) -> str:
    """Normalize any date string to YYYY-MM-DD, stripping time portion."""
    if not raw_date_str:
        return ""
    date_part = str(raw_date_str).strip().split(' ')[0].strip()
    for fmt in ("%d-%b-%Y", "%d/%b/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(date_part, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_part


def _make_fingerprint(log_number: str, imo_number: str, log_date: str) -> str:
    normalized_date = _normalize_date(log_date)
    fp_string = f"{str(log_number).strip()}|{imo_number}|{normalized_date}"
    return hashlib.sha256(fp_string.encode()).hexdigest()


def _resolve_voyage_no(header: dict, excel: dict, nested: dict, row_data: dict) -> str:
    """Resolve Voyage/Leg number from all sources with garbage-value rejection."""
    def is_valid(v):
        if not v:
            return False
        s = str(v).strip()
        if len(s) <= 1:
            return False
        if s.lower() in ("on", "off", "yes", "no", "true", "false", "none", "null", "nan"):
            return False
        return True

    voyage_keys = [
        "Leg Number", "Leg No", "Voyage Number", "Voyage No",
        "Voyage Number - #", "Voyage Number_#", "Voyage_No",
        "voyage_number", "leg_number", "voyage_no",
    ]

    for source in [header, excel, nested, row_data]:
        for k in voyage_keys:
            v = source.get(k)
            if is_valid(v):
                return str(v).strip()

    # Broad scan for any key containing 'voyage' or 'leg'
    for source in [excel, nested, header]:
        for k, v in source.items():
            k_lower = k.lower()
            if ("voyage" in k_lower or "leg" in k_lower) and is_valid(v):
                return str(v).strip()

    return None


def _resolve_from_port(header: dict, excel: dict, nested: dict) -> str:
    """Resolve departure/from port from all available sources."""
    port_keys = [
        "Departure Port", "From Port", "From_Port", "Orig. Port",
        "Departure Port_Orig. Port", "departure_port", "from_port",
        "Origin Port", "Port of Departure",
    ]
    for source in [header, excel, nested]:
        for k in port_keys:
            v = source.get(k)
            if v and str(v).strip() not in ("", "None", "nan"):
                return str(v).strip()
    for source in [header, excel, nested]:
        for k, v in source.items():
            k_lower = k.lower()
            if ("from" in k_lower or "dep" in k_lower or "orig" in k_lower) and "port" in k_lower:
                if v and str(v).strip() not in ("", "None", "nan"):
                    return str(v).strip()
    return None


# ---------------------------------------------------------------------------
# ASSEMBLE FULL ROW_DATA WITH ALL 6 TABS
# ---------------------------------------------------------------------------

def build_full_row_data(
    row_data: dict,
    excel_data: dict = None,
    header_data: dict = None,
    tab_data: dict = None,
) -> dict:
    """
    Merges grid metadata + excel + header + all 6 tab dicts into one payload.
    This is what gets stored as raw_json in RawMariAppsLog.

    tab_data is the dict from MariAppsDetailExtractor.extract_details():
        { "Position": {...}, "Operation": {...}, "Consumption": {...},
          "Performance": {...}, "Machinery": {...}, "Fuel Stock": {...}, "KPI": {...} }

    Stored under keys that mariapps_mapping._extract_tabs() reads:
        Position_Data, Operation_Data, Consumption_Data,
        Performance_Data, Machinery_Data, Fuel_Stock_Data, KPI_Data
    """
    full = dict(row_data)

    if excel_data:
        full["Excel_Data"] = excel_data

    if header_data:
        full["Header_Data"] = header_data

    if tab_data:
        full["Position_Data"]    = tab_data.get("Position",    {})
        full["Operation_Data"]   = tab_data.get("Operation",   {})
        full["Consumption_Data"] = tab_data.get("Consumption", {})
        full["Performance_Data"] = tab_data.get("Performance", {})
        full["Machinery_Data"]   = tab_data.get("Machinery",   {})
        full["Fuel_Stock_Data"]  = tab_data.get("Fuel Stock",  {})
        full["KPI_Data"]         = tab_data.get("KPI",         {})

    return full


# ---------------------------------------------------------------------------
# MAIN PERSISTENCE HANDLER
# ---------------------------------------------------------------------------

class MariAppsPersistenceHandler:

    def is_already_processed(self, log_number: str, vessel_name: str, log_date: str) -> bool:
        db = SessionLocal()
        try:
            vessel_ref = db.query(Vessel).filter(
                Vessel.vessel_name.ilike(f"%{vessel_name}%")
            ).first()
            if not vessel_ref:
                log.error(f"Vessel '{vessel_name}' not found in DB.")
                return False
            fingerprint = _make_fingerprint(log_number, vessel_ref.imo_number, log_date)
            return db.query(RawMariAppsLog).filter(
                RawMariAppsLog.fingerprint == fingerprint
            ).first() is not None
        except Exception as e:
            log.error(f"Error checking duplicate for {log_number}: {e}")
            return False
        finally:
            db.close()

    def save_log(
        self,
        row_data: dict,
        excel_data: dict = None,
        header_data: dict = None,
        tab_data: dict = None,
    ) -> bool:
        """
        Saves one log record across 3 tables:
            RawMariAppsLog      → raw_json stores ALL 6 tabs + excel + header
            MariAppsReportData  → 160-column mapped table
            AnalysisData        → 57-column analysis table

        Parameters
        ----------
        row_data    : grid metadata (log_number, vessel, log_date, log_type)
        excel_data  : flat columns from the Excel export
        header_data : header form scan results
        tab_data    : all 6 detail-page tab dicts from extract_details()
        """
        db = SessionLocal()
        try:
            log_number   = str(row_data.get("log_number", "")).strip()
            vessel_name  = str(row_data.get("vessel", "")).strip()
            log_date_raw = str(row_data.get("log_date", "")).strip()
            log_date     = _normalize_date(log_date_raw)

            vessel_ref = db.query(Vessel).filter(
                Vessel.vessel_name.ilike(f"%{vessel_name}%")
            ).first()
            if not vessel_ref:
                log.error(f"Vessel '{vessel_name}' not found in DB.")
                return False

            header = header_data or {}
            excel  = excel_data  or {}
            nested = row_data.get("Excel_Data", {})  # backward compat

            # Build complete payload → goes into raw_json
            full_payload = build_full_row_data(row_data, excel_data, header_data, tab_data)

            leg_number   = _resolve_voyage_no(header, excel, nested, row_data)
            fingerprint  = _make_fingerprint(log_number, vessel_ref.imo_number, log_date)
            existing_raw = db.query(RawMariAppsLog).filter(
                RawMariAppsLog.fingerprint == fingerprint
            ).first()

            log_type = (
                nested.get("Log Type") or
                excel.get("Log Type") or
                row_data.get("log_type", "UNKNOWN")
            )
            cleaned_payload = clean_dict(full_payload)

            # DUPLICATE / CORRECTION GUARD — checked before inserting a raw row.
            # Identity alone (fingerprint) can't tell "already seen, unchanged"
            # from "already seen, but the master corrected it in MariApps
            # since" — both have the same log_number|vessel|date. Compare the
            # actual content against what's stored: identical -> same cheap
            # skip as before (no new row, just an audit log entry). Different
            # -> a real correction was found (only reachable when the caller
            # re-opens a recent log inside mariapps_pipeline.py's
            # RECHECK_WINDOW_DAYS, since outside that window a matching
            # fingerprint is skipped before the detail tabs are even opened)
            # -> update the existing raw row + its derived rows in place
            # instead of silently discarding the correction.
            is_correction = False
            if existing_raw is not None:
                if cleaned_payload == existing_raw.raw_json:
                    db.add(DataQualityLog(
                        raw_mariapps_id=existing_raw.id,
                        raw_report_id=None,
                        source_id="mari_apps",
                        vessel_name=vessel_name,
                        vessel_imo=vessel_ref.imo_number,
                        issue_type="DUPLICATE_REPORT",
                        event_type=log_type,
                        report_date=pd.to_datetime(log_date, errors='coerce'),
                        audit_period=get_audit_label("mari_apps"),
                    ))
                    db.commit()
                    log.info(f"UNCHANGED: Log {log_number} re-checked, no change.")
                    return True

                is_correction = True
                existing_raw.raw_json     = cleaned_payload
                existing_raw.log_type     = log_type
                existing_raw.leg_number   = leg_number
                existing_raw.extracted_at = datetime.now()
                db.add(DataQualityLog(
                    raw_mariapps_id=existing_raw.id,
                    raw_report_id=None,
                    source_id="mari_apps",
                    vessel_name=vessel_name,
                    vessel_imo=vessel_ref.imo_number,
                    issue_type="REPORT_CORRECTED",
                    event_type=log_type,
                    report_date=pd.to_datetime(log_date, errors='coerce'),
                    audit_period=get_audit_label("mari_apps"),
                ))
                raw_id = existing_raw.id
                db.flush()
            else:
                # 1. RAW LOG — stores everything as JSONB
                new_raw = RawMariAppsLog(
                    vessel_imo=vessel_ref.imo_number,
                    source_id="mari_apps",
                    log_number=log_number,
                    vessel_name=vessel_name,
                    log_date=log_date,
                    log_type=log_type,
                    leg_number=leg_number,
                    raw_json=cleaned_payload,
                    fingerprint=fingerprint,
                    is_duplicate=False,
                )
                db.add(new_raw)
                db.flush()
                raw_id = new_raw.id

            # Fetch vessel_particulars for KPI calculations
            vp_obj = db.query(VesselParticulars).filter_by(
                vessel_imo=vessel_ref.imo_number
            ).first()
            vessel_particulars_dict = {}
            if vp_obj:
                vessel_particulars_dict = {
                    c.name: getattr(vp_obj, c.name)
                    for c in VesselParticulars.__table__.columns
                }
            else:
                log.warning(f"[VP]  No vessel_particulars found for {vessel_name} ({vessel_ref.imo_number}) — KPI fields will be None.")

            # 3. 160-COLUMN MAPPED TABLE
            mapped_160 = map_mariapps_to_160(
                full_payload,
                excel_data=excel,
                header_data=header,
            )
            mapped_160_clean = clean_dict(mapped_160)
            existing_160 = (
                db.query(MariAppsReportData).filter_by(raw_report_id=raw_id).first()
                if is_correction else None
            )
            if existing_160:
                for k, v in mapped_160_clean.items():
                    setattr(existing_160, k, v)
            else:
                db.add(MariAppsReportData(
                    **mapped_160_clean,
                    vessel_imo=vessel_ref.imo_number,
                    source_id="mari_apps",
                    raw_report_id=raw_id,
                ))

            # 4. 57-COLUMN ANALYSIS TABLE
            flat_row = {}
            flat_row.update(nested)
            flat_row.update(excel)
            flat_row.update(header)
            flat_row.update({
                "log_number": log_number,
                "vessel":     vessel_name,
                "log_date":   log_date,
            })
            # Forward all 6 tab dicts so _extract_tabs() in mapping can find them
            if tab_data:
                flat_row["Position_Data"]    = full_payload.get("Position_Data",    {})
                flat_row["Operation_Data"]   = full_payload.get("Operation_Data",   {})
                flat_row["Consumption_Data"] = full_payload.get("Consumption_Data", {})
                flat_row["Performance_Data"] = full_payload.get("Performance_Data", {})
                flat_row["Machinery_Data"]   = full_payload.get("Machinery_Data",   {})
                flat_row["Fuel_Stock_Data"]  = full_payload.get("Fuel_Stock_Data",  {})
                flat_row["KPI_Data"]         = full_payload.get("KPI_Data",         {})

            mapped_57 = map_mariapps_to_analysis(
                flat_row,
                excel_data=excel,
                header_data=header,
                vessel_particulars=vessel_particulars_dict,
            )

            mapped_57["Voyage_No"] = leg_number
            if not mapped_57.get("From_Port"):
                mapped_57["From_Port"] = _resolve_from_port(header, excel, nested)

            mapped_57_clean = clean_dict(mapped_57)
            existing_57 = (
                db.query(AnalysisData).filter_by(raw_mariapps_id=raw_id).first()
                if is_correction else None
            )
            if existing_57:
                for k, v in mapped_57_clean.items():
                    setattr(existing_57, k, v)
            else:
                db.add(AnalysisData(
                    **mapped_57_clean,
                    vessel_imo=vessel_ref.imo_number,
                    source_id="mari_apps",
                    raw_mariapps_id=raw_id,
                    raw_report_id=None,
                ))

            db.commit()

            # ── Live-sync to expanded_mariapps_data (non-critical) ───────────
            # write_expanded_mariapps() upserts by raw_log_id (ON CONFLICT DO
            # UPDATE), so this is correct for both a fresh insert and a
            # correction without any branching here.
            try:
                from ..pipeline.expander import write_expanded_mariapps
                write_expanded_mariapps(
                    db, raw_id, vessel_ref.imo_number,
                    log_date, log_type, log_number, cleaned_payload,
                )
                db.commit()
            except Exception as exc:
                log.warning(f"Expanded MariApps write failed (non-critical): {exc}")

            # ── ISO 19030 calculation for this record (non-critical) ──────────
            try:
                from ..iso19030.runner import run_single
                from ..models import AnalysisData as _AD
                ad = db.query(_AD).filter(
                    _AD.raw_mariapps_id == raw_id
                ).first()
                if ad:
                    run_single(ad.id, db)
                    db.commit()
            except Exception as exc:
                log.warning(f"ISO 19030 calc failed (non-critical): {exc}")

            # Backfill From_Port for same voyage where it is null
            try:
                db.execute(text("""
                    UPDATE analysis_data a
                    SET "From_Port" = b."From_Port"
                    FROM analysis_data b
                    WHERE a."Voyage_No" = b."Voyage_No"
                      AND a.vessel_imo = b.vessel_imo
                      AND a."From_Port" IS NULL
                      AND b."From_Port" IS NOT NULL
                """))
                db.commit()
            except Exception as e:
                log.warning(f"[FROM_PORT_BACKFILL] Failed: {e}")
                db.rollback()

            log.info(f"{'CORRECTED' if is_correction else 'SAVED'}: Log {log_number} | Voyage={leg_number}")
            return True

        except Exception as e:
            db.rollback()
            log.error(f"DB ERROR for {row_data.get('log_number')}: {e}")
            return False
        finally:
            db.close()