import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { memoryStore } from './utils/memoryStore'

import { Zap, AlertTriangle, FileText, Database, BarChart2, ChevronDown, Users, LogOut, Shield, BookOpen, Map, ScrollText, Leaf, Fuel, Columns, Droplet } from 'lucide-react'
import {
  queryAnalysis, queryExpandedData, fetchExpandedColumns, fetchCPCompliancePilotVessels, fetchCPCompliance,
  fetchCategoryOrder, fetchCalculationCategories, fetchCalcCategoryColumns,
} from './api/vesselApi'
import TopFilterBar from './components/TopFilterBar'
import FuelBarChart from './components/FuelBarChart'
import AverageValuesPanel from './components/AverageValuesPanel'
import CPSummaryPanel from './components/CPSummaryPanel'
import AnalysisTable from './components/AnalysisTable'
import SpeedLossChart from './components/SpeedLossChart'
import ScanPage from './pages/ScanPage'
import SavedReportsPage from './pages/SavedReportsPage'
import MDMPage from './pages/MDMPage'
import SpeedPowerScatter from './components/SpeedPowerScatter'
import ISO19030Page from './pages/ISO19030Page'
import FleetStatusPage from './pages/FleetStatusPage'
import CPDescriptionPage from './pages/CPDescriptionPage'
import EmissionPage from './pages/EmissionPage'
import ImoDcsPage from './pages/ImoDcsPage'
import EmissionComingSoonPage from './pages/EmissionComingSoonPage'
import EuMrvPage from './pages/EuMrvPage'
import EuEtsPage from './pages/EuEtsPage'
import FuelEuPage from './pages/FuelEuPage'
import BiofuelCalcPage from './pages/BiofuelCalcPage'
import BunkerReportPage from './pages/BunkerReportPage'
import LoginPage from './pages/LoginPage'
import AdminPage from './pages/AdminPage'
import ColumnConfigPage from './pages/ColumnConfigPage'
import { AuthProvider, useAuth } from './context/AuthContext'
import './App.css'

const LS_VISIBLE_KEY_PREFIX = 'vp_visible_cols_'
const MIN_TOP = 160
const MAX_TOP = 520

// ── Avatar dropdown ────────────────────────────────────────────────────────────
function AvatarMenu({ user, isAdmin, onAdmin, onColumnConfig, onLogout }) {
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

          {/* Configure Columns — admin-only, defines the calc categories
              (Performance/Emission/custom) and the "All" category order
              everyone else's Logbook+ view reads from. */}
          {isAdmin && (
            <button
              className="av-dropdown-item"
              onClick={() => { setOpen(false); onColumnConfig() }}
            >
              <Columns size={13} />
              Configure Columns
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
// Two-level nav: top-level groups, some of which (Vessel Performance, Emission)
// fan out into a click-to-open dropdown of the pages that actually live under
// them. This is purely a navigation regroup — `page` ids and the routing in
// VesselPerfApp below are completely unchanged, only how you get to each id
// changed. A group with no `children` navigates directly on click, same as a
// plain tab always did.
const NAV_GROUPS = [
  { id: 'reports', icon: <FileText size={14} />, label: 'Vessel Reports' },
  { id: 'fleet',   icon: <Map      size={14} />, label: 'Fleet Status'   },
  {
    id: 'vessel_performance', icon: <BarChart2 size={14} />, label: 'Vessel Performance',
    children: [
      { id: 'logbook', icon: <BookOpen   size={14} />, label: 'Logbook+'        },
      { id: 'scan',    icon: <Zap        size={14} />, label: 'Vessel Scan'     },
      { id: 'mdm',     icon: <Database   size={14} />, label: 'Design Data'     },
      { id: 'iso',     icon: <BarChart2  size={14} />, label: 'ISO 19030'       },
      { id: 'cp',      icon: <ScrollText size={14} />, label: 'CP Description'  },
    ],
  },
  {
    id: 'emission_group', icon: <Leaf size={14} />, label: 'Emission',
    children: [
      { id: 'emission',      icon: <Leaf      size={14} />, label: 'Emission'        },
      { id: 'imo_dcs',       icon: <BarChart2 size={14} />, label: 'IMO DCS'         },
      { id: 'eu_mrv',        icon: <ScrollText size={14} />, label: 'EU MRV'          },
      { id: 'eu_ets',        icon: <Database  size={14} />, label: 'EU ETS'          },
      { id: 'fueleu',        icon: <Zap       size={14} />, label: 'FuelEU Maritime' },
      { id: 'biofuel_calc',  icon: <Droplet   size={14} />, label: 'Biofuel Calc'    },
      { id: 'bunker',        icon: <Fuel      size={14} />, label: 'Bunker Report'   },
    ],
  },
]

function PageTabBar({ active, onChange, isAdmin, onLogout, currentUser, onAdmin, onColumnConfig }) {
  const [openGroup, setOpenGroup] = useState(null)
  const navRef = useRef(null)

  // Close the open dropdown on outside click — same pattern as AvatarMenu.
  useEffect(() => {
    if (!openGroup) return
    function handle(e) {
      if (navRef.current && !navRef.current.contains(e.target)) setOpenGroup(null)
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [openGroup])

  function isGroupActive(group) {
    return group.children ? group.children.some(c => c.id === active) : group.id === active
  }

  function handleGroupClick(group) {
    if (!group.children) {
      onChange(group.id)
      setOpenGroup(null)
      return
    }
    setOpenGroup(prev => (prev === group.id ? null : group.id))
  }

  function handleChildClick(childId) {
    onChange(childId)
    setOpenGroup(null)
  }

  return (
    <div className="page-tabs" ref={navRef}>
      {NAV_GROUPS.map(group => (
        <div key={group.id} className="page-tab-group">
          <div
            className={`page-tab${isGroupActive(group) ? ' active' : ''}`}
            onClick={() => handleGroupClick(group)}
          >
            <span className="page-tab-icon">{group.icon}</span>
            {group.label}
            {group.children && (
              <ChevronDown
                size={12}
                className={`page-tab-chevron${openGroup === group.id ? ' rotated' : ''}`}
              />
            )}
          </div>

          {group.children && openGroup === group.id && (
            <div className="page-tab-dropdown">
              {group.children.map(child => (
                <div
                  key={child.id}
                  className={`page-tab-dropdown-item${active === child.id ? ' active' : ''}`}
                  onClick={() => handleChildClick(child.id)}
                >
                  <span className="page-tab-icon">{child.icon}</span>
                  {child.label}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}

      <div className="page-tab-spacer" />

      <AvatarMenu
        user={currentUser}
        isAdmin={isAdmin}
        onAdmin={onAdmin}
        onColumnConfig={onColumnConfig}
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
  const [source, setSource]         = useState(() => memoryStore.getItem('vp_source') || 'mari_apps')
  const [catFilter, setCatFilter]   = useState(() => memoryStore.getItem('vp_cat_filter') || 'All')
  const [pilotVessels, setPilotVessels] = useState([])
  const [complianceByDate, setComplianceByDate] = useState({})

  useEffect(() => { memoryStore.setItem('vp_graph_type', graphType) }, [graphType])
  useEffect(() => { memoryStore.setItem('vp_fuel_mode', fuelMode) }, [fuelMode])
  useEffect(() => { memoryStore.setItem('vp_top_height', topHeight) }, [topHeight])
  useEffect(() => { memoryStore.setItem('vp_source', source) }, [source])
  useEffect(() => { memoryStore.setItem('vp_cat_filter', catFilter) }, [catFilter])

  const effSource = source === 'all' ? 'wni' : source

  // Column visibility/order now comes entirely from the admin-only Configure
  // Columns page (see ColumnConfigPage.jsx) rather than the old per-user/
  // per-vessel column picker (removed) — `calcCategories` are the named
  // calculation categories (Performance/Emission/custom) an admin built
  // there, `categoryOrder` is the "All" mode category ordering, and
  // `calcFieldOrder` is the exact field order for whichever calc category
  // is currently selected via catFilter.
  const [calcCategories, setCalcCategories] = useState([])
  const [categoryOrder, setCategoryOrder]   = useState([])
  const [calcFieldOrder, setCalcFieldOrder] = useState([])

  const dragStartY = useRef(0)
  const dragStartH = useRef(0)
  const filterReqIdRef = useRef(0)

  useEffect(() => {
    let active = true
    Promise.all([
      fetchExpandedColumns(effSource).catch(() => []),
      fetchCalculationCategories(effSource).catch(() => []),
      fetchCategoryOrder(effSource).catch(() => []),
    ]).then(([cols, calcCats, catOrder]) => {
      if (!active) return
      setColsMeta(cols)
      setCalcCategories(calcCats)
      const activeCats = new Set(cols.filter(c => c.is_active && !c.is_identity).map(c => c.category || 'Other'))
      const filtered = catOrder.filter(c => activeCats.has(c))
      const missing = [...activeCats].filter(c => !filtered.includes(c)).sort()
      setCategoryOrder([...filtered, ...missing])
    })
    return () => { active = false }
  }, [effSource])

  // When catFilter matches a calc category (by name), load its exact field
  // list + order — this is what makes a reorder made on the Configure
  // Columns page actually show up here.
  useEffect(() => {
    const cat = calcCategories.find(c => c.name === catFilter)
    if (!cat) { setCalcFieldOrder([]); return }
    let active = true
    fetchCalcCategoryColumns(cat.id).catch(() => []).then(cols => { if (active) setCalcFieldOrder(cols) })
    return () => { active = false }
  }, [catFilter, calcCategories])

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

  // Plain source categories (Vessel General Data, Weather Data, etc.) — excludes
  // whatever's a calc category name (Performance/Emission/custom), since those are
  // rendered as their own pinned pills, not via this alphabetical list. Also
  // requires at least one is_active column — otherwise a category whose every
  // column was pruned as permanently-empty still showed up as a clickable chip
  // that yielded zero columns when picked.
  const categories = useMemo(() => {
    const calcNames = new Set(calcCategories.map(c => c.name))
    const cats = [...new Set(
      columnsMeta.filter(c => !c.is_identity && c.is_active).map(c => c.category || 'Other')
    )].filter(cat => !calcNames.has(cat)).sort((a, b) => a.localeCompare(b))
    return cats
  }, [columnsMeta, calcCategories])

  // Column visibility/order is entirely admin-configured now (Configure Columns
  // page) — no personal per-user toggle layer anymore.
  //   'All'          → every active column, ordered by category (per categoryOrder).
  //   a calc category → exactly that category's field list, in its saved order.
  //   a plain category (e.g. "Weather Data") → that category's active columns.
  const effectiveExtras = useMemo(() => {
    if (catFilter === 'All') {
      return new Set(columnsMeta.filter(c => c.is_active && !c.is_identity).map(c => c.db_column))
    }
    const isCalcCategory = calcCategories.some(c => c.name === catFilter)
    if (isCalcCategory) {
      return new Set(calcFieldOrder)
    }
    return new Set(
      columnsMeta.filter(c => !c.is_identity && c.is_active && (c.category || 'Other') === catFilter).map(c => c.db_column)
    )
  }, [catFilter, columnsMeta, calcCategories, calcFieldOrder])

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

      {!voyageView && (categories.length > 0 || calcCategories.length > 0) && (
        <div className="cat-filter-bar">
          <button className={`cat-chip${catFilter === 'All' ? ' active' : ''}`} onClick={() => setCatFilter('All')}>All</button>
          {calcCategories.map(cat => (
            <button
              key={cat.id}
              className={`cat-chip${cat.name === 'Performance' ? ' cat-perf-chip' : cat.name === 'Emission' ? ' cat-emission-chip' : ''}${catFilter === cat.name ? ' active' : ''}`}
              onClick={() => setCatFilter(cat.name)}
            >{cat.name}</button>
          ))}
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
            : <AnalysisTable
                rows={rows}
                columnsMeta={columnsMeta}
                visibleExtras={effectiveExtras}
                filtersApplied={filtersApplied}
                complianceByDate={complianceByDate}
                vesselName={vesselName}
                hideComplianceErrors={catFilter === 'Emission'}
                emissionExactOrder={catFilter === 'Emission'}
                categoryOrder={catFilter === 'All' ? categoryOrder : null}
                fieldOrder={catFilter !== 'All' && catFilter !== 'Emission' && calcCategories.some(c => c.name === catFilter) ? calcFieldOrder : null}
              />
        }
      </div>
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
  const [showColumnConfig, setShowColumnConfig] = useState(false)

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
    setShowColumnConfig(false)
    setPage(id)
    localStorage.setItem('vp_current_page', id)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg-primary)', overflow: 'hidden' }}>
      <PageTabBar
        active={showAdmin ? '__admin__' : showColumnConfig ? '__column_config__' : page}
        onChange={handleTabChange}
        isAdmin={isAdmin}
        onLogout={logout}
        currentUser={user}
        onAdmin={() => { setShowColumnConfig(false); setShowAdmin(true) }}
        onColumnConfig={() => { setShowAdmin(false); setShowColumnConfig(true) }}
      />

      {/* Configure Columns full page — admin-only */}
      {showColumnConfig && isAdmin && (
        <div className="admin-overlay">
          <div className="admin-overlay-header">
            <button className="admin-overlay-back" onClick={() => setShowColumnConfig(false)}>
              ← Back to App
            </button>
            <span className="admin-overlay-title">
              <Columns size={15} /> Configure Columns
            </span>
            <div style={{ width: 140 }} />
          </div>
          <ColumnConfigPage />
        </div>
      )}

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

      {/* Main pages — hidden when admin panel or column config is open */}
      {!showAdmin && !showColumnConfig && (
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
          {page === 'imo_dcs' && <ImoDcsPage />}
          {page === 'eu_mrv' && <EuMrvPage />}
          {page === 'eu_ets' && <EuEtsPage />}
          {page === 'fueleu' && <FuelEuPage />}
          {page === 'biofuel_calc' && <BiofuelCalcPage />}
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
