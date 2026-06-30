import { useState, useMemo } from 'react'
import { useReactTable, getCoreRowModel, flexRender } from '@tanstack/react-table'
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
  if (val == null || val === '' || val === 'None' || val === 'nan' || val === 'NaN') return null
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

function buildColumns(columnsMeta, visibleExtras, scanResults) {
  // Which columns to show: identity (except hidden ones) + active (yellow) + user-toggled (pink)
  const visible = columnsMeta.filter(m => {
    if (HIDDEN_COLS.has(m.db_column)) return false
    return m.is_identity || m.is_active || visibleExtras?.has(m.db_column)
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

  const dataCols = sorted.map(m => ({
    id:          m.db_column,
    accessorKey: m.db_column,
    header:      m.display_name,
    size:        m.is_identity ? 110 : 140,
    cell:        ({ getValue }) => <CellValue val={getValue()} />,
  }))

  return [errCol, ...dataCols]
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function AnalysisTable({ rows, columnsMeta, visibleExtras, filtersApplied }) {
  const [selectedId, setSelectedId] = useState(null)

  const scanResults = useMemo(() => {
    const reports = getSavedReports()
    if (!reports.length) return null
    return rows.map(row => rowScanResult(row, reports))
  }, [rows])

  const columns = useMemo(
    () => buildColumns(columnsMeta || [], visibleExtras, scanResults),
    [columnsMeta, visibleExtras, scanResults]
  )

  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() })

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
    <div className="table-container">
      <table className="analysis-table">
        <thead>
          {table.getHeaderGroups().map(hg => (
            <tr key={hg.id}>
              {hg.headers.map(h => (
                <th key={h.id} style={{ minWidth: h.column.getSize() }}>
                  {flexRender(h.column.columnDef.header, h.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map(row => {
            const sr = scanResults?.[row.index]
            return (
              <tr
                key={row.id}
                className={selectedId === row.original.id ? 'selected' : ''}
                onClick={() => setSelectedId(row.original.id)}
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
          })}
        </tbody>
      </table>
    </div>
  )
}
