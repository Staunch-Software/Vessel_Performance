# ============================================================
# COLUMN PREFERENCE ROUTES  (scaffold for future UI phase)
# ============================================================
# GET  /api/v1/column-prefs                   — current user's prefs
# PUT  /api/v1/column-prefs                   — save current user's prefs
# GET  /api/v1/vessel-column-defaults         — [Admin] vessel defaults
# PUT  /api/v1/vessel-column-defaults         — [Admin] set vessel defaults
# ============================================================

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, Any, Dict

from backend.auth import User, get_current_user, require_admin, get_db_for_auth
from backend.models import UserColumnPreference, VesselColumnDefault

router = APIRouter(tags=["column-preferences"])


# ── Request schemas ──────────────────────────────────────────
class ColumnPrefPayload(BaseModel):
    source: str                              # 'mari_apps' | 'wni'
    vessel_imo: Optional[str] = None         # None = user-level pref
    column_prefs: Dict[str, Any]             # {visible: [...], order: [...]}


class VesselColumnDefaultPayload(BaseModel):
    vessel_imo: Optional[str] = None
    source: str
    column_prefs: Dict[str, Any]


# ── GET /column-prefs ────────────────────────────────────────
@router.get("/column-prefs")
def get_column_prefs(
    source: str,
    vessel_imo: Optional[str] = None,
    db: Session = Depends(get_db_for_auth),
    current_user: User = Depends(get_current_user),
):
    """Get the current user's column preferences for a source (+ optional vessel)."""
    # First check for specific vessel
    pref = None
    if vessel_imo:
        pref = db.query(UserColumnPreference).filter(
            UserColumnPreference.user_id == current_user.id,
            UserColumnPreference.source  == source,
            UserColumnPreference.vessel_imo == vessel_imo
        ).first()

    # Fallback to user's global preference
    if not pref:
        pref = db.query(UserColumnPreference).filter(
            UserColumnPreference.user_id == current_user.id,
            UserColumnPreference.source  == source,
            UserColumnPreference.vessel_imo.is_(None)
        ).first()

    return pref.column_prefs if pref else {}


# ── PUT /column-prefs ────────────────────────────────────────
@router.put("/column-prefs")
def save_column_prefs(
    payload: ColumnPrefPayload,
    db: Session = Depends(get_db_for_auth),
    current_user: User = Depends(get_current_user),
):
    """Save the current user's column preferences (upsert)."""
    q = db.query(UserColumnPreference).filter(
        UserColumnPreference.user_id == current_user.id,
        UserColumnPreference.source  == payload.source,
    )
    if payload.vessel_imo:
        q = q.filter(UserColumnPreference.vessel_imo == payload.vessel_imo)
    else:
        q = q.filter(UserColumnPreference.vessel_imo.is_(None))

    existing = q.first()
    if existing:
        existing.column_prefs = payload.column_prefs
    else:
        db.add(UserColumnPreference(
            user_id=current_user.id,
            source=payload.source,
            vessel_imo=payload.vessel_imo,
            column_prefs=payload.column_prefs,
        ))
    db.commit()
    return {"status": "saved"}


# ── GET /vessel-column-defaults  [All Users] 
@router.get("/vessel-column-defaults")
def get_vessel_column_defaults(
    source: str,
    vessel_imo: Optional[str] = None,
    db: Session = Depends(get_db_for_auth),
    current_user: User = Depends(get_current_user),
):
    """Retrieve the vessel-level column default (allowed for all authenticated users). Fallback to global if vessel_imo not found."""
    # First check specific vessel
    rec = None
    if vessel_imo:
        rec = db.query(VesselColumnDefault).filter(
            VesselColumnDefault.vessel_imo == vessel_imo,
            VesselColumnDefault.source     == source,
        ).first()
    
    # Fallback to global if no specific default
    if not rec:
        rec = db.query(VesselColumnDefault).filter(
            VesselColumnDefault.vessel_imo.is_(None),
            VesselColumnDefault.source     == source,
        ).first()

    return rec.column_prefs if rec else {}


# ── PUT /vessel-column-defaults  [Admin] ─────────────────────
@router.put("/vessel-column-defaults")
def save_vessel_column_defaults(
    payload: VesselColumnDefaultPayload,
    db: Session = Depends(get_db_for_auth),
    _admin: User = Depends(require_admin),
):
    """Admin: set the default column layout for a specific vessel or globally (upsert)."""
    q = db.query(VesselColumnDefault).filter(VesselColumnDefault.source == payload.source)
    if payload.vessel_imo:
        q = q.filter(VesselColumnDefault.vessel_imo == payload.vessel_imo)
    else:
        q = q.filter(VesselColumnDefault.vessel_imo.is_(None))
        
    existing = q.first()
    if existing:
        existing.column_prefs = payload.column_prefs
    else:
        db.add(VesselColumnDefault(
            vessel_imo=payload.vessel_imo,
            source=payload.source,
            column_prefs=payload.column_prefs,
        ))
    db.commit()
    return {"status": "saved"}
