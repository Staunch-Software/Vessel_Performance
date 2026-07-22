from datetime import datetime
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any



# Import your existing database session utility
from backend.database import SessionLocal, _ensure_scrape_flags

# Import your models
from sqlalchemy import func, extract, and_, or_, not_, literal, literal_column, String
import re
from backend.models import (
    Vessel, VesselParticulars, AnalysisData, VesselParticularsResponse,
    NoonReportData, MariAppsReportData, DataQualityLog, RawMariAppsLog,
)

# --- Dependency to get DB session ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Define the Router ---
router = APIRouter(prefix="")

# --- ENDPOINT 1: Get Vessel List ---
@router.get("/vessels")
def read_vessels(db: Session = Depends(get_db)):
    try:
        _ensure_scrape_flags()  # make sure wni_enabled / mari_enabled exist + seeded
        vessels = db.query(Vessel).order_by(Vessel.vessel_name).all()
        return [
            {
                "imo_number": v.imo_number,
                "vessel_name": v.vessel_name,
                "wni_enabled": bool(v.wni_enabled),
                "mari_enabled": bool(v.mari_enabled),
            }
            for v in vessels
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error fetching vessels: {e}")


# --- ENDPOINT 1c: Toggle a vessel's per-source scrape flags ---
@router.patch("/vessels/{imo}/sources")
def update_vessel_sources(imo: str, body: dict, db: Session = Depends(get_db)):
    """Enable/disable a vessel in the WNI and/or MariApps scrape.

    Body accepts either or both of: {"wni_enabled": bool, "mari_enabled": bool}.
    Takes effect on the next pipeline run — no restart needed.
    """
    _ensure_scrape_flags()
    vessel = db.query(Vessel).filter(Vessel.imo_number == str(imo)).first()
    if not vessel:
        raise HTTPException(status_code=404, detail=f"Vessel {imo} not found.")

    if "wni_enabled" in body:
        vessel.wni_enabled = bool(body["wni_enabled"])
    if "mari_enabled" in body:
        vessel.mari_enabled = bool(body["mari_enabled"])

    try:
        db.commit()
        db.refresh(vessel)
        return {
            "imo_number": vessel.imo_number,
            "vessel_name": vessel.vessel_name,
            "wni_enabled": bool(vessel.wni_enabled),
            "mari_enabled": bool(vessel.mari_enabled),
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update vessel sources: {e}")


# --- ENDPOINT 1b: Create a new vessel ---
@router.post("/vessels")
def create_vessel(body: dict, db: Session = Depends(get_db)):
    imo  = str(body.get("imo_number", "")).strip()
    name = str(body.get("vessel_name", "")).strip()

    if not imo or not name:
        raise HTTPException(status_code=400, detail="Both IMO number and vessel name are required.")

    # IMO numbers are 7 digits — basic validation
    if not imo.isdigit() or not (6 <= len(imo) <= 10):
        raise HTTPException(status_code=400, detail="IMO number must be 6–10 digits.")

    existing = db.query(Vessel).filter(Vessel.imo_number == imo).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Vessel with IMO {imo} already exists ({existing.vessel_name})."
        )

    try:
        vessel = Vessel(imo_number=imo, vessel_name=name)
        db.add(vessel)
        db.commit()
        db.refresh(vessel)
        logging.info(f"New vessel created: {name} (IMO {imo})")
        return {"imo_number": vessel.imo_number, "vessel_name": vessel.vessel_name}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create vessel: {e}")

# --- ENDPOINT 2: Get Vessel Specs ---
@router.get("/vessel/{imo}/specs", response_model=VesselParticularsResponse)
def get_vessel_specs(imo: str, db: Session = Depends(get_db)):
    specs = db.query(VesselParticulars).filter(VesselParticulars.vessel_imo == imo).first()
    if not specs:
        raise HTTPException(status_code=404, detail="Vessel particulars not found")
    return specs

# ... (all other imports and functions) ...

# --- ENDPOINT 3: Query Analysis Data ---
# --- ENDPOINT 3: Query Analysis Data ---
@router.get("/detail/{id}", response_model=Dict[str, Any])
def get_detail_data(id: int, db: Session = Depends(get_db)):
    try:
        analysis_record = db.query(AnalysisData).filter(AnalysisData.id == id).first()
        if not analysis_record:
            raise HTTPException(status_code=404, detail="Not found")

        # --- ADD THE MISSING KEYS HERE ---
        record_dict = {
            "id": analysis_record.id,
            "vessel_imo": analysis_record.vessel_imo, # CRITICAL: Needed for the next API call
            "Voyage_No": analysis_record.Voyage_No,   # CRITICAL: Needed for the next API call
            "Record_ID": analysis_record.Record_ID,
            "Date": analysis_record.Date.isoformat() if analysis_record.Date else None,
            "Time_UTC": analysis_record.Time_UTC,
            "From_Port": analysis_record.From_Port,
            "To_Port": analysis_record.To_Port,
            "Loading_Cond": analysis_record.Loading_Cond,
            "STW_kn": analysis_record.STW_kn,
            "SOG_kn": analysis_record.SOG_kn,
            "ME_FOC_MT": analysis_record.ME_FOC_MT,
            "AE_FOC_MT": analysis_record.AE_FOC_MT,
            "Shaft_Power_kW": analysis_record.Shaft_Power_kW,
            "Shaft_RPM": analysis_record.Shaft_RPM,
            "SFOC_gkWh": analysis_record.SFOC_gkWh,
            "True_Wind_Spd_ms": analysis_record.True_Wind_Spd_ms,
            "Sig_Wave_Ht_m": analysis_record.Sig_Wave_Ht_m,
            "Current_Spd_kn": analysis_record.Current_Spd_kn,
            "Mean_Draft_m": analysis_record.Mean_Draft_m,
            "Draft_Fwd_m": analysis_record.Draft_Fwd_m,
            "Draft_Aft_m": analysis_record.Draft_Aft_m,
            "Distance_nm": analysis_record.Distance_nm,
            "Duration_h": analysis_record.Duration_h,
            "Power_Dev_pct": analysis_record.Power_Dev_pct,
            "AE_1_POWER_KW": analysis_record.AE_1_POWER_KW
        }
        return record_dict
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ENDPOINT 5: Get Voyage List filtered by vessel ---
@router.get("/voyages")
def get_voyages(
    vessel_imo: str = None,
    source_id:  str = None,
    loading_cond: str = None,
    db: Session = Depends(get_db)
):
    try:
        q = db.query(AnalysisData.Voyage_No).distinct().filter(
            AnalysisData.Voyage_No != None,
            AnalysisData.Voyage_No != ""
        )
        if vessel_imo:
            q = q.filter(AnalysisData.vessel_imo == vessel_imo)
        # Only return voyages that belong to the selected source
        if source_id and source_id != "all":
            q = q.filter(AnalysisData.source_id == source_id)
        if loading_cond and loading_cond.lower() != "all":
            lc = loading_cond.lower()
            if lc == "laden":
                q = q.filter(func.upper(AnalysisData.Loading_Cond).in_(("LADEN", "L", "LD")))
            elif lc == "ballast":
                q = q.filter(func.upper(AnalysisData.Loading_Cond).in_(("BALLAST", "B", "BL")))
            else:
                q = q.filter(AnalysisData.Loading_Cond.ilike(loading_cond))

        voyages = q.order_by(AnalysisData.Voyage_No).all()
        return [v[0] for v in voyages]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error fetching voyages: {e}")
    
@router.post("/query", response_model=List[Dict[str, Any]])
async def query_analysis_data(filters: dict, db: Session = Depends(get_db)):
    """
    Fetches all analysis_data columns + event_type (log_type from source tables).
    Filters: vessel_imo, voyageNo, fromDate, toDate, loadingConditions, source_id
    """
    try:
        voyage_no         = filters.get("voyageNo")
        voyage_nos        = filters.get("voyageNos")    # optional list (multi-select)
        from_date_str     = filters.get("fromDate")
        to_date_str       = filters.get("toDate")
        loading_conditions= filters.get("loadingConditions", [])
        vessel_imo        = filters.get("vessel_imo")
        source_id         = filters.get("source_id")   # 'wni' | 'mari_apps' | None (all)

        logging.info(f"Backend received filters: {filters}")

        # LEFT JOIN both source tables to get log_type as event_type
        event_type_col = func.coalesce(
            NoonReportData.log_type,
            MariAppsReportData.log_type,
        ).label("event_type")
        
        log_date_col = func.coalesce(
            RawMariAppsLog.log_date,
            func.cast(NoonReportData.log_date, String),
            func.cast(MariAppsReportData.log_date, String)
        ).label("log_date")

        query = (
            db.query(AnalysisData, event_type_col, log_date_col)
            .outerjoin(
                NoonReportData,
                NoonReportData.raw_report_id == AnalysisData.raw_report_id,
            )
            .outerjoin(
                MariAppsReportData,
                MariAppsReportData.raw_report_id == AnalysisData.raw_mariapps_id,
            )
            .outerjoin(
                RawMariAppsLog,
                RawMariAppsLog.id == MariAppsReportData.raw_report_id,
            )
        )

        if vessel_imo:
            query = query.filter(AnalysisData.vessel_imo == vessel_imo)

        # source_id filter (All = no filter)
        if source_id and source_id != "all":
            query = query.filter(AnalysisData.source_id == source_id)

        # FIX: Voyage_No is VARCHAR — never compare to integer.
        # Accept either a single voyageNo or a voyageNos list (multi-select).
        voyage_list = []
        if voyage_nos:
            voyage_list = [str(v).strip() for v in voyage_nos if str(v).strip()]
        elif voyage_no:
            voyage_list = [str(voyage_no).strip()]

        if voyage_list:
            conds = []
            for voyage_str in voyage_list:
                conds.append(AnalysisData.Voyage_No == voyage_str)
                try:
                    voyage_int_str = str(int(voyage_str.split()[0]))
                    if voyage_int_str != voyage_str:
                        conds.append(AnalysisData.Voyage_No == voyage_int_str)
                except (ValueError, IndexError):
                    pass
            query = query.filter(or_(*conds))

        if from_date_str and from_date_str != "None":
            query = query.filter(AnalysisData.Date >= datetime.strptime(from_date_str, '%Y-%m-%d'))

        if to_date_str and to_date_str != "None":
            query = query.filter(AnalysisData.Date <= datetime.strptime(to_date_str, '%Y-%m-%d'))

        if loading_conditions:
            conds = []
            for lc in loading_conditions:
                l = lc.lower()
                if l == "laden":
                    conds.append(func.upper(AnalysisData.Loading_Cond).in_(("LADEN", "L", "LD")))
                elif l == "ballast":
                    conds.append(func.upper(AnalysisData.Loading_Cond).in_(("BALLAST", "B", "BL")))
                else:
                    conds.append(AnalysisData.Loading_Cond.ilike(lc))
            if conds:
                query = query.filter(or_(*conds))

        results = query.order_by(AnalysisData.Date.desc()).all()
        logging.info(f"Query returned {len(results)} results.")

        def _row(r, event_type, log_date):
            return {
                "event_type": event_type,
                "log_date": str(log_date) if log_date else None,
                "id": r.id,
                "vessel_imo": r.vessel_imo,
                "source_id": r.source_id,
                "Record_ID": r.Record_ID,
                "Date": r.Date.isoformat() if r.Date else None,
                "Time_UTC": r.Time_UTC,
                "Voyage_No": r.Voyage_No,
                "From_Port": r.From_Port,
                "To_Port": r.To_Port,
                "Loading_Cond": r.Loading_Cond,
                "STW_kn": r.STW_kn,
                "SOG_kn": r.SOG_kn,
                "Heading_deg": r.Heading_deg,
                "Distance_nm": r.Distance_nm,
                "Duration_h": r.Duration_h,
                "Draft_Fwd_m": r.Draft_Fwd_m,
                "Draft_Aft_m": r.Draft_Aft_m,
                "Mean_Draft_m": r.Mean_Draft_m,
                "Displacement_MT": r.Displacement_MT,
                "Trim_m": r.Trim_m,
                "ME_Energy_Meter_Reading_KWh": r.ME_Energy_Meter_Reading_KWh,
                "Shaft_Power_kW": r.Shaft_Power_kW,
                "Shaft_RPM": r.Shaft_RPM,
                "ME_COMMON_MASS_FLOWMETER_MT": r.ME_COMMON_MASS_FLOWMETER_MT,
                "AE_1_ENERGY_READING_KWh": r.AE_1_ENERGY_READING_KWh,
                "A_E_1_RUNNING_HOURS": r.A_E_1_RUNNING_HOURS,
                "AE_1_POWER_KW": r.AE_1_POWER_KW,
                "AE_2_ENERGY_READING_KWh": r.AE_2_ENERGY_READING_KWh,
                "A_E_2_RUNNING_HOURS": r.A_E_2_RUNNING_HOURS,
                "AE_2_POWER_KW": r.AE_2_POWER_KW,
                "AE_3_ENERGY_READING_KWh": r.AE_3_ENERGY_READING_KWh,
                "A_E_3_RUNNING_HOURS": r.A_E_3_RUNNING_HOURS,
                "AE_3_POWER_KW": r.AE_3_POWER_KW,
                "AE_MASS_FLOWMETER_IN": r.AE_MASS_FLOWMETER_IN,
                "AE_FLOWMETER_READING_OUT": r.AE_FLOWMETER_READING_OUT,
                "ME_FOC_MT": r.ME_FOC_MT,
                "AE_FOC_MT": r.AE_FOC_MT,
                "Est_Power_kW": r.Est_Power_kW,
                "SFOC_gkWh": r.SFOC_gkWh,
                "Rel_Wind_Spd_ms": r.Rel_Wind_Spd_ms,
                "Rel_Wind_Dir_deg": r.Rel_Wind_Dir_deg,
                "True_Wind_Spd_ms": r.True_Wind_Spd_ms,
                "True_Wind_Dir_deg": r.True_Wind_Dir_deg,
                "Sig_Wave_Ht_m": r.Sig_Wave_Ht_m,
                "Wave_Period_s": r.Wave_Period_s,
                "Wave_Dir_deg": r.Wave_Dir_deg,
                "Swell_Ht_m": r.Swell_Ht_m,
                "Swell_Period_s": r.Swell_Period_s,
                "Swell_Dir_deg": r.Swell_Dir_deg,
                "Water_Temp_C": r.Water_Temp_C,
                "Water_Depth_m": r.Water_Depth_m,
                "Current_Spd_kn": r.Current_Spd_kn,
                "Current_Dir_deg": r.Current_Dir_deg,
                "Rudder_Angle_deg": r.Rudder_Angle_deg,
                "P_wind_kW": r.P_wind_kW,
                "P_wave_kW": r.P_wave_kW,
                "P_temp_kW": r.P_temp_kW,
                "VTI": r.VTI,
                "Power_Dev_pct": r.Power_Dev_pct,
                "Speed_Loss_pct": r.Speed_Loss_pct,
            }

        # results is a list of (AnalysisData, event_type, log_date) tuples
        return [_row(r, et, ld) for r, et, ld in results]

    except Exception as e:
        logging.error(f"Error in /query endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load analysis: {e}")
    
@router.get("/voyage/series")
def get_voyage_series(voyage_no: str, vessel_imo: str, db: Session = Depends(get_db)):
    results = db.query(
        AnalysisData,
        NoonReportData,
        MariAppsReportData
    ).outerjoin(
        NoonReportData, AnalysisData.raw_report_id == NoonReportData.raw_report_id
    ).outerjoin(
        MariAppsReportData, AnalysisData.raw_mariapps_id == MariAppsReportData.raw_report_id
    ).filter(
        AnalysisData.Voyage_No == str(voyage_no),
        AnalysisData.vessel_imo == str(vessel_imo)
    ).order_by(AnalysisData.Date.asc()).all()
    
    out = []
    for row in results:
        ad = row[0]
        noon = row[1]
        mariapps = row[2]
        
        # Determine the source model to fetch lat/lon and event_type
        source_model = noon if noon else (mariapps if mariapps else None)
        
        out.append({
            "Date": ad.Date.isoformat() if ad.Date else None,
            "Voyage_No": ad.Voyage_No,
            "Loading_Cond": ad.Loading_Cond,
            "From_Port": ad.From_Port,
            "To_Port": ad.To_Port,
            "STW_kn": ad.STW_kn,
            "SOG_kn": ad.SOG_kn,
            "ME_FOC_MT": ad.ME_FOC_MT,
            "AE_FOC_MT": ad.AE_FOC_MT,
            "Shaft_Power_kW": ad.Shaft_Power_kW,
            "Shaft_RPM": ad.Shaft_RPM,
            "SFOC_gkWh": ad.SFOC_gkWh,
            "True_Wind_Spd_ms": ad.True_Wind_Spd_ms,
            "True_Wind_Dir_deg": getattr(ad, 'True_Wind_Dir_deg', None),
            "BF_Wind": getattr(ad, 'BF_Wind', None),
            "Sig_Wave_Ht_m": ad.Sig_Wave_Ht_m,
            "Swell_Ht_m": ad.Swell_Ht_m,
            "Current_Spd_kn": ad.Current_Spd_kn,
            "Swell_Dir_deg": getattr(ad, 'Swell_Dir_deg', None),
            "Current_Dir_deg": getattr(ad, 'Current_Dir_deg', None),
            "Mean_Draft_m": ad.Mean_Draft_m,
            "Draft_Fwd_m": getattr(ad, 'Draft_Fwd_m', None),
            "Draft_Aft_m": getattr(ad, 'Draft_Aft_m', None),
            "Trim_m": ad.Trim_m,
            "Displacement_MT": ad.Displacement_MT,
            "VTI": ad.VTI,
            "Speed_Loss_pct": ad.Speed_Loss_pct,
            "Water_Temp_C": ad.Water_Temp_C,
            "Power_Dev_pct": ad.Power_Dev_pct,
            "Distance_nm": ad.Distance_nm,
            "Duration_h": getattr(ad, 'Duration_h', None),
            "event_type": getattr(source_model, 'log_type', getattr(source_model, 'event_type', None)) if source_model else getattr(ad, 'event_type', None),
            "Boiler_FOC_MT": getattr(ad, 'Boiler_FOC_MT', None),
            "lat_degree": getattr(source_model, 'lat_degree', None) if source_model else None,
            "lat_minutes": getattr(source_model, 'lat_minutes', None) if source_model else None,
            "lat_direction": getattr(source_model, 'lat_direction', None) if source_model else None,
            "lon_degree": getattr(source_model, 'lon_degree', None) if source_model else None,
            "lon_minutes": getattr(source_model, 'lon_minutes', None) if source_model else None,
            "lon_direction": getattr(source_model, 'lon_direction', None) if source_model else None,
        })
        
    return out

# backend/routers/analysis.py

from sqlalchemy import func

@router.get("/voyage/summary")
def get_voyage_summary(voyage_no: str, vessel_imo: str, db: Session = Depends(get_db)):
    """
    Returns aggregated voyage-level summary for the detail page.
    Computes departure/arrival times, totals, and averages from all records.
    """
    records = db.query(AnalysisData).filter(
        AnalysisData.Voyage_No == str(voyage_no),
        AnalysisData.vessel_imo == str(vessel_imo)
    ).order_by(AnalysisData.Date.asc()).all()

    if not records:
        raise HTTPException(status_code=404, detail="No voyage records found")

    first = records[0]   # earliest record = departure
    last  = records[-1]  # latest record  = arrival

    total_me_foc   = sum(r.ME_FOC_MT  or 0 for r in records)
    total_ae_foc   = sum(r.AE_FOC_MT  or 0 for r in records)
    total_distance = sum(r.Distance_nm or 0 for r in records)
    total_duration = sum(r.Duration_h  or 0 for r in records)

    avg_speed = total_distance / total_duration if total_duration > 0 else None
    avg_sfoc  = (
        sum(r.SFOC_gkWh or 0 for r in records) / len(records)
        if records else None
    )
    avg_power = (
        sum(r.Shaft_Power_kW or 0 for r in records) / len(records)
        if records else None
    )

    return {
        # Identity
        "Voyage_No":       first.Voyage_No,
        "vessel_imo":      first.vessel_imo,
        "Loading_Cond":    first.Loading_Cond,
        "From_Port":       first.From_Port,
        "To_Port":         last.To_Port,

        # ✅ Departure & Arrival — derived from first/last records
        "Departure_Time":  first.Date.strftime("%d %b %Y %H:%M") if first.Date else None,
        "Arrival_Date":    last.Date.isoformat() if last.Date else None,
        "Arrival_Time":    last.Date.strftime("%d %b %Y %H:%M") if last.Date else None,

        # ✅ Draft — from first (departure) record
        "Draft_Fwd_m":     first.Draft_Fwd_m,
        "Draft_Aft_m":     first.Draft_Aft_m,

        # ✅ Voyage totals
        "Distance_nm":     round(total_distance, 2),
        "Duration_h":      round(total_duration, 2),
        "Avg_Speed_kn":    round(avg_speed, 2) if avg_speed else None,
        "ME_FOC_MT":       round(total_me_foc, 2),

        # ✅ DO/GO & LNG — currently null (no column), explicit None for clarity
        "ae_lfo_mt":       None,   # Add DB column when available
        "lng_con":         None,   # Add DB column when available

        # ✅ Performance
        "SFOC_gkWh":       round(avg_sfoc, 2) if avg_sfoc else None,
        "Shaft_Power_kW":  round(avg_power, 2) if avg_power else None,
        "Power_Dev_pct":   first.Power_Dev_pct,

        # ✅ Deltas (hardcoded for now — replace when CP baseline exists)
        "fuel_delta":      None,
        "time_delta":      None,
    }

# ADD this endpoint to vessel_routes.py:
@router.get("/fleet/status")
def get_fleet_status(db: Session = Depends(get_db)):
    try:
        vessels = db.query(Vessel).all()
        result = []
        for v in vessels:
            # Get latest analysis record for this vessel
            latest = db.query(AnalysisData)\
                .filter(AnalysisData.vessel_imo == str(v.imo_number))\
                .order_by(AnalysisData.Date.desc())\
                .first()
            
            earliest = db.query(AnalysisData)\
              .filter(AnalysisData.vessel_imo == str(v.imo_number))\
              .order_by(AnalysisData.Date.asc())\
              .first()

            # Get vessel particulars
            specs = db.query(VesselParticulars)\
                .filter(VesselParticulars.vessel_imo == str(v.imo_number))\
                .first()

            result.append({
                "id": v.imo_number,
                "vesselName": v.vessel_name,
                "vesselType": specs.vessel_type if specs else "—",
                "imo": str(v.imo_number),
                "speed": str(latest.STW_kn) if latest and latest.STW_kn else "0.0",
                "cargoStatus": latest.Loading_Cond if latest else "—",
                "cargoQuantity": f"{latest.Displacement_MT:,.0f} MT" if latest and latest.Displacement_MT else "—",
                "heading": str(latest.Heading_deg) if latest and latest.Heading_deg else "—",
                "updatedOn": latest.Date.strftime("%Y-%m-%d %H:%M") if latest and latest.Date else "—",
                "vesselMoment": "Underway" if latest and latest.STW_kn and float(latest.STW_kn) > 0.5 else "At Anchor",
                "lastPort": latest.From_Port if latest else "—",
                "nextPort": latest.To_Port if latest else "—",
                "presentPort": latest.From_Port if latest else "—",
                "etdDate": earliest.Date.strftime("%d %b %Y") if earliest and earliest.Date else "—",
                "etaFull": latest.Date.strftime("%d %b %Y %H:%M") if latest and latest.Date else "—",
                "etaDate": latest.Date.strftime("%d %b %Y") if latest and latest.Date else "—",
                "agency": {
                    "owners": {
                        "company": "—", "contact": "—",
                        "address": "—", "phone": "—", "email": "—"
                    },
                    "charterers": {
                        "company": "—", "contact": "—",
                        "address": "—", "phone": "—", "email": "—"
                    }
                }
            })
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fleet status error: {e}")


# ── FLEET STATUS VOYAGES — latest record per vessel from SSM scrape ───────────
@router.get("/fleet/voyages")
def get_fleet_voyages(db: Session = Depends(get_db)):
    """
    Returns the most recent fleet status record for each vessel,
    scraped from the Weathernews SSM (Fleet Status Monitoring) map page.
    Used by the new FleetStatusPage React component to power the Leaflet map
    and the data table.
    """
    try:
        from backend.models import FleetStatusData, VesselParticulars
        from sqlalchemy import func

        # Subquery: latest scraped_at per vessel_name
        latest_sub = (
            db.query(
                FleetStatusData.vessel_name,
                func.max(FleetStatusData.scraped_at).label("max_scraped")
            )
            .group_by(FleetStatusData.vessel_name)
            .subquery()
        )

        records = (
            db.query(FleetStatusData, VesselParticulars)
            .join(
                latest_sub,
                (FleetStatusData.vessel_name == latest_sub.c.vessel_name) &
                (FleetStatusData.scraped_at  == latest_sub.c.max_scraped)
            )
            .outerjoin(
                VesselParticulars,
                FleetStatusData.imo == VesselParticulars.vessel_imo
            )
            .order_by(FleetStatusData.vessel_name)
            .all()
        )

        return [
            {
                "vessel_name":      r.FleetStatusData.vessel_name,
                "imo":              r.FleetStatusData.imo,
                "callsign":         r.FleetStatusData.callsign,
                "ship_type":        r.FleetStatusData.ship_type,
                "lat":              r.FleetStatusData.lat,
                "lon":              r.FleetStatusData.lon,
                "speed":            r.FleetStatusData.speed,
                "heading":          r.FleetStatusData.heading,
                "status":           r.FleetStatusData.status,
                "pos_date":         r.FleetStatusData.pos_date,
                "last_port":        r.FleetStatusData.last_port,
                "etd":              r.FleetStatusData.etd,
                "next_port":        r.FleetStatusData.next_port,
                "eta":              r.FleetStatusData.eta,
                "voyage_number":    r.FleetStatusData.voyage_number,
                "port_alert":       r.FleetStatusData.port_alert,
                "coastal_storm":    r.FleetStatusData.coastal_storm,
                "ocean_storm":      r.FleetStatusData.ocean_storm,
                "tropical_cyclone": r.FleetStatusData.tropical_cyclone,
                "pos_diff":         r.FleetStatusData.pos_diff,
                "report_missing":   r.FleetStatusData.report_missing,
                
                "dwt":              r.VesselParticulars.deadweight if r.VesselParticulars else r.FleetStatusData.dwt,
                "rep_time":         r.FleetStatusData.rep_time,
                "rep_type":         r.FleetStatusData.rep_type,
                "service":          r.FleetStatusData.service,
                "alert_detail":     r.FleetStatusData.alert_detail,
                "rta":              r.FleetStatusData.rta,
                
                "scraped_at":       r.FleetStatusData.scraped_at.isoformat() if r.FleetStatusData.scraped_at else None,
                
                "flag_code":        r.FleetStatusData.flag_code or (r.VesselParticulars.flag if r.VesselParticulars else None),
                "build_date":       r.FleetStatusData.build_date or (str(r.VesselParticulars.year_built) if (r.VesselParticulars and r.VesselParticulars.year_built) else None),
                "length":           r.FleetStatusData.length or (round(r.VesselParticulars.length_overall, 2) if (r.VesselParticulars and r.VesselParticulars.length_overall) else None),
                "breadth":          r.FleetStatusData.breadth or (round(r.VesselParticulars.beam, 2) if (r.VesselParticulars and r.VesselParticulars.beam) else None),
                "depth":            r.FleetStatusData.depth or (round(r.VesselParticulars.depth_m, 2) if (r.VesselParticulars and r.VesselParticulars.depth_m) else None),
                "draft":            r.FleetStatusData.draft or (round(r.VesselParticulars.design_draft, 3) if (r.VesselParticulars and r.VesselParticulars.design_draft) else None),
                "gross_tonnage":    r.FleetStatusData.gross_tonnage or (round(r.VesselParticulars.gross_tonnage, 0) if (r.VesselParticulars and r.VesselParticulars.gross_tonnage) else None),
                "engine_builder":   r.FleetStatusData.engine_builder or (r.VesselParticulars.me_engine_type if (r.VesselParticulars and r.VesselParticulars.me_engine_type) else None),
                "power_mcr":        r.FleetStatusData.power_mcr or (round(r.VesselParticulars.me_engine_mcr_kw, 0) if (r.VesselParticulars and r.VesselParticulars.me_engine_mcr_kw) else None),
                "rpm_mcr":          r.FleetStatusData.rpm_mcr or (round(r.VesselParticulars.me_mcr_rpm, 1) if (r.VesselParticulars and r.VesselParticulars.me_mcr_rpm) else None),
                "teu":              r.FleetStatusData.teu   or None,
                "email":            r.FleetStatusData.email or None,
                "fax":              r.FleetStatusData.fax   or None,
                "phone":            r.FleetStatusData.phone or None
            }
            for r in records
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fleet voyages error: {e}")

# ── VESSEL REPORT HEALTH ─────────────────────────────────────────────────────
@router.get("/vessel-report")
def get_vessel_report(year: int = None, ship_group: str = None, db: Session = Depends(get_db)):
    """
    Returns per-vessel discrepancy counts for the Vessel Report Health page.
    Discrepancy categories computed from analysis_data null/missing fields:
      - missing_report_wni      : gaps in daily date sequence for WNI
      - missing_report_mariapps : gaps in daily date sequence for MariApps
      - rob_consumption : null ME_FOC_MT or AE_FOC_MT
      - distance        : null Distance_nm
      - cargo_weight    : null Displacement_MT
      - bunkering       : DUPLICATE_REPORT entries in data_quality_logs
    """
    from datetime import timedelta, date as _date
    try:
        vessels = db.query(Vessel).order_by(Vessel.vessel_name).all()
        result  = []

        for v in vessels:
            imo = str(v.imo_number)

            # Derive ship group from first word of vessel name
            vessel_group = v.vessel_name.split()[0] if v.vessel_name else "OTHER"
            if ship_group and ship_group.lower() != "all":
                if vessel_group.upper() != ship_group.upper():
                    continue

            # ── Base query for this vessel + year ──
            q = db.query(AnalysisData).filter(AnalysisData.vessel_imo == imo)
            if year:
                q = q.filter(extract("year", AnalysisData.Date) == year)

            records = q.all()

            # Helper to calculate missing reports for a specific subset of records
            def calc_missing(subset):
                dates = sorted({r.Date for r in subset if r.Date})
                if not dates:
                    return None
                first = dates[0]
                last  = dates[-1]
                today     = _date.today()
                yesterday = today - timedelta(days=1)

                upper = last
                # Extend trailing edge to yesterday only for the live (current) year
                if (year is None or year == today.year) and yesterday > last:
                    upper = yesterday
                # Never let the window spill past the selected year
                if year is not None:
                    year_end = _date(year, 12, 31)
                    if upper > year_end:
                        upper = year_end
                    
                    # Force the start of the range to Jan 1 of the selected year
                    year_start = _date(year, 1, 1)
                    if first > year_start:
                        first = year_start

                if upper >= first:
                    expected = (upper - first).days + 1
                    return max(0, expected - len(dates))
                return 0

            # 1. Missing reports per source
            missing_report_wni = None
            if getattr(v, "wni_enabled", False):
                records_wni = [r for r in records if r.source_id == "wni"]
                missing_report_wni = calc_missing(records_wni)
            
            missing_report_mariapps = None
            if getattr(v, "mari_enabled", False):
                records_mariapps = [r for r in records if r.source_id == "mari_apps"]
                missing_report_mariapps = calc_missing(records_mariapps)

            # 2. ROB & Consumption — BOTH ME and AE fuel are missing (no fuel data at all)
            rob_consumption = sum(
                1 for r in records
                if r.ME_FOC_MT is None and r.AE_FOC_MT is None
            )

            # 3. Distance — null or zero distance when vessel was underway (STW > 0)
            distance = sum(
                1 for r in records
                if r.Distance_nm is None or (
                    r.Distance_nm == 0 and r.STW_kn is not None and r.STW_kn > 0.5
                )
            )

            # 4. Cargo Weight — null Displacement_MT only for Laden voyages
            cargo_weight = sum(
                1 for r in records
                if r.Displacement_MT is None
                and r.Loading_Cond is not None
                and r.Loading_Cond.upper() in ('LADEN', 'L', 'LD')
            )

            # 5. Bunkering — duplicate reports logged in data_quality_logs
            bq = db.query(DataQualityLog).filter(
                DataQualityLog.vessel_imo == imo,
                DataQualityLog.issue_type == "DUPLICATE_REPORT",
            )
            if year:
                bq = bq.filter(extract("year", DataQualityLog.report_date) == year)
            bunkering = bq.count()

            total_issues = (missing_report_wni or 0) + (missing_report_mariapps or 0) + rob_consumption + distance + cargo_weight + bunkering

            result.append({
                "vessel_name":    v.vessel_name,
                "imo_number":     imo,
                "ship_group":     vessel_group,
                "report_count":   len(records),
                "total_issues":   total_issues,
                "missing_report_wni": missing_report_wni,
                "missing_report_mariapps": missing_report_mariapps,
                "rob_consumption":rob_consumption,
                "distance":       distance,
                "cargo_weight":   cargo_weight,
                "bunkering":      bunkering,
            })

        return result

    except Exception as e:
        logging.error(f"Vessel report error: {e}")
        raise HTTPException(status_code=500, detail=f"Vessel report error: {e}")


@router.get("/vessel-report/groups")
def get_ship_groups(db: Session = Depends(get_db)):
    """Returns distinct ship groups derived from vessel name prefixes."""
    try:
        vessels = db.query(Vessel.vessel_name).all()
        groups  = sorted({v.vessel_name.split()[0] for v in vessels if v.vessel_name})
        return ["All"] + list(groups)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── VESSEL SCAN ENGINE ───────────────────────────────────────────────────────

SCAN_ALLOWED_FIELDS = {
    "Speed_Loss_pct", "Power_Dev_pct", "SFOC_gkWh", "VTI", "Est_Power_kW",
    "ME_FOC_MT", "AE_FOC_MT",
    "SOG_kn", "STW_kn", "Distance_nm", "Duration_h", "Heading_deg",
    "True_Wind_Spd_ms", "True_Wind_Dir_deg", "Rel_Wind_Spd_ms",
    "Sig_Wave_Ht_m", "Wave_Period_s", "Swell_Ht_m", "Swell_Period_s",
    "Current_Spd_kn", "Water_Temp_C", "Water_Depth_m",
    "Shaft_Power_kW", "Shaft_RPM", "AE_1_POWER_KW", "AE_2_POWER_KW", "AE_3_POWER_KW",
    "Mean_Draft_m", "Draft_Fwd_m", "Draft_Aft_m", "Trim_m", "Displacement_MT",
    "P_wind_kW", "P_wave_kW",
}

# ── Expression parser ─────────────────────────────────────────────────────────
_TOKEN_RE = re.compile(
    r'(?P<OP><=|>=|!=|==|<|>|=)'
    r'|(?P<ARITH>[+\-*/])'
    r'|(?P<LPAREN>\()'
    r'|(?P<RPAREN>\))'
    r'|(?P<COMMA>,)'
    r'|(?P<NUMBER>\d+\.?\d*|\.\d+)'
    r'|(?P<WORD>[A-Za-z_][A-Za-z0-9_]*)'
    r'|(?P<WS>\s+)'
)
_KEYWORDS = frozenset(['AND', 'OR', 'NOT', 'BETWEEN'])


def _tokenize(expr: str, allowed_fields=None):
    fields = allowed_fields if allowed_fields is not None else SCAN_ALLOWED_FIELDS
    tokens = []
    for m in _TOKEN_RE.finditer(expr):
        kind = m.lastgroup
        val  = m.group()
        if kind == 'WS':
            continue
        if kind == 'WORD':
            upper = val.upper()
            if upper in _KEYWORDS:
                tokens.append(('KW', upper))
            elif val in fields:
                tokens.append(('FIELD', val))
            else:
                raise ValueError(
                    f"Unknown field '{val}'. Check the field name is correct for the selected source."
                )
        else:
            tokens.append((kind, val))
    return tokens


class _Parser:
    """
    Grammar:
      expr       → or_expr
      or_expr    → and_expr ('OR' and_expr)*
      and_expr   → not_expr ('AND' not_expr)*
      not_expr   → 'NOT' atom | atom
      atom       → '(' expr ')' | comparison
      comparison → add_expr OP add_expr
                 | add_expr 'BETWEEN' add_expr ('AND'|',') add_expr
      add_expr   → mul_expr (('+' | '-') mul_expr)*
      mul_expr   → unary (('*' | '/') unary)*
      unary      → '-' (NUMBER | unary) | primary
      primary    → NUMBER | FIELD | '(' add_expr ')'
    """
    def __init__(self, tokens, field_fn=None):
        self.t         = tokens
        self.pos       = 0
        self._field_fn = field_fn or (lambda name: getattr(AnalysisData, name))

    def _peek(self, offset=0):
        i = self.pos + offset
        return self.t[i] if i < len(self.t) else None

    def _consume(self, kind=None):
        tok = self.t[self.pos]
        if kind and tok[0] != kind:
            raise ValueError(f"Expected {kind}, got {tok[0]!r} ({tok[1]!r})")
        self.pos += 1
        return tok

    def parse(self):
        clause = self._or()
        if self.pos < len(self.t):
            raise ValueError(f"Unexpected token: {self.t[self.pos][1]!r}")
        return clause

    def _or(self):
        left = self._and()
        while self._peek() == ('KW', 'OR'):
            self.pos += 1
            left = or_(left, self._and())
        return left

    def _and(self):
        left = self._not()
        while self._peek() == ('KW', 'AND'):
            self.pos += 1
            left = and_(left, self._not())
        return left

    def _not(self):
        if self._peek() == ('KW', 'NOT'):
            self.pos += 1
            return not_(self._atom())
        return self._atom()

    def _atom(self):
        if self._peek() and self._peek()[0] == 'LPAREN':
            self.pos += 1
            clause = self._or()
            self._consume('RPAREN')
            return clause
        return self._comparison()

    def _comparison(self):
        left = self._add()
        tok = self._peek()
        if tok == ('KW', 'BETWEEN'):
            self.pos += 1
            v1  = self._add()
            sep = self._peek()
            if sep and sep[0] == 'COMMA':
                self.pos += 1
            elif sep == ('KW', 'AND'):
                self.pos += 1
            else:
                raise ValueError("BETWEEN requires 'AND' or ',' between the two values")
            v2 = self._add()
            return left.between(v1, v2)
        if tok and tok[0] == 'OP':
            self.pos += 1
            right = self._add()
            return {
                '<' : left <  right,
                '<=': left <= right,
                '>' : left >  right,
                '>=': left >= right,
                '=' : left == right,
                '==': left == right,
                '!=': left != right,
            }[tok[1]]
        tok_desc = repr(tok[1]) if tok else 'end of input'
        raise ValueError(
            f"Expected comparison operator or BETWEEN after expression, got {tok_desc}"
        )

    def _add(self):
        left = self._mul()
        while True:
            tok = self._peek()
            if tok and tok[0] == 'ARITH' and tok[1] in ('+', '-'):
                self.pos += 1
                right = self._mul()
                left = (left + right) if tok[1] == '+' else (left - right)
            else:
                break
        return left

    def _mul(self):
        left = self._unary()
        while True:
            tok = self._peek()
            if tok and tok[0] == 'ARITH' and tok[1] in ('*', '/'):
                self.pos += 1
                right = self._unary()
                left = (left * right) if tok[1] == '*' else (left / right)
            else:
                break
        return left

    def _unary(self):
        tok = self._peek()
        if tok and tok[0] == 'ARITH' and tok[1] == '-':
            self.pos += 1
            nxt = self._peek()
            if nxt and nxt[0] == 'NUMBER':
                self.pos += 1
                return literal(-float(nxt[1]))
            return literal(-1) * self._unary()
        return self._primary()

    def _primary(self):
        tok = self._peek()
        if tok is None:
            raise ValueError("Unexpected end of expression")
        if tok[0] == 'NUMBER':
            self.pos += 1
            return literal(float(tok[1]))
        if tok[0] == 'FIELD':
            self.pos += 1
            return self._field_fn(tok[1])
        if tok[0] == 'LPAREN':
            self.pos += 1
            expr = self._add()
            self._consume('RPAREN')
            return expr
        raise ValueError(f"Expected field name or number, got {tok[1]!r}")


def _parse_expression(expr: str, allowed_fields=None, field_fn=None):
    tokens = _tokenize(expr.strip(), allowed_fields=allowed_fields)
    if not tokens:
        raise ValueError("Empty expression")
    return _Parser(tokens, field_fn=field_fn).parse()


@router.post("/scan/run")
def run_scan(payload: dict, db: Session = Depends(get_db)):
    """
    Run a scan using a filter expression against an expanded data table.
    Payload:
      {
        "expression": "Vessel_SOG_avg_operational_LF > 10 AND Weather_Hwv_avg_operational_LF < 2",
        "vessel_imo": "9832925",   -- optional
        "source": "wni"            -- 'wni' (default) or 'mariapps'
      }
    """
    try:
        expression = (payload.get("expression") or "").strip()
        vessel_imo = payload.get("vessel_imo") or None
        source     = payload.get("source", "wni")

        if not expression:
            raise HTTPException(status_code=400, detail="No expression provided.")

        # Choose expanded table + date column
        if source == "mariapps":
            table    = "expanded_mariapps_data"
            date_col = "log_date"
            src_key  = "mari_apps"
        else:
            table    = "expanded_wni_data"
            date_col = "date"
            src_key  = "wni"

        # Load allowed fields + identity columns from DB metadata
        meta_rows = db.execute(text(
            "SELECT db_column, is_identity FROM expanded_column_metadata WHERE source = :s"
        ), {"s": src_key}).fetchall()
        allowed_fields = {r[0] for r in meta_rows}
        identity_cols  = [r[0] for r in meta_rows if r[1]]

        # Parse expression — column refs become quoted SQL literals for raw SQL
        try:
            condition_clause = _parse_expression(
                expression,
                allowed_fields=allowed_fields,
                field_fn=lambda name: literal_column(f'"{name}"'),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Expression error: {e}")

        # Compile WHERE to SQL with inlined numeric literals (field names are validated above)
        from sqlalchemy.dialects import postgresql as _pg
        where_sql = str(condition_clause.compile(
            dialect=_pg.dialect(),
            compile_kwargs={"literal_binds": True},
        ))

        # Columns to return: identity + fields mentioned in expression
        mentioned = list(dict.fromkeys(
            w for w in re.findall(r'\b[A-Za-z_][A-Za-z0-9_]*\b', expression)
            if w in allowed_fields and w not in identity_cols
        ))
        all_cols = list(dict.fromkeys(identity_cols + mentioned))
        col_sql  = ", ".join(f'"{c}"' for c in all_cols)

        # Build parameterised query
        where_parts = [f"({where_sql})"]
        params: dict = {}
        if vessel_imo:
            where_parts.append("vessel_imo = :vessel_imo")
            params["vessel_imo"] = vessel_imo

        sql = text(f"""
            SELECT {col_sql}
            FROM   {table}
            WHERE  {" AND ".join(where_parts)}
            ORDER  BY "{date_col}" DESC
            LIMIT  500
        """)

        rows = db.execute(sql, params).fetchall()
        logging.info("Scan (%s) returned %d rows", source, len(rows))
        return [dict(zip(all_cols, row)) for row in rows]

    except HTTPException:
        raise
    except Exception as e:
        logging.error("Scan error: %s", e)
        raise HTTPException(status_code=500, detail=f"Scan error: {e}")


import os
import json
from fastapi.responses import JSONResponse

@router.get("/{vessel_imo}/track")
def get_vessel_track(vessel_imo: str):
    """
    Returns the combined historical track and route GeoJSON files downloaded from Weathernews.
    """
    from backend.config import config
    import os, json
    
    track_dir = os.path.join(config.ROOT_DIR, "data", "wni", "tracks")
    track_path = os.path.join(track_dir, f"{vessel_imo}.geojson")
    route_path = os.path.join(track_dir, f"{vessel_imo}_route.geojson")
    
    features = []
    
    for path in [route_path]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("type") == "FeatureCollection":
                        features.extend(data.get("features", []))
                    elif data.get("type") == "Feature":
                        features.append(data)
            except Exception:
                pass

    if not features:
        raise HTTPException(status_code=404, detail="Track/Route not found for this vessel")
        
    return JSONResponse(content={"type": "FeatureCollection", "features": features})
