import pandas as pd
import logging
from datetime import datetime

log = logging.getLogger(__name__)

# ===========================================================================
# 1. HELPER FUNCTIONS
# ===========================================================================

def val_num(data_dict, key):
    """Extracts a numeric value from a dictionary, handling NaNs and commas."""
    if not data_dict or key not in data_dict:
        return None
    val = data_dict.get(key)
    try:
        if pd.isna(val) or str(val).strip() == "":
            return None
        # Remove commas and convert to float
        return float(str(val).replace(',', '').strip())
    except (ValueError, TypeError):
        return None

def val_str(data_dict, key):
    """Extracts a string value from a dictionary, handling NaNs."""
    if not data_dict or key not in data_dict:
        return None
    val = data_dict.get(key)
    if pd.isna(val) or str(val).strip() == "":
        return None
    return str(val).strip()

# ===========================================================================
# 2. COLUMN DEFINITIONS
# ===========================================================================

MARI_APPS_COLUMNS = [
    "log_number", "log_date", "log_date_utc", "time_zone", "log_type", "status",
    "validation_status", "validation_details", "leg_number", "to_port", 
    "loading_condition", "is_closed", "log_duration", "distance_og", "speed_og",
    "distance_to_eosp", "ship_heading", "lat_degree", "lat_minutes", "lat_direction",
    "lon_degree", "lon_minutes", "lon_direction", "cargo_on_board", "total_ballast_onboard",
    "anchorage_hours", "drifting_hours", "draft_fwd", "draft_aft", "trim", "eta", "etb", "ets",
    "me1_running_hrs", "me1_rpm", "me1_power", "mcr", "ae1_running_hrs", "ae1_calculated_e_power",
    "ae1_calc_load", "ae2_running_hrs", "ae2_calculated_e_power", "ae2_calc_load",
    "ae3_running_hrs", "ae3_calculated_e_power", "ae3_calc_load", "bl1_running_hrs",
    "inc1_running_hrs", "eg1_running_hrs", "combl1_running_hrs", "me_total_cons",
    "ae_total_cons", "wind_speed", "wind_direction", "true_wind_force", "wave_height",
    "wave_direction", "current_speed", "current_direction", "apparent_slip", "real_slip",
    "m_e_iso_sfoc", "m_e_scoc", "a_e_iso_sfoc", "nox_emitted", "co2_emitted", "sox_emitted", "eeoi",
    "mandatory_failed_reason", "field_validation_failed_reason", "rejected_remarks",
    "me_hfo", "me_lfo", "me_mdo", "me_lpg_propane", "me_lpg_butane", "me_lng", "me_methanol", 
    "me_ethanol", "me_ammonia", "me_bio_fuel", "ae_hfo", "ae_lfo", "ae_mdo", "ae_lpg_propane", 
    "ae_lpg_butane", "ae_lng", "ae_methanol", "ae_ethanol", "ae_ammonia", "ae_bio_fuel",
    "bl_total_cons", "bl_hfo", "bl_lfo", "bl_mdo", "bl_lpg_propane", "bl_lpg_butane", "bl_lng", 
    "bl_methanol", "bl_ethanol", "bl_ammonia", "bl_bio_fuel", "inc_total_cons", "inc_hfo", 
    "inc_lfo", "inc_mdo", "inc_lpg_propane", "inc_lpg_butane", "inc_lng", "inc_methanol", 
    "inc_ethanol", "inc_ammonia", "inc_bio_fuel", "eg_total_cons", "eg_hfo", "eg_lfo", 
    "eg_mdo", "eg_lpg_propane", "eg_lpg_butane", "eg_lng", "eg_methanol", "eg_ethanol", 
    "eg_ammonia", "eg_bio_fuel", "combl_total_cons", "combl_hfo", "combl_lfo", "combl_mdo", 
    "combl_lpg_propane", "combl_lpg_butane", "combl_lng", "combl_methanol", "combl_ethanol", 
    "combl_ammonia", "combl_bio_fuel", "aeb_total_cons", "aeb_hfo", "aeb_lfo", "aeb_mdo", 
    "aeb_lpg_propane", "aeb_lpg_butane", "aeb_lng", "aeb_methanol", "aeb_ethanol", "aeb_ammonia", 
    "aeb_bio_fuel", "blfo_total_cons", "blfo_hfo", "blfo_lfo", "blfo_mdo", "blfo_lpg_propane", 
    "blfo_lpg_butane", "blfo_lng", "blfo_methanol", "blfo_ethanol", "blfo_ammonia", "blfo_bio_fuel",
    "fore_draught", "aft_draught"
]

ANALYSIS_DATA_COLUMNS = [
    "Record_ID", "Date", "Time_UTC", "Voyage_No", "From_Port", "To_Port", "Loading_Cond",
    "STW_kn", "SOG_kn", "Heading_deg", "Distance_nm", "Duration_h", "Draft_Fwd_m",
    "Draft_Aft_m", "Mean_Draft_m", "Displacement_MT", "Trim_m", "ME_Energy_Meter_Reading_KWh",
    "Shaft_Power_kW", "Shaft_RPM", "ME_COMMON_MASS_FLOWMETER_MT", "AE_1_ENERGY_READING_KWh",
    "A_E_1_RUNNING_HOURS", "AE_1_POWER_KW", "AE_2_ENERGY_READING_KWh", "A_E_2_RUNNING_HOURS",
    "AE_2_POWER_KW", "AE_3_ENERGY_READING_KWh", "A_E_3_RUNNING_HOURS", "AE_3_POWER_KW",
    "AE_MASS_FLOWMETER_IN", "AE_FLOWMETER_READING_OUT", "ME_FOC_MT", "AE_FOC_MT",
    "Est_Power_kW", "SFOC_gkWh", "Rel_Wind_Spd_ms", "Rel_Wind_Dir_deg", "True_Wind_Spd_ms",
    "True_Wind_Dir_deg", "Sig_Wave_Ht_m", "Wave_Period_s", "Wave_Dir_deg", "Swell_Ht_m",
    "Swell_Period_s", "Swell_Dir_deg", "Water_Temp_C", "Water_Depth_m", "Current_Spd_kn",
    "Current_Dir_deg", "Rudder_Angle_deg", "P_wind_kW", "P_wave_kW", "P_temp_kW", "VTI",
    "Power_Dev_pct", "Speed_Loss_pct"
]

# ===========================================================================
# 3. KEY LOOKUP HELPERS
# ===========================================================================

def find_key_fuzzy(data_dict, search_terms):
    if not data_dict:
        return None
    for key in data_dict.keys():
        for term in search_terms:
            if term.lower() in key.lower():
                return key
    return None

def find_key_all_terms(data_dict, required_terms):
    if not data_dict:
        return None
    for key in data_dict.keys():
        if all(term.lower() in key.lower() for term in required_terms):
            return key
    return None

def get_fuel(excel_dict, category, fuel_type):
    key = find_key_all_terms(excel_dict, [category, fuel_type])
    if not key:
        return None
    return val_num(excel_dict, key)

def _extract_tabs(payload: dict) -> dict:
    return {
        "pos":  payload.get("Position_Data",    {}),
        "op":   payload.get("Operation_Data",   {}),
        "cons": payload.get("Consumption_Data", {}),
        "perf": payload.get("Performance_Data", {}),
        "mach": payload.get("Machinery_Data",   {}),
        "fuel": payload.get("Fuel_Stock_Data",  {}),
        "kpi":  payload.get("KPI_Data",         {}),
    }

# ===========================================================================
# 4. MAP TO 160-COLUMN MARIAPPS REPORT TABLE
# ===========================================================================

def map_mariapps_to_160(payload, excel_data=None, header_data=None):
    out = {col: None for col in MARI_APPS_COLUMNS}

    excel  = excel_data  if excel_data  is not None else payload.get("Excel_Data", {})
    header = header_data if header_data is not None else {}

    tabs = _extract_tabs(payload)
    perf = tabs["perf"]
    mach = tabs["mach"]
    pos  = tabs["pos"]
    op   = tabs["op"]

    # --- METADATA ---
    out["log_number"] = payload.get("log_number")

    raw_date_from_excel  = val_str(excel, find_key_fuzzy(excel, ["Log Date", "Date"]))
    raw_time_from_header = header.get("Time") or header.get("Log Time")

    if raw_date_from_excel and len(str(raw_date_from_excel)) > 12:
        parsed_date = pd.to_datetime(raw_date_from_excel, errors='coerce')
    elif raw_time_from_header:
        ui_date = payload.get("log_date")
        parsed_date = pd.to_datetime(f"{ui_date} {raw_time_from_header}", errors='coerce')
    else:
        parsed_date = pd.to_datetime(payload.get("log_date"), errors='coerce')

    out["log_date"]     = parsed_date
    out["log_date_utc"] = parsed_date
    out["time_zone"]    = val_str(excel, find_key_fuzzy(excel, ["Time Zone", "TZ"]))
    out["log_type"]     = val_str(excel, find_key_fuzzy(excel, ["Log Type"])) or payload.get("log_type")
    out["status"]       = val_str(excel, find_key_fuzzy(excel, ["Status"]))
    out["validation_status"]  = val_str(excel, find_key_fuzzy(excel, ["Validation Status"]))
    out["validation_details"] = val_str(excel, find_key_fuzzy(excel, ["Validation Details", "Remarks", "Comment"]))
    out["leg_number"]   = (
        val_str(header, find_key_fuzzy(header, ["Voyage Number", "Leg Number"])) or
        val_str(excel,  find_key_fuzzy(excel,  ["Voyage Number", "Leg Number"]))
    )
    out["to_port"]           = val_str(excel, find_key_fuzzy(excel, ["To Port", "Destination Port"]))
    out["loading_condition"] = val_str(excel, find_key_fuzzy(excel, ["Loading Condition", "Condition"]))
    out["mandatory_failed_reason"]        = val_str(excel, find_key_fuzzy(excel, ["Mandatory Failed", "Mandatory"]))
    out["field_validation_failed_reason"] = val_str(excel, find_key_fuzzy(excel, ["Field Validation", "Validation Failed"]))
    out["rejected_remarks"]               = val_str(excel, find_key_fuzzy(excel, ["Reject", "Rejected"]))

    closed_val = val_str(excel, find_key_fuzzy(excel, ["Is Closed", "Closed"]))
    if closed_val:
        out["is_closed"] = str(closed_val).lower() in ['true', 'yes', '1', 'y']

    # --- NAVIGATION ---
    out["log_duration"]     = val_num(excel, find_key_fuzzy(excel, ["Steaming Time", "Duration"]))
    out["distance_og"]      = (
        val_num(pos,   find_key_fuzzy(pos,   ["Distance Over Ground", "Distance OG"])) or
        val_num(excel, find_key_fuzzy(excel, ["Distance Observed", "Distance (nm)"]))
    )
    out["speed_og"]         = (
        val_num(pos,   find_key_fuzzy(pos,   ["Speed Over Ground", "SOG"])) or
        val_num(excel, find_key_fuzzy(excel, ["Speed (OG)", "Speed Observed"]))
    )
    out["distance_to_eosp"] = val_num(excel, find_key_fuzzy(excel, ["Distance to Go", "Distance to EOSP"]))
    out["ship_heading"]     = (
        val_str(pos,   find_key_fuzzy(pos,   ["Heading"])) or
        val_str(excel, find_key_fuzzy(excel, ["Heading", "Ship Heading"]))
    )

    out["lat_degree"]    = val_num(excel, find_key_fuzzy(excel, ["Lat Deg", "Latitude Degree"]))
    out["lat_minutes"]   = val_num(excel, find_key_fuzzy(excel, ["Lat Min", "Latitude Minutes"]))
    out["lat_direction"] = val_str(excel, find_key_fuzzy(excel, ["Lat Dir", "Latitude Direction"]))
    out["lon_degree"]    = val_num(excel, find_key_fuzzy(excel, ["Lon Deg", "Longitude Degree"]))
    out["lon_minutes"]   = val_num(excel, find_key_fuzzy(excel, ["Lon Min", "Longitude Minutes"]))
    out["lon_direction"] = val_str(excel, find_key_fuzzy(excel, ["Lon Dir", "Longitude Direction"]))

    # --- CARGO & DRAFT ---
    out["cargo_on_board"]        = val_num(excel, find_key_fuzzy(excel, ["Cargo On Board", "Cargo"]))
    out["total_ballast_onboard"] = val_num(excel, find_key_fuzzy(excel, ["Ballast Onboard", "Total Ballast"]))
    out["anchorage_hours"]       = val_str(excel, find_key_fuzzy(excel, ["Anchorage Hours", "Anchor"]))
    out["drifting_hours"]        = val_str(excel, find_key_fuzzy(excel, ["Drifting Hours", "Drift"]))
    out["draft_fwd"]    = val_num(excel, find_key_fuzzy(excel, ["Draft Fwd", "Fore Draft"]))
    out["draft_aft"]    = val_num(excel, find_key_fuzzy(excel, ["Draft Aft", "Aft Draught"]))
    out["fore_draught"] = out["draft_fwd"]
    out["aft_draught"]  = out["draft_aft"]
    out["displacement"] = val_num(excel, find_key_fuzzy(excel, ["Displacement"]))

    if out["draft_fwd"] and out["draft_aft"]:
        try:
            out["trim"] = float(out["draft_fwd"]) - float(out["draft_aft"])
        except (ValueError, TypeError):
            pass

    out["eta"] = pd.to_datetime(val_str(excel, find_key_fuzzy(excel, ["ETA", "E.T.A"])), errors='coerce')
    out["etb"] = pd.to_datetime(val_str(excel, find_key_fuzzy(excel, ["ETB", "E.T.B"])), errors='coerce')
    out["ets"] = pd.to_datetime(val_str(excel, find_key_fuzzy(excel, ["ETS", "E.T.S"])), errors='coerce')

    # --- WEATHER ---
    out["wind_speed"]      = val_num(perf, find_key_fuzzy(perf, ["Wind Speed"])) or val_num(excel, find_key_fuzzy(excel, ["Wind Speed"]))
    out["wind_direction"]  = val_str(perf, find_key_fuzzy(perf, ["Wind Direction"])) or val_str(excel, find_key_fuzzy(excel, ["Wind Direction"]))
    out["true_wind_force"] = val_num(perf, find_key_fuzzy(perf, ["Wind Force", "True Wind Force"])) or val_num(excel, find_key_fuzzy(excel, ["Wind Force"]))
    out["wave_height"]     = val_num(perf, find_key_fuzzy(perf, ["Wave Height", "Sig Wave"]))
    out["wave_direction"]  = val_str(perf, find_key_fuzzy(perf, ["Wave Direction", "Wave Dir"]))
    out["current_speed"]   = val_num(perf, find_key_fuzzy(perf, ["Current Speed"])) or val_num(excel, find_key_fuzzy(excel, ["Current Speed"]))
    out["current_direction"] = val_str(perf, find_key_fuzzy(perf, ["Current Dir"])) or val_str(excel, find_key_fuzzy(excel, ["Current Dir"]))
    out["apparent_slip"]   = val_num(perf, find_key_fuzzy(perf, ["Apparent Slip", "Slip"])) or val_num(excel, find_key_fuzzy(excel, ["Apparent Slip"]))
    out["real_slip"]       = val_num(perf, find_key_fuzzy(perf, ["Real Slip"]))
    out["m_e_iso_sfoc"]    = val_num(perf, find_key_all_terms(perf, ["ME", "SFOC"]))
    out["m_e_scoc"]        = val_num(perf, find_key_all_terms(perf, ["ME", "SCOC"]))
    out["a_e_iso_sfoc"]    = val_num(perf, find_key_all_terms(perf, ["AE", "SFOC"]))
    out["nox_emitted"]     = val_num(perf, find_key_fuzzy(perf, ["NOx"]))
    out["co2_emitted"]     = val_num(perf, find_key_fuzzy(perf, ["CO2"]))
    out["sox_emitted"]     = val_num(perf, find_key_fuzzy(perf, ["SOx"]))
    out["eeoi"]            = val_num(perf, find_key_fuzzy(perf, ["EEOI"]))

    # --- MACHINERY ---
    out["me1_running_hrs"] = (
        val_num(op,    find_key_fuzzy(op,    ["ME", "Running", "Hrs"])) or
        val_num(excel, find_key_fuzzy(excel, ["ME1 Running Hrs", "ME 1 Running"]))
    )
    # ME RPM — MUST come from Machinery_Data "ME Speed (Inst.)" or Operation_Data
    # "ME Calculated Speed (Avg.) - Value".
    # Excel_Data "ME1 RPM" is the CUMULATIVE REVOLUTION COUNTER (e.g. 81990 total
    # revolutions), NOT actual shaft RPM. Using it as RPM causes wildly wrong
    # power calculations (e.g. 81990 RPM → near-zero torque → 200 kW instead of 7874 kW).
    out["me1_rpm"] = (
        val_num(mach, find_key_all_terms(mach, ["ME Speed"])) or          # "ME Speed (Inst.)" = 56.9 RPM ✓
        val_num(op,   find_key_all_terms(op,   ["ME Calculated Speed", "Value"])) or  # "ME Calculated Speed (Avg.) - Value" = 56.94 ✓
        val_num(op,   find_key_fuzzy(op,       ["RPM"]))                   # any explicit RPM key in Operation_Data
        # NOTE: Excel_Data "ME1 RPM" intentionally excluded — it is a revolution counter
    )
    # ME Power — prefer Machinery_Data shaft power (instantaneous measured),
    # then Operation_Data calculated effective power, then Excel_Data flat field.
    # Excel_Data "ME1 Power (kW)" is an operator-entered reported value and is
    # acceptable as a fallback.
    out["me1_power"] = (
        val_num(mach,  find_key_all_terms(mach, ["ME Shaft Power"])) or          # "ME Shaft Power (Inst.)" — direct measurement
        val_num(op,    find_key_all_terms(op,   ["ME Calculated Effective Power", "Value"])) or  # computed effective power
        val_num(excel, find_key_fuzzy(excel,    ["M/E Power", "ME Power", "ME1 Power"])) or      # reported value
        val_num(mach,  find_key_fuzzy(mach,     ["ME", "Power"]))
    )
    out["mcr"] = val_num(excel, find_key_fuzzy(excel, ["MCR"]))

    out["ae1_running_hrs"]        = val_num(op, find_key_all_terms(op, ["AE", "Running", "No 1"])) or val_num(excel, find_key_fuzzy(excel, ["AE1 Running"]))
    out["ae1_calculated_e_power"] = val_num(op, find_key_all_terms(op, ["AE", "Power",   "No 1"])) or val_num(excel, find_key_fuzzy(excel, ["AE1 Power"]))
    out["ae1_calc_load"]          = val_num(op, find_key_all_terms(op, ["AE", "Load",    "No 1"])) or val_num(excel, find_key_fuzzy(excel, ["AE1 Load"]))

    out["ae2_running_hrs"]        = val_num(op, find_key_all_terms(op, ["AE", "Running", "No 2"])) or val_num(excel, find_key_fuzzy(excel, ["AE2 Running"]))
    out["ae2_calculated_e_power"] = val_num(op, find_key_all_terms(op, ["AE", "Power",   "No 2"])) or val_num(excel, find_key_fuzzy(excel, ["AE2 Power"]))
    out["ae2_calc_load"]          = val_num(op, find_key_all_terms(op, ["AE", "Load",    "No 2"])) or val_num(excel, find_key_fuzzy(excel, ["AE2 Load"]))

    out["ae3_running_hrs"]        = val_num(op, find_key_all_terms(op, ["AE", "Running", "No 3"])) or val_num(excel, find_key_fuzzy(excel, ["AE3 Running"]))
    out["ae3_calculated_e_power"] = val_num(op, find_key_all_terms(op, ["AE", "Power",   "No 3"])) or val_num(excel, find_key_fuzzy(excel, ["AE3 Power"]))
    out["ae3_calc_load"]          = val_num(op, find_key_all_terms(op, ["AE", "Load",    "No 3"])) or val_num(excel, find_key_fuzzy(excel, ["AE3 Load"]))

    out["bl1_running_hrs"]    = val_num(op, find_key_fuzzy(op, ["Boiler", "Running"])) or val_num(excel, find_key_fuzzy(excel, ["BL1 Running"]))
    out["inc1_running_hrs"]   = val_num(op, find_key_fuzzy(op, ["Incinerator", "Running"])) or val_num(excel, find_key_fuzzy(excel, ["INC1 Running"]))
    out["eg1_running_hrs"]    = val_num(op, find_key_fuzzy(op, ["Emergency", "Running"])) or val_num(excel, find_key_fuzzy(excel, ["EG1 Running"]))
    out["combl1_running_hrs"] = val_num(op, find_key_fuzzy(op, ["Composite", "Running"])) or val_num(excel, find_key_fuzzy(excel, ["COMBL1 Running"]))

    # --- FUEL CONSUMPTION ---
    cons_tab = tabs["cons"]
    fuel_categories = {
        "me":    ["Main Engine", "M/E"],
        # MariApps uses "Auxilary Engine" (note typo — one 'i') in Excel_Data keys.
        # Put "Auxilary Engine" first so get_fuel() fallback picks it up via substring match.
        "ae":    ["Auxilary Engine", "Auxiliary Engine", "Aux Engine", "A/E"],
        "bl":    ["Boiler"],
        "inc":   ["Incinerator"],
        "eg":    ["Emergency Gen", "E/G"],
        "combl": ["Composite Boiler"],
        "aeb":   ["AE Boiler", "AE/B"],
        "blfo":  ["Bunker", "BLFO"],
    }
    fuel_types = {
        "hfo":         ["HFO", "Heavy"],
        "lfo":         ["LFO", "Light"],
        "mdo":         ["MDO", "MGO", "Diesel"],
        "lpg_propane": ["LPG", "Propane"],
        "lpg_butane":  ["LPG", "Butane"],
        "lng":         ["LNG"],
        "methanol":    ["Methanol"],
        "ethanol":     ["Ethanol"],
        "ammonia":     ["Ammonia"],
        "bio_fuel":    ["Bio"],
    }

    for cat_prefix, cat_search_terms in fuel_categories.items():
        total_cons = 0.0
        found_any  = False
        for fuel_prefix, fuel_search_terms in fuel_types.items():
            key_cons = find_key_all_terms(cons_tab, cat_search_terms + fuel_search_terms)
            val = None
            if key_cons and cons_tab.get(key_cons) not in (None, ""):
                val = val_num(cons_tab, key_cons)
            if val is None:
                val = get_fuel(excel, cat_search_terms[0], fuel_search_terms[0])

            out[f"{cat_prefix}_{fuel_prefix}"] = val
            if val is not None:
                total_cons += val
                found_any = True

        if found_any:
            out[f"{cat_prefix}_total_cons"] = total_cons

    return out

# ===========================================================================
# 5. KPI CALCULATION (P_wind, P_wave, P_temp, VTI, Power_Dev, Speed_Loss)
#
#  vessel_particulars columns used:
#    transverse_projected_area, length_bp, beam, total_propulsive_efficiency
#    baseline_coeff_a_laden/ballast, baseline_exponent_n_laden/ballast
#    reference_draft_laden/ballast
#    wind_coeff_cx_0/30/60/90/120/150/180  (interpolated by rel wind direction)
# ===========================================================================

# Wind coefficient angle table — maps angle (deg) to VP column name
_WIND_COEFF_ANGLES = [
    (0,   "wind_coeff_cx_0"),
    (30,  "wind_coeff_cx_30"),
    (60,  "wind_coeff_cx_60"),
    (90,  "wind_coeff_cx_90"),
    (120, "wind_coeff_cx_120"),
    (150, "wind_coeff_cx_150"),
    (180, "wind_coeff_cx_180"),
]

def _interpolate_wind_cx(vp: dict, rel_wind_dir_deg) -> float:
    """
    Interpolate Wind Coefficient C_X from vessel_particulars directional columns
    based on relative wind direction (0–360°). Uses linear interpolation between
    the two nearest tabulated angles (mirrored for 180–360° range).
    Returns None if required columns are missing.
    """
    if rel_wind_dir_deg is None:
        return None

    # Normalise to 0–180° (symmetric about ship centreline)
    angle = float(rel_wind_dir_deg) % 360
    if angle > 180:
        angle = 360 - angle

    # Find bracketing angles
    lower_angle, lower_col = _WIND_COEFF_ANGLES[0]
    upper_angle, upper_col = _WIND_COEFF_ANGLES[-1]
    for i in range(len(_WIND_COEFF_ANGLES) - 1):
        a0, c0 = _WIND_COEFF_ANGLES[i]
        a1, c1 = _WIND_COEFF_ANGLES[i + 1]
        if a0 <= angle <= a1:
            lower_angle, lower_col = a0, c0
            upper_angle, upper_col = a1, c1
            break

    cx_lower = vp.get(lower_col)
    cx_upper = vp.get(upper_col)

    if cx_lower is None and cx_upper is None:
        return None
    if cx_lower is None:
        return cx_upper
    if cx_upper is None:
        return cx_lower

    # Linear interpolation
    if upper_angle == lower_angle:
        return cx_lower
    t = (angle - lower_angle) / (upper_angle - lower_angle)
    return cx_lower + t * (cx_upper - cx_lower)


def _get_baseline_params(vp: dict, loading_cond) -> tuple:
    """
    Return (coeff_a, exponent_n, reference_draft) based on loading condition.
    Tries to detect laden vs ballast from Loading_Cond string.
    Falls back to whichever set is available if condition is unclear.
    Returns (None, None, None) if nothing available.
    """
    cond = str(loading_cond).lower().strip() if loading_cond else ""
    is_ballast = "ballast" in cond
    is_laden   = any(w in cond for w in ["laden", "loaded", "full"])

    laden_params   = (
        vp.get("baseline_coeff_a_laden"),
        vp.get("baseline_exponent_n_laden"),
        vp.get("reference_draft_laden"),
    )
    ballast_params = (
        vp.get("baseline_coeff_a_ballast"),
        vp.get("baseline_exponent_n_ballast"),
        vp.get("reference_draft_ballast"),
    )

    if is_ballast:
        # Use ballast; fall back to laden if ballast is incomplete
        if all(v is not None for v in ballast_params):
            return ballast_params
        if all(v is not None for v in laden_params):
            log.warning("Ballast baseline params missing; falling back to laden params.")
            return laden_params
    elif is_laden:
        # Use laden; fall back to ballast if laden is incomplete
        if all(v is not None for v in laden_params):
            return laden_params
        if all(v is not None for v in ballast_params):
            log.warning("Laden baseline params missing; falling back to ballast params.")
            return ballast_params
    else:
        # Condition unclear — use whichever set is fully populated
        if all(v is not None for v in laden_params):
            return laden_params
        if all(v is not None for v in ballast_params):
            return ballast_params

    return (None, None, None)


def calculate_kpis(analysis_row: dict, vessel_particulars: dict = None) -> dict:
    """
    Calculate performance KPIs using analysis row values + vessel_particulars.

    vessel_particulars must be a plain dict with column names matching the
    VesselParticulars ORM model (snake_case).

    Returns dict:
        P_wind_kW, P_wave_kW, P_temp_kW, VTI, Power_Dev_pct, Speed_Loss_pct
    Each value is None if required inputs are missing.
    """
    vp  = vessel_particulars or {}
    out = {
        "P_wind_kW": None, "P_wave_kW": None, "P_temp_kW": None,
        "VTI": None, "Power_Dev_pct": None, "Speed_Loss_pct": None,
    }

    # --- values from analysis_row ---
    stw           = analysis_row.get("STW_kn")
    shaft_power   = analysis_row.get("Shaft_Power_kW")
    rel_wind_spd  = analysis_row.get("Rel_Wind_Spd_ms")
    rel_wind_dir  = analysis_row.get("Rel_Wind_Dir_deg")
    sig_wave_ht   = analysis_row.get("Sig_Wave_Ht_m")
    wave_period   = analysis_row.get("Wave_Period_s")
    water_temp    = analysis_row.get("Water_Temp_C")
    mean_draft    = analysis_row.get("Mean_Draft_m")
    loading_cond  = analysis_row.get("Loading_Cond")

    # --- vessel_particulars columns (snake_case, direct from ORM/dict) ---
    trans_area = vp.get("transverse_projected_area")
    lbp        = vp.get("length_bp")
    beam       = vp.get("beam")
    eta_prop   = vp.get("total_propulsive_efficiency")

    # Convert STW knots → m/s
    stw_ms = stw * 0.5144 if stw is not None else None

    # --- P_wind_kW ---
    # Formula: 0.5 * 1.225 * C_X * A_T * (Vrel² - Vship²) * Vship / 1000
    try:
        cx = _interpolate_wind_cx(vp, rel_wind_dir)
        if all(v is not None for v in [cx, trans_area, rel_wind_spd, stw_ms]):
            out["P_wind_kW"] = (
                0.5 * 1.225 * cx * trans_area
                * (rel_wind_spd**2 - stw_ms**2)
                * stw_ms / 1000
            )
        else:
            log.debug("P_wind_kW skipped — missing: cx=%s, trans_area=%s, rel_wind_spd=%s, stw_ms=%s",
                      cx, trans_area, rel_wind_spd, stw_ms)
    except (TypeError, ZeroDivisionError) as e:
        log.warning("P_wind_kW calculation error: %s", e)

    # --- P_wave_kW ---
    # Formula: 0.5 * 1025 * 0.05 * LBP * B * Hs² * (2π/Tw)² * Vship / (1000 * η)
    try:
        if all(v is not None for v in [lbp, beam, sig_wave_ht, wave_period, stw_ms, eta_prop]) \
                and wave_period != 0 and eta_prop != 0:
            omega = (2 * 3.14159 / wave_period) ** 2
            out["P_wave_kW"] = (
                0.5 * 1025 * 0.05
                * lbp * beam
                * (sig_wave_ht ** 2)
                * omega
                * stw_ms
                / (1000 * eta_prop)
            )
        else:
            log.debug("P_wave_kW skipped — missing: lbp=%s, beam=%s, sig_wave_ht=%s, "
                      "wave_period=%s, stw_ms=%s, eta_prop=%s",
                      lbp, beam, sig_wave_ht, wave_period, stw_ms, eta_prop)
    except (TypeError, ZeroDivisionError) as e:
        log.warning("P_wave_kW calculation error: %s", e)

    # --- P_temp_kW ---
    # Formula: Shaft_Power_kW * 0.002 * (15 - Water_Temp_C)
    try:
        if shaft_power is not None and water_temp is not None:
            out["P_temp_kW"] = shaft_power * 0.002 * (15 - water_temp)
        else:
            log.debug("P_temp_kW skipped — missing: shaft_power=%s, water_temp=%s",
                      shaft_power, water_temp)
    except TypeError as e:
        log.warning("P_temp_kW calculation error: %s", e)

    # --- VTI ---
    # Formula: Shaft_Power / (A * STW^n * (Mean_Draft / Ref_Draft)^0.67)
    try:
        coeff_a, exp_n, ref_draft = _get_baseline_params(vp, loading_cond)
        if all(v is not None for v in [coeff_a, exp_n, stw, mean_draft, ref_draft, shaft_power]) \
                and ref_draft != 0 and stw > 0:
            draft_ratio = (mean_draft / ref_draft) ** 0.67
            stw_power   = stw ** exp_n
            baseline_power = coeff_a * stw_power * draft_ratio
            vti_value = shaft_power / baseline_power if baseline_power != 0 else None
            log.warning(
                "[VTI_DEBUG] coeff_a=%s | exp_n=%s | stw=%s | stw^n=%s | "
                "mean_draft=%s | ref_draft=%s | draft_ratio=%s | "
                "baseline_power=%s | shaft_power=%s | VTI=%s | loading=%s",
                coeff_a, exp_n, stw, round(stw_power, 4),
                mean_draft, ref_draft, round(draft_ratio, 4),
                round(baseline_power, 4), shaft_power,
                round(vti_value, 4) if vti_value else None, loading_cond
            )
            out["VTI"] = vti_value
        else:
            log.debug("VTI skipped — missing: coeff_a=%s, exp_n=%s, stw=%s, "
                      "mean_draft=%s, ref_draft=%s, shaft_power=%s",
                      coeff_a, exp_n, stw, mean_draft, ref_draft, shaft_power)
    except (TypeError, ZeroDivisionError) as e:
        log.warning("VTI calculation error: %s", e)

    # --- Power_Dev_pct & Speed_Loss_pct (derived from VTI) ---
    vti = out["VTI"]
    try:
        if vti is not None:
            out["Power_Dev_pct"]  = (vti - 1) * 100
            out["Speed_Loss_pct"] = ((vti - 1) * 100) / 3
    except (TypeError, ZeroDivisionError) as e:
        log.warning("Power_Dev/Speed_Loss calculation error: %s", e)

    return out


# ===========================================================================
# 6. MAP TO 57-COLUMN ANALYSIS TABLE
# ===========================================================================

def map_mariapps_to_analysis(payload, excel_data=None, header_data=None, vessel_particulars=None):
    m160   = map_mariapps_to_160(payload, excel_data=excel_data, header_data=header_data)
    out    = {col: None for col in ANALYSIS_DATA_COLUMNS}
    excel  = excel_data  if excel_data  is not None else payload.get("Excel_Data", {})
    header = header_data if header_data is not None else {}

    tabs = _extract_tabs(payload)
    pos  = tabs["pos"]
    op   = tabs["op"]
    perf = tabs["perf"]
    mach = tabs["mach"]
    kpi  = tabs["kpi"]

    # 1. Basics
    out["Record_ID"] = val_str(header, find_key_fuzzy(header, ["Record ID"]))
    if pd.notnull(m160.get("log_date")):
        _d = m160["log_date"]
        if not hasattr(_d, "date"):
            _d = pd.to_datetime(_d)
        out["Date"] = _d.date()
        out["Time_UTC"] = m160["log_date"].strftime('%H:%M')

    out["Voyage_No"]  = m160["leg_number"]

    from_port_terms = ["Departure Port", "From Port", "Origin Port", "Port of Departure", "depPort", "departurePort"]
    out["From_Port"]  = (
        val_str(header,  find_key_fuzzy(header,  from_port_terms)) or
        val_str(payload, find_key_fuzzy(payload, from_port_terms)) or
        payload.get("depPort") or
        payload.get("departurePort")
    )
    out["To_Port"]      = m160["to_port"]
    out["Loading_Cond"] = m160["loading_condition"]

    # 2. Navigation
    # STW — Speed Through Water from the ship's speed log.
    # Operation_Data "ME Calculated Speed" is a shaft/propeller-derived estimate,
    # NOT a water speed measurement. It is intentionally removed as a fallback to
    # avoid confusing propeller speed with water speed.
    out["STW_kn"] = (
        val_num(pos,   find_key_fuzzy(pos,   ["Speed Through Water", "STW", "Speed Log", "Log Speed"])) or
        val_num(perf,  find_key_fuzzy(perf,  ["Speed Through Water"])) or
        val_num(excel, find_key_fuzzy(excel, ["Speed Through Water", "STW", "Speed Log"]))
        # NOTE: "ME Calculated Speed (Avg.)" from Operation_Data is excluded —
        # it is propeller-slip-derived, not a water speed log reading
    )
    out["SOG_kn"] = (
        val_num(pos,   find_key_fuzzy(pos,   ["Speed Over Ground", "SOG", "Speed OG", "Calculated Speed"])) or
        val_num(excel, find_key_fuzzy(excel, ["Speed Over Ground", "SOG", "Speed OG"])) or
        m160["speed_og"]
    )
    out["Heading_deg"] = m160["ship_heading"]
    out["Distance_nm"] = (
        val_num(pos,   find_key_fuzzy(pos,   ["Distance Over Ground", "Distance OG", "Distance Obs", "Distance (nm)"])) or
        val_num(excel, find_key_fuzzy(excel, ["Distance Over Ground", "Distance OG", "Distance Obs", "Distance (nm)"])) or
        m160["distance_og"]
    )
    out["Duration_h"] = m160["log_duration"]

    # 3. Drafts
    out["Draft_Fwd_m"]    = m160["draft_fwd"]
    out["Draft_Aft_m"]    = m160["draft_aft"]
    if out["Draft_Fwd_m"] and out["Draft_Aft_m"]:
        out["Mean_Draft_m"] = (out["Draft_Fwd_m"] + out["Draft_Aft_m"]) / 2
    out["Trim_m"]          = m160["trim"]
    out["Displacement_MT"] = m160["displacement"]

    # 4. Main Engine
    out["ME_Energy_Meter_Reading_KWh"] = (
    val_num(mach, find_key_all_terms(mach, ["ME", "Energy", "Meter"])) or
    val_num(op, find_key_fuzzy(op, ["Energy Produced - Value"]))
)
    # Shaft Power — taken from excel 'M/E Power (kW)' via m160["me1_power"]
    out["Shaft_Power_kW"] = m160.get("me1_power")
    out["Shaft_RPM"]                   = m160["me1_rpm"]
    out["ME_COMMON_MASS_FLOWMETER_MT"] = val_num(mach, find_key_all_terms(mach, ["ME", "Mass", "Flowmeter"]))

    # 5. Aux Engines
    out["AE_1_ENERGY_READING_KWh"] = val_num(mach, find_key_all_terms(mach, ["AE", "1", "Energy"]))
    out["A_E_1_RUNNING_HOURS"]     = m160["ae1_running_hrs"]
    out["AE_1_POWER_KW"]           = m160["ae1_calculated_e_power"]
    out["AE_2_ENERGY_READING_KWh"] = val_num(mach, find_key_all_terms(mach, ["AE", "2", "Energy"]))
    out["A_E_2_RUNNING_HOURS"]     = m160["ae2_running_hrs"]
    out["AE_2_POWER_KW"]           = m160["ae2_calculated_e_power"]
    out["AE_3_ENERGY_READING_KWh"] = val_num(mach, find_key_all_terms(mach, ["AE", "3", "Energy"]))
    out["A_E_3_RUNNING_HOURS"]     = m160["ae3_running_hrs"]
    out["AE_3_POWER_KW"]           = m160["ae3_calculated_e_power"]
    out["AE_MASS_FLOWMETER_IN"]     = val_num(mach, find_key_all_terms(mach, ["AE", "Flowmeter", "In"]))
    out["AE_FLOWMETER_READING_OUT"] = val_num(mach, find_key_all_terms(mach, ["AE", "Flowmeter", "Out"]))

    # 6. Fuel & Efficiency
    out["ME_FOC_MT"]    = m160.get("me_total_cons")
    out["AE_FOC_MT"]    = m160.get("ae_total_cons")
    out["Est_Power_kW"] = (
        val_num(perf, find_key_fuzzy(perf, ["Est Power", "Estimated Power", "Est. Power"])) or
        val_num(mach, find_key_fuzzy(mach, ["Est Power", "Estimated Power", "Est. Power"])) or
        val_num(op,   find_key_fuzzy(op,   ["Est Power", "Estimated Power"]))
    )
    if out["Shaft_Power_kW"] and out["Duration_h"] and out["ME_FOC_MT"]:
        try:
            out["SFOC_gkWh"] = (out["ME_FOC_MT"] * 1_000_000) / (out["Shaft_Power_kW"] * out["Duration_h"])
        except ZeroDivisionError:
            out["SFOC_gkWh"] = 0

    # 7. Environment
    out["Rel_Wind_Spd_ms"]  = val_num(perf, find_key_all_terms(perf, ["Rel", "Wind", "Speed"]))
    out["Rel_Wind_Dir_deg"] = val_num(perf, find_key_all_terms(perf, ["Rel", "Wind", "Dir"]))
    # Wind speed unit: MariApps Performance_Data stores wind speed in KNOTS (not m/s)
    # despite the field being named True_Wind_Spd_ms in analysis_data.
    # Convert kn → m/s (1 kn = 0.5144 m/s) so ISO 19030 filter (≤ 5.5 m/s) works correctly.
    # The JSON sample confirms: "True Wind Speed at Anemometer (Inst.)": "10" (knots)
    # and "True Wind Force (Bft)": "3" (Beaufort 3 ≈ 5.4 m/s ≈ 10.5 kn — consistent).
    _ws_raw = m160["wind_speed"]
    out["True_Wind_Spd_ms"]  = round(_ws_raw * 0.5144, 3) if _ws_raw else None
    out["True_Wind_Dir_deg"] = (
        val_num(perf,  find_key_fuzzy(perf,  ["True Wind Direction"])) or
        val_num(excel, find_key_fuzzy(excel, ["True Wind Direction"])) or
        (float(m160["wind_direction"]) if m160.get("wind_direction") else None)
    )
    out["Sig_Wave_Ht_m"]   = m160["wave_height"]
    out["Wave_Period_s"] = (
        val_num(perf, find_key_fuzzy(perf, ["Wave Period"])) or
        val_num(excel, find_key_fuzzy(excel, ["Wave Period"]))
    )
    out["Wave_Dir_deg"]    = val_num(perf, find_key_fuzzy(perf, ["Wave Direction"]))
    out["Swell_Ht_m"]      = val_num(perf, find_key_fuzzy(perf, ["Swell Height"]))
    out["Swell_Period_s"]  = val_num(perf, find_key_fuzzy(perf, ["Swell Period"]))
    out["Swell_Dir_deg"]   = val_num(perf, find_key_fuzzy(perf, ["Swell Direction"]))
    out["Water_Temp_C"]    = val_num(perf, find_key_fuzzy(perf, ["Sea Water Temperature", "Water Temperature", "Water Temp"]))
    out["Water_Depth_m"]   = val_num(perf, find_key_fuzzy(perf, ["Sea Water Depth", "Water Depth"]))
    out["Current_Spd_kn"]  = m160["current_speed"]
    out["Current_Dir_deg"] = val_num(perf, find_key_fuzzy(perf, ["Current Direction"]))
    out["Rudder_Angle_deg"]= val_num(perf, find_key_all_terms(perf, ["Rudder", "Angle"]))

    # 8. KPIs — calculated from formulas using vessel_particulars
    kpi_results = calculate_kpis(out, vessel_particulars)
    out["P_wind_kW"]      = kpi_results.get("P_wind_kW")
    out["P_wave_kW"]      = kpi_results.get("P_wave_kW")
    out["P_temp_kW"]      = kpi_results.get("P_temp_kW")
    out["VTI"]            = kpi_results.get("VTI")
    out["Power_Dev_pct"]  = kpi_results.get("Power_Dev_pct")
    out["Speed_Loss_pct"] = kpi_results.get("Speed_Loss_pct")

    return out