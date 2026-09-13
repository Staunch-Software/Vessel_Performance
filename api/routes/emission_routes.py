"""
Emission tab — AER & CII API.
ESG / SCC / ESI reports are NOT implemented here — their definition/format was
never specified by the client; the frontend renders them as "pending" placeholders.
See backend/emission/cii_calculator.py for the full IMO-resolution citations.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from pydantic import BaseModel

from backend.database import SessionLocal
from backend.models import VesselParticulars, Vessel
from backend.emission.cii_calculator import compute_cii, CF_TABLE, DEFAULT_SHIP_TYPE
from backend.emission.imo_dcs_calculator import validate_innovative_tech, group_into_legs
from backend.emission.eu_mrv_calculator import classify_eu_voyage, CATEGORY_LABELS, EU_VOYAGE_CATEGORIES, ch4_n2o_co2e_t
from backend.emission.eu_ets_calculator import (
    phase_in_pct, ets_scope_pct, ETS_CATEGORY_LABELS, EUA_PRICE_USD_PER_EUA,
    NON_SURRENDER_PENALTY_EUR_PER_T, ghg_scope_covers_ch4_n2o, ghg_scope_label,
)
from backend.emission.fueleu_calculator import ghg_limit, leg_wtw, estimated_penalty

log = logging.getLogger(__name__)
router = APIRouter(prefix="/emission", tags=["emission"])

# Same 8 consumer prefixes / 10 fuel grades on both noon_report_data (WNI) and
# mariapps_reports_data (MariApps) — identical schema, so one query template
# works for either source by swapping the table/join.
_CONSUMERS = ["me", "ae", "bl", "inc", "eg", "combl", "aeb", "blfo"]
_GRADES = ["hfo", "lfo", "mdo", "lpg_propane", "lpg_butane", "lng", "methanol", "ethanol", "ammonia", "bio_fuel"]

_SOURCE_JOIN = {
    "wni": ("JOIN noon_report_data n ON n.raw_report_id = a.raw_report_id", "wni"),
    "mari_apps": ("JOIN mariapps_reports_data n ON n.raw_report_id = a.raw_mariapps_id", "mari_apps"),
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _numexpr(col):
    # Same VARCHAR-safe cast convention as cp_routes.py — non-numeric/blank -> 0.
    return f"(CASE WHEN {col} ~ '^[-+]?[0-9]+(\\.[0-9]+)?$' THEN {col}::double precision ELSE 0 END)"


def _grade_sum_expr(grade):
    parts = [_numexpr(f'n."{c}_{grade}"') for c in _CONSUMERS]
    return "(" + "+".join(parts) + f") AS {grade}"


_GRADE_EXPRS = ",\n               ".join(_grade_sum_expr(g) for g in _GRADES)


def _fuel_and_distance(db, imo, source, year):
    join, src = _SOURCE_JOIN[source]
    sql = f"""
        SELECT COALESCE(SUM(a."Distance_nm"), 0) AS total_distance,
               {", ".join(f'COALESCE(SUM({g}), 0) AS total_{g}' for g in _GRADES)}
        FROM (
            SELECT a."Distance_nm", {_GRADE_EXPRS}
            FROM analysis_data a
            {join}
            WHERE a.vessel_imo = :imo AND a.source_id = :src
              AND EXTRACT(YEAR FROM a."Date") = :year
        ) a
    """
    row = db.execute(text(sql), {"imo": imo, "src": src, "year": year}).mappings().first()
    if not row:
        return 0.0, {g: 0.0 for g in _GRADES}
    distance = float(row["total_distance"] or 0)
    fuel = {g: float(row[f"total_{g}"] or 0) for g in _GRADES}
    return distance, fuel


@router.get("/{imo}/years")
def list_available_years(imo: str, db: Session = Depends(get_db)):
    rows = db.execute(
        text('SELECT DISTINCT EXTRACT(YEAR FROM "Date")::int AS y FROM analysis_data WHERE vessel_imo = :imo ORDER BY 1'),
        {"imo": imo},
    ).fetchall()
    return [r[0] for r in rows if r[0] is not None]


@router.get("/{imo}/cii")
def get_cii(
    imo: str,
    year: int = Query(..., description="Calendar year"),
    source: Optional[str] = Query(None, description="'wni' or 'mari_apps'; omit combines both (may double-count overlapping days)"),
    db: Session = Depends(get_db),
):
    vessel = db.query(VesselParticulars).filter(VesselParticulars.vessel_imo == imo).first()
    dwt = vessel.deadweight if vessel else None
    if not dwt:
        raise HTTPException(
            status_code=404,
            detail=f"No DWT (deadweight) configured for IMO {imo} — CII cannot be computed without it. Set it on the Design Data tab.",
        )

    sources = [source] if source in _SOURCE_JOIN else list(_SOURCE_JOIN.keys())
    total_distance = 0.0
    fuel_totals = {g: 0.0 for g in _GRADES}
    for src in sources:
        d, f = _fuel_and_distance(db, imo, src, year)
        total_distance += d
        for g in _GRADES:
            fuel_totals[g] += f[g]

    result = compute_cii(fuel_totals, total_distance, dwt, year, DEFAULT_SHIP_TYPE)
    if result is None:
        return {
            "vessel_imo": imo, "year": year, "source": source, "dwt": dwt,
            "note": "No distance data for this vessel/year/source — CII not computable.",
        }

    result["vessel_imo"] = imo
    result["source"] = source
    return result


# ============================================================
# IMO DCS ENHANCED — MARPOL Annex VI Reg. 27 + MEPC.385(81)
# ============================================================
# Sections A/C/D of the client's IMO_DCS workbook sheet, plus Section E (CII,
# already computed above via compute_cii — reused, not duplicated). Sourced
# from expanded_mariapps_data / expanded_wni_data (the Emission Log direct
# columns built earlier this session — fuel by grade/consumer, Op. Status,
# cargo/distance/loading condition), NOT the analysis_data path the plain
# CII endpoint above uses — that table doesn't carry per-consumer or Op.
# Status breakdowns at all.
_EXPANDED_TABLE = {"wni": "expanded_wni_data", "mari_apps": "expanded_mariapps_data"}
_EXPANDED_DATE_COL = {"wni": "date", "mari_apps": "log_date"}


def _num(col):
    # Same VARCHAR-safe cast convention as cp_routes.py / this file's _numexpr —
    # the expanded tables store every value as text. Rounded to 2dp at the SQL
    # level (not left to each call site to remember) so every value built from
    # this — distance, duration, speed, drafts, cargo, per-consumer/grade fuel —
    # comes out clean instead of carrying raw source-string decimal noise.
    return (
        f'(CASE WHEN "{col}" ~ \'^[-+]?[0-9]+(\\.[0-9]+)?$\' '
        f'THEN ROUND("{col}"::numeric, 2)::double precision ELSE 0 END)'
    )


def _imo_dcs_aggregate(db, imo, source, year):
    table = _EXPANDED_TABLE[source]
    date_col = _EXPANDED_DATE_COL[source]
    sql = f"""
        SELECT
            COALESCE(SUM({_num('emissionx_grand_total_mt')}), 0)                                   AS total_fuel,
            COALESCE(SUM({_num('Vessel_DOG_dCnt_operational_LF')}), 0)                              AS total_distance,
            COALESCE(SUM({_num('VoyageMeta_log_durationh_operational_LF')})
                     FILTER (WHERE emissionx_op_status = 'UW'), 0)                                   AS hours_uw,
            COALESCE(SUM({_num('emissionx_total_hfo_mt')}), 0)                                      AS hfo,
            COALESCE(SUM({_num('emissionx_total_lfo_mt')}), 0)                                      AS lfo,
            COALESCE(SUM({_num('emissionx_total_mdo_mt')}), 0)                                      AS mdo,
            COALESCE(SUM({_num('emissionx_total_biofuel_mt')}), 0)                                  AS bio_fuel,
            COALESCE(SUM({_num('ME_FO_mFOCME_dCnt_operational_LF')}), 0)                            AS me_total,
            COALESCE(SUM({_num('AE_FO_mFOCAE_dCnt_operational_LF')}), 0)                            AS ae_total,
            COALESCE(SUM({_num('AuxBoiler_mFOCBL_dCnt_operational_LF')}), 0)                        AS boiler_total,
            COALESCE(SUM({_num('emissionx_ig_other_mt')}), 0)                                       AS ig_other_total,
            COALESCE(SUM({_num('ME_FO_mFOCME_dCnt_operational_LF')})
                     FILTER (WHERE emissionx_op_status = 'NUW'), 0)                                  AS me_nuw,
            COALESCE(SUM({_num('AE_FO_mFOCAE_dCnt_operational_LF')})
                     FILTER (WHERE emissionx_op_status = 'NUW'), 0)                                  AS ae_nuw,
            COALESCE(SUM({_num('AuxBoiler_mFOCBL_dCnt_operational_LF')})
                     FILTER (WHERE emissionx_op_status = 'NUW'), 0)                                  AS boiler_nuw,
            COALESCE(SUM({_num('emissionx_ig_other_mt')})
                     FILTER (WHERE emissionx_op_status = 'NUW'), 0)                                  AS ig_other_nuw,
            COALESCE(SUM({_num('Vessel_Cargo_onboard_operational_LF')} * {_num('Vessel_DOG_dCnt_operational_LF')}), 0) AS transport_work,
            COALESCE(SUM({_num('Vessel_DOG_dCnt_operational_LF')})
                     FILTER (WHERE loading_condition ILIKE 'Laden'), 0)                              AS laden_distance
        FROM {table}
        WHERE vessel_imo = :imo AND EXTRACT(YEAR FROM {date_col}) = :year
    """
    row = db.execute(text(sql), {"imo": imo, "year": year}).mappings().first()
    return dict(row) if row else None


@router.get("/{imo}/imo-dcs")
def get_imo_dcs(
    imo: str,
    year: int = Query(..., description="Calendar year"),
    source: Optional[str] = Query(None, description="'wni' or 'mari_apps'; omit combines both"),
    db: Session = Depends(get_db),
):
    vessel = db.query(Vessel).filter(Vessel.imo_number == imo).first()
    particulars = db.query(VesselParticulars).filter(VesselParticulars.vessel_imo == imo).first()
    dwt = particulars.deadweight if particulars else None

    sources = [source] if source in _EXPANDED_TABLE else list(_EXPANDED_TABLE.keys())
    totals = {
        "total_fuel": 0.0, "total_distance": 0.0, "hours_uw": 0.0,
        "hfo": 0.0, "lfo": 0.0, "mdo": 0.0, "bio_fuel": 0.0,
        "me_total": 0.0, "ae_total": 0.0, "boiler_total": 0.0, "ig_other_total": 0.0,
        "me_nuw": 0.0, "ae_nuw": 0.0, "boiler_nuw": 0.0, "ig_other_nuw": 0.0,
        "transport_work": 0.0, "laden_distance": 0.0,
    }
    any_data = False
    for src in sources:
        agg = _imo_dcs_aggregate(db, imo, src, year)
        if not agg:
            continue
        any_data = True
        for k in totals:
            totals[k] += float(agg.get(k) or 0)

    if not any_data or totals["total_distance"] == 0:
        return {
            "vessel_imo": imo, "year": year, "source": source,
            "note": "No distance data for this vessel/year/source — IMO DCS not computable.",
        }

    # Section C — fuel by type + CO2 (Cf x tonnes, MEPC.364(79) via cii_calculator's CF_TABLE).
    # Biofuel CO2 uses Cf=2.834 here (DCS reports actual TtW CO2 for all fuels, unlike CII
    # which zeroes biofuel's Cf) — MEPC.1/Circ.905-Rev.1 Section 10 of RefConstants.
    fuel_by_type = [
        {"fuel_type": "HFO", "total_mt": round(totals["hfo"], 3), "co2_mt": round(totals["hfo"] * CF_TABLE["hfo"], 3)},
        {"fuel_type": "LFO", "total_mt": round(totals["lfo"], 3), "co2_mt": round(totals["lfo"] * CF_TABLE["lfo"], 3)},
        {"fuel_type": "MDO/MGO", "total_mt": round(totals["mdo"], 3), "co2_mt": round(totals["mdo"] * CF_TABLE["mdo"], 3)},
        {"fuel_type": "Biofuel (FAME)", "total_mt": round(totals["bio_fuel"], 3), "co2_mt": round(totals["bio_fuel"] * 2.834, 3)},
    ]
    total_co2 = round(sum(f["co2_mt"] for f in fuel_by_type), 3)

    # Section E — CII, reusing the exact same calculator as the plain /cii endpoint.
    cii_result = None
    if dwt:
        fuel_for_cii = {"hfo": totals["hfo"], "lfo": totals["lfo"], "mdo": totals["mdo"], "bio_fuel": totals["bio_fuel"]}
        cii_result = compute_cii(fuel_for_cii, totals["total_distance"], dwt, year, DEFAULT_SHIP_TYPE)

    return {
        "vessel_imo": imo, "year": year, "source": source,
        # Section A — Ship ID
        "ship_id": {
            "imo_number": imo,
            "ship_name": vessel.vessel_name if vessel else None,
            "flag_state": particulars.flag if particulars else None,
            "ship_type": particulars.vessel_type if particulars else None,
            "gt": particulars.gross_tonnage if particulars else None,
            "dwt": dwt,
        },
        # Section B — standard DCS items
        "standard_dcs": {
            "total_fuel_consumed_mt": round(totals["total_fuel"], 3),
            "total_distance_nm": round(totals["total_distance"], 1),
            "total_hours_underway": round(totals["hours_uw"], 1),
        },
        # Section C
        "fuel_by_type": fuel_by_type,
        "total_co2_mt": total_co2,
        # Section D — Enhanced DCS (MEPC.385(81))
        "enhanced_dcs": {
            "item1_fuel_by_consumer_mt": {
                "main_engine": round(totals["me_total"], 3),
                "aux_engines": round(totals["ae_total"], 3),
                "boilers": round(totals["boiler_total"], 3),
                "ig_other": round(totals["ig_other_total"], 3),
            },
            "item2_fuel_not_underway_mt": {
                "main_engine": round(totals["me_nuw"], 3),
                "aux_engines": round(totals["ae_nuw"], 3),
                "boilers": round(totals["boiler_nuw"], 3),
                "ig_other": round(totals["ig_other_nuw"], 3),
            },
            "item3_ops_supplied_kwh": None,
            "item3_note": "Not available — Onshore Power Supply is not currently captured "
                          "anywhere in the ingested schema (mapped in the source contract but "
                          "the column was never added to any live table). Report 0 if no OPS "
                          "used, per MEPC.385(81) para 2.3, until this is wired up.",
            "item4_transport_work_mt_nm": round(totals["transport_work"], 1),
            "item5_laden_distance_nm": round(totals["laden_distance"], 1),
            "item6_innovative_tech_category": particulars.innovative_tech_category if particulars else None,
        },
        "cii": cii_result,
    }


# WNI carries its voyage identity as the plain `voyage_no` column (identity,
# never renamed — see expander.py IDENTITY_WNI). MariApps has no equivalent
# identity column in expanded_mariapps_data; the nearest thing is the
# Emission-Log-only `emissionx_voyage_no` data column built earlier this
# session, which is NULL wherever that field wasn't captured on the source
# log — voyages with a null value are grouped together under "—" rather than
# silently dropped. Per CLAUDE.md convention, WNI and MariApps voyage numbers
# are NEVER blended (incompatible numbering schemes), so voyage grouping is
# always done per-source, one call per source, never combined server-side.
_VOYAGE_COL = {"wni": "voyage_no", "mari_apps": "emissionx_voyage_no"}


def _imo_dcs_monthly(db, imo, source, year):
    table = _EXPANDED_TABLE[source]
    date_col = _EXPANDED_DATE_COL[source]
    sql = f"""
        SELECT EXTRACT(MONTH FROM {date_col})::int AS month,
               COALESCE(SUM({_num('Vessel_DOG_dCnt_operational_LF')}), 0)  AS total_distance,
               COALESCE(SUM({_num('emissionx_total_hfo_mt')}), 0)          AS hfo,
               COALESCE(SUM({_num('emissionx_total_lfo_mt')}), 0)          AS lfo,
               COALESCE(SUM({_num('emissionx_total_mdo_mt')}), 0)          AS mdo,
               COALESCE(SUM({_num('emissionx_total_biofuel_mt')}), 0)      AS bio_fuel
        FROM {table}
        WHERE vessel_imo = :imo AND EXTRACT(YEAR FROM {date_col}) = :year
        GROUP BY 1
        ORDER BY 1
    """
    return db.execute(text(sql), {"imo": imo, "year": year}).mappings().all()


def _co2_breakdown(hfo, lfo, mdo, bio_fuel):
    co2 = hfo * CF_TABLE["hfo"] + lfo * CF_TABLE["lfo"] + mdo * CF_TABLE["mdo"] + bio_fuel * 2.834
    return round(co2, 3)


@router.get("/{imo}/imo-dcs/monthly")
def get_imo_dcs_monthly(
    imo: str,
    year: int = Query(..., description="Calendar year"),
    source: str = Query(..., description="'wni' or 'mari_apps' — required, never blended across sources"),
    db: Session = Depends(get_db),
):
    if source not in _EXPANDED_TABLE:
        raise HTTPException(status_code=400, detail="source must be 'wni' or 'mari_apps'.")
    rows = _imo_dcs_monthly(db, imo, source, year)
    out = []
    for r in rows:
        hfo, lfo, mdo, bio = float(r["hfo"] or 0), float(r["lfo"] or 0), float(r["mdo"] or 0), float(r["bio_fuel"] or 0)
        out.append({
            "month": r["month"],
            "total_distance_nm": round(float(r["total_distance"] or 0), 1),
            "total_fuel_mt": round(hfo + lfo + mdo + bio, 3),
            "total_co2_mt": _co2_breakdown(hfo, lfo, mdo, bio),
        })
    return {"vessel_imo": imo, "year": year, "source": source, "months": out}


# ============================================================
# LEG TAB — per-leg breakdown, matching the WNI "Leg" sheet
# ============================================================
# A leg = a contiguous run sharing (voyage_no, loading_condition) — see
# group_into_legs() docstring. Only 4 of the WNI sheet's 8 fuel grades are
# ever used by this fleet — LNG/LPG-Propane/LPG-Butane/Methanol are always 0
# for every vessel (confirmed, none of these bulk carriers burn anything but
# HFO/LFO/MDO/Biofuel) — so they're dropped entirely rather than computed and
# hidden. Re-add if a vessel in this fleet ever actually bunkers one of them.
_LEG_GRADES = ["hfo", "lfo", "mdo", "bio_fuel"]


def _imo_dcs_leg_source_rows(db, imo, source, year):
    e_table = _EXPANDED_TABLE[source]
    date_col = _EXPANDED_DATE_COL[source]
    voyage_col = _VOYAGE_COL[source]
    sql = f"""
        SELECT e."{date_col}" AS dt,
               COALESCE(NULLIF(e."{voyage_col}", ''), '—') AS voyage_no,
               COALESCE(NULLIF(e."loading_condition", ''), 'Unknown') AS loading_condition,
               e."VoyageMeta_departure_port_last_leg_operational_LF" AS from_port,
               e."VoyageMeta_to_port_operational_LF" AS to_port,
               e."emissionx_op_status" AS op_status,
               {_num('Vessel_DOG_dCnt_operational_LF')} AS distance_nm,
               {_num('VoyageMeta_log_durationh_operational_LF')} AS duration_h,
               {_num('Vessel_Cargo_onboard_operational_LF')} AS cargo_mt,
               {_num('emissionx_total_hfo_mt')} AS hfo,
               {_num('emissionx_total_lfo_mt')} AS lfo,
               {_num('emissionx_total_mdo_mt')} AS mdo,
               {_num('emissionx_total_biofuel_mt')} AS bio_fuel
        FROM {e_table} e
        WHERE e."vessel_imo" = :imo AND EXTRACT(YEAR FROM e."{date_col}") = :year
        ORDER BY e."{date_col}"
    """
    return db.execute(text(sql), {"imo": imo, "year": year}).mappings().all()


@router.get("/{imo}/imo-dcs/legs")
def get_imo_dcs_legs(
    imo: str,
    year: int = Query(..., description="Calendar year"),
    source: str = Query(..., description="'wni' or 'mari_apps' — required, never blended across sources"),
    db: Session = Depends(get_db),
):
    if source not in _EXPANDED_TABLE:
        raise HTTPException(status_code=400, detail="source must be 'wni' or 'mari_apps'.")
    particulars = db.query(VesselParticulars).filter(VesselParticulars.vessel_imo == imo).first()
    dwt = particulars.deadweight if particulars else None

    raw_rows = _imo_dcs_leg_source_rows(db, imo, source, year)
    if not raw_rows:
        return {"vessel_imo": imo, "year": year, "source": source, "legs": [],
                "note": "No leg data for this vessel/year/source."}

    rows = [{
        "date": r["dt"], "voyage_no": r["voyage_no"], "loading_condition": r["loading_condition"],
        "op_status": r["op_status"], "from_port": r["from_port"], "to_port": r["to_port"],
        "distance_nm": float(r["distance_nm"] or 0), "duration_h": float(r["duration_h"] or 0),
        "cargo_mt": float(r["cargo_mt"] or 0),
        "fuel_by_grade": {g: float(r[g] or 0) for g in _LEG_GRADES},
    } for r in raw_rows]

    legs = []
    for grp in group_into_legs(rows):
        lrows = grp["rows"]
        voyage_no, loading_condition = grp["key"]
        first_row, last_row = lrows[0], lrows[-1]
        distance = sum(r["distance_nm"] for r in lrows)
        time_at_sea = sum(r["duration_h"] for r in lrows if r["op_status"] == "UW")
        cargo_vals = [r["cargo_mt"] for r in lrows if r["cargo_mt"]]
        cargo = cargo_vals[0] if cargo_vals else None
        # Transport work only meaningful for a laden leg (cargo actually onboard).
        transport_work = round(sum(r["cargo_mt"] * r["distance_nm"] for r in lrows), 1) \
            if loading_condition.lower() == "laden" else None

        fuel_total = {g: sum(r["fuel_by_grade"][g] for r in lrows) for g in _LEG_GRADES}
        fuel_at_sea = {g: sum(r["fuel_by_grade"][g] for r in lrows if r["op_status"] == "UW") for g in _LEG_GRADES}
        fuel_in_port = {g: sum(r["fuel_by_grade"][g] for r in lrows if r["op_status"] == "NUW") for g in _LEG_GRADES}

        def _bucket(fuel):
            return {
                "consumption_mt": round(sum(fuel.values()), 3),
                **{g: round(v, 3) for g, v in fuel.items()},
                "co2_mt": round(sum(fuel[g] * CF_TABLE.get(g, 0) for g in fuel), 3),
            }

        # Arrived only if the leg's last row is actually in-port (NUW) — an
        # ongoing/incomplete leg (still steaming as of the latest data) has no
        # arrival yet, matching the WNI sheet leaving Arrival Port/Berth blank
        # for the current in-progress leg.
        arrived = last_row["op_status"] == "NUW"

        cii_result = compute_cii(fuel_total, distance, dwt, year, DEFAULT_SHIP_TYPE) if dwt else None

        legs.append({
            "voyage_no": voyage_no,
            "loading_condition": loading_condition,
            "from_port": first_row["from_port"],
            "departure_time": first_row["date"].isoformat() if first_row["date"] else None,
            "to_port": last_row["to_port"] if arrived else None,
            "arrival_time": last_row["date"].isoformat() if arrived and last_row["date"] else None,
            "next_departure_time": None,  # filled below via look-ahead
            "distance_nm": round(distance, 1),
            "time_at_sea_h": round(time_at_sea, 1),
            "cargo_weight_mt": round(cargo, 1) if cargo else None,
            "transport_work_mt_nm": transport_work,
            "consumption_total_mt": round(sum(fuel_total.values()), 3),
            "co2_total_mt": round(sum(fuel_total[g] * CF_TABLE.get(g, 0) for g in fuel_total), 3),
            "attained_cii": cii_result["attained_cii"] if cii_result else None,
            "cii_rating": cii_result["rating"] if cii_result else None,
            "at_sea": _bucket(fuel_at_sea),
            "in_port": _bucket(fuel_in_port),
        })

    for i in range(len(legs) - 1):
        legs[i]["next_departure_time"] = legs[i + 1]["departure_time"]

    return {"vessel_imo": imo, "year": year, "source": source, "legs": legs}


# ============================================================
# EVENT TAB — plain per-report passthrough of the existing Emission Log
# columns (same table Logbook+ already renders under the Emission category) —
# no new calculation, just exposed here filtered to one vessel/year/source.
# ============================================================
_LOG_TYPE_COL = {"wni": "event_type", "mari_apps": "log_type"}
_LOG_NUMBER_EXPR = {"wni": "NULL", "mari_apps": 'e."log_number"'}
# BDN Ref (bunker delivery note) is MariApps-only — matched against real
# bunker reports (mariapps_bunker_reports); no equivalent source for WNI at
# all, so the column was never added to expanded_wni_data (physically absent,
# not just unpopulated).
_BDN_REF_EXPR = {"wni": "NULL", "mari_apps": 'e."emissionx_bdn_ref"'}


@router.get("/{imo}/imo-dcs/events")
def get_imo_dcs_events(
    imo: str,
    year: int = Query(..., description="Calendar year"),
    source: str = Query(..., description="'wni' or 'mari_apps' — required, never blended across sources"),
    db: Session = Depends(get_db),
):
    if source not in _EXPANDED_TABLE:
        raise HTTPException(status_code=400, detail="source must be 'wni' or 'mari_apps'.")
    e_table = _EXPANDED_TABLE[source]
    date_col = _EXPANDED_DATE_COL[source]
    log_type_col = _LOG_TYPE_COL[source]
    log_number_expr = _LOG_NUMBER_EXPR[source]
    sql = f"""
        SELECT e."vessel_imo" AS vessel_imo,
               e."{log_type_col}" AS log_type,
               e."{date_col}" AS log_date,
               {log_number_expr} AS log_number,
               e."{_VOYAGE_COL[source]}" AS voyage_no,
               e."VoyageMeta_departure_port_last_leg_operational_LF" AS from_port,
               e."emissionx_from_country" AS from_country,
               e."emissionx_from_eu_port" AS from_eu_port,
               e."VoyageMeta_to_port_operational_LF" AS to_port,
               e."emissionx_to_country" AS to_country,
               e."emissionx_to_eu_port" AS to_eu_port,
               e."loading_condition" AS loading_condition,
               e."VoyageMeta_latitude_operational_LF" AS latitude,
               e."VoyageMeta_longitude_operational_LF" AS longitude,
               e."emissionx_op_status" AS op_status,
               {_num('Vessel_DOG_dCnt_operational_LF')} AS distance_nm,
               {_num('VoyageMeta_log_durationh_operational_LF')} AS duration_h,
               {_num('Vessel_SOG_avg_operational_LF')} AS speed_kn,
               {_num('Vessel_Tf_avg_operational_LF')} AS draft_fwd,
               {_num('Vessel_Ta_avg_operational_LF')} AS draft_aft,
               {_num('Vessel_Cargo_onboard_operational_LF')} AS cargo_mt,
               {_num('emissionx_me_hfo_mt')} AS me_hfo, {_num('emissionx_me_lfo_mt')} AS me_lfo,
               {_num('emissionx_me_mdo_mt')} AS me_mdo, {_num('emissionx_me_biofuel_mt')} AS me_bio,
               {_num('ME_FO_mFOCME_dCnt_operational_LF')} AS me_total,
               {_num('emissionx_ae_hfo_mt')} AS ae_hfo, {_num('emissionx_ae_lfo_mt')} AS ae_lfo,
               {_num('emissionx_ae_mdo_mt')} AS ae_mdo, {_num('emissionx_ae_biofuel_mt')} AS ae_bio,
               {_num('AE_FO_mFOCAE_dCnt_operational_LF')} AS ae_total,
               {_num('emissionx_bl_hfo_mt')} AS bl_hfo, {_num('emissionx_bl_lfo_mt')} AS bl_lfo,
               {_num('emissionx_bl_mdo_mt')} AS bl_mdo, {_num('emissionx_bl_biofuel_mt')} AS bl_bio,
               {_num('AuxBoiler_mFOCBL_dCnt_operational_LF')} AS boiler_total,
               {_num('emissionx_ig_other_mt')} AS ig_other,
               {_num('emissionx_grand_total_mt')} AS grand_total,
               {_num('emissionx_total_hfo_mt')} AS total_hfo, {_num('emissionx_total_lfo_mt')} AS total_lfo,
               {_num('emissionx_total_mdo_mt')} AS total_mdo, {_num('emissionx_total_biofuel_mt')} AS total_bio,
               {_BDN_REF_EXPR[source]} AS bdn_ref
        FROM {e_table} e
        WHERE e."vessel_imo" = :imo AND EXTRACT(YEAR FROM e."{date_col}") = :year
        ORDER BY e."{date_col}" DESC
        LIMIT 2000
    """
    rows = db.execute(text(sql), {"imo": imo, "year": year}).mappings().all()
    events = [{**r, "log_date": r["log_date"].isoformat() if r["log_date"] else None} for r in rows]
    return {"vessel_imo": imo, "year": year, "source": source, "events": events,
            "truncated": len(events) == 2000}


class InnovativeTechPayload(BaseModel):
    category: Optional[str] = None  # 'A' | 'B-1' | 'B-2' | 'C-1' | 'C-2' | None


@router.patch("/{imo}/innovative-tech")
def set_innovative_tech(imo: str, payload: InnovativeTechPayload, db: Session = Depends(get_db)):
    """Item 6 is a manual per-vessel classification (MEPC.1/Circ.896) — not
    derivable from operational data, so this is a plain field set, not a
    calculation."""
    category = validate_innovative_tech(payload.category)
    particulars = db.query(VesselParticulars).filter(VesselParticulars.vessel_imo == imo).first()
    if not particulars:
        raise HTTPException(status_code=404, detail=f"No vessel_particulars row for IMO {imo}.")
    particulars.innovative_tech_category = category
    db.commit()
    return {"vessel_imo": imo, "innovative_tech_category": category}


# ============================================================
# EU MRV — Reg. (EU) 2015/757. Reuses the exact same Emission Log columns and
# leg-grouping (group_into_legs) as IMO DCS — a leg here is one row's worth of
# EU-jurisdiction classification (see eu_mrv_calculator.py for the WNI
# "from port" gap this depends on). The monthly fuel/CO2 trend chart is
# shared verbatim with IMO DCS (GET /imo-dcs/monthly) — EU scope doesn't
# change that number, so there's no separate endpoint for it.
# ============================================================

def _eu_mrv_leg_source_rows(db, imo, source, year):
    e_table = _EXPANDED_TABLE[source]
    date_col = _EXPANDED_DATE_COL[source]
    voyage_col = _VOYAGE_COL[source]
    sql = f"""
        SELECT e."{date_col}" AS dt,
               COALESCE(NULLIF(e."{voyage_col}", ''), '—') AS voyage_no,
               COALESCE(NULLIF(e."loading_condition", ''), 'Unknown') AS loading_condition,
               e."VoyageMeta_departure_port_last_leg_operational_LF" AS from_port,
               e."VoyageMeta_to_port_operational_LF" AS to_port,
               e."emissionx_from_eu_port" AS from_eu,
               e."emissionx_to_eu_port" AS to_eu,
               e."emissionx_op_status" AS op_status,
               {_num('Vessel_DOG_dCnt_operational_LF')} AS distance_nm,
               {_num('VoyageMeta_log_durationh_operational_LF')} AS duration_h,
               {_num('emissionx_total_hfo_mt')} AS hfo,
               {_num('emissionx_total_lfo_mt')} AS lfo,
               {_num('emissionx_total_mdo_mt')} AS mdo,
               {_num('emissionx_total_biofuel_mt')} AS bio_fuel
        FROM {e_table} e
        WHERE e."vessel_imo" = :imo AND EXTRACT(YEAR FROM e."{date_col}") = :year
        ORDER BY e."{date_col}"
    """
    return db.execute(text(sql), {"imo": imo, "year": year}).mappings().all()


def _eu_mrv_legs_computed(db, imo, source, year):
    """Shared by both EU MRV endpoints below — one row per leg (same
    (voyage_no, loading_condition) grouping as IMO DCS), each carrying its EU
    voyage-category classification, CO2/distance/fuel totals, and the portion
    of that CO2 emitted at berth in an EU port (Art. 10(k) — independent of
    voyage category, computed from NUW rows where the current port is in the
    EU)."""
    raw_rows = _eu_mrv_leg_source_rows(db, imo, source, year)
    if not raw_rows:
        return None
    rows = [{
        "date": r["dt"], "voyage_no": r["voyage_no"], "loading_condition": r["loading_condition"],
        "op_status": r["op_status"], "from_port": r["from_port"], "to_port": r["to_port"],
        "from_eu": r["from_eu"], "to_eu": r["to_eu"],
        "distance_nm": float(r["distance_nm"] or 0), "duration_h": float(r["duration_h"] or 0),
        "fuel_by_grade": {g: float(r[g] or 0) for g in _LEG_GRADES},
    } for r in raw_rows]

    legs = []
    for grp in group_into_legs(rows):
        lrows = grp["rows"]
        voyage_no, loading_condition = grp["key"]
        first_row, last_row = lrows[0], lrows[-1]
        distance = sum(r["distance_nm"] for r in lrows)
        fuel_total = {g: sum(r["fuel_by_grade"][g] for r in lrows) for g in _LEG_GRADES}
        fuel_mt = round(sum(fuel_total.values()), 3)
        co2_mt = round(sum(fuel_total[g] * CF_TABLE.get(g, 0) for g in fuel_total), 3)
        ch4_co2e_mt, n2o_co2e_mt = ch4_n2o_co2e_t(fuel_total)
        co2e_mt = round(co2_mt + ch4_co2e_mt + n2o_co2e_mt, 3)

        at_berth_rows = [r for r in lrows if r["op_status"] == "NUW" and r["to_eu"] == "Y"]
        at_berth_fuel_by_grade = {g: sum(r["fuel_by_grade"][g] for r in at_berth_rows) for g in _LEG_GRADES}
        at_berth_fuel = sum(at_berth_fuel_by_grade.values())
        at_berth_co2 = round(sum(at_berth_fuel_by_grade[g] * CF_TABLE.get(g, 0) for g in at_berth_fuel_by_grade), 3)
        at_berth_ch4_co2e, at_berth_n2o_co2e = ch4_n2o_co2e_t(at_berth_fuel_by_grade)
        at_berth_co2e = round(at_berth_co2 + at_berth_ch4_co2e + at_berth_n2o_co2e, 3)
        at_berth_hours = round(sum(r["duration_h"] for r in at_berth_rows), 2)

        category = classify_eu_voyage(first_row["from_eu"], last_row["to_eu"])

        legs.append({
            "voyage_no": voyage_no,
            "loading_condition": loading_condition,
            "from_port": first_row["from_port"],
            "departure_time": first_row["date"].isoformat() if first_row["date"] else None,
            "to_port": last_row["to_port"],
            "eu_category": category,
            "eu_category_label": CATEGORY_LABELS[category],
            "distance_nm": round(distance, 1),
            "fuel_mt": fuel_mt,
            "co2_mt": co2_mt,
            "ch4_co2e_mt": round(ch4_co2e_mt, 4),
            "n2o_co2e_mt": round(n2o_co2e_mt, 4),
            "co2e_mt": co2e_mt,
            "at_berth_eu_co2_mt": at_berth_co2,
            "at_berth_eu_co2e_mt": at_berth_co2e,
            "at_berth_eu_hours": at_berth_hours,
            "_at_berth_fuel_mt": at_berth_fuel,  # internal, stripped before response
        })
    return legs


@router.get("/{imo}/eu-mrv")
def get_eu_mrv(
    imo: str,
    year: int = Query(..., description="Calendar year"),
    source: str = Query(..., description="'wni' or 'mari_apps' — required, never blended across sources"),
    db: Session = Depends(get_db),
):
    if source not in _EXPANDED_TABLE:
        raise HTTPException(status_code=400, detail="source must be 'wni' or 'mari_apps'.")
    vessel = db.query(Vessel).filter(Vessel.imo_number == imo).first()
    particulars = db.query(VesselParticulars).filter(VesselParticulars.vessel_imo == imo).first()

    legs = _eu_mrv_legs_computed(db, imo, source, year)
    if legs is None:
        return {"vessel_imo": imo, "year": year, "source": source,
                "note": "No leg data for this vessel/year/source — EU MRV not computable."}

    by_category = {cat: {"co2_mt": 0.0, "co2e_mt": 0.0, "distance_nm": 0.0, "fuel_mt": 0.0, "leg_count": 0} for cat in EU_VOYAGE_CATEGORIES}
    total_co2 = total_ch4_co2e = total_n2o_co2e = total_distance = total_fuel = at_berth_eu_co2 = at_berth_eu_co2e = at_berth_eu_hours = 0.0
    for leg in legs:
        b = by_category[leg["eu_category"]]
        b["co2_mt"] += leg["co2_mt"]; b["co2e_mt"] += leg["co2e_mt"]; b["distance_nm"] += leg["distance_nm"]
        b["fuel_mt"] += leg["fuel_mt"]; b["leg_count"] += 1
        total_co2 += leg["co2_mt"]; total_ch4_co2e += leg["ch4_co2e_mt"]; total_n2o_co2e += leg["n2o_co2e_mt"]
        total_distance += leg["distance_nm"]; total_fuel += leg["fuel_mt"]
        at_berth_eu_co2 += leg["at_berth_eu_co2_mt"]; at_berth_eu_co2e += leg["at_berth_eu_co2e_mt"]
        at_berth_eu_hours += leg["at_berth_eu_hours"]

    return {
        "vessel_imo": imo, "year": year, "source": source,
        "ship_id": {
            "imo_number": imo,
            "ship_name": vessel.vessel_name if vessel else None,
            "flag_state": particulars.flag if particulars else None,
            "ship_type": particulars.vessel_type if particulars else None,
            "gt": particulars.gross_tonnage if particulars else None,
        },
        "totals": {
            "total_co2_mt": round(total_co2, 3),
            # CH4/N2O per Reg. 2015/757 as amended by Reg. 2023/957 (Art. 5)
            # — energy-based, EU AR4 GWP. See eu_mrv_calculator.ch4_n2o_co2e_t.
            "total_ch4_co2e_mt": round(total_ch4_co2e, 4),
            "total_n2o_co2e_mt": round(total_n2o_co2e, 4),
            "total_co2e_mt": round(total_co2 + total_ch4_co2e + total_n2o_co2e, 3),
            "total_distance_nm": round(total_distance, 1),
            "total_fuel_mt": round(total_fuel, 3),
            "at_berth_eu_co2_mt": round(at_berth_eu_co2, 3),
            "at_berth_eu_co2e_mt": round(at_berth_eu_co2e, 3),
            "at_berth_eu_hours": round(at_berth_eu_hours, 1),
        },
        "by_category": [
            {"category": cat, "label": CATEGORY_LABELS[cat], **{k: round(v, 3) if isinstance(v, float) else v
                                                                   for k, v in vals.items()}}
            for cat, vals in by_category.items() if vals["leg_count"] > 0
        ],
        "data_gap_note": (
            "WNI has no 'departure port' field at all, so legs arriving at an EU port can't be "
            "split into 'between EU ports' vs 'non-EU → EU' — they're tagged 'Touches EU (direction "
            "unknown)' instead of guessed at. MariApps carries both fields (with some gaps) and gets "
            "the full 3-way classification wherever both sides are known."
        ) if source == "wni" else None,
    }


@router.get("/{imo}/eu-mrv/legs")
def get_eu_mrv_legs(
    imo: str,
    year: int = Query(..., description="Calendar year"),
    source: str = Query(..., description="'wni' or 'mari_apps' — required, never blended across sources"),
    db: Session = Depends(get_db),
):
    if source not in _EXPANDED_TABLE:
        raise HTTPException(status_code=400, detail="source must be 'wni' or 'mari_apps'.")
    legs = _eu_mrv_legs_computed(db, imo, source, year)
    if legs is None:
        return {"vessel_imo": imo, "year": year, "source": source, "legs": [],
                "note": "No leg data for this vessel/year/source."}
    for leg in legs:
        leg.pop("_at_berth_fuel_mt", None)
    return {"vessel_imo": imo, "year": year, "source": source, "legs": legs}


# ============================================================
# EU ETS — Dir. 2003/87/EC as amended by Dir. (EU) 2023/959. Reuses the same
# leg grouping and EU voyage classification as EU MRV (see eu_ets_calculator.py
# for the coverage-percentage / phase-in rules), extended with the extra
# per-leg fields (cargo, time-at-sea, next-departure lookahead, port-of-call
# flag) needed to reproduce the reference dashboard's Voyage Details table —
# the same fields IMO DCS's Leg tab already exposes, just carried through
# here alongside the EU classification instead of computed twice.
# ============================================================

def _eu_ets_leg_source_rows(db, imo, source, year):
    e_table = _EXPANDED_TABLE[source]
    date_col = _EXPANDED_DATE_COL[source]
    voyage_col = _VOYAGE_COL[source]
    sql = f"""
        SELECT e."{date_col}" AS dt,
               COALESCE(NULLIF(e."{voyage_col}", ''), '—') AS voyage_no,
               COALESCE(NULLIF(e."loading_condition", ''), 'Unknown') AS loading_condition,
               e."VoyageMeta_departure_port_last_leg_operational_LF" AS from_port,
               e."VoyageMeta_to_port_operational_LF" AS to_port,
               e."emissionx_from_eu_port" AS from_eu,
               e."emissionx_to_eu_port" AS to_eu,
               e."emissionx_op_status" AS op_status,
               {_num('Vessel_DOG_dCnt_operational_LF')} AS distance_nm,
               {_num('VoyageMeta_log_durationh_operational_LF')} AS duration_h,
               {_num('Vessel_Cargo_onboard_operational_LF')} AS cargo_mt,
               {_num('emissionx_total_hfo_mt')} AS hfo,
               {_num('emissionx_total_lfo_mt')} AS lfo,
               {_num('emissionx_total_mdo_mt')} AS mdo,
               {_num('emissionx_total_biofuel_mt')} AS bio_fuel
        FROM {e_table} e
        WHERE e."vessel_imo" = :imo AND EXTRACT(YEAR FROM e."{date_col}") = :year
        ORDER BY e."{date_col}"
    """
    return db.execute(text(sql), {"imo": imo, "year": year}).mappings().all()


def _eu_ets_legs_computed(db, imo, source, year):
    raw_rows = _eu_ets_leg_source_rows(db, imo, source, year)
    if not raw_rows:
        return None
    rows = [{
        "date": r["dt"], "voyage_no": r["voyage_no"], "loading_condition": r["loading_condition"],
        "op_status": r["op_status"], "from_port": r["from_port"], "to_port": r["to_port"],
        "from_eu": r["from_eu"], "to_eu": r["to_eu"],
        "distance_nm": float(r["distance_nm"] or 0), "duration_h": float(r["duration_h"] or 0),
        "cargo_mt": float(r["cargo_mt"] or 0),
        "fuel_by_grade": {g: float(r[g] or 0) for g in _LEG_GRADES},
    } for r in raw_rows]

    covers_ch4_n2o = ghg_scope_covers_ch4_n2o(year)

    legs = []
    for grp in group_into_legs(rows):
        lrows = grp["rows"]
        voyage_no, loading_condition = grp["key"]
        first_row, last_row = lrows[0], lrows[-1]
        distance = sum(r["distance_nm"] for r in lrows)
        time_at_sea = sum(r["duration_h"] for r in lrows if r["op_status"] == "UW")
        cargo_vals = [r["cargo_mt"] for r in lrows if r["cargo_mt"]]
        cargo = cargo_vals[0] if cargo_vals else None
        fuel_total = {g: sum(r["fuel_by_grade"][g] for r in lrows) for g in _LEG_GRADES}
        consumption_mt = round(sum(fuel_total.values()), 3)
        co2_mt = round(sum(fuel_total[g] * CF_TABLE.get(g, 0) for g in fuel_total), 3)
        # Art. 3ga(1): CO2 only for 2024-2025, CO2+CH4+N2O from 2026 onward —
        # co2e_mt is the actual covered-gas figure ETS scoping applies to.
        if covers_ch4_n2o:
            ch4_co2e, n2o_co2e = ch4_n2o_co2e_t(fuel_total)
            co2e_mt = round(co2_mt + ch4_co2e + n2o_co2e, 3)
        else:
            ch4_co2e = n2o_co2e = 0.0
            co2e_mt = co2_mt

        at_berth_rows = [r for r in lrows if r["op_status"] == "NUW" and r["to_eu"] == "Y"]
        at_berth_fuel_by_grade = {g: sum(r["fuel_by_grade"][g] for r in at_berth_rows) for g in _LEG_GRADES}
        at_berth_co2 = round(sum(at_berth_fuel_by_grade[g] * CF_TABLE.get(g, 0) for g in at_berth_fuel_by_grade), 3)
        if covers_ch4_n2o:
            at_berth_ch4, at_berth_n2o = ch4_n2o_co2e_t(at_berth_fuel_by_grade)
            at_berth_co2e = round(at_berth_co2 + at_berth_ch4 + at_berth_n2o, 3)
        else:
            at_berth_co2e = at_berth_co2

        category = classify_eu_voyage(first_row["from_eu"], last_row["to_eu"])
        scope_pct = ets_scope_pct(category)
        underway_co2e = round(co2e_mt - at_berth_co2e, 3)
        if scope_pct is None:
            # Underway portion can't be scoped (the WNI departure-port gap) —
            # only the at-berth-in-EU portion (always 100%, independent of
            # direction) is counted; the rest is an explicit gap, not a guess.
            eu_emission_mt = at_berth_co2e
            gap_co2_mt = underway_co2e
        else:
            eu_emission_mt = round(scope_pct * underway_co2e + at_berth_co2e, 3)
            gap_co2_mt = 0.0

        arrived = last_row["op_status"] == "NUW"

        legs.append({
            "voyage_no": voyage_no,
            "loading_condition": loading_condition,
            "eu_category": category,
            "eu_category_label": ETS_CATEGORY_LABELS[category],
            "port_of_call": "Port of call" if arrived else "Not port of call",
            "from_port": first_row["from_port"],
            "departure_time": first_row["date"].isoformat() if first_row["date"] else None,
            "to_port": last_row["to_port"] if arrived else None,
            "arrival_time": last_row["date"].isoformat() if arrived and last_row["date"] else None,
            "next_departure_time": None,  # filled below via look-ahead
            "distance_nm": round(distance, 1),
            "time_at_sea_h": round(time_at_sea, 1),
            "cargo_weight_mt": round(cargo, 1) if cargo else None,
            "consumption_mt": consumption_mt,
            "co2_mt": co2_mt,
            "co2e_mt": co2e_mt,
            "eu_emission_mt": eu_emission_mt,
            "gap_co2_mt": gap_co2_mt,
        })

    for i in range(len(legs) - 1):
        legs[i]["next_departure_time"] = legs[i + 1]["departure_time"]

    return legs


@router.get("/{imo}/eu-ets")
def get_eu_ets(
    imo: str,
    year: int = Query(..., description="Calendar year"),
    source: str = Query(..., description="'wni' or 'mari_apps' — required, never blended across sources"),
    eua_price: Optional[float] = Query(None, description="Live EUA market price (EUR/tCO2e) to estimate purchase cost — omit to skip that estimate rather than assume a market price"),
    db: Session = Depends(get_db),
):
    if source not in _EXPANDED_TABLE:
        raise HTTPException(status_code=400, detail="source must be 'wni' or 'mari_apps'.")
    vessel = db.query(Vessel).filter(Vessel.imo_number == imo).first()
    particulars = db.query(VesselParticulars).filter(VesselParticulars.vessel_imo == imo).first()

    legs = _eu_ets_legs_computed(db, imo, source, year)
    if legs is None:
        return {"vessel_imo": imo, "year": year, "source": source,
                "note": "No leg data for this vessel/year/source — EU ETS not computable."}

    pct = phase_in_pct(year)
    by_category = {cat: {"leg_count": 0} for cat in EU_VOYAGE_CATEGORIES}
    total_co2e = total_covered = total_gap = 0.0
    for leg in legs:
        by_category[leg["eu_category"]]["leg_count"] += 1
        total_co2e += leg["co2e_mt"]
        total_covered += leg["eu_emission_mt"]
        total_gap += leg["gap_co2_mt"]

    total_legs = len(legs)
    eu_emission_mt = round(total_covered * pct, 3)
    eu_allowance = round(eu_emission_mt, 0)  # 1 EUA surrendered per tCO2e (Art. 3gb)
    # Two separate, uncorrelated money figures — see eu_ets_calculator.py docstring.
    # Purchase-cost estimate is ONLY computed when a real price is supplied —
    # unlike the old single "EU Cost" field, no illustrative default is
    # fabricated here (the reference workbook leaves this cell blank for the
    # same reason: it's a fluctuating market price, not a constant).
    non_surrender_penalty_eur = round(eu_allowance * NON_SURRENDER_PENALTY_EUR_PER_T, 0)  # Art. 16(3), fixed
    estimated_purchase_cost_eur = round(eu_allowance * eua_price, 0) if eua_price is not None else None

    return {
        "vessel_imo": imo, "year": year, "source": source,
        "ship_id": {
            "imo_number": imo,
            "ship_name": vessel.vessel_name if vessel else None,
            "flag_state": particulars.flag if particulars else None,
            "ship_type": particulars.vessel_type if particulars else None,
            "gt": particulars.gross_tonnage if particulars else None,
        },
        "results": {
            "ghg_emission_mt": round(total_co2e, 3),
            "eu_emission_mt": eu_emission_mt,
            "phase_in_pct": round(pct * 100, 0),
            "ghg_scope": ghg_scope_label(year),
        },
        "eu_allowance_eua": eu_allowance,
        "non_surrender_penalty_eur": non_surrender_penalty_eur,
        "non_surrender_penalty_rate_eur_per_t": NON_SURRENDER_PENALTY_EUR_PER_T,
        "estimated_purchase_cost_eur": estimated_purchase_cost_eur,
        "eua_price_used": eua_price,
        "voyage_distribution": [
            {"category": cat, "label": ETS_CATEGORY_LABELS[cat], "leg_count": v["leg_count"],
             "pct": round(100 * v["leg_count"] / total_legs, 1) if total_legs else 0}
            for cat, v in by_category.items() if v["leg_count"] > 0
        ],
        "gap_co2_mt": round(total_gap, 3),
        "data_gap_note": (
            "WNI has no 'departure port' field, so legs arriving at an EU port with unknown origin "
            "('Touches EU (direction unknown)') can't be scoped at 50% or 100% — their underway "
            f"{ghg_scope_label(year)} is excluded from EU Emission/Allowance/Cost above (see "
            "gap_co2_mt) rather than guessed at; only their at-berth-in-EU portion, which is always "
            "100% regardless of direction, is counted. MariApps carries both port fields (with some "
            "gaps) and gets the full scoping wherever both sides are known."
        ) if source == "wni" else None,
    }


@router.get("/{imo}/eu-ets/legs")
def get_eu_ets_legs(
    imo: str,
    year: int = Query(..., description="Calendar year"),
    source: str = Query(..., description="'wni' or 'mari_apps' — required, never blended across sources"),
    db: Session = Depends(get_db),
):
    if source not in _EXPANDED_TABLE:
        raise HTTPException(status_code=400, detail="source must be 'wni' or 'mari_apps'.")
    legs = _eu_ets_legs_computed(db, imo, source, year)
    if legs is None:
        return {"vessel_imo": imo, "year": year, "source": source, "legs": [],
                "note": "No leg data for this vessel/year/source."}
    return {"vessel_imo": imo, "year": year, "source": source, "legs": legs}


# ============================================================
# FuelEU Maritime — Reg. (EU) 2023/1805. Voyage Details table below is
# identical in shape to EU ETS's (same leg grouping, same Art. 2(1) energy
# scope — see fueleu_calculator.py docstring for why reusing ets_scope_pct
# is correct, not just convenient), so this reuses _eu_ets_leg_source_rows
# directly rather than a third copy of the same query.
# ============================================================

def _fueleu_legs_computed(db, imo, source, year):
    raw_rows = _eu_ets_leg_source_rows(db, imo, source, year)
    if not raw_rows:
        return None
    rows = [{
        "date": r["dt"], "voyage_no": r["voyage_no"], "loading_condition": r["loading_condition"],
        "op_status": r["op_status"], "from_port": r["from_port"], "to_port": r["to_port"],
        "from_eu": r["from_eu"], "to_eu": r["to_eu"],
        "distance_nm": float(r["distance_nm"] or 0), "duration_h": float(r["duration_h"] or 0),
        "cargo_mt": float(r["cargo_mt"] or 0),
        "fuel_by_grade": {g: float(r[g] or 0) for g in _LEG_GRADES},
    } for r in raw_rows]

    legs = []
    for grp in group_into_legs(rows):
        lrows = grp["rows"]
        voyage_no, loading_condition = grp["key"]
        first_row, last_row = lrows[0], lrows[-1]
        distance = sum(r["distance_nm"] for r in lrows)
        time_at_sea = sum(r["duration_h"] for r in lrows if r["op_status"] == "UW")
        cargo_vals = [r["cargo_mt"] for r in lrows if r["cargo_mt"]]
        cargo = cargo_vals[0] if cargo_vals else None
        fuel_total = {g: sum(r["fuel_by_grade"][g] for r in lrows) for g in _LEG_GRADES}
        consumption_mt = round(sum(fuel_total.values()), 3)

        category = classify_eu_voyage(first_row["from_eu"], last_row["to_eu"])
        scope_pct = ets_scope_pct(category)
        wtw_g, energy_mj = leg_wtw(fuel_total)

        arrived = last_row["op_status"] == "NUW"

        legs.append({
            "voyage_no": voyage_no,
            "loading_condition": loading_condition,
            "eu_category": category,
            "eu_category_label": ETS_CATEGORY_LABELS[category],
            "port_of_call": "Port of call" if arrived else "Not port of call",
            "from_port": first_row["from_port"],
            "departure_time": first_row["date"].isoformat() if first_row["date"] else None,
            "to_port": last_row["to_port"] if arrived else None,
            "arrival_time": last_row["date"].isoformat() if arrived and last_row["date"] else None,
            "next_departure_time": None,  # filled below via look-ahead
            "distance_nm": round(distance, 1),
            "time_at_sea_h": round(time_at_sea, 1),
            "cargo_weight_mt": round(cargo, 1) if cargo else None,
            "consumption_mt": consumption_mt,
            "_wtw_g": wtw_g, "_energy_mj": energy_mj, "_scope_pct": scope_pct,
        })

    for i in range(len(legs) - 1):
        legs[i]["next_departure_time"] = legs[i + 1]["departure_time"]

    return legs


@router.get("/{imo}/fueleu")
def get_fueleu(
    imo: str,
    year: int = Query(..., description="Calendar year"),
    source: str = Query(..., description="'wni' or 'mari_apps' — required, never blended across sources"),
    db: Session = Depends(get_db),
):
    if source not in _EXPANDED_TABLE:
        raise HTTPException(status_code=400, detail="source must be 'wni' or 'mari_apps'.")
    vessel = db.query(Vessel).filter(Vessel.imo_number == imo).first()
    particulars = db.query(VesselParticulars).filter(VesselParticulars.vessel_imo == imo).first()

    legs = _fueleu_legs_computed(db, imo, source, year)
    if legs is None:
        return {"vessel_imo": imo, "year": year, "source": source,
                "note": "No leg data for this vessel/year/source — FuelEU Maritime not computable."}

    scoped_wtw_g = scoped_energy_mj = gap_energy_mj = 0.0
    for leg in legs:
        if leg["_scope_pct"] is None:
            gap_energy_mj += leg["_energy_mj"]
            continue
        scoped_wtw_g += leg["_scope_pct"] * leg["_wtw_g"]
        scoped_energy_mj += leg["_scope_pct"] * leg["_energy_mj"]

    ghgie_actual = round(scoped_wtw_g / scoped_energy_mj, 4) if scoped_energy_mj else None
    limit = ghg_limit(year)

    compliance_balance = banking = penalty = None
    cb_g = None
    if ghgie_actual is not None:
        cb_g = (limit - ghgie_actual) * scoped_energy_mj
        compliance_balance = round(cb_g / 1_000_000, 3)  # tCO2eq
        if compliance_balance >= 0:
            banking, penalty = compliance_balance, 0.0
        else:
            # Real Art. 23(2) penalty for the raw deficit — no assumed
            # borrowing offset (see fueleu_calculator.py docstring for why
            # that earlier policy didn't match the reference workbook).
            banking = 0.0
            penalty = estimated_penalty(abs(cb_g), ghgie_actual)

    for leg in legs:
        leg.pop("_wtw_g", None); leg.pop("_energy_mj", None); leg.pop("_scope_pct", None)

    return {
        "vessel_imo": imo, "year": year, "source": source,
        "ship_id": {
            "imo_number": imo,
            "ship_name": vessel.vessel_name if vessel else None,
            "flag_state": particulars.flag if particulars else None,
            "ship_type": particulars.vessel_type if particulars else None,
            "gt": particulars.gross_tonnage if particulars else None,
        },
        "results": {
            "ghg_intensity_g_per_mj": ghgie_actual,
            "ghg_limit_g_per_mj": limit,
            "compliance_balance_t": compliance_balance,
            "banking_t": banking,
            # Not auto-derived — Art. 20(3) borrowing is a company-declared
            # action against a FUTURE period, capped/restricted after 2
            # consecutive deficit years; a single year's data can't
            # determine it. See borrowing_note and fueleu_calculator.py.
            "borrowing_t": None,
            "estimated_penalty_eur": penalty,
        },
        "borrowing_note": (
            "Borrowing (Art. 20(3)) isn't tracked here — it's a company-declared, capped, multi-year "
            "action this single-year snapshot can't determine. Estimated Penalty above is the raw "
            "current-period deficit exposure as if no borrowing were declared."
        ) if compliance_balance is not None and compliance_balance < 0 else None,
        "gap_energy_mj": round(gap_energy_mj, 1),
        "data_gap_note": (
            "WNI has no 'departure port' field, so legs arriving at an EU port with unknown origin "
            "can't be scoped at 50% or 100% — their energy is excluded from this calculation entirely "
            "(see gap_energy_mj) rather than guessed at. MariApps carries both port fields (with some "
            "gaps) and gets the full scoping wherever both sides are known. See fueleu_calculator.py "
            "for the documented Well-to-Wake simplification this GHG Intensity figure relies on."
        ) if source == "wni" else (
            "See fueleu_calculator.py for the documented Well-to-Wake simplification this GHG "
            "Intensity figure relies on (no CH4/N2O slip data; biofuel priced at its fossil-equivalent "
            "factor absent Proof-of-Sustainability documentation)."
        ),
    }


@router.get("/{imo}/fueleu/legs")
def get_fueleu_legs(
    imo: str,
    year: int = Query(..., description="Calendar year"),
    source: str = Query(..., description="'wni' or 'mari_apps' — required, never blended across sources"),
    db: Session = Depends(get_db),
):
    if source not in _EXPANDED_TABLE:
        raise HTTPException(status_code=400, detail="source must be 'wni' or 'mari_apps'.")
    legs = _fueleu_legs_computed(db, imo, source, year)
    if legs is None:
        return {"vessel_imo": imo, "year": year, "source": source, "legs": [],
                "note": "No leg data for this vessel/year/source."}
    for leg in legs:
        leg.pop("_wtw_g", None); leg.pop("_energy_mj", None); leg.pop("_scope_pct", None)
    return {"vessel_imo": imo, "year": year, "source": source, "legs": legs}
