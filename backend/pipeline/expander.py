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
from datetime import datetime

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

# ── MariApps direct fields — Consumption tab "Grade" columns ──────────────────
# Each fuel consumer's "Grade" cell on the Consumption tab's Fuel Oil grid is a
# COMPOSITE string, not a single value, e.g.:
#   "VLSFO / HFO/ 0.47%/ 369/ 971.900/ 74.12 MT/ 21-Jun-2026 21:45"
# = ISO Grade / Fuel Type / Sulphur% / Viscosity(cSt) / Density(kg/m3) / ROB after
#   (MT) / last bunkered date-time. Confirmed from 10+ real rows across multiple
# vessels — notably a Marine Diesel Oil row shows viscosity 3.25 and density
# 839.000 (correct for MDO, vs. VLSFO's ~200-370 cSt / ~940-995 kg/m3), which
# pins down field order unambiguously.
#
# The raw key already exists in mari_metadata.json/mariapps_col_map.json (e.g.
# "Consumption_Data.Section0::Composite Boiler::Grade" -> db_column
# cons_section0_composite_boiler_grade) and detail_extractor.py already scrapes
# it into raw_mariapps_logs.raw_json — but it was never actually reaching a
# usable column: the auto-generated MARIAPPS_TO_NEWCOL mapping collides all 4
# consumers' Grade values onto the SAME New Column Name as 3 unrelated fields
# (pressure/temperature/volume), and _map_flat_to_newcols() keeps only the
# first non-null of those competing sources. So today Grade is captured but not
# reliably surfaced anywhere. Rather than touch the generated
# service_variable_mapping.py (auto-regenerated from an .xlsx pair, not meant to
# be hand-edited), this bypasses it the same way _WNI_DIRECT_FIELDS does for WNI:
# dedicated columns added via ALTER TABLE, populated straight from raw_json.
_MARIAPPS_GRADE_CONSUMERS = [
    # (consumer key used in column names, exact MariApps label used in raw_json)
    ("composite_boiler", "Composite Boiler"),
    ("aux_engine",        "Aux Engine"),
    ("aux_boiler",        "Aux Boiler"),
    ("main_engine",        "Main Engine"),
]

# (subfield key, display name, unit)
_GRADE_SUBFIELDS = [
    ("iso_grade",         "ISO Grade",        ""),
    ("fuel_type",         "Fuel Type",        ""),
    ("sulphur_pct",       "Sulphur",          "%"),
    ("viscosity_cst",     "Viscosity",        "cSt"),
    ("density_kg_m3",     "Density",          "kg/m³"),
    ("rob_after_mt",      "ROB After",        "MT"),
    ("last_bunkered_at",  "Last Bunkered",    ""),
]

_CONSUMER_DISPLAY_PREFIX = {
    "composite_boiler": "Composite Boiler",
    "aux_engine":         "Aux Engine",
    "aux_boiler":         "Aux Boiler",
    "main_engine":         "Main Engine",
}


def _mariappsx_col(consumer_key: str, subfield_key: str) -> str:
    return (f"mariappsx_{consumer_key}_{subfield_key}")[:_PG_MAX_IDENT]


def _parse_grade_string(raw) -> dict:
    """Split one Consumption-tab Grade cell into its 7 sub-values. Returns a
    dict of all-None if raw is empty/missing or doesn't match the expected
    7-slash-separated shape — this is scraped free text off a live UI, not a
    guaranteed contract, so a shape mismatch is logged and skipped rather than
    ever raising and breaking the surrounding backfill/live-write."""
    empty = {sf: None for sf, _, _ in _GRADE_SUBFIELDS}
    if not raw or not isinstance(raw, str):
        return empty
    parts = [p.strip() for p in raw.split("/")]
    if len(parts) != 7:
        log.warning(f"[GRADE]    Unexpected Grade format ({len(parts)} part(s), expected 7): {raw!r}")
        return empty
    iso_grade, fuel_type, sulphur_raw, viscosity_raw, density_raw, rob_raw, last_bunkered_at = parts

    def _num(s):
        try:
            return float(re.sub(r"[^0-9.\-]", "", s))
        except (ValueError, TypeError):
            return None

    return {
        "iso_grade":        iso_grade or None,
        "fuel_type":        fuel_type or None,
        "sulphur_pct":      _num(sulphur_raw),
        "viscosity_cst":    _num(viscosity_raw),
        "density_kg_m3":    _num(density_raw),
        "rob_after_mt":     _num(rob_raw),
        "last_bunkered_at": last_bunkered_at or None,
    }


def _mariapps_extra_fields(raw_json, table_cols) -> dict:
    """Pull + parse each consumer's Grade cell straight from raw_json into its
    7 dedicated columns (only those physically present in the table)."""
    out = {}
    if not isinstance(raw_json, dict):
        return out
    consumption = raw_json.get("Consumption_Data")
    if isinstance(consumption, dict):
        for consumer_key, consumer_label in _MARIAPPS_GRADE_CONSUMERS:
            raw_grade = consumption.get(f"Section0::{consumer_label}::Grade")
            parsed = _parse_grade_string(raw_grade)
            for sf, _, _ in _GRADE_SUBFIELDS:
                col = _mariappsx_col(consumer_key, sf)
                if col in table_cols:
                    out[col] = parsed[sf]

    # CONFIRMED real bug: VoyageMeta_trimm_operational_LF (an EXISTING column in the
    # generated schema) never gets a value because MARIAPPS_TO_NEWCOL's source key
    # for it is "trimm", but the actual raw field flattens to "trim_m" (from
    # raw_json['Excel_Data']['Trim(m)'] via flatten_mariapps's snake-casing) — a
    # name mismatch, not missing data. Confirmed a real value (-2.6) exists for
    # AM TARANG right now, silently dropped purely by this mismatch. Pulled
    # directly here rather than editing the generated service_variable_mapping.py
    # (explicitly marked DO NOT edit manually) — same bypass approach as the Grade
    # fields above, but targeting an EXISTING column, not a new dedicated one.
    excel_data = raw_json.get("Excel_Data")
    if isinstance(excel_data, dict) and "VoyageMeta_trimm_operational_LF" in table_cols:
        trim_val = excel_data.get("Trim(m)")
        if trim_val is not None and str(trim_val).strip() != "":
            out["VoyageMeta_trimm_operational_LF"] = str(trim_val)

    return out


_MARIAPPS_DIRECT_META = []
for _ck, _cl in _MARIAPPS_GRADE_CONSUMERS:
    for _sf, _disp, _unit in _GRADE_SUBFIELDS:
        _MARIAPPS_DIRECT_META.append({
            "col":          _mariappsx_col(_ck, _sf),
            "display_name": f"{_CONSUMER_DISPLAY_PREFIX[_ck]} {_disp}",
            # category="Fuel Grade" (not "Emission") — these per-consumer Grade
            # sub-fields (ISO Grade/Fuel Type/Sulphur/...) aren't columns in the
            # Emission Log workbook sheet, so they must not show under the
            # Emission capsule, which is now scoped to exactly that sheet's
            # columns. Own dedicated category instead of being orphaned.
            "category":     "Fuel Grade",
            "unit":         _unit,
        })
_MARIAPPS_DIRECT_COLS = [m["col"] for m in _MARIAPPS_DIRECT_META]
# Sentinel: presence of this dedicated column means the Grade extras have been added.
_MARIAPPS_DIRECT_SENTINEL = _MARIAPPS_DIRECT_COLS[0] if _MARIAPPS_DIRECT_COLS else None

# ── CP Warranty direct fields (per-report nearest-speed match) ────────────────
# Held back initially — unlike the Grade fields above, this isn't a straight
# raw_json pull: a noon report carries its LOADING CONDITION but not which speed
# mode (Eco/Full) the charterer actually instructed, so matching it to a
# cp_sea_warranty row needs the same nearest-warranted-speed heuristic the CP
# Phase 3a compliance engine already uses. Imported directly from
# cp_compliance_v2.py — single source of truth for this heuristic, not
# reimplemented here (that module is pure-function/no-DB, so this is a safe,
# one-directional import with no circularity risk).
from ..cp.cp_compliance_v2 import _pick_sea_warranty, _normalize_loading_cond

_CP_WARRANTY_DIRECT_META = [
    # category="Performance" (not "Emission") — these aren't part of the
    # Emission Log workbook sheet, so they must not appear when the Emission
    # capsule is active; `performance=True` is already their real primary
    # placement (see populate_column_metadata below), this just makes the
    # category field agree instead of being a moot leftover from before the
    # Emission capsule was scoped down to exactly the Emission Log columns.
    {"col": "mariappsx_cp_warranted_speed_kn",         "display_name": "CP Warranted Speed",       "category": "Performance", "unit": "kn"},
    {"col": "mariappsx_cp_speed_tolerance_kn",         "display_name": "CP Speed Tolerance",       "category": "Performance", "unit": "kn"},
    {"col": "mariappsx_cp_warranted_consumption_mtday", "display_name": "CP Warranted Consumption", "category": "Performance", "unit": "mt/day"},
    {"col": "mariappsx_cp_consumption_tolerance_pct",  "display_name": "CP Consumption Tolerance", "category": "Performance", "unit": "%"},
]
_CP_WARRANTY_DIRECT_COLS = [m["col"] for m in _CP_WARRANTY_DIRECT_META]
_CP_WARRANTY_SENTINEL = _CP_WARRANTY_DIRECT_COLS[0]
# Separate sentinel for the 2 consumption columns added after the speed/tolerance
# pair already shipped — _CP_WARRANTY_SENTINEL alone would already be satisfied
# on any DB that has the original 2 columns, so the migration below would never
# fire to add these 2 new ones.
_CP_CONSUMPTION_SENTINEL = "mariappsx_cp_warranted_consumption_mtday"


def _fetch_active_cp_sea_warranty(conn, vessel_imo):
    """All Active cp_sea_warranty rows (both Ballast/Laden x Eco/Full candidates)
    for one vessel. Callers should cache this per vessel_imo across a batch run —
    it's the same warranty set for every report from that vessel."""
    rows = conn.execute(text("""
        SELECT w.loading_condition, w.speed_mode, w.warranted_speed_kn, w.speed_tolerance_kn,
               w.total_cons_mt_day, w.cons_tolerance_pct
        FROM cp_sea_warranty w
        JOIN cp_vessel_description d ON d.id = w.cp_id
        WHERE d.vessel_imo = :imo AND d.doc_status = 'Active'
    """), {"imo": vessel_imo}).fetchall()
    return [dict(r._mapping) for r in rows]


def _cp_warranty_extra_fields(conn, vessel_imo, loading_condition_raw, observed_speed_kn, table_cols, cache):
    """Match one report's loading condition + observed speed (STW, falling back to
    SOG — same preference cp_compliance_v2 uses) against the vessel's Active CP
    sea-passage warranty, picking the nearest-warranted-speed candidate within
    that loading condition. `cache` is a dict the caller owns, keyed by
    vessel_imo, so a batch backfill queries cp_sea_warranty once per vessel
    rather than once per row."""
    out = {}
    if not vessel_imo:
        return out
    if vessel_imo not in cache:
        try:
            cache[vessel_imo] = _fetch_active_cp_sea_warranty(conn, vessel_imo)
        except Exception as exc:
            log.error(f"CP warranty lookup failed for vessel {vessel_imo}: {exc}")
            cache[vessel_imo] = []
    candidates = cache[vessel_imo]
    cond = _normalize_loading_cond(loading_condition_raw)
    cand = [c for c in candidates if c.get("loading_condition") == cond] if cond else []
    warranty = _pick_sea_warranty(cand, observed_speed_kn)
    if warranty is None:
        return out
    if "mariappsx_cp_warranted_speed_kn" in table_cols:
        out["mariappsx_cp_warranted_speed_kn"] = warranty.get("warranted_speed_kn")
    if "mariappsx_cp_speed_tolerance_kn" in table_cols:
        out["mariappsx_cp_speed_tolerance_kn"] = warranty.get("speed_tolerance_kn")
    if "mariappsx_cp_warranted_consumption_mtday" in table_cols:
        out["mariappsx_cp_warranted_consumption_mtday"] = warranty.get("total_cons_mt_day")
    if "mariappsx_cp_consumption_tolerance_pct" in table_cols:
        out["mariappsx_cp_consumption_tolerance_pct"] = warranty.get("cons_tolerance_pct")
    return out


def _observed_speed_kn(data_rec):
    """STW first, falling back to SOG — same preference cp_compliance_v2 uses
    for its own nearest-warranted-speed match."""
    for col in ("Vessel_STW_avg_operational_LF", "Vessel_SOG_avg_operational_LF"):
        v = data_rec.get(col)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


# ── Emission Log direct columns (fuel by consumer × grade + Op. Status) ────────
# Per the client's "Emission Log" workbook sheet: a fuel-consumption matrix of
# ME/AE/Boiler × HFO/LFO/MDO/Biofuel (12 cells), plus IG/Other (everything not
# ME/AE/Boiler), Grand Total, and grade-wise Totals across every consumer. The
# raw per-consumer-per-grade data already exists — identical schema on both
# noon_report_data (WNI) and mariapps_reports_data (MariApps), the same
# {consumer}_{grade} / {consumer}_total_cons columns emission_routes.py already
# queries for the CII calculator — it was just never surfaced into the
# expanded_*/Logbook+ layer. Both sources get these columns (unlike the
# CP Warranty / Grade direct fields, which are MariApps-only).
_EMISSION_FUEL_CORE_CONSUMERS = [("me", "ME"), ("ae", "AE"), ("bl", "Boiler")]
# Every other consumer prefix in the shared raw schema — summed into one
# "IG/Other" figure, matching the workbook's single blended column for
# everything that isn't ME/AE/Boiler.
_EMISSION_FUEL_OTHER_CONSUMERS = ["inc", "eg", "combl", "aeb", "blfo"]
# (raw suffix, column-name suffix, display suffix) — bio_fuel's raw suffix
# differs from its column/display form ("biofuel"), everything else matches.
_EMISSION_FUEL_GRADES = [
    ("hfo", "hfo", "HFO"),
    ("lfo", "lfo", "LFO"),
    ("mdo", "mdo", "MDO"),
    ("bio_fuel", "biofuel", "Biofuel"),
]


def _build_emission_log_direct_meta():
    meta = []
    for consumer, consumer_disp in _EMISSION_FUEL_CORE_CONSUMERS:
        for _raw_suffix, col_suffix, grade_disp in _EMISSION_FUEL_GRADES:
            meta.append({
                "col": f"emissionx_{consumer}_{col_suffix}_mt",
                "display_name": f"{consumer_disp} {grade_disp} Consumption",
                "category": "Emission", "unit": "MT",
            })
    meta.append({"col": "emissionx_ig_other_mt", "display_name": "IG/Other Fuel Consumption", "category": "Emission", "unit": "MT"})
    meta.append({"col": "emissionx_grand_total_mt", "display_name": "Grand Total Fuel Consumption", "category": "Emission", "unit": "MT"})
    for _raw_suffix, col_suffix, grade_disp in _EMISSION_FUEL_GRADES:
        meta.append({
            "col": f"emissionx_total_{col_suffix}_mt",
            "display_name": f"Total {grade_disp} Consumption",
            "category": "Emission", "unit": "MT",
        })
    meta.append({
        "col": "emissionx_op_status", "display_name": "Op. Status (UW/NUW)",
        "category": "Emission", "unit": "",
    })
    return meta


_EMISSION_LOG_DIRECT_META = _build_emission_log_direct_meta()
_EMISSION_LOG_DIRECT_COLS = [m["col"] for m in _EMISSION_LOG_DIRECT_META]
_EMISSION_LOG_SENTINEL = _EMISSION_LOG_DIRECT_COLS[0]

# Full Emission Log column order — the workbook's exact sequence, covering
# BOTH the new emissionx_* direct fields AND the pre-existing columns that
# are dual-tagged into Emission (see _EMISSION_EXTRA_COLUMNS below). One
# combined rank list so the Emission-filtered table renders in the sheet's
# actual order end to end, not two separately-ordered blocks bolted together.
# Columns the sheet has but we don't yet capture (Country x2, EU Port? x2,
# OPS kWh, BDN Ref, Remarks) are simply absent from both this list and the
# table — nothing to rank.
_EMISSION_LOG_DEFAULT_ORDER = [
    "emissionx_voyage_no",                                 # Voyage No.
    "VoyageMeta_departure_port_last_leg_operational_LF",  # From Port
    "emissionx_from_country", "emissionx_from_eu_port",   # Country/EU Port? (From)
    "VoyageMeta_to_port_operational_LF",                  # To Port
    "emissionx_to_country", "emissionx_to_eu_port",       # Country/EU Port? (To)
    "VoyageMeta_latitude_operational_LF",                 # Latitude
    "VoyageMeta_longitude_operational_LF",                # Longitude
    "emissionx_op_status",                                # Op. Status
    "Vessel_DOG_dCnt_operational_LF",                     # Dist. (nm)
    "VoyageMeta_log_durationh_operational_LF",            # Hours
    "Vessel_SOG_avg_operational_LF",                      # Speed (kn)
    "Vessel_Tf_avg_operational_LF",                       # Draft F (m)
    "Vessel_Ta_avg_operational_LF",                       # Draft A (m)
    "Vessel_Cargo_onboard_operational_LF",                # Cargo OB (t)
    "emissionx_me_hfo_mt", "emissionx_me_lfo_mt", "emissionx_me_mdo_mt", "emissionx_me_biofuel_mt",
    "ME_FO_mFOCME_dCnt_operational_LF",                   # ME Total
    "emissionx_ae_hfo_mt", "emissionx_ae_lfo_mt", "emissionx_ae_mdo_mt", "emissionx_ae_biofuel_mt",
    "AE_FO_mFOCAE_dCnt_operational_LF",                   # AE Total
    "emissionx_bl_hfo_mt", "emissionx_bl_lfo_mt", "emissionx_bl_mdo_mt", "emissionx_bl_biofuel_mt",
    "AuxBoiler_mFOCBL_dCnt_operational_LF",                # Boiler Total
    "emissionx_ig_other_mt", "emissionx_grand_total_mt",
    "emissionx_total_hfo_mt", "emissionx_total_lfo_mt", "emissionx_total_mdo_mt", "emissionx_total_biofuel_mt",
    "emissionx_bdn_ref",                                   # BDN Ref
]
_EMISSION_LOG_DEFAULT_RANK = {c: i for i, c in enumerate(_EMISSION_LOG_DEFAULT_ORDER)}


def _safe_emission_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fetch_emission_fuel_raw_row(conn, source, raw_id):
    """One row of {consumer}_{grade} / {consumer}_total_cons raw values from
    noon_report_data (wni) / mariapps_reports_data (mari_apps), keyed by
    raw_report_id. Returns None if raw_id is missing or has no matching row
    (a real but small gap — see the WNI join-coverage note where this is
    called from backfill; ~77% of expanded_wni_data rows currently match)."""
    if raw_id is None:
        return None
    table = "noon_report_data" if source == "wni" else "mariapps_reports_data"
    cols = []
    for consumer, _ in _EMISSION_FUEL_CORE_CONSUMERS:
        cols.append(f"{consumer}_total_cons")
        for raw_suffix, _, _ in _EMISSION_FUEL_GRADES:
            cols.append(f"{consumer}_{raw_suffix}")
    for consumer in _EMISSION_FUEL_OTHER_CONSUMERS:
        cols.append(f"{consumer}_total_cons")
        for raw_suffix, _, _ in _EMISSION_FUEL_GRADES:
            cols.append(f"{consumer}_{raw_suffix}")
    col_sql = ", ".join(f'"{c}"' for c in cols)
    row = conn.execute(
        text(f'SELECT {col_sql} FROM {table} WHERE raw_report_id = :rid'),
        {"rid": raw_id},
    ).fetchone()
    if row is None:
        return None
    return dict(zip(cols, row))


def _fmt_emission_mt(v):
    """Round to 3dp before stringifying — plain float addition otherwise bakes
    in binary-representation noise (e.g. 27.200000000000003) into the stored
    text value."""
    return str(round(v, 3))


def _emission_log_fuel_fields(conn, source, raw_id, table_cols):
    """Compute the 17 Emission Log fuel columns (12 per-grade + IG/Other +
    Grand Total + 4 grade Totals) for one report. Returns {} if no matching
    raw row (leaves those columns NULL rather than fabricating zeros)."""
    out = {}
    raw = _fetch_emission_fuel_raw_row(conn, source, raw_id)
    if raw is None:
        return out

    def g(col):
        return _safe_emission_float(raw.get(col)) or 0.0

    total_by_grade = {raw_suffix: 0.0 for raw_suffix, _, _ in _EMISSION_FUEL_GRADES}
    grand_total = 0.0

    for consumer, _ in _EMISSION_FUEL_CORE_CONSUMERS:
        for raw_suffix, col_suffix, _ in _EMISSION_FUEL_GRADES:
            val = g(f"{consumer}_{raw_suffix}")
            total_by_grade[raw_suffix] += val
            col = f"emissionx_{consumer}_{col_suffix}_mt"
            if col in table_cols:
                out[col] = _fmt_emission_mt(val)
        grand_total += g(f"{consumer}_total_cons")

    ig_other = 0.0
    for consumer in _EMISSION_FUEL_OTHER_CONSUMERS:
        ig_other += g(f"{consumer}_total_cons")
        for raw_suffix, _, _ in _EMISSION_FUEL_GRADES:
            total_by_grade[raw_suffix] += g(f"{consumer}_{raw_suffix}")
    grand_total += ig_other

    if "emissionx_ig_other_mt" in table_cols:
        out["emissionx_ig_other_mt"] = _fmt_emission_mt(ig_other)
    if "emissionx_grand_total_mt" in table_cols:
        out["emissionx_grand_total_mt"] = _fmt_emission_mt(grand_total)
    for raw_suffix, col_suffix, _ in _EMISSION_FUEL_GRADES:
        col = f"emissionx_total_{col_suffix}_mt"
        if col in table_cols:
            out[col] = _fmt_emission_mt(total_by_grade[raw_suffix])

    return out


# ── Emission Log Navigation columns (Voyage No., Country, EU Port?, BDN Ref) ──
# "To Port" itself is NOT one of these direct fields — it's plain
# VoyageMeta_to_port_operational_LF (Destination Port), dual-tagged into
# Emission via _EMISSION_EXTRA_COLUMNS like From Port/Lat/Long always were.
# An earlier version of this swapped "To Port" to
# VoyageMeta_arrival_port_current_leg_operational_LF (which has a richer
# "Name {LOCODE},Country" format) with a fallback to Destination Port when
# empty — reverted per explicit request: displaying a different field than
# what the source data actually calls "To Port" was confusing, not helpful.
# Per-column data-source audit (see conversation — not guessed at):
#   - Voyage No.: MariApps raw_json carries "Leg Number" (e.g. "AM KIRTI V
#     38/03") right next to Log Number — present on 1891/1921 raw rows
#     (98.4%, the same small gap every other direct field in this file has).
#     WNI already has its own `voyage_no` identity column — this is
#     MariApps-only, filling the gap for that source.
#   - Country / EU Port?: derived from the SAME field displayed as "From
#     Port" / "To Port" (Departure Port / Destination Port) — never a
#     different hidden field. Two paths: (1) if the string has the rich
#     "Name {LOCODE},Country" format (MariApps' Departure Port sometimes has
#     this), parse the country directly — authoritative. (2) otherwise
#     (every WNI port string, and MariApps' bare Destination Port), normalize
#     the bare name and look it up against a hardcoded EU/EEA ports list
#     (_EU_PORTS_BY_NAME) — a miss is a confident "N" (that's the point of an
#     EU-scoped list) with Country left blank, since we have no reliable
#     non-EU country source for a bare name alone. See _EU_PORTS_BY_NAME's
#     docstring for why this is EU/EEA-scoped rather than a global port
#     database (~100k-row UN/LOCODE isn't fetchable in this environment, and
#     is the wrong scope anyway — only EU/EEA membership regulatory-matters
#     here).
#   - BDN Ref: mariapps_bunker_reports.bdn_reference_no, joined by vessel +
#     calendar date parsed from begin_of_bunkering ("DD-Mon-YYYY HH:MM", the
#     raw scraped string). Only 11 real bunkering transactions exist across
#     the whole fleet right now, so this is blank on nearly every row by
#     design — it should only ever populate the day a bunkering happened.
#     MariApps-only; WNI has no equivalent bunker-report table at all.

_EU_EEA_ISO2 = {
    # 27 EU member states
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
    # EEA (non-EU) additions — Reg. 2015/757 Art. 2(1) scope is EU/EEA
    "IS", "LI", "NO",
}
_EU_EEA_NAMES = {
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czech republic",
    "czechia", "denmark", "estonia", "finland", "france", "germany", "greece",
    "hungary", "ireland", "italy", "latvia", "lithuania", "luxembourg",
    "malta", "netherlands", "poland", "portugal", "romania", "slovakia",
    "slovenia", "spain", "sweden",
    "iceland", "liechtenstein", "norway",
}
_PORT_LOCODE_RE = re.compile(r'\{([A-Za-z]{2})[A-Za-z0-9]*\}')


def _parse_port_country(raw_port):
    """(country, eu_port_YN) from a 'Name {LOCODE},Country' port string.
    Returns (None, None) if the string is missing or has no comma at all
    (true of every bare port name — WNI's port strings, and MariApps'
    VoyageMeta_to_port_operational_LF, are always bare, no country suffix)."""
    if not raw_port or "," not in raw_port:
        return None, None
    country = raw_port.rsplit(",", 1)[-1].strip()
    if not country:
        return None, None
    m = _PORT_LOCODE_RE.search(raw_port)
    if m:
        eu = "Y" if m.group(1).upper() in _EU_EEA_ISO2 else "N"
    else:
        eu = "Y" if country.lower() in _EU_EEA_NAMES else "N"
    return country, eu


# ── Hardcoded EU/EEA ports list (bare-name fallback) ───────────────────────
# When a port string has no country suffix to parse (true of every WNI port
# string, and of MariApps' VoyageMeta_to_port_operational_LF), the only way
# left to know Country/EU Port? is a lookup by name. A full global port
# database (UN/LOCODE is ~100k rows covering every country and location
# type, not just ports) isn't fetchable in this environment — but it's also
# the wrong scope: the only thing that regulatory-matters is EU Port? Y/N,
# so this only needs to cover ports WITHIN the 30 EU/EEA countries. A miss
# against this list is a confident "N" (that's the whole point of scoping it
# to EU/EEA only), not "unknown" — Country stays blank on a miss since we
# have no reliable non-EU country source for a bare name.
#
# Knowledge-based (not an authoritative import) — covers major commercial/
# cargo ports per EU/EEA country. Landlocked EU members (Austria, Czechia,
# Hungary, Luxembourg, Slovakia) are omitted — no sea ports to list. Several
# aliases are listed per port to absorb real formatting variance already
# observed in our data (case, "PT"/"Port" suffixes, alternate spellings).
def _build_eu_ports_by_name():
    # (country, iso2, [port name aliases])
    entries = [
        ("Belgium", "BE", ["Antwerp", "Antwerpen", "Zeebrugge", "Ghent", "Gent", "Ostend", "Oostende"]),
        ("Bulgaria", "BG", ["Varna", "Burgas"]),
        ("Croatia", "HR", ["Rijeka", "Split", "Ploce", "Zadar", "Pula", "Sibenik"]),
        ("Cyprus", "CY", ["Limassol", "Larnaca", "Vasiliko", "Vasilikos"]),
        ("Denmark", "DK", ["Copenhagen", "Kobenhavn", "Aarhus", "Esbjerg", "Fredericia", "Kalundborg", "Aalborg", "Odense", "Skagen"]),
        ("Estonia", "EE", ["Tallinn", "Muuga", "Paldiski"]),
        ("Finland", "FI", ["Helsinki", "Kotka", "Hamina", "Rauma", "Kokkola", "Oulu", "Naantali", "Pori", "Turku"]),
        ("France", "FR", ["Marseille", "Fos Sur Mer", "Fos-Sur-Mer", "Le Havre", "Dunkirk", "Dunkerque",
                            "Nantes", "Saint Nazaire", "Bordeaux", "Rouen", "Calais", "La Rochelle",
                            "Fort De France", "Pointe A Pitre", "Cayenne", "Port Reunion"]),
        ("Germany", "DE", ["Hamburg", "Bremen", "Bremerhaven", "Wilhelmshaven", "Rostock", "Kiel",
                             "Lubeck", "Duisburg", "Emden", "Brunsbuttel"]),
        ("Greece", "GR", ["Piraeus", "Thessaloniki", "Patras", "Volos", "Igoumenitsa", "Kavala",
                            "Eleusis", "Aspropyrgos", "Elefsis"]),
        ("Ireland", "IE", ["Dublin", "Cork", "Shannon Foynes", "Foynes", "Waterford", "Rosslare", "New Ross"]),
        ("Italy", "IT", ["Genoa", "Genova", "La Spezia", "Livorno", "Naples", "Napoli", "Trieste",
                           "Venice", "Venezia", "Ravenna", "Taranto", "Gioia Tauro", "Augusta",
                           "Salerno", "Civitavecchia", "Bari", "Brindisi", "Cagliari", "Palermo", "Savona"]),
        ("Latvia", "LV", ["Riga", "Ventspils", "Liepaja"]),
        ("Lithuania", "LT", ["Klaipeda"]),
        ("Malta", "MT", ["Valletta", "Marsaxlokk"]),
        ("Netherlands", "NL", ["Rotterdam", "Amsterdam", "Vlissingen", "Vlissingen (Flushing)", "Flushing",
                                 "Terneuzen", "Moerdijk", "Ijmuiden", "Delfzijl", "Eemshaven"]),
        ("Poland", "PL", ["Gdansk", "Gdynia", "Szczecin", "Swinoujscie", "Police"]),
        ("Portugal", "PT", ["Lisbon", "Lisboa", "Sines", "Leixoes", "Setubal", "Aveiro", "Figueira Da Foz",
                              "Ponta Delgada", "Praia Da Vitoria", "Funchal"]),
        ("Romania", "RO", ["Constanta", "Galati", "Braila", "Midia"]),
        ("Slovenia", "SI", ["Koper"]),
        ("Spain", "ES", ["Algeciras", "Valencia", "Barcelona", "Bilbao", "Las Palmas", "Las Palmas De Gran Canaria",
                           "Santa Cruz De Tenerife", "Tarragona", "Cartagena", "Huelva", "Gijon", "Vigo",
                           "A Coruna", "Coruna", "Ferrol", "Aviles", "Santander", "Castellon", "Alicante",
                           "Almeria", "Malaga", "Sagunto", "Ceuta", "Melilla"]),
        ("Sweden", "SE", ["Gothenburg", "Goteborg", "Stockholm", "Malmo", "Helsingborg", "Trelleborg",
                            "Lulea", "Gavle", "Norrkoping", "Brofjorden"]),
        # EEA (non-EU) additions — Reg. 2015/757 Art. 2(1) scope is EU/EEA
        ("Iceland", "IS", ["Reykjavik"]),
        ("Norway", "NO", ["Oslo", "Bergen", "Stavanger", "Narvik", "Bronnoysund", "Kristiansand",
                            "Trondheim", "Mongstad", "Sture"]),
    ]
    out = {}
    for country, iso2, aliases in entries:
        for alias in aliases:
            out[_normalize_port_name(alias)] = (country, iso2)
    return out


def _normalize_port_name(raw):
    """Uppercase, strip any {LOCODE}/(parenthetical) suffix, collapse
    punctuation/whitespace — so 'Las Palmas De Gran Canaria', 'LAS PALMAS',
    and 'Las Palmas de Gran Canaria {ESLPA}' all normalize to a matchable
    key regardless of which source or format they came from."""
    if not raw:
        return ""
    s = raw.upper()
    s = re.sub(r"\{[^}]*\}", "", s)
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return s.strip()


_EU_PORTS_BY_NAME = _build_eu_ports_by_name()


def _resolve_port_country(raw_port):
    """(country, eu_port_YN) for one port field, from whichever source has
    data: the rich 'Name {LOCODE},Country' format first (authoritative when
    present — MariApps' Departure Port), falling back to a name lookup
    against the EU/EEA ports list for bare names (everything else). A lookup
    miss is a confident "N" (see _EU_PORTS_BY_NAME's docstring) with Country
    left blank — a hit outside the EU list isn't something we can tell from
    a bare name alone."""
    if not raw_port or not raw_port.strip():
        return None, None
    country, eu = _parse_port_country(raw_port)
    if country:
        return country, eu
    hit = _EU_PORTS_BY_NAME.get(_normalize_port_name(raw_port))
    if hit:
        return hit[0], "Y"
    return None, "N"


def _emission_log_nav_fields(data_rec, table_cols):
    """Country/EU Port? (From/To) — pure string computation over already-
    mapped New Column values (VoyageMeta_departure_port_last_leg_operational_LF
    for "From", VoyageMeta_to_port_operational_LF for "To" — the SAME field
    the table displays as those columns, so Country/EU Port? always describe
    the port actually shown, never a different hidden field). Runs
    identically for both sources; WNI's port fields are simply always empty/
    bare, so it naturally yields blank Country and EU Port?="N" rather than
    needing per-source branching (see _resolve_port_country)."""
    out = {}
    departure_port = data_rec.get("VoyageMeta_departure_port_last_leg_operational_LF")
    to_port = data_rec.get("VoyageMeta_to_port_operational_LF")

    from_country, from_eu = _resolve_port_country(departure_port)
    to_country, to_eu = _resolve_port_country(to_port)

    if "emissionx_from_country" in table_cols and from_country:
        out["emissionx_from_country"] = from_country
    if "emissionx_from_eu_port" in table_cols and from_eu:
        out["emissionx_from_eu_port"] = from_eu
    if "emissionx_to_country" in table_cols and to_country:
        out["emissionx_to_country"] = to_country
    if "emissionx_to_eu_port" in table_cols and to_eu:
        out["emissionx_to_eu_port"] = to_eu

    return out


def _mariapps_voyage_no_field(raw_json, table_cols):
    """Voyage No. from raw_json's Excel_Data.'Leg Number' — same bypass
    pattern as the Grade fields, since it's not part of the generated
    New Column Name mapping."""
    out = {}
    if not isinstance(raw_json, dict):
        return out
    excel_data = raw_json.get("Excel_Data")
    if isinstance(excel_data, dict) and "emissionx_voyage_no" in table_cols:
        leg = excel_data.get("Leg Number")
        if leg is not None and str(leg).strip() != "":
            out["emissionx_voyage_no"] = str(leg).strip()
    return out


# imo_fuel_grade (mariapps_bunker_reports) -> the same raw_suffix keys used in
# _EMISSION_FUEL_GRADES. Only HFO/MDO have ever actually appeared in the real
# data (confirmed by direct query) — LFO/BIOFUEL are included for when a real
# delivery of those grades eventually shows up, not because we've seen one.
# An unrecognized grade string is logged and skipped, never guessed at.
_BDN_GRADE_SUFFIX = {"HFO": "hfo", "LFO": "lfo", "MDO": "mdo", "BIOFUEL": "bio_fuel"}


def _fetch_bdn_windows(conn, vessel_imo):
    """Per-grade FIFO consumption windows built from real bunkering deliveries:
    {grade_suffix: [(start_date, end_date_or_None, bdn_ref), ...]} sorted by
    start_date. Fuel delivered on `start_date` is being drawn down until the
    NEXT real delivery of the SAME grade arrives (`end_date`, exclusive) — so
    every day in between (not just the delivery day itself) is attributable
    to that BDN. The most recent delivery per grade has end_date=None (still
    open — no later delivery exists in this data yet). 'First Time Inventory'
    rows are a declared starting balance, not an attributable delivery, and
    never anchor a window — fuel burned before the FIRST real delivery for a
    grade is genuinely unattributable and stays blank, not guessed at.
    Callers should cache this per vessel_imo across a batch run, same pattern
    as _fetch_active_cp_sea_warranty."""
    rows = conn.execute(text("""
        SELECT begin_of_bunkering, imo_fuel_grade, bdn_reference_no FROM mariapps_bunker_reports
        WHERE vessel_imo = :imo AND transaction_type ILIKE '%bunker%'
          AND begin_of_bunkering IS NOT NULL AND bdn_reference_no IS NOT NULL
    """), {"imo": vessel_imo}).fetchall()
    by_grade = {}
    for begin_str, fuel_grade, bdn_ref in rows:
        date_part = str(begin_str).split(" ")[0].strip()
        dt = None
        for fmt in ("%d-%b-%Y", "%d-%b-%y"):
            try:
                dt = datetime.strptime(date_part, fmt).date()
                break
            except ValueError:
                continue
        if dt is None:
            log.warning(f"[BDN] Unparseable begin_of_bunkering date for vessel {vessel_imo}: {begin_str!r}")
            continue
        grade_suffix = _BDN_GRADE_SUFFIX.get(str(fuel_grade or "").strip().upper())
        if grade_suffix is None:
            log.warning(f"[BDN] Unrecognized imo_fuel_grade for vessel {vessel_imo}: {fuel_grade!r} — skipped, not guessed at.")
            continue
        by_grade.setdefault(grade_suffix, []).append((dt, bdn_ref))

    windows = {}
    for grade_suffix, entries in by_grade.items():
        entries.sort(key=lambda e: e[0])
        grade_windows = []
        for i, (dt, bdn_ref) in enumerate(entries):
            end = entries[i + 1][0] if i + 1 < len(entries) else None
            grade_windows.append((dt, end, bdn_ref))
        windows[grade_suffix] = grade_windows
    return windows


def _bdn_ref_for_date(grade_windows, log_date):
    for start, end, bdn_ref in grade_windows:
        if log_date < start:
            continue
        if end is not None and log_date >= end:
            continue
        return bdn_ref
    return None


def _bdn_ref_field(conn, vessel_imo, log_date, fuel_fields, table_cols, cache):
    """BDN Ref for one report — one ref PER GRADE actually consumed that day
    (HFO/LFO/MDO/Biofuel are separate tanks/deliveries), each matched against
    its own FIFO window from _fetch_bdn_windows(). A day burning two grades
    from two different deliveries renders as "HFO: X | MDO: Y". `fuel_fields`
    is the dict already returned by _emission_log_fuel_fields() for this same
    row — reused here (not re-queried) just to read each grade's
    emissionx_total_*_mt consumption. `cache` is a dict the caller owns, keyed
    by vessel_imo, so a batch backfill queries mariapps_bunker_reports once
    per vessel rather than once per row (same pattern as CP Warranty)."""
    out = {}
    if "emissionx_bdn_ref" not in table_cols or not vessel_imo or not log_date:
        return out
    if vessel_imo not in cache:
        try:
            cache[vessel_imo] = _fetch_bdn_windows(conn, vessel_imo)
        except Exception as exc:
            log.error(f"BDN ref window lookup failed for vessel {vessel_imo}: {exc}")
            cache[vessel_imo] = {}
    windows_by_grade = cache[vessel_imo]
    if not windows_by_grade:
        return out

    date_key = log_date if hasattr(log_date, "year") else None
    if date_key is None:
        try:
            date_key = datetime.strptime(str(log_date)[:10], "%Y-%m-%d").date()
        except ValueError:
            return out

    parts = []
    for raw_suffix, col_suffix, grade_disp in _EMISSION_FUEL_GRADES:
        grade_windows = windows_by_grade.get(raw_suffix)
        if not grade_windows:
            continue
        consumed = _safe_emission_float(fuel_fields.get(f"emissionx_total_{col_suffix}_mt")) or 0.0
        if consumed <= 0:
            continue
        ref = _bdn_ref_for_date(grade_windows, date_key)
        if ref:
            parts.append(f"{grade_disp}: {ref}")
    if parts:
        out["emissionx_bdn_ref"] = " | ".join(parts)
    return out


# Country (From/To) + EU Port? (From/To): both sources — _resolve_port_country
# is a pure string function (rich-format parse, else EU/EEA name lookup) that
# works identically regardless of which source's port field it's given. WNI's
# port fields are usually bare with no country suffix, but the EU/EEA ports
# lookup resolves those too now (e.g. WNI's "LAS PALMAS" -> Spain/Y), which
# was the whole point of building that list — no reason to withhold it from
# WNI the way Voyage No./BDN Ref genuinely have to be (no source data at all).
_EMISSION_LOG_NAV_META_BOTH = [
    {"col": "emissionx_from_country", "display_name": "Country (From)",     "category": "Emission", "unit": ""},
    {"col": "emissionx_from_eu_port", "display_name": "EU Port? (From)",    "category": "Emission", "unit": ""},
    {"col": "emissionx_to_country",   "display_name": "Country (To)",       "category": "Emission", "unit": ""},
    {"col": "emissionx_to_eu_port",   "display_name": "EU Port? (To)",      "category": "Emission", "unit": ""},
]
# Voyage No. / BDN Ref: MariApps-only — no equivalent raw source for WNI at
# all (WNI already has its own `voyage_no` identity column; WNI has no
# bunker-report table, see _fetch_bdn_refs_by_date).
_EMISSION_LOG_NAV_META_MARIAPPS_ONLY = [
    {"col": "emissionx_voyage_no", "display_name": "Voyage No.", "category": "Emission", "unit": ""},
    {"col": "emissionx_bdn_ref",   "display_name": "BDN Ref",    "category": "Emission", "unit": ""},
]
_EMISSION_LOG_NAV_DIRECT_COLS = (
    [m["col"] for m in _EMISSION_LOG_NAV_META_BOTH]
    + [m["col"] for m in _EMISSION_LOG_NAV_META_MARIAPPS_ONLY]
)
_EMISSION_LOG_NAV_SENTINEL = _EMISSION_LOG_NAV_META_BOTH[0]["col"]


# ── CP Voyage Remarks (per-day CP speed/consumption instruction) ──────────
# MariApps' Position tab detail page carries a free-text "Remarks" box below
# the Distance/Loading Condition/Time boxes — masters use it to record that
# day's actual CP speed/consumption instruction (e.g. "LADEN ABT 11.5 KNOTS
# ON ABT IFO 30.5 MT/DAY (ABT 26.9 MT FOR M/E + ABT 3.6 MT FOR A/E)"), which
# can differ from the vessel's standing cp_sea_warranty figure day-to-day
# (Eco vs Full speed, an ETA-driven full-speed instruction, a revised term
# mid-voyage). This was never scraped before — MariApps-only, same posture
# as Voyage No./BDN Ref (no equivalent WNI field). See cp/cp_remarks_parser.py
# for how this free text gets turned into a structured per-day override.
_CP_REMARKS_META = [
    {"col": "cpx_remarks", "display_name": "Voyage Remarks (CP Instruction)", "category": "Charter Party", "unit": ""},
]
_CP_REMARKS_DIRECT_COLS = [m["col"] for m in _CP_REMARKS_META]
_CP_REMARKS_SENTINEL = _CP_REMARKS_DIRECT_COLS[0]


def _mariapps_remarks_field(raw_json, table_cols):
    """cpx_remarks from raw_json's Position_Data.Remarks — same bypass
    pattern as _mariapps_voyage_no_field, since it's not part of the
    generated New Column Name mapping."""
    out = {}
    if not isinstance(raw_json, dict):
        return out
    position_data = raw_json.get("Position_Data")
    if isinstance(position_data, dict) and "cpx_remarks" in table_cols:
        val = position_data.get("Remarks")
        if val is not None and str(val).strip() != "":
            out["cpx_remarks"] = str(val).strip()
    return out


# ── "Also show under Emission" columns ─────────────────────────────────────────
# Per explicit request: the Emission capsule must show EXACTLY the "Emission Log"
# workbook sheet's columns — nothing else. Trimmed from an earlier, broader set
# (Weather x13, Displacement, slip %, calculated-speed variants, redundant
# Arrival-Port field, Distance Through Water) that was never part of that sheet.
# These 10 pre-existing columns (already in their own normal category — Voyage/
# Vessel, Voyage Metadata) ADDITIONALLY appear under "Emission" without losing
# their original category — additive (see `emission` on ExpandedColumnMetadata),
# unlike `performance` which replaces the category outright.
_EMISSION_EXTRA_COLUMNS = {
    # Navigation — From/To Port, Lat/Long (Emission Log: "From Port",
    # "To Port", "Latitude", "Longitude"). Country/EU Port? for both are
    # separately computed (emissionx_from_country etc., MariApps-only) from
    # these SAME two fields — never a different hidden field — see
    # _emission_log_nav_fields.
    "VoyageMeta_departure_port_last_leg_operational_LF",  # From Port
    "VoyageMeta_to_port_operational_LF",                  # To Port
    "VoyageMeta_latitude_operational_LF",
    "VoyageMeta_longitude_operational_LF",
    # Vessel — Distance/Hours/Speed/Drafts (Emission Log: "Dist. (nm)", "Hours",
    # "Speed (kn)", "Draft F (m)", "Draft A (m)")
    "Vessel_DOG_dCnt_operational_LF",   # Dist.
    "VoyageMeta_log_durationh_operational_LF",  # Hours
    "Vessel_SOG_avg_operational_LF",    # Speed
    "Vessel_Tf_avg_operational_LF",     # Draft F
    "Vessel_Ta_avg_operational_LF",     # Draft A
    # Cargo (Emission Log: "Cargo OB (t)")
    "Vessel_Cargo_onboard_operational_LF",
    # Consumer fuel totals (Emission Log: "ME Total", "AE Total", "Boiler
    # Total" — the emissionx_* direct columns cover the per-grade breakdown,
    # these are the already-existing "Tot." columns, not duplicated).
    "ME_FO_mFOCME_dCnt_operational_LF",
    "AE_FO_mFOCAE_dCnt_operational_LF",
    "AuxBoiler_mFOCBL_dCnt_operational_LF",
}

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

# Manager-specified default order for the Performance category (MariApps + WNI —
# every column below exists for both sources). Only these 18 get a forced low
# sort_order (their list index) so they render first, in this exact sequence,
# every time populate_column_metadata() regenerates the table from scratch — a
# code-level default that survives the DELETE+reinsert on every backend restart
# (unlike the picker's drag-to-reorder user_sort_order, which does not; see the
# populate_column_metadata() docstring/comment for that separate, still-open bug).
# The remaining ~46 Performance columns keep whatever sort_order they'd otherwise
# get from the main entries loop below, and simply sort after these 18.
_PERFORMANCE_DEFAULT_ORDER = [
    "VoyageMeta_to_port_operational_LF",           # Destination Port
    "VoyageMeta_log_durationh_operational_LF",     # Log Duration (hr)
    "ME_RHME_dCnt_operational_LF",                 # ME Running Hours (Tot.)
    "Vessel_SOG_avg_operational_LF",                # Speed Over Ground (Avg.)
    "Vessel_SOGcal_avg_operational_LF",             # Calculated Speed Over Ground (Avg.)
    "Vessel_STW_avg_operational_LF",                # Speed Through Water (Avg.)
    "VoyageMeta_real_slip_operational_LF",          # Real Slip
    "ME_FO_mFOCME_dCnt_operational_LF",             # ME Mass FO Consumption (Tot.)
    "AE_FO_mFOCAE_dCnt_operational_LF",             # AE Mass FO Consumption (Tot.)
    "AuxBoiler_mFOCBL_dCnt_operational_LF",         # BL Mass FO Consumption (Tot.)
    "ME_NME_avg_operational_LF",                    # ME Speed (Avg.)
    "ME_mcrcalME_avg_operational_LF",               # ME Calculated Load (Avg.)
    "ME_PSME_avg_operational_LF",                   # ME Shaft Power (Avg.)
    "ME_DESME_dCnt_operational_LF",                 # ME Energy Produced (Tot.)
    "ME_PeffcalME_avg_operational_LF",              # ME Calculated Effective Power (Avg.)
    "ME_PeffestME_avg_operational_LF",              # ME Estimated Effective Power (Avg.)
    "VoyageMeta_trimm_operational_LF",              # Trim
    "Vessel_DISP_avg_operational_LF",               # Displacement (Avg.)
]
_PERFORMANCE_DEFAULT_RANK = {c: i for i, c in enumerate(_PERFORMANCE_DEFAULT_ORDER)}

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

        # Add emission column if table existed without it (migration)
        try:
            conn.execute(text(
                "ALTER TABLE expanded_column_metadata ADD COLUMN IF NOT EXISTS "
                "emission BOOLEAN DEFAULT FALSE"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Force-update emission flag on existing rows from the known set.
        # ADDITIVE only — unlike performance, never clear it based on absence here,
        # since the Grade columns' `emission` intent is expressed via `category`
        # ("Emission" directly) rather than this flag; only touch columns actually
        # in _EMISSION_EXTRA_COLUMNS so nothing else gets silently reset.
        try:
            if _EMISSION_EXTRA_COLUMNS:
                placeholders = ", ".join(f"'{c}'" for c in _EMISSION_EXTRA_COLUMNS)
                conn.execute(text(
                    f"UPDATE expanded_column_metadata SET emission = TRUE  "
                    f"WHERE db_column IN ({placeholders})"
                ))
                conn.commit()
        except Exception as _e:
            log.debug(f"Emission flag update: {_e}")
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

        # Dedicated MariApps direct columns (raw_json → expanded_mariapps_data,
        # bypassing the service-variable Grade collision). Idempotent.
        for c in _MARIAPPS_DIRECT_COLS:
            conn.execute(text(
                f'ALTER TABLE expanded_mariapps_data ADD COLUMN IF NOT EXISTS "{c}" TEXT'
            ))

        # Dedicated CP Warranty columns (cp_sea_warranty join, not raw_json). Idempotent.
        for c in _CP_WARRANTY_DIRECT_COLS:
            conn.execute(text(
                f'ALTER TABLE expanded_mariapps_data ADD COLUMN IF NOT EXISTS "{c}" TEXT'
            ))

        # Dedicated Emission Log columns (fuel-by-grade join + Op. Status walk).
        # Both sources — the raw per-consumer-per-grade schema is identical on
        # noon_report_data and mariapps_reports_data. Idempotent.
        for c in _EMISSION_LOG_DIRECT_COLS:
            conn.execute(text(
                f'ALTER TABLE expanded_mariapps_data ADD COLUMN IF NOT EXISTS "{c}" TEXT'
            ))
            conn.execute(text(
                f'ALTER TABLE expanded_wni_data ADD COLUMN IF NOT EXISTS "{c}" TEXT'
            ))

        # Dedicated Emission Log Navigation columns. "To Port" is NOT one of
        # these: it's VoyageMeta_to_port_operational_LF, dual-tagged into
        # Emission via _EMISSION_EXTRA_COLUMNS like every other pre-existing
        # column, same as before this feature ever touched port fields.
        for c in _EMISSION_LOG_NAV_META_BOTH:
            conn.execute(text(
                f'ALTER TABLE expanded_mariapps_data ADD COLUMN IF NOT EXISTS "{c["col"]}" TEXT'
            ))
            conn.execute(text(
                f'ALTER TABLE expanded_wni_data ADD COLUMN IF NOT EXISTS "{c["col"]}" TEXT'
            ))
        for c in _EMISSION_LOG_NAV_META_MARIAPPS_ONLY:
            conn.execute(text(
                f'ALTER TABLE expanded_mariapps_data ADD COLUMN IF NOT EXISTS "{c["col"]}" TEXT'
            ))

        # Dedicated CP Voyage Remarks column (raw_json → expanded_mariapps_data,
        # MariApps-only). Idempotent.
        for c in _CP_REMARKS_DIRECT_COLS:
            conn.execute(text(
                f'ALTER TABLE expanded_mariapps_data ADD COLUMN IF NOT EXISTS "{c}" TEXT'
            ))

        # Cleanup: emissionx_to_port existed briefly this session (the
        # Arrival-Port swap reverted above) before ever reaching production —
        # drop it so it doesn't linger as dead, always-empty-going-forward
        # cruft. Idempotent, safe to run every startup indefinitely.
        conn.execute(text(
            'ALTER TABLE expanded_mariapps_data DROP COLUMN IF EXISTS "emissionx_to_port"'
        ))
        conn.execute(text(
            'ALTER TABLE expanded_wni_data DROP COLUMN IF EXISTS "emissionx_to_port"'
        ))

        # _emission_log_fuel_fields() does one lookup per report keyed on
        # raw_report_id — neither table had an index on it (only pkey `id`),
        # so every backfill row was a full sequential scan. These indexes
        # make both the backfill and live single-row writes fast.
        conn.execute(text(
            'CREATE INDEX IF NOT EXISTS ix_noon_report_data_raw_report_id '
            'ON noon_report_data (raw_report_id)'
        ))
        conn.execute(text(
            'CREATE INDEX IF NOT EXISTS ix_mariapps_reports_data_raw_report_id '
            'ON mariapps_reports_data (raw_report_id)'
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
                "performance": False, "emission": False, "sort_order": so,
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
                "emission":     nc in _EMISSION_EXTRA_COLUMNS,
                "sort_order":   so,
            })
            so += 1

        # Emission Log direct columns (fuel-by-grade + Op. Status) — both sources.
        # sort_order gets overridden below by _EMISSION_LOG_DEFAULT_RANK so the
        # fuel-matrix columns cluster together in the workbook's ME→AE→Boiler→
        # IG/Other→Grand Total→grade Totals order, same post-pass pattern as
        # _PERFORMANCE_DEFAULT_RANK.
        for dm in _EMISSION_LOG_DIRECT_META:
            entries.append({
                "source":       source,
                "db_column":    dm["col"],
                "display_name": dm["display_name"],
                "category":     dm["category"],
                "unit":         dm["unit"],
                "description":  dm["display_name"],
                "is_active":    True,
                "is_identity":  False,
                "performance":  False,
                "emission":     False,
                "sort_order":   so,
            })
            so += 1

        # Emission Log Navigation columns — Country/EU Port? (From+To) work
        # for both sources (see _EMISSION_LOG_NAV_META_BOTH); Voyage No./BDN
        # Ref are MariApps-only (no source data for WNI at all). "To Port" is
        # not one of these — it's VoyageMeta_to_port_operational_LF, tagged
        # via _EMISSION_EXTRA_COLUMNS.
        for dm in _EMISSION_LOG_NAV_META_BOTH:
            entries.append({
                "source":       source,
                "db_column":    dm["col"],
                "display_name": dm["display_name"],
                "category":     dm["category"],
                "unit":         dm["unit"],
                "description":  dm["display_name"],
                "is_active":    True,
                "is_identity":  False,
                "performance":  False,
                "emission":     False,
                "sort_order":   so,
            })
            so += 1
        if source == "mari_apps":
            for dm in _EMISSION_LOG_NAV_META_MARIAPPS_ONLY:
                entries.append({
                    "source":       source,
                    "db_column":    dm["col"],
                    "display_name": dm["display_name"],
                    "category":     dm["category"],
                    "unit":         dm["unit"],
                    "description":  dm["display_name"],
                    "is_active":    True,
                    "is_identity":  False,
                    "performance":  False,
                    "emission":     False,
                    "sort_order":   so,
                })
                so += 1
            for dm in _CP_REMARKS_META:
                entries.append({
                    "source":       source,
                    "db_column":    dm["col"],
                    "display_name": dm["display_name"],
                    "category":     dm["category"],
                    "unit":         dm["unit"],
                    "description":  dm["display_name"],
                    "is_active":    True,
                    "is_identity":  False,
                    "performance":  False,
                    "emission":     False,
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
                    "emission":     False,
                    "sort_order":   so,
                })
                so += 1

        # MariApps-only dedicated direct columns (Consumption-tab Grade, parsed).
        # Active by default so they show in the grid immediately.
        if source == "mari_apps":
            for dm in _MARIAPPS_DIRECT_META:
                entries.append({
                    "source":       source,
                    "db_column":    dm["col"],
                    "display_name": dm["display_name"],
                    "category":     dm["category"],
                    "unit":         dm["unit"],
                    "description":  dm["display_name"],
                    "is_active":    True,
                    "is_identity":  False,
                    "performance":  False,
                    "emission":     False,
                    "sort_order":   so,
                })
                so += 1

            # MariApps-only dedicated CP Warranty columns (cp_sea_warranty join).
            # Performance-only now — not part of the Emission Log workbook sheet,
            # so no longer dual-tagged into Emission (see _CP_WARRANTY_DIRECT_META).
            for dm in _CP_WARRANTY_DIRECT_META:
                entries.append({
                    "source":       source,
                    "db_column":    dm["col"],
                    "display_name": dm["display_name"],
                    "category":     dm["category"],
                    "unit":         dm["unit"],
                    "description":  dm["display_name"],
                    "is_active":    True,
                    "is_identity":  False,
                    "performance":  True,
                    "emission":     False,
                    "sort_order":   so,
                })
                so += 1

    # Force the manager-specified default order onto the Performance category
    # (applies to whichever source(s) actually have these columns — currently
    # both mari_apps and wni). Done as a post-pass so it's independent of
    # whatever order CLEAN_OPERATIONAL_COLUMNS happens to iterate in above.
    for e in entries:
        if e["db_column"] in _PERFORMANCE_DEFAULT_RANK:
            e["sort_order"] = _PERFORMANCE_DEFAULT_RANK[e["db_column"]]
        elif e["db_column"] in _EMISSION_LOG_DEFAULT_RANK:
            e["sort_order"] = _EMISSION_LOG_DEFAULT_RANK[e["db_column"]]

    with engine.connect() as conn:
        # NOTE: this used to unconditionally `DELETE FROM expanded_column_metadata`
        # before the insert below. That wiped every row on every backend restart,
        # including `user_sort_order` (the picker's drag-to-reorder position) —
        # since a fresh INSERT has nothing to conflict with once the table's been
        # emptied, the `ON CONFLICT ... DO UPDATE` clause never actually fired, so
        # any manual reordering was silently lost on every deploy. Fixed by only
        # removing rows that no longer correspond to a real column (genuinely
        # retired fields) and otherwise relying on the upsert to update in place —
        # `user_sort_order` is deliberately excluded from the UPDATE SET below, so
        # it now survives restarts as intended.
        if entries:
            valid_keys = {(e["source"], e["db_column"]) for e in entries}
            existing_keys = {
                (r[0], r[1]) for r in conn.execute(text(
                    "SELECT source, db_column FROM expanded_column_metadata"
                )).fetchall()
            }
            stale_keys = existing_keys - valid_keys
            for src, col in stale_keys:
                conn.execute(text(
                    "DELETE FROM expanded_column_metadata WHERE source = :s AND db_column = :c"
                ), {"s": src, "c": col})
            if stale_keys:
                log.info(f"Column metadata: removed {len(stale_keys)} retired column(s).")

            conn.execute(text("""
                INSERT INTO expanded_column_metadata
                    (source, db_column, display_name, category, unit,
                     description, is_active, is_identity, performance, emission, sort_order)
                VALUES
                    (:source, :db_column, :display_name, :category, :unit,
                     :description, :is_active, :is_identity, :performance, :emission, :sort_order)
                ON CONFLICT (source, db_column) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    category     = EXCLUDED.category,
                    unit         = EXCLUDED.unit,
                    description  = EXCLUDED.description,
                    performance  = EXCLUDED.performance,
                    emission     = EXCLUDED.emission,
                    sort_order   = EXCLUDED.sort_order
                    -- `is_active` deliberately excluded from the UPDATE SET, same
                    -- reasoning as `user_sort_order` above: this function reruns on
                    -- every backend startup (via setup_expanded_tables), and it was
                    -- unconditionally resetting is_active back to its hardcoded
                    -- per-column default every single time — silently reverting any
                    -- manual is_active=FALSE toggle (e.g. an admin pruning permanently
                    -- -empty columns out of the picker) on the very next restart. The
                    -- computed default below still applies to a genuinely NEW column
                    -- via the INSERT path; an existing row's is_active now survives
                    -- restarts exactly like user_sort_order already does.
            """), entries)
        else:
            conn.execute(text("DELETE FROM expanded_column_metadata"))
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
    cp_warranty_cache = {}  # vessel_imo -> cp_sea_warranty candidates; one query per vessel for the whole run
    bdn_ref_cache = {}      # vessel_imo -> {date: [bdn_ref, ...]}; one query per vessel for the whole run
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

                    fuel_fields = _emission_log_fuel_fields(conn, "mari_apps", rid, table_cols)
                    record = {
                        "raw_log_id":       rid,
                        "vessel_imo":       vessel_imo,
                        "log_date":         str(log_date)[:10] if log_date else None,
                        "log_type":         log_type,
                        "log_number":       log_number,
                        "source_id":        "mari_apps",
                        "loading_condition": lc,
                        **data_rec,
                        **_mariapps_extra_fields(raw_json, table_cols),
                        **_cp_warranty_extra_fields(
                            conn, vessel_imo, lc, _observed_speed_kn(data_rec), table_cols, cp_warranty_cache
                        ),
                        **fuel_fields,
                        **_emission_log_nav_fields(data_rec, table_cols),
                        **_mariapps_voyage_no_field(raw_json, table_cols),
                        **_bdn_ref_field(conn, vessel_imo, log_date, fuel_fields, table_cols, bdn_ref_cache),
                        **_mariapps_remarks_field(raw_json, table_cols),
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
                        **_emission_log_fuel_fields(conn, "wni", rid, table_cols),
                        **_emission_log_nav_fields(data_rec, table_cols),
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
        fuel_fields = _emission_log_fuel_fields(conn, "mari_apps", raw_log_id, table_cols)
        record = {
            "raw_log_id":        raw_log_id,
            "vessel_imo":        vessel_imo,
            "log_date":          str(log_date)[:10] if log_date else None,
            "log_type":          log_type,
            "log_number":        log_number,
            "source_id":         "mari_apps",
            "loading_condition": lc,
            **data_rec,
            **_mariapps_extra_fields(raw_json, table_cols),
            **_cp_warranty_extra_fields(conn, vessel_imo, lc, _observed_speed_kn(data_rec), table_cols, {}),
            **fuel_fields,
            **_emission_log_nav_fields(data_rec, table_cols),
            **_mariapps_voyage_no_field(raw_json, table_cols),
            **_bdn_ref_field(conn, vessel_imo, log_date, fuel_fields, table_cols, {}),
            **_mariapps_remarks_field(raw_json, table_cols),
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
            **_emission_log_fuel_fields(conn, "wni", raw_report_id, table_cols),
            **_emission_log_nav_fields(data_rec, table_cols),
        }
        _upsert_row(conn, "expanded_wni_data", "raw_report_id", record)
    except Exception as exc:
        log.error(f"write_expanded_wni error (raw_report_id={raw_report_id}): {exc}")


# ---------------------------------------------------------------------------
# Op. Status (UW/NUW) — sequential per-vessel backfill
# ---------------------------------------------------------------------------

# Event types (case-insensitive) that mark the start of Under Way / end of
# Under Way, per MEPC.401(83): UW = FAOP (Full Away On Passage, i.e. BOSP) to
# EOSP; NUW = EOSP to the next BOSP. COSP (Commencement Of Sea Passage) is
# treated the same as BOSP where it appears instead — both mark "now sailing".
_OP_STATUS_UW_START = {"BOSP", "COSP"}
_OP_STATUS_UW_END = {"EOSP"}

# Genuinely port-side event types — by definition never underway, regardless
# of what the BOSP/EOSP state machine below says. Needed because same-day
# ordering only has date-level (not time-of-day) precision, so a Departure
# Report or Noon-at-port sharing a calendar date with that day's BOSP can sort
# after it purely on the `id` tiebreak and would otherwise inherit UW from the
# state machine — a real bug reported live (Noon at port / Departure Report
# showing as UW). Forcing these three to NUW unconditionally is correct
# regardless of same-day ordering ambiguity: Arrival/Departure Report and Noon
# at port are never underway. Only BOSP/COSP/EOSP themselves are the boundary
# markers and stay driven by the state machine (EOSP counts as UW per spec).
_OP_STATUS_FORCE_NUW = {"ARRIVAL REPORT", "DEPARTURE REPORT", "NOON AT PORT"}


def _backfill_op_status(engine):
    """Walk each vessel's reports in chronological order (both sources) and
    assign Op. Status (UW/NUW) from the BOSP/COSP → EOSP event sequence —
    this can't be computed per-row like the other direct fields, it needs the
    whole vessel history in order. EOSP itself is still UW (it's the last
    moment of being underway); NUW starts on the row after it. Defaults to
    NUW for any reports before a vessel's first BOSP/COSP."""
    tables = [
        ("expanded_mariapps_data", "log_date", "log_type"),
        ("expanded_wni_data", "date", "event_type"),
    ]
    with engine.connect() as conn:
        for table, date_col, type_col in tables:
            vessels = [r[0] for r in conn.execute(text(
                f'SELECT DISTINCT vessel_imo FROM {table} WHERE vessel_imo IS NOT NULL'
            )).fetchall()]
            updated = 0
            for imo in vessels:
                rows = conn.execute(text(
                    f'SELECT id, "{type_col}" FROM {table} '
                    f'WHERE vessel_imo = :imo ORDER BY "{date_col}" ASC, id ASC'
                ), {"imo": imo}).fetchall()

                state = "NUW"
                updates = []
                for row_id, event_type in rows:
                    et = str(event_type or "").strip().upper()
                    if et in _OP_STATUS_UW_START:
                        state = "UW"
                        row_status = "UW"
                    elif et in _OP_STATUS_UW_END:
                        row_status = "UW"
                        state = "NUW"
                    elif et in _OP_STATUS_FORCE_NUW:
                        row_status = "NUW"
                    else:
                        row_status = state
                    updates.append({"id": row_id, "status": row_status})

                if updates:
                    conn.execute(text(
                        f'UPDATE {table} SET emissionx_op_status = :status WHERE id = :id'
                    ), updates)
                    updated += len(updates)
            conn.commit()
            log.info(f"Op. Status backfill: {table} — {updated} rows across {len(vessels)} vessels.")


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

    # ── Detect missing MariApps direct columns (Consumption Grade) → re-backfill ──
    mariapps_extras_missing = False
    if not needs_rebuild and "expanded_mariapps_data" in existing and _MARIAPPS_DIRECT_SENTINEL:
        with engine.connect() as _c:
            cols = {r[0] for r in _c.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='expanded_mariapps_data'"
            ))}
        if _MARIAPPS_DIRECT_SENTINEL not in cols:
            mariapps_extras_missing = True
            log.info("expanded_mariapps_data missing Grade direct columns — will add and backfill.")

    # ── Detect missing CP Warranty direct columns → re-backfill to populate them ──
    if not needs_rebuild and "expanded_mariapps_data" in existing and not mariapps_extras_missing:
        with engine.connect() as _c:
            cols = {r[0] for r in _c.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='expanded_mariapps_data'"
            ))}
        if _CP_WARRANTY_SENTINEL not in cols:
            mariapps_extras_missing = True
            log.info("expanded_mariapps_data missing CP Warranty direct columns — will add and backfill.")
        if _CP_CONSUMPTION_SENTINEL not in cols:
            mariapps_extras_missing = True
            log.info("expanded_mariapps_data missing CP Warranted Consumption columns — will add and backfill.")

    # ── Detect missing Emission Log direct columns (fuel-by-grade + Op. Status) ──
    # Both sources — set both flags since these columns exist on both tables.
    emission_log_missing = False
    if not needs_rebuild and "expanded_mariapps_data" in existing:
        with engine.connect() as _c:
            cols = {r[0] for r in _c.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='expanded_mariapps_data'"
            ))}
        if _EMISSION_LOG_SENTINEL not in cols:
            emission_log_missing = True
            mariapps_extras_missing = True
            log.info("expanded_mariapps_data missing Emission Log columns — will add and backfill.")
    if not needs_rebuild and "expanded_wni_data" in existing:
        with engine.connect() as _c:
            cols = {r[0] for r in _c.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='expanded_wni_data'"
            ))}
        if _EMISSION_LOG_SENTINEL not in cols:
            emission_log_missing = True
            wni_extras_missing = True
            log.info("expanded_wni_data missing Emission Log columns — will add and backfill.")

    # ── Detect missing Emission Log Navigation columns (Voyage No./To Port/
    # Country/EU Port?/BDN Ref) — separate sentinel since these were added
    # after the fuel-by-grade columns already shipped on some DBs.
    if not needs_rebuild and "expanded_mariapps_data" in existing:
        with engine.connect() as _c:
            cols = {r[0] for r in _c.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='expanded_mariapps_data'"
            ))}
        if _EMISSION_LOG_NAV_SENTINEL not in cols:
            emission_log_missing = True
            mariapps_extras_missing = True
            log.info("expanded_mariapps_data missing Emission Log Navigation columns — will add and backfill.")
        if _CP_REMARKS_SENTINEL not in cols:
            mariapps_extras_missing = True
            log.info("expanded_mariapps_data missing CP Voyage Remarks column — will add and backfill.")

    create_expanded_tables(engine)   # ALTERs the dedicated WNI/MariApps columns into place

    need_backfill_m = "expanded_mariapps_data" not in existing
    need_backfill_w = "expanded_wni_data"       not in existing

    if need_backfill_m or need_backfill_w or needs_rebuild or wni_extras_missing or mariapps_extras_missing:
        if need_backfill_m or needs_rebuild or mariapps_extras_missing:
            backfill_mariapps(engine)
        if need_backfill_w or needs_rebuild or wni_extras_missing:
            backfill_wni(engine)

    if need_backfill_m or need_backfill_w or needs_rebuild or emission_log_missing:
        _backfill_op_status(engine)

    populate_column_metadata(engine)
    log.info("Expanded tables setup complete.")
