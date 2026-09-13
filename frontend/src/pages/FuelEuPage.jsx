import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { memoryStore } from '../utils/memoryStore'
import { Loader2, AlertTriangle, Info, FileText, Download, Settings } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import ExcelJS from 'exceljs'
import { saveAs } from 'file-saver'
import { fetchVessels, fetchEmissionYears, fetchFuelEu, fetchFuelEuLegs } from '../api/vesselApi'
import './EuEtsPage.css'

// FuelEU's voyage-energy scope can't blend WNI/MariApps (same reason as EU
// ETS/MRV) — a source has to be chosen.
const SOURCES = [
  { id: 'wni', label: 'WNI' },
  { id: 'mari_apps', label: 'MariApps' },
]

// Reg. (EU) 2023/1805 Art. 4(1) + Annex I — same schedule as
// backend/emission/fueleu_calculator.py's REDUCTION_SCHEDULE, mirrored here
// only to draw the forward-looking limit trajectory without a round trip
// (it's a fixed, published regulatory schedule, not derived from any
// per-vessel data).
const FUELEU_BASELINE_2020 = 91.16
const REDUCTION_SCHEDULE = [
  [2020, 2024, 0.00], [2025, 2029, 0.02], [2030, 2034, 0.06],
  [2035, 2039, 0.145], [2040, 2044, 0.31], [2045, 2049, 0.62], [2050, 9999, 0.80],
]
function ghgLimitForYear(y) {
  const band = REDUCTION_SCHEDULE.find(([from, to]) => y >= from && y <= to)
  const reduction = band ? band[2] : 0.80
  return Number((FUELEU_BASELINE_2020 * (1 - reduction)).toFixed(4))
}
const CHART_YEARS = [2025, 2030, 2035, 2040, 2045, 2050, 2055]

function fmt(n, dp = 2) {
  if (n === null || n === undefined) return '—'
  return Number(n).toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp })
}
function fmtInt(n) {
  if (n === null || n === undefined) return '—'
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 })
}
function fmtDate(iso) {
  if (!iso) return '--'
  const d = new Date(iso)
  const pad = (x) => String(x).padStart(2, '0')
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function FuelEuPage() {
  const [vessels, setVessels] = useState([])
  const [selectedImo, setImo] = useState('')
  const [years, setYears] = useState([])
  const [year, setYear] = useState(null)
  const [source, setSource] = useState('wni')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const [legs, setLegs] = useState([])
  const [legsLoading, setLegsLoading] = useState(false)
  const [compact, setCompact] = useState(false)
  const [gearOpen, setGearOpen] = useState(false)
  const gearRef = useRef(null)

  useEffect(() => {
    fetchVessels().then(list => {
      setVessels(list)
      if (list.length > 0) {
        const saved = memoryStore.getItem('vp_last_vessel_emission')
        setImo(saved && list.find(v => v.imo_number === saved) ? saved : list[0].imo_number)
      }
    }).catch(console.error)
  }, [])

  const loadYears = useCallback((imo) => {
    if (!imo) return
    fetchEmissionYears(imo)
      .then(list => { setYears(list); setYear(list.length > 0 ? list[list.length - 1] : null) })
      .catch(() => { setYears([]); setYear(null) })
  }, [])

  useEffect(() => { loadYears(selectedImo) }, [selectedImo, loadYears])

  useEffect(() => {
    if (!selectedImo || !year) return
    setLoading(true)
    setError(null)
    fetchFuelEu(selectedImo, year, source)
      .then(setData)
      .catch(e => { setError(e?.response?.data?.detail ?? 'Failed to load FuelEU Maritime data.'); setData(null) })
      .finally(() => setLoading(false))
  }, [selectedImo, year, source])

  useEffect(() => {
    if (!selectedImo || !year) return
    setLegsLoading(true)
    fetchFuelEuLegs(selectedImo, year, source)
      .then(r => setLegs(r.legs || []))
      .catch(() => setLegs([]))
      .finally(() => setLegsLoading(false))
  }, [selectedImo, year, source])

  useEffect(() => {
    if (!gearOpen) return
    const onClick = (e) => { if (gearRef.current && !gearRef.current.contains(e.target)) setGearOpen(false) }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [gearOpen])

  const vesselName = useMemo(() => vessels.find(v => v.imo_number === selectedImo)?.vessel_name, [vessels, selectedImo])

  const chartData = useMemo(() => {
    const actual = data?.results?.ghg_intensity_g_per_mj
    return CHART_YEARS.map(y => ({
      year: y,
      ghg_limit: ghgLimitForYear(y),
      ghg_intensity: actual != null ? actual : null,
    }))
  }, [data])

  function handleExcelDownload() {
    const wb = new ExcelJS.Workbook()
    const ws = wb.addWorksheet('Voyage Details')
    ws.columns = [
      { header: 'Voyage Number', key: 'voyage_no', width: 14 },
      { header: 'L/B', key: 'loading_condition', width: 10 },
      { header: 'Voyage Pattern', key: 'eu_category_label', width: 26 },
      { header: 'Port of Call [Arrival]', key: 'port_of_call', width: 18 },
      { header: 'Departure Port', key: 'from_port', width: 22 },
      { header: 'Departure Berth [UTC]', key: 'departure_time', width: 18 },
      { header: 'Arrival Port', key: 'to_port', width: 22 },
      { header: 'Arrival Berth [UTC]', key: 'arrival_time', width: 18 },
      { header: 'Next Departure Berth [UTC]', key: 'next_departure_time', width: 22 },
      { header: 'Distance [nm]', key: 'distance_nm', width: 14 },
      { header: 'Time at Sea [Hours]', key: 'time_at_sea_h', width: 16 },
      { header: 'Cargo Weight [mt]', key: 'cargo_weight_mt', width: 16 },
      { header: 'Consumption [mt]', key: 'consumption_mt', width: 16 },
    ]
    ws.getRow(1).font = { bold: true }
    legs.forEach(l => ws.addRow({
      ...l,
      departure_time: fmtDate(l.departure_time), arrival_time: fmtDate(l.arrival_time),
      next_departure_time: fmtDate(l.next_departure_time),
    }))
    wb.xlsx.writeBuffer().then(buf => saveAs(new Blob([buf]), `FuelEU_${selectedImo}_${year}_${source}.xlsx`))
  }

  function handleGetReport() {
    const doc = new jsPDF({ orientation: 'landscape' })
    doc.setFontSize(14)
    doc.text(`FuelEU Maritime Report — ${vesselName || selectedImo} (${year}, ${source.toUpperCase()})`, 14, 14)
    doc.setFontSize(10)
    doc.text(`GHG Intensity: ${fmt(data?.results?.ghg_intensity_g_per_mj)} gCO2eq/MJ   |   GHG Limit: ${fmt(data?.results?.ghg_limit_g_per_mj)} gCO2eq/MJ`, 14, 22)
    doc.text(`Compliance Balance: ${fmt(data?.results?.compliance_balance_t)} tCO2eq   |   Banking: ${fmt(data?.results?.banking_t)}   |   Borrowing: ${fmt(data?.results?.borrowing_t)}   |   Penalty: ${fmtInt(data?.results?.estimated_penalty_eur)} EUR`, 14, 28)
    autoTable(doc, {
      startY: 34,
      styles: { fontSize: 7 },
      head: [['Voyage', 'L/B', 'Pattern', 'Departure', 'Dep. Berth', 'Arrival', 'Arr. Berth', 'Dist (nm)', 'Sea (h)', 'Cargo (mt)', 'Cons. (mt)']],
      body: legs.map(l => [
        l.voyage_no, l.loading_condition, l.eu_category_label, l.from_port || '—', fmtDate(l.departure_time),
        l.to_port || '—', fmtDate(l.arrival_time), fmt(l.distance_nm, 1), fmt(l.time_at_sea_h, 1),
        fmt(l.cargo_weight_mt, 0), fmt(l.consumption_mt),
      ]),
    })
    doc.save(`FuelEU_${selectedImo}_${year}_${source}.pdf`)
  }

  return (
    <div className="ets-page">
      <div className="ets-tabbar">
        <button className="ets-tab active">Dashboard</button>
      </div>

      <div className="ets-body">
        <div className="ets-sidebar">
          <div className="ets-field">
            <label>Target</label>
            <select disabled value="vessel"><option value="vessel">Vessel</option></select>
          </div>
          <div className="ets-field">
            <label>&nbsp;</label>
            <select value={selectedImo} onChange={e => { setImo(e.target.value); memoryStore.setItem('vp_last_vessel_emission', e.target.value) }}>
              {vessels.map(v => <option key={v.imo_number} value={v.imo_number}>{v.vessel_name} ({v.imo_number})</option>)}
            </select>
          </div>
          <div className="ets-field">
            <label>Mode</label>
            <select disabled value="fueleu"><option value="fueleu">FuelEU Maritime</option></select>
          </div>
          <div className="ets-field">
            <label>Period</label>
            <select disabled value="yearly"><option value="yearly">Yearly</option></select>
          </div>
          <div className="ets-field">
            <label>&nbsp;</label>
            <select value={year ?? ''} onChange={e => setYear(Number(e.target.value))}>
              {years.length === 0 && <option value="">No data</option>}
              {years.map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
          <div className="ets-field">
            <label>Source</label>
            <div className="ets-source-tabs">
              {SOURCES.map(s => (
                <button key={s.id} className={`ets-source-tab${source === s.id ? ' active' : ''}`} onClick={() => setSource(s.id)}>{s.label}</button>
              ))}
            </div>
          </div>
        </div>

        <div className="ets-main">
          {loading && <div className="ets-empty"><Loader2 size={16} className="icon-spin" /> Calculating…</div>}
          {!loading && error && <div className="ets-empty error"><AlertTriangle size={13} /> {error}</div>}
          {!loading && !error && data && data.note && <div className="ets-empty">{data.note}</div>}

          {!loading && !error && data && !data.note && (
            <>
              <div className="ets-top-row" style={{ gridTemplateColumns: '1fr 1.3fr 1.7fr' }}>
                <div className="ets-card ets-vessel-card">
                  <div className="ets-kv"><span>Vessel</span><b>{data.ship_id.ship_name || '—'}</b></div>
                  <div className="ets-kv"><span>IMO Number</span><b>{data.ship_id.imo_number}</b></div>
                  <div className="ets-kv"><span>Vessel Type</span><b>{data.ship_id.ship_type || '—'}</b></div>
                </div>

                <div className="ets-card ets-results-card">
                  <div className="ets-card-title">Results</div>
                  <div className="ets-result-row">
                    <span>GHG Intensity</span>
                    <b>{fmt(data.results.ghg_intensity_g_per_mj)} <em>gCO<sub>2</sub>eq/MJ</em></b>
                  </div>
                  <div className="ets-result-row">
                    <span>GHG Limit</span>
                    <b>{fmt(data.results.ghg_limit_g_per_mj)} <em>gCO<sub>2</sub>eq/MJ</em></b>
                  </div>
                  <div className="ets-result-row">
                    <span>Compliance Balance</span>
                    <b>{fmt(data.results.compliance_balance_t)} <em>tCO<sub>2</sub>eq</em></b>
                  </div>
                  <div className="ets-result-row">
                    <span>Banking</span>
                    <b>{fmt(data.results.banking_t)} <em>tCO<sub>2</sub>eq</em></b>
                  </div>
                  <div className="ets-result-row">
                    <span>Borrowing</span>
                    <b>{data.results.borrowing_t == null ? 'not tracked' : fmt(data.results.borrowing_t)} {data.results.borrowing_t != null && <em>tCO<sub>2</sub>eq</em>}</b>
                  </div>
                  <div className="ets-result-row">
                    <span>Estimated Penalty</span>
                    <b>{fmtInt(data.results.estimated_penalty_eur)} <em>EUR</em></b>
                  </div>
                </div>

                <div className="ets-card ets-chart-card">
                  <div className="ets-card-title">GHG Intensity</div>
                  <div style={{ width: '100%', height: 260, padding: '10px 14px 14px' }}>
                    <ResponsiveContainer>
                      <LineChart data={chartData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                        <XAxis dataKey="year" tick={{ fill: '#7fa8cc', fontSize: 11 }} />
                        <YAxis tick={{ fill: '#7fa8cc', fontSize: 11 }} domain={[0, 100]} />
                        <Tooltip contentStyle={{ background: '#0c1826', border: '1px solid #1e3a5f', fontSize: 12 }} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <Line type="stepAfter" dataKey="ghg_intensity" name="GHG Intensity" stroke="#5a9bd8" strokeWidth={2} strokeDasharray="5 4" dot={{ r: 3 }} connectNulls />
                        <Line type="stepAfter" dataKey="ghg_limit" name="GHG Limit" stroke="#e0507a" strokeWidth={2} dot={{ r: 3 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>

              {data.data_gap_note && (
                <div className="ets-card">
                  <div className="ets-empty" style={{ alignItems: 'flex-start' }}>
                    <Info size={13} style={{ marginTop: 2, flexShrink: 0 }} />
                    <span>{data.data_gap_note}</span>
                  </div>
                </div>
              )}

              {data.borrowing_note && (
                <div className="ets-card">
                  <div className="ets-empty" style={{ alignItems: 'flex-start' }}>
                    <Info size={13} style={{ marginTop: 2, flexShrink: 0 }} />
                    <span>{data.borrowing_note}</span>
                  </div>
                </div>
              )}

              <div className="ets-card ets-table-card">
                <div className="ets-table-toolbar">
                  <button className="ets-btn" onClick={handleGetReport} disabled={legs.length === 0}>
                    <FileText size={13} /> Get Report
                  </button>
                  <div className="ets-table-title">Voyage Details</div>
                  <div className="ets-toolbar-right">
                    <button className="ets-btn" onClick={handleExcelDownload} disabled={legs.length === 0}>
                      <Download size={13} /> Excel Download
                    </button>
                    <div className="ets-gear-wrap" ref={gearRef}>
                      <button className="ets-icon-btn" onClick={() => setGearOpen(o => !o)} title="Column settings"><Settings size={14} /></button>
                      {gearOpen && (
                        <div className="ets-gear-menu">
                          <label><input type="checkbox" checked={compact} onChange={e => setCompact(e.target.checked)} /> Compact view (hide Cargo/Consumption)</label>
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {legsLoading && <div className="ets-empty"><Loader2 size={14} className="icon-spin" /> Loading…</div>}
                {!legsLoading && legs.length === 0 && <div className="ets-empty">No voyages for {year}.</div>}
                {!legsLoading && legs.length > 0 && (
                  <div className="ets-table-wrap">
                    <table className="ets-table">
                      <thead>
                        <tr>
                          <th>Voyage Number</th><th>L/B</th><th>Voyage Pattern</th>
                          <th>Port of Call [Arrival]</th>
                          <th>Departure Port<br />(UN/LOCODE)</th><th>Departure Berth<br />[UTC]</th>
                          <th>Arrival Port<br />(UN/LOCODE)</th><th>Arrival Berth<br />[UTC]</th>
                          <th>Next Departure Berth<br />[UTC]</th>
                          <th>Distance<br />[nm]</th><th>Time at Sea<br />[Hours]</th>
                          {!compact && <th>Cargo Weight<br />[mt]</th>}
                          {!compact && <th>Consumption<br />[mt]</th>}
                        </tr>
                      </thead>
                      <tbody>
                        {legs.map((l, i) => (
                          <tr key={`${l.voyage_no}-${l.loading_condition}-${i}`}>
                            <td>{l.voyage_no}</td>
                            <td>{l.loading_condition}</td>
                            <td>{l.eu_category_label}</td>
                            <td>{l.port_of_call}</td>
                            <td>{l.from_port || '—'}</td>
                            <td>{fmtDate(l.departure_time)}</td>
                            <td>{l.to_port || '--'}</td>
                            <td>{fmtDate(l.arrival_time)}</td>
                            <td>{fmtDate(l.next_departure_time)}</td>
                            <td>{fmtInt(l.distance_nm)}</td>
                            <td>{fmtInt(l.time_at_sea_h)}</td>
                            {!compact && <td>{l.cargo_weight_mt != null ? fmtInt(l.cargo_weight_mt) : '--'}</td>}
                            {!compact && <td>{fmt(l.consumption_mt)}</td>}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
