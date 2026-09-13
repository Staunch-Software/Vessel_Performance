import { useState, useMemo, memo, useRef, useCallback } from 'react'
import { useReactTable, getCoreRowModel, flexRender } from '@tanstack/react-table'
import { Download, Loader2 } from 'lucide-react'
import { getSavedReports } from '../utils/savedReports'
import './AnalysisTable.css'

// Exact "Emission Log" workbook sheet structure — group sections + column
// order within each, both derived from this single source of truth (not from
// the backend's sort_order, and NOT from emission_sort_order/drag-to-reorder
// either — see the `emissionFocus` branch in buildColumns below) because the
// client confirmed this exact 41-column structure/order against their own
// workbook twice this session; several of these columns are ALSO
// `performance=True` for their normal Performance-tab home (e.g. Speed Over
// Ground, ME/AE/Boiler fuel totals) — sort_order/emission_sort_order is one
// shared field per column, so it can't simultaneously encode both the
// Performance tab's order AND this sheet's fixed order/grouping. Columns not
// listed anywhere here keep their incoming (backend-sorted) relative order,
// appended after everything listed. Groups with zero matching columns present
// (OPS — OPS kWh not built yet) are simply skipped when rendering, not shown
// empty. Country/EU Port?/BDN Ref/Voyage No. are MariApps-only (see
// expander.py's _EMISSION_LOG_NAV_META_MARIAPPS_ONLY for why WNI can't
// support them) — they just won't resolve to a real column for WNI and get
// skipped per-row, same as any other column a source doesn't have.
const EMISSION_LOG_GROUPS = [
  { label: 'Event Info', cols: ['vessel_imo', 'log_type', 'event_type', 'log_date', 'date', 'log_number', 'voyage_no', 'emissionx_voyage_no'] },
  { label: 'Navigation', cols: [
    'VoyageMeta_departure_port_last_leg_operational_LF', // From Port
    'emissionx_from_country',                             // Country (From)
    'emissionx_from_eu_port',                             // EU Port? (From)
    'VoyageMeta_to_port_operational_LF',                 // To Port
    'emissionx_to_country',                                // Country (To)
    'emissionx_to_eu_port',                                // EU Port? (To)
    'loading_condition',                                 // Condition
    'VoyageMeta_latitude_operational_LF',
    'VoyageMeta_longitude_operational_LF',
    'emissionx_op_status',                                // Op. Status
  ] },
  { label: 'Vessel', cols: [
    'Vessel_DOG_dCnt_operational_LF',           // Dist. (nm)
    'VoyageMeta_log_durationh_operational_LF',  // Hours
    'Vessel_SOG_avg_operational_LF',            // Speed (kn)
    'Vessel_Tf_avg_operational_LF',             // Draft F (m)
    'Vessel_Ta_avg_operational_LF',             // Draft A (m)
  ] },
  { label: 'Cargo', cols: ['Vessel_Cargo_onboard_operational_LF'] },
  { label: 'ME Fuel Consumption', cols: [
    'emissionx_me_hfo_mt', 'emissionx_me_lfo_mt', 'emissionx_me_mdo_mt', 'emissionx_me_biofuel_mt',
    'ME_FO_mFOCME_dCnt_operational_LF', // ME Total
  ] },
  { label: 'AE Fuel Consumption', cols: [
    'emissionx_ae_hfo_mt', 'emissionx_ae_lfo_mt', 'emissionx_ae_mdo_mt', 'emissionx_ae_biofuel_mt',
    'AE_FO_mFOCAE_dCnt_operational_LF', // AE Total
  ] },
  { label: 'Boiler Fuel Consumption', cols: [
    'emissionx_bl_hfo_mt', 'emissionx_bl_lfo_mt', 'emissionx_bl_mdo_mt', 'emissionx_bl_biofuel_mt',
    'AuxBoiler_mFOCBL_dCnt_operational_LF', // Boiler Total
  ] },
  { label: 'Fuel Totals', cols: [
    'emissionx_ig_other_mt', 'emissionx_grand_total_mt',
    'emissionx_total_hfo_mt', 'emissionx_total_lfo_mt', 'emissionx_total_mdo_mt', 'emissionx_total_biofuel_mt',
  ] },
  // OPS (OPS kWh): not built yet, so no `cols` entry — intentionally omitted
  // rather than listed-but-empty.
  { label: 'Reference', cols: ['emissionx_bdn_ref'] }, // Remarks not built yet
]
const EMISSION_LOG_COLUMN_ORDER = EMISSION_LOG_GROUPS.flatMap(g => g.cols)
const EMISSION_LOG_COLUMN_RANK = new Map(EMISSION_LOG_COLUMN_ORDER.map((c, i) => [c, i]))

// Wraps flat leaf column defs into TanStack Table's native grouped-column
// shape ({ header, columns: [...] }) per EMISSION_LOG_GROUPS, which renders
// as a proper multi-row header with correct colSpan automatically — no
// manual colSpan math needed. Columns not covered by any group (shouldn't
// normally happen — everything Emission-tagged is listed above) are appended
// ungrouped at the end rather than silently dropped.
function groupEmissionLogColumns(dataCols) {
  const byId = new Map(dataCols.map(c => [c.id, c]))
  const used = new Set()
  const groups = []
  for (const g of EMISSION_LOG_GROUPS) {
    const children = g.cols.map(id => byId.get(id)).filter(Boolean)
    if (children.length === 0) continue
    children.forEach(c => used.add(c.id))
    groups.push({ id: `__group_${g.label}__`, header: g.label, columns: children })
  }
  const leftover = dataCols.filter(c => !used.has(c.id))
  return [...groups, ...leftover]
}

// ── Scan condition evaluator ──────────────────────────────────────────────────
function evalCond(row, { field, operator, value, value2 }) {
  const v = parseFloat(row[field])
  if (isNaN(v)) return false
  switch (operator) {
    case 'gt':      return v > value
    case 'gte':     return v >= value
    case 'lt':      return v < value
    case 'lte':     return v <= value
    case 'eq':      return v === value
    case 'neq':     return v !== value
    case 'between': return v >= value && v <= (value2 ?? value)
    default:        return false
  }
}

function rowScanResult(row, reports) {
  let matchCount = 0
  const triggered = new Set()
  for (const r of reports) {
    // Expression-based reports (new format) can't be evaluated client-side — skip
    if (!Array.isArray(r.conditions)) continue
    const conds = r.conditions.map(c => ({ field: c.field, hit: evalCond(row, c) }))
    const matches = r.logic === 'AND' ? conds.every(c => c.hit) : conds.some(c => c.hit)
    if (matches) {
      matchCount++
      conds.forEach(c => { if (c.hit) triggered.add(c.field) })
    }
  }
  return { matchCount, triggered }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtCell(val) {
  if (val == null || val === '' || val === 'None' || val === 'nan' || val === 'NaN' || String(val).toLowerCase() === 'null') return null
  // Strings containing letters, dashes, slashes, colons are dates/text — show as-is
  if (typeof val === 'string' && /[a-zA-Z\-\/:]/.test(val)) return val
  const n = parseFloat(val)
  if (isNaN(n)) return String(val)
  // Pure integers (no decimal in original) → no .00 suffix
  const s = String(val)
  if (Number.isInteger(n) && !s.includes('.')) return String(n)
  return n.toFixed(2)
}

function CellValue({ val }) {
  const s = fmtCell(val)
  if (s == null) return <span className="cell-null">—</span>
  // Right-align only genuine numeric-looking values
  const isNum = typeof val === 'number' || (typeof val === 'string' && /^-?\d+\.?\d*$/.test(val.trim()))
  return <span className={isNum ? 'cell-num' : ''}>{s}</span>
}

// ── Excel export helpers ─────────────────────────────────────────────────────
// Mirrors the on-screen cell formatting (fmtCell + the lat/lon special-casing
// in buildColumns' cell renderer above) so the exported sheet matches exactly
// what's visible in the table — same rows, same columns, same values.
function exportCellValue(dbColumn, row) {
  if (dbColumn === 'VoyageMeta_latitude_operational_LF') {
    const deg = parseFloat(row[dbColumn])
    if (!isNaN(deg)) {
      const min = row.VoyageMeta_latitude_lat_minutes_operational_LF || 0
      let dir = row.VoyageMeta_latitude_lat_direction_operational_LF || ''
      if (!dir || !isNaN(dir)) dir = deg >= 0 ? 'N' : 'S'
      return `${Math.abs(deg)}°${Number(min).toFixed(1)}'${dir}`
    }
  }
  if (dbColumn === 'VoyageMeta_longitude_operational_LF') {
    const deg = parseFloat(row[dbColumn])
    if (!isNaN(deg)) {
      const min = row.VoyageMeta_longitude_minutes_operational_LF || row.VoyageMeta_longitude_lon_minutes_operational_LF || 0
      let dir = row.VoyageMeta_longitude_direction_operational_LF || row.VoyageMeta_longitude_lon_direction_operational_LF || ''
      if (!dir || !isNaN(dir)) dir = deg >= 0 ? 'E' : 'W'
      return `${Math.abs(deg)}°${Number(min).toFixed(1)}'${dir}`
    }
  }
  const val = row[dbColumn]
  const s = fmtCell(val)
  if (s == null) return ''
  // Keep genuine numbers as numbers (not strings) so Excel treats them as numeric
  const isNum = typeof val === 'number' || (typeof val === 'string' && /^-?\d+\.?\d*$/.test(val.trim()))
  return isNum ? Number(s) : s
}

// Exports exactly the rows/columns currently shown on screen (same filters,
// same visible-columns selection, same sort order) to a formatted .xlsx —
// same client-side pattern already used for the Fleet Status export.
async function exportAnalysisExcel(rows, dataCols, vesselName) {
  const ExcelJS = (await import('exceljs')).default
  const { saveAs } = (await import('file-saver')).default

  const workbook = new ExcelJS.Workbook()
  const sheet = workbook.addWorksheet('Noon Records', {
    views: [{ state: 'frozen', ySplit: 1 }],
  })

  sheet.columns = dataCols.map(c => ({ header: c.header, key: c.id, width: 18 }))

  const headerRow = sheet.getRow(1)
  headerRow.height = 22
  headerRow.eachCell(cell => {
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF1F3864' } }
    cell.font = { bold: true, color: { argb: 'FFFFFFFF' }, size: 10 }
    cell.alignment = { horizontal: 'center', vertical: 'middle' }
  })

  rows.forEach((row, idx) => {
    const rowData = {}
    dataCols.forEach(c => { rowData[c.id] = exportCellValue(c.id, row) })
    const excelRow = sheet.addRow(rowData)
    if (idx % 2 === 1) {
      excelRow.eachCell(cell => {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEBF0FA' } }
      })
    }
  })

  const buffer = await workbook.xlsx.writeBuffer()
  const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const safeName = (vesselName || 'Vessel').replace(/[^a-z0-9]+/gi, '_')
  saveAs(blob, `${safeName}_Noon_Records_${new Date().toISOString().slice(0, 10)}.xlsx`)
}

// ── Column builder ────────────────────────────────────────────────────────────
// Columns that are identity but should never appear in the table
const HIDDEN_COLS = new Set(['raw_log_id', 'raw_report_id', 'source_id'])

// Identity sticky columns — vessel_imo always first, then log metadata.
// loading_condition is_identity too, but wasn't listed here — it fell through
// into the generic non-sticky/category-grouped bucket under a stray one-column
// "Identity" category (its own `category` field is literally "Identity") that
// the Column Manager can't even reorder (buildOrder() excludes is_identity
// columns from the draggable list entirely), so it always rendered wherever
// its raw backend sort_order happened to land it — in practice, last — with no
// way to move it. Pinning it here like the other identity columns fixes that.
const STICKY_ORDER = ['vessel_imo', 'log_type', 'event_type', 'log_date', 'date', 'log_number', 'voyage_no', 'loading_condition']

const COMPLIANCE_CLS = {
  'Non-compliant': 'compliance-red',
  'Compliant': 'compliance-green',
  'Excluded (weather)': 'compliance-amber',
  'Not evaluable': 'compliance-amber',
  'Unmatched': 'compliance-amber',
}

function rowDateKey(row) {
  return String(row.log_date || row.date || '').slice(0, 10)
}

// Same passage-boundary/port-side exclusion set the backend CP compliance pilot uses
// (backend/cp/cp_compliance_v2.py's _NON_SEA_PASSAGE_EVENT_TYPES) — BOSP/COSP/EOSP/
// Arrival Report/Departure Report/Noon at port are never actually judged for speed/fuel
// compliance, only "Noon at sea" steaming rows are. complianceByDate is keyed by calendar
// DATE though (worst-status-wins across a day's reports), so without this check every
// other report sharing that date — a BOSP, an EOSP, a Departure Report — would visually
// inherit the "Noon at sea" row's verdict on that same day, looking as if it had been
// individually judged when it never was.
const _NON_SEA_PASSAGE_LOG_TYPES = new Set(['BOSP', 'COSP', 'EOSP', 'ARRIVAL REPORT', 'DEPARTURE REPORT', 'NOON AT PORT'])
function isSeaPassageReport(row) {
  // MariApps rows carry it in `log_type`, WNI rows in `event_type` — both display under
  // the same "Log Type" column header (see expander.py's identity-column definitions).
  const logType = String(row.log_type || row.event_type || '').trim().toUpperCase()
  return !_NON_SEA_PASSAGE_LOG_TYPES.has(logType)
}

function buildColumns(columnsMeta, visibleExtras, scanResults, complianceByDate, hideComplianceErrors, emissionFocus) {
  // Which columns to show: identity (except hidden ones) + user-toggled (pink)
  const visible = columnsMeta.filter(m => {
    if (HIDDEN_COLS.has(m.db_column)) return false
    return m.is_identity || visibleExtras?.has(m.db_column)
  })

  // Sticky identity columns (fixed 3 slots after Errors)
  const stickySet   = new Set(STICKY_ORDER)
  const stickySlots = STICKY_ORDER.map(k => visible.find(m => m.db_column === k)).filter(Boolean)

  // Non-sticky columns
  const nonSticky = visible.filter(m => !stickySet.has(m.db_column))

  // Emission-focused view (the "Emission" category chip is active): every
  // visible column here is a member of the Emission bucket, so there's no
  // category clustering to do — just lay them out in EMISSION_LOG_COLUMN_RANK
  // order (the client's own workbook sequence — confirmed twice this session,
  // see the module docstring above), not a free-drag emission_sort_order and
  // not their primary-category order. Anything not in that list (shouldn't
  // normally happen) keeps its incoming relative order, appended at the end.
  if (emissionFocus) {
    const sortedNonSticky = [...nonSticky].sort((a, b) => {
      const ra = EMISSION_LOG_COLUMN_RANK.has(a.db_column) ? EMISSION_LOG_COLUMN_RANK.get(a.db_column) : Infinity
      const rb = EMISSION_LOG_COLUMN_RANK.has(b.db_column) ? EMISSION_LOG_COLUMN_RANK.get(b.db_column) : Infinity
      return ra - rb
    })
    return groupEmissionLogColumns(
      buildDataColumns([...stickySlots, ...sortedNonSticky], scanResults, complianceByDate, hideComplianceErrors)
    )
  }

  // Group by category so columns stay clustered with the rest of their
  // category instead of scattering across the full ~500+ column list.
  // `nonSticky` already arrives sorted by the backend's
  // coalesce(user_sort_order, sort_order), so within each category group the
  // relative order still reflects any manual drag; a column is placed once,
  // under its primary category (the `performance` flag wins over `category`,
  // matching the picker).
  //
  // Category ORDER itself (which category block comes before which) follows
  // the same coalesced order — i.e. it respects a category-level drag done in
  // the Column Manager — with one exception: until a source has ever had a
  // manual reorder at all (no column carries a user_sort_order), we pin
  // Performance first / Emission second as the sensible out-of-the-box
  // default. Once ANY drag has happened, `persist()` in the picker stamps
  // user_sort_order on every column for that source in one go, so this flag
  // flips for the whole source at once and the forced default gets out of
  // the way permanently — otherwise a category-level drag (e.g. moving "AE
  // Cylinder Data" above Performance) would save correctly to the backend
  // but keep getting silently reverted to Performance-first on every re-render.
  const catOf = m => (m.performance ? 'Performance' : (m.category || 'Other'))
  const hasCustomOrder = columnsMeta.some(m => m.user_sort_order != null)

  const catOrder = []
  for (const m of nonSticky) {
    const cat = catOf(m)
    if (!catOrder.includes(cat)) catOrder.push(cat)
  }

  const finalCatOrder = hasCustomOrder
    ? catOrder
    : (() => {
        const withPerf = catOrder.includes('Performance') ? catOrder : ['Performance', ...catOrder]
        const rest = withPerf.filter(c => c !== 'Performance' && c !== 'Emission')
        return [
          'Performance',
          ...(withPerf.includes('Emission') ? ['Emission'] : []),
          ...rest,
        ]
      })()

  const sortedNonSticky = []
  for (const cat of finalCatOrder) {
    sortedNonSticky.push(...nonSticky.filter(m => catOf(m) === cat))
  }

  const sorted = [...stickySlots, ...sortedNonSticky]

  return buildDataColumns(sorted, scanResults, complianceByDate, hideComplianceErrors)
}

// Builds the actual TanStack column defs (Compliance/Errors + one per data
// column) from an already-ordered list of column metadata. Shared by both
// the normal (category-grouped) and Emission-focused paths above — only how
// `sorted` gets its order differs between them.
function buildDataColumns(sorted, scanResults, complianceByDate, hideComplianceErrors) {
  // Compliance status column (Phase 3a pilot — AM KIRTI/GCL FOS only; blank elsewhere).
  // Always first, ahead of the error count column.
  const complianceCol = {
    id: '__compliance__',
    accessorKey: '__compliance__',
    header: 'Compliance',
    size: 110,
    cell: ({ row }) => {
      const status = isSeaPassageReport(row.original) ? complianceByDate?.[rowDateKey(row.original)] : null
      if (!status) return <span className="cell-null">—</span>
      return <span className={`compliance-pill ${COMPLIANCE_CLS[status] || ''}`}>{status}</span>
    },
  }

  // Error count column (always first, computed)
  const errCol = {
    id: '__errors__',
    accessorKey: '__errors__',
    header: 'Errors',
    size: 62,
    cell: ({ row }) => {
      const n = scanResults?.[row.index]?.matchCount ?? 0
      return n === 0
        ? <span className="cell-null">—</span>
        : <span className="error-count-badge">{n}</span>
    },
  }

  const dataCols = sorted.map(m => {
    const headerText = (m.display_name && String(m.display_name).trim() !== '')
      ? String(m.display_name)
      : (m.db_column ? String(m.db_column) : 'NO_COL');

    return {
      id:          m.db_column,
      accessorKey: m.db_column,
      header:      headerText,
      size:        m.is_identity ? 110 : 140,
      cell:        ({ row, getValue }) => {
        let val = getValue()

        if (m.db_column === 'VoyageMeta_latitude_operational_LF' && val != null) {
          const deg = parseFloat(val)
          if (!isNaN(deg)) {
            const min = row.original.VoyageMeta_latitude_lat_minutes_operational_LF || 0
            let dir = row.original.VoyageMeta_latitude_lat_direction_operational_LF || ''
            // Derive direction from sign when missing or when MariApps stores a raw number instead
            if (!dir || !isNaN(dir)) {
                dir = deg >= 0 ? 'N' : 'S'
            }
            return <span className="cell-num">{`${Math.abs(deg)}°${Number(min).toFixed(1)}'${dir}`}</span>
          }
        }

        if (m.db_column === 'VoyageMeta_longitude_operational_LF' && val != null) {
          const deg = parseFloat(val)
          if (!isNaN(deg)) {
            const min = row.original.VoyageMeta_longitude_minutes_operational_LF || row.original.VoyageMeta_longitude_lon_minutes_operational_LF || 0
            let dir = row.original.VoyageMeta_longitude_direction_operational_LF || row.original.VoyageMeta_longitude_lon_direction_operational_LF || ''
            // Derive direction from sign when missing or when MariApps stores a raw number instead
            if (!dir || !isNaN(dir)) {
                dir = deg >= 0 ? 'E' : 'W'
            }
            return <span className="cell-num">{`${Math.abs(deg)}°${Number(min).toFixed(1)}'${dir}`}</span>
          }
        }

        return <CellValue val={val} />
      },
    }
  })

  // Compliance/Errors are diagnostic to the noon-report data itself, not to
  // emissions — hidden while the Emission focus filter is active so the table
  // reads as a clean emissions view, same as how Performance-focused columns
  // aren't cluttered by unrelated fields.
  return hideComplianceErrors ? dataCols : [complianceCol, errCol, ...dataCols]
}


// ── Memoized Row ───────────────────────────────────────────────────────────────
// `columns` array reference is passed so that React.memo re-renders rows when
// the column layout changes (e.g. swapping, renaming, adding/removing columns).
// Without this, TanStack Table's cached row references might fool memo into skipping
// re-render and the body would show stale cells while the header already reflects new columns.
const TableRow = memo(({ row, idx, isSelected, sr, onClick, columns, complianceStatus }) => {
  const rowCls = [
    isSelected ? 'selected' : '',
    complianceStatus === 'Non-compliant' ? 'row-noncompliant' : '',
  ].filter(Boolean).join(' ')
  return (
    <tr
      className={rowCls || undefined}
      onClick={(e) => onClick(e, row, idx)}
    >
      {row.getVisibleCells().map(cell => (
        <td
          key={cell.id}
          className={sr?.triggered.has(cell.column.id) ? 'cell-triggered' : undefined}
        >
          {flexRender(cell.column.columnDef.cell, cell.getContext())}
        </td>
      ))}
    </tr>
  )
})

// ── Component ─────────────────────────────────────────────────────────────────
export default function AnalysisTable({ rows, columnsMeta, visibleExtras, filtersApplied, complianceByDate, vesselName, hideComplianceErrors, emissionFocus }) {
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [exporting, setExporting] = useState(false)
  const lastSelectedIdx = useRef(null)

  const sortedRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      // 1. Primary sort: local calendar date descending (latest first)
      const dateA = (a.log_date || a.date || '').substring(0, 10)
      const dateB = (b.log_date || b.date || '').substring(0, 10)
      if (dateA !== dateB) return dateB.localeCompare(dateA)

      // 2. Secondary sort: actual UTC datetime descending.
      //    `Date` on AnalysisData rows contains the full ISO datetime (e.g. "2026-03-21T03:12:00").
      //    This gives the real recorded chronological order regardless of event type.
      const tsA = a.Date ? new Date(a.Date).getTime() : NaN
      const tsB = b.Date ? new Date(b.Date).getTime() : NaN
      const bothHaveTs = !isNaN(tsA) && !isNaN(tsB)
      if (bothHaveTs && tsA !== tsB) return tsB - tsA

      // 3. If UTC datetime is identical or missing, fall back to Time_UTC string comparison descending
      const timeA = String(a.Time_UTC || a.time_utc || '')
      const timeB = String(b.Time_UTC || b.time_utc || '')
      if (timeA && timeB && timeA !== timeB) return timeB.localeCompare(timeA)

      // 4. Last resort: log_number / voyage_no descending
      const numA = String(a.log_number || a.voyage_no || a.Voyage_No || '')
      const numB = String(b.log_number || b.voyage_no || b.Voyage_No || '')
      return numB.localeCompare(numA)
    })
  }, [rows])


  const scanResults = useMemo(() => {
    const reports = getSavedReports()
    if (!reports.length) return null
    return sortedRows.map(row => rowScanResult(row, reports))
  }, [sortedRows])

  const columns = useMemo(
    () => buildColumns(columnsMeta || [], visibleExtras, scanResults, complianceByDate, hideComplianceErrors, emissionFocus),
    [columnsMeta, visibleExtras, scanResults, complianceByDate, hideComplianceErrors, emissionFocus]
  )

  const table = useReactTable({ data: sortedRows, columns, getCoreRowModel: getCoreRowModel() })

  const handleExportExcel = useCallback(async () => {
    if (exporting) return
    setExporting(true)
    try {
      // Same rows/columns the table is rendering — excludes the UI-only Errors and
      // Compliance columns, which are computed from lookup maps (scanResults /
      // complianceByDate) rather than plain row properties, so a raw row[id] read
      // would just come back blank for them.
      const dataCols = columns.filter(c => c.id !== '__errors__' && c.id !== '__compliance__')
      await exportAnalysisExcel(sortedRows, dataCols, vesselName)
    } catch (e) {
      console.error('Excel export failed', e)
    } finally {
      setExporting(false)
    }
  }, [exporting, columns, sortedRows, vesselName])

  const handleRowClick = useCallback((e, row, idx) => {
    const isCtrl = e.ctrlKey || e.metaKey
    const isShift = e.shiftKey
    const rowId = row.id

    if (isShift && lastSelectedIdx.current !== null) {
      const allRows = table.getRowModel().rows
      const start = Math.min(lastSelectedIdx.current, idx)
      const end = Math.max(lastSelectedIdx.current, idx)
      
      setSelectedIds(prev => {
        const next = isCtrl ? new Set(prev) : new Set()
        for (let i = start; i <= end; i++) {
          next.add(allRows[i].id)
        }
        return next
      })
    } else if (isCtrl) {
      setSelectedIds(prev => {
        const next = new Set(prev)
        if (next.has(rowId)) next.delete(rowId)
        else next.add(rowId)
        return next
      })
      lastSelectedIdx.current = idx
    } else {
      setSelectedIds(prev => {
        if (prev.has(rowId) && prev.size === 1) {
          return new Set()
        }
        return new Set([rowId])
      })
      lastSelectedIdx.current = idx
    }

    if (isShift) {
      window.getSelection()?.removeAllRanges()
    }
  }, [table])

  if (!rows.length) {
    return (
      <div className="table-empty">
        {filtersApplied
          ? 'No data available for the selected period.'
          : 'Select a vessel and date range to view reports.'}
      </div>
    )
  }

  return (
    <div className="table-wrap">
      <div className="table-toolbar">
        <span className="table-row-count">{sortedRows.length} report{sortedRows.length === 1 ? '' : 's'}</span>
        <button
          type="button"
          className={`table-export-btn ${exporting ? 'spinning' : ''}`}
          onClick={handleExportExcel}
          disabled={exporting}
          title="Export the current view to Excel"
        >
          {exporting ? <Loader2 size={13} className="icon-spin" /> : <Download size={13} />}
          <span>Export Excel</span>
        </button>
      </div>
    <div className="table-container">
      <table className="analysis-table">
        <thead>
          {table.getHeaderGroups().map(hg => (
            <tr key={hg.id}>
              {hg.headers.map(h => (
                <th key={h.id} style={{ minWidth: h.column.columnDef.size ?? 140 }}>
                  {h.isPlaceholder ? null : flexRender(h.column.columnDef.header, h.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row, idx) => {
            const sr = scanResults?.[row.index]
            const complianceStatus = isSeaPassageReport(row.original) ? complianceByDate?.[rowDateKey(row.original)] : null
            return (
              <TableRow
                key={row.id}
                row={row}
                idx={idx}
                isSelected={selectedIds.has(row.id)}
                sr={sr}
                onClick={handleRowClick}
                columns={columns}
                complianceStatus={complianceStatus}
              />
            )
          })}
        </tbody>
      </table>
    </div>
    </div>
  )
}
