import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, ExternalLink, Download } from 'lucide-react'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'
import { fetchVesselReport, fetchShipGroups } from '../api/vesselApi'
import './VesselReportPage.css'

// ── Colour helpers ───────────────────────────────────────────────────────────
const DONUT_COLORS = {
  none: '#38bdf8',   // blue  — 0 issues
  low:  '#c9a800',   // gold  — 1-9 issues
  high: '#ef4444',   // red   — 10+ issues
}

function issueTier(n) {
  if (n === 0)  return 'none'
  if (n <= 9)   return 'low'
  return 'high'
}

function badgeClass(n) { return `issue-badge ${issueTier(n)}` }
function discClass(n)  { return `disc-count ${n > 0 ? 'nonzero' : 'zero'}` }

// Year options: 2022 → current year
const currentYear = new Date().getFullYear()
const YEARS = Array.from({ length: currentYear - 2021 }, (_, i) => String(currentYear - i))

// ── Custom donut tooltip ─────────────────────────────────────────────────────
function DonutTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const { name, value } = payload[0]
  return (
    <div style={{
      background: '#1a2a3a', border: '1px solid #2d4a6a',
      padding: '6px 10px', borderRadius: 4, fontSize: 11,
    }}>
      {name}: <strong>{value}</strong> vessel{value !== 1 ? 's' : ''}
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────
export default function VesselReportPage() {
  const navigate = useNavigate()

  const [rows,       setRows]       = useState([])
  const [groups,     setGroups]     = useState(['All'])
  const [year,       setYear]       = useState(String(currentYear))
  const [shipGroup,  setShipGroup]  = useState('All')
  const [search,     setSearch]     = useState('')
  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState(null)

  // Load ship groups once
  useEffect(() => {
    fetchShipGroups().then(setGroups).catch(console.error)
  }, [])

  // Load report data when year / shipGroup changes
  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchVesselReport(Number(year), shipGroup)
      .then(setRows)
      .catch(e => setError(e?.response?.data?.detail ?? e.message))
      .finally(() => setLoading(false))
  }, [year, shipGroup])

  // Filtered rows by search
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return rows
    return rows.filter(
      r => r.vessel_name.toLowerCase().includes(q) || r.imo_number.includes(q)
    )
  }, [rows, search])

  // Donut data
  const donutData = useMemo(() => {
    const none = rows.filter(r => r.total_issues === 0).length
    const low  = rows.filter(r => r.total_issues > 0 && r.total_issues <= 9).length
    const high = rows.filter(r => r.total_issues >= 10).length
    return [
      { name: 'No issues', value: none, color: DONUT_COLORS.none },
      { name: '1-9 issues', value: low,  color: DONUT_COLORS.low  },
      { name: '10+ issues', value: high, color: DONUT_COLORS.high },
    ].filter(d => d.value > 0)
  }, [rows])

  // Navigate to logbook pre-filtered by vessel IMO
  function openLogbook(imo) {
    navigate(`/?vessel=${imo}`)
  }

  return (
    <div style={{ display:'flex', flexDirection:'column', height:'100vh', background:'var(--bg-primary)' }}>

      {/* ── Top bar ── */}
      <div className="vr-topbar">
        <div className="sidenav-logo-icon" style={{
          width:28, height:28, background:'linear-gradient(135deg,#38bdf8,#d946ef)',
          borderRadius:6, display:'flex', alignItems:'center', justifyContent:'center',
          fontSize:12, fontWeight:700, color:'#fff', flexShrink:0,
        }}>VP</div>
        <div>
          <div className="vr-topbar-title">Vessel Report</div>
          <div className="vr-topbar-sub">Powered by Weathernews</div>
        </div>
        <div className="vr-topbar-spacer" />
        <div className="vr-topbar-user">technical@ozellar.com</div>
      </div>

      {/* ── Filters ── */}
      <div className="vr-filters">
        <div className="vr-filter-group">
          <span className="vr-filter-label">Ship Group</span>
          <select className="vr-filter-select" value={shipGroup} onChange={e => setShipGroup(e.target.value)}>
            {groups.map(g => <option key={g} value={g}>{g}</option>)}
          </select>
        </div>
        <div className="vr-filter-group">
          <span className="vr-filter-label">Year</span>
          <select className="vr-filter-select" value={year} onChange={e => setYear(e.target.value)}>
            {YEARS.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
      </div>

      {/* ── Body ── */}
      <div className="vr-body">

        {/* Left sidebar */}
        <aside className="vr-sidebar">
          {/* Target vessels stat */}
          <div className="vr-stat-box">
            <div className="vr-stat-box-title">Target Vessels</div>
            <div className="vr-stat-count">{rows.length}</div>
            <div className="vr-stat-label">Vessels</div>
          </div>

          {/* Vessel health donut */}
          <div className="vr-health-box">
            <div className="vr-health-title">Vessel Report Health</div>
            <div className="vr-donut-wrap">
              <ResponsiveContainer width={130} height={130}>
                <PieChart>
                  <Pie
                    data={donutData.length ? donutData : [{ name:'No data', value:1, color:'#2d4a6a' }]}
                    cx="50%" cy="50%"
                    innerRadius={38} outerRadius={58}
                    paddingAngle={2}
                    dataKey="value"
                    strokeWidth={0}
                  >
                    {(donutData.length ? donutData : [{ color:'#2d4a6a' }]).map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip content={<DonutTooltip />} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="vr-legend">
              {[
                { label: '10+ issues', color: DONUT_COLORS.high },
                { label: '1-9 issues', color: DONUT_COLORS.low  },
                { label: 'No issues',  color: DONUT_COLORS.none },
              ].map(({ label, color }) => (
                <div key={label} className="vr-legend-item">
                  <div className="vr-legend-dot" style={{ background: color }} />
                  <span>{label}</span>
                </div>
              ))}
            </div>
          </div>
        </aside>

        {/* Main table area */}
        <div className="vr-main">

          {/* Table header */}
          <div className="vr-table-header">
            <span className="vr-table-title">Vessel Details</span>
            <div className="vr-search-wrap">
              <span className="vr-search-icon"><Search size={13} /></span>
              <input
                placeholder="Search by vessel name or IMO…"
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </div>
          </div>

          {/* Error */}
          {error && (
            <div style={{ padding:'8px 16px', color:'#fca5a5', fontSize:12, background:'rgba(239,68,68,0.1)' }}>
              ⚠ {error}
            </div>
          )}

          {/* Table */}
          <div className="vr-table-wrap">
            {loading ? (
              <div className="vr-loading">
                <div className="spinner" /> Loading vessel report…
              </div>
            ) : filtered.length === 0 ? (
              <div className="vr-empty">No vessels found.</div>
            ) : (
              <table className="vr-table">
                <thead>
                  {/* Group header row */}
                  <tr className="group-row">
                    <th colSpan={5}></th>
                    <th colSpan={3} style={{ textAlign: 'center', borderBottom: '1px solid #2d4a6a' }}>Vessel Report (missing report)</th>
                    <th colSpan={4} style={{ textAlign: 'center' }}>Data Discrepancy</th>
                  </tr>
                  {/* Column header row */}
                  <tr>
                    <th className="left" style={{ width:50 }}>Details</th>
                    <th className="left" style={{ width:40 }}>DL</th>
                    <th className="left" style={{ minWidth:160 }}>Vessel Name</th>
                    <th style={{ minWidth:110 }}>IMO Number</th>
                    <th style={{ minWidth:100 }}>Total Issues</th>
                    <th style={{ minWidth:120, textAlign: 'center' }}>WNI</th>
                    <th style={{ minWidth:120, textAlign: 'center' }}>MariApps</th>
                    <th style={{ minWidth:100, textAlign: 'center' }}>Total</th>
                    <th style={{ minWidth:140 }}>ROB &amp; Consumption</th>
                    <th style={{ minWidth:100 }}>Distance</th>
                    <th style={{ minWidth:110 }}>Cargo Weight</th>
                    <th style={{ minWidth:100 }}>Bunkering</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(r => (
                    <tr key={r.imo_number}>
                      {/* Details icon */}
                      <td className="left">
                        <button
                          className="vr-action-btn"
                          onClick={() => openLogbook(r.imo_number)}
                          title="Open in Logbook"
                        ><ExternalLink size={13} /></button>
                      </td>

                      {/* Download icon */}
                      <td className="left">
                        <button className="vr-action-btn" title="Download"><Download size={13} /></button>
                      </td>

                      <td className="left" style={{ fontWeight: 500 }}>{r.vessel_name}</td>
                      <td>{r.imo_number}</td>

                      {/* Total issues — colour coded */}
                      <td>
                        <span className={badgeClass(r.total_issues)}>{r.total_issues}</span>
                      </td>

                      {/* Discrepancy columns */}
                      <td><span className={discClass(r.missing_report_wni)}>{r.missing_report_wni ?? 0}</span></td>
                      <td><span className={discClass(r.missing_report_mariapps)}>{r.missing_report_mariapps ?? 0}</span></td>
                      <td><span className={discClass((r.missing_report_wni ?? 0) + (r.missing_report_mariapps ?? 0))}>{(r.missing_report_wni ?? 0) + (r.missing_report_mariapps ?? 0)}</span></td>
                      <td><span className={discClass(r.rob_consumption)}>{r.rob_consumption}</span></td>
                      <td><span className={discClass(r.distance)}>{r.distance}</span></td>
                      <td><span className={discClass(r.cargo_weight)}>{r.cargo_weight}</span></td>
                      <td><span className={discClass(r.bunkering)}>{r.bunkering}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
