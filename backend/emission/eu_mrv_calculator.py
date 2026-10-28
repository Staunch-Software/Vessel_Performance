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
CH4 / N2O — mass-based tank-to-wake emission factors from the Del. Reg. (EU)
2023/2776 table, as supplied by the client (Meena, 2026-10, from the table the
verifier also uses):
    CH4 EF = 0.00005 gCH4/gFuel     N2O EF = 0.00018 gN2O/gFuel
    (identical for HFO, LFO and MDO/MGO; this fleet burns no LNG/LPG)
This replaced an energy-based IPCC 2006 method (7.0 / 2.0 kg/TJ) taken from
the client's older RefConstants sheet — the verifier uses the regulation's
mass-based values, so the calculation now follows them.
Converted to CO2e using GWP100 from IPCC AR5: CH4=28, N2O=265 — per the
client's Emission Reference Check (Meena, 2026-10): AR5 is right for EU MRV /
EU ETS. (The older RefConstants Section 6 had AR4 25/298 here; FuelEU
Maritime is the regime that uses AR4 — see fueleu_calculator.py.)
ch4_n2o_co2e_t() below is shared by both EU MRV and EU ETS (from scope-year
2026, per Dir. 2003/87/EC Art. 3ga(1) — see eu_ets_calculator.py).
"""

# g of CH4 / N2O per g of fuel (= t per t) — Del. Reg. (EU) 2023/2776 table.
# The table gives one pair for HFO, LFO and MDO/MGO; it lists nothing for FAME
# biofuel, so bio_fuel uses the same fossil-class pair (flagged assumption).
CH4_EF_G_PER_G = {"hfo": 0.00005, "lfo": 0.00005, "mdo": 0.00005, "bio_fuel": 0.00005}
N2O_EF_G_PER_G = {"hfo": 0.00018, "lfo": 0.00018, "mdo": 0.00018, "bio_fuel": 0.00018}
GWP_EU_AR5 = {"ch4": 28, "n2o": 265}  # EU MRV / EU ETS use AR5 (Emission Reference Check); FuelEU uses AR4 (25/298)


def ch4_n2o_co2e_t(fuel_mt):
    """Returns (ch4_co2e_t, n2o_co2e_t) for a fuel-by-grade dict (tonnes of
    each grade): mass x mass-based emission factor x AR5 GWP. An unknown
    grade falls back to the HFO factors."""
    ch4_t = sum((fuel_mt.get(g) or 0) * CH4_EF_G_PER_G.get(g, CH4_EF_G_PER_G["hfo"]) for g in fuel_mt)
    n2o_t = sum((fuel_mt.get(g) or 0) * N2O_EF_G_PER_G.get(g, N2O_EF_G_PER_G["hfo"]) for g in fuel_mt)
    return (ch4_t * GWP_EU_AR5["ch4"], n2o_t * GWP_EU_AR5["n2o"])

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
