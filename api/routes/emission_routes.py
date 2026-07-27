"""
Emission tab — AER & CII API.
ESG / SCC / ESI reports are NOT implemented here — their definition/format was
never specified by the client; the frontend renders them as "pending" placeholders.
See backend/emission/cii_calculator.py for the full IMO-resolution citations.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import VesselParticulars
from backend.emission.cii_calculator import compute_cii, DEFAULT_SHIP_TYPE

log = logging.getLogger(__name__)
router = APIRouter(prefix="/emission", tags=["emission"])

# Same 8 consumer prefixes / 10 fuel grades on both noon_report_data (WNI) and
# mariapps_reports_data (MariApps) — identical schema, so one query template
# works for either source by swapping the table/join.
_CONSUMERS = ["me", "ae", "bl", "inc", "eg", "combl", "aeb", "blfo"]
_GRADES = ["hfo", "lfo", "mdo", "lpg_propane", "lpg_butane", "lng", "methanol", "ethanol", "ammonia", "bio_fuel"]

_SOURCE_JOIN = {
    "wni": ("JOIN noon_report_data n ON n.raw_report_id = a.raw_report_id", "wni"),
    "mari_apps": ("JOIN mariapps_reports_data n ON n.raw_report_id = a.raw_mariapps_id", "mari_apps"),
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _numexpr(col):
    # Same VARCHAR-safe cast convention as cp_routes.py — non-numeric/blank -> 0.
    return f"(CASE WHEN {col} ~ '^[-+]?[0-9]+(\\.[0-9]+)?$' THEN {col}::double precision ELSE 0 END)"


def _grade_sum_expr(grade):
    parts = [_numexpr(f'n."{c}_{grade}"') for c in _CONSUMERS]
    return "(" + "+".join(parts) + f") AS {grade}"


_GRADE_EXPRS = ",\n               ".join(_grade_sum_expr(g) for g in _GRADES)


def _fuel_and_distance(db, imo, source, year):
    join, src = _SOURCE_JOIN[source]
    sql = f"""
        SELECT COALESCE(SUM(a."Distance_nm"), 0) AS total_distance,
               {", ".join(f'COALESCE(SUM({g}), 0) AS total_{g}' for g in _GRADES)}
        FROM (
            SELECT a."Distance_nm", {_GRADE_EXPRS}
            FROM analysis_data a
            {join}
            WHERE a.vessel_imo = :imo AND a.source_id = :src
              AND EXTRACT(YEAR FROM a."Date") = :year
        ) a
    """
    row = db.execute(text(sql), {"imo": imo, "src": src, "year": year}).mappings().first()
    if not row:
        return 0.0, {g: 0.0 for g in _GRADES}
    distance = float(row["total_distance"] or 0)
    fuel = {g: float(row[f"total_{g}"] or 0) for g in _GRADES}
    return distance, fuel


@router.get("/{imo}/years")
def list_available_years(imo: str, db: Session = Depends(get_db)):
    rows = db.execute(
        text('SELECT DISTINCT EXTRACT(YEAR FROM "Date")::int AS y FROM analysis_data WHERE vessel_imo = :imo ORDER BY 1'),
        {"imo": imo},
    ).fetchall()
    return [r[0] for r in rows if r[0] is not None]


@router.get("/{imo}/cii")
def get_cii(
    imo: str,
    year: int = Query(..., description="Calendar year"),
    source: Optional[str] = Query(None, description="'wni' or 'mari_apps'; omit combines both (may double-count overlapping days)"),
    db: Session = Depends(get_db),
):
    vessel = db.query(VesselParticulars).filter(VesselParticulars.vessel_imo == imo).first()
    dwt = vessel.deadweight if vessel else None
    if not dwt:
        raise HTTPException(
            status_code=404,
            detail=f"No DWT (deadweight) configured for IMO {imo} — CII cannot be computed without it. Set it on the Design Data tab.",
        )

    sources = [source] if source in _SOURCE_JOIN else list(_SOURCE_JOIN.keys())
    total_distance = 0.0
    fuel_totals = {g: 0.0 for g in _GRADES}
    for src in sources:
        d, f = _fuel_and_distance(db, imo, src, year)
        total_distance += d
        for g in _GRADES:
            fuel_totals[g] += f[g]

    result = compute_cii(fuel_totals, total_distance, dwt, year, DEFAULT_SHIP_TYPE)
    if result is None:
        return {
            "vessel_imo": imo, "year": year, "source": source, "dwt": dwt,
            "note": "No distance data for this vessel/year/source — CII not computable.",
        }

    result["vessel_imo"] = imo
    result["source"] = source
    return result
