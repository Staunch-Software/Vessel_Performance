"""
ISO 19030 API Routes
=====================
CRUD for vessel_iso_config, vessel_baseline_curves, vessel_maintenance_events.
Run-trigger and KPI endpoints.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.database import SessionLocal
from backend.models import (
    Vessel, VesselISOConfig, VesselBaselineCurve, VesselMaintenanceEvent
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/iso19030", tags=["iso19030"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── ISO Config ────────────────────────────────────────────────────────────────

@router.get("/{imo}/config")
def get_iso_config(imo: str, db: Session = Depends(get_db)):
    row = db.query(VesselISOConfig).filter(VesselISOConfig.vessel_imo == imo).first()
    if not row:
        return {"vessel_imo": imo, "_empty": True}
    return _config_to_dict(row)


@router.post("/{imo}/config")
def upsert_iso_config(imo: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    vessel = db.query(Vessel).filter(Vessel.imo_number == imo).first()
    if not vessel:
        raise HTTPException(status_code=404, detail=f"Vessel {imo} not found")

    row = db.query(VesselISOConfig).filter(VesselISOConfig.vessel_imo == imo).first()
    if row is None:
        row = VesselISOConfig(vessel_imo=imo)
        db.add(row)

    _allowed = {c.name for c in VesselISOConfig.__table__.columns} - {"vessel_imo", "created_at", "updated_at"}
    for k, v in payload.items():
        if k in _allowed:
            setattr(row, k, v if v != "" else None)

    db.commit()
    db.refresh(row)
    return _config_to_dict(row)


def _config_to_dict(row) -> dict:
    cols = [c.name for c in VesselISOConfig.__table__.columns]
    return {c: getattr(row, c) for c in cols}


# ── Baseline Curves ───────────────────────────────────────────────────────────

@router.get("/{imo}/baseline-curves")
def get_baseline_curves(imo: str, db: Session = Depends(get_db)):
    rows = db.query(VesselBaselineCurve).filter(VesselBaselineCurve.vessel_imo == imo).all()
    return [_curve_to_dict(r) for r in rows]


@router.post("/{imo}/baseline-curves")
def upsert_baseline_curve(imo: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    """Upsert one curve by (generation, condition). Required: generation, condition, a1, a0."""
    gen  = payload.get("generation", "").upper()
    cond = payload.get("condition", "").capitalize()
    if gen not in ("B1", "B2") or cond not in ("Laden", "Ballast"):
        raise HTTPException(status_code=422, detail="generation must be B1/B2, condition must be Laden/Ballast")

    row = (db.query(VesselBaselineCurve)
           .filter_by(vessel_imo=imo, generation=gen, condition=cond)
           .first())
    if row is None:
        row = VesselBaselineCurve(vessel_imo=imo, generation=gen, condition=cond)
        db.add(row)

    for k in ("a3", "a2", "a1", "a0", "effective_from", "notes"):
        if k in payload:
            v = payload[k]
            setattr(row, k, float(v) if k in ("a3","a2","a1","a0") and v is not None else v)

    db.commit()
    db.refresh(row)
    return _curve_to_dict(row)


@router.delete("/{imo}/baseline-curves/{curve_id}")
def delete_baseline_curve(imo: str, curve_id: int, db: Session = Depends(get_db)):
    row = db.query(VesselBaselineCurve).filter_by(id=curve_id, vessel_imo=imo).first()
    if not row:
        raise HTTPException(status_code=404, detail="Curve not found")
    db.delete(row)
    db.commit()
    return {"deleted": curve_id}


def _curve_to_dict(r) -> dict:
    return {
        "id": r.id, "vessel_imo": r.vessel_imo,
        "generation": r.generation, "condition": r.condition,
        "a3": r.a3, "a2": r.a2, "a1": r.a1, "a0": r.a0,
        "effective_from": str(r.effective_from) if r.effective_from else None,
        "notes": r.notes,
    }


# ── Maintenance Events ────────────────────────────────────────────────────────

@router.get("/{imo}/events")
def get_events(imo: str, db: Session = Depends(get_db)):
    rows = (db.query(VesselMaintenanceEvent)
            .filter(VesselMaintenanceEvent.vessel_imo == imo)
            .filter(text("EXTRACT(year FROM event_date) BETWEEN 1900 AND 9999"))
            .order_by(VesselMaintenanceEvent.event_date.desc())
            .all())
    return [_event_to_dict(r) for r in rows]


@router.post("/{imo}/events")
def add_event(imo: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    if not payload.get("event_type") or not payload.get("event_date"):
        raise HTTPException(status_code=422, detail="event_type and event_date are required")

    from datetime import date as _date
    try:
        raw_date = payload["event_date"]
        parsed = _date.fromisoformat(str(raw_date)) if not isinstance(raw_date, _date) else raw_date
        if not (1900 <= parsed.year <= 9999):
            raise HTTPException(status_code=422, detail=f"Invalid event year: {parsed.year}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid event_date: {exc}")

    ev = VesselMaintenanceEvent(
        vessel_imo=imo,
        event_type=payload["event_type"],
        event_date=parsed,
        notes=payload.get("notes"),
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return _event_to_dict(ev)


@router.delete("/{imo}/events/{event_id}")
def delete_event(imo: str, event_id: int, db: Session = Depends(get_db)):
    ev = db.query(VesselMaintenanceEvent).filter_by(id=event_id, vessel_imo=imo).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    db.delete(ev)
    db.commit()
    return {"deleted": event_id}


def _event_to_dict(r) -> dict:
    return {
        "id": r.id, "vessel_imo": r.vessel_imo,
        "event_type": r.event_type,
        "event_date": str(r.event_date),
        "notes": r.notes,
    }


# ── Run calculation ───────────────────────────────────────────────────────────

@router.post("/{imo}/run")
def run_iso19030(
    imo: str,
    data_source: str = Query(default="mariapps", description="'mariapps' or 'wni'"),
    db: Session = Depends(get_db),
):
    """Trigger ISO 19030 calculation for all records of a vessel."""
    from backend.iso19030.runner import run_for_vessel, run_for_vessel_wni
    try:
        if data_source == "wni":
            summary = run_for_vessel_wni(imo, db)
        else:
            summary = run_for_vessel(imo, db)
        return {"status": "ok", "data_source": data_source, **summary}
    except Exception as e:
        log.error(f"ISO 19030 run failed for {imo} (source={data_source}): {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── KPIs ──────────────────────────────────────────────────────────────────────

@router.get("/{imo}/kpis")
def get_kpis(
    imo: str,
    data_source: str = Query(default="mariapps"),
    db: Session = Depends(get_db),
):
    """Compute and return the 4 ISO 19030 KPIs for a vessel."""
    from backend.iso19030.runner import load_iso_config
    from backend.iso19030.kpi import compute_kpis
    from dataclasses import asdict

    config = load_iso_config(imo, db)
    kpi = compute_kpis(imo, db, config=config, data_source=data_source)

    return {
        "vessel_imo": imo,
        "kpi1_dry_docking": {
            "value": kpi.dd_performance_pct,
            "rag":   kpi.dd_performance_rag,
            "label": "Dry-Docking Performance",
            "unit":  "% speed loss",
        },
        "kpi2_in_service": {
            "value": kpi.in_service_slope_pct30d,
            "rag":   kpi.in_service_rag,
            "label": "In-Service Performance",
            "unit":  "%/30 days",
        },
        "kpi3_trigger": {
            "value":       kpi.rolling_avg_pct,
            "triggered":   kpi.maintenance_trigger,
            "label":       "Maintenance Trigger",
            "unit":        "% speed loss (rolling avg)",
        },
        "kpi4_effect": {
            "value":      kpi.maintenance_effect_pct,
            "event_type": kpi.last_event_type,
            "event_date": str(kpi.last_event_date) if kpi.last_event_date else None,
            "label":      "Maintenance Effect",
            "unit":       "% speed loss change",
        },
        # Summary metric — matches Excel KPI Dashboard
        # "Current avg speed loss (B2, PASS pts)" — mean SL vs post-DD baseline
        "summary_avg_speed_loss": {
            "value": kpi.current_avg_speed_loss_b2,
            "rag":   kpi.current_avg_rag,
            "label": "Current Avg Speed Loss (B2, PASS)",
            "unit":  "%",
            "note":  "Mean in-service speed loss vs post-DD baseline",
        },
        "meta": {
            "total_pass_records": kpi.total_pass_records,
            "date_from":          str(kpi.date_range_start) if kpi.date_range_start else None,
            "date_to":            str(kpi.date_range_end)   if kpi.date_range_end else None,
        },
    }


# ── Speed loss data for chart ─────────────────────────────────────────────────

@router.get("/{imo}/speed-loss")
def get_speed_loss_data(
    imo: str,
    loading_condition: Optional[str] = Query(default="all"),
    baseline: Optional[str] = Query(default="B2"),
    data_source: Optional[str] = Query(default="mariapps"),
    db: Session = Depends(get_db),
):
    """
    Returns ISO-corrected speed loss data for the SpeedLossChart.
    Each record: date, speed_loss (%), condition, filter_pass.
    """
    lc = (loading_condition or "all").strip().lower()
    src = data_source or "mariapps"

    where_extra = ""
    if lc not in ("all", ""):
        where_extra = f"AND LOWER(r.condition) LIKE '{lc[0]}%'"

    col = "speed_loss_b2" if baseline.upper() == "B2" else "speed_loss_b1"

    rows = db.execute(text(f"""
        SELECT r.record_date, r.{col} AS speed_loss,
               r.condition, r.filter_pass, r.filter_reason,
               r.p_corr, r.stw_corr, r.v_exp_b1, r.v_exp_b2
        FROM iso19030_results r
        WHERE r.vessel_imo = :imo
          AND r.filter_pass = TRUE
          AND COALESCE(r.data_source, 'mariapps') = :src
          AND r.{col} IS NOT NULL
          {where_extra}
        ORDER BY r.record_date
    """), {"imo": imo, "src": src}).fetchall()

    return [
        {
            "Date":      str(r[0]),
            "Speed_Loss_pct": round(float(r[1]), 3),
            "Loading_Cond":   r[2],
            "filter_pass":    r[3],
            "P_corr_kW":      round(float(r[5]), 1) if r[5] else None,
            "STW_corr_kn":    round(float(r[6]), 2) if r[6] else None,
        }
        for r in rows
    ]


# ── ISO speed-power data for scatter chart ────────────────────────────────────

@router.get("/{imo}/speed-power-iso")
def get_speed_power_iso(
    imo: str,
    loading_condition: Optional[str] = Query(default="all"),
    db: Session = Depends(get_db),
):
    """
    Returns ISO 19030 corrected (P_corr, STW_corr) scatter data
    plus baseline curve points for the speed-power chart.

    Dots:     (P_corr kW, STW_corr kn) from iso19030_results — PASS records only
    Baseline: evaluated from vessel_baseline_curves polynomial
    Fallback: if no ISO results exist, returns empty so chart falls back to raw data
    """
    from backend.iso19030.runner import load_baseline_curves, load_iso_config
    import json

    lc = (loading_condition or "all").strip().lower()
    lc_filter = ""
    if lc not in ("all", ""):
        lc_filter = f"AND LOWER(r.condition) LIKE '{lc[0]}%'"

    # ── Actual ISO corrected scatter points ───────────────────────────────────
    rows = db.execute(text(f"""
        SELECT r.p_corr, r.stw_corr, r.condition, r.record_date
        FROM iso19030_results r
        WHERE r.vessel_imo = :imo
          AND r.filter_pass = TRUE
          AND r.p_corr     IS NOT NULL
          AND r.stw_corr   IS NOT NULL
          AND r.p_corr > 0
          {lc_filter}
        ORDER BY r.record_date
    """), {"imo": imo}).fetchall()

    actual = [
        {
            "speed":             round(float(r[1]), 2),   # STW_corr as speed
            "power":             round(float(r[0]), 1),   # P_corr as power
            "loading_condition": r[2],
            "data_source":       "iso_corrected",
        }
        for r in rows
    ]

    # ── Baseline curve from vessel_baseline_curves ────────────────────────────
    config = load_iso_config(imo, db)
    curves = load_baseline_curves(imo, db)

    active_gen = config.active_baseline if config else "B2"
    cond_for_baseline = "Laden" if lc.startswith("l") else ("Ballast" if lc.startswith("b") else "Laden")
    curve = curves.get((active_gen, cond_for_baseline))

    baseline_points = []
    baseline_source = None

    if curve and actual:
        p_vals = [r["power"] for r in actual]
        p_min = max(0, min(p_vals) - 500)
        p_max = max(p_vals) + 500
        steps = 40
        step = (p_max - p_min) / steps
        for i in range(steps + 1):
            p = p_min + i * step
            v = curve.v_exp(p)
            if v > 0:
                baseline_points.append({"speed": round(v, 3), "power": round(p, 1)})
        baseline_source = f"{active_gen} {cond_for_baseline} ({curve.a1:.3f}×10⁻³ P + {curve.a0})"
    elif actual:
        # No curves configured yet — no baseline
        baseline_source = None

    return {
        "actual":          actual,
        "baseline_points": baseline_points,
        "baseline_source": baseline_source,
        "count":           len(actual),
        "corrected":       True,
    }


# ── Verification endpoint ─────────────────────────────────────────────────────

@router.get("/{imo}/verify")
def verify_iso19030(imo: str, db: Session = Depends(get_db)):
    """
    Quick verification: shows how many records were processed,
    PASS vs EXCL breakdown, top filter reasons, and speed loss stats.
    Use this to confirm the ISO 19030 calculation ran correctly.
    """
    total = db.execute(text(
        "SELECT COUNT(*) FROM iso19030_results WHERE vessel_imo = :imo"
    ), {"imo": imo}).scalar() or 0

    if total == 0:
        return {"status": "not_run", "message": "No ISO 19030 results found. Click 'Run ISO 19030' first."}

    # PASS / EXCL counts
    counts = db.execute(text("""
        SELECT filter_pass, COUNT(*) FROM iso19030_results
        WHERE vessel_imo = :imo GROUP BY filter_pass
    """), {"imo": imo}).fetchall()
    pass_count = next((r[1] for r in counts if r[0] is True),  0)
    excl_count = next((r[1] for r in counts if r[0] is False), 0)

    # Top EXCL reasons
    reasons = db.execute(text("""
        SELECT filter_reason, COUNT(*) as cnt
        FROM iso19030_results
        WHERE vessel_imo = :imo AND filter_pass = FALSE
        GROUP BY filter_reason ORDER BY cnt DESC LIMIT 8
    """), {"imo": imo}).fetchall()

    # Speed loss stats (PASS records, vs B2)
    stats = db.execute(text("""
        SELECT
            condition,
            COUNT(*) as cnt,
            ROUND(AVG(speed_loss_b2)::numeric, 3) as avg_sl,
            ROUND(MIN(speed_loss_b2)::numeric, 3) as min_sl,
            ROUND(MAX(speed_loss_b2)::numeric, 3) as max_sl,
            ROUND(AVG(p_corr)::numeric,       0) as avg_p_corr,
            ROUND(AVG(stw_corr)::numeric,      2) as avg_stw
        FROM iso19030_results
        WHERE vessel_imo = :imo
          AND filter_pass = TRUE
          AND speed_loss_b2 IS NOT NULL
        GROUP BY condition ORDER BY condition
    """), {"imo": imo}).fetchall()

    # Missing data counts (records that passed filter but had no power/STW)
    missing = db.execute(text("""
        SELECT
            SUM(CASE WHEN p_corr    IS NULL THEN 1 ELSE 0 END) AS missing_power,
            SUM(CASE WHEN stw_corr  IS NULL THEN 1 ELSE 0 END) AS missing_stw,
            SUM(CASE WHEN speed_loss_b2 IS NULL AND filter_pass = TRUE THEN 1 ELSE 0 END) AS missing_speed_loss
        FROM iso19030_results WHERE vessel_imo = :imo
    """), {"imo": imo}).fetchone()

    return {
        "status":      "ok",
        "total":       total,
        "pass":        pass_count,
        "excl":        excl_count,
        "pass_pct":    round(pass_count / total * 100, 1) if total else 0,
        "excl_reasons": [{"reason": r[0] or "Unknown", "count": r[1]} for r in reasons],
        "speed_loss_stats": [
            {
                "condition":   r[0],
                "count":       r[1],
                "avg_speed_loss_b2_pct": float(r[2]) if r[2] else None,
                "min_speed_loss_b2_pct": float(r[3]) if r[3] else None,
                "max_speed_loss_b2_pct": float(r[4]) if r[4] else None,
                "avg_p_corr_kw":         float(r[5]) if r[5] else None,
                "avg_stw_corr_kn":       float(r[6]) if r[6] else None,
            }
            for r in stats
        ],
        "data_quality": {
            "missing_power":      int(missing[0] or 0),
            "missing_stw":        int(missing[1] or 0),
            "missing_speed_loss": int(missing[2] or 0),
        },
    }
