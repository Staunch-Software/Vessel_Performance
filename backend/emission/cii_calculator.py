"""
IMO Carbon Intensity Indicator (CII) / AER calculator
======================================================
Pure functions — no DB access. All constants below are cited directly from the
governing IMO resolutions (fetched and read from IMO's own document server);
update this module, not scattered magic numbers elsewhere, if IMO revises them.

  - Attained CII / AER formula, Cf table:      MEPC.336(76)  (2021 Guidelines G1)
    Cf values:                                  MEPC.308(73)  (2018 EEDI Guidelines, Annex 5)
  - Reference line (a, c) per ship type:        MEPC.353(78)  (2022 Guidelines G2)
  - Annual reduction factor Z (2023-2026):      MEPC.338(76)  (2021 Guidelines G3)
  - Annual reduction factor Z (2027-2030):      MEPC.400(83)  (adopted 11 Apr 2025)
  - Rating boundaries d1-d4 per ship type:       MEPC.354(78)  (2022 Guidelines G4)

Per MEPC.336(76) Reg. 28, AER = the DWT-capacity variant of the general CII
formula. For the ship types in this fleet (bulk carriers), attained CII AND
AER are the same number — there is no separate "AER calculation" to do.

CAVEAT (flag before extending to other ship types or trusting long-term):
reference-line/rating values are current as of MEPC 83 (Apr 2025). IMO has a
work plan targeting a revised reference line at MEPC 87 (spring 2028) — verify
these constants haven't been superseded before relying on them past that date.
"""

# Cf: tonnes CO2 per tonne fuel — MEPC.308(73) Annex 5, Table (§2.2.1)
CF_TABLE = {
    "hfo": 3.114,          # HFO / VLSFO / ULSFO / HSFO — all reported under IMO's HFO category
    "lfo": 3.151,
    "mdo": 3.206,          # covers MDO, MGO, DO, GO — all "Diesel/Gas Oil" in the IMO table
    "lpg_propane": 3.000,
    "lpg_butane": 3.030,
    "lng": 2.750,
    "methanol": 1.375,
    "ethanol": 1.913,
    # Not in the MEPC.308(73) table; treated as Cf=0 pending well-to-wake / sustainability-
    # certificate methodology (ammonia: zero-carbon at combustion; biofuel: requires supplier
    # documentary evidence per MEPC.1/Circ.896 to claim a reduced/zero factor). Flag before
    # relying on this for a vessel that actually burns meaningful ammonia or biofuel volumes.
    "ammonia": 0.0,
    "bio_fuel": 0.0,
}

# Reference line: CIIref = a * Capacity^-c — MEPC.353(78) Table 1
REFERENCE_LINE = {
    "bulk_carrier": {"a": 4745, "c": 0.622},
}

# Annual reduction factor Z (%) vs the 2019 reference line — MEPC.338(76) Table 1 (2023-2026),
# MEPC.400(83) (2027-2030, adopted 11 Apr 2025).
Z_FACTOR_PCT = {
    2023: 5.0, 2024: 7.0, 2025: 9.0, 2026: 11.0,
    2027: 13.625, 2028: 16.250, 2029: 18.875, 2030: 21.500,
}

# Rating boundaries exp(d1..d4), multiplied by required CII — MEPC.354(78) Table 2.
# superior (A) | superior..lower (B) | lower..upper (C) | upper..inferior (D) | >inferior (E)
RATING_BOUNDARIES = {
    "bulk_carrier": {"superior": 0.86, "lower": 0.94, "upper": 1.06, "inferior": 1.18},
}

DEFAULT_SHIP_TYPE = "bulk_carrier"


def required_cii(dwt, year, ship_type=DEFAULT_SHIP_TYPE):
    ref = REFERENCE_LINE[ship_type]
    cii_ref = ref["a"] * (dwt ** -ref["c"])
    z = Z_FACTOR_PCT.get(year)
    if z is None:
        # Fall back to the latest known year rather than silently extrapolating.
        z = Z_FACTOR_PCT[max(Z_FACTOR_PCT)]
    return cii_ref * (1 - z / 100.0)


def rate_cii(attained, required, ship_type=DEFAULT_SHIP_TYPE):
    b = RATING_BOUNDARIES[ship_type]
    if attained <= b["superior"] * required:
        return "A"
    if attained <= b["lower"] * required:
        return "B"
    if attained <= b["upper"] * required:
        return "C"
    if attained <= b["inferior"] * required:
        return "D"
    return "E"


def compute_cii(fuel_by_grade_mt, distance_nm, dwt, year, ship_type=DEFAULT_SHIP_TYPE):
    """
    fuel_by_grade_mt: {"hfo": mt, "lfo": mt, ...} — total fuel burned (all consumers
                      combined: ME+AE+Boiler+Incinerator+Emergency Gen+etc.) for the period.
    distance_nm:      total distance sailed (nm) over the same period.
    dwt:              vessel deadweight (mt).
    year:             calendar year the period falls in (determines Z).

    Returns None if distance or dwt is missing/zero (CII isn't computable).
    """
    if not distance_nm or not dwt:
        return None

    breakdown = []
    co2_mt_total = 0.0
    for grade, mt in fuel_by_grade_mt.items():
        mt = mt or 0.0
        cf = CF_TABLE.get(grade)
        co2_mt = mt * cf if cf is not None else 0.0
        co2_mt_total += co2_mt
        if mt > 0:
            breakdown.append({"grade": grade, "fuel_mt": round(mt, 2), "cf": cf, "co2_mt": round(co2_mt, 2)})

    co2_grams = co2_mt_total * 1_000_000
    w = dwt * distance_nm
    attained = co2_grams / w if w else None

    req = required_cii(dwt, year, ship_type)
    rating = rate_cii(attained, req, ship_type) if attained is not None else None

    return {
        "year": year,
        "ship_type": ship_type,
        "dwt": dwt,
        "distance_nm": round(distance_nm, 1),
        "co2_total_mt": round(co2_mt_total, 2),
        "attained_cii": round(attained, 3) if attained is not None else None,
        "required_cii": round(req, 3),
        "rating": rating,
        "rating_boundaries": {
            k: round(v * req, 3) for k, v in RATING_BOUNDARIES[ship_type].items()
        },
        "fuel_breakdown": breakdown,
    }
