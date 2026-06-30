"""
Charter-Party (CP) Performance API Routes
=========================================
CRUD for vessel_cp_config — the per-vessel × loading-condition CP speed/consumption
warranty values that drive CP compliance monitoring.

  GET  /cp/{imo}/config        - both Laden + Ballast warranty rows for a vessel
  POST /cp/{imo}/config        - upsert one loading-condition's warranty row
  GET  /cp/{imo}/performance   - WNI-style per-segment CP performance table
                                 (Good Weather vs Entire Voyage, Loss/Saving by
                                  FO and DO/GO, warranty / allowance / GW definition)
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import Vessel, VesselCPConfig
from backend.cp.cp_calculator import compute_cp_voyage_table

log = logging.getLogger(__name__)
router = APIRouter(prefix="/cp", tags=["cp"])

VALID_CONDS = ("Laden", "Ballast")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _config_to_dict(row) -> dict:
    cols = [c.name for c in VesselCPConfig.__table__.columns]
    return {c: getattr(row, c) for c in cols}


def _norm_cond(raw: str) -> str:
    """Normalise to 'Laden' / 'Ballast'; raise 422 otherwise."""
    cond = (raw or "").strip().capitalize()
    if cond not in VALID_CONDS:
        raise HTTPException(
            status_code=422,
            detail="loading_cond must be 'Laden' or 'Ballast'",
        )
    return cond


@router.get("/{imo}/config")
def get_cp_config(imo: str, db: Session = Depends(get_db)):
    """Return CP warranty config for a vessel, keyed by loading condition."""
    rows = db.query(VesselCPConfig).filter(VesselCPConfig.vessel_imo == imo).all()
    configs = {r.loading_cond: _config_to_dict(r) for r in rows}
    return {
        "vessel_imo": imo,
        "configs": configs,           # {"Laden": {...}, "Ballast": {...}}
        "_empty": len(configs) == 0,
    }


@router.post("/{imo}/config")
def upsert_cp_config(imo: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    """Upsert one loading-condition warranty row. `loading_cond` is required."""
    vessel = db.query(Vessel).filter(Vessel.imo_number == imo).first()
    if not vessel:
        raise HTTPException(status_code=404, detail=f"Vessel {imo} not found")

    cond = _norm_cond(payload.get("loading_cond"))

    row = (db.query(VesselCPConfig)
           .filter_by(vessel_imo=imo, loading_cond=cond)
           .first())
    if row is None:
        row = VesselCPConfig(vessel_imo=imo, loading_cond=cond)
        db.add(row)

    _allowed = {c.name for c in VesselCPConfig.__table__.columns} - {
        "vessel_imo", "loading_cond", "created_at", "updated_at"
    }
    for k, v in payload.items():
        if k in _allowed:
            setattr(row, k, v if v != "" else None)

    db.commit()
    db.refresh(row)
    return _config_to_dict(row)


# ── CP performance — WNI SeaNavigator-style segment table ────────────────────────

# Fuel columns in the normalized tables are stored as VARCHAR, so each must be
# safely cast text→number (non-numeric / blank → 0) before summing.
# FO = HFO + LFO ;  DO/GO = MDO (distillate).  Aggregated across all consumers.
def _numexpr(col):
    # Require at least one digit (rejects '', '.', text); optional sign / decimals.
    return f"(CASE WHEN {col} ~ '^[-+]?[0-9]+(\\.[0-9]+)?$' THEN {col}::double precision ELSE 0 END)"

_FO_COLS   = ["me_hfo", "me_lfo", "ae_hfo", "ae_lfo", "bl_hfo", "bl_lfo"]
_DOGO_COLS = ["me_mdo", "ae_mdo", "bl_mdo"]
_FO_EXPR   = "(" + "+".join(_numexpr(f"n.{c}") for c in _FO_COLS) + ")"
_DOGO_EXPR = "(" + "+".join(_numexpr(f"n.{c}") for c in _DOGO_COLS) + ")"

# Per-source join: WNI links via raw_report_id, MariApps via raw_mariapps_id.
_SOURCE_SQL = {
    "wni": ("JOIN noon_report_data n ON n.raw_report_id = a.raw_report_id", "wni"),
    "mari_apps": ("JOIN mariapps_reports_data n ON n.raw_report_id = a.raw_mariapps_id", "mari_apps"),
}


def _rows_for_source(db, imo, source, vlist):
    join, src = _SOURCE_SQL[source]
    sql = f"""
        SELECT a."Voyage_No", a."Loading_Cond", a."Date", a."From_Port", a."To_Port",
               a."Distance_nm", a."Duration_h", a."SOG_kn", a."STW_kn", a."BF_Wind",
               a."Sig_Wave_Ht_m", a."Current_Spd_kn", a.source_id,
               {_FO_EXPR} AS fo_mt, {_DOGO_EXPR} AS dogo_mt
        FROM analysis_data a
        {join}
        WHERE a.vessel_imo = :imo AND a.source_id = :src
    """
    params = {"imo": imo, "src": src}
    if vlist:
        sql += ' AND a."Voyage_No" = ANY(:vlist)'
        params["vlist"] = vlist
    sql += ' ORDER BY a."Voyage_No", a."Date"'
    return [dict(m) for m in db.execute(text(sql), params).mappings().all()]


@router.get("/{imo}/performance")
def cp_performance(
    imo: str,
    voyages: str = Query(None, description="Comma-separated Voyage_No values; omit for all"),
    source: str = Query(None, description="'wni' or 'mari_apps'; omit for both"),
    db: Session = Depends(get_db),
):
    """WNI-style per-segment CP performance for the selected voyage(s)."""
    cp_rows = db.query(VesselCPConfig).filter(VesselCPConfig.vessel_imo == imo).all()
    cp_by_cond = {r.loading_cond: _config_to_dict(r) for r in cp_rows}

    vlist = [v.strip() for v in voyages.split(",")] if voyages else None
    vlist = [v for v in vlist if v] if vlist else None
    sources = [source] if source in _SOURCE_SQL else ["wni", "mari_apps"]

    rows = []
    try:
        for s in sources:
            rows.extend(_rows_for_source(db, imo, s, vlist))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CP query failed: {e}")

    results = compute_cp_voyage_table(rows, cp_by_cond)
    return {
        "vessel_imo":    imo,
        "source":        source,
        "voyages":       voyages,
        "cp_configured": len(cp_by_cond) > 0,
        "results":       results,
    }
