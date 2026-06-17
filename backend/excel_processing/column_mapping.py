import pandas as pd
from backend.pipeline.mapping import val_num, val_str

# Define the mapping from your OLD EXCEL column names to the SYSTEM names
# Update the keys (left side) to match your actual Excel headers
OLD_REPORT_MAP = {
    "Vessel Name": "vessel_name",
    "Date of Report": "log_date",
    "Voyage No": "leg_number",
    "Report Type": "log_type",
    "Latitude": "lat_raw",
    "Longitude": "lon_raw",
    "Speed Observed": "speed_og",
    "Distance Run": "distance_og",
    "Draft Fwd": "draft_fwd",
    "Draft Aft": "draft_aft",
    "ME HFO Cons": "me_hfo",
    "ME MDO Cons": "me_mdo",
    "AE HFO Cons": "ae_hfo",
    "AE MDO Cons": "ae_mdo",
    "Wind Force (BF)": "true_wind_force",
    "Sea State": "wave_height"
}

def map_old_to_160(row_dict):
    """Maps a raw dictionary from Excel to the 160-column format."""
    out = {}
    # Use the helper from mapping.py to ensure data types are correct
    out["log_date"] = pd.to_datetime(row_dict.get("Date of Report"), errors='coerce')
    out["log_date_utc"] = out["log_date"]
    out["leg_number"] = val_str(row_dict, "Voyage No")
    out["log_type"] = val_str(row_dict, "Report Type")
    out["speed_og"] = val_num(row_dict, "Speed Observed")
    out["distance_og"] = val_num(row_dict, "Distance Run")
    out["draft_fwd"] = val_num(row_dict, "Draft Fwd")
    out["draft_aft"] = val_num(row_dict, "Draft Aft")
    out["me_hfo"] = val_num(row_dict, "ME HFO Cons")
    out["me_mdo"] = val_num(row_dict, "ME MDO Cons")
    out["me_total_cons"] = out["me_hfo"] + out["me_mdo"]
    
    # Add more fields as per your Excel structure...
    return out

def map_old_to_analysis(m160):
    """Maps the already processed 160-column data to the 57-column analysis format."""
    # You can reuse the logic from your existing analysis mappers
    out = {
        "Date": m160.get("log_date"),
        "SOG_kn": m160.get("speed_og"),
        "Distance_nm": m160.get("distance_og"),
        "Draft_Fwd_m": m160.get("draft_fwd"),
        "Draft_Aft_m": m160.get("draft_aft"),
        "ME_FOC_MT": m160.get("me_total_cons"),
    }
    return out