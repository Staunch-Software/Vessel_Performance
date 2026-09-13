"""
IMO DCS Enhanced — MARPOL Annex VI Reg. 27 + MEPC.385(81) enhanced data items.
==============================================================================
Pure helper functions for the 6 Enhanced DCS items mandatory from CY2026
(MEPC.385(81) para 2.1-2.5) — everything else (Ship ID, fuel-by-type + CO2,
CII) is either a straight DB read or already covered by cii_calculator.py.

  Item 1: Fuel by consumer type (ME/AE/Boiler/IG-Other)      — para 2.1
  Item 2: Fuel NOT under way, by consumer                     — para 2.2,
          using the UW/NUW definitions from MEPC.401(83)
  Item 3: Onshore Power Supplied (kWh)                        — para 2.3
  Item 4: Transport work (cargo-tonne x nm)                   — para 2.4
  Item 5: Laden distance (voluntary)                          — para 2.5
  Item 6: Innovative technology category                      — manual field,
          MEPC.1/Circ.896 categories A/B-1/B-2/C-1/C-2 — not derivable from
          operational data, so this module just validates/passes it through.

All aggregation (SUM/GROUP BY over expanded_mariapps_data / expanded_wni_data)
happens in emission_routes.py; this module only holds the small amount of
actual arithmetic/validation so it isn't buried inline in the route.
"""

INNOVATIVE_TECH_CATEGORIES = {"A", "B-1", "B-2", "C-1", "C-2", "None"}


def transport_work_mt_nm(cargo_onboard_mt, distance_nm):
    """Item 4 — cargo-tonne x nm for one report. Either missing -> 0, not None,
    so summing a period never silently drops a row's contribution to NaN."""
    if cargo_onboard_mt is None or distance_nm is None:
        return 0.0
    return float(cargo_onboard_mt) * float(distance_nm)


def group_into_legs(rows):
    """Group per-report rows (sorted by date) into legs — a leg is a
    contiguous run sharing the same (voyage_no, loading_condition), matching
    the WNI Leg-sheet convention (e.g. voyage 40 = one Ballast leg to the
    load port + one Laden leg to the discharge port). A voyage_no or
    loading_condition change always starts a new leg even mid-voyage.

    Each row dict must carry: date, voyage_no, loading_condition, op_status,
    from_port, to_port, distance_nm, duration_h, cargo_mt, and fuel_by_grade
    (an 8-key dict: hfo/lfo/mdo/bio_fuel/lng/lpg_propane/lpg_butane/methanol).
    Returns a list of leg dicts (still raw — aggregation/CII happens in the
    route, which has access to compute_cii and CF_TABLE).
    """
    legs = []
    current = None
    for r in rows:
        key = (r["voyage_no"], r["loading_condition"])
        if current is None or key != current["key"]:
            if current is not None:
                legs.append(current)
            current = {"key": key, "rows": []}
        current["rows"].append(r)
    if current is not None:
        legs.append(current)
    return legs


def validate_innovative_tech(category):
    if category is None or category == "":
        return None
    if category not in INNOVATIVE_TECH_CATEGORIES:
        raise ValueError(
            f"Invalid innovative technology category '{category}' — "
            f"must be one of {sorted(INNOVATIVE_TECH_CATEGORIES)} (MEPC.1/Circ.896)."
        )
    return category
