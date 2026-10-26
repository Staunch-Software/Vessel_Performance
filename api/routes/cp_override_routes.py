# ============================================================
# CP MANUAL OVERRIDE ROUTES
# ============================================================
# Lets shore staff correct a voyage's (or one day's) CP speed/consumption
# once a remarks gap or parsing error is confirmed — see models.py's
# CPManualOverride and backend/cp/cp_overrides.py for the priority chain
# this plugs into (day override > voyage override > remarks instruction >
# standing warranty match). Consumed by expander.py (display columns) and
# cp_routes.py (/cp/{imo}/performance + the Voyage Audit PDF) — NOT yet by
# cp_compliance_v2.py's CP Description pilot evaluator (pre-existing gap,
# that module doesn't consume the remarks instruction either).
#
# GET    /api/v1/cp-overrides/{imo}                 — list (optional ?voyage_no=&source=)
# POST   /api/v1/cp-overrides/{imo}                  — create/update (find-or-create)
# DELETE /api/v1/cp-overrides/{imo}/{override_id}    — remove one override
# ============================================================
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import User, get_current_user, get_db_for_auth
from backend.models import CPManualOverride, Vessel

router = APIRouter(prefix="/cp-overrides", tags=["cp-overrides"])

_VALID_SOURCES = {"wni", "mari_apps"}


class OverridePayload(BaseModel):
    source_id: str
    voyage_no: str
    log_date: Optional[str] = None   # "YYYY-MM-DD"; omit/None = voyage-level
    speed_kn: Optional[float] = None
    total_mt_day: Optional[float] = None
    go_mt_day: Optional[float] = None
    note: Optional[str] = None


def _row_dict(row: CPManualOverride):
    return {
        "id": row.id,
        "vessel_imo": row.vessel_imo,
        "source_id": row.source_id,
        "voyage_no": row.voyage_no,
        "log_date": row.log_date.isoformat() if row.log_date else None,
        "speed_kn": row.speed_kn,
        "total_mt_day": row.total_mt_day,
        "go_mt_day": row.go_mt_day,
        "note": row.note,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/{imo}")
def list_overrides(
    imo: str,
    voyage_no: Optional[str] = Query(None),
    source: Optional[str] = Query(None, description="'wni' or 'mari_apps'; omit for both"),
    db: Session = Depends(get_db_for_auth),
    current_user: User = Depends(get_current_user),
):
    q = db.query(CPManualOverride).filter(CPManualOverride.vessel_imo == imo)
    if voyage_no:
        q = q.filter(CPManualOverride.voyage_no == voyage_no)
    if source:
        q = q.filter(CPManualOverride.source_id == source)
    rows = q.order_by(CPManualOverride.voyage_no, CPManualOverride.log_date.asc().nulls_first()).all()
    return [_row_dict(r) for r in rows]


@router.post("/{imo}")
def upsert_override(
    imo: str,
    payload: OverridePayload,
    db: Session = Depends(get_db_for_auth),
    current_user: User = Depends(get_current_user),
):
    if payload.source_id not in _VALID_SOURCES:
        raise HTTPException(status_code=400, detail=f"source_id must be one of {sorted(_VALID_SOURCES)}")
    if not db.query(Vessel).filter(Vessel.imo_number == imo).first():
        raise HTTPException(status_code=404, detail=f"Vessel {imo} not found")
    if payload.speed_kn is None and payload.total_mt_day is None and payload.go_mt_day is None:
        raise HTTPException(status_code=400, detail="At least one of speed_kn/total_mt_day/go_mt_day is required")

    log_date = None
    if payload.log_date:
        try:
            log_date = datetime.strptime(payload.log_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="log_date must be YYYY-MM-DD")

    # Find-or-create: the DB unique constraint only guards the day-level case
    # (NULL log_date values are all-distinct to Postgres), so the voyage-level
    # "only one per voyage" rule is enforced here instead.
    q = db.query(CPManualOverride).filter(
        CPManualOverride.vessel_imo == imo,
        CPManualOverride.source_id == payload.source_id,
        CPManualOverride.voyage_no == payload.voyage_no,
    )
    q = q.filter(CPManualOverride.log_date.is_(None)) if log_date is None else q.filter(CPManualOverride.log_date == log_date)
    row = q.first()
    if row is None:
        row = CPManualOverride(
            vessel_imo=imo, source_id=payload.source_id, voyage_no=payload.voyage_no, log_date=log_date,
        )
        db.add(row)

    row.speed_kn = payload.speed_kn
    row.total_mt_day = payload.total_mt_day
    row.go_mt_day = payload.go_mt_day
    row.note = payload.note
    row.created_by = row.created_by or current_user.username
    db.commit()
    db.refresh(row)
    return _row_dict(row)


@router.delete("/{imo}/{override_id}")
def delete_override(
    imo: str,
    override_id: int,
    db: Session = Depends(get_db_for_auth),
    current_user: User = Depends(get_current_user),
):
    row = db.query(CPManualOverride).filter(
        CPManualOverride.id == override_id, CPManualOverride.vessel_imo == imo,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Override not found")
    db.delete(row)
    db.commit()
    return {"deleted": override_id}
