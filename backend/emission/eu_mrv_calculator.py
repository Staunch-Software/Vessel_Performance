"""
EU MRV — Reg. (EU) 2015/757 (as amended by Reg. (EU) 2023/957, which extended
scope to CH4/N2O and non-EEA voyages from 2024).
==============================================================================
Pure classification/aggregation helpers — no DB access, same convention as
cii_calculator.py / imo_dcs_calculator.py. All SQL/aggregation lives in
emission_routes.py.

Article 9-10 require CO2 (now CO2e) to be reported per VOYAGE CATEGORY:
  - between two ports under a Member State's jurisdiction     ("between_eu")
  - from a port outside the EU to a port under EU jurisdiction ("to_eu")
  - from a port under EU jurisdiction to a port outside the EU ("from_eu")
  - aggregated separately: CO2 emitted AT BERTH within EU ports (Art. 10(k))

CAVEAT — a real, documented data gap, not a bug: WNI carries no "departure
port" field at all (see expander.py's VoyageMeta_ note), so from_eu_port is
always unpopulated for WNI legs. A WNI leg that arrives at an EU port
(to_eu='Y') genuinely cannot be classified as between_eu / to_eu without
knowing where it came from — it's tagged 'eu_direction_unknown' rather than
guessed at. MariApps has both fields (though from_eu_port itself has some
gaps — see expander.py's per-column data-source audit) so gets the full
3-way classification wherever both sides are known.

============================================================================
CH4 / N2O — this module's docstring long claimed the amended Regulation's
CH4/N2O scope, but the calculation itself only ever produced CO2 until this
was cross-checked against the client's Unified_Emissions_2026_v6 workbook
(EU_MRV sheet row 18-21) and found to be a real, silent gap. Now implemented
per that sheet's own method, energy-based per IPCC 2006 (RefConstants
Sections 2 & 4 — same client workbook, sheet RefConstants):
    CH4 EF = 7.0 kg/TJ     N2O EF = 2.0 kg/TJ   (HFO/LFO/MDO/Biodiesel share
    these two figures — only LNG differs, and this fleet burns none)
Converted to CO2e using the EU's own AR4 GWP (Reg. 2015/757 uses AR4, not
IMO's AR5 used for CII/DCS): CH4=25, N2O=298 (RefConstants Section 6).
ch4_n2o_co2e_t() below is shared by both EU MRV and EU ETS (from scope-year
2026, per Dir. 2003/87/EC Art. 3ga(1) — see eu_ets_calculator.py).
"""

# LCV (MJ/kg) — RefConstants Sections 1/5. Same figures as
# fueleu_calculator.LCV_MJ_PER_KG / biofuel_calculator.LCV_BASE — kept as a
# separate copy here (lowercase grade keys, matching this fleet's
# analysis_data naming) rather than cross-importing between otherwise
# independent calculator modules; keep all three in sync if ever revised.
LCV_MJ_PER_KG = {"hfo": 40.2, "lfo": 41.0, "mdo": 42.7, "bio_fuel": 37.2}

CH4_EF_KG_PER_TJ = 7.0   # RefConstants Section 2 (Del. Reg. 2023/2776 / IPCC 2006)
N2O_EF_KG_PER_TJ = 2.0   # RefConstants Section 4 (Del. Reg. 2023/2776 / IPCC 2006)
GWP_EU_AR4 = {"ch4": 25, "n2o": 298}  # RefConstants Section 6 — EU MRV/ETS use AR4, not IMO's AR5


def ghg_energy_tj(fuel_mt):
    """Total energy (TJ) for a fuel-by-grade dict — the base of the
    energy-based CH4/N2O method below (and cross-checks against
    fueleu_calculator's own per-leg energy figure, just in TJ not MJ)."""
    return sum((fuel_mt.get(g) or 0) * LCV_MJ_PER_KG.get(g, 40.2) * 1000 / 1_000_000 for g in fuel_mt)


def ch4_n2o_co2e_t(fuel_mt):
    """Returns (ch4_co2e_t, n2o_co2e_t) for a fuel-by-grade dict, per the
    EU_MRV sheet's own row 18-21 method (see module docstring)."""
    energy_tj = ghg_energy_tj(fuel_mt)
    ch4_kg = energy_tj * CH4_EF_KG_PER_TJ
    n2o_kg = energy_tj * N2O_EF_KG_PER_TJ
    return (ch4_kg / 1000 * GWP_EU_AR4["ch4"], n2o_kg / 1000 * GWP_EU_AR4["n2o"])

EU_VOYAGE_CATEGORIES = {
    "between_eu", "to_eu", "from_eu", "outside_eu",
    "eu_direction_unknown", "undeterminable",
}

CATEGORY_LABELS = {
    "between_eu": "Between EU ports",
    "to_eu": "Non-EU → EU",
    "from_eu": "EU → Non-EU",
    "outside_eu": "Outside EU scope",
    "eu_direction_unknown": "Touches EU (direction unknown)",
    "undeterminable": "Not determinable",
}


def classify_eu_voyage(from_eu, to_eu):
    """from_eu / to_eu are 'Y'/'N'/None strings (matches emissionx_from_eu_port
    / emissionx_to_eu_port as stored). See module docstring for the WNI gap."""
    if from_eu == "Y" and to_eu == "Y":
        return "between_eu"
    if from_eu == "Y" and to_eu == "N":
        return "from_eu"
    if from_eu == "N" and to_eu == "Y":
        return "to_eu"
    if from_eu == "N" and to_eu == "N":
        return "outside_eu"
    if to_eu == "Y":
        # from_eu missing (the WNI gap) but we know it touches an EU port.
        return "eu_direction_unknown"
    # from_eu missing AND to_eu missing/'N' — to_eu='N' alone doesn't rule out
    # an EU-outbound leg (from could still be EU), so this is genuinely
    # unknowable, not "outside EU" by default.
    return "undeterminable"
