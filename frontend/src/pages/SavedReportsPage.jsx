import { useState, useEffect, useMemo, useRef } from 'react'
import { memoryStore } from '../utils/memoryStore'

import { RefreshCw, ExternalLink, Download, Search, Loader2, FileText,
         Pencil, Trash2, Check, X, Activity } from 'lucide-react'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'
import { fetchVesselReport, fetchShipGroups, runScan, fetchSyncStatus } from '../api/vesselApi'
import { getSavedReports, deleteReport, renameReport } from '../utils/savedReports'
import { condSummary } from '../constants/scanFields'
import './SavedReportsPage.css'

// ── Constants ─────────────────────────────────────────────────────────────────
const currentYear = new Date().getFullYear()
const YEARS = Array.from({ length: currentYear - 2021 }, (_, i) => String(currentYear - i))

const TIER = { none: '#38bdf8', low: '#c9a800', high: '#ef4444' }

function tier(n) {
  if (!n || n === 0) return 'none'
  if (n <= 9) return 'low'
  return 'high'
}

// ── Sub-components ────────────────────────────────────────────────────────────
function IssueBadge({ n }) {
  return <span className={`issue-badge ${tier(n ?? 0)}`}>{n ?? 0}</span>
}

function CountCell({ count, scanning, onClick }) {
  if (scanning && count === undefined)
    return <span className="vr2-cell-scanning"><Loader2 size={11} className="icon-spin" /></span>
  if (count === null)  return <span className="vr2-cell-err" title="Scan error">!</span>
  if (count === undefined) return <span className="vr2-cell-dash">—</span>
  if (count === 0)     return <span className="vr2-cell-zero">0</span>
  return <button className="vr2-cell-count" onClick={onClick}>{count}</button>
}

function DonutTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const { name, value } = payload[0]
  return (
    <div style={{ background:'#1a2a3a', border:'1px solid #2d4a6a', padding:'6px 10px', borderRadius:4, fontSize:11 }}>
      {name}: <strong>{value}</strong> vessel{value !== 1 ? 's' : ''}
    </div>
  )
}

// ── Sync status helpers ─────────────────────────────────────────────────────
function fmtSyncDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d)) return '—'
  return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', year: '2-digit', hour: '2-digit', minute: '2-digit' })
}
function fmtSyncDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d)) return '—'
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}
// 0–1 days = fresh, 2–3 = warn, >3 = stale, null = no data
function staleClass(days) {
  if (days == null) return 'none'
  if (days <= 1) return 'fresh'
  if (days <= 3) return 'warn'
  return 'stale'
}
function staleLabel(days) {
  if (days == null) return 'no data'
  if (days === 0) return 'today'
  if (days === 1) return '1 day ago'
  return `${days} days ago`
}

function SyncSourceCell({ block }) {
  return (
    <td className="sync-cell">
      <div className="sync-cell-line">
        <span className="sync-cell-key">Synced</span>
        <span>{fmtSyncDateTime(block.last_synced)}</span>
      </div>
      <div className="sync-cell-line">
        <span className="sync-cell-key">Latest</span>
        <span>{fmtSyncDate(block.latest_report_date)}</span>
        <span className={`sync-stale ${staleClass(block.stale_days)}`}>{staleLabel(block.stale_days)}</span>
      </div>
      <div className="sync-cell-line muted">
        <span className="sync-cell-key">Rows</span>
        <span>{block.analysis_count ?? 0}</span>
      </div>
    </td>
  )
}

function SyncStatusModal({ onClose }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [search,  setSearch]  = useState('')

  const load = () => {
    setLoading(true)
    setError(null)
    fetchSyncStatus()
      .then(setData)
      .catch(e => setError(e?.response?.data?.detail ?? e.message ?? 'Failed to load sync status'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])
  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const rows = useMemo(() => {
    const list = data?.vessels ?? []
    const q = search.trim().toLowerCase()
    return q ? list.filter(v => v.vessel_name.toLowerCase().includes(q) || v.imo_number.includes(q)) : list
  }, [data, search])

  return (
    <div className="manage-modal-backdrop" onClick={onClose}>
      <div className="manage-modal sync-modal" onClick={e => e.stopPropagation()}>
        <div className="manage-modal-header">
          <div className="manage-modal-title">
            <Activity size={14} />
            Data Sync Status
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className="manage-icon-btn" onClick={load} title="Refresh">
              <RefreshCw size={13} className={loading ? 'icon-spin' : ''} />
            </button>
            <button className="manage-modal-close" onClick={onClose}><X size={16} /></button>
          </div>
        </div>

        <div className="sync-modal-subbar">
          <div className="vr2-search-wrap">
            <Search size={13} />
            <input placeholder="Search vessel name or IMO…" value={search} onChange={e => setSearch(e.target.value)} />
          </div>
          <span className="sync-legend">
            <span className="sync-stale fresh">fresh</span>
            <span className="sync-stale warn">2–3d</span>
            <span className="sync-stale stale">&gt;3d</span>
            <span className="sync-stale none">no data</span>
          </span>
        </div>

        <div className="manage-modal-body">
          {loading ? (
            <div className="manage-empty"><Loader2 size={16} className="icon-spin" /> Loading sync status…</div>
          ) : error ? (
            <div className="vr2-error">⚠ {error}</div>
          ) : rows.length === 0 ? (
            <div className="manage-empty">No vessels found.</div>
          ) : (
            <table className="manage-table sync-table">
              <thead>
                <tr>
                  <th style={{ minWidth: 160 }}>Vessel</th>
                  <th style={{ minWidth: 110 }}>IMO</th>
                  <th style={{ minWidth: 220 }}>MariApps</th>
                  <th style={{ minWidth: 220 }}>WNI</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(v => (
                  <tr key={v.imo_number}>
                    <td className="manage-name">{v.vessel_name}</td>
                    <td>{v.imo_number}</td>
                    <SyncSourceCell block={v.mari_apps} />
                    <SyncSourceCell block={v.wni} />
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function SavedReportsPage({ onNavigateToScan, onNavigateToScanForEdit, onNavigateToLogbook }) {
  const [year,       setYear]       = useState(() => memoryStore.getItem('vp_vr_year') || String(currentYear))
  const [shipGroup,  setShipGroup]  = useState(() => memoryStore.getItem('vp_vr_shipgroup') || 'All')
  const [groups,     setGroups]     = useState(['All'])

  useEffect(() => { memoryStore.setItem('vp_vr_year', year) }, [year])
  useEffect(() => { memoryStore.setItem('vp_vr_shipgroup', shipGroup) }, [shipGroup])
  const [vessels,    setVessels]    = useState([])
  const [missingMapWni, setMissingMapWni] = useState({})
  const [missingMapMariapps, setMissingMapMariapps] = useState({})
  const [matrix,     setMatrix]     = useState({})
  const [scanning,   setScanning]   = useState(false)
  const [scanned,    setScanned]    = useState(false)
  const [loading,    setLoading]    = useState(false)
  const [search,     setSearch]     = useState('')
  const [error,      setError]      = useState(null)

  // Saved reports — mutable via manage panel
  const [savedReports, setSavedReports] = useState(() => getSavedReports())

  // Manage panel state
  const [manageOpen,   setManageOpen]   = useState(false)
  const [syncOpen,     setSyncOpen]     = useState(false)
  const [editingId,    setEditingId]    = useState(null)   // which row is being renamed
  const [editingName,  setEditingName]  = useState('')
  const renameInputRef = useRef(null)

  // Load ship groups once
  useEffect(() => {
    fetchShipGroups().then(setGroups).catch(console.error)
  }, [])

  async function loadVessels() {
    setLoading(true)
    setError(null)
    setMatrix({})
    setScanned(false)
    try {
      const reportData = await fetchVesselReport(Number(year), shipGroup)
      const newMissingWni = {}
      const newMissingMariapps = {}
      reportData.forEach(r => { 
        newMissingWni[r.imo_number] = r.missing_report_wni
        newMissingMariapps[r.imo_number] = r.missing_report_mariapps
      })
      setMissingMapWni(newMissingWni)
      setMissingMapMariapps(newMissingMariapps)
      setVessels(reportData.map(r => ({ imo_number: r.imo_number, vessel_name: r.vessel_name })))
    } catch (e) {
      setError(e?.response?.data?.detail ?? e.message)
    } finally {
      setLoading(false)
    }
  }

  // Load vessel + missing-report data whenever year or shipGroup changes
  useEffect(() => {
    loadVessels()
  }, [year, shipGroup]) // eslint-disable-line

  // ESC key closes manage modal
  useEffect(() => {
    if (!manageOpen) return
    function onKey(e) { if (e.key === 'Escape') setManageOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [manageOpen])

  // ── Manage panel handlers ────────────────────────────────────────────────
  function handleDelete(id) {
    const updated = deleteReport(id)
    setSavedReports(updated)
    // Remove deleted report's counts from matrix
    setMatrix(prev => {
      const next = { ...prev }
      Object.keys(next).forEach(k => { if (k.startsWith(`${id}_`)) delete next[k] })
      return next
    })
  }

  function startRename(report) {
    setEditingId(report.id)
    setEditingName(report.name)
    setTimeout(() => renameInputRef.current?.focus(), 50)
  }

  function commitRename() {
    if (!editingName.trim() || !editingId) { setEditingId(null); return }
    const updated = renameReport(editingId, editingName.trim())
    setSavedReports(updated)
    setEditingId(null)
  }

  function cancelRename() { setEditingId(null) }

  // Run every saved scan for every vessel in parallel
  async function runMatrix() {
    if (!savedReports.length || !vessels.length) return
    setScanning(true)
    const newMatrix = {}

    const tasks = vessels.flatMap(v =>
      savedReports.map(r => {
        const key = `${r.id}_${v.imo_number}`
        return runScan({
          expression: r.expression || '',
          vessel_imo: v.imo_number,
          from_date:  `${year}-01-01`,
          to_date:    `${year}-12-31`,
        })
          .then(rows => { newMatrix[key] = rows.length })
          .catch(()  => { newMatrix[key] = null })
      })
    )

    await Promise.all(tasks)
    setMatrix(newMatrix)
    setScanned(true)
    setScanning(false)
  }

  // ── Derived data ──────────────────────────────────────────────────────────
  const totalsMap = useMemo(() => {
    const out = {}
    vessels.forEach(v => {
      const missing = (missingMapWni[v.imo_number] ?? 0) + (missingMapMariapps[v.imo_number] ?? 0)
      const scanSum = savedReports.reduce((s, r) => {
        const c = matrix[`${r.id}_${v.imo_number}`]
        return s + (c ?? 0)
      }, 0)
      out[v.imo_number] = missing + scanSum
    })
    return out
  }, [vessels, missingMapWni, missingMapMariapps, matrix, savedReports])

  const donutData = useMemo(() => {
    const none = vessels.filter(v => (totalsMap[v.imo_number] ?? 0) === 0).length
    const low  = vessels.filter(v => { const t = totalsMap[v.imo_number] ?? 0; return t > 0 && t <= 9 }).length
    const high = vessels.filter(v => (totalsMap[v.imo_number] ?? 0) >= 10).length
    return [
      { name: 'No issues',  value: none, color: TIER.none },
      { name: '1-9 issues', value: low,  color: TIER.low  },
      { name: '10+ issues', value: high, color: TIER.high },
    ].filter(d => d.value > 0)
  }, [vessels, totalsMap])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return q
      ? vessels.filter(v => v.vessel_name.toLowerCase().includes(q) || v.imo_number.includes(q))
      : vessels
  }, [vessels, search])

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="vr2-page">

      {/* ── Filters ── */}
      <div className="vr2-topbar">
        <div className="vr2-filter-group">
          <span className="vr2-filter-label">Ship Group</span>
          <select className="vr2-filter-select" value={shipGroup} onChange={e => setShipGroup(e.target.value)}>
            {groups.map(g => <option key={g} value={g}>{g}</option>)}
          </select>
        </div>
        <div className="vr2-filter-group">
          <span className="vr2-filter-label">Year</span>
          <select className="vr2-filter-select" value={year} onChange={e => setYear(e.target.value)}>
            {YEARS.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
        <button
          className={`vr2-run-btn${scanning ? ' active' : ''}`}
          onClick={runMatrix}
          disabled={scanning || !savedReports.length || !vessels.length}
          title={!savedReports.length ? 'Save a scan first on the Vessel Scan tab' : 'Run all saved scans across all vessels'}
        >
          <RefreshCw size={13} className={scanning ? 'icon-spin' : ''} />
          {scanning ? 'Running matrix…' : scanned ? 'Refresh Matrix' : 'Run Matrix'}
        </button>
        {!savedReports.length && (
          <span className="vr2-hint">No saved scans yet — go to Vessel Scan tab to create one</span>
        )}
        <button className="manage-scans-btn" onClick={() => setManageOpen(true)}>
          <FileText size={13} />
          Manage Scans
          <span className="manage-count-pill">{savedReports.length}</span>
        </button>
        <button className="sync-status-btn" onClick={() => setSyncOpen(true)} title="View last-sync status for each vessel">
          <Activity size={13} />
          Sync Status
        </button>
      </div>

      {/* ── Body ── */}
      <div className="vr2-body">

        {/* Sidebar */}
        <aside className="vr2-sidebar">
          <div className="vr2-stat-box">
            <div className="vr2-stat-title">Target Vessels</div>
            <div className="vr2-stat-count">{vessels.length}</div>
            <div className="vr2-stat-label">Vessels</div>
          </div>

          <div className="vr2-health-box">
            <div className="vr2-health-title">Vessel Report Health</div>
            <div className="vr2-donut-wrap">
              <ResponsiveContainer width={130} height={130} minWidth={1} minHeight={1}>
                <PieChart>
                  <Pie
                    data={donutData.length ? donutData : [{ name:'No data', value:1, color:'#2d4a6a' }]}
                    cx="50%" cy="50%"
                    innerRadius={38} outerRadius={58}
                    paddingAngle={2} dataKey="value" strokeWidth={0}
                  >
                    {(donutData.length ? donutData : [{ color:'#2d4a6a' }]).map((d, i) => (
                      <Cell key={i} fill={d.color} />
                    ))}
                  </Pie>
                  <Tooltip content={<DonutTooltip />} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="vr2-legend">
              {[
                { label: '10+ issues', color: TIER.high },
                { label: '1-9 issues', color: TIER.low  },
                { label: 'No issues',  color: TIER.none },
              ].map(({ label, color }) => (
                <div key={label} className="vr2-legend-item">
                  <div className="vr2-legend-dot" style={{ background: color }} />
                  <span>{label}</span>
                </div>
              ))}
            </div>
          </div>
        </aside>

        {/* Main table area */}
        <div className="vr2-main">

          <div className="vr2-table-hdr">
            <span className="vr2-table-title">Vessel Details</span>
            <div className="vr2-search-wrap">
              <Search size={13} />
              <input
                placeholder="Search by vessel name or IMO…"
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </div>
          </div>

          {error && (
            <div className="vr2-error">⚠ {error}</div>
          )}

          <div className="vr2-table-wrap">
            {loading ? (
              <div className="vr2-loading"><Loader2 size={16} className="icon-spin" /> Loading vessels…</div>
            ) : filtered.length === 0 ? (
              <div className="vr2-empty">No vessels found.</div>
            ) : (
              <table className="vr2-table">
                <thead>
                  <tr className="vr2-group-row">
                    <th colSpan={5} />
                    <th colSpan={3} className="vr2-group-label" style={{ borderBottom: '1px solid #2d4a6a' }}>
                      Vessel Report (missing report)
                    </th>
                    {savedReports.length > 0 && (
                      <th colSpan={savedReports.length} className="vr2-group-label">
                        Saved Scans
                      </th>
                    )}
                  </tr>
                  {/* ── Column header ── */}
                  <tr>
                    <th className="left" style={{ width: 46 }}>Details</th>
                    <th className="left" style={{ width: 40 }}>DL</th>
                    <th className="left" style={{ minWidth: 160 }}>Vessel Name</th>
                    <th style={{ minWidth: 110 }}>IMO Number</th>
                    <th style={{ minWidth: 100 }}>Total Issues</th>
                    <th style={{ minWidth: 120, textAlign: 'center' }}>WNI</th>
                    <th style={{ minWidth: 120, textAlign: 'center' }}>MariApps</th>
                    <th style={{ minWidth: 100, textAlign: 'center' }}>Total</th>
                    {savedReports.map(r => (
                      <th key={r.id} style={{ minWidth: 130 }}>
                        <div className="col-header-wrap" title={r.name}>
                          <span className="col-header-name">{r.name}</span>
                          <button
                            className="col-delete-btn"
                            onClick={() => handleDelete(r.id)}
                            title={`Delete "${r.name}"`}
                          ><X size={10} /></button>
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(v => {
                    const total = totalsMap[v.imo_number] ?? 0
                    return (
                      <tr key={v.imo_number}>
                        {/* Details */}
                        <td className="left">
                          <button
                            className="vr2-action-btn"
                            title="Open in Logbook"
                            onClick={() => onNavigateToLogbook?.(v.imo_number)}
                          >
                            <ExternalLink size={13} />
                          </button>
                        </td>

                        {/* Download */}
                        <td className="left">
                          <button className="vr2-action-btn" title="Download">
                            <Download size={13} />
                          </button>
                        </td>

                        <td className="left" style={{ fontWeight: 500 }}>{v.vessel_name}</td>
                        <td>{v.imo_number}</td>

                        {/* Total issues */}
                        <td><IssueBadge n={total} /></td>

                        {/* Missing Report (WNI) — fixed column, not clickable */}
                        <td>
                          {missingMapWni[v.imo_number] === null ? '-' : (
                            <span className={`disc-count ${(missingMapWni[v.imo_number] ?? 0) > 0 ? 'nonzero' : 'zero'}`}>
                              {missingMapWni[v.imo_number] ?? 0}
                            </span>
                          )}
                        </td>

                        {/* Missing Report (MariApps) — fixed column, not clickable */}
                        <td>
                          {missingMapMariapps[v.imo_number] === null ? '-' : (
                            <span className={`disc-count ${(missingMapMariapps[v.imo_number] ?? 0) > 0 ? 'nonzero' : 'zero'}`}>
                              {missingMapMariapps[v.imo_number] ?? 0}
                            </span>
                          )}
                        </td>

                        {/* Missing Report (Total) — fixed column, not clickable */}
                        <td>
                          {missingMapWni[v.imo_number] === null && missingMapMariapps[v.imo_number] === null ? '-' : (
                            <span className={`disc-count ${((missingMapWni[v.imo_number] ?? 0) + (missingMapMariapps[v.imo_number] ?? 0)) > 0 ? 'nonzero' : 'zero'}`}>
                              {(missingMapWni[v.imo_number] ?? 0) + (missingMapMariapps[v.imo_number] ?? 0)}
                            </span>
                          )}
                        </td>

                        {/* Dynamic saved-scan columns */}
                        {savedReports.map(r => {
                          const count = matrix[`${r.id}_${v.imo_number}`]
                          return (
                            <td key={r.id} style={{ textAlign: 'center' }}>
                              <CountCell
                                count={count}
                                scanning={scanning}
                                onClick={() => onNavigateToScan?.(r, v.imo_number)}
                              />
                            </td>
                          )
                        })}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>

        </div>
      </div>

      {/* ── Sync Status modal ── */}
      {syncOpen && <SyncStatusModal onClose={() => setSyncOpen(false)} />}

      {/* ── Manage Scans modal ── */}
      {manageOpen && (
        <div className="manage-modal-backdrop" onClick={() => setManageOpen(false)}>
          <div className="manage-modal" onClick={e => e.stopPropagation()}>
            <div className="manage-modal-header">
              <div className="manage-modal-title">
                <FileText size={14} />
                Manage Saved Scans
                <span className="manage-count-pill">{savedReports.length}</span>
              </div>
              <button className="manage-modal-close" onClick={() => setManageOpen(false)}>
                <X size={16} />
              </button>
            </div>
            <div className="manage-modal-body">
              {savedReports.length === 0 ? (
                <div className="manage-empty">No saved scans yet. Go to Vessel Scan to create one.</div>
              ) : (
                <table className="manage-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Report Name</th>
                      <th>Expression</th>
                      <th>Created</th>
                      <th style={{ width: 130, textAlign: 'center' }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {savedReports.map((r, idx) => (
                      <tr key={r.id}>
                        <td className="manage-idx">{idx + 1}</td>
                        <td>
                          {editingId === r.id ? (
                            <div className="manage-rename-wrap">
                              <input
                                ref={renameInputRef}
                                className="manage-rename-input"
                                value={editingName}
                                onChange={e => setEditingName(e.target.value)}
                                onKeyDown={e => { if (e.key === 'Enter') commitRename(); if (e.key === 'Escape') cancelRename() }}
                              />
                              <button className="manage-icon-btn confirm" onClick={commitRename} title="Save name"><Check size={13} /></button>
                              <button className="manage-icon-btn cancel"  onClick={cancelRename} title="Cancel"><X size={13} /></button>
                            </div>
                          ) : (
                            <span className="manage-name">{r.name}</span>
                          )}
                        </td>
                        <td className="manage-cond-cell" title={r.expression || '—'}>
                          {condSummary(r.expression, null, 55)}
                        </td>
                        <td className="manage-date">
                          {r.createdAt ? new Date(r.createdAt).toLocaleDateString('en-GB', { day:'2-digit', month:'short', year:'numeric' }) : '—'}
                        </td>
                        <td>
                          <div className="manage-actions">
                            <button className="manage-icon-btn" onClick={() => startRename(r)} title="Rename">
                              <Pencil size={13} />
                            </button>
                            <button className="manage-icon-btn edit" onClick={() => { onNavigateToScanForEdit?.(r); setManageOpen(false) }} title="Edit conditions in Vessel Scan">
                              <ExternalLink size={13} />
                            </button>
                            <button className="manage-icon-btn delete" onClick={() => handleDelete(r.id)} title="Delete">
                              <Trash2 size={13} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
