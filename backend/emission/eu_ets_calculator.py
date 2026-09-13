"""
EU ETS — Dir. 2003/87/EC as amended by Dir. (EU) 2023/959, which folded
maritime transport into the EU Emissions Trading System from scope-year 2024.

Pure calculation helpers — no DB access, same convention as
eu_mrv_calculator.py / imo_dcs_calculator.py. All SQL/aggregation lives in
emission_routes.py.

EU ETS reuses EU MRV's exact voyage-category classification (Art. 3gb points
to the MRV Regulation's port/voyage definitions) — a voyage is covered at:
  - 100% of CO2  — a voyage entirely between two ports under a Member
    State's jurisdiction ("between_eu"), AND (independently) 100% of CO2
    emitted at berth in an EU port regardless of the voyage's own category
    (Art. 3gb(3), mirrors MRV Art. 10(k))
  -  50% of CO2  — a voyage between an EU port and a non-EU port
    ("to_eu" / "from_eu")
  -   0% of CO2  — a voyage entirely outside EU jurisdiction ("outside_eu")

On top of the voyage-scope percentage, a PHASE-IN percentage applies to the
covered emissions themselves (Art. 3gb(2)): shipping companies were only
required to surrender allowances for 40% of verified 2024 emissions, 70% of
2025, and 100% from 2026 onwards.

CAVEAT — same real, documented data gap as EU MRV: WNI carries no "departure
port" field, so a WNI leg that arrives at an EU port without a known origin
can't be scoped at 50% or 100% — it's flagged as a gap (not guessed at) and
excluded from the covered-emissions total. See eu_mrv_calculator.py's
docstring for the full explanation; the same 'eu_direction_unknown' /
'undeterminable' categories from that module are reused here unchanged.

GHG SCOPE (Art. 3ga(1), confirmed against the client's own RefConstants
Section 9): CO2 only for scope-years 2024-2025, but CO2 + CH4 + N2O from
2026 onward — this was a real gap here (this module used to compute CO2
only, unconditionally, for every year). ghg_scope_covers_ch4_n2o() below
gates that, and the CH4/N2O figures themselves are computed by
eu_mrv_calculator.ch4_n2o_co2e_t() (same EU AR4 GWP method, shared rather
than duplicated — Art. 3ga points at the MRV Regulation's methodology).

TWO SEPARATE MONEY FIGURES, not one — this was conflated here previously:
  - EUA_PRICE_USD_PER_EUA: an ILLUSTRATIVE placeholder for the cost of
    actually BUYING allowances to surrender — this fleet has no live
    bunker/carbon brokerage feed, so this is not a market quote and should
    be replaced with the caller's real EUA price (the client's own
    reference workbook leaves this as a blank, user-supplied input for
    exactly this reason — market price, not a constant).
  - NON_SURRENDER_PENALTY_EUR_PER_T: a real, cited, FIXED figure (Art.
    16(3)) — the penalty for failing to surrender enough allowances at all,
    completely independent of whatever the market price happens to be.
    This was previously computed under the "EU Cost" label using the same
    illustrative constant as the price above, which accidentally produced
    the right NUMBER (100) for the wrong REASON (mislabeled as a purchase
    cost when it's actually this fixed penalty rate).
"""

EUA_PRICE_USD_PER_EUA = 100.0  # illustrative flat EUA price — NOT a live market quote; override per-call when a real price is available
NON_SURRENDER_PENALTY_EUR_PER_T = 100.0  # Art. 16(3) — fixed regulatory penalty rate, unrelated to EUA_PRICE_USD_PER_EUA above

# Backwards-compat alias — old name, now split into the two constants above.
CARBON_PRICE_USD_PER_EUA = EUA_PRICE_USD_PER_EUA


def ghg_scope_covers_ch4_n2o(year):
    """Art. 3ga(1): CO2 only for 2024-2025, CO2+CH4+N2O from 2026 onward."""
    return year >= 2026


def ghg_scope_label(year):
    return "CO2 + CH4 + N2O" if ghg_scope_covers_ch4_n2o(year) else "CO2 only"


def phase_in_pct(year):
    """Art. 3gb(2) phase-in of the maritime ETS obligation."""
    if year <= 2023:
        return 0.0
    if year == 2024:
        return 0.40
    if year == 2025:
        return 0.70
    return 1.00  # 2026 onwards


def ets_scope_pct(category):
    """Fraction of a leg's underway CO2 (excluding its own at-berth-in-EU
    portion, which is always scoped separately at 100%) that falls under ETS
    coverage. Returns None when the category can't be determined (the WNI
    departure-port gap) — the caller must treat that leg's underway CO2 as an
    explicit gap, not silently zero it or guess a percentage."""
    if category == "between_eu":
        return 1.00
    if category in ("to_eu", "from_eu"):
        return 0.50
    if category == "outside_eu":
        return 0.00
    return None  # eu_direction_unknown / undeterminable


# Same 4(+2) categories as EU MRV, relabeled to match the reference ETS
# dashboard's "Voyage Pattern" phrasing (direction described relative to the
# vessel's own leg, not the abstract MRV wording).
ETS_CATEGORY_LABELS = {
    "between_eu": "Inside EU",
    "to_eu": "Outside EU to Inside EU",
    "from_eu": "Inside EU to Outside EU",
    "outside_eu": "Outside EU",
    "eu_direction_unknown": "Touches EU (direction unknown)",
    "undeterminable": "Not determinable",
}
