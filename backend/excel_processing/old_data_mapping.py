import warnings
import os
import re
import datetime
import pandas as pd
import numpy as np
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# =============================================================================
# CONFIGURATION
# =============================================================================
# --- LOCAL (original hardcoded paths — uncomment to use) ---
# INPUT_DIR  = r"C:\Users\visha\Downloads\ozellar\Data_ingestion_pipeline\backend\data\old_reports"
# OUTPUT_DIR = r"C:\Users\visha\Downloads\ozellar\Data_ingestion_pipeline\backend\excel_processing\output"
# --- VM / CROSS-PLATFORM (env var, defaults relative to this file) ---
_BASE_DIR  = os.path.dirname(os.path.abspath(__file__))          # backend/excel_processing
INPUT_DIR  = os.getenv("OLD_DATA_INPUT_DIR",  os.path.join(_BASE_DIR, "..", "data", "old_reports"))
OUTPUT_DIR = os.getenv("OLD_DATA_OUTPUT_DIR", os.path.join(_BASE_DIR, "output"))
TODAY = pd.Timestamp.today().normalize()

VESSEL_CONFIG = {
    "AM_KIRTI":     {"skiprows": 3, "name": "AM Kirti"},
    "AM_TARANG":    {"skiprows": 2, "name": "AM Tarang"},
    "AM_UMANG":     {"skiprows": 2, "name": "AM Umang"},
    "GCL_Ganga":    {"skiprows": 2, "name": "GCL Ganga"},
    "GCL_Narmada":  {"skiprows": 2, "name": "GCL Narmada"},
    "GCL_Sabarmati":{"skiprows": 2, "name": "GCL Sabarmati"},
    "GCL_Tapi":     {"skiprows": 2, "name": "GCL Tapi"},
    "GCL_Yamuna":   {"skiprows": 2, "name": "GCL Yamuna"},
}

OUTPUT_COLS = [
    "Record_ID", "Date", "Time_UTC", "Voyage_No", "From_Port", "To_Port",
    "Loading_Cond", "STW_kn", "SOG_kn", "Heading_deg", "Distance_nm",
    "Duration_h", "Draft_Fwd_m", "Draft_Aft_m", "Mean_Draft_m",
    "Displacement_MT", "Trim_m", "ME_Energy_Meter_Reading_KWh",
    "Shaft_Power_kW", "Shaft_RPM", "ME_COMMON_MASS_FLOWMETER_MT",
    "AE_1_ENERGY_READING_KWh", "A_E_1_RUNNING_HOURS", "AE_1_POWER_KW",
    "AE_2_ENERGY_READING_KWh", "A_E_2_RUNNING_HOURS", "AE_2_POWER_KW",
    "AE_3_ENERGY_READING_KWh", "A_E_3_RUNNING_HOURS", "AE_3_POWER_KW",
    "AE_MASS_FLOWMETER_IN", "AE_FLOWMETER_READING_OUT", "ME_FOC_MT",
    "AE_FOC_MT", "Est_Power_kW", "SFOC_gkWh", "Rel_Wind_Spd_ms",
    "Rel_Wind_Dir_deg", "True_Wind_Spd_ms", "True_Wind_Dir_deg",
    "Sig_Wave_Ht_m", "Wave_Period_s", "Wave_Dir_deg", "Swell_Ht_m",
    "Swell_Period_s", "Swell_Dir_deg", "Water_Temp_C", "Water_Depth_m",
    "Current_Spd_kn", "Current_Dir_deg", "Rudder_Angle_deg", "P_wind_kW",
    "P_wave_kW", "P_temp_kW", "VTI", "Power_Dev_pct", "Speed_Loss_pct",
]

SRC_IDX = {
    4: "Voyage_No", 5: "To_Port", 7: "_log_date_utc", 11: "Loading_Cond", 12: "Duration_h",
    13: "Distance_nm", 14: "SOG_kn", 26: "Draft_Fwd_m", 27: "Draft_Aft_m", 28: "Trim_m",
    33: "Shaft_RPM", 34: "Shaft_Power_kW", 36: "A_E_1_RUNNING_HOURS", 37: "AE_1_POWER_KW",
    39: "A_E_2_RUNNING_HOURS", 40: "AE_2_POWER_KW", 42: "A_E_3_RUNNING_HOURS", 43: "AE_3_POWER_KW",
    49: "ME_FOC_MT", 60: "AE_FOC_MT", 139: "Displacement_MT", 141: "Heading_deg",
    142: "_wind_speed_kn", 143: "True_Wind_Dir_deg", 144: "Current_Spd_kn", 145: "Current_Dir_deg",
    146: "Sig_Wave_Ht_m", 147: "Wave_Dir_deg", 148: "SFOC_gkWh",
}

def sanitize_text(value):
    if isinstance(value, str): return re.sub(r'[\000-\010\013\014\016-\037]', '', value)
    return value
def parse_utc(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return pd.NaT
    if isinstance(val, (datetime.datetime, pd.Timestamp)):
        return pd.Timestamp(val)
    if isinstance(val, (int, float)):
        return pd.to_datetime(val, unit='D', origin='1899-12-30')
    
    s = str(val).strip()
    # Split by - or / or space
    parts = re.split(r'[-/ ]', s)
    
    if len(parts) >= 3:
        try:
            p1, p2, p3 = int(parts[0]), int(parts[1]), int(parts[2])
            
            # Logic: 
            # If p1 (Day) is > 12, it MUST be the day.
            # If p2 (Month) is > 12, it MUST be the day, so swap p1 and p2.
            if p1 > 12:
                day, month, year = p1, p2, p3
            elif p2 > 12:
                day, month, year = p2, p1, p3
            else:
                # If both are <= 12, assume DD-MM-YYYY (your primary format)
                day, month, year = p1, p2, p3
                
            if year < 100: year += 2000
            return pd.Timestamp(year=year, month=month, day=day)
        except:
            return pd.NaT
    return pd.NaT
def write_excel(rows, path, vessel_name):
    df = pd.DataFrame(rows)
    df = df.reindex(columns=OUTPUT_COLS)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    df.to_excel(path, index=False)

def process_file(input_path, output_path, skiprows, vessel_name):
    df = pd.read_excel(input_path, header=None, skiprows=skiprows)
    rows = []
    for idx, row in df.iterrows():
        raw_list = row.tolist()
        if pd.isna(raw_list[7]): continue
        
        out = {col: None for col in OUTPUT_COLS}
        for csv_idx, field in SRC_IDX.items():
            if csv_idx < len(raw_list):
                val = raw_list[csv_idx]
                if field == "_log_date_utc":
                    ts = parse_utc(val)
                    if pd.notna(ts):
                        out["Date"] = ts.strftime("%Y-%m-%d")
                        out["Time_UTC"] = ts.strftime("%H:%M")
                        out["_sort_dt"] = ts # Keep this for sorting
                else: out[field] = sanitize_text(val) if isinstance(val, str) else val
        rows.append(out)
    
    # --- CRITICAL FIX: SORT BY DATE FIRST ---
    # This ensures the output Excel is in perfect chronological order
    rows.sort(key=lambda x: x.get("_sort_dt") or pd.Timestamp("9999-12-31"))
    
    # Voyage logic (From_Port)
    voyage_map = {}
    voyages = []
    for r in rows:
        v = str(r["Voyage_No"]) if r["Voyage_No"] else "Unknown"
        if v not in voyage_map:
            voyage_map[v] = []
            voyages.append(v)
        voyage_map[v].append(r)
    
    for i, v in enumerate(voyages):
        if i > 0:
            prev_to_port = next((r["To_Port"] for r in reversed(voyage_map[voyages[i-1]]) if r["To_Port"]), None)
            for r in voyage_map[v]: r["From_Port"] = prev_to_port
            
    # Remove the temporary sort key before writing
    for r in rows: r.pop("_sort_dt", None)
            
    write_excel(rows, output_path, vessel_name)
    print(f"[{vessel_name}] Processed {len(rows)} rows.")

def main():
    if not os.path.isdir(INPUT_DIR): return
    for filename in os.listdir(INPUT_DIR):
        if filename.lower().endswith(".xlsx"):
            for key, cfg in VESSEL_CONFIG.items():
                if key.lower().replace("_", " ") in filename.lower():
                    process_file(os.path.join(INPUT_DIR, filename), os.path.join(OUTPUT_DIR, f"{os.path.splitext(filename)[0]}_57col.xlsx"), cfg["skiprows"], cfg["name"])
                    break

if __name__ == "__main__":
    main()