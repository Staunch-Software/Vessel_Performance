import { useState, useEffect, useCallback } from 'react'
import { memoryStore } from '../utils/memoryStore'
import { Loader2, AlertTriangle, BarChart2 } from 'lucide-react'
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import {
  fetchVessels, fetchEmissionYears, fetchImoDcs, saveInnovativeTech,
  fetchImoDcsMonthly, fetchImoDcsLegs, fetchImoDcsEvents,
} from '../api/vesselApi'
import './EmissionPage.css'
import './ImoDcsPage.css'

const SOURCE_TABS = [
  { id: '', label: 'All' },
  { id: 'wni', label: 'WNI' },
  { id: 'mari_apps', label: 'MariApps' },
]

// Monthly trend + per-voyage breakdown are never blended across sources (WNI
// and MariApps use incompatible Voyage_No schemes — see CLAUDE.md) — this
// mini-toggle picks which source feeds those two views independently of the
// year-total source tab above, defaulting to whichever isn't 'All'.
const DCS_SOURCE_TABS = [
  { id: 'wni', label: 'WNI' },
  { id: 'mari_apps', label: 'MariApps' },
]
const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

const RATING_COLORS = { A: 'a', B: 'b', C: 'c', D: 'd', E: 'e' }
const TECH_CATEGORIES = ['None', 'A', 'B-1', 'B-2', 'C-1', 'C-2']

function RatingBadge({ rating }) {
  if (!rating) return <span className="em-rating-badge none">—</span>
  return <span className={`em-rating-badge ${RATING_COLORS[rating] || ''}`}>{rating}</span>
}

function RatingScale({ attained, boundaries }) {
  if (!boundaries || attained == null) return null
  const { superior, lower, upper, inferior } = boundaries
  const max = inferior * 1.15
  const pct = v => Math.min(100, (v / max) * 100)
  return (
    <div className="em-scale">
      <div className="em-scale-track">
        <div className="em-scale-band a" style={{ width: `${pct(superior)}%` }} />
        <div className="em-scale-band b" style={{ width: `${pct(lower) - pct(superior)}%` }} />
        <div className="em-scale-band c" style={{ width: `${pct(upper) - pct(lower)}%` }} />
        <div className="em-scale-band d" style={{ width: `${pct(inferior) - pct(upper)}%` }} />
        <div className="em-scale-band e" style={{ width: `${100 - pct(inferior)}%` }} />
        <div className="em-scale-marker" style={{ left: `${pct(attained)}%` }} title={`Attained: ${attained}`} />
      </div>
      <div className="em-scale-labels">
        <span>0</span><span>{superior}</span><span>{lower}</span><span>{upper}</span><span>{inferior}</span>
      </div>
    </div>
  )
}

// LNG/LPG-Propane/LPG-Butane/Methanol dropped — confirmed 0 for every vessel
// in this fleet (none burn anything but HFO/LFO/MDO/Biofuel). Re-add if a
// vessel ever actually bunkers one of them.
const GRADE_LABELS = [
  ['hfo', 'HFO'], ['lfo', 'LFO'], ['mdo', 'DO/GO'], ['bio_fuel', 'Bio'],
]

function BucketCells({ bucket }) {
  if (!bucket) return <>{Array.from({ length: 10 }, (_, i) => <td key={i}>—</td>)}</>
  return (
    <>
      <td>{bucket.consumption_mt}</td>
      {GRADE_LABELS.map(([k]) => <td key={k}>{bucket[k]}</td>)}
      <td>{bucket.co2_mt}</td>
    </>
  )
}

// Matches the WNI "Leg" sheet exactly (Voyage Details | Total Consumption &
// Emissions | At Sea | In Port), minus the 2 columns we honestly can't
// populate (UN/LOCODE port codes aren't in our schema — port names only).
function LegTable({ legs, year }) {
  if (legs.length === 0) return <div className="em-empty">No legs for {year}.</div>
  return (
    <div className="em-table-wrap">
      <table className="em-table">
        <thead>
          <tr>
            <th colSpan={11}>Voyage Details</th>
            <th colSpan={4}>Total</th>
            <th colSpan={GRADE_LABELS.length + 2}>At Sea Consumption &amp; Emissions</th>
            <th colSpan={GRADE_LABELS.length + 2}>In Port Consumption &amp; Emissions</th>
          </tr>
          <tr>
            <th>Voyage No.</th><th>L/B</th><th>Departure Port</th><th>Departure [UTC]</th>
            <th>Arrival Port</th><th>Arrival [UTC]</th><th>Next Departure [UTC]</th>
            <th>Distance (nm)</th><th>Time at Sea (h)</th><th>Cargo (t)</th><th>Transport Work (mt·nm)</th>
            <th>Consumption (t)</th><th>CO₂ (t)</th><th>Attained CII</th><th>Rating</th>
            <th>Cons. (t)</th>{GRADE_LABELS.map(([k, l]) => <th key={k}>{l}</th>)}<th>CO₂ (t)</th>
            <th>Cons. (t)</th>{GRADE_LABELS.map(([k, l]) => <th key={`p-${k}`}>{l}</th>)}<th>CO₂ (t)</th>
          </tr>
        </thead>
        <tbody>
          {legs.map((l, i) => (
            <tr key={`${l.voyage_no}-${l.loading_condition}-${i}`}>
              <td>{l.voyage_no}</td>
              <td>{l.loading_condition}</td>
              <td>{l.from_port || '—'}</td>
              <td>{l.departure_time?.replace('T', ' ') || '—'}</td>
              <td>{l.to_port || '—'}</td>
              <td>{l.arrival_time?.replace('T', ' ') || '—'}</td>
              <td>{l.next_departure_time?.replace('T', ' ') || '—'}</td>
              <td>{l.distance_nm}</td>
              <td>{l.time_at_sea_h}</td>
              <td>{l.cargo_weight_mt ?? '—'}</td>
              <td>{l.transport_work_mt_nm ?? '—'}</td>
              <td>{l.consumption_total_mt}</td>
              <td>{l.co2_total_mt}</td>
              <td>{l.attained_cii ?? '—'}</td>
              <td>{l.cii_rating ? <span className={`em-rating-badge ${RATING_COLORS[l.cii_rating] || ''}`} style={{ width: 20, height: 20, fontSize: 10, borderRadius: 4 }}>{l.cii_rating}</span> : '—'}</td>
              <BucketCells bucket={l.at_sea} />
              <BucketCells bucket={l.in_port} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// Plain passthrough of the Emission Log columns already used in Logbook+ —
// same table, just filtered to this vessel/year/source. No new calculation.
const EVENT_COLUMNS = [
  ['log_type', 'Log Type'], ['log_date', 'Log Date'], ['log_number', 'Log No.'], ['voyage_no', 'Voyage No.'],
  ['from_port', 'From Port'], ['from_country', 'Country (From)'], ['from_eu_port', 'EU? (From)'],
  ['to_port', 'To Port'], ['to_country', 'Country (To)'], ['to_eu_port', 'EU? (To)'],
  ['loading_condition', 'L/B'], ['latitude', 'Lat'], ['longitude', 'Lon'], ['op_status', 'Op. Status'],
  ['distance_nm', 'Dist. (nm)'], ['duration_h', 'Hours'], ['speed_kn', 'Speed (kn)'],
  ['draft_fwd', 'Draft F (m)'], ['draft_aft', 'Draft A (m)'], ['cargo_mt', 'Cargo (t)'],
  ['me_hfo', 'ME HFO'], ['me_lfo', 'ME LFO'], ['me_mdo', 'ME MDO'], ['me_bio', 'ME Bio'], ['me_total', 'ME Total'],
  ['ae_hfo', 'AE HFO'], ['ae_lfo', 'AE LFO'], ['ae_mdo', 'AE MDO'], ['ae_bio', 'AE Bio'], ['ae_total', 'AE Total'],
  ['bl_hfo', 'Boiler HFO'], ['bl_lfo', 'Boiler LFO'], ['bl_mdo', 'Boiler MDO'], ['bl_bio', 'Boiler Bio'],
  ['boiler_total', 'Boiler Total'], ['ig_other', 'IG/Other'], ['grand_total', 'Grand Total'],
  ['total_hfo', 'Total HFO'], ['total_lfo', 'Total LFO'], ['total_mdo', 'Total MDO'], ['total_bio', 'Total Bio'],
  ['bdn_ref', 'BDN Ref'],
]

function EventTable({ events, truncated }) {
  if (events.length === 0) return <div className="em-empty">No events for this year.</div>
  return (
    <>
      {truncated && <div className="em-empty">Showing first 2000 rows — narrow the year/source to see more.</div>}
      <div className="em-table-wrap">
        <table className="em-table">
          <thead><tr>{EVENT_COLUMNS.map(([k, l]) => <th key={k}>{l}</th>)}</tr></thead>
          <tbody>
            {events.map((e, i) => (
              <tr key={i}>
                {EVENT_COLUMNS.map(([k]) => (
                  <td key={k}>{k === 'log_date' ? (e[k] || '—') : (e[k] ?? '—')}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
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

export default function ImoDcsPage() {
  const [vessels, setVessels] = useState([])
  const [selectedImo, setImo] = useState('')
  const [years, setYears] = useState([])
  const [year, setYear] = useState(null)
  const [source, setSource] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [techSaving, setTechSaving] = useState(false)

  const [dcsSource, setDcsSource] = useState('wni')
  const [monthly, setMonthly] = useState([])
  const [trendLoading, setTrendLoading] = useState(false)

  const [tableTab, setTableTab] = useState('leg') // 'leg' | 'event'
  const [legs, setLegs] = useState([])
  const [events, setEvents] = useState([])
  const [eventsTruncated, setEventsTruncated] = useState(false)
  const [tableLoading, setTableLoading] = useState(false)

  // The top source tabs (All/WNI/MariApps) are the single source-of-truth for
  // the whole page. Monthly trend / Voyage Details can't blend sources (see
  // note above DCS_SOURCE_TABS), so 'All' falls back to whichever of the two
  // was last picked via the inner toggle (default WNI) instead of showing
  // nothing — but choosing WNI or MariApps at the top always drives the chart
  // and table too, matching what the rest of the page shows.
  useEffect(() => {
    if (source === 'wni' || source === 'mari_apps') setDcsSource(source)
  }, [source])

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
    fetchImoDcs(selectedImo, year, source || undefined)
      .then(setData)
      .catch(e => { setError(e?.response?.data?.detail ?? 'Failed to load IMO DCS data.'); setData(null) })
      .finally(() => setLoading(false))
  }, [selectedImo, year, source])

  useEffect(() => {
    if (!selectedImo || !year) return
    setTrendLoading(true)
    fetchImoDcsMonthly(selectedImo, year, dcsSource)
      .then(m => setMonthly(m.months || []))
      .catch(() => setMonthly([]))
      .finally(() => setTrendLoading(false))
  }, [selectedImo, year, dcsSource])

  // Leg and Event tabs are fetched independently (only the active tab), same
  // never-blend-sources rule as the trend chart.
  useEffect(() => {
    if (!selectedImo || !year) return
    setTableLoading(true)
    if (tableTab === 'leg') {
      fetchImoDcsLegs(selectedImo, year, dcsSource)
        .then(r => setLegs(r.legs || []))
        .catch(() => setLegs([]))
        .finally(() => setTableLoading(false))
    } else {
      fetchImoDcsEvents(selectedImo, year, dcsSource)
        .then(r => { setEvents(r.events || []); setEventsTruncated(!!r.truncated) })
        .catch(() => { setEvents([]); setEventsTruncated(false) })
        .finally(() => setTableLoading(false))
    }
  }, [selectedImo, year, dcsSource, tableTab])

  async function handleTechChange(e) {
    const category = e.target.value === 'None' ? null : e.target.value
    setTechSaving(true)
    try {
      await saveInnovativeTech(selectedImo, category)
      setData(d => d ? { ...d, enhanced_dcs: { ...d.enhanced_dcs, item6_innovative_tech_category: category } } : d)
    } catch (err) {
      alert(err?.response?.data?.detail || 'Could not save.')
    } finally {
      setTechSaving(false)
    }
  }

  return (
    <div className="em-page">
      <div className="em-topbar">
        <div className="em-topbar-left">
          <span className="em-title">IMO DCS Enhanced</span>
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
            {/* Section A — Ship ID */}
            <div className="em-card">
              <div className="em-card-title">A. Ship Identification</div>
              <StatRow items={[
                ['IMO Number', data.ship_id.imo_number],
                ['Ship Name', data.ship_id.ship_name || '—'],
                ['Flag State', data.ship_id.flag_state || '—'],
                ['Ship Type', data.ship_id.ship_type || '—'],
                ['GT', data.ship_id.gt ?? '—'],
                ['DWT', data.ship_id.dwt ?? '—'],
              ]} />
            </div>

            {/* Section B — Standard DCS */}
            <div className="em-card">
              <div className="em-card-title">B. Standard DCS Data Items <span className="em-card-meta">MARPOL Annex VI Reg. 27.1</span></div>
              <StatRow items={[
                ['Total Fuel Consumed', data.standard_dcs.total_fuel_consumed_mt, 't'],
                ['Total Distance Sailed', data.standard_dcs.total_distance_nm, 'nm'],
                ['Total Hours Under Way', data.standard_dcs.total_hours_underway, 'hr'],
              ]} />
            </div>

            {/* Section C — Fuel by type + CO2 */}
            <div className="em-card">
              <div className="em-card-title">C. Fuel Consumption by Type + CO₂ <span className="em-card-meta">MEPC.364(79)</span></div>
              <div className="em-table-wrap">
                <table className="em-table">
                  <thead><tr><th>Fuel Type</th><th>Total (t)</th><th>CO₂ (t)</th></tr></thead>
                  <tbody>
                    {data.fuel_by_type.map(f => (
                      <tr key={f.fuel_type}><td>{f.fuel_type}</td><td>{f.total_mt}</td><td>{f.co2_mt}</td></tr>
                    ))}
                    <tr><td><strong>TOTAL</strong></td><td></td><td><strong>{data.total_co2_mt}</strong></td></tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* Monthly trend + per-voyage breakdown — never blended across sources */}
            <div className="em-card">
              <div className="em-card-title">
                Monthly Fuel &amp; CO₂ Trend
                <span className="em-card-meta">{year} · {DCS_SOURCE_TABS.find(t => t.id === dcsSource)?.label}{source === '' ? ' (All selected above — pick one, sources can’t be combined here)' : ''}</span>
                {source === '' && (
                  <div className="em-source-tabs" style={{ marginLeft: 'auto' }}>
                    {DCS_SOURCE_TABS.map(t => (
                      <button key={t.id} className={`em-source-tab${dcsSource === t.id ? ' active' : ''}`} onClick={() => setDcsSource(t.id)}>{t.label}</button>
                    ))}
                  </div>
                )}
              </div>
              {trendLoading && <div className="em-empty"><Loader2 size={14} className="icon-spin" /> Loading…</div>}
              {!trendLoading && monthly.length === 0 && <div className="em-empty">No {DCS_SOURCE_TABS.find(t => t.id === dcsSource)?.label} data for {year}.</div>}
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
              <div className="em-card-title">
                <div className="em-source-tabs">
                  <button className={`em-source-tab${tableTab === 'leg' ? ' active' : ''}`} onClick={() => setTableTab('leg')}>Leg</button>
                  <button className={`em-source-tab${tableTab === 'event' ? ' active' : ''}`} onClick={() => setTableTab('event')}>Event</button>
                </div>
                <span className="em-card-meta">{DCS_SOURCE_TABS.find(t => t.id === dcsSource)?.label} · {year}</span>
              </div>
              {tableLoading && <div className="em-empty"><Loader2 size={14} className="icon-spin" /> Loading…</div>}
              {!tableLoading && tableTab === 'leg' && <LegTable legs={legs} year={year} />}
              {!tableLoading && tableTab === 'event' && <EventTable events={events} truncated={eventsTruncated} />}
            </div>

            {/* Section D — Enhanced DCS */}
            <div className="em-card">
              <div className="em-card-title">D. Enhanced DCS Data Items <span className="em-card-meta">MEPC.385(81) — mandatory from CY2026</span></div>
              <div className="dcs-enhanced-grid">
                <div className="dcs-enhanced-block">
                  <p className="dcs-enhanced-head">Item 1 — Fuel by Consumer Type (t)</p>
                  <StatRow items={[
                    ['Main Engine', data.enhanced_dcs.item1_fuel_by_consumer_mt.main_engine],
                    ['Aux. Engines', data.enhanced_dcs.item1_fuel_by_consumer_mt.aux_engines],
                    ['Boilers', data.enhanced_dcs.item1_fuel_by_consumer_mt.boilers],
                    ['IG/Other', data.enhanced_dcs.item1_fuel_by_consumer_mt.ig_other],
                  ]} />
                </div>
                <div className="dcs-enhanced-block">
                  <p className="dcs-enhanced-head">Item 2 — Fuel NOT Under Way, by Consumer (t)</p>
                  <StatRow items={[
                    ['Main Engine', data.enhanced_dcs.item2_fuel_not_underway_mt.main_engine],
                    ['Aux. Engines', data.enhanced_dcs.item2_fuel_not_underway_mt.aux_engines],
                    ['Boilers', data.enhanced_dcs.item2_fuel_not_underway_mt.boilers],
                    ['IG/Other', data.enhanced_dcs.item2_fuel_not_underway_mt.ig_other],
                  ]} />
                </div>
              </div>
              <div className="dcs-enhanced-grid">
                <div className="dcs-enhanced-block">
                  <p className="dcs-enhanced-head">Item 3 — Onshore Power Supplied</p>
                  <p className="dcs-unavailable">{data.enhanced_dcs.item3_note}</p>
                </div>
                <div className="dcs-enhanced-block">
                  <p className="dcs-enhanced-head">Item 4 — Transport Work</p>
                  <StatRow items={[['Cargo × Distance', data.enhanced_dcs.item4_transport_work_mt_nm, 't·nm']]} />
                </div>
                <div className="dcs-enhanced-block">
                  <p className="dcs-enhanced-head">Item 5 — Laden Distance (voluntary)</p>
                  <StatRow items={[['Laden Distance', data.enhanced_dcs.item5_laden_distance_nm, 'nm']]} />
                </div>
                <div className="dcs-enhanced-block">
                  <p className="dcs-enhanced-head">Item 6 — Innovative Technology <span className="em-card-meta">MEPC.1/Circ.896</span></p>
                  <select
                    className="em-year-select"
                    value={data.enhanced_dcs.item6_innovative_tech_category || 'None'}
                    onChange={handleTechChange}
                    disabled={techSaving}
                  >
                    {TECH_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              </div>
            </div>

            {/* Section E — CII */}
            <div className="em-card">
              <div className="em-card-title">E. CII Calculation <span className="em-card-meta">MARPOL Annex VI Reg. 28</span></div>
              {!data.cii && <div className="em-empty">No DWT configured — set it on the Design Data tab to compute CII.</div>}
              {data.cii && (
                <>
                  <div className="em-headline">
                    <div className="em-headline-stat">
                      <span className="em-headline-label">Attained CII / AER</span>
                      <span className="em-headline-value">{data.cii.attained_cii}</span>
                      <span className="em-headline-unit">gCO₂ / dwt·nm</span>
                    </div>
                    <RatingBadge rating={data.cii.rating} />
                    <div className="em-headline-stat">
                      <span className="em-headline-label">Required CII ({year})</span>
                      <span className="em-headline-value muted">{data.cii.required_cii}</span>
                    </div>
                  </div>
                  <RatingScale attained={data.cii.attained_cii} boundaries={data.cii.rating_boundaries} />
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
