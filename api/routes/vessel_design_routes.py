"""
API routes for Vessel Design Data (MDM — Master Data Management).
Provides CRUD endpoints for the vessel_design_data table.
"""
import json
import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import inspect as sa_inspect, text
from typing import Any, Dict, Optional

from backend.database import SessionLocal
from backend.models import VesselDesignData, Vessel, VesselParticulars

log = logging.getLogger(__name__)
router = APIRouter(prefix="/vessels", tags=["vessel-design"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _mdm_to_dict(record: VesselDesignData) -> Dict[str, Any]:
    """Serialize a VesselDesignData ORM row to a plain dict."""
    mapper = sa_inspect(VesselDesignData)
    return {c.key: getattr(record, c.key) for c in mapper.attrs}


# ── GET ──────────────────────────────────────────────────────────────────────
@router.get("/{imo}/design-data")
def get_design_data(imo: str, db: Session = Depends(get_db)):
    """
    Fetch the MDM design data record for a vessel.
    Returns 404 if no record has been saved yet (this is normal for new vessels).
    """
    record = db.query(VesselDesignData).filter(VesselDesignData.vessel_imo == imo).first()
    if not record:
        # Return an empty shell so the frontend form still renders
        return {"vessel_imo": imo, "_empty": True}
    return _mdm_to_dict(record)


# ── POST (upsert) ─────────────────────────────────────────────────────────────
@router.post("/{imo}/design-data")
def upsert_design_data(imo: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    """
    Create or fully replace the MDM design data record for a vessel.
    Payload keys must match column names in vessel_design_data.
    Unknown keys are silently ignored.
    """
    vessel = db.query(Vessel).filter(Vessel.imo_number == imo).first()
    if not vessel:
        raise HTTPException(status_code=404, detail=f"Vessel IMO {imo} not found.")

    # Collect valid column names (excluding system cols)
    valid_cols = {
        c.key for c in sa_inspect(VesselDesignData).attrs
        if c.key not in ("id", "vessel_imo", "created_at", "updated_at")
    }

    record = db.query(VesselDesignData).filter(VesselDesignData.vessel_imo == imo).first()

    if record is None:
        record = VesselDesignData(vessel_imo=imo)
        db.add(record)

    for key, value in payload.items():
        if key in valid_cols:
            # Coerce empty strings to None so numeric columns don't error
            if value == "":
                value = None
            setattr(record, key, value)

    try:
        db.commit()
        db.refresh(record)
        log.info(f"MDM upsert OK — IMO {imo}")
        return _mdm_to_dict(record)
    except Exception as e:
        db.rollback()
        log.error(f"MDM upsert failed for IMO {imo}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── PATCH (partial update) ────────────────────────────────────────────────────
@router.patch("/{imo}/design-data")
def patch_design_data(imo: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    """
    Partially update the MDM design data record for a vessel.
    Only the supplied keys are updated; everything else is left unchanged.
    """
    record = db.query(VesselDesignData).filter(VesselDesignData.vessel_imo == imo).first()
    if not record:
        # Auto-create if not existing
        vessel = db.query(Vessel).filter(Vessel.imo_number == imo).first()
        if not vessel:
            raise HTTPException(status_code=404, detail=f"Vessel IMO {imo} not found.")
        record = VesselDesignData(vessel_imo=imo)
        db.add(record)

    valid_cols = {
        c.key for c in sa_inspect(VesselDesignData).attrs
        if c.key not in ("id", "vessel_imo", "created_at", "updated_at")
    }

    for key, value in payload.items():
        if key in valid_cols:
            if value == "":
                value = None
            setattr(record, key, value)

    try:
        db.commit()
        db.refresh(record)
        return _mdm_to_dict(record)
    except Exception as e:
        db.rollback()
        log.error(f"MDM patch failed for IMO {imo}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Speed-Power scatter data ──────────────────────────────────────────────────

# Candidate column names in priority order for each measurement
# New Service Variable column names used for speed-power scatter
_SPEED_CANDIDATES = [
    "Vessel_SOG_avg_operational_LF",   # primary (new schema)
    "speed_og", "speed_og_knots",      # legacy fallback
]
_POWER_CANDIDATES = [
    "ME_PeffestME_avg_operational_LF", # primary (new schema)
    "ME_PSME_avg_operational_LF",      # shaft power (new schema)
    "me1_power", "me_power_kw",        # legacy fallback
]
_LC_CANDIDATES    = ["loading_condition", "loading_cond", "load_condition"]


def _find_col(db: Session, table: str, candidates: list) -> Optional[str]:
    """Return the first candidate that exists as a column in the given table."""
    quoted = ", ".join(f"'{c}'" for c in candidates)
    row = db.execute(text(
        f"SELECT column_name FROM information_schema.columns "
        f"WHERE table_name = '{table}' AND column_name IN ({quoted}) LIMIT 1"
    )).fetchone()
    return row[0] if row else None


def _query_expanded(db: Session, table: str, imo: str, lc_letter: str, source_label: str) -> list:
    """
    Query one expanded table for (speed, power) scatter points.
    Discovers actual column names first so it works regardless of schema differences
    between expanded_mariapps_data and expanded_wni_data.
    Returns [] if the table lacks the required columns.
    """
    speed_col = _find_col(db, table, _SPEED_CANDIDATES)
    power_col = _find_col(db, table, _POWER_CANDIDATES)
    lc_col    = _find_col(db, table, _LC_CANDIDATES)

    if not speed_col or not power_col:
        log.info(f"{table}: no speed/power columns found (speed={speed_col}, power={power_col})")
        return []

    lc_clause = ""
    if lc_letter and lc_col:
        lc_clause = f"AND {lc_col} ILIKE '{lc_letter}%'"

    lc_select = f"COALESCE({lc_col}, '')" if lc_col else "''"

    sql = text(f"""
        SELECT
            {speed_col}::float   AS speed,
            {power_col}::float   AS power,
            {lc_select}          AS loading_condition,
            '{source_label}'     AS data_source
        FROM {table}
        WHERE vessel_imo = :imo
          AND {speed_col} ~ '^[0-9]+\\.?[0-9]*$'
          AND {power_col} ~ '^[0-9]+\\.?[0-9]*$'
          AND {speed_col}::float > 0
          AND {power_col}::float > 0
          {lc_clause}
    """)

    try:
        rows = db.execute(sql, {"imo": imo}).fetchall()
        return [
            {
                "speed":             float(r[0]),
                "power":             float(r[1]),
                "loading_condition": r[2],
                "data_source":       r[3],
            }
            for r in rows
        ]
    except Exception as e:
        db.rollback()   # unstick the transaction so subsequent ORM calls still work
        log.warning(f"{table} speed-power query failed for IMO {imo}: {e}")
        return []


@router.get("/{imo}/speed-power-data")
def get_speed_power_data(
    imo: str,
    loading_condition: Optional[str] = Query(default="all"),
    db: Session = Depends(get_db),
):
    """
    Returns actual speed/power scatter points from expanded tables plus a
    baseline speed-power curve.

    Baseline source priority:
      1. vessel_design_data  — SeaTrialsHull corrected speed/power vectors
      2. vessel_particulars  — propeller-law coefficients (P = A × v^n)
    """
    lc = (loading_condition or "all").strip().lower()
    lc_letter = lc[0] if lc not in ("all", "") else ""

    # ── 1. Actual data — query each table separately (different schemas) ────────
    actual = (
        _query_expanded(db, "expanded_mariapps_data", imo, lc_letter, "mari_apps") +
        _query_expanded(db, "expanded_wni_data",      imo, lc_letter, "wni")
    )

    # ── 2. Baseline: vessel_design_data (sea trial corrected curve) ─────────────
    baseline_points = []
    baseline_source = None

    try:
        design = db.query(VesselDesignData).filter(VesselDesignData.vessel_imo == imo).first()
        if design:
            u_raw = getattr(design, "SeaTrialsHull_UCorSTrial_design_data", None)
            p_raw = getattr(design, "SeaTrialsHull_PCorSTrial_design_data", None)
            if u_raw and p_raw:
                speeds = json.loads(u_raw)
                powers = json.loads(p_raw)
                if speeds and powers and len(speeds) == len(powers):
                    baseline_points = sorted(
                        [{"speed": float(s), "power": float(p)} for s, p in zip(speeds, powers)],
                        key=lambda x: x["speed"],
                    )
                    baseline_source = "sea_trials"
    except Exception as e:
        log.debug(f"Sea trial baseline parse failed for {imo}: {e}")

    # ── 3. Fallback: vessel_particulars propeller-law curve (P = A × v^n) ───────
    if not baseline_points:
        try:
            vp = db.query(VesselParticulars).filter(VesselParticulars.vessel_imo == imo).first()
            if vp:
                ballast = lc_letter == "b"
                A = vp.baseline_coeff_a_ballast if ballast else vp.baseline_coeff_a_laden
                n = vp.baseline_exponent_n_ballast if ballast else vp.baseline_exponent_n_laden

                if A and n:
                    baseline_points = [
                        {"speed": round(7 + i * 0.25, 2), "power": round(A * ((7 + i * 0.25) ** n), 1)}
                        for i in range(45)
                    ]
                    baseline_source = "vessel_particulars"
                elif vp.ncr_kw or vp.me_engine_mcr_kw:
                    # Last resort: cubic law anchored at NCR
                    ncr   = vp.ncr_kw or vp.me_engine_mcr_kw * 0.85
                    ref_v = 13.0
                    baseline_points = [
                        {"speed": round(7 + i * 0.25, 2), "power": round(ncr * ((7 + i * 0.25) / ref_v) ** 3, 1)}
                        for i in range(45)
                    ]
                    baseline_source = "vessel_particulars_approx"
        except Exception as e:
            log.debug(f"VP baseline failed for {imo}: {e}")

    return {
        "actual":          actual,
        "baseline_points": baseline_points,
        "baseline_source": baseline_source,
        "count":           len(actual),
    }
