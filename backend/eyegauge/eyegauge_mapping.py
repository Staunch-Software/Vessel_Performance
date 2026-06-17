"""
eyegauge_mapping.py
===================
Maps ACTUAL Eyegauge (Sea Vision) sensor keys to the same
57-column ANALYSIS_DATA_COLUMNS schema used by WNI.

Keys verified from debug_keys.py output.
"""

import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# Exact 57-column list — same as WNI analysis_data
# ─────────────────────────────────────────────────────────────────────────────
ANALYSIS_DATA_COLUMNS = [
    "Record_ID", "Date", "Time_UTC", "Voyage_No", "From_Port", "To_Port",
    "Loading_Cond", "STW_kn", "SOG_kn", "Heading_deg", "Distance_nm",
    "Duration_h", "Draft_Fwd_m", "Draft_Aft_m", "Mean_Draft_m",
    "Displacement_MT", "Trim_m", "ME_Energy_Meter_Reading_KWh", "Shaft_Power_kW",
    "Shaft_RPM", "ME_COMMON_MASS_FLOWMETER_MT", "AE_1_ENERGY_READING_KWh",
    "A_E_1_RUNNING_HOURS", "AE_1_POWER_KW", "AE_2_ENERGY_READING_KWh",
    "A_E_2_RUNNING_HOURS", "AE_2_POWER_KW", "AE_3_ENERGY_READING_KWh",
    "A_E_3_RUNNING_HOURS", "AE_3_POWER_KW", "AE_MASS_FLOWMETER_IN",
    "AE_FLOWMETER_READING_OUT", "ME_FOC_MT", "AE_FOC_MT", "Est_Power_kW",
    "SFOC_gkWh", "Rel_Wind_Spd_ms", "Rel_Wind_Dir_deg", "True_Wind_Spd_ms",
    "True_Wind_Dir_deg", "Sig_Wave_Ht_m", "Wave_Period_s", "Wave_Dir_deg",
    "Swell_Ht_m", "Swell_Period_s", "Swell_Dir_deg", "Water_Temp_C",
    "Water_Depth_m", "Current_Spd_kn", "Current_Dir_deg", "Rudder_Angle_deg",
    "P_wind_kW", "P_wave_kW", "P_temp_kW", "VTI", "Power_Dev_pct",
    "Speed_Loss_pct",
]

BEAUFORT_TO_KTS = {
    0: 1,   1: 2,   2: 5,   3: 8.5,  4: 13.5,
    5: 19,  6: 24.5, 7: 30.5, 8: 37,  9: 44,
    10: 51.5, 11: 59.5, 12: 64,
}

KTS_TO_MS  = 0.5144
KMPH_TO_MS = 1 / 3.6


# ─────────────────────────────────────────────────────────────────────────────
# Safe helpers
# ─────────────────────────────────────────────────────────────────────────────

def _num(row: dict, *keys, default: float = 0.0) -> float:
    """
    Returns the first numeric value found for the given keys.
    - If value is 0    → returns 0.0  (stored as 0)
    - If no value found → returns default (caller decides whether to store N/A)
    """
    for k in keys:
        v = pd.to_numeric(row.get(k), errors="coerce")
        if pd.notna(v):
            return float(v)
    return default


def _str(row: dict, *keys, default=None):
    """
    Returns the first non-empty string found for the given keys.
    Returns default (None) if nothing found — caller maps None → 'N/A'.
    """
    for k in keys:
        v = row.get(k)
        if v is not None:
            try:
                if pd.isna(v):
                    continue
            except (TypeError, ValueError):
                pass
            s = str(v).strip()
            if s and s.lower() not in ("nan", "none", "null"):
                return s
    return default


def _val(raw):
    """
    Final value resolver — converts unusable values to None (SQL NULL).
    - None / nan / inf / empty string → None
    - any real numeric value (incl. 0) → value as-is
    """
    if raw is None:
        return None
    if isinstance(raw, float):
        import math
        if math.isnan(raw) or math.isinf(raw):
            return None
    if isinstance(raw, str) and raw.strip().lower() in ("nan", "none", "null", "n/a", ""):
        return None
    return raw


# ─────────────────────────────────────────────────────────────────────────────
# Main mapping function
# ─────────────────────────────────────────────────────────────────────────────

def map_eyegauge_analysis_row(row: dict, specs=None, record_id=None) -> dict:
    out = {col: None for col in ANALYSIS_DATA_COLUMNS}

    def get_spec(attr: str, default: float = 0.0) -> float:
        val = getattr(specs, attr, default)
        return float(val) if val is not None else default

    # ── 1. Identity & timestamp ───────────────────────────────────────────────
    out["Record_ID"] = record_id

    ts = row.get("__timestamp__")
    if ts is not None:
        dt = pd.to_datetime(ts, errors="coerce")
        if pd.notnull(dt):
            out["Date"]     = dt.date()
            out["Time_UTC"] = dt.strftime("%H:%M")

    # Voyage / port
    # voyage_num and voyage_type come from ASSET telemetry.
    # After clean_name() in the pipeline they become:
    #   voyage_num  → sensor_voyage_num
    #   voyage_type → sensor_voyage_type
    # We try both the renamed key (pipeline path) and the raw key (direct path).
    out["Voyage_No"]    = _str(row, "sensor_voyage_num",  "voyage_num")
    out["From_Port"]    = None
    out["To_Port"]      = None
    out["Loading_Cond"] = _str(row, "sensor_voyage_type", "voyage_type")

    # ── 2. Navigation ─────────────────────────────────────────────────────────
    # ACTUAL SPEED = speed through water (knots) — from engine device
    stw_kn = _num(row, "ACTUAL SPEED", default=0.0)
    out["STW_kn"] = stw_kn if stw_kn > 0 else None

    # SOG = speed over ground (knots) — from ASSET
    sog_kn = _num(row, "SOG", default=0.0)
    out["SOG_kn"] = sog_kn if sog_kn > 0 else None

    # COG = course over ground (degrees)
    out["Heading_deg"] = _num(row, "COG") or None

    # Distance — distanceNM from ASSET
    dist = _num(row, "distanceNM", "voyage_distance", default=0.0)
    out["Distance_nm"] = dist if dist > 0 else None

    # Duration — not directly available; leave NULL
    out["Duration_h"] = None

    # Draft — draftfore / draftaft from ASSET
    fwd = _num(row, "draftfore", default=0.0)
    aft = _num(row, "draftaft",  default=0.0)
    out["Draft_Fwd_m"] = fwd if fwd > 0 else None
    out["Draft_Aft_m"] = aft if aft > 0 else None

    mean_draft = 0.0
    if fwd > 0 and aft > 0:
        mean_draft          = round((fwd + aft) / 2, 2)
        out["Mean_Draft_m"] = mean_draft
        out["Trim_m"]       = round(aft - fwd, 2)
        design_draft        = get_spec("design_draft")
        if design_draft > 0:
            out["Displacement_MT"] = (
                get_spec("displacement_at_design")
                + (mean_draft - design_draft) * 100 * get_spec("tpc_at_design")
            )

    # ── 3. Main Engine ────────────────────────────────────────────────────────
    # me-power  → Shaft_Power_kW  (engine device)
    shaft_power_kw = _num(row, "me-power", default=0.0)
    out["Shaft_Power_kW"] = shaft_power_kw if shaft_power_kw > 0 else None

    # me-rpm → Shaft_RPM  (engine device)
    rpm = _num(row, "me-rpm", default=0.0)
    out["Shaft_RPM"] = rpm if rpm > 0 else None

    # Estimated power from cubic RPM law
    mcr_kw  = get_spec("me_engine_mcr_kw")
    mcr_rpm = get_spec("me_mcr_rpm")
    if rpm > 0 and mcr_rpm > 0:
        out["Est_Power_kW"] = round(
            mcr_kw * (rpm / mcr_rpm) ** get_spec("propeller_law_exponent", 3.0), 2
        )

    # ME fuel consumption:
    # consumption-me-mtph  → mt per hour  (flowmeters device)
    # consumption-me-avg   → daily average (ASSET)
    # fm_me-fuel-flow-mass → flow mass    (ASSET)
    me_foc_mtph = _num(row, "consumption-me-mtph", default=0.0)
    me_foc_avg  = _num(row, "consumption-me-avg",  default=0.0)
    me_flow     = _num(row, "fm_me-fuel-flow-mass", default=0.0)

    # ME_FOC_MT — prefer hourly rate (mt/h), store as-is
    me_foc = me_foc_mtph if me_foc_mtph > 0 else (me_foc_avg / 24 if me_foc_avg > 0 else me_flow)
    out["ME_FOC_MT"]                   = me_foc       if me_foc > 0       else None
    out["ME_COMMON_MASS_FLOWMETER_MT"] = me_flow      if me_flow > 0      else None

    # me-fuel-flow-mass from flowmeters → ME_MASS_FLOWMETER
    me_fuel_flow = _num(row, "me-fuel-flow-mass", default=0.0)
    out["AE_MASS_FLOWMETER_IN"] = _num(row, "dg-fuel-flow-mass", default=0.0) or None

    # SFOC = (FOC mt/h × 1,000,000) / shaft_power_kW
    if shaft_power_kw > 0 and me_foc > 0:
        out["SFOC_gkWh"] = round((me_foc * 1_000_000) / shaft_power_kw, 2)

    # me-scav-air → not a direct column but informational
    # me-load → load percentage (not a direct column)

    # ── 4. Auxiliary Engines ──────────────────────────────────────────────────
    # 1-kw, 2-kw, 3-kw → AE power (generators device)
    ae1_kw = _num(row, "1-kw", default=0.0)
    ae2_kw = _num(row, "2-kw", default=0.0)
    ae3_kw = _num(row, "3-kw", default=0.0)
    out["AE_1_POWER_KW"] = ae1_kw if ae1_kw > 0 else None
    out["AE_2_POWER_KW"] = ae2_kw if ae2_kw > 0 else None
    out["AE_3_POWER_KW"] = ae3_kw if ae3_kw > 0 else None

    # AE fuel consumption — consumption-dg-mtph (flowmeters) or consumption-dg-avg (ASSET)
    ae_foc_mtph = _num(row, "consumption-dg-mtph", default=0.0)
    ae_foc_avg  = _num(row, "consumption-dg-avg",  default=0.0)
    ae_foc      = ae_foc_mtph if ae_foc_mtph > 0 else (ae_foc_avg / 24 if ae_foc_avg > 0 else 0.0)
    out["AE_FOC_MT"] = ae_foc if ae_foc > 0 else None

    # AE flowmeter
    ae_flow = _num(row, "dg-fuel-flow-mass", "fm_dg-fuel-flow-mass", default=0.0)
    out["AE_FLOWMETER_READING_OUT"] = ae_flow if ae_flow > 0 else None

    # ── 5. Wind ───────────────────────────────────────────────────────────────
    # winddirDegree → True_Wind_Dir_deg  (ASSET)
    true_wind_dir = _num(row, "winddirDegree", default=0.0)
    out["True_Wind_Dir_deg"] = true_wind_dir if true_wind_dir > 0 else None

    # windspeedKmph → convert to m/s  (ASSET)
    wind_kmph = _num(row, "windspeedKmph", default=0.0)
    beaufort  = _num(row, "beaufort",      default=-1.0)

    if wind_kmph > 0:
        true_wind_ms = round(wind_kmph * KMPH_TO_MS, 3)
    elif beaufort >= 0:
        bf_kts       = BEAUFORT_TO_KTS.get(int(round(beaufort)), 0.0)
        true_wind_ms = round(bf_kts * KTS_TO_MS, 3)
    else:
        true_wind_ms = 0.0

    out["True_Wind_Spd_ms"] = true_wind_ms if true_wind_ms > 0 else None
    out["Rel_Wind_Spd_ms"]  = out["True_Wind_Spd_ms"]
    out["Rel_Wind_Dir_deg"] = out["True_Wind_Dir_deg"]

    # ── 6. Waves & Swell ──────────────────────────────────────────────────────
    # waveHeight, waveDirection → from ASSET
    sig_wave_ht = _num(row, "waveHeight",    default=0.0)
    wave_dir    = _num(row, "waveDirection", default=0.0)
    swell_ht    = _num(row, "swellHeight",   default=0.0)
    swell_dir   = _num(row, "swellDir",      default=0.0)

    out["Sig_Wave_Ht_m"] = sig_wave_ht if sig_wave_ht > 0 else None
    out["Wave_Dir_deg"]  = wave_dir    if wave_dir    > 0 else None
    out["Swell_Ht_m"]    = swell_ht    if swell_ht    > 0 else None
    out["Swell_Dir_deg"] = swell_dir   if swell_dir   > 0 else None

    # Period not available in Eyegauge keys
    out["Wave_Period_s"]  = None
    out["Swell_Period_s"] = None

    # ── 7. Current & Water ────────────────────────────────────────────────────
    # currentSpeed, currentDirection → from ASSET
    current_spd = _num(row, "currentSpeed",     default=0.0)
    current_dir = _num(row, "currentDirection", default=0.0)
    out["Current_Spd_kn"]  = current_spd if current_spd > 0 else None
    out["Current_Dir_deg"] = current_dir if current_dir > 0 else None

    # Derive current from SOG - STW if not available
    if out["Current_Spd_kn"] is None and sog_kn > 0 and stw_kn > 0:
        out["Current_Spd_kn"] = round(sog_kn - stw_kn, 2)

    # waterTemperature → Water_Temp_C  (ASSET)
    water_temp = _num(row, "waterTemperature", "temperature", default=0.0)
    out["Water_Temp_C"] = water_temp if water_temp > 0 else None

    out["Water_Depth_m"]    = None   # not in Eyegauge keys
    out["Rudder_Angle_deg"] = None   # not in Eyegauge keys

    # ── 8. Resistance power components ───────────────────────────────────────
    stw_ms = stw_kn * KTS_TO_MS if stw_kn > 0 else 0.0

    if true_wind_ms > 0 and stw_ms > 0:
        out["P_wind_kW"] = round(
            0.5 * 1.225
            * get_spec("wind_coeff_cx_0", 0.8)
            * get_spec("transverse_projected_area")
            * (true_wind_ms ** 2 - stw_ms ** 2)
            * stw_ms / 1000, 2,
        )

    if stw_ms > 0 and sig_wave_ht > 0:
        out["P_wave_kW"] = round(
            0.5 * 1025 * 0.05
            * get_spec("length_bp")
            * get_spec("beam")
            * (sig_wave_ht ** 2)
            * (2 * 3.14159 / 8.0) ** 2
            * stw_ms
            / (1000 * get_spec("total_propulsive_efficiency", 0.7)), 2,
        )

    wt = water_temp if water_temp > 0 else 15.0
    out["P_temp_kW"] = round(shaft_power_kw * 0.002 * (15.0 - wt), 2) if shaft_power_kw > 0 else 0.0

    # ── 9. VTI, Power deviation, Speed loss ───────────────────────────────────
    voyage_type = str(out["Loading_Cond"] or "").upper()
    is_laden    = voyage_type in ("LADEN", "L")
    coeff_a  = get_spec("baseline_coeff_a_laden")  if is_laden else get_spec("baseline_coeff_a_ballast")
    exp_n    = get_spec("baseline_exponent_n_laden") if is_laden else get_spec("baseline_exponent_n_ballast")
    ref_draft = get_spec("reference_draft_laden")   if is_laden else get_spec("reference_draft_ballast")

    if stw_kn > 0 and mean_draft > 0 and ref_draft > 0 and coeff_a > 0:
        baseline_pwr = coeff_a * (stw_kn ** exp_n) * (mean_draft / ref_draft) ** 0.67
        if baseline_pwr > 0 and shaft_power_kw > 0:
            vti = shaft_power_kw / baseline_pwr
            out["VTI"]            = round(vti, 4)
            out["Power_Dev_pct"]  = round((vti - 1) * 100, 2)
            out["Speed_Loss_pct"] = round(out["Power_Dev_pct"] / 3, 2)

    # ── Final pass: sanitise numeric columns — None/nan/inf → None (SQL NULL) ──
    # Text/identity columns are left as-is (None = SQL NULL, real value = value).
    TEXT_COLS = {"Record_ID", "Date", "Time_UTC", "Voyage_No",
                 "From_Port", "To_Port", "Loading_Cond", "vessel_imo", "source_id"}

    for col in list(out.keys()):
        if col not in TEXT_COLS:
            out[col] = _val(out[col])

    return out