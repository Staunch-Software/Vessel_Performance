import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { memoryStore } from './utils/memoryStore'

import { Zap, AlertTriangle, FileText, Database, BarChart2, ChevronDown, Users, LogOut, Shield, BookOpen, Map, ScrollText, Leaf, Fuel } from 'lucide-react'
import { queryAnalysis, queryExpandedData, fetchExpandedColumns, fetchUserColumnPrefs, fetchVesselColumnDefaults, fetchCPCompliancePilotVessels, fetchCPCompliance } from './api/vesselApi'
import { PERFORMANCE_COLUMNS } from './utils/performanceColumns'
import TopFilterBar from './components/TopFilterBar'
import FuelBarChart from './components/FuelBarChart'
import AverageValuesPanel from './components/AverageValuesPanel'
import CPSummaryPanel from './components/CPSummaryPanel'
import AnalysisTable from './components/AnalysisTable'
import ColumnPicker from './components/ColumnPicker'
import SpeedLossChart from './components/SpeedLossChart'
import ScanPage from './pages/ScanPage'
import SavedReportsPage from './pages/SavedReportsPage'
import MDMPage from './pages/MDMPage'
import SpeedPowerScatter from './components/SpeedPowerScatter'
import ISO19030Page from './pages/ISO19030Page'
import FleetStatusPage from './pages/FleetStatusPage'
import CPDescriptionPage from './pages/CPDescriptionPage'
import EmissionPage from './pages/EmissionPage'
import BunkerReportPage from './pages/BunkerReportPage'
import LoginPage from './pages/LoginPage'
import AdminPage from './pages/AdminPage'
import { AuthProvider, useAuth } from './context/AuthContext'
import './App.css'

const LS_VISIBLE_KEY_PREFIX = 'vp_visible_cols_'
const MIN_TOP = 160
const MAX_TOP = 520

// ── Avatar dropdown ────────────────────────────────────────────────────────────
function AvatarMenu({ user, isAdmin, onAdmin, onLogout }) {
  const [open, setOpen] = useState(false)
  const menuRef = useRef(null)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    function handle(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [open])

  // User initials for avatar
  const initials = (user?.username || 'U')
    .split(/[\s_-]/)
    .map(w => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)

  return (
    <div className="av-wrap" ref={menuRef}>
      <button
        className={`av-btn${open ? ' open' : ''}`}
        onClick={() => setOpen(v => !v)}
        title={user?.username}
        aria-haspopup="true"
        aria-expanded={open}
      >
        <span className="av-circle">{initials}</span>
        <span className="av-name">{user?.username}</span>
        <ChevronDown size={12} className={`av-chevron${open ? ' rotated' : ''}`} />
      </button>

      {open && (
        <div className="av-dropdown">
          {/* User info header */}
          <div className="av-dropdown-header">
            <span className="av-dropdown-username">{user?.username}</span>
            <span className={`av-dropdown-role ${user?.role}`}>{user?.role}</span>
          </div>

          <div className="av-dropdown-divider" />

          {/* Admin Panel — only for admins */}
          {isAdmin && (
            <button
              className="av-dropdown-item"
              onClick={() => { setOpen(false); onAdmin() }}
            >
              <Users size={13} />
              User Management
            </button>
          )}

          {/* Sign out */}
          <button
            className="av-dropdown-item danger"
            onClick={() => { setOpen(false); onLogout() }}
          >
            <LogOut size={13} />
            Sign Out
          </button>
        </div>
      )}
    </div>
  )
}

// ── Page tab bar ──────────────────────────────────────────────────────────────
function PageTabBar({ active, onChange, isAdmin, onLogout, currentUser, onAdmin }) {
  const tabs = [
    { id: 'reports', icon: <FileText  size={14} />, label: 'Vessel Reports' },
    { id: 'logbook', icon: <BookOpen  size={14} />, label: 'Logbook+'       },
    { id: 'scan',    icon: <Zap       size={14} />, label: 'Vessel Scan'    },
    { id: 'mdm',     icon: <Database  size={14} />, label: 'Design Data'    },
    { id: 'iso',     icon: <BarChart2 size={14} />, label: 'ISO 19030'      },
    { id: 'fleet',   icon: <Map       size={14} />, label: 'Fleet Status'   },
    { id: 'cp',      icon: <ScrollText size={14} />, label: 'CP Description' },
    { id: 'emission', icon: <Leaf size={14} />, label: 'Emission' },
    { id: 'bunker',  icon: <Fuel size={14} />, label: 'Bunker Report' },
  ]
  return (
    <div className="page-tabs">
      {tabs.map(t => (
        <div
          key={t.id}
          className={`page-tab${active === t.id ? ' active' : ''}`}
          onClick={() => onChange(t.id)}
        >
          <span className="page-tab-icon">{t.icon}</span>
          {t.label}
        </div>
      ))}

      <div className="page-tab-spacer" />

      <AvatarMenu
        user={currentUser}
        isAdmin={isAdmin}
        onAdmin={onAdmin}
        onLogout={onLogout}
      />
    </div>
  )
}

// ── Logbook page ───────────────────────────────────────────────────────────────
function LogbookPage({ preloadVesselImo, currentUser }) {
  const [rows, setRows]             = useState([])
  const [chartRows, setChartRows]   = useState([])
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState(null)
  const [filtersApplied, setFiltersApplied] = useState(false)
  const [vesselImo, setVesselImo]   = useState('')
  const [vesselName, setVesselName] = useState('')
  const [cpVoyages, setCpVoyages]   = useState(null)
  const [graphType, setGraph]       = useState(() => memoryStore.getItem('vp_graph_type') || 'fuel')
  const [fuelMode, setFuelMode]     = useState(() => memoryStore.getItem('vp_fuel_mode') || 'daily')
  const [topHeight, setTopH]        = useState(() => parseInt(memoryStore.getItem('vp_top_height'), 10) || 290)
  const [dragging, setDrag]         = useState(false)
  const [columnsMeta, setColsMeta]  = useState([])
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerAdminMode, setPickerAdminMode] = useState(false)
  const [source, setSource]         = useState(() => memoryStore.getItem('vp_source') || 'mari_apps')
  const [catFilter, setCatFilter]   = useState(() => memoryStore.getItem('vp_cat_filter') || 'All')
  const [colsVersion, setColsVersion] = useState(0)
  const [pilotVessels, setPilotVessels] = useState([])
  const [complianceByDate, setComplianceByDate] = useState({})

  useEffect(() => { memoryStore.setItem('vp_graph_type', graphType) }, [graphType])
  useEffect(() => { memoryStore.setItem('vp_fuel_mode', fuelMode) }, [fuelMode])
  useEffect(() => { memoryStore.setItem('vp_top_height', topHeight) }, [topHeight])
  useEffect(() => { memoryStore.setItem('vp_source', source) }, [source])
  useEffect(() => { memoryStore.setItem('vp_cat_filter', catFilter) }, [catFilter])

  const effSource = source === 'all' ? 'wni' : source

  const [vesselDefaults, setVesselDefaults] = useState(new Set())
  const [userVisible, setUserVisible] = useState(new Set())

  const dragStartY = useRef(0)
  const dragStartH = useRef(0)
  const filterReqIdRef = useRef(0)

  useEffect(() => {
    let active = true
    Promise.all([
      fetchExpandedColumns(effSource, vesselImo).catch(() => []),
      vesselImo ? fetchVesselColumnDefaults(effSource, vesselImo).catch(() => ({})) : Promise.resolve({}),
      vesselImo ? fetchUserColumnPrefs(effSource, vesselImo).catch(() => ({})) : Promise.resolve({})
    ]).then(([cols, defs, prefs]) => {
      if (!active) return
      setColsMeta(cols.map(c => ({ ...c, performance: c.performance || PERFORMANCE_COLUMNS.has(c.db_column) })))
      
      const vDef = new Set(defs.visible || [])
      setVesselDefaults(vDef)
      
      let uVis = new Set(prefs.visible || [])
      if (uVis.size === 0) {
        const defaultCols = cols.filter(c => c.is_active).map(c => c.db_column)
        if (vDef.size > 0) {
          uVis = new Set(defaultCols.filter(col => vDef.has(col)))
        } else {
          uVis = new Set(defaultCols)
        }
      }

      // ── TUFMAX: always show Tufmax-specific columns when this vessel is selected ──
      const TUFMAX_IMO = '9486295'
      if (vesselImo === TUFMAX_IMO) {
        uVis.add('wni_tufmax_me_ldo_mt')
        uVis.add('wni_tufmax_ae_hfhsd_mt')
      }
      // ────────────────────────────────────────────────────────────────────────────

      setUserVisible(uVis)
    })
    return () => { active = false }
  }, [effSource, vesselImo, colsVersion])

  // Charter-Party compliance pilot (AM KIRTI / GCL FOS only) — per-day status lookup used to
  // annotate the Month/Period data table + fuel chart. Not tied to voyage view at all.
  useEffect(() => {
    fetchCPCompliancePilotVessels().then(setPilotVessels).catch(() => setPilotVessels([]))
  }, [])

  useEffect(() => {
    if (!vesselImo || !pilotVessels.includes(vesselImo)) { setComplianceByDate({}); return }
    let active = true
    const srcParam = source === 'all' ? undefined : source
    fetchCPCompliance(vesselImo, srcParam)
      .then(d => {
        if (!active) return
        // Worst-status wins when a date has multiple reports (e.g. partial-day legs).
        const rank = { 'Non-compliant': 3, 'Compliant': 2, 'Excluded (weather)': 1, 'Not evaluable': 1, 'Unmatched': 1 }
        const byDate = {}
        for (const v of (d.voyages || [])) {
          for (const day of (v.daily || [])) {
            const dateKey = (day.date || '').slice(0, 10)
            if (!dateKey) continue
            const cur = byDate[dateKey]
            if (!cur || (rank[day.status] || 0) > (rank[cur] || 0)) byDate[dateKey] = day.status
          }
        }
        setComplianceByDate(byDate)
      })
      .catch(() => setComplianceByDate({}))
    return () => { active = false }
  }, [vesselImo, source, pilotVessels])

  const handleFilters = useCallback(async (filters) => {
    // Guard against out-of-order responses: TopFilterBar can fire a new filter change
    // (vessel/month/source switch) before the previous one's request has resolved. Without
    // this, a slower older request could resolve AFTER a faster newer one and overwrite its
    // correct chartRows/rows with stale (sometimes empty) data — the chart/table would then
    // silently show the wrong filter's result, intermittently, depending on network timing.
    const reqId = ++filterReqIdRef.current
    const src = filters.source_id || 'wni'
    setLoading(true)
    setError(null)
    setFiltersApplied(true)
    if (filters.vessel_imo) setVesselImo(filters.vessel_imo)
    if (filters.vessel_name) setVesselName(filters.vessel_name)
    setCpVoyages(
      Array.isArray(filters.voyageNos) && filters.voyageNos.length
        ? filters.voyageNos.map(String)
        : null
    )
    try {
      const [chartData, tableData] = await Promise.all([
        queryAnalysis(filters).catch(() => []),
        queryExpandedData(src, filters),
      ])
      if (reqId !== filterReqIdRef.current) return // superseded by a newer filter change
      setChartRows(chartData)
      setRows(tableData)
    } catch (e) {
      if (reqId !== filterReqIdRef.current) return
      setError(e?.response?.data?.detail ?? e.message ?? 'Failed to load data')
      setRows([])
      setChartRows([])
    } finally {
      if (reqId === filterReqIdRef.current) setLoading(false)
    }
  }, [])

  function handleSetUserVisible(newSet) {
    setUserVisible(newSet)
  }

  function handleAdminDefaultsChanged(newDefaultsSet) {
    setVesselDefaults(newDefaultsSet)
  }

  function onDragMouseDown(e) {
    e.preventDefault()
    dragStartY.current = e.clientY
    dragStartH.current = topHeight
    setDrag(true)
    function onMove(ev) {
      setTopH(Math.min(MAX_TOP, Math.max(MIN_TOP, dragStartH.current + (ev.clientY - dragStartY.current))))
    }
    function onUp() {
      setDrag(false)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  const hasChartData = chartRows.length > 0
  const voyageView = !!(cpVoyages && cpVoyages.length > 0)

  // "Emission" is rendered as its own pinned chip (like Performance), not via the
  // alphabetical category list — excluded here so it doesn't also show up twice.
  const categories = useMemo(() => {
    const cats = [...new Set(
      columnsMeta.filter(c => !c.is_identity).map(c => c.category || 'Other')
    )].filter(cat => cat !== 'Emission').sort((a, b) => a.localeCompare(b))
    return cats
  }, [columnsMeta])

  // Note: We no longer override `is_active` to act as the category filter.
  // The category filter just determines which columns are allowed in `effectiveExtras`.
  const effectiveExtras = useMemo(() => {
    const baseVisible = vesselDefaults.size === 0
      ? userVisible
      : new Set([...userVisible].filter(k => vesselDefaults.has(k)))

    if (catFilter === 'All') {
      return baseVisible
    }

    const isPerf = catFilter === 'Performance'
    const isEmission = catFilter === 'Emission'
    // Emission focus = columns whose own category IS "Emission" (the Grade fields)
    // OR columns flagged `emission` (dual-membership fields that keep their normal
    // category too, e.g. Weather/Voyage/Vessel General Data fields also relevant to
    // emissions) — matches the picker's "also show under Emission" behavior.
    const inFocus = c => isPerf ? c.performance
      : isEmission ? (c.category === 'Emission' || c.emission === true)
      : (c.category || 'Other') === catFilter

    const focusKeys = new Set(
      columnsMeta.filter(c => !c.is_identity && inFocus(c)).map(c => c.db_column)
    )

    return new Set([...baseVisible].filter(k => focusKeys.has(k)))
  }, [catFilter, userVisible, vesselDefaults, columnsMeta])

  useEffect(() => { setCatFilter('All') }, [source])

  return (
    <div className="app-wrapper">
      <TopFilterBar
        graphType={graphType}
        onGraphTypeChange={setGraph}
        fuelMode={fuelMode}
        onFuelModeChange={setFuelMode}
        source={source}
        onSourceChange={setSource}
        onFiltersChange={handleFilters}
        defaultVesselImo={preloadVesselImo}
        onColumnsClick={(imo, name) => {
          if (imo) {
            setVesselImo(imo)
            setVesselName(name)
          }
          setPickerOpen(true)
        }}
        isAdminMode={pickerAdminMode}
      />

      {error && <div className="error-bar"><AlertTriangle size={13} style={{ flexShrink: 0 }} /> {error}</div>}

      <div className="middle-section" style={{ height: topHeight }}>
        <div className="chart-panel">
          <div className="section-title">
            {graphType === 'fuel'
              ? `Total Fuel Consumption (mt) · ${fuelMode === 'event' ? 'Event-wise' : fuelMode === 'underway' ? 'Underway' : 'Daily'}`
              : graphType === 'speed' ? 'Speed & Power'
              : 'Power-Normalised Speed Loss %'}
          </div>
          {loading && <div className="chart-empty"><div className="spinner" /> Loading…</div>}
          {!loading && !hasChartData && graphType !== 'speed' && (
            <div className="chart-empty">
              {filtersApplied ? 'No data available for the selected period.' : 'Select a vessel and date range to view data.'}
            </div>
          )}
          {!loading && hasChartData && graphType === 'fuel'       && <FuelBarChart rows={chartRows} mode={fuelMode} voyageView={voyageView} complianceByDate={complianceByDate} />}
          {!loading && graphType === 'speed'      && <SpeedPowerScatter vesselImo={vesselImo} />}
          {!loading && graphType === 'speed_loss' && <SpeedLossChart rows={chartRows} />}
        </div>
        <AverageValuesPanel rows={chartRows} />
      </div>

      <div className={`drag-handle${dragging ? ' dragging' : ''}`} onMouseDown={onDragMouseDown} title="Drag to resize">
        <div className="drag-handle-grip" />
      </div>

      {!voyageView && categories.length > 0 && (
        <div className="cat-filter-bar">
          <button className={`cat-chip${catFilter === 'All' ? ' active' : ''}`} onClick={() => setCatFilter('All')}>All</button>
          <button
            className={`cat-chip cat-perf-chip${catFilter === 'Performance' ? ' active' : ''}`}
            onClick={() => setCatFilter('Performance')}
            title="Show only NoonData / Calc Engine performance columns"
          >Performance</button>
          <button
            className={`cat-chip cat-emission-chip${catFilter === 'Emission' ? ' active' : ''}`}
            onClick={() => setCatFilter('Emission')}
            title="Show only emission-relevant columns (Grade + Voyage/Weather/Fuel fields)"
          >Emission</button>
          {categories.map(cat => (
            <button
              key={cat}
              className={`cat-chip${catFilter === cat ? ' active' : ''}`}
              onClick={() => setCatFilter(cat)}
            >{cat}</button>
          ))}
        </div>
      )}

      <div className="table-section">
        {voyageView
          ? <CPSummaryPanel imo={vesselImo} vesselName={vesselName} source={source} voyages={cpVoyages} loadingCond={filtersApplied?.loadingCond} />
          : loading
            ? <div className="loading-overlay"><div className="spinner" /> Loading reports…</div>
            : <AnalysisTable rows={rows} columnsMeta={columnsMeta} visibleExtras={effectiveExtras} filtersApplied={filtersApplied} complianceByDate={complianceByDate} vesselName={vesselName} hideComplianceErrors={catFilter === 'Emission'} emissionFocus={catFilter === 'Emission'} />
        }
      </div>

      {pickerOpen && (
        <ColumnPicker
          pageSource={effSource}
          pageUserVisible={userVisible}
          pageVesselDefaults={vesselDefaults}
          vesselImo={vesselImo}
          vesselName={vesselName}
          currentUser={currentUser}
          onPageSetVisible={handleSetUserVisible}
          onOrderChanged={() => setColsVersion(v => v + 1)}
          onClose={() => setPickerOpen(false)}
          onAdminDefaultsChanged={handleAdminDefaultsChanged}
          modeIsAdmin={pickerAdminMode}
          onModeChange={setPickerAdminMode}
        />
      )}
    </div>
  )
}

// ── Loading splash ─────────────────────────────────────────────────────────────
function AppLoadingScreen() {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      height: '100vh', background: '#0d1b2a', gap: 16, color: '#64748b',
    }}>
      <div style={{
        width: 36, height: 36, border: '3px solid #1e3a5f',
        borderTopColor: '#38bdf8', borderRadius: '50%',
        animation: 'spin 0.8s linear infinite',
      }} />
      <span style={{ fontSize: 13 }}>Loading Vessel Performance…</span>
    </div>
  )
}

// ── Authenticated App Shell ────────────────────────────────────────────────────
function AuthenticatedApp() {
  const { user, isAdmin, logout } = useAuth()

  const [page, setPage] = useState(() => {
    return localStorage.getItem('vp_current_page') || 'reports'
  })
  const [scanPreload,      setScanPreload]      = useState(null)
  const [logbookVesselImo, setLogbookVesselImo] = useState(null)
  const [showAdmin,        setShowAdmin]        = useState(false)

  function navigateToScan(savedReport, vesselImo) {
    setScanPreload({ savedReport, vesselImo, editMode: false })
    setPage('scan')
    localStorage.setItem('vp_current_page', 'scan')
  }
  function navigateToScanForEdit(savedReport) {
    setScanPreload({ savedReport, vesselImo: savedReport.vesselImo || '', editMode: true })
    setPage('scan')
    localStorage.setItem('vp_current_page', 'scan')
  }
  function navigateToLogbook(imo) {
    setLogbookVesselImo(imo || null)
    setPage('logbook')
    localStorage.setItem('vp_current_page', 'logbook')
  }
  function handleTabChange(id) {
    if (id === 'logbook') setLogbookVesselImo(null)
    setShowAdmin(false)
    setPage(id)
    localStorage.setItem('vp_current_page', id)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg-primary)', overflow: 'hidden' }}>
      <PageTabBar
        active={showAdmin ? '__admin__' : page}
        onChange={handleTabChange}
        isAdmin={isAdmin}
        onLogout={logout}
        currentUser={user}
        onAdmin={() => setShowAdmin(true)}
      />

      {/* Admin full page */}
      {showAdmin && isAdmin && (
        <div className="admin-overlay">
          <div className="admin-overlay-header">
            <button className="admin-overlay-back" onClick={() => setShowAdmin(false)}>
              ← Back to App
            </button>
            <span className="admin-overlay-title">
              <Users size={15} /> User Management
            </span>
            <div style={{ width: 140 }} />{/* spacer to center title */}
          </div>
          <AdminPage />
        </div>
      )}

      {/* Main pages — hidden when admin panel is open */}
      {!showAdmin && (
        <>
          {page === 'logbook' && <LogbookPage preloadVesselImo={logbookVesselImo} currentUser={user} />}
          {page === 'scan' && (
            <ScanPage preload={scanPreload} onPreloadConsumed={() => setScanPreload(null)} />
          )}
          {page === 'reports' && (
            <SavedReportsPage
              onNavigateToScan={navigateToScan}
              onNavigateToScanForEdit={navigateToScanForEdit}
              onNavigateToLogbook={navigateToLogbook}
            />
          )}
          {page === 'mdm'   && <MDMPage />}
          {page === 'iso'   && <ISO19030Page />}
          {page === 'fleet' && <FleetStatusPage />}
          {page === 'cp'    && <CPDescriptionPage />}
          {page === 'emission' && <EmissionPage />}
          {page === 'bunker' && <BunkerReportPage />}
        </>
      )}
    </div>
  )
}

// ── Root App with Auth Gate ────────────────────────────────────────────────────
function AppContent() {
  const { isAuthenticated, loading } = useAuth()
  if (loading)        return <AppLoadingScreen />
  if (!isAuthenticated) return <LoginPage />
  return <AuthenticatedApp />
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}
