import { useState, useEffect, useRef, useCallback } from 'react'
import { Download, Loader2 } from 'lucide-react'
import { fetchCPPerformance } from '../api/vesselApi'
import { generateVoyagePdf } from '../utils/voyagePdfExport'
import './CPSummaryPanel.css'

const fmt = (v, d = 2) =>
  v === null || v === undefined || isNaN(v) ? '—' : (+v).toFixed(d)

// Loss(+)/Saving(-) value, coloured: positive = loss (red), negative = saving (green)
function LS({ v, d = 2 }) {
  if (v === null || v === undefined || isNaN(v)) return <span>—</span>
  const cls = v > 0 ? 'cp-loss' : v < 0 ? 'cp-save' : ''
  return <span className={cls}>{v > 0 ? '+' : ''}{(+v).toFixed(d)}</span>
}

// Total Voyage Analysis dual cell — upper: good weather, lower: entire voyage
function GE({ g, e, d = 2 }) {
  return (
    <div className="cp-ge">
      <span className="cp-ge-good">{fmt(g, d)}</span>
      <span className="cp-ge-ent">{fmt(e, d)}</span>
    </div>
  )
}

// Plain-number version of fmt() for the Excel export — keeps genuine numbers as
// numbers (rounded to the same precision shown on screen) so Excel can sort/sum
// them, rather than exporting the '—' placeholder text as a literal cell value.
function numOrDash(v, d = 2) {
  return (v === null || v === undefined || isNaN(v)) ? '—' : +(+v).toFixed(d)
}

// Columns that are single-valued per voyage (everything except Total Voyage Analysis) —
// these get a real Excel vertical merge (rowSpan=2) across the voyage's two physical
// rows, same as they visually span both lines of the on-screen "Good Wx / Entire" cell.
const _SINGLE_VALUE_COLS = new Set([
  'voyage_no', 'lb', 'spd_instr', 'seg', 'departure_port', 'atd', 'arrival_port', 'ata',
  'ls_time_h', 'ls_fo_mt', 'ls_dogo_mt', 'ls_ratio_pct',
  'w_speed', 'w_fo', 'w_dogo', 'al_speed', 'al_cons',
  'gd_wind', 'gd_sea_state', 'gd_current', 'gd_ratio_pct',
])
// Total Voyage Analysis columns — good weather value goes on the voyage's top physical
// row, entire-voyage value on the bottom row, matching the on-screen stacked cell
// (green Good Wx on top, muted Entire below) instead of splitting into side-by-side
// columns.
const _TVA_COLS = ['tva_time_h', 'tva_dist_nm', 'tva_avg_spd', 'tva_curr_fac', 'tva_fo_mt', 'tva_dogo_mt', 'tva_daily_fo', 'tva_daily_dogo']

// Exports exactly the rows currently shown in the Charter-Party Performance table
// (same voyage/segment selection, same columns), laid out the same way the UI shows
// it: each voyage occupies two physical Excel rows (rowSpan=2), with the single-valued
// columns vertically merged across both and the Total Voyage Analysis columns carrying
// the Good Wx value on the top row / Entire Voyage value on the bottom row.
async function exportCPExcel(rows, vesselName) {
  const ExcelJS = (await import('exceljs')).default
  const { saveAs } = (await import('file-saver')).default

  const workbook = new ExcelJS.Workbook()
  const sheet = workbook.addWorksheet('CP Performance', {
    views: [{ state: 'frozen', ySplit: 2, xSplit: 0 }],
  })

  const colDefs = [
    { key: 'voyage_no',      width: 16 }, { key: 'lb',           width: 6  },
    { key: 'spd_instr',      width: 12 }, { key: 'seg',          width: 6  },
    { key: 'departure_port', width: 26 }, { key: 'atd',          width: 12 },
    { key: 'arrival_port',   width: 26 }, { key: 'ata',          width: 12 },
    { key: 'ls_time_h',      width: 10 }, { key: 'ls_fo_mt',     width: 10 },
    { key: 'ls_dogo_mt',     width: 10 }, { key: 'ls_ratio_pct', width: 10 },
    { key: 'tva_time_h',     width: 10 }, { key: 'tva_dist_nm',  width: 10 },
    { key: 'tva_avg_spd',    width: 10 }, { key: 'tva_curr_fac', width: 10 },
    { key: 'tva_fo_mt',      width: 10 }, { key: 'tva_dogo_mt',  width: 10 },
    { key: 'tva_daily_fo',   width: 10 }, { key: 'tva_daily_dogo', width: 10 },
    { key: 'w_speed',        width: 10 }, { key: 'w_fo',         width: 10 },
    { key: 'w_dogo',         width: 10 },
    { key: 'al_speed',       width: 12 }, { key: 'al_cons',      width: 12 },
    { key: 'gd_wind',        width: 14 }, { key: 'gd_sea_state', width: 14 },
    { key: 'gd_current',     width: 14 }, { key: 'gd_ratio_pct', width: 10 },
  ]
  sheet.columns = colDefs
  const colIndex = {}
  colDefs.forEach((c, i) => { colIndex[c.key] = i + 1 })

  // Row 1 — merged group headers
  const groupStyle = (cellRef, label, bgColor) => {
    const cell = sheet.getCell(cellRef)
    cell.value = label
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: bgColor } }
    cell.font = { bold: true, color: { argb: 'FFFFFFFF' }, size: 10 }
    cell.alignment = { horizontal: 'center', vertical: 'middle' }
  }
  sheet.mergeCells('A1:H1');  groupStyle('A1', 'Voyage Information', 'FF1E293B')
  sheet.mergeCells('I1:L1');  groupStyle('I1', 'Loss (+) / Saving (-)', 'FF7F1D1D')
  sheet.mergeCells('M1:T1');  groupStyle('M1', 'Total Voyage Analysis · Good Wx / Entire', 'FF1E3A8A')
  sheet.mergeCells('U1:W1');  groupStyle('U1', 'CP Warranty', 'FF14532D')
  sheet.mergeCells('X1:Y1');  groupStyle('X1', 'Allowance', 'FF854D0E')
  sheet.mergeCells('Z1:AC1'); groupStyle('Z1', 'Good Weather Definition', 'FF581C87')
  sheet.getRow(1).height = 20

  // Row 2 — sub-headers (also merged vertically across... no, single row 2 only —
  // rowSpan starts at the data rows, not the header)
  const subHeaders = [
    'Voyage', 'L/B', 'Spd Instr', 'Seg', 'Departure', 'ATD', 'Arrival', 'ATA',
    'Time h', 'FO mt', 'DO/GO mt', 'Ratio %',
    'Time h', 'Dist nm', 'Avg Spd', 'Curr Fac', 'FO mt', 'DO/GO mt', 'Daily FO', 'Daily DO/GO',
    'Speed', 'FO/d', 'DO/GO/d', 'Speed', 'Cons',
    'Wind', 'Sea State', 'Current', 'Ratio %',
  ]
  const row2 = sheet.getRow(2)
  subHeaders.forEach((label, idx) => {
    const cell = row2.getCell(idx + 1)
    cell.value = label
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF0F172A' } }
    cell.font = { bold: true, color: { argb: 'FF94A3B8' }, size: 9 }
    cell.alignment = { vertical: 'middle', horizontal: 'center', wrapText: true }
  })
  row2.height = 22

  // Data rows — two physical rows per voyage (rowSpan=2), starting after the 2 header rows
  const GOOD_FONT = { color: { argb: 'FF34D399' }, bold: true, size: 9.5 }  // matches .cp-ge-good
  const ENT_FONT  = { color: { argb: 'FF94A3B8' }, size: 9.5 }              // matches .cp-ge-ent

  rows.forEach((r, idx) => {
    const g = r.good_wx || {}, e = r.entire || {}, l = r.loss || {}
    const w = r.warranty || {}, al = r.allowance || {}, gd = r.good_wx_def || {}
    const topRowNum = 3 + idx * 2
    const botRowNum = topRowNum + 1

    const topVals = {
      voyage_no: r.voyage_no || '', lb: (r.loading_cond || '')[0] || '—',
      spd_instr: r.speed_instruction || '—', seg: r.segment_no,
      departure_port: r.departure_port || '—', atd: r.atd || '—',
      arrival_port: r.arrival_port || '—', ata: r.ata || '—',
      ls_time_h: numOrDash(l.time_h), ls_fo_mt: numOrDash(l.fo_mt),
      ls_dogo_mt: numOrDash(l.dogo_mt), ls_ratio_pct: numOrDash(l.ratio_pct, 1),
      tva_time_h: numOrDash(g.time_h, 1), tva_dist_nm: numOrDash(g.distance_nm, 0),
      tva_avg_spd: numOrDash(g.avg_speed_kn), tva_curr_fac: numOrDash(g.current_factor_kn),
      tva_fo_mt: numOrDash(g.fo_mt), tva_dogo_mt: numOrDash(g.dogo_mt),
      tva_daily_fo: numOrDash(g.daily_fo), tva_daily_dogo: numOrDash(g.daily_dogo),
      w_speed: numOrDash(w.speed_kn), w_fo: numOrDash(w.fo_mtpd), w_dogo: numOrDash(w.dogo_mtpd),
      al_speed: al.speed_kn != null ? `${al.speed_kn} kts` : '—',
      al_cons: al.cons_pct != null ? `${al.cons_pct} %` : '—',
      gd_wind: gd.wind || '—', gd_sea_state: gd.sea_state || '—',
      gd_current: gd.current || '—', gd_ratio_pct: gd.ratio_pct != null ? `${gd.ratio_pct} %` : '—',
    }
    const botVals = {
      tva_time_h: numOrDash(e.time_h, 1), tva_dist_nm: numOrDash(e.distance_nm, 0),
      tva_avg_spd: numOrDash(e.avg_speed_kn), tva_curr_fac: numOrDash(e.current_factor_kn),
      tva_fo_mt: numOrDash(e.fo_mt), tva_dogo_mt: numOrDash(e.dogo_mt),
      tva_daily_fo: numOrDash(e.daily_fo), tva_daily_dogo: numOrDash(e.daily_dogo),
    }

    const topRow = sheet.getRow(topRowNum)
    const botRow = sheet.getRow(botRowNum)
    const zebra = idx % 2 === 1 ? { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEBF0FA' } } : null

    colDefs.forEach(c => {
      const col = colIndex[c.key]
      if (_SINGLE_VALUE_COLS.has(c.key)) {
        topRow.getCell(col).value = topVals[c.key]
        sheet.mergeCells(topRowNum, col, botRowNum, col)
        const cell = sheet.getCell(topRowNum, col)
        cell.alignment = { vertical: 'middle', horizontal: 'center' }
        if (zebra) { topRow.getCell(col).fill = zebra; botRow.getCell(col).fill = zebra }
      } else if (_TVA_COLS.includes(c.key)) {
        const topCell = topRow.getCell(col)
        const botCell = botRow.getCell(col)
        topCell.value = topVals[c.key]
        botCell.value = botVals[c.key]
        topCell.font = GOOD_FONT
        botCell.font = ENT_FONT
        topCell.alignment = { horizontal: 'center' }
        botCell.alignment = { horizontal: 'center' }
        if (zebra) { topCell.fill = zebra; botCell.fill = zebra }
      }
    })
  })

  const buffer = await workbook.xlsx.writeBuffer()
  const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const safeName = (vesselName || 'Vessel').replace(/[^a-z0-9]+/gi, '_')
  saveAs(blob, `${safeName}_CP_Performance_${new Date().toISOString().slice(0, 10)}.xlsx`)
}

export default function CPSummaryPanel({ imo, vesselName, source, voyages, loadingCond }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [pdfLoadingVoyage, setPdfLoadingVoyage] = useState(null)
  const [exporting, setExporting] = useState(false)

  const rows = data?.results || []

  const [selectedIds, setSelectedIds] = useState(new Set())
  const lastSelectedIdx = useRef(null)

  const handleRowClick = useCallback((e, rowKey, idx) => {
    const isCtrl = e.ctrlKey || e.metaKey
    const isShift = e.shiftKey

    if (isShift && lastSelectedIdx.current !== null) {
      const start = Math.min(lastSelectedIdx.current, idx)
      const end = Math.max(lastSelectedIdx.current, idx)
      
      setSelectedIds(prev => {
        const next = isCtrl ? new Set(prev) : new Set()
        for (let i = start; i <= end; i++) {
          const r = rows[i]
          next.add(`${r.voyage_no}-${r.segment_no}-${i}`)
        }
        return next
      })
    } else if (isCtrl) {
      setSelectedIds(prev => {
        const next = new Set(prev)
        if (next.has(rowKey)) next.delete(rowKey)
        else next.add(rowKey)
        return next
      })
      lastSelectedIdx.current = idx
    } else {
      setSelectedIds(prev => {
        if (prev.has(rowKey) && prev.size === 1) {
          return new Set()
        }
        return new Set([rowKey])
      })
      lastSelectedIdx.current = idx
    }
  }, [rows])

  const voyageKey = (voyages || []).join(',')

  useEffect(() => {
    if (!imo || !voyages || voyages.length === 0) return
    let cancelled = false
    setLoading(true); setError(null)
    fetchCPPerformance(imo, voyages, source, loadingCond)
      .then(d => { if (!cancelled) setData(d) })
      .catch(e => { if (!cancelled) setError(e?.response?.data?.detail ?? 'CP load failed') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [imo, source, voyageKey, loadingCond])   // eslint-disable-line react-hooks/exhaustive-deps

  if (!imo || !voyages || voyages.length === 0) return null

  const handleExportExcel = async () => {
    if (exporting) return
    setExporting(true)
    try {
      await exportCPExcel(rows, vesselName)
    } catch (e) {
      console.error('CP Performance Excel export failed', e)
    } finally {
      setExporting(false)
    }
  }

  // Vessel-level Loss/Saving totals
  const tot = rows.reduce((a, r) => ({
    time: a.time + (r.loss?.time_h || 0),
    fo:   a.fo   + (r.loss?.fo_mt  || 0),
    dogo: a.dogo + (r.loss?.dogo_mt|| 0),
  }), { time: 0, fo: 0, dogo: 0 })

  return (
    <div className="cpp-panel">
      <div className="cp-panel-head">
        Charter-Party Performance
        <span className="cp-panel-sub"> · Total Voyage Analysis cells show <span className="cp-ge-good">Good Weather</span> / <span className="cp-ge-ent">Entire Voyage</span></span>
        {rows.length > 0 && (
          <span className="cp-tot">
            Loss (+) / Saving (−) — Time <LS v={tot.time} /> hrs · FO <LS v={tot.fo} /> mt · DO/GO <LS v={tot.dogo} /> mt
          </span>
        )}
        {rows.length > 0 && (
          <button
            type="button"
            className={`cp-export-btn ${exporting ? 'spinning' : ''}`}
            onClick={handleExportExcel}
            disabled={exporting}
            title="Export this voyage table to Excel"
          >
            {exporting ? <Loader2 size={12} className="icon-spin" /> : <Download size={12} />}
            <span>Export Excel</span>
          </button>
        )}
      </div>

      {loading && <div className="cp-panel-msg">Loading…</div>}
      {error && <div className="cp-panel-msg cp-err">{error}</div>}
      {!loading && data && !data.cp_configured && (
        <div className="cp-panel-msg cp-warn">
          No CP warranties for this vessel — set them on ISO 19030 → Configuration to see Loss/Saving &amp; compliance.
        </div>
      )}

      <div className="cpp-scroll-area">
      {!loading && rows.length > 0 && (
        <div className="cp-table-wrap">
          <table className="cp-table">
            <thead>
              <tr className="cp-grp">
                <th colSpan={8}>Voyage Information</th>
                <th colSpan={4}>Loss (+) / Saving (−)</th>
                <th colSpan={8} className="cp-grp-tva">Total Voyage Analysis · Good Wx / Entire</th>
                <th colSpan={3}>CP Warranty</th>
                <th colSpan={2}>Allowance</th>
                <th colSpan={4}>Good Weather Definition</th>
              </tr>
              <tr className="cp-sub">
                <th>Voyage</th><th>L/B</th><th>Spd Instr</th><th>Seg</th>
                <th>Departure</th><th>ATD</th><th>Arrival</th><th>ATA</th>
                <th>Time h</th><th>FO mt</th><th>DO/GO mt</th><th>Ratio %</th>
                <th>Time h</th><th>Dist nm</th><th>Avg Spd</th><th>Curr Fac</th>
                <th>FO mt</th><th>DO/GO mt</th><th>Daily FO</th><th>Daily DO/GO</th>
                <th>Speed</th><th>FO/d</th><th>DO/GO/d</th>
                <th>Speed</th><th>Cons</th>
                <th>Wind</th><th>Sea State</th><th>Current</th><th>Ratio</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const g = r.good_wx || {}, e = r.entire || {}, l = r.loss || {}
                const w = r.warranty || {}, al = r.allowance || {}, gd = r.good_wx_def || {}
                const rowKey = `${r.voyage_no}-${r.segment_no}-${i}`
                return (
                  <tr 
                    key={rowKey}
                    className={selectedIds.has(rowKey) ? 'selected' : ''}
                    onClick={(e) => handleRowClick(e, rowKey, i)}
                  >
                    <td className="cp-voyage">
                      <div className="cp-voyage-dl-wrap">
                        <button
                          type="button"
                          className={`cp-dl-btn ${pdfLoadingVoyage === r.voyage_no ? 'spinning' : ''}`}
                          onClick={async (e) => {
                            e.preventDefault()
                            e.stopPropagation()
                            if (pdfLoadingVoyage === r.voyage_no) return
                            setPdfLoadingVoyage(r.voyage_no)
                            try {
                              await generateVoyagePdf({
                                vesselImo: imo,
                                vesselName: vesselName || '',
                                voyageNo: r.voyage_no,
                                voyageNos: [r.voyage_no],
                                source,
                                loadingCond,
                                onProgress: () => {},
                              })
                            } catch (_) {
                              // silent
                            } finally {
                              setPdfLoadingVoyage(null)
                            }
                          }}
                          title={`Download PDF for Voyage ${r.voyage_no}`}
                        >
                          {pdfLoadingVoyage === r.voyage_no
                            ? <Loader2 size={12} className="icon-spin" />
                            : <Download size={12} />}
                        </button>
                        <span>{r.voyage_no}</span>
                      </div>
                    </td>
                    <td>{(r.loading_cond || '')[0] || '—'}</td>
                    <td>{r.speed_instruction || '—'}</td>
                    <td>{r.segment_no}</td>
                    <td className="cp-port">{r.departure_port}</td>
                    <td className="cp-dt">{r.atd}</td>
                    <td className="cp-port">{r.arrival_port}</td>
                    <td className="cp-dt">{r.ata}</td>
                    {/* Loss / Saving */}
                    <td><LS v={l.time_h} /></td>
                    <td><LS v={l.fo_mt} /></td>
                    <td><LS v={l.dogo_mt} /></td>
                    <td>{fmt(l.ratio_pct, 1)}</td>
                    {/* Total Voyage Analysis (good / entire) */}
                    <td><GE g={g.time_h} e={e.time_h} d={1} /></td>
                    <td><GE g={g.distance_nm} e={e.distance_nm} d={0} /></td>
                    <td><GE g={g.avg_speed_kn} e={e.avg_speed_kn} /></td>
                    <td><GE g={g.current_factor_kn} e={e.current_factor_kn} /></td>
                    <td><GE g={g.fo_mt} e={e.fo_mt} /></td>
                    <td><GE g={g.dogo_mt} e={e.dogo_mt} /></td>
                    <td><GE g={g.daily_fo} e={e.daily_fo} /></td>
                    <td><GE g={g.daily_dogo} e={e.daily_dogo} /></td>
                    {/* CP Warranty */}
                    <td>{fmt(w.speed_kn, 2)}</td>
                    <td>{fmt(w.fo_mtpd, 2)}</td>
                    <td>{fmt(w.dogo_mtpd, 2)}</td>
                    {/* Allowance */}
                    <td>{al.speed_kn != null ? `${al.speed_kn} kts` : '—'}</td>
                    <td>{al.cons_pct != null ? `${al.cons_pct} %` : '—'}</td>
                    {/* Good Weather Definition */}
                    <td>{gd.wind}</td>
                    <td>{gd.sea_state}</td>
                    <td>{gd.current}</td>
                    <td>{gd.ratio_pct} %</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {!loading && data && rows.length === 0 && (
        <div className="cp-panel-msg">No analysis rows for the selected voyage(s).</div>
      )}
      </div>
    </div>
  )
}
