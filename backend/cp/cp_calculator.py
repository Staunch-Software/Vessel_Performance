"""
Charter-Party (CP) performance calculator
==========================================
Pure functions — no DB access. Given a list of analysis_data rows (dicts) for a
vessel and the CP warranty config per loading condition, produce a per-voyage
summary with:

  - All-weather aggregate   (every steaming row)
  - Fair-weather aggregate  (WNI parity: BF_Wind <= 4 AND Sig_Wave_Ht_m <= 3.0)
  - CP compliance           (fair-weather speed / ME / AE vs warranty ± tolerance)
  - Time lost / gained       (h, over the voyage distance)
  - Fuel over / under         (MT, ME and AE separately)

Fair-weather thresholds are FIXED to match what WNI applies for CP audits
(good weather = up to Beaufort 4 and significant wave height up to 3.0 m).

Each row is expected to expose these analysis_data keys (None-safe):
  Voyage_No, Loading_Cond, Date, Distance_nm, Duration_h, SOG_kn, STW_kn,
  ME_FOC_MT, AE_FOC_MT, BF_Wind, Sig_Wave_Ht_m, source_id, Record_ID
"""

import re
from collections import OrderedDict

from backend.cp.cp_compliance_v2 import _pick_sea_warranty

# Fixed fair-weather definition (WNI charter-party "good weather day")
FAIR_BF_MAX        = 4.0     # Beaufort wind force
FAIR_WAVE_MAX_M    = 3.0     # significant wave height (m)
GW_MIN_SAMPLE_PCT  = 5.0     # min fair-weather share of steaming time to be representative
DIST_CHECK_TOL_PCT = 25.0    # flag a row if |distance - SOG*hours| exceeds this % of SOG*hours


# ── helpers ─────────────────────────────────────────────────────────────────────

def _num(v):
    """Coerce to float or return None (treats '', None, non-numeric as None)."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _is_steaming(r):
    d = _num(r.get("Distance_nm"))
    h = _num(r.get("Duration_h"))
    return d is not None and d > 0 and h is not None and h > 0


def _distance_ok(r):
    """True if reported distance ~ SOG x hours (rejects garbage like 24 nm @ 13.9 kn)."""
    d = _num(r.get("Distance_nm"))
    h = _num(r.get("Duration_h"))
    s = _num(r.get("SOG_kn"))
    if d is None or h is None or s is None or h <= 0 or s <= 0:
        return True  # can't check → don't penalise
    implied = s * h
    if implied <= 0:
        return True
    return abs(d - implied) <= (DIST_CHECK_TOL_PCT / 100.0) * implied


def _is_fair_weather(r):
    """WNI good-weather: BF <= 4 AND Hs <= 3.0. Missing just one criterion → not
    fair (can't verify). Missing BOTH → treat as good weather (approved by
    client 2026-08) rather than penalise a voyage for a logging gap."""
    bf = _num(r.get("BF_Wind"))
    hs = _num(r.get("Sig_Wave_Ht_m"))
    if bf is None and hs is None:
        return True
    if bf is None or hs is None:
        return False
    return bf <= FAIR_BF_MAX and hs <= FAIR_WAVE_MAX_M


def _dominant_condition(rows):
    """Pick 'Laden'/'Ballast' by majority of rows (CP warranty differs by condition)."""
    counts = {"Laden": 0, "Ballast": 0}
    for r in rows:
        lc = str(r.get("Loading_Cond") or "").strip().lower()
        if lc.startswith("l"):
            counts["Laden"] += 1
        elif lc.startswith("b"):
            counts["Ballast"] += 1
    return "Laden" if counts["Laden"] >= counts["Ballast"] else "Ballast"


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _aggregate(rows):
    """Sum cumulative quantities, average rates. Returns a summary dict."""
    dist  = sum(_num(r.get("Distance_nm")) or 0 for r in rows)
    hours = sum(_num(r.get("Duration_h")) or 0 for r in rows)
    me    = sum(_num(r.get("ME_FOC_MT")) or 0 for r in rows)
    ae    = sum(_num(r.get("AE_FOC_MT")) or 0 for r in rows)
    days  = hours / 24.0 if hours else 0.0

    return {
        "report_count":  len(rows),
        "distance_nm":   round(dist, 1),
        "steaming_h":    round(hours, 1),
        "steaming_days": round(days, 2),
        "avg_speed_kn":  round(dist / hours, 2) if hours else None,   # speed made good
        "avg_sog_kn":    _round(_mean([_num(r.get("SOG_kn")) for r in rows]), 2),
        "avg_stw_kn":    _round(_mean([_num(r.get("STW_kn")) for r in rows]), 2),
        "me_total_mt":   round(me, 2),
        "ae_total_mt":   round(ae, 2),
        "me_mtpd":       round(me / days, 2) if days else None,
        "ae_mtpd":       round(ae / days, 2) if days else None,
    }


def _round(v, n):
    return round(v, n) if v is not None else None


# ── per-voyage computation ────────────────────────────────────────────────────

def _compute_voyage(voyage_no, rows, cp_by_cond):
    # Keep only steaming rows with sane distance; count what we drop.
    steaming = [r for r in rows if _is_steaming(r)]
    valid    = [r for r in steaming if _distance_ok(r)]
    suspect  = len(steaming) - len(valid)

    all_w     = _aggregate(valid)
    fair_rows = [r for r in valid if _is_fair_weather(r)]
    fair      = _aggregate(fair_rows)

    fair_pct = (round(fair["steaming_h"] / all_w["steaming_h"] * 100, 1)
                if all_w["steaming_h"] else 0.0)

    cond = _dominant_condition(valid or rows)
    cfg  = cp_by_cond.get(cond)

    result = {
        "voyage_no":            voyage_no,
        "loading_cond":         cond,
        "source":              (rows[0].get("source_id") if rows else None),
        "all_weather":          all_w,
        "fair_weather":         fair,
        "fair_weather_pct":     fair_pct,
        "sample_sufficient":    fair_pct >= GW_MIN_SAMPLE_PCT,
        "suspect_distance_rows": suspect,
        "warranty":             None,
        "compliance":           None,
        "time_lost_gained_h":   None,
        "me_over_under_mt":     None,
        "ae_over_under_mt":     None,
        "notes":                [],
    }

    if suspect:
        result["notes"].append(
            f"{suspect} row(s) excluded: reported distance inconsistent with SOG x hours."
        )

    if not cfg:
        result["notes"].append(f"No CP warranty configured for {cond}.")
        return result
    if not fair_rows:
        result["notes"].append("No fair-weather records — CP metrics not computable.")
        result["warranty"] = _warranty_view(cfg)
        return result
    if not result["sample_sufficient"]:
        result["notes"].append(
            f"Fair-weather sample {fair_pct}% < {GW_MIN_SAMPLE_PCT}% — result not representative."
        )

    w_speed = _num(cfg.get("warranted_speed_kn"))
    w_me    = _num(cfg.get("warranted_me_mtpd"))
    w_ae    = _num(cfg.get("warranted_ae_mtpd"))
    tol_kn  = _num(cfg.get("speed_tol_kn")) or 0.0
    tol_pct = _num(cfg.get("cons_tol_pct")) or 0.0

    result["warranty"] = _warranty_view(cfg)

    fair_speed = fair["avg_speed_kn"]
    fair_me    = fair["me_mtpd"]
    fair_ae    = fair["ae_mtpd"]
    voyage_days = all_w["steaming_days"]
    total_dist  = all_w["distance_nm"]

    # Compliance (pass = within the "about" band)
    result["compliance"] = {
        "speed": _pass_speed(fair_speed, w_speed, tol_kn),
        "me":    _pass_cons(fair_me, w_me, tol_pct),
        "ae":    _pass_cons(fair_ae, w_ae, tol_pct),
    }

    # Time lost (+) / gained (-): actual good-weather time minus warranted time over
    # the voyage distance. Faster-than-warranted → negative (time gained/saved).
    if w_speed and fair_speed and total_dist:
        result["time_lost_gained_h"] = round(
            total_dist / fair_speed - total_dist / w_speed, 2
        )

    # Fuel over (+) / under (-) consumption, ME and AE separately
    if w_me is not None and fair_me is not None and voyage_days:
        result["me_over_under_mt"] = round((fair_me - w_me) * voyage_days, 2)
    if w_ae is not None and fair_ae is not None and voyage_days:
        result["ae_over_under_mt"] = round((fair_ae - w_ae) * voyage_days, 2)

    return result


def _warranty_view(cfg):
    return {
        "warranted_speed_kn": _num(cfg.get("warranted_speed_kn")),
        "warranted_me_mtpd":  _num(cfg.get("warranted_me_mtpd")),
        "warranted_ae_mtpd":  _num(cfg.get("warranted_ae_mtpd")),
        "speed_tol_kn":       _num(cfg.get("speed_tol_kn")),
        "cons_tol_pct":       _num(cfg.get("cons_tol_pct")),
    }


def _pass_speed(actual, warranted, tol_kn):
    if actual is None or warranted is None:
        return {"actual": actual, "warranted": warranted, "pass": None}
    return {
        "actual": actual,
        "warranted": warranted,
        "pass": actual >= warranted - tol_kn,
    }


def _pass_cons(actual, warranted, tol_pct):
    if actual is None or warranted is None:
        return {"actual": actual, "warranted": warranted, "pass": None}
    return {
        "actual": actual,
        "warranted": warranted,
        "pass": actual <= warranted * (1 + tol_pct / 100.0),
    }


# ── public entry point ──────────────────────────────────────────────────────────

def compute_cp_performance(rows, cp_by_cond):
    """
    rows       : list of analysis_data dicts (one vessel, one source)
    cp_by_cond : {"Laden": {...warranty...}, "Ballast": {...warranty...}}

    Returns a list of per-voyage result dicts, ordered by voyage number.
    """
    by_voyage = OrderedDict()
    for r in rows:
        v = r.get("Voyage_No")
        by_voyage.setdefault(v, []).append(r)

    results = []
    for voyage_no, vrows in by_voyage.items():
        results.append(_compute_voyage(voyage_no, vrows, cp_by_cond or {}))

    # Stable order: numeric voyage if possible, else string
    def _key(res):
        try:
            return (0, float(res["voyage_no"]))
        except (TypeError, ValueError):
            return (1, str(res["voyage_no"]))

    results.sort(key=_key)
    return results


# ============================================================================
# WNI SeaNavigator "CP Performance" segment table
# ============================================================================
# Each row = a voyage segment (a contiguous run of reports with the same
# destination port). Every analytic cell carries TWO figures:
#   good_wx  = fair-weather subset (BF<=4 & Hs<=3.0)
#   entire   = all steaming rows
# Consumption is split by fuel TYPE: FO (HFO/LFO) and DO/GO (distillate).
# Rows are expected to also expose: From_Port, To_Port, fo_mt, dogo_mt,
# Current_Spd_kn  (in addition to the keys used above).

GW_WIND   = "BF 4"
GW_SEA    = "Sig.Wave 3.0m"
GW_CURRENT = "NoAdv"
GW_RATIO  = 50          # good-weather ratio threshold (%)


def _reclassified_fo(hfo_raw, go_raw, go_allowance):
    """Reclassifies GO into the FO comparison figure using that day's own
    CP-remarks GO allowance (manager methodology 2026-09): in rough weather
    a vessel may be forced to burn GO in place of its normal fuel, so for
    FO-warranty comparison/display purposes that GO needs folding into the
    FO figure. Deliberately ADDITIVE, not a bucket-move — GO's own separate
    consumption (fo_mt/dogo_mt above) is untouched; only this figure gains
    the amount. Ported 2026-09 from voyagePdfExport.js's reclassifiedFO() —
    this now lives in exactly one place, read by both the PDF report and the
    live table (client request), instead of being recomputed independently
    in the frontend.
      a = that day's CP-remarks GO allowance (0 if none — explicit fallback,
          not the standing GO warranty)
      b = that day's actual raw GO consumption
      b - a > 0  -> add the EXCESS (b - a) to that day's FO figure
      b - a <= 0 -> add the FULL raw GO amount (b) to that day's FO figure
    """
    a = go_allowance if go_allowance is not None else 0
    excess = go_raw - a
    return hfo_raw + (excess if excess > 0 else go_raw)


def _sum_fo_reclassified(rows):
    total = 0.0
    for r in rows:
        hfo = _num(r.get("fo_mt")) or 0
        go = _num(r.get("dogo_mt")) or 0
        instr = r.get("cp_instruction") or {}
        total += _reclassified_fo(hfo, go, instr.get("go_mt_day"))
    return round(total, 2)


def _agg_wni(rows):
    dist  = sum(_num(r.get("Distance_nm")) or 0 for r in rows)
    hours = sum(_num(r.get("Duration_h")) or 0 for r in rows)
    fo    = sum(_num(r.get("fo_mt")) or 0 for r in rows)
    dogo  = sum(_num(r.get("dogo_mt")) or 0 for r in rows)
    days  = hours / 24.0 if hours else 0.0
    return {
        "time_h":         round(hours, 2),
        "distance_nm":    round(dist, 1),
        "avg_speed_kn":   round(dist / hours, 2) if hours else None,
        "current_factor_kn": _round(_mean([_num(r.get("Current_Spd_kn")) for r in rows]), 2),
        "fo_mt":          round(fo, 2),
        "dogo_mt":        round(dogo, 2),
        # Display-only reclassified FO (see _reclassified_fo's doc comment) —
        # NOT used for any verdict/comparison (that's the combined d_tot/
        # e_tot/f_tot in "detail", built from raw fo_mt+dogo_mt to avoid
        # double-counting GO — see that comment in compute_cp_voyage_table).
        "fo_reclassified_mt": _sum_fo_reclassified(rows),
        "daily_fo":       round(fo / days, 2) if days else None,
        "daily_dogo":     round(dogo / days, 2) if days else None,
        "days":           round(days, 2),
    }


def _segments(vrows):
    """Split a voyage's (date-ordered) rows into segments at real BOSP→EOSP
    passages — NOT whenever the daily destination-port label changes, and NOT
    on every single EOSP-tagged row by itself. The destination label on a
    "Noon at sea" report can be corrected mid-passage before the ship has
    actually arrived anywhere (a diverted/re-routed voyage), which used to
    create a fake extra segment for a port the vessel never called at.

    A segment only closes when a NEW BOSP (departure) shows up after it has
    already seen at least one EOSP — not the moment any EOSP appears. This
    absorbs the case where the same real arrival gets logged with more than
    one EOSP-tagged row (e.g. a corrected/re-submitted arrival report) with no
    genuine departure in between: they all stay in the same segment instead of
    each one starting a fresh (spurious, near-duplicate) segment. Within a
    segment, compute_cp_voyage_table already picks the LAST EOSP row for the
    arrival_port/ata, so the corrected/final arrival naturally wins.

    The caller (cp_routes._rows_for_source) already trims off any trailing
    rows past the last EOSP (an unfinished/ongoing next leg), so every row set
    handed to compute_cp_voyage_table ends on a real EOSP.
    """
    segs, cur = [], []
    seen_eosp = False
    for r in vrows:
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


# ── event-wise CP-remarks-aware calculation (client request 2026-09) ────────
# Ported from the PDF Voyage Audit Report's own frontend calculation
# (voyagePdfExport.js: eventWiseCpRows/eventCpFigures/computeEventWiseCp) so
# the live Logbook+ table and the PDF report reach the SAME conclusion for
# the same voyage, instead of the live table's older single-standing-rate
# extrapolation (which had no awareness of a day's own CP remarks override,
# and judged FO/DOGO as two fully independent verdicts against warranty
# rates that can be wrong when a vessel's GO warranty was never properly
# populated — see cp_routes.py's AE-fuel-grade fix).
#
# DOGO no longer gets its own independent Loss/Saving verdict here (manager
# instruction 2026-09, matching the PDF's cover-page GO box): GO consumption
# is judged only as part of the COMBINED FO+GO total below, so `dogo_mt` in
# the returned `loss` dict is always None now.

def _event_wise_rows(seg):
    """Excludes the COSP/BOSP boundary row itself, keeping every event from
    the next report through EOSP inclusive — matches eventWiseCpRows()."""
    return [r for r in seg if not re.search(r"COSP|BOSP", r.get("event_type") or "", re.IGNORECASE)]


def _event_cp_figures(row, w_spd, w_fo, w_dogo):
    """Resolves the CP speed/FO/GO that actually applied on ONE event/day:
    that day's parsed CP remarks instruction (cp_instruction, attached by
    cp_routes._rows_for_source) if one exists, otherwise the vessel's
    standing CP warranty — matches eventCpFigures()."""
    instr = row.get("cp_instruction") or {}
    speed = instr.get("speed_kn")
    fo    = instr.get("total_mt_day")
    go    = instr.get("go_mt_day")
    return (
        speed if speed is not None else (w_spd or 0),
        fo if fo is not None else (w_fo or 0),
        go if go is not None else (w_dogo or 0),
    )


def _event_wise_cp(seg, w_spd, w_fo, w_dogo, tol_kn, tol_pct):
    """Cumulative event-wise Time-at-Warranted-Speed (b_h/c_h) and combined
    Max/Min Warranted Consumption (e_tot/f_tot), using whichever CP
    instruction actually applied each day — matches computeEventWiseCp()."""
    rows = _event_wise_rows(seg)
    b_h = c_h = e_tot = f_tot = 0.0
    event_count = 0
    for r in rows:
        dist = _num(r.get("Distance_nm")) or 0
        speed, fo, go = _event_cp_figures(r, w_spd, w_fo, w_dogo)
        if dist <= 0 or not speed:
            continue
        event_count += 1
        eff_spd   = speed - tol_kn
        total_max = (fo + go) * (1 + tol_pct / 100.0)
        total_min = (fo + go) * (1 - tol_pct / 100.0)
        c_h   += dist / speed
        f_tot += (dist / speed) * (total_min / 24.0)
        if eff_spd > 0:
            b_h   += dist / eff_spd
            e_tot += (dist / eff_spd) * (total_max / 24.0)
    return {"b_h": b_h, "c_h": c_h, "e_tot": e_tot, "f_tot": f_tot, "event_count": event_count}


def compute_cp_voyage_table(rows, cp_by_cond):
    """
    Return WNI-style per-segment rows for the selected voyage(s).

    `cp_by_cond`: {"Laden": [warranty_dict, ...], "Ballast": [warranty_dict, ...]} —
    a LIST of candidate warranty records per loading condition (e.g. Eco + Full),
    not a single fixed dict. Each segment picks whichever candidate's
    warranted_speed_kn is nearest to its observed speed (see _pick_sea_warranty),
    so a segment sailed at Full speed is compared against the Full warranty, not
    forced against a single collapsed figure. Each dict needs: warranted_speed_kn,
    warranted_fo_mtpd, warranted_dogo_mtpd, speed_tol_kn, cons_tol_pct.

    Each result's `loss.fo_mt` is the COMBINED FO+GO Total Fuel Loss(+)/
    Saving(-) (see _event_wise_cp()); `loss.dogo_mt` is always None — GO no
    longer gets an independent verdict, per manager instruction 2026-09
    (matches the PDF report's cover-page GO box).
    """
    by_voyage = OrderedDict()
    for r in rows:
        by_voyage.setdefault(r.get("Voyage_No"), []).append(r)

    out = []
    for voyage_no, vrows in by_voyage.items():
        vrows = sorted(vrows, key=lambda r: str(r.get("Date") or ""))
        for seg_no, seg in enumerate(_segments(vrows), start=1):
            # No _distance_ok() sanity filter here (removed 2026-09) — the
            # PDF report's own frontend calculation never applied one, and
            # this table dropping a row the PDF kept (found via a real
            # voyage's EOSP row: 15nm/1h vs its instantaneous SOG, a ~30%
            # mismatch typical of a short partial-day boundary segment, not
            # actual garbage data) was producing a "close but not exact"
            # mismatch between the two — the same class of drift this whole
            # unification effort exists to eliminate. _is_steaming() alone
            # (positive distance AND duration) still applies, matching the
            # PDF's own dist<=0 guards.
            steaming = [r for r in seg if _is_steaming(r)]
            if not steaming:
                continue
            fair = [r for r in steaming if _is_fair_weather(r)]
            entire  = _agg_wni(steaming)
            good_wx = _agg_wni(fair)

            cond = _dominant_condition(steaming)
            candidates = cp_by_cond.get(cond) or []
            observed_speed_for_match = good_wx["avg_speed_kn"] or entire["avg_speed_kn"]
            cfg = _pick_sea_warranty(candidates, observed_speed_for_match) or {}
            w_spd  = _num(cfg.get("warranted_speed_kn"))
            w_fo   = _num(cfg.get("warranted_fo_mtpd"))
            w_dogo = _num(cfg.get("warranted_dogo_mtpd"))
            tol_kn  = _num(cfg.get("speed_tol_kn"))  or 0.0
            tol_pct = _num(cfg.get("cons_tol_pct")) or 0.0

            # Event-wise (client request 2026-09) — see _event_wise_cp()'s doc
            # comment. Time Lost/Gained now uses cumulative per-event b_h/c_h
            # (whichever CP instruction actually applied each day) instead of
            # one single warranted-speed division for the whole segment.
            gw_speed = good_wx["avg_speed_kn"]
            dist_e   = entire["distance_nm"]
            time_ls = fo_ls = None
            dogo_ls = None  # GO no longer gets its own verdict — see module doc comment above
            # Intermediate formula values (a_h/b_h/c_h/d_tot/e_tot/f_tot) are
            # exposed in the result's "detail" key below — these are what the
            # PDF report's Section B/C pages walk through step by step. They
            # used to be recomputed independently in the frontend
            # (voyagePdfExport.js); exposing them here lets the PDF just
            # DISPLAY this endpoint's own numbers instead of recalculating,
            # which is what caused the PDF/live-table drift this whole
            # unification effort has been fixing (client request 2026-09).
            a_h = b_h = c_h = d_tot = e_tot = f_tot = None
            ev = _event_wise_cp(seg, w_spd, w_fo, w_dogo, tol_kn, tol_pct)
            if gw_speed and dist_e and ev["event_count"] > 0:
                a_h = dist_e / gw_speed
                b_h, c_h = ev["b_h"], ev["c_h"]
                time_lost   = (a_h - ev["b_h"]) if ev["b_h"] > 0 else None
                time_gained = ev["c_h"] - a_h
                if time_lost is not None and time_lost > 0:
                    time_ls = round(time_lost, 2)
                elif time_gained > 0:
                    time_ls = round(-time_gained, 2)
                else:
                    time_ls = 0.0

                # Combined Total Fuel Over-consumption(+) / Saving(-) — FO and
                # GO judged TOGETHER against the combined warranted band, not
                # as two independent verdicts. Uses the TRUE physical total
                # (raw FO + raw GO from good_wx, already correctly aggregated
                # by _agg_wni) — never a reclassified figure, which would
                # double-count; see voyagePdfExport.js's dTotal doc comment
                # for the bug this mirrors and avoids.
                good_time = good_wx["time_h"]
                if good_time:
                    good_raw_total = (good_wx["fo_mt"] or 0) + (good_wx["dogo_mt"] or 0)
                    d_tot = a_h * (good_raw_total / good_time)
                    e_tot, f_tot = ev["e_tot"], ev["f_tot"]
                    over = (d_tot - ev["e_tot"]) if ev["e_tot"] > 0 else None
                    save = (ev["f_tot"] - d_tot) if ev["f_tot"] > 0 else None
                    if over is not None and over > 0:
                        fo_ls = round(over, 2)
                    elif save is not None and save > 0:
                        fo_ls = round(-save, 2)
                    elif over is not None or save is not None:
                        fo_ls = 0.0

            ratio = round(good_wx["time_h"] / entire["time_h"] * 100, 1) if entire["time_h"] else 0.0

            # Arrival port/date are finalised from the segment's actual EOSP row,
            # not the last "steaming" row — an EOSP report usually carries zero
            # distance/duration for that day (it marks the end of the passage),
            # so it gets filtered out of `steaming` entirely. Pulling from `seg`
            # (the full segment, before that filter) is what makes this land on
            # the real arrival port/date instead of whatever the last plausible
            # sailing day happened to say.
            eosp_rows = [r for r in seg if "EOSP" in (r.get("event_type") or "").upper()]
            eosp_row = eosp_rows[-1] if eosp_rows else None

            dep = (steaming[0].get("From_Port") or "").strip() or "—"
            arr = ((eosp_row.get("To_Port") if eosp_row else None)
                   or (steaming[-1].get("To_Port") if steaming else None) or "").strip() or "—"

            out.append({
                "voyage_no":      voyage_no,
                "segment_no":     seg_no,
                "loading_cond":   cond,
                "source":         steaming[0].get("source_id"),
                "departure_port": dep,
                "arrival_port":   arr,
                "atd":            str(steaming[0].get("Date") or ""),
                "ata":            str((eosp_row.get("Date") if eosp_row else None)
                                       or (steaming[-1].get("Date") if steaming else "") or ""),
                "loss": {
                    "time_h": time_ls, "fo_mt": fo_ls, "dogo_mt": dogo_ls, "ratio_pct": ratio,
                },
                # Formula walk-through values for the PDF's Section B (Time
                # Calculation) and Section C (Consumption Calculation) pages —
                # see comment above. event_count is the same [N events] shown
                # in both formula boxes.
                "detail": {
                    "a_h": _round(a_h, 2), "b_h": _round(b_h, 2), "c_h": _round(c_h, 2),
                    "d_tot": _round(d_tot, 2), "e_tot": _round(e_tot, 2), "f_tot": _round(f_tot, 2),
                    "event_count": ev["event_count"],
                },
                "good_wx":  good_wx,
                "entire":   entire,
                "warranty": {"speed_kn": w_spd, "fo_mtpd": w_fo, "dogo_mtpd": w_dogo},
                "allowance": {"speed_kn": _num(cfg.get("speed_tol_kn")), "cons_pct": _num(cfg.get("cons_tol_pct"))},
                "good_wx_def": {"wind": GW_WIND, "sea_state": GW_SEA, "current": GW_CURRENT, "ratio_pct": GW_RATIO},
                "sample_sufficient": ratio >= GW_RATIO,
                "configured": bool(cfg),
            })

    def _k(res):
        try:    return (0, float(res["voyage_no"]), res["segment_no"])
        except (TypeError, ValueError): return (1, str(res["voyage_no"]), res["segment_no"])
    out.sort(key=_k)
    return out


def not_computable_result(voyage_no, reason, source=None):
    """A placeholder result for a requested voyage that produced ZERO
    segments in compute_cp_voyage_table() — e.g. no EOSP yet (still an
    ongoing voyage in the source system). Client request 2026-09: a voyage
    like this used to just silently vanish from the CP Performance table
    with no explanation (looked like a bug); this makes the reason explicit
    instead, in the same result shape the frontend already renders, so no
    UI-side special-casing is needed beyond checking not_computable/reason.

    Every numeric/nested field is None-shaped rather than 0-shaped — the
    frontend's existing fmt()-style helpers already render None as '—',
    same as any other not-yet-available figure."""
    empty_agg = {
        "time_h": None, "distance_nm": None, "avg_speed_kn": None,
        "current_factor_kn": None, "fo_mt": None, "dogo_mt": None,
        "fo_reclassified_mt": None,
        "daily_fo": None, "daily_dogo": None, "days": None,
    }
    return {
        "voyage_no":      voyage_no,
        "segment_no":     1,
        "loading_cond":   None,
        "source":         source,
        "departure_port": "—",
        "arrival_port":   "—",
        "atd":            "",
        "ata":            "",
        "loss": {"time_h": None, "fo_mt": None, "dogo_mt": None, "ratio_pct": None},
        "detail": {"a_h": None, "b_h": None, "c_h": None, "d_tot": None, "e_tot": None, "f_tot": None, "event_count": None},
        "good_wx":  empty_agg,
        "entire":   empty_agg,
        "warranty": {"speed_kn": None, "fo_mtpd": None, "dogo_mtpd": None},
        "allowance": {"speed_kn": None, "cons_pct": None},
        "good_wx_def": {"wind": GW_WIND, "sea_state": GW_SEA, "current": GW_CURRENT, "ratio_pct": GW_RATIO},
        "sample_sufficient": False,
        "configured": False,
        "not_computable": True,
        "reason": reason,
    }
