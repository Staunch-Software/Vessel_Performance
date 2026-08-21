"""
Charter-Party compliance engine v2 — Phase 3a pilot (AM KIRTI + GCL FOS only)
==============================================================================
Implements the 12-step evaluation sequence from the client's own
"7. Perf. Evaluation Logic" sheet (CP_Description_Consolidated_Fleet_14Vessels.xlsx),
driven by the new cp_vessel_description / cp_sea_warranty / cp_warranty_conditions
tables (see import_cp_description.py) instead of the older vessel_cp_config.

Pure functions — no DB access — same style as backend/cp/cp_calculator.py.

Gated to a 2-vessel pilot (PILOT_VESSEL_IMOS) by api/routes/cp_compliance_routes.py
so the logic can be checked against real, partially messy data before fleet rollout.
See CLAUDE.md "Charter-Party Compliance v2 (Phase 3a pilot)" for the full write-up
of every approximation this module makes versus the client's literal spec, and why.

KNOWN APPROXIMATIONS vs. the 12-step spec (source data does not support these
steps as literally specified — each is called out again inline where it applies):

  1. Speed-mode selection (Eco vs Full): the spec says match on "Charterer's
     instructed speed mode", but analysis_data has no such field. We instead pick
     whichever CP_SEA_WARRANTY row (within the correct loading condition) has a
     warranted_speed_kn closest to the row's observed speed. This is a heuristic,
     not the literal rule — flag for the client if pilot results look wrong.
  2. Exclusion filter (step 2): the spec excludes canal/river/manoeuvring/drifting/
     awaiting-orders/tug-assistance events. analysis_data has no per-report canal/
     awaiting-orders/tug-assistance flag, so those still fall back to the steaming +
     distance-sanity filter (same one backend/cp/cp_calculator.py already uses) and
     are NOT reliably excluded. Passage-boundary/port-side reports ARE now excluded
     explicitly by event_type — BOSP, COSP, EOSP, Arrival Report, Departure Report,
     and Noon at port (see _NON_SEA_PASSAGE_EVENT_TYPES) — since those can carry a
     small non-zero Distance_nm/Duration_h (a maneuvering/approach fragment) that
     used to slip past the distance/duration check alone and get judged on a
     non-representative low-speed fragment.
  3. Good-weather filter (step 3): uses BF_Wind <= weather_max_bf AND
     Sig_Wave_Ht_m <= max_swell_m as a proxy for "Douglas Sea State <= X AND swell
     <= Y" (no separate DSS field exists in analysis_data). Adverse-current
     exclusion is NOT enforced — Current_Spd_kn has no direction-relative-to-course
     data, so "adverse" cannot be determined; this is a real data gap.
  4. Fuel-grade split (step 9): CP consumption warranties are per fuel grade, but
     ME_FOC_MT / AE_FOC_MT in analysis_data are NOT split by grade. Observed
     consumption is compared against the warranty's total_cons_mt_day as one figure.
  5. Hull & propeller check (step 10) and claim quantification (step 11): both
     require data not present anywhere in the system yet — last_drydock_date
     (not populated by the Phase 1 load; none of the 14 source files had it) and
     a daily hire rate / bunker price (no such config exists). Both return None
     with an explicit note rather than a fabricated number.
  6. Exception reporting (step 12): the literal rule needs day-level granularity
     ("excess consumption > 5% for 30 consecutive days"); our aggregation is
     per-voyage. We approximate with "voyage excess > 0 AND voyage spans >= 30
     qualifying days" — a coarser proxy pending day-level tracking.
"""

from collections import OrderedDict

# Only these two vessels are evaluated in Phase 3a. Enforced again at the route
# layer (403 for any other IMO) — kept here too so this module is safe to call
# directly (e.g. from a script or a future workflow) without bypassing the gate.
PILOT_VESSEL_IMOS = {"9832925", "9532082"}  # AM KIRTI (clean pilot), GCL FOS (messy pilot)

DIST_CHECK_TOL_PCT = 25.0  # same tolerance as cp_calculator._distance_ok


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _is_steaming(r):
    d, h = _num(r.get("Distance_nm")), _num(r.get("Duration_h"))
    return d is not None and d > 0 and h is not None and h > 0


# Report types that mark a passage boundary or port-side operation, not a day of actual
# sea steaming — explicitly requested to be kept out of speed/fuel compliance judgment.
# BOSP/COSP mark departure, EOSP marks arrival, Arrival/Departure Report are the port-call
# bookends, and "Noon at port" is by definition not steaming. These are the same normalized
# labels WNI/MariApps/manual-Excel imports all share (see
# backend/excel_processing/tufmax_parser.py's TUFMAX_REPORT_TYPE_MAP) — a report can carry
# one of these event types while still having a small non-zero Distance_nm/Duration_h (a
# maneuvering/approach fragment), which is exactly what let it slip past the plain
# steaming check before and get judged on a non-representative low-speed fragment.
_NON_SEA_PASSAGE_EVENT_TYPES = {
    "BOSP", "COSP", "EOSP", "ARRIVAL REPORT", "DEPARTURE REPORT", "NOON AT PORT",
}


def _is_sea_passage_event(r):
    et = str(r.get("event_type") or "").strip().upper()
    return et not in _NON_SEA_PASSAGE_EVENT_TYPES


def _distance_ok(r):
    d, h, s = _num(r.get("Distance_nm")), _num(r.get("Duration_h")), _num(r.get("SOG_kn"))
    if d is None or h is None or s is None or h <= 0 or s <= 0:
        return True
    implied = s * h
    if implied <= 0:
        return True
    return abs(d - implied) <= (DIST_CHECK_TOL_PCT / 100.0) * implied


def _normalize_loading_cond(raw):
    lc = str(raw or "").strip().lower()
    if lc.startswith("l"):
        return "Laden"
    if lc.startswith("b"):
        return "Ballast"
    return None


def _pick_sea_warranty(candidates, observed_speed):
    """Nearest-warranted-speed heuristic — see module docstring, approximation #1."""
    if not candidates:
        return None
    if observed_speed is None:
        return candidates[0]
    return min(candidates, key=lambda w: abs((_num(w.get("warranted_speed_kn")) or 0) - observed_speed))


def _is_good_weather(row, conditions):
    bf = _num(row.get("BF_Wind"))
    hs = _num(row.get("Sig_Wave_Ht_m"))
    max_bf = conditions.get("weather_max_bf")
    max_swell = conditions.get("max_swell_m")
    if bf is None or hs is None or max_bf is None or max_swell is None:
        return False
    return bf <= max_bf and hs <= max_swell


def _group_consecutive_good_weather_runs(ordered_rows, conditions):
    """
    ordered_rows must be date-sorted, chronologically-adjacent reports (e.g. one
    voyage's rows matched to one warranty record). Returns runs of CONSECUTIVE
    good-weather rows — a run breaks as soon as an intervening row (of any kind)
    fails the good-weather test, so filtering the list first and grouping second
    would wrongly treat non-adjacent good-weather rows as one continuous period.
    """
    runs, cur = [], []
    for r in ordered_rows:
        if _is_good_weather(r, conditions):
            cur.append(r)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def _daily_breakdown(rows, conditions, speed_threshold, cons_threshold, qualifying_ids):
    """
    Per-report pass/fail detail. Each entry is judged independently against the SAME
    matched-warranty thresholds as the voyage aggregate — no minimum-period smoothing.
    `qualifying_ids` marks which rows also contributed to the official voyage-level
    aggregate (id()-based membership check against the qualifying_rows list).

    Status: 'Excluded (weather)' if the report itself isn't good-weather (a per-day
    verdict can't be judged fairly outside the CP's own good-weather clause); otherwise
    'Compliant' / 'Non-compliant' against the voyage's matched warranty thresholds.
    """
    out = []
    for r in rows:
        hours = _num(r.get("Duration_h")) or 0
        dist = _num(r.get("Distance_nm")) or 0
        me = _num(r.get("ME_FOC_MT")) or 0
        ae = _num(r.get("AE_FOC_MT")) or 0
        good_wx = _is_good_weather(r, conditions)
        obs_speed = round(dist / hours, 2) if hours else None
        obs_cons = round((me + ae) / (hours / 24), 2) if hours else None

        shortfall = excess = None
        status = "Excluded (weather)"
        if good_wx:
            if speed_threshold is not None and obs_speed is not None:
                shortfall = round(max(0.0, speed_threshold - obs_speed), 2)
            if cons_threshold is not None and obs_cons is not None:
                excess = round(max(0.0, obs_cons - cons_threshold), 2)
            if shortfall is None and excess is None:
                status = "Not evaluable"
            else:
                status = "Non-compliant" if (shortfall or excess) else "Compliant"

        out.append({
            "date": str(r.get("Date") or ""),
            "distance_nm": round(dist, 1) if dist else dist,
            "duration_h": round(hours, 1) if hours else hours,
            "bf_wind": _num(r.get("BF_Wind")),
            "sig_wave_ht_m": _num(r.get("Sig_Wave_Ht_m")),
            "observed_speed_kn": obs_speed,
            "observed_cons_mtpd": obs_cons,
            "good_weather": good_wx,
            "in_qualifying_period": id(r) in qualifying_ids,
            "speed_shortfall_kn": shortfall,
            "excess_cons_mtpd": excess,
            "status": status,
        })
    return out


def _aggregate(rows):
    dist = sum(_num(r.get("Distance_nm")) or 0 for r in rows)
    hours = sum(_num(r.get("Duration_h")) or 0 for r in rows)
    me = sum(_num(r.get("ME_FOC_MT")) or 0 for r in rows)
    ae = sum(_num(r.get("AE_FOC_MT")) or 0 for r in rows)
    days = hours / 24.0 if hours else 0.0
    return {
        "report_count": len(rows),
        "distance_nm": round(dist, 1),
        "steaming_h": round(hours, 1),
        "days": round(days, 2),
        "observed_speed_kn": round(dist / hours, 2) if hours else None,
        "me_mtpd": round(me / days, 2) if days else None,
        "ae_mtpd": round(ae / days, 2) if days else None,
        "total_mtpd": round((me + ae) / days, 2) if days else None,
    }


def evaluate_voyage(voyage_no, rows, sea_warranty_rows, conditions):
    """
    Runs steps 1-9 + 12(partial) of the client's calculation sequence for one voyage.
    `rows` = analysis_data dicts for this voyage, any order.
    `sea_warranty_rows` = list of cp_sea_warranty dicts (all 4 for the vessel's CP fixture).
    `conditions` = cp_warranty_conditions dict.
    """
    rows = sorted(rows, key=lambda r: str(r.get("Date") or ""))
    steaming = [r for r in rows if _is_steaming(r) and _distance_ok(r) and _is_sea_passage_event(r)]

    result = {
        "voyage_no": voyage_no,
        "source": rows[0].get("source_id") if rows else None,
        "report_count": len(rows),
        "steaming_count": len(steaming),
        "unmatched_count": 0,
        "loading_cond": None,
        "matched_warranty": None,
        "good_weather_count": 0,
        "qualifying_count": 0,
        "observed": None,
        "thresholds": None,
        "speed_shortfall_kn": None,
        "time_lost_gained_h": None,
        "excess_cons_mt": None,
        "hull_prop_flag": "Not evaluable — last_drydock_date not populated in source data.",
        "claim_value_usd": "Not evaluable — no daily hire rate / bunker price configured.",
        "notes": [],
        "daily": [],
    }
    if not steaming:
        result["notes"].append("No steaming reports in this voyage.")
        return result

    # Step 1: select applicable warranty record (per-row nearest-speed match within loading cond)
    matched_rows = []
    for r in steaming:
        cond = _normalize_loading_cond(r.get("Loading_Cond"))
        cand = [w for w in sea_warranty_rows if w.get("loading_condition") == cond] if cond else []
        w = _pick_sea_warranty(cand, _num(r.get("STW_kn")) or _num(r.get("SOG_kn")))
        if w is None:
            result["unmatched_count"] += 1
            continue
        matched_rows.append((r, cond, w))

    if not matched_rows:
        result["notes"].append("No report matched a CP_SEA_WARRANTY record — excluded ('Unmatched').")
        return result

    # Dominant loading condition + dominant matched warranty row for this voyage
    cond_counts = {}
    for _, cond, _w in matched_rows:
        cond_counts[cond] = cond_counts.get(cond, 0) + 1
    dominant_cond = max(cond_counts, key=cond_counts.get)

    w_counts = {}
    for _, cond, w in matched_rows:
        if cond == dominant_cond:
            w_counts[w["id"]] = w_counts.get(w["id"], 0) + 1
    dominant_w_id = max(w_counts, key=w_counts.get)
    warranty = next(w for _, _, w in matched_rows if w["id"] == dominant_w_id)

    result["loading_cond"] = dominant_cond
    result["matched_warranty"] = {
        "id": warranty["id"], "loading_condition": warranty["loading_condition"],
        "speed_mode": warranty["speed_mode"], "warranted_speed_kn": warranty.get("warranted_speed_kn"),
        "total_cons_mt_day": warranty.get("total_cons_mt_day"),
    }

    # Step 2 (approximated) + Step 3: good-weather filter, restricted to rows matched to the dominant warranty.
    # dominant_rows stays in chronological order so runs are detected against true report adjacency.
    dominant_rows = [r for r, cond, w in matched_rows if cond == dominant_cond and w["id"] == dominant_w_id]
    result["good_weather_count"] = sum(1 for r in dominant_rows if _is_good_weather(r, conditions))

    # Step 6: warranty tolerance thresholds (computed before the qualifying-period test so the
    # daily breakdown below can use them even for voyages with no qualifying aggregate period).
    about = warranty.get("about_clause", True)
    w_speed = _num(warranty.get("warranted_speed_kn"))
    tol_kn = _num(warranty.get("speed_tolerance_kn")) or 0.0
    speed_threshold = (w_speed - tol_kn) if (about and w_speed is not None) else w_speed

    w_cons = _num(warranty.get("total_cons_mt_day"))
    tol_pct = _num(warranty.get("cons_tolerance_pct")) or 0.0
    cons_threshold = (w_cons * (1 + tol_pct / 100.0)) if (about and w_cons is not None) else w_cons

    result["thresholds"] = {
        "speed_threshold_kn": round(speed_threshold, 2) if speed_threshold is not None else None,
        "cons_threshold_mtpd": round(cons_threshold, 2) if cons_threshold is not None else None,
    }

    # Step 4: minimum continuous good-weather period test
    min_hrs = conditions.get("min_good_weather_hrs") or 24
    runs = _group_consecutive_good_weather_runs(dominant_rows, conditions)
    qualifying_rows = []
    for run in runs:
        if sum(_num(r.get("Duration_h")) or 0 for r in run) >= min_hrs:
            qualifying_rows.extend(run)
    result["qualifying_count"] = len(qualifying_rows)

    # Daily breakdown — one entry PER REPORT, each with its own pass/fail verdict against the
    # same matched-warranty thresholds as the voyage aggregate above. Requested explicitly as a
    # daily view; note this is noisier than the voyage-level verdict, which the client's own
    # spec deliberately aggregates over a >=min_good_weather_hrs period to avoid single-day noise
    # (a maneuvering hour, a partial-day report, etc.) reading as a false breach.
    qualifying_ids = {id(r) for r in qualifying_rows}
    result["daily"] = _daily_breakdown(dominant_rows, conditions, speed_threshold, cons_threshold, qualifying_ids)

    if not qualifying_rows:
        result["notes"].append(
            f"No qualifying good-weather period >= {min_hrs}h — voyage-level compliance not computable "
            "(see the daily breakdown for individual report detail)."
        )
        return result

    # Step 5: observed performance (weighted across qualifying periods)
    observed = _aggregate(qualifying_rows)
    result["observed"] = observed

    # Step 7: speed shortfall
    obs_speed = observed["observed_speed_kn"]
    if speed_threshold is not None and obs_speed is not None:
        result["speed_shortfall_kn"] = round(max(0.0, speed_threshold - obs_speed), 2)

    # Step 8: time lost / gained, over the qualifying distance
    if w_speed and obs_speed and observed["distance_nm"]:
        dist = observed["distance_nm"]
        result["time_lost_gained_h"] = round(dist / obs_speed - dist / w_speed, 2)

    # Step 9: over-consumption (approximation #4 — not split by fuel grade)
    obs_cons = observed["total_mtpd"]
    if cons_threshold is not None and obs_cons is not None and observed["days"]:
        result["excess_cons_mt"] = round(max(0.0, obs_cons - cons_threshold) * observed["days"], 2)

    if result["unmatched_count"]:
        result["notes"].append(f"{result['unmatched_count']} report(s) unmatched to any CP_SEA_WARRANTY record.")

    return result


def evaluate_vessel(header, sea_warranty_rows, conditions, analysis_rows):
    """
    Full Phase-3a pilot evaluation for one vessel.
    Returns {voyages: [...], exceptions: [...]} — see module docstring for the
    12-step spec and every approximation this makes against it.

    NOTE: WNI and MariApps use different Voyage_No numbering schemes for the
    same vessel (e.g. WNI "35" vs MariApps "AM KIRTI V 35/01"). Grouping and the
    "consecutive voyages" exception check (step 12) are done PER SOURCE so a
    streak is never computed across two unrelated numbering systems.
    """
    by_source = OrderedDict()
    for r in analysis_rows:
        by_source.setdefault(r.get("source_id"), []).append(r)

    voyages = []
    exceptions = []
    for src, src_rows in by_source.items():
        by_voyage = OrderedDict()
        for r in src_rows:
            by_voyage.setdefault(r.get("Voyage_No"), []).append(r)

        src_voyages = [evaluate_voyage(v, rows, sea_warranty_rows, conditions) for v, rows in by_voyage.items()]

        def _key(v):
            try:
                return (0, float(v["voyage_no"]))
            except (TypeError, ValueError):
                return (1, str(v["voyage_no"]))
        src_voyages.sort(key=_key)

        # Step 12 (approximated — see module docstring #6): exception reporting, per source
        consecutive_shortfall = 0
        for v in src_voyages:
            if v.get("speed_shortfall_kn") and v["speed_shortfall_kn"] > 0:
                consecutive_shortfall += 1
            else:
                consecutive_shortfall = 0
            if consecutive_shortfall >= 2:
                exceptions.append({
                    "type": "speed_shortfall_streak",
                    "source": src,
                    "voyage_no": v["voyage_no"],
                    "detail": f"Speed shortfall > 0 for {consecutive_shortfall} consecutive voyages ({src}).",
                })
            if v.get("excess_cons_mt") and v["excess_cons_mt"] > 0 and v.get("observed", {}).get("days", 0) >= 30:
                exceptions.append({
                    "type": "excess_consumption_30d_proxy",
                    "source": src,
                    "voyage_no": v["voyage_no"],
                    "detail": (
                        f"Excess consumption {v['excess_cons_mt']} mt over a {v['observed']['days']}-day voyage "
                        "(proxy for the spec's '30 consecutive days' rule — see module docstring #6)."
                    ),
                })

        voyages.extend(src_voyages)

    return {"vessel_imo": header.get("vessel_imo"), "voyages": voyages, "exceptions": exceptions}
