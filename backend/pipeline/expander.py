"""
expander.py
-----------
Creates and populates two flat "expanded" tables from the raw JSONB staging layers:
  - expanded_mariapps_data  (flattened from raw_mariapps_logs.raw_json)
  - expanded_wni_data       (flattened from raw_noon_reports.raw_json)

Column schema is driven by service_variable_mapping.py (generated from
service_variable_mapping.xlsx).  Every data column is named using the
New Column Name convention: CategoryShort_Symbol_operational_LF.
VoyageMeta_ prefix is used for non-standard MariApps voyage metadata fields.

Column metadata (display names, categories, active/inactive) is stored in
expanded_column_metadata and served to the frontend.
"""

import logging
import re

from sqlalchemy import text, inspect

from .mapping import map_row
from .service_variable_mapping import (
    MARIAPPS_TO_NEWCOL,
    WNI_TO_NEWCOL,
    NEWCOL_META,
    ALL_OPERATIONAL_COLUMNS,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Clean the column list — remove noisy / oversized columns once at import
# ---------------------------------------------------------------------------

# Regex to detect date-embedded or numeric-ID-embedded fallback column names
# e.g. ME_Lub_section2_918900_11306_mt_27_mar_2026_2109_operational_LF
_NOISY_COL_RE = re.compile(
    r'\d{2}_[a-z]{3}_\d{4}'   # date pattern: 27_mar_2026
    r'|_\d{6,}_'              # long numeric ID: _918900_
    r'|section\d+_\d',        # numbered section with digit: section2_9
    re.IGNORECASE,
)

_PG_MAX_IDENT = 63  # PostgreSQL maximum identifier length in bytes


def _clean_operational_columns(cols: list) -> list:
    """
    From ALL_OPERATIONAL_COLUMNS:
      1. Remove columns whose names contain date-embedded or noisy patterns.
      2. Truncate any remaining names to 63 chars (PostgreSQL max identifier).
      3. Deduplicate (keep first occurrence after truncation).
    Returns a clean, deduplicated list safe for CREATE TABLE.
    """
    seen: set = set()
    result: list = []
    for col in cols:
        if _NOISY_COL_RE.search(col):
            continue                          # skip date-embedded / noisy
        safe = col[:_PG_MAX_IDENT]            # truncate to PG limit
        if safe in seen:
            continue                          # deduplicate
        seen.add(safe)
        result.append(safe)
    return result


# Pre-built clean list used for both CREATE TABLE and write operations
CLEAN_OPERATIONAL_COLUMNS: list = _clean_operational_columns(ALL_OPERATIONAL_COLUMNS)

log.debug(
    f"Operational columns: {len(ALL_OPERATIONAL_COLUMNS)} raw → "
    f"{len(CLEAN_OPERATIONAL_COLUMNS)} after noise/dup filter"
)

# ---------------------------------------------------------------------------
# Identity column sets (never renamed, not in operational columns)
# ---------------------------------------------------------------------------

IDENTITY_MARIAPPS = {
    "id", "raw_log_id", "vessel_imo", "log_date", "log_type", "log_number",
    "source_id", "loading_condition",
}
IDENTITY_WNI = {
    "id", "raw_report_id", "vessel_imo", "date", "event_type", "voyage_no",
    "source_id", "loading_condition",
}

# WNI mapped columns that become identity columns instead of data columns
_WNI_IDENTITY_SKIP = {"log_date_utc", "log_type", "leg_number"}

# Only these NEWCOL names actually exist as data columns in expanded_wni_data
# (derived from WNI_TO_NEWCOL values, excluding __identity__ placeholders)
_WNI_VALID_DATA_COLS: set = {
    v for v in WNI_TO_NEWCOL.values()
    if v and v != "__identity__"
}

# Genuine WNI extras: fields WNI reports that have an EXISTING service-variable
# column (the same columns MariApps already populates) but which map_row() never
# produces. Mapped here directly from the raw WNI record so the WNI grid gains
# STW, engine slip and swell — without touching map_row() or the 160-col contract.
_WNI_EXTRA_MAP = {
    "Speed_TW Spd. (kts)":       "Vessel_STW_avg_operational_LF",        # Speed Through Water (Avg.)
    "Engine_Slip (%)":           "VoyageMeta_apparent_slip_operational_LF",  # Apparent Slip
    "Wave (WNI)_Swell Hgt. (m)": "Weather_Hsl_avg_operational_LF",       # Swell Height (Avg.)
}


def _wni_extra_fields(raw_json, table_cols) -> dict:
    """Pull WNI fields straight from raw_json into their target columns (only those
    physically present in the table). Covers both the original service-variable
    extras (_WNI_EXTRA_MAP) and the dedicated direct columns (_WNI_DIRECT_MAP).
    A raw key may legitimately appear in both maps (e.g. TW Spd. → service column
    *and* its own grouped column), so we iterate both."""
    out = {}
    if not isinstance(raw_json, dict):
        return out
    for mapping in (_WNI_EXTRA_MAP, _WNI_DIRECT_MAP):
        for raw_key, col in mapping.items():
            if col not in table_cols:
                continue
            sv = _safe_str(raw_json.get(raw_key))
            if sv is not None:
                out[col] = sv
    return out


# The extras' target columns must also be listed in WNI column metadata, otherwise
# the /expanded/wni route would never surface them in the grid.
_WNI_VALID_DATA_COLS |= set(_WNI_EXTRA_MAP.values())

# ── WNI direct fields (bypass the 160-col map_row bottleneck) ──────────────────
# These WNI noon fields exist in raw_noon_reports.raw_json but have no slot in the
# 160-col MARI_APPS_COLUMNS schema, so map_row() drops them. We surface them straight
# from raw_json into DEDICATED columns on expanded_wni_data (added via ALTER TABLE,
# no service-variable rebuild). Each tuple: (raw_json key, display name, category, unit).
# Column name is derived from the raw key with a `wnix_` prefix.
_WNI_DIRECT_FIELDS = [
    # Distance
    ("Distance (nm)_Reported Distance (nm)",            "Reported Distance",            "Distance (nm)",        "nm"),
    ("Time Sailed (hrs)",                               "Time Sailed",                  "Distance (nm)",        "hrs"),
    # Wind (Reported)
    ("Wind (Reported)_Relative Wind Dir.",              "Relative Wind Dir.",           "Wind (Reported)",      ""),
    ("Wind (Reported)_Wind Dir.",                       "Wind Dir.",                    "Wind (Reported)",      ""),
    ("Wind (Reported)_BF Wind",                         "BF Wind",                      "Wind (Reported)",      "Bft"),
    # Wind (WNI)
    ("Wind (WNI)_Relative Wind Dir.",                   "Relative Wind Dir.",           "Wind (WNI)",           ""),
    ("Wind (WNI)_Wind Dir.",                            "Wind Dir.",                    "Wind (WNI)",           ""),
    ("Wind (WNI)_BF Wind",                              "BF Wind",                      "Wind (WNI)",           "Bft"),
    # Wave (Reported)
    ("Wave (Reported)_Wind Seas (m)",                   "Wind Seas",                    "Wave (Reported)",      "m"),
    ("Wave (Reported)_Swell Dir.",                      "Swell Dir.",                   "Wave (Reported)",      ""),
    ("Wave (Reported)_Swell Hgt. (m)",                  "Swell Hgt.",                   "Wave (Reported)",      "m"),
    # Wave (WNI)  — source has no "Wind Seas"; closest is Sig. Wave (m)
    ("Wave (WNI)_Sig. Wave (m)",                        "Sig. Wave",                    "Wave (WNI)",           "m"),
    ("Wave (WNI)_Swell Dir.",                           "Swell Dir.",                   "Wave (WNI)",           ""),
    ("Wave (WNI)_Swell Hgt. (m)",                       "Swell Hgt.",                   "Wave (WNI)",           "m"),
    # Current (WNI)
    ("Current (WNI)_Relative Current Dir.",             "Relative Current Dir.",        "Current (WNI)",        ""),
    ("Current (WNI)_Current Factor (kts)",              "Current Factor",               "Current (WNI)",        "kts"),
    # Speed
    ("Speed_Reported Spd. (kts)",                       "Reported Spd.",                "Speed",                "kts"),
    ("Speed_Instructed Spd. (kts)",                     "Instructed Spd.",              "Speed",                "kts"),
    ("Speed_Diff. Reported - Instructed (kts)",         "Diff. Reported - Instructed",  "Speed",                "kts"),
    ("Speed_TW Spd. (kts)",                             "TW Spd.",                      "Speed",                "kts"),
    ("Speed_TW Spd. - Instructed (kts)",                "TW Spd. - Instructed",         "Speed",                "kts"),
    # Fuel Efficiency
    ("Fuel Efficiency_NM/Ton (nm)",                     "NM/Ton",                       "Fuel Efficiency",      "nm"),
    ("Fuel Efficiency_Ton / NM (nm)",                   "Ton/NM",                       "Fuel Efficiency",      "nm"),
    # M/E Fuel Consumption
    ("M/E Fuel Consumption_HSFO (>0.5%) (mt)",          "HSFO (>0.5%)",                 "M/E Fuel Consumption", "mt"),
    ("M/E Fuel Consumption_VLSFO (HFO) (mt)",           "VLSFO (HFO)",                  "M/E Fuel Consumption", "mt"),
    ("M/E Fuel Consumption_VLSFO (HFO/LFO) (mt)",       "VLSFO (HFO/LFO)",              "M/E Fuel Consumption", "mt"),
    ("M/E Fuel Consumption_MGO (>0.1%) (mt)",           "MGO (>0.1%)",                  "M/E Fuel Consumption", "mt"),
    ("M/E Fuel Consumption_LSMGO (mt)",                 "LSMGO",                        "M/E Fuel Consumption", "mt"),
    ("M/E Fuel Consumption_MDO (>0.1%) (mt)",           "MDO (>0.1%)",                  "M/E Fuel Consumption", "mt"),
    ("M/E Fuel Consumption_Bio (mt)",                   "Bio",                          "M/E Fuel Consumption", "mt"),
    # A/E Fuel Consumption
    ("A/E Fuel Consumption_HSFO (>0.5%) (mt)",          "HSFO (>0.5%)",                 "A/E Fuel Consumption", "mt"),
    ("A/E Fuel Consumption_VLSFO (LFO) (mt)",           "VLSFO (LFO)",                  "A/E Fuel Consumption", "mt"),
    ("A/E Fuel Consumption_VLSFO (HFO/LFO) (mt)",       "VLSFO (HFO/LFO)",              "A/E Fuel Consumption", "mt"),
    ("A/E Fuel Consumption_MGO (>0.1%) (mt)",           "MGO (>0.1%)",                  "A/E Fuel Consumption", "mt"),
    ("A/E Fuel Consumption_LSMGO (mt)",                 "LSMGO",                        "A/E Fuel Consumption", "mt"),
    ("A/E Fuel Consumption_MDO (>0.1%) (mt)",           "MDO (>0.1%)",                  "A/E Fuel Consumption", "mt"),
    ("A/E Fuel Consumption_Bio (mt)",                   "Bio",                          "A/E Fuel Consumption", "mt"),
    # Boiler Fuel Consumption
    ("Boiler Fuel Consumption_HSFO (>0.5%) (mt)",       "HSFO (>0.5%)",                 "Boiler Fuel Consumption", "mt"),
    ("Boiler Fuel Consumption_VLSFO (LFO) (mt)",        "VLSFO (LFO)",                  "Boiler Fuel Consumption", "mt"),
    ("Boiler Fuel Consumption_MGO (>0.1%) (mt)",        "MGO (>0.1%)",                  "Boiler Fuel Consumption", "mt"),
    ("Boiler Fuel Consumption_LSMGO (mt)",              "LSMGO",                        "Boiler Fuel Consumption", "mt"),
    ("Boiler Fuel Consumption_MDO (>0.1%) (mt)",        "MDO (>0.1%)",                  "Boiler Fuel Consumption", "mt"),
    ("Boiler Fuel Consumption_Bio (mt)",                "Bio",                          "Boiler Fuel Consumption", "mt"),
    # IGG and GCU Consumption
    ("IGG and GCU Consumption_HSFO (>0.5%) (mt)",       "HSFO (>0.5%)",                 "IGG and GCU Consumption", "mt"),
    ("IGG and GCU Consumption_MGO (>0.1%) (mt)",        "MGO (>0.1%)",                  "IGG and GCU Consumption", "mt"),
    ("IGG and GCU Consumption_MDO (>0.1%) (mt)",        "MDO (>0.1%)",                  "IGG and GCU Consumption", "mt"),
    # Cargo Heating Fuel Consumption
    ("Cargo Heating Fuel Consumption_HSFO (>0.5%) (mt)","HSFO (>0.5%)",                 "Cargo Heating Fuel Consumption", "mt"),
    ("Cargo Heating Fuel Consumption_MGO (>0.1%) (mt)", "MGO (>0.1%)",                  "Cargo Heating Fuel Consumption", "mt"),
    ("Cargo Heating Fuel Consumption_MDO (>0.1%) (mt)", "MDO (>0.1%)",                  "Cargo Heating Fuel Consumption", "mt"),
    # Cargo Cooling Fuel Consumption
    ("Cargo Cooling Fuel Consumption_HSFO (>0.5%) (mt)","HSFO (>0.5%)",                 "Cargo Cooling Fuel Consumption", "mt"),
    ("Cargo Cooling Fuel Consumption_MGO (>0.1%) (mt)", "MGO (>0.1%)",                  "Cargo Cooling Fuel Consumption", "mt"),
    ("Cargo Cooling Fuel Consumption_MDO (>0.1%) (mt)", "MDO (>0.1%)",                  "Cargo Cooling Fuel Consumption", "mt"),
    # Engine
    ("Engine_RPM",                                      "RPM",                          "Engine",               "rpm"),
    ("Engine_Slip (%)",                                 "Slip",                         "Engine",               "%"),
    ("Engine_M/E Power (kW)",                           "M/E Power",                    "Engine",               "kW"),
    ("Engine_M/E Load (%)",                             "M/E Load",                     "Engine",               "%"),
    # Cargo
    ("Cargo_Type (Primary)",                            "Type (Primary)",               "Cargo",                ""),
    ("Cargo_Total Cargo Weight on Dep/Arr (mt)",        "Total Cargo Weight on Dep/Arr","Cargo",                "mt"),
    ("Cargo_Loaded (mt)",                               "Loaded",                       "Cargo",                "mt"),
    ("Cargo_Unloaded (mt)",                             "Unloaded",                     "Cargo",                "mt"),
    # ROB
    ("ROB_HSFO (>0.5%) (mt)",                           "HSFO (>0.5%)",                 "ROB",                  "mt"),
    ("ROB_VLSFO (LFO) (mt)",                            "VLSFO (LFO)",                  "ROB",                  "mt"),
    ("ROB_VLSFO (HFO/LFO) (mt)",                        "VLSFO (HFO/LFO)",              "ROB",                  "mt"),
    ("ROB_MGO (>0.1%) (mt)",                            "MGO (>0.1%)",                  "ROB",                  "mt"),
    ("ROB_LSMGO (mt)",                                  "LSMGO",                        "ROB",                  "mt"),
    ("ROB_MDO (>0.1%) (mt)",                            "MDO (>0.1%)",                  "ROB",                  "mt"),
    ("ROB_Bio (mt)",                                    "Bio",                          "ROB",                  "mt"),
    # Bunkered
    ("Bunkered_HSFO (>0.5%) (mt)",                      "HSFO (>0.5%)",                 "Bunkered",             "mt"),
    ("Bunkered_MGO (>0.1%) (mt)",                       "MGO (>0.1%)",                  "Bunkered",             "mt"),
    ("Bunkered_MDO (>0.1%) (mt)",                       "MDO (>0.1%)",                  "Bunkered",             "mt"),
    ("Bunkered_Bio (mt)",                               "Bio",                          "Bunkered",             "mt"),
    # Total Fuel Consumption
    ("Total Fuel Consumption_LFO (mt)",                 "LFO",                          "Total Fuel Consumption", "mt"),
    ("Total Fuel Consumption_GO (mt)",                  "GO",                           "Total Fuel Consumption", "mt"),
    ("Total Fuel Consumption_Bio (mt)",                 "Bio",                          "Total Fuel Consumption", "mt"),
    # Speed and Consumption Order
    ("Speed and Consumption Order_Speed (kts)",         "Speed",                        "Speed and Consumption Order", "kts"),
    ("Speed and Consumption Order_FO (mt)",             "FO",                           "Speed and Consumption Order", "mt"),
    ("Speed and Consumption Order_DO (mt)",             "DO",                           "Speed and Consumption Order", "mt"),
]


def _wnix_col(raw_key: str) -> str:
    """Derive a safe, unique dedicated column name from a raw WNI key."""
    s = re.sub(r"[^a-z0-9]+", "_", raw_key.lower()).strip("_")
    return ("wnix_" + s)[:_PG_MAX_IDENT]


# Build the dedicated-column metadata list + raw_key→column map.
# Kept SEPARATE from _WNI_EXTRA_MAP so the original service-variable extras
# (STW / slip / swell) keep populating their columns too — a raw key present in
# both maps fills both columns (see _wni_extra_fields).
_WNI_DIRECT_MAP = {}
_WNI_DIRECT_META = []
for _rk, _disp, _cat, _unit in _WNI_DIRECT_FIELDS:
    _c = _wnix_col(_rk)
    _WNI_DIRECT_MAP[_rk] = _c                      # populated via _wni_extra_fields()
    _WNI_DIRECT_META.append(
        {"col": _c, "display_name": _disp, "category": _cat, "unit": _unit}
    )
_WNI_DIRECT_COLS = [m["col"] for m in _WNI_DIRECT_META]
_WNI_VALID_DATA_COLS |= set(_WNI_DIRECT_COLS)

# Short prefix prepended to a direct column's display name so the grid header is
# self-describing (e.g. "M/E HSFO (>0.5%)" instead of an ambiguous "HSFO (>0.5%)").
# Categories whose own field names are already unique are left unprefixed.
_WNI_DISPLAY_PREFIX = {
    "Wind (Reported)":                "Wind (Rep.)",
    "Wind (WNI)":                     "Wind (WNI)",
    "Wave (Reported)":                "Wave (Rep.)",
    "Wave (WNI)":                     "Wave (WNI)",
    "M/E Fuel Consumption":           "M/E",
    "A/E Fuel Consumption":           "A/E",
    "Boiler Fuel Consumption":        "Boiler",
    "IGG and GCU Consumption":        "IGG/GCU",
    "Cargo Heating Fuel Consumption": "Cargo Heat.",
    "Cargo Cooling Fuel Consumption": "Cargo Cool.",
    "ROB":                            "ROB",
    "Bunkered":                       "Bunkered",
    "Total Fuel Consumption":         "Total Fuel",
    "Speed and Consumption Order":    "Order",
    "Cargo":                          "Cargo",
}


def _wni_direct_display(meta: dict) -> str:
    """Display name with a consumer/group prefix when needed for disambiguation."""
    prefix = _WNI_DISPLAY_PREFIX.get(meta["category"], "")
    name = meta["display_name"]
    if prefix and not name.startswith(prefix):
        return f"{prefix} {name}"
    return name
# Sentinel: presence of this dedicated column means the extras have been added.
_WNI_DIRECT_SENTINEL = _WNI_DIRECT_COLS[0] if _WNI_DIRECT_COLS else None

# Rebuild-detection sentinel: new schema has this column
_SCHEMA_SENTINEL = "Vessel_SOG_avg_operational_LF"

# ── Performance columns (NoonData + Calc Engine inputs/outputs) ───────────────
# These are the columns used as inputs to or outputs from the ISO 19030
# Calc Engine (Sheet 4) — equivalent to the NoonData (Sheet 3) inputs.
# performance = TRUE  →  shown as primary KPI / performance data
# performance = FALSE →  secondary / diagnostic data
_PERFORMANCE_COLUMNS = {
    # Vessel General — NoonData inputs
    "Vessel_STW_avg_operational_LF",
    "Vessel_STW_operational_LF",
    "Vessel_SOG_avg_operational_LF",
    "Vessel_SOG_operational_LF",
    "Vessel_STWcal_avg_operational_LF",
    "Vessel_SOGcal_avg_operational_LF",
    "Vessel_Ta_avg_operational_LF",          # Draft Aft
    "Vessel_Tf_avg_operational_LF",          # Draft Fwd
    "Vessel_DISP_avg_operational_LF",        # Displacement
    "Vessel_HEAD_avg_operational_LF",        # Ship Heading
    "Vessel_COG_avg_operational_LF",         # Course Over Ground
    "Vessel_ROT_avg_operational_LF",         # Rate of Turn
    "Vessel_DOG_dCnt_operational_LF",        # Distance Over Ground
    "Vessel_DTW_dCnt_operational_LF",        # Distance Through Water
    "Vessel_BallastTot_operational_LF",      # Total Ballast
    "Vessel_Cargo_onboard_operational_LF",   # Cargo Onboard
    "Vessel_AH_dCnt_operational_LF",         # Anchorage Hours
    "Vessel_DH_dCnt_operational_LF",         # Drifting Hours
    # Weather — NoonData inputs
    "Weather_Uwit_avg_operational_LF",       # True Wind Speed
    "Weather_Uwit_operational_LF",
    "Weather_Uwir_avg_operational_LF",       # Relative Wind Speed
    "Weather_psiwit_avg_operational_LF",     # True Wind Direction
    "Weather_psiwit_operational_LF",
    "Weather_psiwir_avg_operational_LF",     # Relative Wind Direction
    "Weather_Hwv_avg_operational_LF",        # Wave Height (Hs)
    "Weather_Hwv_operational_LF",
    "Weather_Twv_avg_operational_LF",        # Wave Period
    "Weather_psiwvt_avg_operational_LF",     # Wave Direction
    "Weather_Hsl_avg_operational_LF",        # Swell Height
    "Weather_Tsl_avg_operational_LF",        # Swell Period
    "Weather_Tsw_avg_operational_LF",        # Sea Water Temperature
    "Weather_Tsw_operational_LF",
    "Weather_Tair_avg_operational_LF",       # Air Temperature
    "Weather_Tair_operational_LF",
    "Weather_pair_avg_operational_LF",       # Barometric Pressure
    "Weather_pair_operational_LF",
    "Weather_hsw_avg_operational_LF",        # Water Depth
    "Weather_hsw_operational_LF",
    "Weather_Ucut_avg_operational_LF",       # Current Speed
    "Weather_psicut_avg_operational_LF",     # Current Direction
    # ME General — NoonData inputs (power source, RPM)
    "ME_NME_avg_operational_LF",             # ME Speed (RPM) — filled from calculated speed for MariApps
    "ME_NME_operational_LF",
    "ME_PSME_avg_operational_LF",            # ME Shaft Power
    "ME_PSME_operational_LF",
    "ME_PeffestME_avg_operational_LF",       # ME Estimated Effective Power
    "ME_PeffcalME_avg_operational_LF",       # ME Calculated Effective Power
    "ME_RHME_dCnt_operational_LF",           # ME Running Hours
    "ME_QME_avg_operational_LF",             # ME Torque
    "ME_mcrcalME_avg_operational_LF",        # ME Load (%)
    "ME_DESME_dCnt_operational_LF",          # ME Energy Produced
    "ME_DRME_dCnt_operational_LF",           # ME Total Revolutions
    # ME Fuel — NoonData inputs
    "ME_FO_mFOCME_dCnt_operational_LF",     # ME Mass FO Consumption (Total)
    "ME_FO_mFOCcalME_avg_operational_LF",   # ME Calculated Mass FOC
    # AE Fuel — NoonData inputs
    "AE_FO_mFOCAE_dCnt_operational_LF",     # AE Mass FO Consumption (Total)
    # Boiler — NoonData inputs
    "AuxBoiler_mFOCBL_dCnt_operational_LF", # Boiler Mass FO Consumption
    # VoyageMeta — NoonData inputs
    "VoyageMeta_log_durationh_operational_LF",
    "VoyageMeta_latitude_operational_LF",
    "VoyageMeta_longitude_operational_LF",
    "VoyageMeta_trimm_operational_LF",
    "VoyageMeta_real_slip_operational_LF",
    "VoyageMeta_eeoi_gco2mtnm_operational_LF",
    "VoyageMeta_to_port_operational_LF",
    "VoyageMeta_departure_port_last_leg_operational_LF",
    "VoyageMeta_arrival_port_current_leg_operational_LF",
}

# ---------------------------------------------------------------------------
# MariApps flattening
# ---------------------------------------------------------------------------

MARIAPPS_SECTIONS = {
    "Excel_Data":       "",
    "Operation_Data":   "op",
    "Performance_Data": "perf",
    "Position_Data":    "pos",
    "Consumption_Data": "cons",
    "KPI_Data":         "kpi",
    "Header_Data":      "hdr",
    "Machinery_Data":   "mach",
    "Fuel_Stock_Data":  "fuelstock",
}


def _to_snake(s: str, prefix: str = "") -> str:
    """Convert any string to a safe snake_case identifier."""
    s = re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")
    s = re.sub(r"_+", "_", s)
    if prefix:
        s = f"{prefix}_{s}"
    if s and s[0].isdigit():
        s = "f_" + s
    return s[:120]


def flatten_mariapps(raw_json: dict) -> dict:
    """
    Flatten all MariApps sub-objects into a single dict with snake_case keys.
    These keys are then translated to New Column Names via MARIAPPS_TO_NEWCOL.
    """
    result = {}
    for section, prefix in MARIAPPS_SECTIONS.items():
        sub = raw_json.get(section)
        if not sub or not isinstance(sub, dict):
            continue
        for k, v in sub.items():
            col = _to_snake(k, prefix)
            result[col] = str(v) if v is not None and not isinstance(v, (dict, list)) else (str(v) if v else None)
    # Also capture top-level keys (backward compat)
    for k, v in raw_json.items():
        if k in MARIAPPS_SECTIONS or k in ("raw_json",):
            continue
        col = _to_snake(k)
        if col not in result:
            result[col] = str(v) if v is not None and not isinstance(v, (dict, list)) else None
    return result


def _map_flat_to_newcols(flat: dict, mapping: dict, table_cols: set) -> dict:
    """
    Translate {source_field: value} → {new_column_name: value}
    using the provided mapping dict.  Only includes columns that exist in the table.
    Multiple source fields may map to the same new column (first non-null wins).
    """
    result = {}
    for src_key, val in flat.items():
        new_col = mapping.get(src_key)
        if not new_col or new_col == "__identity__":
            continue
        if new_col not in table_cols:
            continue
        # First non-null wins when multiple sources map to same column
        if new_col not in result or result[new_col] is None:
            result[new_col] = val
    return result


def _safe_str(val) -> str:
    """Convert value to TEXT, returning None for nulls/NaN/NaT."""
    if val is None:
        return None
    try:
        import pandas as pd
        if pd.isnull(val):
            return None
    except (TypeError, ValueError):
        pass
    s = str(val)
    return None if s in ("nan", "NaT", "None", "") else s


# ---------------------------------------------------------------------------
# Table DDL
# ---------------------------------------------------------------------------

def _col_defs_sql() -> str:
    """Return SQL column definitions for all 1376 operational columns (all TEXT)."""
    return ",\n    ".join(f'"{c}" TEXT' for c in CLEAN_OPERATIONAL_COLUMNS)


def _get_table_cols(conn, table_name: str) -> set:
    rows = conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_name = '{table_name}'"
    )).fetchall()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

def create_expanded_tables(engine):
    """Create expanded_mariapps_data, expanded_wni_data, and expanded_column_metadata."""
    col_defs = _col_defs_sql()
    insp = inspect(engine)
    existing = set(insp.get_table_names())

    with engine.connect() as conn:
        # Column metadata table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS expanded_column_metadata (
                id           SERIAL PRIMARY KEY,
                source       VARCHAR(20)  NOT NULL,
                db_column    VARCHAR(200) NOT NULL,
                display_name VARCHAR(500),
                category     VARCHAR(200),
                unit         VARCHAR(50),
                description  TEXT,
                is_active    BOOLEAN DEFAULT TRUE,
                is_identity  BOOLEAN DEFAULT FALSE,
                performance  BOOLEAN DEFAULT FALSE,
                sort_order   INTEGER DEFAULT 0,
                user_sort_order INTEGER,
                UNIQUE (source, db_column)
            )
        """))
        # Add performance column if table existed without it (migration)
        try:
            conn.execute(text(
                "ALTER TABLE expanded_column_metadata ADD COLUMN IF NOT EXISTS "
                "performance BOOLEAN DEFAULT FALSE"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add user_sort_order column (user-defined column order from the picker).
        # Kept separate from sort_order because populate_column_metadata() resets
        # sort_order on every startup; user_sort_order must survive restarts.
        try:
            conn.execute(text(
                "ALTER TABLE expanded_column_metadata ADD COLUMN IF NOT EXISTS "
                "user_sort_order INTEGER"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Force-update performance flag on existing rows from the known set
        # This runs every startup to keep the flag in sync with _PERFORMANCE_COLUMNS
        try:
            if _PERFORMANCE_COLUMNS:
                placeholders = ", ".join(f"'{c}'" for c in _PERFORMANCE_COLUMNS)
                conn.execute(text(
                    f"UPDATE expanded_column_metadata SET performance = TRUE  "
                    f"WHERE db_column IN ({placeholders})"
                ))
                conn.execute(text(
                    f"UPDATE expanded_column_metadata SET performance = FALSE "
                    f"WHERE db_column NOT IN ({placeholders})"
                ))
                conn.commit()
        except Exception as _e:
            log.debug(f"Performance flag update: {_e}")
            conn.rollback()

        if "expanded_mariapps_data" not in existing:
            conn.execute(text(f"""
                CREATE TABLE expanded_mariapps_data (
                    id          SERIAL PRIMARY KEY,
                    raw_log_id  INTEGER UNIQUE REFERENCES raw_mariapps_logs(id),
                    vessel_imo  VARCHAR(20),
                    log_date    DATE,
                    log_type    VARCHAR(100),
                    log_number  VARCHAR(100),
                    source_id   VARCHAR(50) DEFAULT 'mari_apps',
                    loading_condition VARCHAR(50),
                    {col_defs}
                )
            """))
            log.info(f"Created expanded_mariapps_data with {len(CLEAN_OPERATIONAL_COLUMNS)} data columns.")

        if "expanded_wni_data" not in existing:
            conn.execute(text(f"""
                CREATE TABLE expanded_wni_data (
                    id             SERIAL PRIMARY KEY,
                    raw_report_id  INTEGER UNIQUE REFERENCES raw_noon_reports(id),
                    vessel_imo     VARCHAR(20),
                    date           DATE,
                    event_type     VARCHAR(100),
                    voyage_no      VARCHAR(100),
                    source_id      VARCHAR(50) DEFAULT 'wni',
                    loading_condition VARCHAR(50),
                    {col_defs}
                )
            """))
            log.info(f"Created expanded_wni_data with {len(CLEAN_OPERATIONAL_COLUMNS)} data columns.")

        # Dedicated WNI direct columns (raw_json → expanded_wni_data, bypassing the
        # 160-col map_row schema). Idempotent — added if not already present.
        for c in _WNI_DIRECT_COLS:
            conn.execute(text(
                f'ALTER TABLE expanded_wni_data ADD COLUMN IF NOT EXISTS "{c}" TEXT'
            ))

        conn.commit()


# ---------------------------------------------------------------------------
# Column metadata
# ---------------------------------------------------------------------------

def populate_column_metadata(engine):
    """Populate expanded_column_metadata from NEWCOL_META."""
    entries = []

    # MariApps identity columns (log_date/log_type/log_number are real columns here)
    mari_identity = [
        ("vessel_imo",        "Vessel IMO",          "Identity", ""),
        ("log_date",          "Log Date",             "Identity", ""),
        ("log_type",          "Log Type",             "Identity", ""),
        ("log_number",        "Log Number",           "Identity", ""),
        ("source_id",         "Source",               "Identity", ""),
        ("loading_condition", "Loading Condition",    "Identity", ""),
        ("raw_log_id",        "Raw Log ID",           "Identity", ""),
    ]
    # WNI identity columns. WNI has NO log_date/log_type/log_number columns — those
    # were phantom empties duplicating date/event_type/voyage_no, so they're dropped.
    # raw_report_id is internal and not shown. The surviving columns carry the values.
    wni_identity = [
        ("vessel_imo",        "Vessel IMO",          "Identity", ""),
        ("source_id",         "Source",               "Identity", ""),
        ("loading_condition", "Loading Condition",    "Identity", ""),
        ("date",              "Log Date",             "Identity", ""),
        ("event_type",        "Log Type",             "Identity", ""),
        ("voyage_no",         "Voyage No",            "Identity", ""),
    ]

    for source in ("mari_apps", "wni"):
        so = 0
        # Identity cols
        id_cols = mari_identity if source == "mari_apps" else wni_identity
        for col, disp, cat, unit in id_cols:
            entries.append({
                "source": source, "db_column": col, "display_name": disp,
                "category": cat, "unit": unit, "description": disp,
                "is_active": True, "is_identity": True,
                "performance": False, "sort_order": so,
            })
            so += 1

        # Operational data columns
        for nc in CLEAN_OPERATIONAL_COLUMNS:
            # WNI table only has the ~160 columns mapped from WNI raw fields
            if source == "wni" and nc not in _WNI_VALID_DATA_COLS:
                continue
            meta = NEWCOL_META.get(nc, {})
            base_display = meta.get("display_name", nc)
            copy_no = meta.get("copy_no")
            if copy_no and str(copy_no) not in ("nan", ""):
                try:
                    copy_int = int(float(copy_no))
                    display_name = f"{base_display} — No. {copy_int}"
                except (ValueError, TypeError):
                    display_name = base_display
            else:
                display_name = base_display
            entries.append({
                "source":       source,
                "db_column":    nc,
                "display_name": display_name,
                "category":     meta.get("category_full", "Other"),
                "unit":         meta.get("unit", ""),
                "description":  base_display,
                "is_active":    meta.get("is_active", False),
                "is_identity":  False,
                "performance":  nc in _PERFORMANCE_COLUMNS,
                "sort_order":   so,
            })
            so += 1

        # WNI-only dedicated direct columns (raw_json → expanded_wni_data).
        # Active by default so the previously-missing WNI fields show in the grid.
        if source == "wni":
            for dm in _WNI_DIRECT_META:
                disp = _wni_direct_display(dm)
                entries.append({
                    "source":       source,
                    "db_column":    dm["col"],
                    "display_name": disp,
                    "category":     dm["category"],
                    "unit":         dm["unit"],
                    "description":  disp,
                    "is_active":    True,
                    "is_identity":  False,
                    "performance":  False,
                    "sort_order":   so,
                })
                so += 1

    with engine.connect() as conn:
        conn.execute(text("DELETE FROM expanded_column_metadata"))
        if entries:
            conn.execute(text("""
                INSERT INTO expanded_column_metadata
                    (source, db_column, display_name, category, unit,
                     description, is_active, is_identity, performance, sort_order)
                VALUES
                    (:source, :db_column, :display_name, :category, :unit,
                     :description, :is_active, :is_identity, :performance, :sort_order)
                ON CONFLICT (source, db_column) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    category     = EXCLUDED.category,
                    unit         = EXCLUDED.unit,
                    description  = EXCLUDED.description,
                    is_active    = EXCLUDED.is_active,
                    performance  = EXCLUDED.performance,
                    sort_order   = EXCLUDED.sort_order
            """), entries)
        conn.commit()

    log.info(f"Column metadata: {len(entries)} entries.")
    return len(entries)


# ---------------------------------------------------------------------------
# Upsert helper
# ---------------------------------------------------------------------------

def _upsert_row(conn, table: str, unique_col: str, record: dict):
    """Insert or update a single row using ON CONFLICT."""
    safe = {re.sub(r"[^a-zA-Z0-9]", "_", k): v for k, v in record.items()}
    col_map = {k: re.sub(r"[^a-zA-Z0-9]", "_", k) for k in record}

    cols_sql   = ", ".join(f'"{c}"' for c in record)
    vals_sql   = ", ".join(f":{col_map[c]}" for c in record)
    update_sql = ", ".join(
        f'"{c}" = EXCLUDED."{c}"'
        for c in record if c not in ("id", unique_col)
    )
    conn.execute(text(f"""
        INSERT INTO {table} ({cols_sql})
        VALUES ({vals_sql})
        ON CONFLICT ("{unique_col}") DO UPDATE SET {update_sql}
    """), safe)


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

def backfill_mariapps(engine, batch_size: int = 50):
    """Re-populate expanded_mariapps_data from raw_mariapps_logs using new column names."""
    with engine.connect() as conn:
        table_cols = _get_table_cols(conn, "expanded_mariapps_data")
        total = conn.execute(text("SELECT COUNT(*) FROM raw_mariapps_logs")).scalar()
        log.info(f"Backfilling expanded_mariapps_data ({total} rows) …")

        processed = errors = 0
        offset = 0
        while True:
            rows = conn.execute(text(
                "SELECT id, vessel_imo, log_date, log_type, log_number, raw_json "
                "FROM raw_mariapps_logs ORDER BY id LIMIT :lim OFFSET :off"
            ), {"lim": batch_size, "off": offset}).fetchall()
            if not rows:
                break

            for (rid, vessel_imo, log_date, log_type, log_number, raw_json) in rows:
                try:
                    flat     = flatten_mariapps(raw_json or {})
                    data_rec = _map_flat_to_newcols(flat, MARIAPPS_TO_NEWCOL, table_cols)

                    # Determine loading_condition from source data
                    lc = flat.get("loading_condition") or flat.get("op_loading_condition") or None

                    record = {
                        "raw_log_id":       rid,
                        "vessel_imo":       vessel_imo,
                        "log_date":         str(log_date)[:10] if log_date else None,
                        "log_type":         log_type,
                        "log_number":       log_number,
                        "source_id":        "mari_apps",
                        "loading_condition": lc,
                        **data_rec,
                    }
                    _upsert_row(conn, "expanded_mariapps_data", "raw_log_id", record)
                    processed += 1
                except Exception as exc:
                    conn.rollback()
                    log.error(f"  mariapps row {rid}: {exc}")
                    errors += 1

            conn.commit()
            offset += batch_size
            if offset % 500 == 0 or offset >= total:
                log.info(f"  mariapps: {min(offset, total)}/{total}")

    log.info(f"MariApps backfill: {processed} OK, {errors} errors.")
    return processed, errors


def backfill_wni(engine, batch_size: int = 50):
    """Re-populate expanded_wni_data from raw_noon_reports using new column names."""
    with engine.connect() as conn:
        table_cols = _get_table_cols(conn, "expanded_wni_data")
        total = conn.execute(text("SELECT COUNT(*) FROM raw_noon_reports")).scalar()
        log.info(f"Backfilling expanded_wni_data ({total} rows) …")

        processed = errors = 0
        offset = 0
        while True:
            rows = conn.execute(text(
                "SELECT id, vessel_imo, raw_json FROM raw_noon_reports "
                "ORDER BY id LIMIT :lim OFFSET :off"
            ), {"lim": batch_size, "off": offset}).fetchall()
            if not rows:
                break

            for (rid, vessel_imo, raw_json) in rows:
                try:
                    # Step 1: apply WNI→MariApps mapping (produces 160 MARI_APPS_COLUMNS)
                    mapped_160 = map_row(raw_json or {}).to_dict()

                    # Step 2: translate MARI_APPS_COLUMNS → New Column Names
                    data_rec = {}
                    for mari_col, val in mapped_160.items():
                        if mari_col in _WNI_IDENTITY_SKIP:
                            continue
                        new_col = WNI_TO_NEWCOL.get(mari_col)
                        if not new_col or new_col == "__identity__":
                            continue
                        if new_col not in table_cols:
                            continue
                        sv = _safe_str(val)
                        if new_col not in data_rec or data_rec[new_col] is None:
                            data_rec[new_col] = sv

                    # Step 3: identity columns
                    date_str = _safe_str(mapped_160.get("log_date_utc"))
                    if date_str and len(date_str) > 10:
                        date_str = date_str[:10]

                    record = {
                        "raw_report_id":    rid,
                        "vessel_imo":       vessel_imo,
                        "date":             date_str,
                        "event_type":       _safe_str(mapped_160.get("log_type")),
                        "voyage_no":        _safe_str(mapped_160.get("leg_number")),
                        "source_id":        "wni",
                        "loading_condition": _safe_str(mapped_160.get("loading_condition")),
                        **data_rec,
                        **_wni_extra_fields(raw_json, table_cols),
                    }
                    _upsert_row(conn, "expanded_wni_data", "raw_report_id", record)
                    processed += 1
                except Exception as exc:
                    conn.rollback()
                    log.error(f"  wni row {rid}: {exc}")
                    errors += 1

            conn.commit()
            offset += batch_size
            if offset % 500 == 0 or offset >= total:
                log.info(f"  wni: {min(offset, total)}/{total}")

    log.info(f"WNI backfill: {processed} OK, {errors} errors.")
    return processed, errors


# ---------------------------------------------------------------------------
# Live write (called from pipeline processors on each new record)
# ---------------------------------------------------------------------------

def write_expanded_mariapps(conn, raw_log_id, vessel_imo, log_date,
                             log_type, log_number, raw_json):
    """Flatten and upsert one MariApps record using new Service Variable column names."""
    try:
        table_cols = _get_table_cols(conn, "expanded_mariapps_data")
        flat       = flatten_mariapps(raw_json or {})
        data_rec   = _map_flat_to_newcols(flat, MARIAPPS_TO_NEWCOL, table_cols)
        lc = flat.get("loading_condition") or flat.get("op_loading_condition") or None
        record = {
            "raw_log_id":        raw_log_id,
            "vessel_imo":        vessel_imo,
            "log_date":          str(log_date)[:10] if log_date else None,
            "log_type":          log_type,
            "log_number":        log_number,
            "source_id":         "mari_apps",
            "loading_condition": lc,
            **data_rec,
        }
        _upsert_row(conn, "expanded_mariapps_data", "raw_log_id", record)
    except Exception as exc:
        log.error(f"write_expanded_mariapps error (raw_log_id={raw_log_id}): {exc}")


def write_expanded_wni(conn, raw_report_id, vessel_imo, raw_json):
    """Map WNI record through map_row() + WNI_TO_NEWCOL and upsert to expanded_wni_data."""
    try:
        table_cols  = _get_table_cols(conn, "expanded_wni_data")
        mapped_160  = map_row(raw_json or {}).to_dict()

        data_rec = {}
        for mari_col, val in mapped_160.items():
            if mari_col in _WNI_IDENTITY_SKIP:
                continue
            new_col = WNI_TO_NEWCOL.get(mari_col)
            if not new_col or new_col == "__identity__":
                continue
            if new_col not in table_cols:
                continue
            sv = _safe_str(val)
            if new_col not in data_rec or data_rec[new_col] is None:
                data_rec[new_col] = sv

        date_str = _safe_str(mapped_160.get("log_date_utc"))
        if date_str and len(date_str) > 10:
            date_str = date_str[:10]

        record = {
            "raw_report_id":    raw_report_id,
            "vessel_imo":       vessel_imo,
            "date":             date_str,
            "event_type":       _safe_str(mapped_160.get("log_type")),
            "voyage_no":        _safe_str(mapped_160.get("leg_number")),
            "source_id":        "wni",
            "loading_condition": _safe_str(mapped_160.get("loading_condition")),
            **data_rec,
            **_wni_extra_fields(raw_json, table_cols),
        }
        _upsert_row(conn, "expanded_wni_data", "raw_report_id", record)
    except Exception as exc:
        log.error(f"write_expanded_wni error (raw_report_id={raw_report_id}): {exc}")


# ---------------------------------------------------------------------------
# One-shot setup (called on app startup)
# ---------------------------------------------------------------------------

def setup_expanded_tables(engine):
    """
    Create tables, populate metadata, backfill existing data.

    Rebuild trigger: if expanded_wni_data lacks the schema sentinel column
    (Vessel_SOG_avg_operational_LF), the table is using the old column schema
    → drop both expanded tables and rebuild with new Service Variable schema.
    """
    insp     = inspect(engine)
    existing = set(insp.get_table_names())

    # ── Detect old schema and drop for rebuild ────────────────────────────────
    needs_rebuild = False
    for tbl in ("expanded_wni_data", "expanded_mariapps_data"):
        if tbl in existing:
            with engine.connect() as _c:
                cols = {r[0] for r in _c.execute(text(
                    f"SELECT column_name FROM information_schema.columns WHERE table_name='{tbl}'"
                ))}
            if _SCHEMA_SENTINEL not in cols:
                needs_rebuild = True
                break

    if needs_rebuild:
        log.info("Expanded tables use old schema — dropping and rebuilding with Service Variable Mapping schema …")
        with engine.connect() as _c:
            _c.execute(text("DROP TABLE IF EXISTS expanded_wni_data CASCADE"))
            _c.execute(text("DROP TABLE IF EXISTS expanded_mariapps_data CASCADE"))
            _c.commit()
        existing.discard("expanded_wni_data")
        existing.discard("expanded_mariapps_data")

    # ── Detect missing WNI direct columns → re-backfill WNI to populate them ──────
    wni_extras_missing = False
    if not needs_rebuild and "expanded_wni_data" in existing and _WNI_DIRECT_SENTINEL:
        with engine.connect() as _c:
            cols = {r[0] for r in _c.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='expanded_wni_data'"
            ))}
        if _WNI_DIRECT_SENTINEL not in cols:
            wni_extras_missing = True
            log.info("expanded_wni_data missing WNI direct columns — will add and backfill.")

    create_expanded_tables(engine)   # ALTERs the dedicated WNI columns into place

    need_backfill_m = "expanded_mariapps_data" not in existing
    need_backfill_w = "expanded_wni_data"       not in existing

    if need_backfill_m or need_backfill_w or needs_rebuild or wni_extras_missing:
        if need_backfill_m or needs_rebuild:
            backfill_mariapps(engine)
        if need_backfill_w or needs_rebuild or wni_extras_missing:
            backfill_wni(engine)

    populate_column_metadata(engine)
    log.info("Expanded tables setup complete.")
