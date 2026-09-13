"""
FuelEU Maritime — Reg. (EU) 2023/1805.

Pure calculation helpers — no DB access, same convention as
eu_ets_calculator.py / eu_mrv_calculator.py. All SQL/aggregation lives in
emission_routes.py.

============================================================================
GHG INTENSITY TARGET (Art. 4 + Annex I) — these numbers ARE exact citations,
high confidence:
  - 2020 reference GHG intensity: 91.16 gCO2eq/MJ (Art. 4(1))
  - Reduction schedule vs. that reference (Annex I):
        2025-2029: -2%     2030-2034: -6%     2035-2039: -14.5%
        2040-2044: -31%    2045-2049: -62%    2050 onwards: -80%

============================================================================
VOYAGE ENERGY SCOPE (Art. 2(1)) — IDENTICAL 100% / 50% / 0% split as EU ETS
(Art. 2(1)(a)-(c) explicitly reuses the MRV Regulation's port/voyage
definitions), so this module reuses eu_ets_calculator.ets_scope_pct()
unchanged rather than re-deriving the same three numbers a second time.

============================================================================
GHG INTENSITY (WtW) CALCULATION — updated to the EXACT per-fuel WtW default
values published in Reg. (EU) 2023/1805 Annex II (same table the client's
Unified_Emissions_2026_v6 workbook cites in its RefConstants sheet, Section
5, and that backend/emission/biofuel_calculator.py already uses verbatim —
see WTW_BASE_G_PER_MJ below):
    HFO: 91.16   LFO: 91.16   MDO/MGO: 91.76   gCO2e/MJ
This replaces an earlier, cruder approximation (Tank-to-Wake Cf plus a flat
13.5 gCO2eq/MJ RED II Well-to-Tank adder) that was in the right ballpark
(~91 for HFO) but not the cited Annex II figure itself — now that the exact
values are confirmed from the client's own reference workbook, use them
directly rather than re-deriving an approximation of them.

Two things this still does NOT model, unchanged from before:
  - CH4/N2O slip terms (this fleet's data has no engine-type-specific slip
    factors) — same documented gap posture as ammonia/biofuel Cf=0 in
    cii_calculator.py.
  - Biofuel, absent Proof-of-Sustainability documentation in THIS schema's
    consumption records (analysis_data only carries a total "biofuel_mt"
    figure, with no link back to a specific bunker stem's PoS), is counted
    at its FOSSIL-EQUIVALENT WtW factor (here: MDO's 91.76) — this is not a
    shortcut, it is literally the Art. 9(1) fallback rule: biofuel with no
    certified sustainability/GHG-savings evidence attached must be reported
    at the default fossil value for its fuel category. Biofuel Calc (see
    biofuel_calculator.py) DOES carry the certified 16.38 gCO2e/MJ figure
    per bunker stem — but reconciling a stem against which day's
    consumption actually burned it is not yet wired up (same FIFO
    lot-windowing problem BDN Ref already solves for MariApps, not yet
    extended to biofuel specifically — see that module's docstring).

Treat GHG Intensity/Compliance Balance from this module as DIRECTIONALLY
INDICATIVE, not an audit-grade FuelEU compliance figure, until CH4/N2O slip
data and the biofuel PoS reconciliation above are in place.

============================================================================
COMPLIANCE BALANCE / BANKING / BORROWING / PENALTY (Art. 19, 20, 23) —
POLICY CHANGE from an earlier version of this module, made after checking
the client's own Unified_Emissions_2026_v6 workbook (FuelEU sheet, Sections
E-F): that reference always shows the real computed penalty for any raw
deficit, and treats Banking/Borrowing as a SEPARATE manual, multi-year
ledger (Section F's "Surplus from prior year" / "Advance borrowing" are
blank input cells the preparer fills in by hand — the sheet does not even
feed them back into the penalty calculation in Section E). An earlier
version of this module instead auto-assumed a deficit was always borrowed
in full and silently reported Estimated Penalty as 0 — that was this
codebase's own invention, not something the reference actually does, and
was MORE PERMISSIVE than the real regulation. Now matched to the reference:
  - Compliance Balance (CB, tCO2eq) = (GHG Limit - GHG Intensity) x
    Energy_used_MJ (scoped) / 1,000,000. Positive = surplus, negative =
    deficit, per Art. 20(1).
  - Banking = max(CB, 0) — this period's surplus, potentially bankable
    forward per Art. 20(2) (single-year snapshot; not itself a multi-year
    ledger).
  - Borrowing is NOT auto-derived from CB — Art. 20(3) borrowing is a
    company-declared action against a FUTURE period's allocation, capped
    and restricted after 2 consecutive deficit years, none of which this
    single-year snapshot can determine. It is reported as null with an
    explanatory note rather than guessed at.
  - Estimated Penalty is now ALWAYS the real Art. 23(2) figure
    (estimated_penalty() below) for any deficit — reflecting the raw
    exposure as if no borrowing were declared, matching the reference
    sheet's own default posture, not a silently-assumed best case.
"""

FUELEU_BASELINE_2020 = 91.16  # gCO2eq/MJ, Art. 4(1)

# (year_from, year_to inclusive, reduction fraction vs. 2020 baseline) — Annex I
REDUCTION_SCHEDULE = [
    (2020, 2024, 0.00),
    (2025, 2029, 0.02),
    (2030, 2034, 0.06),
    (2035, 2039, 0.145),
    (2040, 2044, 0.31),
    (2045, 2049, 0.62),
    (2050, 9999, 0.80),
]

# LCV (MJ/kg) and WtW default (gCO2e/MJ) — RefConstants Section 5 (Reg.
# 2023/1805 Annex II), identical values to biofuel_calculator.py's
# LCV_BASE/WTW_BASE (that module's keys are uppercase 'HFO'/'LFO'/'MDO' to
# match the client workbook's dropdown; kept lowercase here to match this
# fleet's analysis_data grade naming — same numbers, keep both in sync if
# either is ever revised).
LCV_MJ_PER_KG = {"hfo": 40.2, "lfo": 41.0, "mdo": 42.7, "bio_fuel": 37.2}
WTW_BASE_G_PER_MJ = {"hfo": 91.16, "lfo": 91.16, "mdo": 91.76}

PENALTY_RATE_EUR_PER_T = 2400.0   # Art. 23(2)
PENALTY_ENERGY_REF_MJ_PER_T = 41000.0  # Art. 23(2) VLSFO-equivalent reference energy content


def ghg_limit(year):
    """Art. 4 + Annex I regulatory GHG intensity limit for a given year, in gCO2eq/MJ."""
    for start, end, reduction in REDUCTION_SCHEDULE:
        if start <= year <= end:
            return round(FUELEU_BASELINE_2020 * (1 - reduction), 4)
    return round(FUELEU_BASELINE_2020 * 0.20, 4)  # beyond the published schedule, hold the -80% floor


def leg_wtw(fuel_mt):
    """fuel_mt: {'hfo': mt, 'lfo': mt, 'mdo': mt, 'bio_fuel': mt}. Returns
    (wtw_g_co2eq, energy_mj) for one leg/report, using the exact Annex II
    WtW default per fuel (WTW_BASE_G_PER_MJ). Biofuel is priced at MDO's
    WtW factor (Art. 9(1) no-Proof-of-Sustainability fallback — see module
    docstring)."""
    wtw_g = 0.0
    energy_mj = 0.0
    for grade, mt in fuel_mt.items():
        if not mt:
            continue
        lcv = LCV_MJ_PER_KG.get(grade, 40.2)
        wtw_factor = WTW_BASE_G_PER_MJ["mdo"] if grade == "bio_fuel" else WTW_BASE_G_PER_MJ.get(grade, WTW_BASE_G_PER_MJ["hfo"])
        mass_kg = mt * 1000
        e_mj = mass_kg * lcv
        wtw_g += wtw_factor * e_mj
        energy_mj += e_mj
    return wtw_g, energy_mj


def estimated_penalty(deficit_g_abs, ghgie_actual_g_per_mj):
    """Art. 23(2): |CB| / (GHGi_actual x 41,000 MJ/tVLSFO) x 2,400 EUR/t.
    deficit_g_abs is the absolute value of a negative Compliance Balance, in
    gCO2eq. NOTE: the client's own reference workbook has an order-of-
    operations bug in this formula (multiplies by 41,000 instead of
    dividing), which would inflate the penalty ~1000x if copied literally —
    this implementation divides, which is the only version that produces
    plausible real-world magnitudes."""
    if not ghgie_actual_g_per_mj:
        return 0.0
    vlsfo_equiv_t = deficit_g_abs / (ghgie_actual_g_per_mj * PENALTY_ENERGY_REF_MJ_PER_T)
    return round(vlsfo_equiv_t * PENALTY_RATE_EUR_PER_T, 0)
