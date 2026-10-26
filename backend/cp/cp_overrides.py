# ============================================================
# CP MANUAL OVERRIDES — shared lookup + merge helper
# ============================================================
# A manual correction to a voyage's (or one day's) CP speed/consumption,
# entered by shore staff once a remarks gap or parsing error is confirmed
# (see models.py's CPManualOverride doc comment for the motivating case).
#
# This is deliberately the ONLY place that decides what "wins" among a day's
# possible CP instruction sources — both expander.py (display columns) and
# cp_routes.py (the live CP Performance table + Voyage Audit PDF) call
# `resolve_cp_instruction()` rather than re-implementing the priority order,
# so the two can't drift out of sync with each other the way the PDF and the
# live table once did (see cp_calculator.py's 2026-09 unification comment).
#
# Priority: day override > voyage override > remarks instruction > standing
# cp_sea_warranty match (the last one isn't resolved here — callers already
# fall back to it themselves when this returns None).
# ============================================================
from sqlalchemy import text


def fetch_cp_overrides(conn, vessel_imo, source_id):
    """One query per vessel+source — same caching convention as
    _fetch_active_cp_sea_warranty (expander.py) and cp_remarks_cache. Returns
    {"voyage": {voyage_no: instr_dict}, "day": {(voyage_no, "YYYY-MM-DD"): instr_dict}}."""
    rows = conn.execute(text("""
        SELECT voyage_no, log_date, speed_kn, total_mt_day, go_mt_day, note
        FROM cp_manual_overrides
        WHERE vessel_imo = :imo AND source_id = :src
    """), {"imo": vessel_imo, "src": source_id}).fetchall()

    voyage, day = {}, {}
    for voyage_no, log_date, speed_kn, total_mt_day, go_mt_day, note in rows:
        instr = {"speed_kn": speed_kn, "total_mt_day": total_mt_day, "go_mt_day": go_mt_day,
                 "note": note, "is_override": True}
        key = str(voyage_no).strip()
        if log_date is None:
            voyage[key] = instr
        else:
            day[(key, str(log_date)[:10])] = instr
    return {"voyage": voyage, "day": day}


def resolve_cp_instruction(overrides, voyage_no, log_date, remarks_instruction=None):
    """Applies the priority order for ONE report: day override > voyage
    override > remarks_instruction (whatever the caller already parsed from
    that day's cpx_remarks) > None (caller falls back to the standing
    warranty match itself).

    `overrides` is a fetch_cp_overrides() result (or None/empty — every
    caller already has a "no overrides configured" path since this is a new,
    optional feature). `voyage_no`/`log_date` are that report's own values
    (log_date as "YYYY-MM-DD" or any string starting with one — only the
    first 10 chars are compared, matching how it's stored)."""
    if not overrides:
        return remarks_instruction
    v_key = str(voyage_no).strip() if voyage_no is not None else ""
    d_key = (v_key, str(log_date)[:10]) if log_date else None

    if d_key and d_key in overrides.get("day", {}):
        return overrides["day"][d_key]
    if v_key in overrides.get("voyage", {}):
        return overrides["voyage"][v_key]
    return remarks_instruction
