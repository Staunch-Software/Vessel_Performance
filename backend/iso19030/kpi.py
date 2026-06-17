"""
ISO 19030 KPI Engine
=====================
Computes the 4 ISO 19030-2 Cl.9 KPIs from iso19030_results.

KPI 1 — Dry-Docking Performance
    Average speed loss % (vs B1) in window after DDn
    compared to average after DDn-1.
    RAG: green = improving, amber ≤ -5%, red ≤ -10%

KPI 2 — In-Service Performance
    Linear slope of speed loss % vs days within current DD interval.
    Reported as %/30 days.
    RAG: green < amber_slope, amber < red_slope, red ≥ red_slope

KPI 3 — Maintenance Trigger
    Rolling average of speed_loss_b2 over last N PASS records.
    YES (trigger) when rolling avg ≤ -maintenance_trigger_pct.

KPI 4 — Maintenance Effect
    Average speed loss after last maintenance event
    minus average before → positive value = improvement.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class KPIResult:
    vessel_imo: str = ''

    # Summary metric (from Excel KPI Dashboard row 5)
    # "Current avg speed loss (B2, PASS pts)" — mean SL_B2 in current DD interval
    current_avg_speed_loss_b2: Optional[float] = None
    current_avg_rag: str = 'grey'

    # KPI 1
    dd_performance_pct: Optional[float] = None     # avg speed loss current DD vs previous
    dd_performance_rag:  str = 'grey'               # 'green', 'amber', 'red', 'grey'

    # KPI 2
    in_service_slope_pct30d: Optional[float] = None  # %/30 days (negative = degrading)
    in_service_rag: str = 'grey'

    # KPI 3
    maintenance_trigger: bool = False               # True = time to clean
    rolling_avg_pct: Optional[float] = None        # rolling avg speed loss

    # KPI 4
    maintenance_effect_pct: Optional[float] = None  # improvement after last event
    last_event_type: str = ''
    last_event_date: Optional[date] = None

    # Meta
    total_pass_records: int = 0
    date_range_start: Optional[date] = None
    date_range_end: Optional[date] = None


# ── Main KPI computation ──────────────────────────────────────────────────────

def compute_kpis(vessel_imo: str, db: Session,
                 config=None, events: list = None,
                 data_source: str = "mariapps") -> KPIResult:
    """
    Compute all 4 ISO 19030 KPIs for a vessel.
    config: ISOConfig instance (for thresholds)
    events: list of VesselMaintenanceEvent rows
    data_source: 'mariapps' or 'wni'
    """
    from .calculator import ISOConfig
    if config is None:
        config = ISOConfig()

    result = KPIResult(vessel_imo=vessel_imo)

    # ── Load PASS records (speed_loss_b2 for KPI 2/3, speed_loss_b1 for KPI 1) ─
    rows = db.execute(text("""
        SELECT r.record_date, r.speed_loss_b1, r.speed_loss_b2, r.filter_pass
        FROM iso19030_results r
        WHERE r.vessel_imo = :imo
          AND r.filter_pass = TRUE
          AND COALESCE(r.data_source, 'mariapps') = :src
          AND (r.speed_loss_b1 IS NOT NULL OR r.speed_loss_b2 IS NOT NULL)
        ORDER BY r.record_date
    """), {"imo": vessel_imo, "src": data_source}).fetchall()

    if not rows:
        return result

    result.total_pass_records = len(rows)
    result.date_range_start = rows[0][0]
    result.date_range_end   = rows[-1][0]

    # ── Summary: current avg speed loss B2 (all PASS records) ─────────────────
    # Matches Excel KPI Dashboard "Current avg speed loss (B2, PASS pts)"
    all_sl_b2 = [float(r[2]) for r in rows if r[2] is not None]
    if all_sl_b2:
        avg_b2 = sum(all_sl_b2) / len(all_sl_b2)
        result.current_avg_speed_loss_b2 = round(avg_b2, 2)
        # RAG: GREEN if > −5%, AMBER if > −10%, RED if ≤ −10%
        if avg_b2 > -5:
            result.current_avg_rag = 'green'
        elif avg_b2 > -10:
            result.current_avg_rag = 'amber'
        else:
            result.current_avg_rag = 'red'

    # ── Sort maintenance events ────────────────────────────────────────────────
    if events is None:
        ev_rows = db.execute(text("""
            SELECT event_type, event_date FROM vessel_maintenance_events
            WHERE vessel_imo = :imo ORDER BY event_date
        """), {"imo": vessel_imo}).fetchall()
        events = [{"type": r[0], "date": r[1]} for r in ev_rows]

    drydocks = sorted(
        [e for e in events if 'dry' in e["type"].lower() or e["type"].upper() == 'DRY-DOCK'],
        key=lambda x: x["date"]
    )
    dd_latest   = drydocks[-1]["date"] if len(drydocks) >= 1 else None
    dd_previous = drydocks[-2]["date"] if len(drydocks) >= 2 else None

    # ── KPI 1: Dry-Docking Performance ────────────────────────────────────────
    if dd_latest and dd_previous:
        after_current  = [r[1] for r in rows if r[0] >= dd_latest  and r[1] is not None]
        after_previous = [r[1] for r in rows if dd_previous <= r[0] < dd_latest and r[1] is not None]
        if after_current and after_previous:
            avg_current  = sum(after_current)  / len(after_current)
            avg_previous = sum(after_previous) / len(after_previous)
            result.dd_performance_pct = avg_current - avg_previous
            if result.dd_performance_pct >= 0:
                result.dd_performance_rag = 'green'
            elif result.dd_performance_pct >= -5:
                result.dd_performance_rag = 'amber'
            else:
                result.dd_performance_rag = 'red'
    elif dd_latest:
        after_current = [r[1] for r in rows if r[0] >= dd_latest and r[1] is not None]
        if after_current:
            result.dd_performance_pct = sum(after_current) / len(after_current)
            result.dd_performance_rag = 'green' if result.dd_performance_pct > -5 else (
                'amber' if result.dd_performance_pct > -10 else 'red')

    # ── KPI 2: In-Service Performance (slope %/30d) ───────────────────────────
    interval_start = dd_latest if dd_latest else (rows[0][0] if rows else None)
    if interval_start:
        interval_rows = [(r[0], r[2]) for r in rows
                         if r[0] >= interval_start and r[2] is not None]
        if len(interval_rows) >= 4:
            slope = _linear_slope_per_30d(interval_rows)
            result.in_service_slope_pct30d = slope
            abs_slope = abs(slope) if slope < 0 else 0
            if abs_slope < config.amber_slope_pct30d:
                result.in_service_rag = 'green'
            elif abs_slope < config.red_slope_pct30d:
                result.in_service_rag = 'amber'
            else:
                result.in_service_rag = 'red'

    # ── KPI 3: Maintenance Trigger ────────────────────────────────────────────
    sl_b2 = [r[2] for r in rows if r[2] is not None]
    n = config.rolling_window_records
    if len(sl_b2) >= n:
        rolling_avg = sum(sl_b2[-n:]) / n
        result.rolling_avg_pct = rolling_avg
        result.maintenance_trigger = rolling_avg <= -config.maintenance_trigger_pct

    # ── KPI 4: Maintenance Effect ─────────────────────────────────────────────
    maint_events = sorted(
        [e for e in events if e["type"].lower() not in ('dry-dock', 'dry dock')],
        key=lambda x: x["date"]
    )
    if maint_events:
        last_ev = maint_events[-1]
        ev_date = last_ev["date"]
        result.last_event_type = last_ev["type"]
        result.last_event_date = ev_date

        window = timedelta(days=30)
        before = [r[2] for r in rows
                  if ev_date - window <= r[0] < ev_date and r[2] is not None]
        after  = [r[2] for r in rows
                  if ev_date <= r[0] <= ev_date + window and r[2] is not None]

        if before and after:
            avg_before = sum(before) / len(before)
            avg_after  = sum(after)  / len(after)
            result.maintenance_effect_pct = avg_after - avg_before  # positive = improvement

    return result


# ── Helper: linear slope ──────────────────────────────────────────────────────

def _linear_slope_per_30d(date_value_pairs: list) -> float:
    """
    Compute linear regression slope (%/day) and scale to %/30 days.
    date_value_pairs: list of (date, float)
    """
    if len(date_value_pairs) < 2:
        return 0.0

    base_date = date_value_pairs[0][0]
    xs = [(r[0] - base_date).days for r in date_value_pairs]
    ys = [r[1] for r in date_value_pairs]

    n = len(xs)
    sx  = sum(xs)
    sy  = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sx2 = sum(x * x for x in xs)

    denom = n * sx2 - sx * sx
    if denom == 0:
        return 0.0

    slope_per_day = (n * sxy - sx * sy) / denom
    return slope_per_day * 30.0   # convert to %/30 days
