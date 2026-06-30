import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { BookOpen, Zap, AlertTriangle, FileText, Database, BarChart2 } from 'lucide-react'
import { queryAnalysis, queryExpandedData, fetchExpandedColumns } from './api/vesselApi'
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
import './App.css'

const LS_VISIBLE_KEY_PREFIX = 'vp_visible_cols_'

const MIN_TOP = 160
const MAX_TOP = 520

// ── Page tab bar ──────────────────────────────────────────────────────────────
function PageTabBar({ active, onChange }) {
  const tabs = [
    { id: 'reports',  icon: <FileText  size={14} />, label: 'Vessel Reports'  },
    { id: 'logbook',  icon: <BookOpen  size={14} />, label: 'Logbook+'        },
    { id: 'scan',     icon: <Zap       size={14} />, label: 'Vessel Scan'     },
    { id: 'mdm',      icon: <Database   size={14} />, label: 'Design Data'     },
    { id: 'iso',      icon: <BarChart2  size={14} />, label: 'ISO 19030'       },
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
    </div>
  )
}

// ── Logbook page ──────────────────────────────────────────────────────────────
function LogbookPage({ preloadVesselImo }) {
  const [rows, setRows]             = useState([])       // expanded data for table
  const [chartRows, setChartRows]   = useState([])       // analysis_data for charts
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState(null)
  const [filtersApplied, setFiltersApplied] = useState(false)   // true once first fetch fires
  const [vesselImo, setVesselImo]   = useState('')       // current vessel IMO for scatter chart
  const [cpVoyages, setCpVoyages]   = useState(null)     // selected voyages — non-null ONLY in Voyage view
  const [graphType, setGraph]       = useState('fuel')
  const [fuelMode, setFuelMode]     = useState('daily')   // daily | event | underway
  const [topHeight, setTopH]        = useState(240)
  const [dragging, setDrag]         = useState(false)
  const [columnsMeta, setColsMeta]  = useState([])
  const [pickerOpen, setPickerOpen] = useState(false)
  const [source, setSource]         = useState('mari_apps')   // raw selection: all | wni | mari_apps
  const [catFilter, setCatFilter]   = useState('All')
  const [colsVersion, setColsVersion] = useState(0)           // bump to force column-metadata reload

  // 'all' has no expanded table of its own — it shows WNI columns/data
  const effSource = source === 'all' ? 'wni' : source

  // User-toggled pink columns — persisted in localStorage per source
  const [userVisible, setUserVisible] = useState(() => {
    try {
      const saved = localStorage.getItem(LS_VISIBLE_KEY_PREFIX + 'mari_apps')
      return new Set(saved ? JSON.parse(saved) : [])
    } catch { return new Set() }
  })

  const dragStartY = useRef(0)
  const dragStartH = useRef(0)

  // Load column metadata when source changes
  // Augment with client-side performance flag (don't rely on DB value alone)
  useEffect(() => {
    fetchExpandedColumns(effSource)
      .then(cols => setColsMeta(
        cols.map(c => ({ ...c, performance: c.performance || PERFORMANCE_COLUMNS.has(c.db_column) }))
      ))
      .catch(console.error)
    // Restore user-visible prefs for this source
    try {
      const saved = localStorage.getItem(LS_VISIBLE_KEY_PREFIX + effSource)
      setUserVisible(new Set(saved ? JSON.parse(saved) : []))
    } catch { setUserVisible(new Set()) }
  }, [effSource, colsVersion])

  const handleFilters = useCallback(async (filters) => {
    // source is controlled by the page (radio / picker); derive concrete src for the query
    const src = filters.source_id || 'wni'
    setLoading(true)
    setError(null)
    setFiltersApplied(true)
    if (filters.vessel_imo) setVesselImo(filters.vessel_imo)
    // CP panel is voyage-scoped: only populate when the user is in Voyage view.
    setCpVoyages(
      Array.isArray(filters.voyageNos) && filters.voyageNos.length
        ? filters.voyageNos.map(String)
        : null
    )
    try {
      // Fetch chart data (analysis_data) and expanded table data in parallel
      const [chartData, tableData] = await Promise.all([
        queryAnalysis(filters).catch(() => []),
        queryExpandedData(src, filters),
      ])
      setChartRows(chartData)
      setRows(tableData)
    } catch (e) {
      setError(e?.response?.data?.detail ?? e.message ?? 'Failed to load data')
      setRows([])
      setChartRows([])
    } finally {
      setLoading(false)
    }
  }, [])

  function handleToggleColumn(dbCol) {
    setUserVisible(prev => {
      const next = new Set(prev)
      if (next.has(dbCol)) next.delete(dbCol)
      else next.add(dbCol)
      localStorage.setItem(LS_VISIBLE_KEY_PREFIX + effSource, JSON.stringify([...next]))
      return next
    })
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

  // Voyage view → CP performance replaces the data table in the lower area.
  const voyageView = !!(cpVoyages && cpVoyages.length > 0)

  // Derive distinct categories from non-identity columns
  const categories = useMemo(() => {
    const cats = [...new Set(
      columnsMeta.filter(c => !c.is_identity).map(c => c.category || 'Other')
    )].sort((a, b) => a.localeCompare(b))
    return cats
  }, [columnsMeta])

  // Filter / sort columnsMeta by selected category.
  // When a category is selected, show ONLY identity columns + that category's columns.
  const filteredMeta = useMemo(() => {
    if (catFilter === 'All') return columnsMeta

    const isPerf = catFilter === 'Performance'

    const inFocus = c =>
      isPerf
        ? c.performance
        : (c.category || 'Other') === catFilter

    return columnsMeta.map(c => {
      if (c.is_identity) return c
      if (inFocus(c)) return { ...c, is_active: true }
      return { ...c, is_active: false }
    })
  }, [columnsMeta, catFilter])

  // When a category filter is active, strip visibleExtras down to only
  // columns that are actually in focus — prevents localStorage-toggled
  // columns from other categories bleeding through.
  const effectiveExtras = useMemo(() => {
    if (catFilter === 'All') return userVisible
    const focusKeys = new Set(
      filteredMeta.filter(c => !c.is_identity && c.is_active).map(c => c.db_column)
    )
    return new Set([...userVisible].filter(k => focusKeys.has(k)))
  }, [catFilter, userVisible, filteredMeta])

  // Reset category filter when source changes
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
        onColumnsClick={() => setPickerOpen(true)}
      />

      {error && <div className="error-bar"><AlertTriangle size={13} style={{ flexShrink: 0 }} /> {error}</div>}

      <div className="middle-section" style={{ height: topHeight }}>
        <div className="chart-panel">
          <div className="section-title">
            {graphType === 'fuel'
              ? `Total Fuel Consumption (mt) · ${fuelMode === 'event' ? 'Event-wise' : fuelMode === 'underway' ? 'Underway' : 'Daily'}`
             : graphType === 'speed'    ? 'Speed & Power'
             : 'Power-Normalised Speed Loss %'}
          </div>
          {loading && <div className="chart-empty"><div className="spinner" /> Loading…</div>}
          {!loading && !hasChartData && graphType !== 'speed' && (
            <div className="chart-empty">
              {filtersApplied
                ? 'No data available for the selected period.'
                : 'Select a vessel and date range to view data.'}
            </div>
          )}
          {!loading && hasChartData && graphType === 'fuel'       && <FuelBarChart rows={chartRows} mode={fuelMode} />}
          {!loading && graphType === 'speed'      && <SpeedPowerScatter vesselImo={vesselImo} />}
          {!loading && graphType === 'speed_loss' && <SpeedLossChart rows={chartRows} />}
        </div>
        <AverageValuesPanel rows={chartRows} />
      </div>

      <div className={`drag-handle${dragging ? ' dragging' : ''}`} onMouseDown={onDragMouseDown} title="Drag to resize">
        <div className="drag-handle-grip" />
      </div>

      {/* Category filter bar — only in Month/Period (table) view */}
      {!voyageView && categories.length > 0 && (
        <div className="cat-filter-bar">
          <button
            className={`cat-chip${catFilter === 'All' ? ' active' : ''}`}
            onClick={() => setCatFilter('All')}
          >All</button>
          <button
            className={`cat-chip cat-perf-chip${catFilter === 'Performance' ? ' active' : ''}`}
            onClick={() => setCatFilter('Performance')}
            title="Show only NoonData / Calc Engine performance columns"
          >⚡ Performance</button>
          {categories.map(cat => (
            <button
              key={cat}
              className={`cat-chip${catFilter === cat ? ' active' : ''}`}
              onClick={() => setCatFilter(cat)}
            >{cat}</button>
          ))}
        </div>
      )}

      {/* Lower area. In Voyage view the CP performance table fully REPLACES the
          data table, inheriting the same full-width / full-height box. */}
      <div className="table-section">
        {voyageView
          ? <CPSummaryPanel imo={vesselImo} source={source} voyages={cpVoyages} />
          : loading
            ? <div className="loading-overlay"><div className="spinner" /> Loading reports…</div>
            : <AnalysisTable rows={rows} columnsMeta={filteredMeta} visibleExtras={effectiveExtras} filtersApplied={filtersApplied} />
        }
      </div>

      {pickerOpen && (
        <ColumnPicker
          pageSource={effSource}
          pageUserVisible={userVisible}
          onPageToggle={handleToggleColumn}
          onOrderChanged={() => setColsVersion(v => v + 1)}
          onClose={() => setPickerOpen(false)}
        />
      )}
    </div>
  )
}

// ── Root App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [page,             setPage]             = useState('reports')
  const [scanPreload,      setScanPreload]      = useState(null)
  const [logbookVesselImo, setLogbookVesselImo] = useState(null)

  // Called when a count cell is clicked → load + auto-run
  function navigateToScan(savedReport, vesselImo) {
    setScanPreload({ savedReport, vesselImo, editMode: false })
    setPage('scan')
  }

  // Called from "Edit in Scan" → load conditions but DON'T auto-run
  function navigateToScanForEdit(savedReport) {
    setScanPreload({ savedReport, vesselImo: savedReport.vesselImo || '', editMode: true })
    setPage('scan')
  }

  // Called from Vessel Reports Details button → pre-select vessel in Logbook
  function navigateToLogbook(imo) {
    setLogbookVesselImo(imo || null)
    setPage('logbook')
  }

  // Manual tab-bar click handler — clears preload so AM Kirti default is used
  function handleTabChange(id) {
    if (id === 'logbook') setLogbookVesselImo(null)
    setPage(id)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg-primary)', overflow: 'hidden' }}>
      <PageTabBar active={page} onChange={handleTabChange} />
      {page === 'logbook'  && <LogbookPage preloadVesselImo={logbookVesselImo} />}
      {page === 'scan'     && (
        <ScanPage
          preload={scanPreload}
          onPreloadConsumed={() => setScanPreload(null)}
        />
      )}
      {page === 'reports'  && (
        <SavedReportsPage
          onNavigateToScan={navigateToScan}
          onNavigateToScanForEdit={navigateToScanForEdit}
          onNavigateToLogbook={navigateToLogbook}
        />
      )}
      {page === 'mdm' && <MDMPage />}
      {page === 'iso' && <ISO19030Page />}
    </div>
  )
}
