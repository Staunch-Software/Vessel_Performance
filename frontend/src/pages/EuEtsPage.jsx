import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { memoryStore } from '../utils/memoryStore'
import { Loader2, AlertTriangle, Info, FileText, Download, Settings } from 'lucide-react'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'
import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import ExcelJS from 'exceljs'
import { saveAs } from 'file-saver'
import { fetchVessels, fetchEmissionYears, fetchEuEts, fetchEuEtsLegs } from '../api/vesselApi'
import './EuEtsPage.css'

// EU ETS's own voyage classification can't blend WNI/MariApps (same reason as
// EU MRV — see eu_mrv_calculator.py), so a source has to be chosen even
// though the reference dashboard this page's layout matches doesn't surface
// one explicitly.
const SOURCES = [
  { id: 'wni', label: 'WNI' },
  { id: 'mari_apps', label: 'MariApps' },
]

const DONUT_COLORS = {
  between_eu: '#3b82c4',
  to_eu: '#2dd4bf',
  from_eu: '#8fd6c8',
  outside_eu: '#5a7a9a',
  eu_direction_unknown: '#d4a03b',
  undeterminable: '#8a5a3b',
}

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

export default function EuEtsPage() {
  const [vessels, setVessels] = useState([])
  const [selectedImo, setImo] = useState('')
  const [years, setYears] = useState([])
  const [year, setYear] = useState(null)
  const [source, setSource] = useState('wni')
  const [euaPrice, setEuaPrice] = useState('')
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
    fetchEuEts(selectedImo, year, source, euaPrice)
      .then(setData)
      .catch(e => { setError(e?.response?.data?.detail ?? 'Failed to load EU ETS data.'); setData(null) })
      .finally(() => setLoading(false))
  }, [selectedImo, year, source, euaPrice])

  useEffect(() => {
    if (!selectedImo || !year) return
    setLegsLoading(true)
    fetchEuEtsLegs(selectedImo, year, source)
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

  const donutData = useMemo(() => (data?.voyage_distribution || []).map(c => ({
    name: c.label, value: c.leg_count, pct: c.pct, category: c.category,
  })), [data])

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
    wb.xlsx.writeBuffer().then(buf => saveAs(new Blob([buf]), `EU_ETS_${selectedImo}_${year}_${source}.xlsx`))
  }

  function handleGetReport() {
    const doc = new jsPDF({ orientation: 'landscape' })
    doc.setFontSize(14)
    doc.text(`EU ETS Report — ${vesselName || selectedImo} (${year}, ${source.toUpperCase()})`, 14, 14)
    doc.setFontSize(10)
    doc.text(`GHG Emission: ${fmt(data?.results?.ghg_emission_mt)} tCO2eq   |   EU Emission: ${fmt(data?.results?.eu_emission_mt)} tCO2eq`, 14, 22)
    doc.text(`EU Allowance: ${fmtInt(data?.eu_allowance_eua)} EUA   |   EU Cost: $${fmtInt(data?.eu_cost_usd)}`, 14, 28)
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
    doc.save(`EU_ETS_${selectedImo}_${year}_${source}.pdf`)
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
            <select disabled value="ets"><option value="ets">EU ETS</option></select>
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
              <div className="ets-top-row">
                <div className="ets-card ets-vessel-card">
                  <div className="ets-kv"><span>Vessel</span><b>{data.ship_id.ship_name || '—'}</b></div>
                  <div className="ets-kv"><span>IMO Number</span><b>{data.ship_id.imo_number}</b></div>
                  <div className="ets-kv"><span>Vessel Type</span><b>{data.ship_id.ship_type || '—'}</b></div>
                </div>

                <div className="ets-card ets-results-card">
                  <div className="ets-card-title">Results <span className="ets-scope-tag">{data.results.ghg_scope}</span></div>
                  <div className="ets-result-row">
                    <span>GHG Emission</span>
                    <b>{fmt(data.results.ghg_emission_mt)} <em>tCO<sub>2</sub>eq</em></b>
                  </div>
                  <div className="ets-result-row">
                    <span>EU Emission</span>
                    <b>{fmt(data.results.eu_emission_mt)} <em>tCO<sub>2</sub>eq</em></b>
                  </div>
                  <div className="ets-boxes">
                    <div className="ets-box">
                      <div className="ets-box-label">EU Allowance</div>
                      <div className="ets-box-value">{fmtInt(data.eu_allowance_eua)}</div>
                      <div className="ets-box-unit">EUA</div>
                    </div>
                    <div className="ets-box">
                      <div className="ets-box-label">Non-Surrender Penalty</div>
                      <div className="ets-box-value">{fmtInt(data.non_surrender_penalty_eur)}</div>
                      <div className="ets-box-unit">EUR · Art. 16(3), €{data.non_surrender_penalty_rate_eur_per_t}/t</div>
                    </div>
                  </div>
                  <div className="ets-eua-price-row">
                    <label>EUA Market Price
                      <input type="number" step="0.01" placeholder="EUR/tCO2e — enter for a cost estimate"
                             value={euaPrice} onChange={e => setEuaPrice(e.target.value)} />
                    </label>
                    {data.estimated_purchase_cost_eur != null ? (
                      <div className="ets-eua-price-result"><b>{fmtInt(data.estimated_purchase_cost_eur)}</b> EUR estimated purchase cost</div>
                    ) : (
                      <div className="ets-eua-price-hint">Not a live market feed — enter a price to estimate purchase cost.</div>
                    )}
                  </div>
                </div>

                <div className="ets-card ets-donut-card">
                  <div className="ets-card-title">Voyage Distribution</div>
                  <div className="ets-donut-wrap">
                    <div className="ets-donut-legend">
                      {donutData.map(d => (
                        <div key={d.category} className="ets-legend-row">
                          <span className="ets-dot" style={{ background: DONUT_COLORS[d.category] || '#666' }} />
                          <span className="ets-legend-label">{d.name}</span>
                          <b>{d.pct}%</b>
                        </div>
                      ))}
                    </div>
                    <div className="ets-donut-chart">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie data={donutData} dataKey="value" nameKey="name" innerRadius="60%" outerRadius="90%" paddingAngle={2}>
                            {donutData.map(d => <Cell key={d.category} fill={DONUT_COLORS[d.category] || '#666'} />)}
                          </Pie>
                          <Tooltip contentStyle={{ background: '#0c1826', border: '1px solid #1e3a5f', fontSize: 12 }}
                                   formatter={(v, n, p) => [`${p.payload.pct}% (${v} legs)`, n]} />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
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
