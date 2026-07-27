"""
Charter-Party compliance v2 — Phase 3a pilot API.
Gated to PILOT_VESSEL_IMOS (AM KIRTI + GCL FOS) — see backend/cp/cp_compliance_v2.py
for the full 12-step evaluation logic and its documented approximations.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy import inspect as sa_inspect

from backend.database import SessionLocal
from backend.models import CPVesselDescription, CPSeaWarranty, CPWarrantyConditions
from backend.cp.cp_compliance_v2 import PILOT_VESSEL_IMOS, evaluate_vessel

log = logging.getLogger(__name__)
router = APIRouter(prefix="/cp-compliance", tags=["cp-compliance-v2-pilot"])

_SOURCE_TABLES = {
    "wni": "wni",
    "mari_apps": "mari_apps",
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _row_dict(row):
    mapper = sa_inspect(type(row))
    return {c.key: getattr(row, c.key) for c in mapper.attrs}


@router.get("/pilot-vessels")
def list_pilot_vessels():
    return sorted(PILOT_VESSEL_IMOS)


@router.get("/{imo}")
def get_cp_compliance(
    imo: str,
    source: Optional[str] = Query(None, description="'wni' or 'mari_apps'; omit for both"),
    db: Session = Depends(get_db),
):
    if imo not in PILOT_VESSEL_IMOS:
        raise HTTPException(
            status_code=403,
            detail=(
                f"CP compliance v2 is a Phase 3a pilot restricted to IMOs {sorted(PILOT_VESSEL_IMOS)}. "
                f"IMO {imo} is not in the pilot yet."
            ),
        )

    header = (
        db.query(CPVesselDescription)
        .filter(CPVesselDescription.vessel_imo == imo, CPVesselDescription.doc_status == "Active")
        .order_by(CPVesselDescription.version_no.desc())
        .first()
    )
    if not header:
        raise HTTPException(status_code=404, detail=f"No Active CP description found for IMO {imo}.")

    sea_rows = [
        _row_dict(r) for r in
        db.query(CPSeaWarranty).filter(CPSeaWarranty.cp_id == header.id).all()
    ]
    conditions_row = db.query(CPWarrantyConditions).filter(CPWarrantyConditions.cp_id == header.id).first()
    if not conditions_row:
        raise HTTPException(status_code=404, detail=f"No warranty conditions found for IMO {imo}.")
    conditions = _row_dict(conditions_row)

    sources = [source] if source in _SOURCE_TABLES else ["wni", "mari_apps"]
    analysis_rows = []
    for src in sources:
        sql = """
            SELECT "Voyage_No", "Loading_Cond", "Date", "Distance_nm", "Duration_h",
                   "SOG_kn", "STW_kn", "ME_FOC_MT", "AE_FOC_MT", "BF_Wind", "Sig_Wave_Ht_m", source_id
            FROM analysis_data
            WHERE vessel_imo = :imo AND source_id = :src
            ORDER BY "Voyage_No", "Date"
        """
        analysis_rows.extend(dict(r) for r in db.execute(text(sql), {"imo": imo, "src": src}).mappings().all())

    if not analysis_rows:
        return {
            "vessel_imo": imo,
            "header": _row_dict(header),
            "voyages": [],
            "exceptions": [],
            "note": "No analysis_data rows found for this vessel/source — nothing to evaluate yet.",
        }

    result = evaluate_vessel(_row_dict(header), sea_rows, conditions, analysis_rows)
    result["header"] = {
        "vessel_name": header.vessel_name, "cp_id": header.cp_id, "doc_status": header.doc_status,
    }
    return result
