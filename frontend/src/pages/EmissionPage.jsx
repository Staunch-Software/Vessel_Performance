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
  ['HFO', 3.114, 40.2, 'MEPC.364(79)'],
  ['LFO', 3.151, 41.0, 'VLSFO (0.5% S)'],
  ['MDO/MGO', 3.206, 42.7, ''],
  ['LNG', 2.750, 49.1, ''],
  ['Methanol', 1.375, 19.9, ''],
  ['LPG', 3.030, 46.0, ''],
  ['Biodiesel (FAME)', 2.834, 37.2, 'Same combustion Cf as fossil equivalent'],
  ['Bio-LNG', 2.750, 49.1, 'Same combustion Cf as fossil equivalent'],
  ['Bio-methanol', 1.375, 19.9, 'Same combustion Cf as fossil equivalent'],
  ['e-Diesel (RFNBO)', 3.206, 42.7, 'Zero WtT credit; same combustion Cf'],
  ['e-Methanol (RFNBO)', 1.375, 19.9, 'Zero WtT credit; same combustion Cf'],
]

const WTW_TABLE = [
  ['HFO', 91.16, 1, 40.2, ''],
  ['LFO', 91.16, 1, 41.0, ''],
  ['MDO/MGO', 91.76, 1, 42.7, ''],
  ['LNG', 0, 1, 49.1, 'Engine-dependent: 76.08–89.20 (see engine table)'],
  ['Methanol', 103.15, 1, 19.9, ''],
  ['LPG', 73.6, 1, 46.0, ''],
  ['Biodiesel (FAME)', 16.38, 1, 37.2, 'Certified sustainable — Annex II Table 1'],
  ['Bio-methanol', 13.14, 1, 19.9, ''],
  ['e-Diesel (RFNBO)', 6.58, 2, 42.7, '2x reward through 2033 — Art. 9(1)(b)'],
  ['e-Methanol (RFNBO)', 6.48, 2, 19.9, '2x reward through 2033 — Art. 9(1)(b)'],
]

const CII_Z_FACTORS = [
  [2023, '5%', 'MEPC.338(76)'], [2024, '7%', 'MEPC.338(76)'], [2025, '9%', 'MEPC.338(76)'],
  [2026, '11%', 'MEPC.338(76)'], [2027, '14.28%', 'MEPC.400(83)'], [2028, '20.41%', 'MEPC.400(83)'],
  [2029, '26.53%', 'MEPC.400(83)'], [2030, '32.65%', 'MEPC.400(83)'],
]

const FUELEU_TARGETS = [
  [2025, 89.34, '-2%'], [2026, 89.34, '-2%'], [2030, 85.69, '-6%'],
  [2035, 77.94, '-14.5%'], [2040, 62.90, '-31%'], [2045, 34.64, '-62%'], [2050, 18.23, '-80%'],
]

const IMO_REFS = [
  ['MARPOL Annex VI Reg. 27', 'DCS — Data Collection System', 'Fuel consumption reporting — annual submission to Admin/RO by 31 March'],
  ['MEPC.385(81)', 'Enhanced DCS — 6 new data items from CY2026', 'Fuel by consumer, NOT UW by consumer, OPS kWh, transport work, laden dist, innov. tech'],
  ['MEPC.401(83)', 'Operational status definitions', 'Under Way = FAOP to EOSP. Not Under Way = EOSP to next FAOP.'],
  ['MARPOL Annex VI Reg. 28', 'CII — Carbon Intensity Indicator', 'Annual operational CII rating A–E. D/E triggers corrective action plan in SEEMP III.'],
  ['MEPC.364(79)', 'CO2 emission factors (Cf)', 'Supersedes MEPC.352(78). Cf values for all fuel types incl. biofuels.'],
  ['MEPC.353(78)', 'CII reference lines', 'Ship-type-specific a, c coefficients. Bulk carrier: a=4745, c=0.622.'],
  ['MEPC.354(78)', 'CII rating boundaries', 'dd1–dd4 per ship type. Bulk carrier: 0.86, 0.94, 1.06, 1.18.'],
  ['MEPC.376(80)', 'LCA / GWP for maritime', 'GWP100 AR5: CH4=28, N2O=265. IMO standard for GHG equivalence.'],
  ['MEPC.1/Circ.905-Rev.1', 'Biofuel Cf methodology', 'Mass-weighted blended Cf. Cf_blend = Σ(mᵢ×Cfᵢ)/Σ(mᵢ).'],
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
      </div>
    </div>
  )
}
