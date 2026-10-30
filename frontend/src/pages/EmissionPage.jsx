import { useState } from 'react'
import { BookOpen, Link as LinkIcon } from 'lucide-react'
import './EmissionPage.css'

// Emission landing page — reference material only (RefConstants +
// Regulatory_Refs from the client's Unified_Emissions workbook). The actual
// calculators (CII moved to IMO DCS; EU MRV/ETS/FuelEU/Biofuel Calc as they're
// built) live on their own pages under this same nav group. Values here are
// cited directly from the governing IMO/EU instruments — do not hand-edit
// without an update to the source regulation (matches the workbook's own
// "do NOT modify unless regulation is amended" note).

const CF_TABLE = [
  ['HFO', 3.114, 40.5, 'MEPC.364(79)'],
  ['LFO', 3.151, 41.0, 'HFO vs LFO is set by viscosity (ISO 8217: HFO > 80 cSt at 50 °C), not sulphur — a VLSFO above 80 cSt is HFO'],
  ['MDO/MGO', 3.206, 42.7, ''],
  ['LNG', 2.750, 49.1, ''],
  ['Methanol', 1.375, 19.9, ''],
  ['LPG — Propane', 3.000, 46.0, 'IMO lists propane and butane separately'],
  ['LPG — Butane', 3.030, 46.0, ''],
  ['Biodiesel (FAME)', 2.834, 37.0, "FAME's own Cf (not diesel's 3.206). Bio CO₂ counts as zero under EU ETS / FuelEU if RED II-compliant"],
  ['Bio-LNG', 2.750, 49.1, 'Same combustion Cf as fossil equivalent; bio-CO₂ zero-rated if RED II-compliant'],
  ['Bio-methanol', 1.375, 19.9, 'Same combustion Cf as fossil equivalent'],
  ['e-Diesel (RFNBO)', 3.206, 42.7, 'Same combustion Cf; WtT comes from the RFNBO certificate (may include captured-carbon credit), not a fixed zero'],
  ['e-Methanol (RFNBO)', 1.375, 19.9, 'Same combustion Cf; WtT comes from the RFNBO certificate, not a fixed zero'],
]

// LPG WtW = WtT 7.8 + (CO2 + CH4 x 25 + N2O x 298) / LCV 0.046 — Annex II marks
// LPG's CH4/N2O as TBM, which requires the highest default of the fuel class
// (0.00005 / 0.00018 g/g), so CO2-only (the old 73.6) is not permitted.
// Same numbers as backend/emission/fueleu_calculator.py lpg_wtw().
const LPG_PROPANE_WTW = 74.2107
const LPG_BUTANE_WTW = 74.8628
const LPG_PROPANE_CF = 3.000
const LPG_BUTANE_CF = 3.030

const WTW_TABLE = [
  ['HFO', 91.74, 1, 40.5, ''],
  ['LFO', 91.39, 1, 41.0, ''],
  ['MDO/MGO', 90.77, 1, 42.7, ''],
  ['LNG', 0, 1, 49.1, 'Engine-dependent: 76.08–89.20 (see engine table)'],
  ['Methanol', 103.15, 1, 19.9, ''],
  ['LPG — Propane', 74.21, 1, 46.0, 'WtT 7.8 + CO₂ 3.000 + CH₄/N₂O at the TBM highest default (0.00005 / 0.00018 g/g)'],
  ['LPG — Butane', 74.86, 1, 46.0, 'WtT 7.8 + CO₂ 3.030 + CH₄/N₂O at the TBM highest default (0.00005 / 0.00018 g/g)'],
  ['Biodiesel (FAME)', 'E + 1.48 (per PoS)', 1, 37.0, 'No single FuelEU default — E is the emission intensity on each consignment’s Proof of Sustainability. No PoS: HFO 91.74 (Art. 10(1)(a))'],
  ['Bio-methanol', 'E + 2.74 (per PoS)', 1, 19.9, 'As for FAME — use the PoS emission intensity E'],
  ['e-Diesel (RFNBO)', 'per RFNBO certificate', 2, 42.7, '2x reward through 2033 — Art. 9(1)(b)'],
  ['e-Methanol (RFNBO)', 'per RFNBO certificate', 2, 19.9, '2x reward through 2033 — Art. 9(1)(b)'],
]

// CH4 / N2O tank-to-wake factors (mass-based, Del. Reg. 2023/2776 table supplied
// by the client / the verifier) and the GWP sets the regimes use.
const GHG_FACTORS = [
  ['CH₄ EF — HFO / LFO / MDO-MGO', '0.00005 gCH₄/gFuel', 'Del. Reg. (EU) 2023/2776 · used by EU MRV / EU ETS'],
  ['N₂O EF — HFO / LFO / MDO-MGO', '0.00018 gN₂O/gFuel', 'Del. Reg. (EU) 2023/2776 · used by EU MRV / EU ETS'],
  ['LNG — CH₄ EF / N₂O EF', '0 / 0.00011 g/gFuel', 'Del. Reg. (EU) 2023/2776'],
  ['LNG — CH₄ slip Cslip (% of fuel mass)', 'Otto dual-fuel medium speed 3.1 · Otto dual-fuel slow speed 1.7 · Diesel dual-fuel slow speed 0.2 · Lean-burn spark-ignited 2.6', 'Del. Reg. (EU) 2023/2776'],
  ['LPG (butane / propane) — CH₄, N₂O', 'TBM → same as the fossil fuels: 0.00005 / 0.00018 g/gFuel', 'Del. Reg. (EU) 2023/2776 · Reg. 2023/1805 Annex II'],
  ['Bio-diesel (FAME) — CO₂ EF 2.834; CH₄, N₂O', 'TBM → same as the fossil fuels: 0.00005 / 0.00018 g/gFuel', 'Del. Reg. (EU) 2023/2776 · used by EU MRV / EU ETS'],
  ['Ethanol — CO₂ EF 1.913; CH₄, N₂O', 'TBM → same as the fossil fuels: 0.00005 / 0.00018 g/gFuel', 'Del. Reg. (EU) 2023/2776'],
  ['GWP100 — AR5', 'CH₄ 28 · N₂O 265', 'IMO (MEPC.376(80)); EU MRV / EU ETS'],
  ['GWP100 — AR4', 'CH₄ 25 · N₂O 298', 'FuelEU Maritime'],
]

const CII_Z_FACTORS = [
  [2023, '5%', 'MEPC.338(76)'], [2024, '7%', 'MEPC.338(76)'], [2025, '9%', 'MEPC.338(76)'],
  [2026, '11%', 'MEPC.338(76)'], [2027, '13.625%', 'MEPC.400(83)'], [2028, '16.25%', 'MEPC.400(83)'],
  [2029, '18.875%', 'MEPC.400(83)'], [2030, '21.5%', 'MEPC.400(83)'],
]

const FUELEU_TARGETS = [
  [2025, 89.34, '-2%'], [2026, 89.34, '-2%'], [2030, 85.69, '-6%'],
  [2035, 77.94, '-14.5%'], [2040, 62.90, '-31%'], [2045, 34.64, '-62%'], [2050, 18.23, '-80%'],
]

const IMO_REFS = [
  ['MARPOL Annex VI Reg. 27', 'DCS — Data Collection System', 'Fuel consumption reporting — annual submission to Admin/RO by 31 March; SoC issued by 31 May; Administration uploads to GISIS within one month'],
  ['MEPC.385(81)', 'Enhanced DCS — 6 new data items from CY2026', 'Fuel by consumer, NOT UW by consumer, OPS kWh, transport work, laden dist, innov. tech'],
  ['MEPC.401(83)', 'Operational status definitions', 'Under Way = FAOP to EOSP. Not Under Way = EOSP to next FAOP.'],
  ['MARPOL Annex VI Reg. 28', 'CII — Carbon Intensity Indicator', 'Annual operational CII rating A–E. A corrective action plan (SEEMP III) is required for an E rating, or for a D rating three consecutive years — not for any single D.'],
  ['MEPC.364(79)', 'EEDI calculation guidelines (2022) — conventional-fuel Cf', 'Supersedes MEPC.308(73). Not the CII guideline — that is MEPC.352(78) (G1), still in force. Biofuel Cf values are not listed here; they come from MEPC.1/Circ.905.'],
  ['MEPC.353(78)', 'CII reference lines', 'Ship-type-specific a, c coefficients. Bulk carrier: a=4745, c=0.622; capacity capped at 279,000 DWT.'],
  ['MEPC.354(78)', 'CII rating boundaries', 'dd1–dd4 per ship type. Bulk carrier: 0.86, 0.94, 1.06, 1.18.'],
  ['MEPC.376(80)', 'LCA / GWP for maritime', 'GWP100 AR5: CH4=28, N2O=265 — IMO standard for GHG equivalence (also EU MRV / EU ETS). FuelEU Maritime uses AR4 instead: CH4=25, N2O=298.'],
  ['MEPC.1/Circ.905-Rev.1', 'Biofuel Cf methodology', 'Mass-weighted blended Cf. Cf_blend = Σ(mᵢ×Cfᵢ)/Σ(mᵢ). The circular also allows a lower Cf for certified biofuel under DCS/CII.'],
  ['MEPC.1/Circ.896', 'Innovative technology categories', 'Cat. A / B-1 / B-2 / C-1 / C-2 — Enhanced DCS Item 6.'],
]

const EU_REFS = [
  ['Reg. (EU) 2015/757', 'EU MRV — Monitoring, Reporting, Verification', 'https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32015R0757'],
  ['Reg. (EU) 2023/957', 'MRV amendment — CH4, N2O, scope extension', 'https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32023R0957'],
  ['Dir. 2003/87/EC', 'EU ETS — Emissions Trading System (original)', 'https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32003L0087'],
  ['Dir. (EU) 2023/959', 'ETS maritime extension — Fit for 55', 'https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32023L0959'],
  ['Reg. (EU) 2023/1805', 'FuelEU Maritime — GHG intensity regulation', 'https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32023R1805'],
  ['Del. Reg. (EU) 2023/2776', 'TtW emission factors — CO2 Cf, CH4 EF, N2O EF', 'https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=OJ:L_202302776'],
  ['Dir. (EU) 2018/2001 (RED II)', 'Renewable Energy Directive — biofuel sustainability criteria', 'https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32018L2001'],
]

function LpgBlend() {
  const [propanePct, setPropanePct] = useState('')
  const p = Math.min(Math.max(Number(propanePct) || 0, 0), 100) / 100
  const wtw = p * LPG_PROPANE_WTW + (1 - p) * LPG_BUTANE_WTW
  const cf = p * LPG_PROPANE_CF + (1 - p) * LPG_BUTANE_CF
  return (
    <div className="em-empty" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 8 }}>
      <div>LPG propane/butane blend (by mass) — both fuels share LCV 46 MJ/kg, so mass- and energy-weighting coincide.</div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        Propane share (% by mass)
        <input type="number" min="0" max="100" step="1" value={propanePct}
          onChange={e => setPropanePct(e.target.value)} style={{ width: 90 }} placeholder="0–100" />
        <span>(butane {(100 - p * 100).toFixed(0)} %)</span>
      </label>
      <div>Blend WtW = <b>{wtw.toFixed(2)} gCO₂e/MJ</b> · Cf = <b>{cf.toFixed(3)} t-CO₂/t-fuel</b></div>
    </div>
  )
}

function RefTable({ head, rows }) {
  return (
    <div className="em-table-wrap">
      <table className="em-table">
        <thead><tr>{head.map(h => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{r.map((c, j) => (
              j === r.length - 1 && typeof c === 'string' && c.startsWith('http')
                ? <td key={j}><a href={c} target="_blank" rel="noreferrer" className="em-ref-link"><LinkIcon size={11} /> Source</a></td>
                : <td key={j}>{c}</td>
            ))}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function EmissionPage() {
  return (
    <div className="em-page">
      <div className="em-topbar">
        <span className="em-title">Emission — Reference</span>
      </div>
      <div className="em-body">
        <div className="em-card">
          <div className="em-card-title">
            <BookOpen size={13} /> How to use this section
          </div>
          <div className="em-empty" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 6 }}>
            <p style={{ margin: 0 }}>
              This page is reference material only — the emission-factor and regulatory constants every
              calculator on the other Emission pages (IMO DCS, EU MRV, EU ETS, FuelEU Maritime, Biofuel Calc)
              is built on. Values are cited directly from the governing IMO/EU instruments; don't hand-edit
              them without a corresponding regulation update.
            </p>
          </div>
        </div>

        <div className="em-card">
          <div className="em-card-title">TtW CO₂ Emission Factors (Cf) <span className="em-card-meta">MEPC.364(79) / Del. Reg. 2023/2776</span></div>
          <RefTable head={['Fuel Type', 'Cf (t-CO₂/t-fuel)', 'LCV (MJ/kg)', 'Notes']} rows={CF_TABLE} />
        </div>

        <div className="em-card">
          <div className="em-card-title">WtW Default Emission Factors (FuelEU) <span className="em-card-meta">Reg. 2023/1805 Annex II</span></div>
          <RefTable head={['Fuel Type', 'WtW (gCO₂e/MJ)', 'RFNBO Multiplier', 'LCV (MJ/kg)', 'Notes']} rows={WTW_TABLE} />
          <LpgBlend />
        </div>

        <div className="em-card">
          <div className="em-card-title">CII Annual Reduction Factor (Z%) <span className="em-card-meta">MEPC.338(76) / MEPC.400(83)</span></div>
          <RefTable head={['Year', 'Z-factor', 'Source']} rows={CII_Z_FACTORS} />
        </div>

        <div className="em-card">
          <div className="em-card-title">FuelEU GHG Intensity Targets <span className="em-card-meta">Reg. 2023/1805 Art. 4(2)</span></div>
          <RefTable head={['Year', 'Target (gCO₂e/MJ)', 'Reduction vs. Baseline']} rows={FUELEU_TARGETS} />
        </div>

        <div className="em-card">
          <div className="em-card-title">IMO Instruments</div>
          <RefTable head={['Instrument', 'Subject', 'Notes']} rows={IMO_REFS} />
        </div>

        <div className="em-card">
          <div className="em-card-title">EU Primary Legislation</div>
          <RefTable head={['Regulation', 'Subject', 'Link']} rows={EU_REFS} />
        </div>

        <div className="em-card">
          <div className="em-card-title">CH₄ / N₂O Factors and GWP <span className="em-card-meta">Del. Reg. 2023/2776 · Reg. 2023/1805 Annex II</span></div>
          <RefTable head={['Item', 'Value', 'Source / used in']} rows={GHG_FACTORS} />
        </div>
      </div>
    </div>
  )
}
