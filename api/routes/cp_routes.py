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
from backend.models import Vessel, VesselCPConfig, CPVesselDescription, CPSeaWarranty
from backend.cp.cp_calculator import compute_cp_voyage_table, not_computable_result
from backend.cp.cp_remarks_parser import parse_cp_remarks, pick_instruction_for_condition
from backend.voyage_window import find_bosp_eosp_window

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

# All 8 documented consumer prefixes (me/ae/bl/combl/inc/aeb/blfo/eg — same
# convention as emission_routes.py's _CONSUMERS and the PDF report's
# equipment-fuel breakdown), not just me/ae/bl. Found 2026-09 via an
# independent audit script cross-checking raw data against this endpoint:
# under-counted good_wx.fo_mt/dogo_mt (and Loss/Saving) on every vessel that
# actually uses Composite Boiler, Incinerator, or the other secondary
# consumers (AM KIRTI, GCL FOS, AMNSI MAXIMUS, GCL SARASWATI, AMNSI
# STALLION), matching a Composite Boiler mapping gap fixed once already
# elsewhere but never closed here.
_CONSUMER_PREFIXES = ("me", "ae", "bl", "combl", "inc", "aeb", "blfo", "eg")
_FO_COLS   = [f"{c}_{g}" for c in _CONSUMER_PREFIXES for g in ("hfo", "lfo")]
_DOGO_COLS = [f"{c}_mdo" for c in _CONSUMER_PREFIXES]
_FO_EXPR   = "(" + "+".join(_numexpr(f"n.{c}") for c in _FO_COLS) + ")"
_DOGO_EXPR = "(" + "+".join(_numexpr(f"n.{c}") for c in _DOGO_COLS) + ")"

# Per-source join: WNI links via raw_report_id, MariApps via raw_mariapps_id.
_SOURCE_SQL = {
    "wni": ("JOIN noon_report_data n ON n.raw_report_id = a.raw_report_id", "wni"),
    "mari_apps": ("JOIN mariapps_reports_data n ON n.raw_report_id = a.raw_mariapps_id", "mari_apps"),
    "Wartsila FOS": ("JOIN noon_report_data n ON n.raw_report_id = a.raw_report_id", "Wartsila FOS"),
}


def _rows_for_source(db, imo, source, vlist, loading_cond=None):
    join, src = _SOURCE_SQL[source]
    sql = f"""
        SELECT a."Voyage_No", a."Loading_Cond", a."Date", a."Time_UTC", a."From_Port", a."To_Port",
               a."Distance_nm", a."Duration_h", a."SOG_kn", a."STW_kn", a."BF_Wind",
               a."Sig_Wave_Ht_m", a."Current_Spd_kn", a.source_id, a.raw_mariapps_id,
               {_FO_EXPR} AS fo_mt, {_DOGO_EXPR} AS dogo_mt,
               n.log_type AS event_type
        FROM analysis_data a
        {join}
        WHERE a.vessel_imo = :imo AND a.source_id = :src
    """
    params = {"imo": imo, "src": src}
    if vlist:
        sql += ' AND a."Voyage_No" = ANY(:vlist)'
        params["vlist"] = vlist
        
    if loading_cond and loading_cond.lower() != "all":
        lc = loading_cond.lower()
        if lc == "laden":
            sql += " AND UPPER(a.\"Loading_Cond\") IN ('LADEN', 'L', 'LD')"
        elif lc == "ballast":
            sql += " AND UPPER(a.\"Loading_Cond\") IN ('BALLAST', 'B', 'BL')"
        else:
            sql += " AND a.\"Loading_Cond\" ILIKE :lc"
            params["lc"] = loading_cond
            
    sql += ' ORDER BY a."Voyage_No", a."Date", a."Time_UTC"'
    raw_rows = [dict(m) for m in db.execute(text(sql), params).mappings().all()]
    
    # Filter rows strictly by BOSP and EOSP (to match get_voyage_summary).
    # A voyage/leg is only "finalised" once it has a real EOSP after its COSP
    # (BOSP) — an ongoing voyage with no EOSP yet is excluded entirely rather
    # than reported using its last available row as a stand-in arrival (client
    # request 2026-08: "report will be prepared only when EOSP comes after
    # COSP and ports will be finalised only from EOSP event report"). Any
    # trailing rows after the last EOSP (an unfinished next leg) are dropped
    # too, for the same reason.
    #
    # excluded_voyages tracks which voyages produced ZERO usable rows and
    # why, so the caller can surface an explicit "not computable" result
    # instead of the voyage just silently vanishing with no explanation
    # (client request 2026-09 — this used to look like a bug, twice: once
    # for "no EOSP", and separately for the inverted-range case below,
    # found testing this exact fix on GCL FOS voyage 001/01).
    valid_rows = []
    excluded_voyages = {}

    # Group by Voyage_No to apply bounds per voyage
    by_voyage = {}
    for r in raw_rows:
        by_voyage.setdefault(r["Voyage_No"], []).append(r)

    for v_no, v_rows in by_voyage.items():
        # v_rows is already Date/Time_UTC-ordered (the SQL's own ORDER BY).
        dated = [(f"{r['Date']}T{r['Time_UTC'] or '00:00'}", r["event_type"], r) for r in v_rows]

        eosps_exist = any(et and "EOSP" in et.upper() for _, et, _ in dated)
        if not eosps_exist:
            excluded_voyages[v_no] = "Voyage not yet complete — no EOSP report found."
            continue  # ongoing voyage — no EOSP yet, nothing to report on it

        window = find_bosp_eosp_window(dated)
        if window is None:
            # dep_dt landed AT OR AFTER arr_dt — no BOSP precedes this
            # voyage's own EOSP, so the range collapsed to nothing useful
            # (see find_bosp_eosp_window's doc comment).
            excluded_voyages[v_no] = (
                "No valid departure-to-arrival window found for this voyage "
                "(its EOSP predates any usable departure record — likely a "
                "port-call gap rather than a real passage)."
            )
            continue
        _, _, dep_dt, arr_dt = window

        voyage_rows = [r for dt, _, r in dated if dep_dt <= dt <= arr_dt]
        if not voyage_rows:
            excluded_voyages[v_no] = "No steaming records found within this voyage's departure-to-arrival window."
            continue
        valid_rows.extend(voyage_rows)

    # Per-day CP remarks (client request 2026-09) — same lookup vessel_routes.py's
    # /voyage/series already does for the PDF report, so the live table can use
    # whichever CP instruction actually applied that day (Eco/Full override,
    # revised term mid-voyage) instead of always the single standing warranty.
    # MariApps-only — WNI rows simply have no raw_mariapps_id and get nothing.
    mariapps_ids = {r["raw_mariapps_id"] for r in valid_rows if r.get("raw_mariapps_id")}
    extras_by_id = {}
    if mariapps_ids:
        extra_rows = db.execute(text(
            'SELECT raw_log_id, cpx_remarks FROM expanded_mariapps_data WHERE raw_log_id = ANY(:ids)'
        ), {"ids": list(mariapps_ids)}).fetchall()
        extras_by_id = {r[0]: r[1] for r in extra_rows}

    for r in valid_rows:
        r["cp_instruction"] = None
        remarks = extras_by_id.get(r.get("raw_mariapps_id")) if r.get("raw_mariapps_id") else None
        if remarks:
            parsed = parse_cp_remarks(remarks)
            instr = pick_instruction_for_condition(parsed, r.get("Loading_Cond"))
            if instr:
                r["cp_instruction"] = {
                    "speed_kn": instr["speed_kn"],
                    "total_mt_day": instr["total_mt_day"],
                    "go_mt_day": instr["go_mt_day"],
                }

    return valid_rows, excluded_voyages


# Same FO/DO-GO grade classification convention as import_cp_description.py / cp_compliance_v2.
def _classify_fuel_grade(grade):
    if not grade:
        return None
    g = grade.upper()
    if "VLSFO" in g or "HFO" in g or "LFO" in g or "HSFO" in g:
        return "FO"
    if "MGO" in g or "MDO" in g or "LDO" in g or "HFHSD" in g or "DMA" in g or "DMB" in g:
        return "DOGO"
    return None


def _cp_by_cond_from_cp_description(db, imo):
    """
    Build {"Laden": [warranty_dict, ...], "Ballast": [...]} from the CP Description
    tables (cp_sea_warranty), replacing vessel_cp_config as the data source for the
    Charter-Party Performance table. Each loading condition can have multiple
    candidate records (Eco + Full) — compute_cp_voyage_table picks the nearest
    match by observed speed per segment, so a Full-speed voyage is compared
    against the Full warranty instead of a single collapsed figure.
    """
    header = (
        db.query(CPVesselDescription)
        .filter(CPVesselDescription.vessel_imo == imo, CPVesselDescription.doc_status == "Active")
        .order_by(CPVesselDescription.version_no.desc())
        .first()
    )
    if not header:
        return {}

    sea_rows = db.query(CPSeaWarranty).filter(CPSeaWarranty.cp_id == header.id).all()
    cp_by_cond = {}
    for s in sea_rows:
        me_cls = _classify_fuel_grade(s.me_fuel_grade)
        # Bug found 2026-09 (AM KIRTI's DO/GO warranty always 0.00, flagging
        # a "Loss" on every single voyage regardless of scale): when the
        # source CP Description Excel's "Fuel Grade" cell wasn't split with a
        # "/" (import_cp_description.py), ae_fuel_grade was left NULL. This
        # used to fall back to the ME's own grade (me_cls) — but AE virtually
        # always burns MGO/MDO (DOGO) on this fleet, never the ME's VLSFO/HFO,
        # so that fallback silently zeroed the DOGO warranty by miscounting
        # AE's real consumption as FO. Default a missing AE grade to DOGO
        # instead, matching actual fleet fuel-use patterns.
        ae_cls = _classify_fuel_grade(s.ae_fuel_grade) if s.ae_fuel_grade else "DOGO"
        me, ae, boiler = s.me_cons_mt_day or 0, s.ae_cons_mt_day or 0, s.boiler_cons_sea_mt_day or 0
        fo   = (me if me_cls == "FO"   else 0) + (ae if ae_cls == "FO"   else 0) + boiler
        dogo = (me if me_cls == "DOGO" else 0) + (ae if ae_cls == "DOGO" else 0)
        cp_by_cond.setdefault(s.loading_condition, []).append({
            "warranted_speed_kn":  s.warranted_speed_kn,
            "warranted_fo_mtpd":   round(fo, 2),
            "warranted_dogo_mtpd": round(dogo, 2),
            "speed_tol_kn":        s.speed_tolerance_kn,
            "cons_tol_pct":        s.cons_tolerance_pct,
        })
    return cp_by_cond


@router.get("/{imo}/performance")
def cp_performance(
    imo: str,
    voyages: str = Query(None, description="Comma-separated Voyage_No values; omit for all"),
    source: str = Query(None, description="'wni' or 'mari_apps'; omit for both"),
    loading_cond: str = Query(None, description="'Laden' or 'Ballast'; omit for all"),
    db: Session = Depends(get_db),
):
    """WNI-style per-segment CP performance for the selected voyage(s)."""
    cp_by_cond = _cp_by_cond_from_cp_description(db, imo)

    vlist = [v.strip() for v in voyages.split(",")] if voyages else None
    vlist = [v for v in vlist if v] if vlist else None
    sources = [source] if source in _SOURCE_SQL else list(_SOURCE_SQL.keys())

    rows = []
    excluded_voyages = {}
    try:
        for s in sources:
            src_rows, src_excluded = _rows_for_source(db, imo, s, vlist, loading_cond)
            rows.extend(src_rows)
            excluded_voyages.update(src_excluded)  # later source's reason wins on overlap; rare, both descriptive
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CP query failed: {e}")

    results = compute_cp_voyage_table(rows, cp_by_cond)

    # Client request 2026-09: a specifically-requested voyage that produced
    # zero segments (no EOSP yet, or an inverted departure/arrival window —
    # see _rows_for_source) used to just silently vanish from the table
    # (looked like a bug). Surface it explicitly instead — only for voyages
    # the caller actually asked for (vlist), never injected into an
    # unfiltered "all voyages" request.
    if vlist:
        seen = {r["voyage_no"] for r in results}
        for v_no in vlist:
            if v_no in seen:
                continue
            reason = excluded_voyages.get(v_no, "Not computable for this voyage.")
            results.append(not_computable_result(v_no, reason, source=source))
    return {
        "vessel_imo":    imo,
        "source":        source,
        "voyages":       voyages,
        "cp_configured": len(cp_by_cond) > 0,
        "results":       results,
    }
