"""
ISO 19030 Correction Calculator
================================
Implements the 6-stage calculation pipeline from
ISO19030_Correction_Methodology.docx and ISO19030_Performance_Program.xlsx.

Stages:
  0. Condition routing (Laden / Ballast)
  1. Derived quantities (T_mean, Δ, ρ_sw, ρ_air)
  2. STW validation & software correction
  3. Filtering (PASS / EXCL — 6 criteria)
  4. Resistance & power corrections (ΔP_wind, ΔP_wave, P_corr)
  5. Speed loss (V_exp from baseline polynomial, SpeedLoss%)
  6. (KPIs computed separately in kpi.py)
"""

import math
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
G = 9.81          # gravitational acceleration m/s²
KN_TO_MS = 0.5144 # 1 knot = 0.5144 m/s


# ── Config dataclass (loaded from vessel_iso_config) ──────────────────────────

@dataclass
class ISOConfig:
    # Vessel particulars
    lpp_m:              float = 185.0
    breadth_m:          float = 30.5
    block_coeff_cb:     float = 0.82
    transverse_area_m2: float = 780.0
    propeller_pitch_m:  float = 4.2
    propulsive_eff_eta_d:  float = 0.70
    shaft_eff_eta_shaft:   float = 0.98
    rho_ref_kgm3:       float = 1025.0

    # SFOC curve: list of (load_pct, sfoc_gkwh, lcv_kjkg)
    sfoc_curve: list = field(default_factory=lambda: [
        (25,  182, 42700),
        (50,  172, 42700),
        (75,  168, 42700),
        (85,  166, 42700),
        (100, 170, 42700),
        (110, 176, 42700),
    ])

    # Filter thresholds
    wind_filter_ms:        float = 5.5
    wave_hs_max_m:         float = 2.0
    depth_draft_ratio_min: float = 6.0
    rudder_max_deg:        float = 5.0
    rot_max_degmin:        float = 10.0
    loading_window_pct:    float = 5.0

    # Environmental coefficients
    c_aa: float = 0.80
    c_aw: float = 0.55

    # Condition split
    condition_split_draft_m: float = 8.5
    active_baseline:         str   = 'B2'

    # Reference displacements
    ref_displacement_laden_t:   float = 57000.0
    ref_displacement_ballast_t: float = 31700.0

    # KPI thresholds
    maintenance_trigger_pct: float = 8.0
    amber_slope_pct30d:      float = 0.5
    red_slope_pct30d:        float = 1.0
    rolling_window_records:  int   = 7


@dataclass
class BaselineCurve:
    generation: str    # 'B1' or 'B2'
    condition:  str    # 'Laden' or 'Ballast'
    a3: float = 0.0   # coefficient ×1e-12
    a2: float = 0.0   # coefficient ×1e-8
    a1: float = 1.05  # coefficient ×1e-3
    a0: float = 6.5   # offset (kn)

    def v_exp(self, p_corr_kw: float) -> float:
        """
        Expected speed from baseline polynomial.
        V_exp (kn) = (a3×1e-12)×P³ + (a2×1e-8)×P² + (a1×1e-3)×P + a0
        """
        p = p_corr_kw
        return (
            (self.a3 * 1e-12) * p**3 +
            (self.a2 * 1e-8)  * p**2 +
            (self.a1 * 1e-3)  * p    +
            self.a0
        )


# ── Input dataclass (one noon report row) ─────────────────────────────────────

@dataclass
class NoonRecord:
    """All fields needed for ISO 19030 calculation from one noon report."""
    # Identifiers
    analysis_id:    int = 0
    vessel_imo:     str = ''
    record_date:    object = None   # datetime.date

    # Drafts
    draft_fwd_m:    Optional[float] = None
    draft_aft_m:    Optional[float] = None

    # Speeds
    stw_raw_kn:     Optional[float] = None   # Speed Through Water (raw, from log)
    sog_kn:         Optional[float] = None   # Speed Over Ground
    k_stw:          float = 1.0              # STW calibration factor (default 1.0)

    # Power
    me_power_kw:    Optional[float] = None   # Measured ME power (kW) — preferred source
    me_foc_kgph:    Optional[float] = None   # ME FOC (kg/h) — for fuel-derived power
    me_rpm:         Optional[float] = None   # ME RPM (for load% calculation)
    me_mcr_kw:      Optional[float] = None   # ME MCR (kW) — for load% calculation

    # Environmental
    wind_speed_ms:  Optional[float] = None   # Relative wind speed at anemometer (m/s)
    wave_hs_m:      Optional[float] = None   # Significant wave height (m)
    sea_temp_c:     Optional[float] = None   # Seawater temperature (°C)
    air_temp_c:     Optional[float] = None   # Atmospheric air temperature (°C)
    air_pressure_hpa: Optional[float] = None  # Barometric pressure (hPa)
    water_depth_m:  Optional[float] = None   # Water depth (m)
    rudder_deg:     Optional[float] = None   # Rudder angle (°)
    rot_degmin:     Optional[float] = None   # Rate of turn (°/min)

    # Loading
    loading_condition: str = ''              # 'Laden' or 'Ballast' (if known)
    displacement_t:    Optional[float] = None  # Actual displacement from loading computer


# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class CalcResult:
    analysis_id:   int   = 0
    vessel_imo:    str   = ''
    record_date:   object = None
    condition:     str   = ''       # 'Laden' or 'Ballast'

    # Stage 2
    stw_corr:      Optional[float] = None

    # Stage 3
    filter_pass:   bool  = False
    filter_reason: str   = ''

    # Stage 4
    delta_actual:  Optional[float] = None
    rho_sw:        Optional[float] = None
    dp_wind:       Optional[float] = None
    dp_wave:       Optional[float] = None
    p_source:      Optional[float] = None
    p_corr:        Optional[float] = None

    # Stage 5
    v_exp_b1:      Optional[float] = None
    v_exp_b2:      Optional[float] = None
    speed_loss_b1: Optional[float] = None
    speed_loss_b2: Optional[float] = None


# ── SFOC interpolation ────────────────────────────────────────────────────────

def _sfoc_at_load(load_pct: float, sfoc_curve: list) -> tuple:
    """
    Interpolate SFOC (g/kWh) and LCV (kJ/kg) at the given ME load %.
    sfoc_curve: list of (load_pct, sfoc, lcv)
    Returns (sfoc_gkwh, lcv_kjkg).
    """
    curve = sorted(sfoc_curve, key=lambda x: x[0])
    if load_pct <= curve[0][0]:
        return curve[0][1], curve[0][2]
    if load_pct >= curve[-1][0]:
        return curve[-1][1], curve[-1][2]
    for i in range(len(curve) - 1):
        x0, s0, l0 = curve[i]
        x1, s1, l1 = curve[i + 1]
        if x0 <= load_pct <= x1:
            t = (load_pct - x0) / (x1 - x0)
            return s0 + t * (s1 - s0), l0 + t * (l1 - l0)
    return curve[-1][1], curve[-1][2]


# ── Main calculator ───────────────────────────────────────────────────────────

def calculate(
    record:   NoonRecord,
    config:   ISOConfig,
    curve_b1_laden:   BaselineCurve,
    curve_b1_ballast: BaselineCurve,
    curve_b2_laden:   BaselineCurve,
    curve_b2_ballast: BaselineCurve,
) -> CalcResult:
    """
    Run the full ISO 19030 6-stage pipeline for one noon record.
    Returns a CalcResult with all intermediate and final values.
    """
    res = CalcResult(
        analysis_id=record.analysis_id,
        vessel_imo=record.vessel_imo,
        record_date=record.record_date,
    )

    # ── Stage 0: Condition routing ────────────────────────────────────────────
    if record.draft_fwd_m is None or record.draft_aft_m is None:
        res.filter_pass = False
        res.filter_reason = 'Missing draft data'
        return res

    t_fwd = record.draft_fwd_m
    t_aft = record.draft_aft_m
    t_mean = (t_fwd + t_aft) / 2.0

    if record.loading_condition and record.loading_condition.lower().startswith('l'):
        condition = 'Laden'
    elif record.loading_condition and record.loading_condition.lower().startswith('b'):
        condition = 'Ballast'
    else:
        condition = 'Ballast' if t_mean <= config.condition_split_draft_m else 'Laden'

    res.condition = condition

    # ── Stage 1: Derived quantities ───────────────────────────────────────────
    t_sw = record.sea_temp_c if record.sea_temp_c is not None else 15.0
    t_air = record.air_temp_c if record.air_temp_c is not None else 25.0
    p_baro = record.air_pressure_hpa if record.air_pressure_hpa is not None else 1013.25

    rho_sw  = 1025.0 * (1.0 - 0.00021 * (t_sw - 15.0))
    rho_air = (p_baro * 100.0) / (287.05 * (t_air + 273.15))
    res.rho_sw = rho_sw

    # Displacement: use loading computer value if available, else block-coeff estimate
    if record.displacement_t and record.displacement_t > 0:
        delta = record.displacement_t
    else:
        delta = (config.lpp_m * config.breadth_m * t_mean *
                 config.block_coeff_cb * (rho_sw / 1000.0))
    res.delta_actual = delta

    # ── Stage 2: STW correction ───────────────────────────────────────────────
    if record.stw_raw_kn is None:
        res.filter_pass = False
        res.filter_reason = 'Missing STW'
        return res

    stw_corr = record.stw_raw_kn * record.k_stw
    res.stw_corr = stw_corr

    # ── Stage 3: Filtering ────────────────────────────────────────────────────
    fail_reason = _apply_filters(record, config, t_mean, delta, condition)
    if fail_reason:
        res.filter_pass = False
        res.filter_reason = fail_reason
        return res
    res.filter_pass = True

    # ── Stage 4: Power corrections ────────────────────────────────────────────
    # 4a. Power source
    p_source = _get_power_source(record, config)
    if p_source is None or p_source <= 0:
        res.filter_pass = False
        res.filter_reason = 'No power source (no ME power or FOC)'
        return res
    res.p_source = p_source

    # 4b. Wind added resistance → power penalty
    v_wind_ms = (record.wind_speed_ms or 0.0)
    v_ship_ms = stw_corr * KN_TO_MS
    r_aa = 0.5 * rho_air * config.c_aa * config.transverse_area_m2 * v_wind_ms**2
    dp_wind = r_aa * v_ship_ms / (1000.0 * config.propulsive_eff_eta_d)
    res.dp_wind = dp_wind

    # 4c. Wave added resistance → power penalty
    hs = record.wave_hs_m or 0.0
    r_aw = (0.5 * rho_sw * G * hs**2 *
            (config.breadth_m**2 / config.lpp_m) * config.c_aw)
    dp_wave = r_aw * v_ship_ms / (1000.0 * config.propulsive_eff_eta_d)
    res.dp_wave = dp_wave

    # 4d. Displacement + density correction
    delta_ref = (config.ref_displacement_laden_t
                 if condition == 'Laden'
                 else config.ref_displacement_ballast_t)

    if delta <= 0 or delta_ref <= 0:
        res.filter_pass = False
        res.filter_reason = 'Invalid displacement'
        return res

    p_net = p_source - dp_wind - dp_wave
    if p_net <= 0:
        p_net = p_source  # don't let corrections drive power negative

    p_corr = (p_net
              * (delta_ref / delta) ** (2.0 / 3.0)
              * (config.rho_ref_kgm3 / rho_sw))
    res.p_corr = p_corr

    # ── Stage 5: Speed loss ───────────────────────────────────────────────────
    b1 = curve_b1_laden if condition == 'Laden' else curve_b1_ballast
    b2 = curve_b2_laden if condition == 'Laden' else curve_b2_ballast

    v_b1 = b1.v_exp(p_corr)
    v_b2 = b2.v_exp(p_corr)

    if v_b1 > 0:
        res.v_exp_b1 = v_b1
        res.speed_loss_b1 = (stw_corr - v_b1) / v_b1 * 100.0

    if v_b2 > 0:
        res.v_exp_b2 = v_b2
        res.speed_loss_b2 = (stw_corr - v_b2) / v_b2 * 100.0

    return res


# ── Helper: filter criteria ───────────────────────────────────────────────────

def _apply_filters(record: NoonRecord, config: ISOConfig,
                   t_mean: float, delta: float, condition: str) -> str:
    """Return the first failing filter reason, or '' if all pass."""

    # Wind
    if record.wind_speed_ms is not None:
        if record.wind_speed_ms > config.wind_filter_ms:
            return f'Wind {record.wind_speed_ms:.1f} m/s > {config.wind_filter_ms} m/s'

    # Wave
    if record.wave_hs_m is not None:
        if record.wave_hs_m > config.wave_hs_max_m:
            return f'Hs {record.wave_hs_m:.2f} m > {config.wave_hs_max_m} m'

    # Water depth / draft ratio
    if record.water_depth_m is not None and t_mean > 0:
        ratio = record.water_depth_m / t_mean
        if ratio < config.depth_draft_ratio_min:
            return f'Depth/draft {ratio:.1f} < {config.depth_draft_ratio_min}'

    # Rudder
    if record.rudder_deg is not None:
        if abs(record.rudder_deg) > config.rudder_max_deg:
            return f'Rudder {abs(record.rudder_deg):.1f}° > {config.rudder_max_deg}°'

    # Rate of turn
    if record.rot_degmin is not None:
        if abs(record.rot_degmin) > config.rot_max_degmin:
            return f'ROT {abs(record.rot_degmin):.1f}°/min > {config.rot_max_degmin}°/min'

    # Loading window — displacement must be within ±X% of reference displacement
    # This is the ISO 19030 Cl. 7.2.4 loading condition filter.
    # It ensures we only compare records at similar loading to the baseline.
    if delta and delta > 0 and config.loading_window_pct:
        delta_ref = (config.ref_displacement_laden_t
                     if condition == 'Laden'
                     else config.ref_displacement_ballast_t)
        if delta_ref and delta_ref > 0:
            pct_diff = abs(delta - delta_ref) / delta_ref * 100
            if pct_diff > config.loading_window_pct:
                return (f'Loading window: Δ={delta:.0f}t vs ref={delta_ref:.0f}t '
                        f'({pct_diff:.1f}% > ±{config.loading_window_pct}%)')

    return ''   # all passed


# ── Helper: power source selection ───────────────────────────────────────────

def _get_power_source(record: NoonRecord, config: ISOConfig) -> Optional[float]:
    """
    Select ME power source per ISO 19030:
      1. Direct shaft power (me_power_kw) if available
      2. Fuel-derived power from FOC + SFOC curve
    """
    if record.me_power_kw and record.me_power_kw > 0:
        return record.me_power_kw

    # Torsion-meter power from RPM × Torque
    # Guard: ME RPM must be in a physically valid range (20–300 RPM)
    # Values outside this range indicate raw revolution counters or bad data
    if (record.me_rpm and record.me_torque_knm
            and 20 <= record.me_rpm <= 300
            and record.me_torque_knm > 0):
        import math
        return round(2 * math.pi * (record.me_rpm / 60) * record.me_torque_knm, 1)

    if record.me_foc_kgph and record.me_foc_kgph > 0:
        # Load % from RPM/MCR if available
        load_pct = 85.0  # default
        if record.me_rpm and record.me_mcr_kw and record.me_mcr_kw > 0:
            # Cubic propeller law: P ∝ N³ → load ≈ (N/N_mcr)^3 × 100
            pass  # use FOC-based approach

        sfoc, lcv = _sfoc_at_load(load_pct, config.sfoc_curve)
        if sfoc > 0 and lcv > 0:
            # P_fuel = (FOC_kgph × LCV_kjkg) / (SFOC_gkwh/1000 × 3600 × η_shaft)
            # = FOC × LCV / (sfoc/1000 × 3600 × eta)
            p_fuel = (record.me_foc_kgph * lcv) / (
                (sfoc / 1000.0) * 3600.0 * config.shaft_eff_eta_shaft
            )
            return p_fuel

    return None
