import pandas as pd
import numpy as np
import math
import re

# ============================================================
# SAFE DATA EXTRACTION FUNCTIONS
# ============================================================

def val_num(row_dict, column_name, default=0.0):
    v = row_dict.get(column_name)
    v_num = pd.to_numeric(v, errors="coerce")
    return default if pd.isna(v_num) else float(v_num)

def val_str(row_dict, column_name, default=None):
    v = row_dict.get(column_name)
    if v is None or pd.isna(v):
        return default
    v_s = str(v).strip()
    return v_s if v_s != "" else default

# ============================================================
# REFERENCE DATA LOOKUPS
# ============================================================

WIND_DIR_MAP = {
    "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5, 
    "E": 90, "ESE": 112.5, "SE": 135, "SSE": 157.5, 
    "S": 180, "SSW": 202.5, "SW": 225, "WSW": 247.5, 
    "W": 270, "WNW": 292.5, "NW": 315, "NNW": 337.5
}

BEAUFORT_MAP = {
    0: 1, 1: 2, 2: 5, 3: 8.5, 4: 13.5, 5: 19, 
    6: 24.5, 7: 30.5, 8: 37, 9: 44, 10: 51.5, 
    11: 59.5, 12: 64
}

EVENT_TYPE_MAP = {
    "NOON": "Noon at sea",
    "INPORT NOON": "Noon at port",
    "EOSP": "EOSP",
    "COSP": "BOSP",
    "START ANCHOR": "Start Anchorage",
    "END ANCHOR": "End Anchorage",
    "BERTH": "Arrival Report",
    "UNBERTH": "Departure Report",
    "BUNKERING": "Bunkering",
    "START FUEL CHANGE": "Start Fuel Change",
    "END FUEL CHANGE": "End Fuel Change"
}

DIR_MAP = {"N": "North", "S": "South", "E": "East", "W": "West"}

def parse_coord(coord):
    if not isinstance(coord, str):
        return None, None, None
    try:
        coord = coord.replace("°", " ").replace("'", " ").strip()
        parts = coord.split()
        deg = float(parts[0])
        min_part = parts[1]
        if min_part[-1].isalpha():
            minutes = float(min_part[:-1])
            direction_raw = min_part[-1]
        else:
            minutes = float(min_part)
            direction_raw = parts[2]
        direction = DIR_MAP.get(direction_raw.upper(), direction_raw)
        return deg, minutes, direction
    except:
        return None, None, None

# ============================================================
# FUEL CONSUMPTION CALCULATION LOGIC
# ============================================================

def calculate_distillate_fuel(row, prefix):
    mdo_columns = [
        f"{prefix}_MGO (>0.5%) (mt)", f"{prefix}_MGO (≤0.5%) (mt)",
        f"{prefix}_MGO (>0.1%) (mt)", f"{prefix}_LSMGO (mt)",
        f"{prefix}_MDO (>0.5%) (mt)", f"{prefix}_MDO (≤0.5%) (mt)",
        f"{prefix}_MDO (>0.1%) (mt)", f"{prefix}_LSMDO (mt)"
    ]
    found_values = []
    for col in mdo_columns:
        val = pd.to_numeric(row.get(col), errors='coerce')
        if val and val > 0:
            found_values.append(float(val))
    if not found_values: return 0.0
    unique_values = set(found_values)
    return list(unique_values)[0] if len(unique_values) == 1 else sum(found_values)

def calculate_bl_hfo_smart(row):
    cols = ["Boiler Fuel Consumption_VLSFO (HFO) (mt)", "Boiler Fuel Consumption_VLSFO (LFO) (mt)"]
    found_values = []
    for col in cols:
        val = pd.to_numeric(row.get(col), errors='coerce')
        if val and val > 0: found_values.append(float(val))
    if not found_values: return 0.0
    unique_values = set(found_values)
    return list(unique_values)[0] if len(unique_values) == 1 else sum(found_values)

# ============================================================
# COLUMN DEFINITIONS
# ============================================================

MARI_APPS_COLUMNS = [
    "log_number", "validation_status", "validation_details", "status", "leg_number",
    "to_port", "is_closed", "log_date", "time_zone", "log_date_utc", "log_type",
    "loading_condition", "log_duration", "distance_og", "speed_og",
    "distance_to_eosp", "lat_degree", "lat_minutes", "lat_direction",
    "lon_degree", "lon_minutes", "lon_direction", "cargo_on_board",
    "anchorage_hours", "drifting_hours", "true_wind_force",
    "draft_fwd", "draft_aft", "trim", "eta", "etb", "ets",
    "me1_running_hrs", "me1_rpm", "me1_power", "mcr",
    "ae1_running_hrs", "ae1_calculated_e_power", "ae1_calc_load", 
    "ae2_running_hrs", "ae2_calculated_e_power", "ae2_calc_load", 
    "ae3_running_hrs", "ae3_calculated_e_power", "ae3_calc_load", 
    "bl1_running_hrs", "inc1_running_hrs", "eg1_running_hrs", "combl1_running_hrs", 
    "me_total_cons", "me_hfo", "me_lfo", "me_mdo", "me_lpg_propane", "me_lpg_butane", 
    "me_lng", "me_methanol", "me_ethanol", "me_ammonia", "me_bio_fuel", 
    "ae_total_cons", "ae_hfo", "ae_lfo", "ae_mdo", "ae_lpg_propane", "ae_lpg_butane", 
    "ae_lng", "ae_methanol", "ae_ethanol", "ae_ammonia", "ae_bio_fuel", 
    "bl_total_cons", "bl_hfo", "bl_lfo", "bl_mdo", "bl_lpg_propane", "bl_lpg_butane", 
    "bl_lng", "bl_methanol", "bl_ethanol", "bl_ammonia", "bl_bio_fuel", 
    "inc_total_cons", "inc_hfo", "inc_lfo", "inc_mdo", "inc_lpg_propane", 
    "inc_lpg_butane", "inc_lng", "inc_methanol", "inc_ethanol", "inc_ammonia", 
    "inc_bio_fuel", "eg_total_cons", "eg_hfo", "eg_lfo", "eg_mdo", "eg_lpg_propane", 
    "eg_lpg_butane", "eg_lng", "eg_methanol", "eg_ethanol", "eg_ammonia", 
    "eg_bio_fuel", "combl_total_cons", "combl_hfo", "combl_lfo", "combl_mdo", 
    "combl_lpg_propane", "combl_lpg_butane", "combl_lng", "combl_methanol", 
    "combl_ethanol", "combl_ammonia", "combl_bio_fuel", "aeb_total_cons", 
    "aeb_hfo", "aeb_lfo", "aeb_mdo", "aeb_lpg_propane", "aeb_lpg_butane", 
    "aeb_lng", "aeb_methanol", "aeb_ethanol", "aeb_ammonia", "aeb_bio_fuel", 
    "blfo_total_cons", "blfo_hfo", "blfo_lfo", "blfo_mdo", "blfo_lpg_propane", 
    "blfo_lpg_butane", "blfo_lng", "blfo_methanol", "blfo_ethanol", 
    "blfo_ammonia", "blfo_bio_fuel", "aft_draught", "fore_draught", 
    "displacement", "total_ballast_onboard", "ship_heading", 
    "wind_speed", "wind_direction", "current_speed", "current_direction", 
    "wave_height", "wave_direction", "m_e_iso_sfoc", "m_e_scoc", 
    "apparent_slip", "real_slip", "a_e_iso_sfoc", "nox_emitted", 
    "co2_emitted", "sox_emitted", "eeoi", 
    "mandatory_failed_reason", "field_validation_failed_reason", "rejected_remarks"
]

ANALYSIS_DATA_COLUMNS = [
    "Record_ID", "Date", "Time_UTC", "Voyage_No", "From_Port", "To_Port", 
    "Loading_Cond", "STW_kn", "SOG_kn", "Heading_deg", "Distance_nm", 
    "Duration_h", "Draft_Fwd_m", "Draft_Aft_m", "Mean_Draft_m", 
    "Displacement_MT", "Trim_m", "ME_Energy_Meter_Reading_KWh", "Shaft_Power_kW", 
    "Shaft_RPM", "ME_COMMON_MASS_FLOWMETER_MT", "AE_1_ENERGY_READING_KWh", 
    "A_E_1_RUNNING_HOURS", "AE_1_POWER_KW", "AE_2_ENERGY_READING_KWh", 
    "A_E_2_RUNNING_HOURS", "AE_2_POWER_KW", "AE_3_ENERGY_READING_KWh", 
    "A_E_3_RUNNING_HOURS", "AE_3_POWER_KW", "AE_MASS_FLOWMETER_IN", 
    "AE_FLOWMETER_READING_OUT", "ME_FOC_MT", "AE_FOC_MT", "Est_Power_kW", "SFOC_gkWh", 
    "Rel_Wind_Spd_ms", "Rel_Wind_Dir_deg", "True_Wind_Spd_ms", 
    "True_Wind_Dir_deg", "Sig_Wave_Ht_m", "Wave_Period_s", "Wave_Dir_deg", 
    "Swell_Ht_m", "Swell_Period_s", "Swell_Dir_deg", "Water_Temp_C", 
    "Water_Depth_m", "Current_Spd_kn", "Current_Dir_deg", "Rudder_Angle_deg", 
    "P_wind_kW", "P_wave_kW", "P_temp_kW", "VTI", "Power_Dev_pct", "Speed_Loss_pct",
    "BF_Wind"
]

# ============================================================
# MAIN MAPPING FUNCTIONS
# ============================================================

def map_row(row):
    out = {col: None for col in MARI_APPS_COLUMNS}
    out["log_date_utc"] = pd.to_datetime(row.get("Date"), errors='coerce')
    out["leg_number"] = val_str(row, "Voyage Number_#")
    out["to_port"] = val_str(row, "Destination Port_Dest. Port")
    out["loading_condition"] = val_str(row, "L/B")
    raw_ev = val_str(row, "Event Type", default="").upper()
    out["log_type"] = EVENT_TYPE_MAP.get(raw_ev, raw_ev)

    lat_d, lat_m, lat_dir = parse_coord(val_str(row, "Position_Lat"))
    lon_d, lon_m, lon_dir = parse_coord(val_str(row, "Position_Long"))
    out["lat_degree"], out["lat_minutes"], out["lat_direction"] = lat_d, lat_m, lat_dir
    out["lon_degree"], out["lon_minutes"], out["lon_direction"] = lon_d, lon_m, lon_dir

    out["speed_og"] = val_num(row, "Speed_Reported Spd. (kts)")
    out["distance_og"] = val_num(row, "Distance (nm)_Reported Distance (nm)")
    out["log_duration"] = val_num(row, "Time Sailed (hrs)")
    out["ship_heading"] = val_str(row, "Vessel Heading_Heading")

    out["true_wind_force"] = val_num(row, "Wind (WNI)_BF Wind")
    out["wind_direction"] = WIND_DIR_MAP.get(val_str(row, "Wind (WNI)_Wind Dir."))
    out["wave_height"] = val_str(row, "Wave (WNI)_Sig. Wave (m)")
    out["wave_direction"] = WIND_DIR_MAP.get(val_str(row, "Wave (WNI)_Swell Dir."))
    out["wind_speed"] = BEAUFORT_MAP.get(row.get("Wind (WNI)_BF Wind"))
    out["current_speed"] = val_num(row, "Current (WNI)_Current Speed (kts)")
    out["current_direction"] = val_str(row, "Current (WNI)_Current Dir")

    # Fuel Logic
    me_vlsfo = val_num(row, "M/E Fuel Consumption_VLSFO (HFO/LFO) (mt)")
    me_ulsfo = val_num(row, "M/E Fuel Consumption_ULSFO (mt)")
    out["me_hfo"] = me_vlsfo if me_vlsfo > 0 else me_ulsfo
    out["me_mdo"] = calculate_distillate_fuel(row, "M/E Fuel Consumption")
    out["me_total_cons"] = out["me_hfo"] + out["me_mdo"]

    ae_vlsfo = val_num(row, "A/E Fuel Consumption_VLSFO (HFO/LFO) (mt)")
    ae_ulsfo = val_num(row, "A/E Fuel Consumption_ULSFO (mt)")
    out["ae_hfo"] = ae_vlsfo if ae_vlsfo > 0 else ae_ulsfo
    out["ae_mdo"] = calculate_distillate_fuel(row, "A/E Fuel Consumption")
    out["ae_total_cons"] = out["ae_hfo"] + out["ae_mdo"]

    out["bl_hfo"] = calculate_bl_hfo_smart(row)
    out["bl_mdo"] = val_num(row, "Boiler Fuel Consumption_LSMGO (mt)")
    out["bl_total_cons"] = out["bl_hfo"] + out["bl_mdo"]

    out["me1_rpm"] = val_num(row, "Engine_RPM")
    out["me1_power"] = val_num(row, "Engine_M/E Power (kW)")
    out["mcr"] = val_str(row, "Engine_Thermal Load (%)")

    fwd, aft = val_num(row, "Draft_FWD (m)"), val_num(row, "Draft_AFT (m)")
    out["draft_fwd"], out["draft_aft"] = fwd, aft
    out["fore_draught"], out["aft_draught"] = fwd, aft
    out["trim"] = round(aft - fwd, 2) if (fwd > 0 and aft > 0) else 0.0
    out["displacement"] = val_num(row, "Draft_Displacement (mt)")

    return pd.Series(out)

def map_analysis_row(row, specs=None):
    out = {k: None for k in ANALYSIS_DATA_COLUMNS}

    def get_spec(attr, default=0.0):
        val = getattr(specs, attr, default)
        return val if val is not None else default

    # 1. Basics
    dt = pd.to_datetime(row.get("Date"), errors='coerce')
    if pd.notnull(dt):
        out["Date"], out["Time_UTC"] = dt.date(), dt.strftime('%H:%M')
    
    out["Voyage_No"] = val_str(row ,"Voyage Number_#")
    out["From_Port"] = val_str(row, "Departure Port_Orig. Port")
    out["To_Port"] = val_str(row, "Destination Port_Dest. Port")
    out["Loading_Cond"] = val_str(row, "L/B")

    # 2. Navigation
    stw_kn = val_num(row, "Speed_TW Spd. (kts)")
    sog_kn = val_num(row, "Speed_Reported Spd. (kts)")
    out["STW_kn"], out["SOG_kn"] = stw_kn, sog_kn
    out["Heading_deg"] = val_num(row, "Vessel Heading_Heading")
    out["Distance_nm"] = val_num(row, "Distance (nm)_Reported Distance (nm)")
    duration = val_num(row, "Time Sailed (hrs)")
    out["Duration_h"] = duration
    
    fwd, aft = val_num(row, "Draft_FWD (m)"), val_num(row, "Draft_AFT (m)")
    out["Draft_Fwd_m"], out["Draft_Aft_m"] = fwd, aft

    # 3. Engine Calculations (Using DB Specs)
    shaft_power_kw, rpm = val_num(row, "Engine_M/E Power (kW)"), val_num(row, "Engine_RPM")
    out["Shaft_Power_kW"], out["Shaft_RPM"] = shaft_power_kw, rpm
    
    mcr_kw, mcr_rpm = get_spec("me_engine_mcr_kw"), get_spec("me_mcr_rpm")
    if rpm > 0 and mcr_rpm > 0:
        out["Est_Power_kW"] = mcr_kw * (rpm / mcr_rpm)**get_spec("propeller_law_exponent", 3.0)

    me_foc = val_num(row, "M/E Fuel Consumption_VLSFO (HFO/LFO) (mt)") + calculate_distillate_fuel(row, "M/E Fuel Consumption")
    out["ME_FOC_MT"] = me_foc
    if shaft_power_kw > 0 and duration > 0:
        out["SFOC_gkWh"] = (me_foc / (shaft_power_kw * duration)) * 1000000

    # AE FOC — same logic as map_row() ae_total_cons
    ae_vlsfo = val_num(row, "A/E Fuel Consumption_VLSFO (HFO/LFO) (mt)")
    ae_ulsfo = val_num(row, "A/E Fuel Consumption_ULSFO (mt)")
    ae_hfo   = ae_vlsfo if ae_vlsfo > 0 else ae_ulsfo
    ae_mdo   = calculate_distillate_fuel(row, "A/E Fuel Consumption")
    out["AE_FOC_MT"] = ae_hfo + ae_mdo

    # 4. Environment (Using DB Specs)
    out["True_Wind_Dir_deg"] = WIND_DIR_MAP.get(val_str(row, "Wind (WNI)_Wind Dir."))

    # WNI-analyzed Beaufort — used by the CP fair-weather filter (BF <= 4).
    out["BF_Wind"] = val_num(row, "Wind (WNI)_BF Wind", default=None)

    out["Sig_Wave_Ht_m"] = val_num(row, "Wave (WNI)_Sig. Wave (m)")
    rel_wind_ms = val_num(row, "Wind (WNI)_Wind Spd. (kts)") * 0.5144

    if stw_kn > 0:
        out["P_wind_kW"] = 0.5 * 1.225 * get_spec("wind_coeff_cx_0", 0.8) * get_spec("transverse_projected_area") * (rel_wind_ms**2 - (stw_kn * 0.5144)**2) * (stw_kn * 0.5144) / 1000

    if stw_kn > 0 and out["Sig_Wave_Ht_m"] > 0:
        out["P_wave_kW"] = 0.5 * 1025 * 0.05 * get_spec("length_bp") * get_spec("beam") * (out["Sig_Wave_Ht_m"]**2) * (2 * 3.14159 / 8.0)**2 * (stw_kn * 0.5144) / (1000 * get_spec("total_propulsive_efficiency", 0.7))

    out["P_temp_kW"] = shaft_power_kw * 0.002 * (15 - 15.0) if shaft_power_kw > 0 else 0.0

    # 5. Draft & Displacement (Using DB Specs)
    if fwd > 0 and aft > 0:
        out["Mean_Draft_m"], out["Trim_m"] = round((fwd + aft) / 2, 2), round(aft - fwd, 2)
        if get_spec("design_draft") > 0:
            out["Displacement_MT"] = get_spec("displacement_at_design") + ((out["Mean_Draft_m"] - get_spec("design_draft")) * 100 * get_spec("tpc_at_design"))

    # 6. VTI & Speed Loss (Using DB Specs)
    is_laden = str(out["Loading_Cond"]).upper() == "L"
    coeff_a = get_spec("baseline_coeff_a_laden") if is_laden else get_spec("baseline_coeff_a_ballast")
    exp_n = get_spec("baseline_exponent_n_laden") if is_laden else get_spec("baseline_exponent_n_ballast")
    ref_draft = get_spec("reference_draft_laden") if is_laden else get_spec("reference_draft_ballast")

    # FIXED LINE: Use (out["Mean_Draft_m"] or 0)
    if stw_kn > 0 and (out["Mean_Draft_m"] or 0) > 0 and ref_draft > 0:
        baseline_pwr = coeff_a * (stw_kn ** exp_n) * (out["Mean_Draft_m"] / ref_draft) ** 0.67
        vti = shaft_power_kw / baseline_pwr if baseline_pwr > 0 else 0
        out["VTI"] = round(vti, 4)
        out["Power_Dev_pct"] = round((vti - 1) * 100, 2)
        out["Speed_Loss_pct"] = round(out["Power_Dev_pct"] / 3, 2)

    if stw_kn > 0 and sog_kn > 0:
        out["Current_Spd_kn"] = round(sog_kn - stw_kn, 2)

    return out