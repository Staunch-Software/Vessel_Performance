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
    """WNI good-weather: BF <= 4 AND Hs <= 3.0. Missing either criterion → not fair."""
    bf = _num(r.get("BF_Wind"))
    hs = _num(r.get("Sig_Wave_Ht_m"))
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
        "daily_fo":       round(fo / days, 2) if days else None,
        "daily_dogo":     round(dogo / days, 2) if days else None,
        "days":           round(days, 2),
    }


def _segments(vrows):
    """Split a voyage's (date-ordered) rows into segments by destination-port runs."""
    segs, cur, cur_port = [], [], object()
    for r in vrows:
        port = (r.get("To_Port") or "").strip()
        if cur and port != cur_port:
            segs.append(cur); cur = []
        cur.append(r); cur_port = port
    if cur:
        segs.append(cur)
    return segs


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
    """
    by_voyage = OrderedDict()
    for r in rows:
        by_voyage.setdefault(r.get("Voyage_No"), []).append(r)

    out = []
    for voyage_no, vrows in by_voyage.items():
        vrows = sorted(vrows, key=lambda r: str(r.get("Date") or ""))
        for seg_no, seg in enumerate(_segments(vrows), start=1):
            steaming = [r for r in seg if _is_steaming(r) and _distance_ok(r)]
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

            # Loss(+) / Saving(-) — good-weather performance vs warranty, extrapolated
            # across the entire-voyage distance/duration. Two separate comparisons,
            # per CP convention (matches the PDF voyage report's Time Calculation):
            #   Time Lost   = (a) - (b)  — (b) uses warranted speed minus the 'about'
            #                              allowance (tol_kn), benefit of the doubt to the vessel
            #   Time Gained = (c) - (a)  — (c) uses the full warranted speed, no allowance,
            #                              to claim a saving
            # Whichever is positive is the result; if neither is, it's 0 (within tolerance).
            gw_speed = good_wx["avg_speed_kn"]
            dist_e   = entire["distance_nm"]
            time_ls = fo_ls = dogo_ls = None
            a_h = b_h = c_h = None
            if w_spd and gw_speed and dist_e:
                eff_spd = w_spd - tol_kn
                a_h = dist_e / gw_speed
                b_h = dist_e / eff_spd if eff_spd else None
                c_h = dist_e / w_spd
                time_lost   = (a_h - b_h) if b_h else None
                time_gained = c_h - a_h
                if time_lost is not None and time_lost > 0:
                    time_ls = round(time_lost, 2)
                elif time_gained > 0:
                    time_ls = round(-time_gained, 2)
                else:
                    time_ls = 0.0

            # Fuel Over-consumption(+) / Saving(-) — same two-formula convention as
            # time above (matches the PDF voyage report's Consumption Calculation):
            #   Over-consumption = (d) - (e)  — (e) extrapolates the MAX warranted
            #                                   consumption (+tol%) over (b_h), the
            #                                   tolerant/allowance speed time — benefit
            #                                   of the doubt to the vessel
            #   Saving           = (f) - (d)  — (f) extrapolates the MIN warranted
            #                                   consumption (-tol%) over (c_h), the full
            #                                   warranted-speed time, no allowance
            # (d) is the entire-voyage-equivalent consumption at the observed good-weather
            # rate, extrapolated over (a_h) — the same good-weather-speed time used for (a).
            if a_h is not None and good_wx["daily_fo"] is not None:
                d_fo = a_h * (good_wx["daily_fo"] / 24.0)
                e_fo = b_h * (w_fo * (1 + tol_pct/100.0) / 24.0) if (w_fo is not None and b_h) else None
                f_fo = c_h * (w_fo * (1 - tol_pct/100.0) / 24.0) if (w_fo is not None and c_h) else None
                fo_over = (d_fo - e_fo) if e_fo is not None else None
                fo_save = (f_fo - d_fo) if f_fo is not None else None
                if fo_over is not None and fo_over > 0:
                    fo_ls = round(fo_over, 2)
                elif fo_save is not None and fo_save > 0:
                    fo_ls = round(-fo_save, 2)
                elif fo_over is not None or fo_save is not None:
                    fo_ls = 0.0
            if a_h is not None and good_wx["daily_dogo"] is not None:
                d_go = a_h * (good_wx["daily_dogo"] / 24.0)
                e_go = b_h * (w_dogo * (1 + tol_pct/100.0) / 24.0) if (w_dogo is not None and b_h) else None
                f_go = c_h * (w_dogo * (1 - tol_pct/100.0) / 24.0) if (w_dogo is not None and c_h) else None
                go_over = (d_go - e_go) if e_go is not None else None
                go_save = (f_go - d_go) if f_go is not None else None
                if go_over is not None and go_over > 0:
                    dogo_ls = round(go_over, 2)
                elif go_save is not None and go_save > 0:
                    dogo_ls = round(-go_save, 2)
                elif go_over is not None or go_save is not None:
                    dogo_ls = 0.0

            ratio = round(good_wx["time_h"] / entire["time_h"] * 100, 1) if entire["time_h"] else 0.0

            dep = (steaming[0].get("From_Port") or "").strip() or "—"
            arr = (steaming[-1].get("To_Port") or "").strip() or "—"

            out.append({
                "voyage_no":      voyage_no,
                "segment_no":     seg_no,
                "loading_cond":   cond,
                "source":         steaming[0].get("source_id"),
                "departure_port": dep,
                "arrival_port":   arr,
                "atd":            str(steaming[0].get("Date") or ""),
                "ata":            str(steaming[-1].get("Date") or ""),
                "loss": {
                    "time_h": time_ls, "fo_mt": fo_ls, "dogo_mt": dogo_ls, "ratio_pct": ratio,
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
