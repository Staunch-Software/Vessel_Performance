"""
audit_cp_calculations.py
=========================
Independent regression check for Charter-Party performance calculations.

Why this exists
----------------
Manually reviewing generated Voyage Audit Report PDFs one at a time doesn't
scale, and only catches whatever specific discrepancy happens to be visible
in the report you happened to open. This script does the same hand-check
that's been done manually on individual voyages (AM UMANG 82B, 80/01) —
pull raw per-day rows straight from the database, independently classify
good/adverse weather, independently re-derive distance/time/fuel and the
event-wise Time Lost / Consumption Over-Consumption formulas — and runs it
across every voyage for a vessel (or the whole fleet), diffing the result
against what the live app's own /cp/{imo}/performance endpoint currently
returns for that same voyage.

Deliberately does NOT import backend.cp.cp_calculator — the point is to
verify the app's actual behaviour against an independent implementation of
the same specification (the Charter Party Compliance Auditing Methodology
printed on the PDF's own pages 10-11), not to test the app's code against
itself. The one thing it does reuse is _pick_sea_warranty() from
cp_compliance_v2.py, since that's a plain nearest-speed lookup over
already-loaded config, not itself a source of any bug found so far.

Usage
-----
    # One vessel
    python audit_cp_calculations.py --imo 9792058

    # One vessel, one source only
    python audit_cp_calculations.py --imo 9792058 --source mari_apps

    # Whole fleet
    python audit_cp_calculations.py --all

    # Point at a different API base (defaults to local dev uvicorn on :8000;
    # on the server pass e.g. http://127.0.0.1:8011/api/v1)
    python audit_cp_calculations.py --imo 9792058 --base-url http://127.0.0.1:8011/api/v1

Exit code is 1 if any voyage shows a discrepancy beyond tolerance, so this
can be wired into a cron/CI job later. Nothing here writes to the database
or calls any mutating endpoint — read-only throughout.
"""

import argparse
import sys

import requests
from sqlalchemy import text

from backend.database import engine
from backend.cp.cp_compliance_v2 import _pick_sea_warranty

# Same fixed fair-weather definition as cp_calculator.py's own docstring —
# re-typed here independently rather than imported, so a regression in the
# app's own constant wouldn't silently pass this check too.
FAIR_BF_MAX = 4.0
FAIR_WAVE_MAX_M = 3.0
SPEED_ALLOWANCE_KN = 0.5
CONS_TOLERANCE_PCT = 5.0

# How far the app's live figures may differ from this script's independent
# recompute before it's flagged — small enough to catch a real regression,
# loose enough to absorb harmless rounding-display differences.
TOL_HOURS = 0.1
TOL_MT = 0.15
TOL_NM = 1.0

# All 8 documented consumer prefixes x the 3 relevant grades (see
# emission_routes.py's _CONSUMERS convention) — closes a gap found while
# building this: cp_routes.py's own SQL only summed me/ae/bl, silently
# dropping combl/inc/aeb/blfo/eg wherever they're actually used.
_FO_COLS = [f"{c}_{g}" for c in ("me", "ae", "bl", "combl", "inc", "aeb", "blfo", "eg") for g in ("hfo", "lfo")]
_DOGO_COLS = [f"{c}_mdo" for c in ("me", "ae", "bl", "combl", "inc", "aeb", "blfo", "eg")]


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _numsum(row, cols):
    total = 0.0
    for c in cols:
        v = _num(row.get(c))
        if v is not None:
            total += v
    return total


def _is_fair_weather(row):
    """Mirrors the printed methodology exactly: BF<=4 and Hs<=3.0m. Missing
    just one -> not fair (can't verify). Missing both -> treated as good
    weather (client-approved 2026-08) rather than penalise a logging gap."""
    bf = _num(row.get("BF_Wind"))
    hs = _num(row.get("Sig_Wave_Ht_m"))
    if bf is None and hs is None:
        return True
    if bf is None or hs is None:
        return False
    return bf <= FAIR_BF_MAX and hs <= FAIR_WAVE_MAX_M


def _discover_voyages(imo=None):
    """Every (vessel_imo, voyage_no, source_id) combo that has a real EOSP —
    same 'only finalised voyages' rule the app itself applies."""
    sql = """
        SELECT DISTINCT a.vessel_imo, a."Voyage_No", a.source_id, v.vessel_name
        FROM analysis_data a
        JOIN vessels v ON v.imo_number = a.vessel_imo
        WHERE a."Voyage_No" IS NOT NULL
    """
    params = {}
    if imo:
        sql += " AND a.vessel_imo = :imo"
        params["imo"] = imo
    with engine.connect() as conn:
        return conn.execute(text(sql), params).fetchall()


def _fetch_raw_rows(imo, voyage_no, source_id):
    """Raw per-day rows for one voyage, with ALL 8 consumers' fuel-grade
    columns and BOSP/EOSP event typing, joined to whichever source table
    actually holds this row's grade data."""
    if source_id == "mari_apps":
        join = 'JOIN mariapps_reports_data m ON m.raw_report_id = a.raw_mariapps_id'
        event_col = "m.log_type"
    else:
        join = 'JOIN noon_report_data m ON m.raw_report_id = a.raw_report_id'
        event_col = "m.log_type"

    grade_cols = ", ".join(f"m.{c}" for c in _FO_COLS + _DOGO_COLS)
    sql = f"""
        SELECT a."Voyage_No", a."Loading_Cond", a."Date", a."Time_UTC",
               a."Distance_nm", a."Duration_h", a."SOG_kn",
               a."BF_Wind", a."Sig_Wave_Ht_m",
               {event_col} AS event_type,
               {grade_cols}
        FROM analysis_data a
        {join}
        WHERE a.vessel_imo = :imo AND a."Voyage_No" = :voyage_no AND a.source_id = :source_id
        ORDER BY a."Date", a."Time_UTC"
    """
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            text(sql), {"imo": imo, "voyage_no": voyage_no, "source_id": source_id}
        ).mappings().all()]
    return rows


def _window_to_bosp_eosp(rows):
    """Same OUTER trim as cp_routes.py._rows_for_source: keep only rows
    between the last valid BOSP (or the first row, if none precedes the
    EOSP) and the final EOSP. Returns None if there's no usable EOSP.
    A voyage_no can still span MORE THAN ONE real BOSP->EOSP passage within
    this trimmed window (the same literal string reused over time) — see
    _segments() below, which is what actually splits it, matching
    cp_calculator.py exactly. Skipping that step was the audit script's own
    bug on its first run: it merged multiple real voyages under one
    voyage_no into a single inflated span, producing false "mismatches"
    against the API (which correctly reports each segment separately)."""
    eosps = [r for r in rows if r["event_type"] and "EOSP" in r["event_type"].upper()]
    if not eosps:
        return None
    eosp = eosps[-1]
    eosp_dt = f"{eosp['Date']}T{eosp['Time_UTC'] or '00:00'}"

    bosps = [r for r in rows if r["event_type"] and "BOSP" in r["event_type"].upper()]
    valid_bosps = [b for b in bosps if f"{b['Date']}T{b['Time_UTC'] or '00:00'}" <= eosp_dt]
    dep = valid_bosps[0] if valid_bosps else rows[0]
    dep_dt = f"{dep['Date']}T{dep['Time_UTC'] or '00:00'}"

    if dep_dt >= eosp_dt:
        return None
    return [r for r in rows if dep_dt <= f"{r['Date']}T{r['Time_UTC'] or '00:00'}" <= eosp_dt]


def _segments(rows):
    """Ported 1:1 from cp_calculator.py._segments(): a segment only closes
    when a NEW BOSP shows up after already having seen an EOSP — not the
    moment any EOSP appears (absorbs a corrected/re-submitted EOSP without
    creating a spurious extra segment)."""
    segs, cur = [], []
    seen_eosp = False
    for r in rows:
        ev = (r.get("event_type") or "").upper()
        if "BOSP" in ev and seen_eosp and cur:
            segs.append(cur)
            cur = []
            seen_eosp = False
        cur.append(r)
        if "EOSP" in ev:
            seen_eosp = True
    if cur:
        segs.append(cur)
    return segs


def _aggregate(rows):
    dist = sum(_num(r.get("Distance_nm")) or 0 for r in rows)
    hours = sum(_num(r.get("Duration_h")) or 0 for r in rows)
    fo = sum(_numsum(r, _FO_COLS) for r in rows)
    dogo = sum(_numsum(r, _DOGO_COLS) for r in rows)
    return {
        "distance_nm": dist,
        "time_h": hours,
        "avg_speed_kn": (dist / hours) if hours else None,
        "fo_mt": fo,
        "dogo_mt": dogo,
    }


def _dominant_condition(rows):
    counts = {"Laden": 0, "Ballast": 0}
    for r in rows:
        lc = str(r.get("Loading_Cond") or "").strip().lower()
        if lc.startswith("l"):
            counts["Laden"] += 1
        elif lc.startswith("b"):
            counts["Ballast"] += 1
    return "Laden" if counts["Laden"] >= counts["Ballast"] else "Ballast"


def _fetch_warranty_candidates(imo, cond):
    sql = """
        SELECT s.warranted_speed_kn, s.me_cons_mt_day, s.me_fuel_grade,
               s.ae_cons_mt_day, s.ae_fuel_grade, s.boiler_cons_sea_mt_day,
               s.speed_tolerance_kn, s.cons_tolerance_pct
        FROM cp_sea_warranty s
        JOIN cp_vessel_description v ON v.id = s.cp_id
        WHERE v.vessel_imo = :imo AND v.doc_status = 'Active' AND s.loading_condition = :cond
    """
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(text(sql), {"imo": imo, "cond": cond}).mappings().all()]

    def _cls(grade):
        if not grade:
            return None
        g = grade.upper()
        if any(x in g for x in ("VLSFO", "HFO", "LFO", "HSFO")):
            return "FO"
        if any(x in g for x in ("MGO", "MDO", "LDO", "HFHSD", "DMA", "DMB")):
            return "DOGO"
        return None

    candidates = []
    for s in rows:
        me_cls = _cls(s["me_fuel_grade"])
        ae_cls = _cls(s["ae_fuel_grade"]) or me_cls
        me, ae, boiler = s["me_cons_mt_day"] or 0, s["ae_cons_mt_day"] or 0, s["boiler_cons_sea_mt_day"] or 0
        fo = (me if me_cls == "FO" else 0) + (ae if ae_cls == "FO" else 0) + boiler
        dogo = (me if me_cls == "DOGO" else 0) + (ae if ae_cls == "DOGO" else 0)
        candidates.append({
            "warranted_speed_kn": s["warranted_speed_kn"],
            "warranted_fo_mtpd": round(fo, 2),
            "warranted_dogo_mtpd": round(dogo, 2),
            "speed_tol_kn": s["speed_tolerance_kn"] or SPEED_ALLOWANCE_KN,
            "cons_tol_pct": s["cons_tolerance_pct"] or CONS_TOLERANCE_PCT,
        })
    return candidates


def _event_wise_time_and_consumption(steaming_rows, warranty):
    """(a)/(b)/(c) Time Calculation and (d')/(e')/(f') Consumption
    Calculation, exactly as printed in the report's own methodology pages —
    computed event-by-event (excluding nothing here, since this script
    checks the ENTIRE steaming set, matching the app's 'excluding the COSP
    report' rule approximately: COSP/BOSP rows carry zero distance so they
    don't contribute regardless)."""
    w_spd = _num(warranty.get("warranted_speed_kn")) or 0
    w_fo = _num(warranty.get("warranted_fo_mtpd")) or 0
    w_dogo = _num(warranty.get("warranted_dogo_mtpd")) or 0
    tol_kn = _num(warranty.get("speed_tol_kn")) or SPEED_ALLOWANCE_KN
    tol_pct = _num(warranty.get("cons_tol_pct")) or CONS_TOLERANCE_PCT
    tot_warranted = w_fo + w_dogo

    b_h = c_h = e_mt = f_mt = 0.0
    event_count = 0
    for r in steaming_rows:
        dist = _num(r.get("Distance_nm")) or 0
        if dist <= 0 or not w_spd:
            continue
        event_count += 1
        eff_spd = w_spd - tol_kn
        c_h += dist / w_spd
        f_mt += (dist / w_spd) * (tot_warranted * (1 - tol_pct / 100.0) / 24.0)
        if eff_spd > 0:
            b_h += dist / eff_spd
            e_mt += (dist / eff_spd) * (tot_warranted * (1 + tol_pct / 100.0) / 24.0)

    return {"b_h": b_h, "c_h": c_h, "e_mt": e_mt, "f_mt": f_mt, "event_count": event_count}


def _segment_result(seg_rows, imo):
    """Per-segment entire/good_wx aggregates plus the decided Loss(+)/
    Saving(-) figures, using the SAME sign convention as cp_calculator.py:
    whichever of (time lost, time gained) is positive wins, else 0 — same
    for fuel over-consumption vs saving. A segment's decided loss can be
    negative (a saving), and summing decided values across segments is
    valid the same way summing several already-decided report rows is."""
    steaming = [r for r in seg_rows if (_num(r.get("Distance_nm")) or 0) > 0 and (_num(r.get("Duration_h")) or 0) > 0]
    if not steaming:
        return None
    fair_rows = [r for r in steaming if _is_fair_weather(r)]
    entire = _aggregate(steaming)
    good_wx = _aggregate(fair_rows)
    cond = _dominant_condition(steaming)

    candidates = _fetch_warranty_candidates(imo, cond)
    warranty = _pick_sea_warranty(candidates, good_wx["avg_speed_kn"] or entire["avg_speed_kn"]) or {}
    w_spd = _num(warranty.get("warranted_speed_kn")) or 0

    ev = _event_wise_time_and_consumption(steaming, warranty)
    time_lost_h = 0.0
    fuel_lost_mt = 0.0
    if good_wx["avg_speed_kn"] and w_spd:
        a_h = entire["distance_nm"] / good_wx["avg_speed_kn"]
        time_lost = (a_h - ev["b_h"]) if ev["b_h"] else None
        time_gained = ev["c_h"] - a_h
        if time_lost is not None and time_lost > 0:
            time_lost_h = time_lost
        elif time_gained > 0:
            time_lost_h = -time_gained

        if good_wx["time_h"]:
            d_mt = a_h * (good_wx["fo_mt"] + good_wx["dogo_mt"]) / good_wx["time_h"]
            fuel_over = d_mt - ev["e_mt"]
            fuel_save = ev["f_mt"] - d_mt
            if fuel_over > 0:
                fuel_lost_mt = fuel_over
            elif fuel_save > 0:
                fuel_lost_mt = -fuel_save

    return {
        "entire": entire, "good_wx": good_wx, "condition": cond,
        "events": ev["event_count"], "time_lost_h": time_lost_h, "fuel_lost_mt": fuel_lost_mt,
    }


def _sum_field(dicts, key, sub=None):
    total = 0.0
    for d in dicts:
        v = d.get(sub, {}).get(key) if sub else d.get(key)
        if v is not None:
            total += v
    return total


def _check_voyage(imo, voyage_no, source_id, vessel_name, base_url, session):
    raw = _fetch_raw_rows(imo, voyage_no, source_id)
    if not raw:
        return None
    windowed = _window_to_bosp_eosp(raw)
    if not windowed:
        return {"imo": imo, "voyage_no": voyage_no, "source": source_id, "vessel": vessel_name,
                "skipped": "no valid BOSP-EOSP window (ongoing or inverted range)"}

    segments = [_segment_result(seg, imo) for seg in _segments(windowed)]
    segments = [s for s in segments if s is not None]
    if not segments:
        return {"imo": imo, "voyage_no": voyage_no, "source": source_id, "vessel": vessel_name,
                "skipped": "no steaming rows in any segment"}

    my_entire_dist = _sum_field(segments, "distance_nm", "entire")
    my_entire_time = _sum_field(segments, "time_h", "entire")
    my_good_dist = _sum_field(segments, "distance_nm", "good_wx")
    my_good_time = _sum_field(segments, "time_h", "good_wx")
    my_good_fo = _sum_field(segments, "fo_mt", "good_wx")
    my_good_dogo = _sum_field(segments, "dogo_mt", "good_wx")
    my_time_lost = sum(s["time_lost_h"] for s in segments)
    my_fuel_lost = sum(s["fuel_lost_mt"] for s in segments)
    cond = segments[0]["condition"]
    total_events = sum(s["events"] for s in segments)

    # Live API — the thing being checked, not the thing computing the answer.
    # A voyage_no reused across multiple real BOSP->EOSP passages comes back
    # as MULTIPLE result rows (one per segment_no) — sum ALL of them, not
    # just the first, to match the segment-summed total on our side.
    try:
        resp = session.get(f"{base_url}/cp/{imo}/performance",
                            params={"voyages": voyage_no, "source": source_id}, timeout=15)
        resp.raise_for_status()
        api_results = resp.json().get("results", [])
        api_rows = [r for r in api_results
                    if str(r.get("voyage_no")) == str(voyage_no) and not r.get("not_computable") and r.get("loss")]
    except requests.RequestException as e:
        return {"imo": imo, "voyage_no": voyage_no, "source": source_id, "vessel": vessel_name,
                "skipped": f"API call failed: {e}"}

    if not api_rows:
        return {"imo": imo, "voyage_no": voyage_no, "source": source_id, "vessel": vessel_name,
                "skipped": "API returned no computable result for this voyage"}

    api_entire_dist = _sum_field(api_rows, "distance_nm", "entire")
    api_entire_time = _sum_field(api_rows, "time_h", "entire")
    api_good_dist = _sum_field(api_rows, "distance_nm", "good_wx")
    api_good_time = _sum_field(api_rows, "time_h", "good_wx")
    api_good_fo = _sum_field(api_rows, "fo_mt", "good_wx")
    api_good_dogo = _sum_field(api_rows, "dogo_mt", "good_wx")
    api_time_lost = _sum_field(api_rows, "time_h", "loss")
    api_fuel_lost = _sum_field(api_rows, "fo_mt", "loss") + _sum_field(api_rows, "dogo_mt", "loss")

    diffs = []

    def _cmp(label, mine, theirs, tol):
        if mine is None or theirs is None:
            return
        d = abs(mine - theirs)
        if d > tol:
            diffs.append(f"{label}: mine={mine:.2f} api={theirs:.2f} (diff {d:.2f})")

    _cmp("entire.distance_nm", my_entire_dist, api_entire_dist, TOL_NM)
    _cmp("entire.time_h", my_entire_time, api_entire_time, TOL_HOURS)
    _cmp("good_wx.distance_nm", my_good_dist, api_good_dist, TOL_NM)
    _cmp("good_wx.time_h", my_good_time, api_good_time, TOL_HOURS)
    _cmp("good_wx.fo_mt", my_good_fo, api_good_fo, TOL_MT)
    _cmp("good_wx.dogo_mt", my_good_dogo, api_good_dogo, TOL_MT)
    _cmp("loss.time_h", my_time_lost, api_time_lost, TOL_HOURS)
    _cmp("loss.fo_mt+dogo_mt", my_fuel_lost, api_fuel_lost, TOL_MT)

    return {
        "imo": imo, "voyage_no": voyage_no, "source": source_id, "vessel": vessel_name,
        "condition": cond, "events": total_events, "segments": len(segments),
        "api_segments": len(api_rows), "diffs": diffs,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--imo", help="Check one vessel only")
    ap.add_argument("--all", action="store_true", help="Check every vessel")
    ap.add_argument("--source", choices=["wni", "mari_apps"], help="Restrict to one source")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1",
                     help="API base URL (default: local dev uvicorn on :8000)")
    args = ap.parse_args()

    if not args.imo and not args.all:
        ap.error("pass --imo <number> or --all")

    voyages = _discover_voyages(args.imo)
    if args.source:
        voyages = [v for v in voyages if v.source_id == args.source]

    session = requests.Session()
    total, skipped, mismatched = 0, 0, 0

    for v in voyages:
        total += 1
        result = _check_voyage(v.vessel_imo, v.Voyage_No, v.source_id, v.vessel_name, args.base_url, session)
        if result is None:
            total -= 1
            continue
        tag = f"{result['vessel']} ({result['imo']}) voyage {result['voyage_no']} [{result['source']}]"
        if "skipped" in result:
            skipped += 1
            print(f"SKIP    {tag} - {result['skipped']}")
        elif result["diffs"]:
            mismatched += 1
            print(f"MISMATCH {tag} ({result['condition']}, {result['events']} events, "
                  f"{result['segments']} segments mine / {result['api_segments']} api):")
            for d in result["diffs"]:
                print(f"          - {d}")
        else:
            print(f"OK      {tag} ({result['condition']}, {result['events']} events, {result['segments']} segments)")

    print(f"\n{total} voyages checked, {skipped} skipped, {mismatched} mismatched.")
    sys.exit(1 if mismatched else 0)


if __name__ == "__main__":
    main()
