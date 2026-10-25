# ============================================================
# DATA DISCREPANCY & VOYAGE REVIEW ROUTES
# ============================================================
# Backs the "Data Discrepancy & Voyage Review" section (manager request
# 2026-10), modeled on the Drs module's Defect/Thread pattern: a per-vessel
# queue of DataQualityFinding rows (already populated by the daily data-
# quality job), each with a discussion thread split into an internal
# (shore-only) channel and a vessel-facing channel.
#
# Voyage-completion reviews (Phase 2 — EOSP-triggered reports) aren't built
# yet, so this is scoped to the data-quality discrepancy side only for now;
# the same DataQualityThread table/shape is meant to be reused once that
# lands, rather than building a second thread model.
#
# GET   /api/v1/data-quality/findings                    — queue listing
# PATCH /api/v1/data-quality/findings/{id}                — status change
# GET   /api/v1/data-quality/findings/{id}/threads        — list messages
# POST  /api/v1/data-quality/findings/{id}/threads        — add a message
# ============================================================

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.auth import User, get_current_user, get_db_for_auth
from backend.models import DataQualityFinding, DataQualityThread, Vessel

router = APIRouter(prefix="/data-quality", tags=["data-quality-review"])

_VALID_STATUSES = {"open", "acknowledged", "resolved"}

# Mirrors daily_job.py's RULE_LABELS — kept as a separate copy rather than an
# import since this is a display-only concern for the review UI, not part of
# the check/email logic itself.
_RULE_LABELS = {
    "missing_weather": "Missing Weather Data",
    "missing_cp_instruction": "Missing CP Instruction",
    "missing_fuel": "Zero Fuel on Steaming Day",
}


class ThreadPayload(BaseModel):
    body: str
    is_internal: bool = True


class StatusPayload(BaseModel):
    status: str


def _finding_dict(row: DataQualityFinding, vessel_name: str, thread_counts: dict):
    counts = thread_counts.get(row.id, {"internal": 0, "vessel": 0})
    return {
        "id": row.id,
        "vessel_imo": row.vessel_imo,
        "vessel_name": vessel_name,
        "source_id": row.source_id,
        "report_date": row.report_date.isoformat() if row.report_date else None,
        "rule_key": row.rule_key,
        "rule_label": _RULE_LABELS.get(row.rule_key, row.rule_key),
        "detail": row.detail,
        "status": row.status,
        "first_detected_at": row.first_detected_at.isoformat() if row.first_detected_at else None,
        "last_notified_at": row.last_notified_at.isoformat() if row.last_notified_at else None,
        "notify_count": row.notify_count,
        "internal_count": counts["internal"],
        "vessel_count": counts["vessel"],
    }


@router.get("/findings")
def list_findings(
    vessel_imo: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="'open' | 'acknowledged' | 'resolved'; omit for all"),
    db: Session = Depends(get_db_for_auth),
    current_user: User = Depends(get_current_user),
):
    q = db.query(DataQualityFinding)
    if vessel_imo:
        q = q.filter(DataQualityFinding.vessel_imo == vessel_imo)
    if status:
        if status not in _VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {sorted(_VALID_STATUSES)}")
        q = q.filter(DataQualityFinding.status == status)
    rows = q.order_by(DataQualityFinding.first_detected_at.desc()).limit(500).all()

    if not rows:
        return []

    vessel_names = {
        v.imo_number: v.vessel_name
        for v in db.query(Vessel).filter(Vessel.imo_number.in_([r.vessel_imo for r in rows])).all()
    }

    finding_ids = [r.id for r in rows]
    count_rows = (
        db.query(
            DataQualityThread.finding_id,
            DataQualityThread.is_internal,
            func.count(DataQualityThread.id),
        )
        .filter(DataQualityThread.finding_id.in_(finding_ids))
        .group_by(DataQualityThread.finding_id, DataQualityThread.is_internal)
        .all()
    )
    thread_counts = {}
    for finding_id, is_internal, cnt in count_rows:
        bucket = thread_counts.setdefault(finding_id, {"internal": 0, "vessel": 0})
        bucket["internal" if is_internal else "vessel"] = cnt

    return [_finding_dict(r, vessel_names.get(r.vessel_imo, r.vessel_imo), thread_counts) for r in rows]


@router.patch("/findings/{finding_id}")
def update_finding_status(
    finding_id: int,
    payload: StatusPayload,
    db: Session = Depends(get_db_for_auth),
    current_user: User = Depends(get_current_user),
):
    if payload.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(_VALID_STATUSES)}")
    row = db.query(DataQualityFinding).filter(DataQualityFinding.id == finding_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Finding not found")

    from datetime import datetime
    row.status = payload.status
    if payload.status == "resolved":
        row.resolved_at = datetime.utcnow()
    db.commit()
    return {"id": row.id, "status": row.status}


@router.get("/findings/{finding_id}/threads")
def list_threads(
    finding_id: int,
    channel: Optional[str] = Query(None, description="'internal' | 'vessel'; omit for both"),
    db: Session = Depends(get_db_for_auth),
    current_user: User = Depends(get_current_user),
):
    finding = db.query(DataQualityFinding).filter(DataQualityFinding.id == finding_id).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    q = db.query(DataQualityThread).filter(DataQualityThread.finding_id == finding_id)
    if channel == "internal":
        q = q.filter(DataQualityThread.is_internal.is_(True))
    elif channel == "vessel":
        q = q.filter(DataQualityThread.is_internal.is_(False))
    rows = q.order_by(DataQualityThread.created_at.asc()).all()

    return [
        {
            "id": t.id,
            "finding_id": t.finding_id,
            "author_name": t.author_name,
            "is_internal": t.is_internal,
            "body": t.body,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in rows
    ]


@router.post("/findings/{finding_id}/threads")
def add_thread_message(
    finding_id: int,
    payload: ThreadPayload,
    db: Session = Depends(get_db_for_auth),
    current_user: User = Depends(get_current_user),
):
    finding = db.query(DataQualityFinding).filter(DataQualityFinding.id == finding_id).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    if not payload.body or not payload.body.strip():
        raise HTTPException(status_code=400, detail="Message body cannot be empty")

    row = DataQualityThread(
        finding_id=finding_id,
        author_user_id=current_user.id,
        author_name=current_user.username,
        is_internal=payload.is_internal,
        body=payload.body.strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "finding_id": row.finding_id,
        "author_name": row.author_name,
        "is_internal": row.is_internal,
        "body": row.body,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
