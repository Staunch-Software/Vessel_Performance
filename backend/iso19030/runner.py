"""
ISO 19030 Runner
=================
Loads config/curves from DB, fetches noon records, runs the calculator,
and stores results in iso19030_results.

Can run as:
  - Full backfill: process all analysis_data rows for a vessel
  - Single record: called from pipeline after new record saved
"""

import logging
from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from .calculator import (
    ISOConfig, BaselineCurve, NoonRecord, calculate
)

log = logging.getLogger(__name__)


# ── Load config from DB ───────────────────────────────────────────────────────

def load_iso_config(vessel_imo: str, db: Session) -> Optional[ISOConfig]:
    """Load VesselISOConfig row and return ISOConfig dataclass."""
    row = db.execute(text("""
        SELECT lpp_m, breadth_m, block_coeff_cb, transverse_area_m2,
               propeller_pitch_m, propulsive_eff_eta_d, shaft_eff_eta_shaft,
               rho_ref_kgm3, sfoc_curve,
               wind_filter_ms, wave_hs_max_m, depth_draft_ratio_min,
               rudder_max_deg, rot_max_degmin, loading_window_pct,
               c_aa, c_aw, condition_split_draft_m, active_baseline,
               ref_displacement_laden_t, ref_displacement_ballast_t,
               maintenance_trigger_pct, amber_slope_pct30d,
               red_slope_pct30d, rolling_window_records
        FROM vessel_iso_config WHERE vessel_imo = :imo
    """), {"imo": vessel_imo}).fetchone()

    if not row:
        log.warning(f"No ISO config for {vessel_imo} — using defaults")
        return ISOConfig()

    cfg = ISOConfig()
    fields = [
        'lpp_m','breadth_m','block_coeff_cb','transverse_area_m2',
        'propeller_pitch_m','propulsive_eff_eta_d','shaft_eff_eta_shaft',
        'rho_ref_kgm3','sfoc_curve',
        'wind_filter_ms','wave_hs_max_m','depth_draft_ratio_min',
        'rudder_max_deg','rot_max_degmin','loading_window_pct',
        'c_aa','c_aw','condition_split_draft_m','active_baseline',
        'ref_displacement_laden_t','ref_displacement_ballast_t',
        'maintenance_trigger_pct','amber_slope_pct30d',
        'red_slope_pct30d','rolling_window_records',
    ]
    for i, f in enumerate(fields):
        v = row[i]
        if v is not None:
            if f == 'sfoc_curve':
                import json as _json
                data = v if isinstance(v, list) else _json.loads(v) if isinstance(v, str) else None
                if data:
                    cfg.sfoc_curve = [(r['load_pct'], r['sfoc_gkwh'], r['lcv_kjkg']) for r in data]
            elif f == 'active_baseline':
                cfg.active_baseline = str(v)
            else:
                try:
                    setattr(cfg, f, float(v) if f != 'rolling_window_records' else int(v))
                except (TypeError, ValueError):
                    pass
    return cfg


def load_baseline_curves(vessel_imo: str, db: Session) -> dict:
    """
    Load all 4 baseline curves for a vessel.
    Returns dict keyed by (generation, condition).
    Missing curves get sensible defaults so calculation still runs.
    """
    rows = db.execute(text("""
        SELECT generation, condition, a3, a2, a1, a0
        FROM vessel_baseline_curves WHERE vessel_imo = :imo
    """), {"imo": vessel_imo}).fetchall()

    curves = {}
    for r in rows:
        gen, cond = r[0], r[1]
        curves[(gen, cond)] = BaselineCurve(
            generation=gen, condition=cond,
            a3=float(r[2] or 0), a2=float(r[3] or 0),
            a1=float(r[4]), a0=float(r[5])
        )

    # Fill missing with defaults
    defaults = {
        ('B1', 'Laden'):   BaselineCurve('B1', 'Laden',   a1=1.05, a0=6.5),
        ('B1', 'Ballast'): BaselineCurve('B1', 'Ballast', a1=1.18, a0=7.4),
        ('B2', 'Laden'):   BaselineCurve('B2', 'Laden',   a1=1.08, a0=6.7),
        ('B2', 'Ballast'): BaselineCurve('B2', 'Ballast', a1=1.21, a0=7.6),
    }
    for key, default in defaults.items():
        if key not in curves:
            curves[key] = default

    return curves


# ── Build NoonRecord from analysis_data + noon_report_data ───────────────────

def _build_noon_record(ad_row, nd_row) -> NoonRecord:
    """Combine analysis_data and noon_report_data rows into NoonRecord."""
    def _f(v): return float(v) if v is not None else None

    # STW: prefer Speed_Through_Water from analysis_data, else try noon_report_data
    stw = _f(getattr(ad_row, 'STW_kn', None))
    if stw is None and nd_row is not None:
        stw = _f(getattr(nd_row, 'stw', None))

    # Wind: relative wind speed in m/s
    wind_ms = _f(getattr(ad_row, 'Rel_Wind_Spd_ms', None))
    if wind_ms is None and nd_row is not None:
        ws_kn = _f(getattr(nd_row, 'wind_speed', None))
        if ws_kn:
            wind_ms = ws_kn * 0.5144

    return NoonRecord(
        analysis_id   = ad_row.id,
        vessel_imo    = ad_row.vessel_imo,
        record_date   = ad_row.Date,
        draft_fwd_m   = _f(getattr(ad_row, 'Draft_Fwd_m', None)),
        draft_aft_m   = _f(getattr(ad_row, 'Draft_Aft_m', None)),
        stw_raw_kn    = stw or _f(getattr(ad_row, 'SOG_kn', None)),  # fallback to SOG
        sog_kn        = _f(getattr(ad_row, 'SOG_kn', None)),
        me_power_kw   = _f(getattr(ad_row, 'Shaft_Power_kW', None)) or _f(getattr(ad_row, 'Est_Power_kW', None)),
        me_foc_kgph   = None,  # daily total not directly usable here
        # Guard RPM: only use if in valid ME range (20-300). Higher values are
        # revolution counters (cumulative), not actual RPM — causes wrong P_source.
        me_rpm        = _f(getattr(ad_row, 'Shaft_RPM', None))
                        if (_f(getattr(ad_row, 'Shaft_RPM', None)) or 0) <= 300
                        else None,
        wind_speed_ms = wind_ms,
        wave_hs_m     = _f(getattr(ad_row, 'Sig_Wave_Ht_m', None)),
        sea_temp_c    = _f(getattr(ad_row, 'Water_Temp_C', None)),
        air_temp_c    = None,
        air_pressure_hpa = None,
        water_depth_m = _f(getattr(ad_row, 'Water_Depth_m', None)),
        rudder_deg    = _f(getattr(ad_row, 'Rudder_Angle_deg', None)),
        rot_degmin    = None,
        loading_condition = str(getattr(ad_row, 'Loading_Cond', '') or ''),
        displacement_t    = _f(getattr(ad_row, 'Displacement_MT', None)),
    )


# ── Upsert result ─────────────────────────────────────────────────────────────

def _upsert_result(db: Session, res) -> None:
    db.execute(text("""
        INSERT INTO iso19030_results
            (analysis_id, vessel_imo, record_date, condition, data_source,
             stw_corr, filter_pass, filter_reason,
             delta_actual, rho_sw, dp_wind, dp_wave, p_source, p_corr,
             v_exp_b1, v_exp_b2, speed_loss_b1, speed_loss_b2)
        VALUES
            (:analysis_id, :vessel_imo, :record_date, :condition, 'mariapps',
             :stw_corr, :filter_pass, :filter_reason,
             :delta_actual, :rho_sw, :dp_wind, :dp_wave, :p_source, :p_corr,
             :v_exp_b1, :v_exp_b2, :speed_loss_b1, :speed_loss_b2)
        ON CONFLICT (analysis_id) DO UPDATE SET
            condition      = EXCLUDED.condition,
            data_source    = EXCLUDED.data_source,
            stw_corr       = EXCLUDED.stw_corr,
            filter_pass    = EXCLUDED.filter_pass,
            filter_reason  = EXCLUDED.filter_reason,
            delta_actual   = EXCLUDED.delta_actual,
            rho_sw         = EXCLUDED.rho_sw,
            dp_wind        = EXCLUDED.dp_wind,
            dp_wave        = EXCLUDED.dp_wave,
            p_source       = EXCLUDED.p_source,
            p_corr         = EXCLUDED.p_corr,
            v_exp_b1       = EXCLUDED.v_exp_b1,
            v_exp_b2       = EXCLUDED.v_exp_b2,
            speed_loss_b1  = EXCLUDED.speed_loss_b1,
            speed_loss_b2  = EXCLUDED.speed_loss_b2,
            updated_at     = NOW()
    """), {
        "analysis_id":  res.analysis_id,
        "vessel_imo":   res.vessel_imo,
        "record_date":  res.record_date,
        "condition":    res.condition,
        "stw_corr":     res.stw_corr,
        "filter_pass":  res.filter_pass,
        "filter_reason": res.filter_reason,
        "delta_actual": res.delta_actual,
        "rho_sw":       res.rho_sw,
        "dp_wind":      res.dp_wind,
        "dp_wave":      res.dp_wave,
        "p_source":     res.p_source,
        "p_corr":       res.p_corr,
        "v_exp_b1":     res.v_exp_b1,
        "v_exp_b2":     res.v_exp_b2,
        "speed_loss_b1": res.speed_loss_b1,
        "speed_loss_b2": res.speed_loss_b2,
    })


# ── Public API ────────────────────────────────────────────────────────────────

def run_for_vessel(vessel_imo: str, db: Session, batch_size: int = 100) -> dict:
    """
    Run ISO 19030 calculation for all analysis_data records of a vessel.
    Returns summary dict.
    """
    from ..models import AnalysisData, NoonReportData

    config = load_iso_config(vessel_imo, db)
    curves = load_baseline_curves(vessel_imo, db)

    b1l = curves[('B1', 'Laden')]
    b1b = curves[('B1', 'Ballast')]
    b2l = curves[('B2', 'Laden')]
    b2b = curves[('B2', 'Ballast')]

    total = db.query(AnalysisData).filter(AnalysisData.vessel_imo == vessel_imo).count()
    log.info(f"ISO 19030 run for {vessel_imo}: {total} records")

    processed = pass_count = excl_count = error_count = 0
    offset = 0

    while True:
        ad_rows = (db.query(AnalysisData)
                   .filter(AnalysisData.vessel_imo == vessel_imo)
                   .order_by(AnalysisData.Date)
                   .offset(offset).limit(batch_size).all())
        if not ad_rows:
            break

        for ad in ad_rows:
            try:
                nd = None
                if ad.raw_report_id:
                    nd = db.query(NoonReportData).filter(
                        NoonReportData.raw_report_id == ad.raw_report_id
                    ).first()

                record = _build_noon_record(ad, nd)
                result = calculate(record, config, b1l, b1b, b2l, b2b)
                _upsert_result(db, result)

                if result.filter_pass:
                    pass_count += 1
                else:
                    excl_count += 1
                processed += 1
            except Exception as e:
                log.error(f"  ISO calc error analysis_id={ad.id}: {e}")
                error_count += 1

        db.commit()
        offset += batch_size
        log.info(f"  {min(offset, total)}/{total} processed")

    log.info(f"ISO 19030 complete: {pass_count} PASS, {excl_count} EXCL, {error_count} errors")
    return {"processed": processed, "pass": pass_count, "excl": excl_count, "errors": error_count}


# ── WNI data source runner ────────────────────────────────────────────────────
# WNI column → NoonRecord field mapping
_WNI_COL = {
    "sog":          "Vessel_SOG_avg_operational_LF",   # no STW in WNI, use SOG
    "draft_fwd":    "Vessel_Tf_avg_operational_LF",
    "draft_aft":    "Vessel_Ta_avg_operational_LF",
    "displacement": "Vessel_DISP_avg_operational_LF",
    "me_power":     "ME_PeffestME_avg_operational_LF",
    "me_rpm":       "ME_NME_avg_operational_LF",
    "wind_ms":      "Weather_Uwit_avg_operational_LF",  # m/s from WNI
    "wave_hs":      "Weather_Hwv_avg_operational_LF",
}

def _build_noon_record_wni(row: dict) -> NoonRecord:
    def _f(k): return float(row[k]) if row.get(k) is not None else None
    return NoonRecord(
        analysis_id   = None,
        vessel_imo    = row["vessel_imo"],
        record_date   = row["date"],
        draft_fwd_m   = _f(_WNI_COL["draft_fwd"]),
        draft_aft_m   = _f(_WNI_COL["draft_aft"]),
        stw_raw_kn    = _f(_WNI_COL["sog"]),   # WNI has SOG only
        sog_kn        = _f(_WNI_COL["sog"]),
        me_power_kw   = _f(_WNI_COL["me_power"]),
        me_foc_kgph   = None,
        me_rpm        = _f(_WNI_COL["me_rpm"])
                        if (_f(_WNI_COL["me_rpm"]) or 0) <= 300 else None,
        wind_speed_ms = _f(_WNI_COL["wind_ms"]),
        wave_hs_m     = _f(_WNI_COL["wave_hs"]),
        sea_temp_c    = None,
        air_temp_c    = None,
        air_pressure_hpa = None,
        water_depth_m = None,
        rudder_deg    = None,
        rot_degmin    = None,
        loading_condition = str(row.get("loading_condition") or ""),
        displacement_t    = _f(_WNI_COL["displacement"]),
    )


def _upsert_result_wni(db: Session, res) -> None:
    """Upsert using (vessel_imo, record_date) for WNI source."""
    db.execute(text("""
        INSERT INTO iso19030_results
            (vessel_imo, record_date, condition, data_source,
             stw_corr, filter_pass, filter_reason,
             delta_actual, rho_sw, dp_wind, dp_wave, p_source, p_corr,
             v_exp_b1, v_exp_b2, speed_loss_b1, speed_loss_b2)
        VALUES
            (:vessel_imo, :record_date, :condition, 'wni',
             :stw_corr, :filter_pass, :filter_reason,
             :delta_actual, :rho_sw, :dp_wind, :dp_wave, :p_source, :p_corr,
             :v_exp_b1, :v_exp_b2, :speed_loss_b1, :speed_loss_b2)
        ON CONFLICT (vessel_imo, record_date) WHERE data_source = 'wni'
        DO UPDATE SET
            condition      = EXCLUDED.condition,
            stw_corr       = EXCLUDED.stw_corr,
            filter_pass    = EXCLUDED.filter_pass,
            filter_reason  = EXCLUDED.filter_reason,
            delta_actual   = EXCLUDED.delta_actual,
            rho_sw         = EXCLUDED.rho_sw,
            dp_wind        = EXCLUDED.dp_wind,
            dp_wave        = EXCLUDED.dp_wave,
            p_source       = EXCLUDED.p_source,
            p_corr         = EXCLUDED.p_corr,
            v_exp_b1       = EXCLUDED.v_exp_b1,
            v_exp_b2       = EXCLUDED.v_exp_b2,
            speed_loss_b1  = EXCLUDED.speed_loss_b1,
            speed_loss_b2  = EXCLUDED.speed_loss_b2,
            updated_at     = NOW()
    """), {
        "vessel_imo":   res.vessel_imo,
        "record_date":  res.record_date,
        "condition":    res.condition,
        "stw_corr":     res.stw_corr,
        "filter_pass":  res.filter_pass,
        "filter_reason": res.filter_reason,
        "delta_actual": res.delta_actual,
        "rho_sw":       res.rho_sw,
        "dp_wind":      res.dp_wind,
        "dp_wave":      res.dp_wave,
        "p_source":     res.p_source,
        "p_corr":       res.p_corr,
        "v_exp_b1":     res.v_exp_b1,
        "v_exp_b2":     res.v_exp_b2,
        "speed_loss_b1": res.speed_loss_b1,
        "speed_loss_b2": res.speed_loss_b2,
    })


def run_for_vessel_wni(vessel_imo: str, db: Session, batch_size: int = 200) -> dict:
    """
    Run ISO 19030 from expanded_wni_data instead of analysis_data.
    Used for testing when MariApps data has quality issues.
    """
    config = load_iso_config(vessel_imo, db)
    curves = load_baseline_curves(vessel_imo, db)

    b1l = curves[('B1', 'Laden')]
    b1b = curves[('B1', 'Ballast')]
    b2l = curves[('B2', 'Laden')]
    b2b = curves[('B2', 'Ballast')]

    # Build SELECT with only columns that exist in expanded_wni_data
    wni_cols = ["vessel_imo", "date", "loading_condition"] + list(_WNI_COL.values())
    col_sql = ", ".join(f'"{c}"' for c in wni_cols)

    total_q = db.execute(text(
        "SELECT count(1) FROM expanded_wni_data WHERE vessel_imo = :imo"
    ), {"imo": vessel_imo}).scalar() or 0
    log.info(f"ISO 19030 WNI run for {vessel_imo}: {total_q} records")

    processed = pass_count = excl_count = error_count = 0
    offset = 0

    while True:
        rows = db.execute(text(
            f"SELECT {col_sql} FROM expanded_wni_data "
            f"WHERE vessel_imo = :imo ORDER BY date LIMIT :lim OFFSET :off"
        ), {"imo": vessel_imo, "lim": batch_size, "off": offset}).fetchall()
        if not rows:
            break

        keys = wni_cols
        for raw in rows:
            row = dict(zip(keys, raw))
            try:
                record = _build_noon_record_wni(row)
                result = calculate(record, config, b1l, b1b, b2l, b2b)
                _upsert_result_wni(db, result)
                if result.filter_pass:
                    pass_count += 1
                else:
                    excl_count += 1
                processed += 1
            except Exception as e:
                log.error(f"  ISO WNI calc error date={row.get('date')}: {e}")
                error_count += 1

        db.commit()
        offset += batch_size

    log.info(f"ISO 19030 WNI complete: {pass_count} PASS, {excl_count} EXCL, {error_count} errors")
    return {"processed": processed, "pass": pass_count, "excl": excl_count, "errors": error_count}


def run_single(analysis_id: int, db: Session) -> None:
    """Run ISO 19030 for a single analysis_data record (called from live pipeline)."""
    from ..models import AnalysisData, NoonReportData

    ad = db.query(AnalysisData).filter(AnalysisData.id == analysis_id).first()
    if not ad:
        return

    config = load_iso_config(ad.vessel_imo, db)
    curves = load_baseline_curves(ad.vessel_imo, db)

    nd = None
    if ad.raw_report_id:
        nd = db.query(NoonReportData).filter(
            NoonReportData.raw_report_id == ad.raw_report_id
        ).first()

    record = _build_noon_record(ad, nd)
    result = calculate(
        record, config,
        curves[('B1','Laden')], curves[('B1','Ballast')],
        curves[('B2','Laden')], curves[('B2','Ballast')]
    )
    _upsert_result(db, result)
