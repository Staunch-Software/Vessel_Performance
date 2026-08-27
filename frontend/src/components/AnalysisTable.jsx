import { useState, useMemo, memo, useRef, useCallback } from 'react'
import { useReactTable, getCoreRowModel, flexRender } from '@tanstack/react-table'
import { Download, Loader2 } from 'lucide-react'
import { getSavedReports } from '../utils/savedReports'
import './AnalysisTable.css'

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

// Identity sticky columns — vessel_imo always first, then log metadata
const STICKY_ORDER = ['vessel_imo', 'log_type', 'event_type', 'log_date', 'date', 'log_number', 'voyage_no']

// Priority columns shown first in the table (new Service Variable column names).
const VGD_PRIORITY = [
  // Identity / voyage
  'status', 'leg_number', 'loading_condition',
  'VoyageMeta_to_port_operational_LF',
  'VoyageMeta_departure_port_last_leg_operational_LF',
  'VoyageMeta_arrival_port_current_leg_operational_LF',
  // Draft / displacement
  'Vessel_Ta_avg_operational_LF',
  'Vessel_Tf_avg_operational_LF',
  'Vessel_DISP_avg_operational_LF',
  // Speed / distance / duration
  'Vessel_SOG_avg_operational_LF',
  'Vessel_STW_avg_operational_LF',
  'Vessel_DOG_dCnt_operational_LF',
  'VoyageMeta_log_durationh_operational_LF',
  // Fuel
  'ME_FO_mFOME_dCnt_operational_LF',
  'AE_FO_mFOAE_dCnt_operational_LF',
  'AuxBoiler_mFOBL_dCnt_operational_LF',
  // Engine
  'ME_NME_avg_operational_LF',
  'ME_PeffestME_avg_operational_LF',
  'ME_PSME_avg_operational_LF',
  // Weather
  'Weather_Hwv_avg_operational_LF',
  'Weather_Uwit_avg_operational_LF',
  'Weather_psiwit_avg_operational_LF',
  'Weather_Ucut_avg_operational_LF',
]

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

function buildColumns(columnsMeta, visibleExtras, scanResults, complianceByDate, hideComplianceErrors) {
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

  // If the user has arranged columns in the picker (any user_sort_order set),
  // honor that order verbatim — columnsMeta already arrives in user order from
  // the backend. Otherwise fall back to the curated default layout.
  const hasUserOrder = columnsMeta.some(m => m.user_sort_order != null)

  let sorted
  if (hasUserOrder) {
    sorted = [...stickySlots, ...nonSticky]
  } else {
    const vgdPrioritySet = new Set(VGD_PRIORITY)
    const vgdPriority = VGD_PRIORITY.map(k => nonSticky.find(m => m.db_column === k)).filter(Boolean)
    const vgdRest     = nonSticky.filter(m =>
      (m.category === 'Vessel General Data') && !vgdPrioritySet.has(m.db_column)
    )
    // Everything else: non-VGD columns that are NOT already placed in vgdPriority.
    // (Priority columns can belong to other categories — e.g. loading_condition is
    //  'Identity', destination port is 'Voyage Metadata' — so excluding only the
    //  VGD-category ones previously let them render twice.)
    const others = nonSticky.filter(m =>
      m.category !== 'Vessel General Data' && !vgdPrioritySet.has(m.db_column)
    )

    // Sort "others" by category alphabetically, then sort_order within category
    others.sort((a, b) => {
      const catA = a.category || 'ZZZ'
      const catB = b.category || 'ZZZ'
      if (catA !== catB) return catA.localeCompare(catB)
      return (a.sort_order ?? 0) - (b.sort_order ?? 0)
    })

    sorted = [...stickySlots, ...vgdPriority, ...vgdRest, ...others]
  }

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
export default function AnalysisTable({ rows, columnsMeta, visibleExtras, filtersApplied, complianceByDate, vesselName, hideComplianceErrors }) {
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
    () => buildColumns(columnsMeta || [], visibleExtras, scanResults, complianceByDate, hideComplianceErrors),
    [columnsMeta, visibleExtras, scanResults, complianceByDate, hideComplianceErrors]
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
