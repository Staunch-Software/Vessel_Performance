import { useState, useEffect, useCallback } from 'react'
import { memoryStore } from '../utils/memoryStore'
import { Loader2, AlertTriangle, Leaf, Clock } from 'lucide-react'
import { fetchVessels, fetchEmissionYears, fetchEmissionCII } from '../api/vesselApi'
import './EmissionPage.css'

const SOURCE_TABS = [
  { id: '', label: 'All' },
  { id: 'wni', label: 'WNI' },
  { id: 'mari_apps', label: 'MariApps' },
]

const RATING_COLORS = { A: 'a', B: 'b', C: 'c', D: 'd', E: 'e' }

function RatingBadge({ rating }) {
  if (!rating) return <span className="em-rating-badge none">—</span>
  return <span className={`em-rating-badge ${RATING_COLORS[rating] || ''}`}>{rating}</span>
}

// Horizontal scale showing where attained CII falls among the A-E boundaries
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
        <span>0</span>
        <span>{superior}</span>
        <span>{lower}</span>
        <span>{upper}</span>
        <span>{inferior}</span>
      </div>
    </div>
  )
}

function CIICard({ imo, year, source }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!imo || !year) return
    setLoading(true)
    setError(null)
    fetchEmissionCII(imo, year, source || undefined)
      .then(d => setData(d))
      .catch(e => { setError(e?.response?.data?.detail ?? 'Failed to load CII data.'); setData(null) })
      .finally(() => setLoading(false))
  }, [imo, year, source])

  return (
    <div className="em-card">
      <div className="em-card-title">
        <Leaf size={13} /> AER &amp; CII
        <span className="em-card-meta">IMO MEPC.336(76) — bulk carrier reference (MEPC.353(78)/354(78))</span>
      </div>

      {loading && <div className="em-empty"><Loader2 size={16} className="icon-spin" /> Calculating…</div>}
      {!loading && error && <div className="em-empty error"><AlertTriangle size={13} /> {error}</div>}
      {!loading && !error && data && data.note && <div className="em-empty">{data.note}</div>}

      {!loading && !error && data && data.attained_cii != null && (
        <>
          <div className="em-headline">
            <div className="em-headline-stat">
              <span className="em-headline-label">Attained CII / AER</span>
              <span className="em-headline-value">{data.attained_cii}</span>
              <span className="em-headline-unit">gCO₂ / dwt·nm</span>
            </div>
            <RatingBadge rating={data.rating} />
            <div className="em-headline-stat">
              <span className="em-headline-label">Required CII ({year})</span>
              <span className="em-headline-value muted">{data.required_cii}</span>
            </div>
            <div className="em-headline-stat">
              <span className="em-headline-label">Total CO₂</span>
              <span className="em-headline-value muted">{data.co2_total_mt} mt</span>
            </div>
            <div className="em-headline-stat">
              <span className="em-headline-label">Distance Sailed</span>
              <span className="em-headline-value muted">{data.distance_nm} nm</span>
            </div>
            <div className="em-headline-stat">
              <span className="em-headline-label">DWT</span>
              <span className="em-headline-value muted">{data.dwt}</span>
            </div>
          </div>

          <RatingScale attained={data.attained_cii} boundaries={data.rating_boundaries} />

          <div className="em-table-wrap">
            <table className="em-table">
              <thead>
                <tr><th>Fuel Grade</th><th>Consumed (mt)</th><th>Cf (t-CO₂/t-fuel)</th><th>CO₂ (mt)</th></tr>
              </thead>
              <tbody>
                {data.fuel_breakdown.map((f, i) => (
                  <tr key={i}>
                    <td>{f.grade.toUpperCase()}</td>
                    <td>{f.fuel_mt}</td>
                    <td>{f.cf}</td>
                    <td>{f.co2_mt}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

function PendingReportCard({ title }) {
  return (
    <div className="em-card">
      <div className="em-card-title">
        <Clock size={13} /> {title}
      </div>
      <div className="em-empty">
        Report definition pending — scope and format to be finalized before this can be built.
      </div>
    </div>
  )
}

export default function EmissionPage() {
  const [vessels, setVessels] = useState([])
  const [selectedImo, setImo] = useState('')
  const [years, setYears] = useState([])
  const [year, setYear] = useState(null)
  const [source, setSource] = useState('')

  useEffect(() => {
    fetchVessels()
      .then(list => {
        setVessels(list)
        if (list.length > 0) {
          const saved = memoryStore.getItem('vp_last_vessel_emission')
          setImo(saved && list.find(v => v.imo_number === saved) ? saved : list[0].imo_number)
        }
      })
      .catch(console.error)
  }, [])

  const loadYears = useCallback((imo) => {
    if (!imo) return
    fetchEmissionYears(imo)
      .then(list => {
        setYears(list)
        setYear(list.length > 0 ? list[list.length - 1] : null)
      })
      .catch(() => { setYears([]); setYear(null) })
  }, [])

  useEffect(() => { loadYears(selectedImo) }, [selectedImo, loadYears])

  return (
    <div className="em-page">
      <div className="em-topbar">
        <div className="em-topbar-left">
          <span className="em-title">Emission</span>
          <select
            className="em-vessel-select"
            value={selectedImo}
            onChange={e => {
              setImo(e.target.value)
              memoryStore.setItem('vp_last_vessel_emission', e.target.value)
            }}
          >
            {vessels.map(v => (
              <option key={v.imo_number} value={v.imo_number}>{v.vessel_name} ({v.imo_number})</option>
            ))}
          </select>
          <select className="em-year-select" value={year ?? ''} onChange={e => setYear(Number(e.target.value))}>
            {years.length === 0 && <option value="">No data</option>}
            {years.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
        <div className="em-source-tabs">
          {SOURCE_TABS.map(t => (
            <button
              key={t.id}
              className={`em-source-tab${source === t.id ? ' active' : ''}`}
              onClick={() => setSource(t.id)}
            >{t.label}</button>
          ))}
        </div>
      </div>

      <div className="em-body">
        <CIICard imo={selectedImo} year={year} source={source} />
        <PendingReportCard title="ESG Report" />
        <PendingReportCard title="SCC Report" />
        <PendingReportCard title="ESI Report" />
      </div>
    </div>
  )
}
