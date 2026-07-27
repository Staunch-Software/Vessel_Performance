"""
API routes for Charter-Party Description (CP Description tab).
CRUD over cp_vessel_description (T1) + its 3 child tables (T2 sea warranty,
T3 port warranty, T4 warranty conditions). See CLAUDE.md "Charter-Party Description"
section and import_cp_description.py for the schema rationale.
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import inspect as sa_inspect
from typing import Any, Dict, List, Optional
from datetime import datetime

from backend.database import SessionLocal
from backend.models import (
    Vessel, CPVesselDescription, CPSeaWarranty, CPPortWarranty, CPWarrantyConditions,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/cp-description", tags=["cp-description"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _row_to_dict(row) -> Dict[str, Any]:
    mapper = sa_inspect(type(row))
    out = {}
    for c in mapper.attrs:
        val = getattr(row, c.key)
        if isinstance(val, datetime):
            val = val.isoformat()
        out[c.key] = val
    return out


# ── List vessels that have CP description data ───────────────────────────────
@router.get("/vessels")
def list_cp_vessels(db: Session = Depends(get_db)):
    rows = db.query(CPVesselDescription).all()
    return [
        {
            "vessel_imo": r.vessel_imo,
            "vessel_name": r.vessel_name,
            "cp_id": r.cp_id,
            "doc_status": r.doc_status,
            "version_no": r.version_no,
        }
        for r in rows
    ]


# ── Fetch full CP description for a vessel ───────────────────────────────────
@router.get("/{imo}")
def get_cp_description(imo: str, db: Session = Depends(get_db)):
    """
    Returns the Active CP fixture for a vessel (falls back to the most recent
    record if none is marked Active). 404 if the vessel has no CP data loaded.
    """
    header = (
        db.query(CPVesselDescription)
        .filter(CPVesselDescription.vessel_imo == imo, CPVesselDescription.doc_status == "Active")
        .order_by(CPVesselDescription.version_no.desc())
        .first()
    )
    if not header:
        header = (
            db.query(CPVesselDescription)
            .filter(CPVesselDescription.vessel_imo == imo)
            .order_by(CPVesselDescription.version_no.desc())
            .first()
        )
    if not header:
        raise HTTPException(status_code=404, detail=f"No CP description found for IMO {imo}.")

    sea_rows = (
        db.query(CPSeaWarranty)
        .filter(CPSeaWarranty.cp_id == header.id)
        .order_by(CPSeaWarranty.id)
        .all()
    )
    port_rows = (
        db.query(CPPortWarranty)
        .filter(CPPortWarranty.cp_id == header.id)
        .order_by(CPPortWarranty.id)
        .all()
    )
    conditions = (
        db.query(CPWarrantyConditions)
        .filter(CPWarrantyConditions.cp_id == header.id)
        .first()
    )

    return {
        "header": _row_to_dict(header),
        "sea_warranty": [_row_to_dict(r) for r in sea_rows],
        "port_warranty": [_row_to_dict(r) for r in port_rows],
        "conditions": _row_to_dict(conditions) if conditions else None,
    }


# ── Update header (T1) fields ────────────────────────────────────────────────
@router.patch("/{imo}/header")
def update_cp_header(imo: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    header = (
        db.query(CPVesselDescription)
        .filter(CPVesselDescription.vessel_imo == imo, CPVesselDescription.doc_status == "Active")
        .order_by(CPVesselDescription.version_no.desc())
        .first()
    )
    if not header:
        raise HTTPException(status_code=404, detail=f"No CP description found for IMO {imo}.")

    valid_cols = {
        c.key for c in sa_inspect(CPVesselDescription).attrs
        if c.key not in ("id", "cp_id", "vessel_imo", "created_at", "updated_at")
    }
    for key, value in payload.items():
        if key in valid_cols:
            setattr(header, key, None if value == "" else value)

    try:
        db.commit()
        db.refresh(header)
        return _row_to_dict(header)
    except Exception as e:
        db.rollback()
        log.error(f"CP header update failed for IMO {imo}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Replace sea-warranty (T2) rows ───────────────────────────────────────────
@router.put("/{imo}/sea-warranty")
def replace_sea_warranty(imo: str, rows: List[Dict[str, Any]], db: Session = Depends(get_db)):
    header = (
        db.query(CPVesselDescription)
        .filter(CPVesselDescription.vessel_imo == imo, CPVesselDescription.doc_status == "Active")
        .order_by(CPVesselDescription.version_no.desc())
        .first()
    )
    if not header:
        raise HTTPException(status_code=404, detail=f"No CP description found for IMO {imo}.")

    valid_cols = {
        c.key for c in sa_inspect(CPSeaWarranty).attrs
        if c.key not in ("id", "cp_id", "created_at")
    }
    try:
        db.query(CPSeaWarranty).filter(CPSeaWarranty.cp_id == header.id).delete(synchronize_session=False)
        for row in rows:
            clean = {k: (None if v == "" else v) for k, v in row.items() if k in valid_cols}
            db.add(CPSeaWarranty(cp_id=header.id, **clean))
        db.commit()
    except Exception as e:
        db.rollback()
        log.error(f"Sea warranty replace failed for IMO {imo}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return [_row_to_dict(r) for r in db.query(CPSeaWarranty).filter(CPSeaWarranty.cp_id == header.id).order_by(CPSeaWarranty.id).all()]


# ── Replace port-warranty (T3) rows ──────────────────────────────────────────
@router.put("/{imo}/port-warranty")
def replace_port_warranty(imo: str, rows: List[Dict[str, Any]], db: Session = Depends(get_db)):
    header = (
        db.query(CPVesselDescription)
        .filter(CPVesselDescription.vessel_imo == imo, CPVesselDescription.doc_status == "Active")
        .order_by(CPVesselDescription.version_no.desc())
        .first()
    )
    if not header:
        raise HTTPException(status_code=404, detail=f"No CP description found for IMO {imo}.")

    valid_cols = {
        c.key for c in sa_inspect(CPPortWarranty).attrs
        if c.key not in ("id", "cp_id", "created_at")
    }
    try:
        db.query(CPPortWarranty).filter(CPPortWarranty.cp_id == header.id).delete(synchronize_session=False)
        for row in rows:
            clean = {k: (None if v == "" else v) for k, v in row.items() if k in valid_cols}
            db.add(CPPortWarranty(cp_id=header.id, **clean))
        db.commit()
    except Exception as e:
        db.rollback()
        log.error(f"Port warranty replace failed for IMO {imo}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return [_row_to_dict(r) for r in db.query(CPPortWarranty).filter(CPPortWarranty.cp_id == header.id).order_by(CPPortWarranty.id).all()]


# ── Update warranty conditions (T4) ──────────────────────────────────────────
@router.patch("/{imo}/conditions")
def update_conditions(imo: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    header = (
        db.query(CPVesselDescription)
        .filter(CPVesselDescription.vessel_imo == imo, CPVesselDescription.doc_status == "Active")
        .order_by(CPVesselDescription.version_no.desc())
        .first()
    )
    if not header:
        raise HTTPException(status_code=404, detail=f"No CP description found for IMO {imo}.")

    conditions = db.query(CPWarrantyConditions).filter(CPWarrantyConditions.cp_id == header.id).first()
    if not conditions:
        conditions = CPWarrantyConditions(cp_id=header.id)
        db.add(conditions)

    valid_cols = {
        c.key for c in sa_inspect(CPWarrantyConditions).attrs
        if c.key not in ("id", "cp_id", "created_at")
    }
    for key, value in payload.items():
        if key in valid_cols:
            setattr(conditions, key, None if value == "" else value)

    try:
        db.commit()
        db.refresh(conditions)
        return _row_to_dict(conditions)
    except Exception as e:
        db.rollback()
        log.error(f"Conditions update failed for IMO {imo}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
