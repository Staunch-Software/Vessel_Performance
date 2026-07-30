import pandas as pd
from datetime import datetime
import logging

log = logging.getLogger(__name__)

# ============================================================
# AMNS TUFMAX Excel Parser
# ============================================================
# This Excel uses LDO (Main Engine fuel) and HFHSD (Aux Engine fuel).
# The sheet is transposed: rows = metrics, columns = days.
# Data columns start from index 8 (Column I).
# ============================================================

FUEL_KEY = "Fuel Consumption \nfor each Consumers at Each Fuel Type"

# Douglas Sea Scale -> approximate wave height in meters (midpoint of each range)
SEA_STATE_TO_METERS = {
    0: 0.0,    # Glassy
    1: 0.05,   # Rippled
    2: 0.3,    # Wavelets
    3: 0.875,  # Slight  (0.5 - 1.25 m)
    4: 2.0,    # Moderate (1.25 - 2.5 m)
    5: 3.25,   # Rough    (2.5 - 4 m)
    6: 5.0,    # Very Rough (4 - 6 m)
    7: 7.5,    # High     (6 - 9 m)
    8: 11.5,   # Very High (9 - 14 m)
    9: 14.0,   # Phenomenal (> 14 m)
}

# Maps the Excel 'Reporting Type' column values → standard log_type labels
# (same labels used by WNI and MariApps so the UI shows them identically)
TUFMAX_REPORT_TYPE_MAP = {
    # Specific dropdown items from TUFMAX template
    "arrival s/by engine": "EOSP",
    "finish with engine":  "Arrival Report",
    "last line let go":    "Departure Report",
    "r/up engine":         "BOSP",
    "let go anchor":       "Start Anchorage",
    "anchor aweigh":       "End Anchorage",
    "drifting start":      "Drifting Start",
    "drifting stop":       "Drifting Stop",
    "shifting":            "Shifting",
    "etc":                 "ETC",

    # Other manual/legacy options
    "noon at sea":   "Noon at sea",
    "port noon":     "Noon at port",
    "noon at port":  "Noon at port",
    "in port":       "Noon at port",
    "inport noon":   "Noon at port",
    "eosp":          "EOSP",
    "cosp":          "BOSP",
    "bosp":          "BOSP",
    "arrival":       "Arrival Report",
    "departure":     "Departure Report",
    "bunkering":     "Bunkering",
    "anchor":        "Start Anchorage",
}
def parse_tufmax_excel(file_content) -> list:
    """
    Parses the Tufmax Excel file (Report sheet).
    Extracts the transposed data where columns represent days.
    Maps it to the WNI format expected by the DB pipeline.
    """
    df = pd.read_excel(file_content, sheet_name='Report', header=None)
    
    parsed_records = []
    start_col = 8

    # ── Find the Reporting Type row index ────────────────────────────────────
    reporting_type_row_idx = -1
    for i in range(df.shape[0]):
        v0 = str(df.iloc[i, 0]).strip().lower()
        v1 = str(df.iloc[i, 1]).strip().lower() if df.shape[1] > 1 else ""
        if "reporting type" in v0 or "reporting type" in v1:
            reporting_type_row_idx = i
            break

    # ── Build metric_map: full_key -> row_index ─────────────────────────────
    metric_map = {}
    for idx, row in df.iterrows():
        main_label = str(row[2]).strip() if pd.notna(row[2]) else None
        
        # Clean up newlines to make it easier to match
        if main_label:
            clean_label = main_label.replace('\n', ' ').strip()
            # Also store the raw version
            metric_map[main_label] = idx
            metric_map[clean_label] = idx

    def get_val(full_key, c_idx, default=None):
        r_idx = None
        if full_key in metric_map:
            r_idx = metric_map[full_key]
        else:
            lbl_lower = full_key.lower().replace('\n', ' ').strip()
            for k, idx in metric_map.items():
                if lbl_lower in k.lower():
                    r_idx = idx
                    break
                    
        if r_idx is not None:
            val = df.iloc[r_idx, c_idx]
            if pd.isna(val) or str(val).strip() in ['', 'nan']:
                return default
            return val
        return default

    def get_num(full_key, c_idx, default=0.0):
        v = get_val(full_key, c_idx, default)
        try:
            f = float(v)
            return 0.0 if pd.isna(f) else f
        except (TypeError, ValueError):
            return default

    # ── Loop through each day column ─────────────────────────────────────────
    for c in range(start_col, df.shape[1]):
        date_val = get_val("Date & Time (Local)", c)
        if date_val is None:
            continue

        # Skip yearly ROB / non-daily summary columns
        date_str_raw = str(date_val)
        if "2027" in date_str_raw or "2026-01-01" in date_str_raw:
            continue

        # Format the date
        if isinstance(date_val, datetime):
            date_str = date_val.strftime("%Y-%m-%d %H:%M:%S")
        else:
            date_str = date_str_raw

        # ── Event Type ───────────────────────────────────────────────────────
        # Read 'Reporting Type' directly from the Excel row and map it to
        # the same standard labels used by WNI / MariApps.
        raw_report_type = ""
        if reporting_type_row_idx is not None:
            raw_report_type = str(df.iloc[reporting_type_row_idx, c]).strip()

        # Normalize and map directly from Excel dropdown value.
        mapped = TUFMAX_REPORT_TYPE_MAP.get(raw_report_type.lower())

        # Determine log_type based on whether the vessel is underway
        dist = get_num("Distance by Propelling during Hours Underway", c, 0)
        sog = get_num("Speed Over Ground (Daily AVG)", c, 0)
        hours = get_num("Daily Hours Underway", c, 0)
        
        # Location Text check (From/To, Position fields, and Port Name)
        loc_text = (
            str(get_val("From Port To Port", c, "")).upper() + " " + 
            str(get_val("Position (Lat)", c, "")).upper() + " " + 
            str(get_val("Port Name", c, "")).upper()
        )
        is_at_port = "AT " in loc_text or "PORT" in loc_text or "ANCHOR" in loc_text

        # Determine Event Type
        if mapped:
            event_type = mapped
        else:
            # Fallback for unrecognized (like "noon")
            # Dual-check: Must have 0 distance AND explicitly say they are at a port/anchor
            if dist == 0 and is_at_port:
                event_type = "Noon at port"
            else:
                event_type = "Noon at sea"


        # ── Loading Condition ────────────────────────────────────────────────
        lb_status = ""
        for lb_key, lb_lbl in [
            ("Vessel Condition_B", "BALLAST"),
            ("Vessel Condition_L", "LADEN"),
            ("Vessel Condition_D", "DOCK")
        ]:
            val = get_val(lb_key, c, None)
            if val is not None and str(val).strip() not in ["", "0", "False", "None", "nan"]:
                lb_status = lb_lbl
                break

        # ── Port: From Port To Port ──────────────────────────────────────────
        from_to = str(get_val("From Port To Port", c, "")).strip().upper()
        dest_port = ""
        orig_port = ""

        if "-" in from_to:
            parts = from_to.split("-")
            orig_port = parts[0].strip()
            dest_port = parts[-1].strip()
        elif " TO " in from_to:
            parts = from_to.split(" TO ")
            orig_port = parts[0].strip()
            dest_port = parts[-1].strip()
        elif from_to and from_to not in ["NAN", ""]:
            dest_port = from_to  # "AT CHENNAI", "ENROUTE HAZIRA", etc.

        # ── RPM: handle "ENGINE STOPPED" string ──────────────────────────────
        rpm_raw = get_val("RPM (Daily AVG)", c) or get_val("RPM", c)
        try:
            rpm = float(rpm_raw)
        except (TypeError, ValueError):
            rpm = 0.0  # ENGINE STOPPED or non-numeric

        # ── Shaft Power (Issue 8): Read from #1 Engine row (row 88) ──────────
        # Row 88 = Shaft Power #1 Engine; Row 90 = Shaft Power (#1+#2) combined
        def get_shaft_power_by_row(col_idx):
            # Try combined first (row 90), then #1 Engine (row 88)
            for row_idx in [90, 88]:
                try:
                    val = df.iloc[row_idx, col_idx]
                    if not pd.isna(val) and str(val).strip() not in ['', 'nan']:
                        return float(val)
                except (TypeError, ValueError, IndexError):
                    pass
            return 0.0
        shaft_power = get_shaft_power_by_row(c)

        # ── ETA (Issue 2): Row 44 = ETA (Date & Time / Local Time) ───────────
        eta_raw = get_val("ETA (Date & Time / Local Time)", c, None)
        eta_str = ""
        if eta_raw is not None:
            if isinstance(eta_raw, datetime):
                eta_str = eta_raw.strftime("%Y-%m-%d %H:%M")
            else:
                eta_str = str(eta_raw).strip()

        # ── Distance to Go (Issue 3): Row 45 ─────────────────────────────────
        distance_to_go = get_num("Distance to Go", c, 0)

        # ── Anchorage Hours (Issue 4): Row 57 ────────────────────────────────
        hours_at_anchor = get_num("Hours at Anchoring", c, 0)

        # ── Drifting Hours (Issue 5): Row 62 ─────────────────────────────────
        hours_at_drifting = get_num("Hours at Drifting", c, 0)

        # ── Relative Wind Speed/Dir (Issue 6): Rows 68, 71 ───────────────────
        rel_wind_speed = get_num("Relative Wind Speed", c, 0)
        rel_wind_dir   = get_num("Relative Wind Direction", c, 0)

        # ── Fuel: TUFMAX uses LDO (ME) and HFHSD (AE/GE) ────────────────────
        # The fuel table spans rows 100-134 with labels in columns 2,3,4.
        # Column 2 has the main section header (only on first row of section).
        # Column 3 has the consumer (M/E, G/E, BOILER, etc.)
        # Column 4 has the fuel type (HFO, VLSFO, LDO, HFHSD, MGO, etc.)
        # We read directly by row index to avoid ambiguous label matching.
        # Row 103 = M/E LDO, Row 113 = G/E HFHSD
        def get_fuel_by_row(row_idx, col_idx, default=0.0):
            try:
                val = df.iloc[row_idx, col_idx]
                if pd.isna(val) or str(val).strip() in ['', 'nan']:
                    return default
                return float(val)
            except (TypeError, ValueError, IndexError):
                return default

        me_ldo = get_fuel_by_row(103, c, 0.0)   # M/E LDO consumption
        ae_hfhsd = get_fuel_by_row(113, c, 0.0) # G/E HFHSD consumption

        # Fallback to named rows (older Excel templates may differ)
        if me_ldo == 0:
            me_ldo = get_num("Main Engine Consumption  (LDO) in Kilo Litres", c, 0)
        if ae_hfhsd == 0:
            ae_hfhsd = get_num("Auxiliary Engine Consumption  (HFHSD) in Kilo Litres", c, 0)

        # ── Drafts ───────────────────────────────────────────────────────────
        fwd = get_num("Draft Fwd", c, 0)
        aft = get_num("Draft Aft", c, 0)

        # ── Wind ─────────────────────────────────────────────────────────────
        bf_wind = get_num("BF Scale", c, 0)  # Row 76 BF Scale 12:00 today
        # True wind direction (Issue 7): Row 72 'True Wind Direction' is same
        # as 'True Wind Direction at Anemometer' — use directly
        true_wind_dir = get_num("True Wind Direction", c, 0)  # degrees
        true_wind_spd = get_num("True Wind Speed", c, 0)      # knots (Row 69)

        # ── Sea State → Wave Height (meters) ─────────────────────────────────
        # Noon to Noon AVG (row 79) is more reliable than 12:00 snapshot (row 78)
        sea_state_raw = get_num("Sea State", c, 0)
        # Try Noon to Noon AVG row (row 79) first
        try:
            sea_state_avg = df.iloc[79, c]
            if not pd.isna(sea_state_avg) and str(sea_state_avg).strip() not in ['', 'nan']:
                sea_state_raw = float(sea_state_avg)
        except (TypeError, ValueError, IndexError):
            pass
        try:
            sea_state_int = int(sea_state_raw)
            wave_height_m = SEA_STATE_TO_METERS.get(sea_state_int, round(sea_state_raw * 0.875, 2))
        except (ValueError, TypeError):
            wave_height_m = 0.0

        # ── Longitude Parsing (Issue 1) ───────────────────────────────────────
        # Position_Long raw format is e.g. "072-29 E" — store as-is; the
        # email_scraper / processor will split degrees/minutes/direction.
        pos_lat_raw  = str(get_val("Position (Lat)",  c, ""))
        pos_long_raw = str(get_val("Position (Long)", c, ""))

        record = {
            # ── Identity ──────────────────────────────────────────────────────
            "Date":                                     date_str,
            "Voyage Number_#":                          "",          # filled from email body
            "Destination Port_Dest. Port":              dest_port,
            "Departure Port_Orig. Port":                orig_port,
            "L/B":                                      lb_status,
            "Event Type":                               event_type,

            # ── Position (Issue 1: full lat/long including minutes) ────────────
            "Position_Lat":                             pos_lat_raw,
            "Position_Long":                            pos_long_raw,

            # ── Speed & Distance ──────────────────────────────────────────────
            "Speed_Reported Spd. (kts)":               sog,
            "Speed_TW Spd. (kts)":                    get_num("Speed through Water (Daily AVG)", c, 0),
            "Distance (nm)_Reported Distance (nm)":    dist,
            "Time Sailed (hrs)":                       hours,
            "Vessel Heading_Heading":                  get_num("Ship's Heading", c, 0),

            # ── ETA & Distance to Go (Issues 2 & 3) ──────────────────────────
            "ETA":                                     eta_str,
            "Distance to EOSP (nm)_Distance to Go":   distance_to_go,  # Issue 3: Distance to Go → Distance to EOSP

            # ── Port Hours (Issues 4 & 5) ─────────────────────────────────────
            "Hours at Anchoring":                      hours_at_anchor,   # Issue 4
            "Hours at Drifting":                       hours_at_drifting, # Issue 5

            # ── Wind (Issues 6 & 7) ───────────────────────────────────────────
            "Wind (WNI)_BF Wind":                      bf_wind,
            "Wind (WNI)_Wind Dir.":                    str(true_wind_dir),  # True Wind Dir (Issue 7)
            "Wind (WNI)_Wind Spd. (kts)":             true_wind_spd,       # True Wind Speed
            "Relative Wind Speed (kts)":               rel_wind_speed,      # Issue 6
            "Relative Wind Direction":                  str(rel_wind_dir),   # Issue 6

            # ── Sea State ─────────────────────────────────────────────────────
            "Wave (WNI)_Sig. Wave (m)":               wave_height_m,  # Converted from Sea State Douglas Scale
            "Wave (WNI)_Swell Dir.":                  "",

            # ── Current ───────────────────────────────────────────────────────
            "Current (WNI)_Current Speed (kts)":      get_num("Current Speed (Relative)", c, 0),
            "Current (WNI)_Current Dir":              str(get_num("Current Direction (Relative)", c, 0)),

            # ── Drafts & Displacement ─────────────────────────────────────────
            "Draft_FWD (m)":                          fwd,
            "Draft_AFT (m)":                          aft,
            "Draft_Displacement (mt)":                get_num("Displacement", c, 0),

            # ── Engine (Issue 8: shaft power from #1 Engine row) ──────────────
            "Engine_RPM":                             rpm,
            "Engine_M/E Power (kW)":                  shaft_power,

            # ── Fuel Consumption ──────────────────────────────────────────────
            # TUFMAX uses LDO (Main Engine) and HFHSD (Generator/AE) only.
            # LDO → stored in MGO column (distillate); HFHSD → AE MGO column
            "M/E Fuel Consumption_VLSFO (HFO/LFO) (mt)": 0,
            "M/E Fuel Consumption_ULSFO (mt)":            0,
            "M/E Fuel Consumption_MGO (>0.5%) (mt)":      me_ldo,    # LDO (M/E)

            "A/E Fuel Consumption_VLSFO (HFO/LFO) (mt)": 0,
            "A/E Fuel Consumption_ULSFO (mt)":            0,
            "A/E Fuel Consumption_MGO (>0.5%) (mt)":      ae_hfhsd,  # HFHSD (G/E)

            "Boiler Fuel Consumption_VLSFO (HFO) (mt)":  0,
            "Boiler Fuel Consumption_LSMGO (mt)":         0,

            # ── Water temp / depth ────────────────────────────────────────────
            "Sea Water Temp_\u00b0C":                  get_num("Sea Water Temp", c, 0),
            "Sea Water Depth_m":                      get_num("Sea Water Depth", c, 0),

            # ── Flag ──────────────────────────────────────────────────────────
            "is_manual_excel":                        True,
        }

        parsed_records.append(record)

    log.info(f"Parsed {len(parsed_records)} daily reports from Tufmax Excel.")
    return parsed_records
