"""
Biofuel Calc — 1:1 rebuild of the "Biofuel_Calc" worksheet in the client's
Unified_Emissions_2026_v6 - Final.xlsx (sheet cells cited throughout below).
Every formula here is copied from that sheet's cell formulas, not
re-derived, EXCEPT the biofuel WtW: the sheet's fixed 16.38 was replaced after
the client's Emission Reference Check (Meena, 2026-10) — a PoS gives the
emission intensity E per consignment and WtW = E + 1.48 (FAME) / + 2.74
(bio-methanol); with no PoS, FuelEU Art. 10(1)(a) applies the least favourable
fossil pathway (HFO 91.7442 as the conservative default). See pos_wtw() and
stem_calc() below.

Pure calculation helpers — no DB access. All SQL/aggregation lives in
biofuel_routes.py.

============================================================================
SOURCE CONSTANTS (RefConstants sheet, same workbook):
  Section 1 (Cf, MEPC.364(79) / Del.Reg.2023/2776), row 6-8:
      HFO Cf=3.114  LFO Cf=3.151  MDO/MGO Cf=3.206   (== cii_calculator.CF_TABLE)
  Section 5 (WtW defaults, FuelEU Reg. 2023/1805 Annex II), row 66-68, 72:
      HFO WtW=91.7442  LFO WtW=91.3924  MDO/MGO WtW=90.7674  gCO2e/MJ
      (corrected per Emission Reference Check, Meena — was 91.16/91.16/91.76)
      Biodiesel(FAME) LCV=37.0 MJ/kg. Its WtW is per PoS (E + 1.48), not a
      fixed sheet value any more.
  LCV (MJ/kg), same rows as above: HFO=40.5  LFO=41.0  MDO/MGO=42.7
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
LCV_BASE = {"HFO": 40.5, "LFO": 41.0, "MDO": 42.7}          # Annex II, per Emission Reference Check
WTW_BASE = {"HFO": 91.7442, "LFO": 91.3924, "MDO": 90.7674}  # Annex II, per Emission Reference Check

LCV_BIO = 37.0    # Annex II / PoS (Biodiesel/FAME), per Emission Reference Check
CF_BIO = 0.0      # MEPC.1/Circ.905-Rev.1 — biogenic CO2 not counted for CII

# Biofuel WtW is NOT a fixed number. Per the client's Emission Reference Check
# (Meena, 2026-10) a Proof of Sustainability gives the emission intensity "E"
# per consignment, and WtW = E + a fixed adder by biofuel type. This replaces
# the earlier fixed 16.38 (the old RefConstants "Certified sustainable" row).
POS_WTW_ADDER = {"FAME Biodiesel": 1.48, "Bio-methanol": 2.74}

# No PoS -> FuelEU Art. 10(1)(a): least favourable fossil pathway for the fuel
# type. HFO is the conservative default unless the verifier confirms otherwise.
WTW_NO_POS_DEFAULT = WTW_BASE["HFO"]


def pos_wtw(biofuel_type, emission_intensity):
    """WtW (gCO2e/MJ) of a PoS-covered biofuel: E + adder. None if the type has no adder."""
    adder = POS_WTW_ADDER.get(biofuel_type)
    if adder is None or emission_intensity is None:
        return None
    return emission_intensity + adder


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


def stem_calc(base_fuel_grade, input_basis, bio_pct, rho_base, rho_bio, quantity_mt,
              pos_wtw_value=None, pos_allocated_mt=None):
    """Returns the sheet's per-row green (calculated) cells: J, K, L, M, N,
    O, P, Q, S, T — for one bunker stem row.

    pos_wtw_value / pos_allocated_mt: WtW of the linked PoS and the mass of
    its quantity allocated to this stem. The bio portion covered by the
    allocation is priced at the PoS WtW; any uncovered bio portion (or all of
    it, with no PoS) at the HFO fossil default — never double-counted."""
    grade = base_fuel_grade if base_fuel_grade in CF_BASE else "HFO"
    cf_base = CF_BASE[grade]
    lcv_base = LCV_BASE[grade]
    wtw_base = WTW_BASE[grade]

    j = bio_pct_by_mass(input_basis, bio_pct, rho_base, rho_bio)
    bio_mt = quantity_mt * j if (quantity_mt is not None and j is not None) else None

    if pos_wtw_value is not None and bio_mt:
        covered = min(max(pos_allocated_mt or 0, 0), bio_mt) / bio_mt
    else:
        covered = 0.0
    wtw_bio = covered * pos_wtw_value + (1 - covered) * WTW_NO_POS_DEFAULT if pos_wtw_value is not None else WTW_NO_POS_DEFAULT
    if covered >= 0.9999:
        wtw_bio_source = "PoS"
    elif covered > 0:
        wtw_bio_source = "Partial PoS + HFO default"
    else:
        wtw_bio_source = "No PoS (HFO default)"

    if j is None:
        return {
            "bio_pct_by_mass": None, "cf_base": cf_base, "cf_blend": None,
            "lcv_base": lcv_base, "lcv_bio": LCV_BIO, "wtw_base": wtw_base, "wtw_bio": round(wtw_bio, 4),
            "wtw_bio_source": wtw_bio_source, "pos_coverage_pct": round(covered * 100, 2),
            "wtw_blend": None, "fossil_portion_mt": None, "bio_portion_mt": None,
        }

    # Col L: =IFERROR((1-J)*K,"")
    cf_blend = (1 - j) * cf_base + j * CF_BIO

    # Col Q: =IFERROR(((1-J)*M*O+J*N*P)/((1-J)*M+J*N),"") — energy-weighted (mass x LCV as weight)
    energy_fossil = (1 - j) * lcv_base
    energy_bio = j * LCV_BIO
    denom = energy_fossil + energy_bio
    wtw_blend = (energy_fossil * wtw_base + energy_bio * wtw_bio) / denom if denom else None

    fossil_portion_mt = quantity_mt * (1 - j) if quantity_mt is not None else None  # col S
    bio_portion_mt = quantity_mt * j if quantity_mt is not None else None            # col T

    return {
        "bio_pct_by_mass": round(j * 100, 4),  # surfaced back in sheet-native percentage terms
        "cf_base": cf_base, "cf_blend": round(cf_blend, 6) if cf_blend is not None else None,
        "lcv_base": lcv_base, "lcv_bio": LCV_BIO, "wtw_base": wtw_base, "wtw_bio": round(wtw_bio, 4),
        "wtw_bio_source": wtw_bio_source, "pos_coverage_pct": round(covered * 100, 2),
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
