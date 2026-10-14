# ===========================================================================
# backend/data_quality/checks.py
#
# The 3 confirmed mandatory-field rules (client request 2026-10):
#   - missing_weather: a steaming report missing BF_Wind or Sig_Wave_Ht_m —
#     the CP fair-weather filter input every CP calculation depends on
#     (see CLAUDE.md's Charter-Party Performance section).
#   - missing_fuel: a real steaming day (Distance_nm/Duration_h present) with
#     zero fuel logged across every grade — the AM KIRTI 38/05 gap found
#     2026-09 while chasing the "fuel chart scale looks wrong" complaint.
#   - missing_cp_instruction: reads the dataqualityx_missing_cp_instruction
#     flag expander.py already computes at ingestion (vessel-gated by
#     cp_vessel_description.requires_cp_remarks_check) — not recomputed here.
#
# Pure read-only query functions — no DB writes, no email. The daily job
# (daily_job.py) owns the open/resolved state machine and notifications.
# ===========================================================================
from sqlalchemy import text

from ..cp.cp_compliance_v2 import _is_steaming, _is_sea_passage_event

# Same consumer-prefix/grade enumeration as api/routes/cp_routes.py's
# _FO_COLS/_DOGO_COLS (duplicated rather than cross-imported from api.routes
# into backend, to not invert that layering — api/routes depends on backend,
# never the reverse elsewhere in this codebase). Keep in sync manually if a
# new consumer type is ever added there.
_CONSUMER_PREFIXES = ("me", "ae", "bl", "combl", "inc", "aeb", "blfo", "eg")
_FO_COLS = [f"{c}_{g}" for c in _CONSUMER_PREFIXES for g in ("hfo", "lfo")]
_DOGO_COLS = [f"{c}_mdo" for c in _CONSUMER_PREFIXES]


def _numexpr(col):
    # Require at least one digit (rejects '', '.', text); optional sign/decimals.
    return f"(CASE WHEN {col} ~ '^[-+]?[0-9]+(\\.[0-9]+)?$' THEN {col}::double precision ELSE 0 END)"


_FO_EXPR = "(" + "+".join(_numexpr(f"n.{c}") for c in _FO_COLS) + ")"
_DOGO_EXPR = "(" + "+".join(_numexpr(f"n.{c}") for c in _DOGO_COLS) + ")"

# Per-source join: WNI links via raw_report_id, MariApps via raw_mariapps_id —
# same convention as cp_routes.py's _SOURCE_SQL (Wartsila FOS omitted here,
# it never feeds analysis_data per CLAUDE.md).
_SOURCE_SQL = {
    "wni": ('JOIN noon_report_data n ON n.raw_report_id = a.raw_report_id', "wni"),
    "mari_apps": ('JOIN mariapps_reports_data n ON n.raw_report_id = a.raw_mariapps_id', "mari_apps"),
}


def fetch_report_rows(db, vessel_imo, report_date, source):
    """One analysis_data row per report for this vessel/date/source — same
    shape cp_routes.py's _rows_for_source() produces (Distance_nm, Duration_h,
    BF_Wind, Sig_Wave_Ht_m, fo_mt, dogo_mt, event_type)."""
    if source not in _SOURCE_SQL:
        return []
    join, src = _SOURCE_SQL[source]
    sql = f"""
        SELECT a."Voyage_No", a."Loading_Cond", a."Date", a."Distance_nm", a."Duration_h",
               a."BF_Wind", a."Sig_Wave_Ht_m",
               {_FO_EXPR} AS fo_mt, {_DOGO_EXPR} AS dogo_mt,
               n.log_type AS event_type
        FROM analysis_data a
        {join}
        WHERE a.vessel_imo = :imo AND a.source_id = :src AND a."Date" = :report_date
    """
    rows = db.execute(text(sql), {"imo": vessel_imo, "src": src, "report_date": report_date}).mappings().all()
    return [dict(r) for r in rows]


def _steaming_sea_passage_rows(db, vessel_imo, report_date, source):
    rows = fetch_report_rows(db, vessel_imo, report_date, source)
    return [r for r in rows if _is_steaming(r) and _is_sea_passage_event(r)]


def check_missing_weather(db, vessel_imo, report_date, source):
    rows = _steaming_sea_passage_rows(db, vessel_imo, report_date, source)
    bad = [r for r in rows if r.get("BF_Wind") is None or r.get("Sig_Wave_Ht_m") is None]
    if not bad:
        return None
    return {"count": len(bad), "voyages": sorted({r["Voyage_No"] for r in bad if r.get("Voyage_No")})}


def check_missing_fuel(db, vessel_imo, report_date, source):
    rows = _steaming_sea_passage_rows(db, vessel_imo, report_date, source)
    bad = [r for r in rows if (r.get("fo_mt") or 0) == 0 and (r.get("dogo_mt") or 0) == 0]
    if not bad:
        return None
    return {"count": len(bad), "voyages": sorted({r["Voyage_No"] for r in bad if r.get("Voyage_No")})}


def check_missing_cp_instruction(db, vessel_imo, report_date):
    """MariApps-only — the CP remarks mechanism doesn't exist for WNI. Already
    respects the per-vessel requires_cp_remarks_check gate, since
    dataqualityx_missing_cp_instruction is only ever set non-null for vessels
    that have that flag on (see expander.py's _data_quality_extra_fields)."""
    rows = db.execute(text("""
        SELECT log_number, voyage_no FROM expanded_mariapps_data
        WHERE vessel_imo = :imo AND log_date = :report_date
          AND dataqualityx_missing_cp_instruction IS NOT NULL
    """), {"imo": vessel_imo, "report_date": report_date}).mappings().all()
    if not rows:
        return None
    return {
        "count": len(rows),
        "logs": sorted({r["log_number"] for r in rows if r["log_number"]}),
    }


def run_checks_for_date(db, vessel_imo, report_date):
    """Returns {(source_id, rule_key): detail_dict} for every rule that found
    a gap on this vessel/date — empty dict if everything's clean."""
    findings = {}
    for source in ("wni", "mari_apps"):
        weather = check_missing_weather(db, vessel_imo, report_date, source)
        if weather:
            findings[(source, "missing_weather")] = weather
        fuel = check_missing_fuel(db, vessel_imo, report_date, source)
        if fuel:
            findings[(source, "missing_fuel")] = fuel

    cp_instr = check_missing_cp_instruction(db, vessel_imo, report_date)
    if cp_instr:
        findings[("mari_apps", "missing_cp_instruction")] = cp_instr

    return findings
