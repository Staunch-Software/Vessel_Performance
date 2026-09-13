"""
Biofuel Calc — 1:1 rebuild of the "Biofuel_Calc" worksheet in the client's
Unified_Emissions_2026_v6 - Final.xlsx (sheet cells cited throughout below).
Every formula here is copied from that sheet's cell formulas, not
re-derived — this module intentionally does NOT implement any of the
Proof-of-Sustainability / fossil-equivalent-fallback logic used elsewhere
in this codebase (see the old git history of this file / fueleu_calculator.py
for that approach) — the client's sheet has no such gate: any biofuel
entered is credited at the fixed values below, always. Match the sheet.

Pure calculation helpers — no DB access. All SQL/aggregation lives in
biofuel_routes.py.

============================================================================
SOURCE CONSTANTS (RefConstants sheet, same workbook):
  Section 1 (Cf, MEPC.364(79) / Del.Reg.2023/2776), row 6-8:
      HFO Cf=3.114  LFO Cf=3.151  MDO/MGO Cf=3.206   (== cii_calculator.CF_TABLE)
  Section 5 (WtW defaults, FuelEU Reg. 2023/1805 Annex II), row 66-68, 72:
      HFO WtW=91.16  LFO WtW=91.16  MDO/MGO WtW=91.76  gCO2e/MJ
      Biodiesel(FAME) WtW=16.38 gCO2e/MJ, LCV=37.2 MJ/kg — "Certified
      sustainable — Annex II Table 1"; this is a FIXED reference value on
      the sheet, not conditioned on any per-stem sustainability check.
  LCV (MJ/kg), same rows as above: HFO=40.2  LFO=41.0  MDO/MGO=42.7
  Section 10: "Cf_blend = Σ(mᵢ × Cfᵢ) / Σ(mᵢ)" — mass-weighted; for CII,
  Cf_bio = 0 (MEPC.1/Circ.905-Rev.1), so only the fossil share of the blend
  contributes to Cf_blend.

Biofuel Type is a single-option dropdown on the sheet ("FAME Biodiesel")
because every FAME feedstock (UCOME/TME/RME/SME/PME) shares the same
Cf/LCV/WtW figures per the sheet's own Quick Reference notes (row 43) — the
field is kept for labeling only and does not change any calculation below.
============================================================================
"""

CF_BASE = {"HFO": 3.114, "LFO": 3.151, "MDO": 3.206}       # RefConstants Section 1
LCV_BASE = {"HFO": 40.2, "LFO": 41.0, "MDO": 42.7}          # RefConstants Section 1 / 5
WTW_BASE = {"HFO": 91.16, "LFO": 91.16, "MDO": 91.76}       # RefConstants Section 5

LCV_BIO = 37.2    # RefConstants row 72 (Biodiesel/FAME)
WTW_BIO = 16.38   # RefConstants row 72 (Biodiesel/FAME)
CF_BIO = 0.0      # MEPC.1/Circ.905-Rev.1 — biogenic CO2 not counted for CII


def bio_pct_by_mass(input_basis, bio_pct, rho_base, rho_bio):
    """Sheet col J. bio_pct is 0-100 (matches the sheet's percentage cell,
    just not pre-divided by 100 — see routes for the /100 conversion point).
    Mirrors: =IF(F="Mass%",G,IF(F="Vol%",IFERROR((G*I)/((1-G)*H+G*I),""),""))
    with G/H/I as fractions (0-1) inside the formula, per the sheet."""
    g = (bio_pct or 0) / 100.0
    if input_basis == "Mass%":
        return g
    if input_basis == "Vol%":
        if rho_base is None or rho_bio is None:
            return None
        denom = (1 - g) * rho_base + g * rho_bio
        if not denom:
            return None
        return (g * rho_bio) / denom
    return None


def stem_calc(base_fuel_grade, input_basis, bio_pct, rho_base, rho_bio, quantity_mt):
    """Returns the sheet's per-row green (calculated) cells: J, K, L, M, N,
    O, P, Q, S, T — for one bunker stem row."""
    grade = base_fuel_grade if base_fuel_grade in CF_BASE else "HFO"
    cf_base = CF_BASE[grade]
    lcv_base = LCV_BASE[grade]
    wtw_base = WTW_BASE[grade]

    j = bio_pct_by_mass(input_basis, bio_pct, rho_base, rho_bio)
    if j is None:
        return {
            "bio_pct_by_mass": None, "cf_base": cf_base, "cf_blend": None,
            "lcv_base": lcv_base, "lcv_bio": LCV_BIO, "wtw_base": wtw_base, "wtw_bio": WTW_BIO,
            "wtw_blend": None, "fossil_portion_mt": None, "bio_portion_mt": None,
        }

    # Col L: =IFERROR((1-J)*K,"")
    cf_blend = (1 - j) * cf_base + j * CF_BIO

    # Col Q: =IFERROR(((1-J)*M*O+J*N*P)/((1-J)*M+J*N),"") — energy-weighted (mass x LCV as weight)
    energy_fossil = (1 - j) * lcv_base
    energy_bio = j * LCV_BIO
    denom = energy_fossil + energy_bio
    wtw_blend = (energy_fossil * wtw_base + energy_bio * WTW_BIO) / denom if denom else None

    fossil_portion_mt = quantity_mt * (1 - j) if quantity_mt is not None else None  # col S
    bio_portion_mt = quantity_mt * j if quantity_mt is not None else None            # col T

    return {
        "bio_pct_by_mass": round(j * 100, 4),  # surfaced back in sheet-native percentage terms
        "cf_base": cf_base, "cf_blend": round(cf_blend, 6) if cf_blend is not None else None,
        "lcv_base": lcv_base, "lcv_bio": LCV_BIO, "wtw_base": wtw_base, "wtw_bio": WTW_BIO,
        "wtw_blend": round(wtw_blend, 6) if wtw_blend is not None else None,
        "fossil_portion_mt": round(fossil_portion_mt, 3) if fossil_portion_mt is not None else None,
        "bio_portion_mt": round(bio_portion_mt, 3) if bio_portion_mt is not None else None,
    }


def weighted_summary(rows_calc):
    """Sheet row 33 "WEIGHTED AVG / TOTAL":
      Cf Blend  = SUMPRODUCT(L13:L32,R13:R32)/SUM(R13:R32)
      WtW Blend = SUMPRODUCT(Q13:Q32,R13:R32)/SUM(R13:R32)
      Total Qty / Fossil Portion / Bio Portion = plain SUM.
    rows_calc: list of {"quantity_mt", "cf_blend", "wtw_blend", "fossil_portion_mt", "bio_portion_mt"}."""
    usable = [r for r in rows_calc if r["quantity_mt"] and r["cf_blend"] is not None and r["wtw_blend"] is not None]
    total_qty = sum(r["quantity_mt"] for r in rows_calc if r["quantity_mt"])
    if not usable or not sum(r["quantity_mt"] for r in usable):
        return {
            "cf_blend_avg": None, "wtw_blend_avg": None,
            "total_qty_mt": round(total_qty, 3),
            "total_fossil_mt": round(sum(r["fossil_portion_mt"] or 0 for r in rows_calc), 3),
            "total_bio_mt": round(sum(r["bio_portion_mt"] or 0 for r in rows_calc), 3),
        }
    weight = sum(r["quantity_mt"] for r in usable)
    cf_blend_avg = sum(r["cf_blend"] * r["quantity_mt"] for r in usable) / weight
    wtw_blend_avg = sum(r["wtw_blend"] * r["quantity_mt"] for r in usable) / weight
    return {
        "cf_blend_avg": round(cf_blend_avg, 6),
        "wtw_blend_avg": round(wtw_blend_avg, 6),
        "total_qty_mt": round(total_qty, 3),
        "total_fossil_mt": round(sum(r["fossil_portion_mt"] or 0 for r in rows_calc), 3),
        "total_bio_mt": round(sum(r["bio_portion_mt"] or 0 for r in rows_calc), 3),
    }
