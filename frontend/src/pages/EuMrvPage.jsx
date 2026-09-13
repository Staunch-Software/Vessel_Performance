import { useState, useEffect, useCallback } from 'react'
import { memoryStore } from '../utils/memoryStore'
import { Loader2, AlertTriangle, Info } from 'lucide-react'
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import {
  fetchVessels, fetchEmissionYears, fetchImoDcsMonthly, fetchEuMrv, fetchEuMrvLegs,
} from '../api/vesselApi'
import './EmissionPage.css'
import './ImoDcsPage.css'

// EU MRV and IMO DCS share one source selector per the earlier established
// rule (top tabs drive everything on the page, no independent inner
// toggles) — but EU MRV's per-leg classification can't blend WNI/MariApps
// (see eu_mrv_calculator.py), so 'All' isn't offered here at all — only a
// real source can produce a real classification.
const SOURCE_TABS = [
  { id: 'wni', label: 'WNI' },
  { id: 'mari_apps', label: 'MariApps' },
]
const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

const CATEGORY_BADGE_CLASS = {
  between_eu: 'mrv-badge-eu', to_eu: 'mrv-badge-eu', from_eu: 'mrv-badge-eu',
  outside_eu: 'mrv-badge-outside', eu_direction_unknown: 'mrv-badge-unknown', undeterminable: 'mrv-badge-unknown',
}

function StatRow({ items }) {
  return (
    <div className="dcs-stat-row">
      {items.map(([label, value, unit]) => (
        <div key={label} className="dcs-stat">
          <span className="dcs-stat-label">{label}</span>
          <span className="dcs-stat-value">{value}{unit ? <span className="dcs-stat-unit"> {unit}</span> : null}</span>
        </div>
      ))}
    </div>
  )
}

export default function EuMrvPage() {
  const [vessels, setVessels] = useState([])
  const [selectedImo, setImo] = useState('')
  const [years, setYears] = useState([])
  const [year, setYear] = useState(null)
  const [source, setSource] = useState('wni')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const [monthly, setMonthly] = useState([])
  const [trendLoading, setTrendLoading] = useState(false)
  const [legs, setLegs] = useState([])
  const [legsLoading, setLegsLoading] = useState(false)

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
    fetchEuMrv(selectedImo, year, source)
      .then(setData)
      .catch(e => { setError(e?.response?.data?.detail ?? 'Failed to load EU MRV data.'); setData(null) })
      .finally(() => setLoading(false))
  }, [selectedImo, year, source])

  useEffect(() => {
    if (!selectedImo || !year) return
    setTrendLoading(true)
    fetchImoDcsMonthly(selectedImo, year, source)
      .then(m => setMonthly(m.months || []))
      .catch(() => setMonthly([]))
      .finally(() => setTrendLoading(false))
  }, [selectedImo, year, source])

  useEffect(() => {
    if (!selectedImo || !year) return
    setLegsLoading(true)
    fetchEuMrvLegs(selectedImo, year, source)
      .then(r => setLegs(r.legs || []))
      .catch(() => setLegs([]))
      .finally(() => setLegsLoading(false))
  }, [selectedImo, year, source])

  return (
    <div className="em-page">
      <div className="em-topbar">
        <div className="em-topbar-left">
          <span className="em-title">EU MRV</span>
          <select className="em-vessel-select" value={selectedImo} onChange={e => { setImo(e.target.value); memoryStore.setItem('vp_last_vessel_emission', e.target.value) }}>
            {vessels.map(v => <option key={v.imo_number} value={v.imo_number}>{v.vessel_name} ({v.imo_number})</option>)}
          </select>
          <select className="em-year-select" value={year ?? ''} onChange={e => setYear(Number(e.target.value))}>
            {years.length === 0 && <option value="">No data</option>}
            {years.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
        <div className="em-source-tabs">
          {SOURCE_TABS.map(t => (
            <button key={t.id} className={`em-source-tab${source === t.id ? ' active' : ''}`} onClick={() => setSource(t.id)}>{t.label}</button>
          ))}
        </div>
      </div>

      <div className="em-body">
        {loading && <div className="em-empty"><Loader2 size={16} className="icon-spin" /> Calculating…</div>}
        {!loading && error && <div className="em-empty error"><AlertTriangle size={13} /> {error}</div>}
        {!loading && !error && data && data.note && <div className="em-empty">{data.note}</div>}

        {!loading && !error && data && !data.note && (
          <>
            <div className="em-card">
              <div className="em-card-title">A. Ship Identification</div>
              <StatRow items={[
                ['IMO Number', data.ship_id.imo_number],
                ['Ship Name', data.ship_id.ship_name || '—'],
                ['Flag State', data.ship_id.flag_state || '—'],
                ['Ship Type', data.ship_id.ship_type || '—'],
                ['GT', data.ship_id.gt ?? '—'],
              ]} />
            </div>

            <div className="em-card">
              <div className="em-card-title">B. Annual Totals <span className="em-card-meta">Reg. (EU) 2015/757 Art. 5, 9-10, as amended by Reg. (EU) 2023/957</span></div>
              <StatRow items={[
                ['Total CO₂', data.totals.total_co2_mt, 't'],
                ['Total CH₄ (as CO₂e)', data.totals.total_ch4_co2e_mt, 't'],
                ['Total N₂O (as CO₂e)', data.totals.total_n2o_co2e_mt, 't'],
                ['Total CO₂e', data.totals.total_co2e_mt, 't'],
                ['Total Distance', data.totals.total_distance_nm, 'nm'],
                ['Total Fuel Consumed', data.totals.total_fuel_mt, 't'],
                ['CO₂e At Berth in EU Ports', data.totals.at_berth_eu_co2e_mt, 't'],
                ['Hours At Berth in EU Ports', data.totals.at_berth_eu_hours, 'hr'],
              ]} />
            </div>

            {data.data_gap_note && (
              <div className="em-card">
                <div className="em-empty" style={{ alignItems: 'flex-start' }}>
                  <Info size={13} style={{ marginTop: 2, flexShrink: 0 }} />
                  <span>{data.data_gap_note}</span>
                </div>
              </div>
            )}

            <div className="em-card">
              <div className="em-card-title">C. CO₂e by Voyage Category <span className="em-card-meta">Art. 9(1)</span></div>
              <div className="em-table-wrap">
                <table className="em-table">
                  <thead><tr><th>Category</th><th>Legs</th><th>Distance (nm)</th><th>Fuel (t)</th><th>CO₂ (t)</th><th>CO₂e (t)</th></tr></thead>
                  <tbody>
                    {data.by_category.map(c => (
                      <tr key={c.category}>
                        <td><span className={`mrv-badge ${CATEGORY_BADGE_CLASS[c.category] || ''}`}>{c.label}</span></td>
                        <td>{c.leg_count}</td>
                        <td>{c.distance_nm}</td>
                        <td>{c.fuel_mt}</td>
                        <td>{c.co2_mt}</td>
                        <td>{c.co2e_mt}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="em-card">
              <div className="em-card-title">Monthly Fuel &amp; CO₂ Trend <span className="em-card-meta">{year} · {SOURCE_TABS.find(t => t.id === source)?.label}</span></div>
              {trendLoading && <div className="em-empty"><Loader2 size={14} className="icon-spin" /> Loading…</div>}
              {!trendLoading && monthly.length === 0 && <div className="em-empty">No data for {year}.</div>}
              {!trendLoading && monthly.length > 0 && (
                <div style={{ width: '100%', height: 260, padding: '10px 14px 14px' }}>
                  <ResponsiveContainer>
                    <ComposedChart data={monthly.map(m => ({ ...m, monthLabel: MONTH_NAMES[m.month - 1] }))}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                      <XAxis dataKey="monthLabel" tick={{ fill: '#7fa8cc', fontSize: 11 }} />
                      <YAxis yAxisId="fuel" tick={{ fill: '#7fa8cc', fontSize: 11 }} label={{ value: 'Fuel (t)', angle: -90, position: 'insideLeft', fill: '#5a7fa8', fontSize: 10 }} />
                      <YAxis yAxisId="co2" orientation="right" tick={{ fill: '#7fa8cc', fontSize: 11 }} label={{ value: 'CO₂ (t)', angle: 90, position: 'insideRight', fill: '#5a7fa8', fontSize: 10 }} />
                      <Tooltip contentStyle={{ background: '#0c1826', border: '1px solid #1e3a5f', fontSize: 12 }} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Bar yAxisId="fuel" dataKey="total_fuel_mt" name="Fuel (t)" fill="#1a6bb5" radius={[3, 3, 0, 0]} />
                      <Line yAxisId="co2" type="monotone" dataKey="total_co2_mt" name="CO₂ (t)" stroke="#e0a030" strokeWidth={2} dot={{ r: 3 }} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            <div className="em-card">
              <div className="em-card-title">D. Per-Leg Detail <span className="em-card-meta">{SOURCE_TABS.find(t => t.id === source)?.label} · {year}</span></div>
              {legsLoading && <div className="em-empty"><Loader2 size={14} className="icon-spin" /> Loading…</div>}
              {!legsLoading && legs.length === 0 && <div className="em-empty">No legs for {year}.</div>}
              {!legsLoading && legs.length > 0 && (
                <div className="em-table-wrap">
                  <table className="em-table">
                    <thead>
                      <tr>
                        <th>Voyage No.</th><th>L/B</th><th>From Port</th><th>To Port</th>
                        <th>EU Category</th><th>Distance (nm)</th><th>Fuel (t)</th><th>CO₂ (t)</th><th>CO₂e (t)</th>
                        <th>At-Berth EU CO₂e (t)</th><th>At-Berth EU Hours</th>
                      </tr>
                    </thead>
                    <tbody>
                      {legs.map((l, i) => (
                        <tr key={`${l.voyage_no}-${l.loading_condition}-${i}`}>
                          <td>{l.voyage_no}</td>
                          <td>{l.loading_condition}</td>
                          <td>{l.from_port || '—'}</td>
                          <td>{l.to_port || '—'}</td>
                          <td><span className={`mrv-badge ${CATEGORY_BADGE_CLASS[l.eu_category] || ''}`}>{l.eu_category_label}</span></td>
                          <td>{l.distance_nm}</td>
                          <td>{l.fuel_mt}</td>
                          <td>{l.co2_mt}</td>
                          <td>{l.co2e_mt}</td>
                          <td>{l.at_berth_eu_co2e_mt}</td>
                          <td>{l.at_berth_eu_hours}</td>
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
  )
}
