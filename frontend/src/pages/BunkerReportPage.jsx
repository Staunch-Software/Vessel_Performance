import { useState, useEffect } from 'react'
import { memoryStore } from '../utils/memoryStore'
import { Loader2, AlertTriangle, Fuel, Download, FileX, Eye, X } from 'lucide-react'
import { fetchBunkerReportVessels, fetchBunkerReport } from '../api/vesselApi'
import './BunkerReportPage.css'

const fmt = (v, d = 2) =>
  v === null || v === undefined || isNaN(v) ? '—' : (+v).toFixed(d)

const EXPORT_COLUMNS = [
  ['transaction_type', 'Transaction Type'], ['voyage_leg', 'Voyage Leg'], ['port', 'Port'],
  ['fuel_type', 'Fuel Type'], ['imo_fuel_grade', 'Grade'], ['bdn_reference_no', 'BDN Reference'],
  ['quantity_mt', 'Quantity (MT)'], ['sulphur_content', 'Sulphur (%)'], ['density_15c', 'Density (kg/m3)'],
  ['kinematic_viscosity', 'Viscosity (cSt)'], ['flash_point_c', 'Flash Pt (C)'], ['supplier_company', 'Supplier'],
  ['begin_of_bunkering', 'Begin of Bunkering'], ['end_of_bunkering', 'End of Bunkering'], ['time_zone', 'Time Zone'],
  ['marpol_sample_no', 'MARPOL Sample No.'], ['bunker_analysis_status', 'Bunker Analysis'],
  ['lab_report_date', 'Lab Report Date'], ['lab_density_15c', 'Lab Density'],
  ['lab_sulphur_content', 'Lab Sulphur'], ['lab_kinematic_viscosity', 'Lab Viscosity'],
]

// Same client-side ExcelJS pattern used on the other Emission pages — a plain
// passthrough of EXPORT_COLUMNS, so headers match the on-screen table (minus
// the preview-icon column, which has no export equivalent).
async function exportBunkerReportExcel(rows, vesselName) {
  const ExcelJS = (await import('exceljs')).default
  const { saveAs } = (await import('file-saver')).default

  const workbook = new ExcelJS.Workbook()
  const sheet = workbook.addWorksheet('Bunker Report', { views: [{ state: 'frozen', ySplit: 1 }] })
  sheet.columns = EXPORT_COLUMNS.map(([k, l]) => ({ header: l, key: k, width: 16 }))

  const headerRow = sheet.getRow(1)
  headerRow.height = 22
  headerRow.eachCell(cell => {
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF1F3864' } }
    cell.font = { bold: true, color: { argb: 'FFFFFFFF' }, size: 10 }
    cell.alignment = { horizontal: 'center', vertical: 'middle' }
  })

  rows.forEach((r, idx) => {
    const rowData = {}
    EXPORT_COLUMNS.forEach(([k]) => { rowData[k] = r[k] ?? '' })
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
  saveAs(blob, `${safeName}_Bunker_Report_${new Date().toISOString().slice(0, 10)}.xlsx`)
}

const STATUS_CLS = {
  'Awaiting': 'br-status-amber',
  'Completed': 'br-status-green',
  'Rejected': 'br-status-red',
}

function StatusPill({ status }) {
  if (!status) return <span className="br-null">—</span>
  return <span className={`br-status-pill ${STATUS_CLS[status] || ''}`}>{status}</span>
}

// Mirrors MariApps' own "Attachment Details" popup: a preview pane for the PDF
// plus a Download action, in one modal — rather than only offering a bare link.
// A transaction can carry multiple files (BDN + Note of Protest + LOP, etc.) —
// when there's more than one, a file-picker strip lets you switch which one is
// previewed; each file has its own Download action either way.
function AttachmentPreviewModal({ row, onClose }) {
  const files = row.attachments && row.attachments.length > 0
    ? row.attachments
    : [{ file_name: row.attachment_file_name, file_size: row.attachment_file_size, download_url: row.download_url }]
  const [activeIdx, setActiveIdx] = useState(0)
  const active = files[activeIdx] || files[0]

  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="br-modal-backdrop" onClick={onClose}>
      <div className="br-modal" onClick={e => e.stopPropagation()}>
        <div className="br-modal-header">
          <span className="br-modal-title">
            {active?.file_name || 'Attachment'}
            {files.length > 1 && <span className="br-modal-count"> ({activeIdx + 1} of {files.length})</span>}
          </span>
          <div className="br-modal-actions">
            <a
              className="br-modal-dl-btn"
              href={active?.download_url}
              target="_blank"
              rel="noopener noreferrer"
              title="Download"
            >
              <Download size={14} /> Download
            </a>
            <button className="br-modal-close" onClick={onClose} title="Close (Esc)">
              <X size={16} />
            </button>
          </div>
        </div>
        {files.length > 1 && (
          <div className="br-modal-filelist">
            {files.map((f, i) => (
              <button
                key={i}
                type="button"
                className={`br-modal-filechip ${i === activeIdx ? 'active' : ''}`}
                onClick={() => setActiveIdx(i)}
                title={f.file_name}
              >
                {f.file_name || `File ${i + 1}`}
              </button>
            ))}
          </div>
        )}
        <div className="br-modal-body">
          <iframe
            title={active?.file_name || 'Attachment preview'}
            src={active?.download_url}
            className="br-modal-frame"
          />
        </div>
      </div>
    </div>
  )
}

export default function BunkerReportPage() {
  const [vessels, setVessels] = useState([])
  const [selectedImo, setImo] = useState('')
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [previewRow, setPreviewRow] = useState(null)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    fetchBunkerReportVessels()
      .then(list => {
        setVessels(list)
        if (list.length > 0) {
          const saved = memoryStore.getItem('vp_last_vessel_bunker')
          setImo(saved && list.find(v => v.imo_number === saved) ? saved : list[0].imo_number)
        }
      })
      .catch(console.error)
  }, [])

  useEffect(() => {
    if (!selectedImo) return
    setLoading(true)
    setError(null)
    fetchBunkerReport(selectedImo)
      .then(setRows)
      .catch(e => { setError(e?.response?.data?.detail ?? 'Failed to load Bunker Report data.'); setRows([]) })
      .finally(() => setLoading(false))
  }, [selectedImo])

  async function handleExport() {
    if (exporting || rows.length === 0) return
    setExporting(true)
    try {
      const vesselName = vessels.find(v => v.imo_number === selectedImo)?.vessel_name
      await exportBunkerReportExcel(rows, vesselName)
    } catch (err) {
      alert('Export failed: ' + (err?.message || err))
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="br-page">
      <div className="br-topbar">
        <div className="br-topbar-left">
          <span className="br-title"><Fuel size={14} /> Bunker Report</span>
          <select
            className="br-vessel-select"
            value={selectedImo}
            onChange={e => {
              setImo(e.target.value)
              memoryStore.setItem('vp_last_vessel_bunker', e.target.value)
            }}
          >
            {vessels.length === 0 && <option value="">No vessels scraped yet</option>}
            {vessels.map(v => (
              <option key={v.imo_number} value={v.imo_number}>{v.vessel_name} ({v.imo_number})</option>
            ))}
          </select>
          {!loading && rows.length > 0 && (
            <span className="br-row-count">{rows.length} bunker record{rows.length === 1 ? '' : 's'}</span>
          )}
        </div>
        <button
          type="button"
          className="br-export-btn"
          onClick={handleExport}
          disabled={exporting || rows.length === 0}
          title="Export the Bunker Report table to Excel"
        >
          {exporting ? <Loader2 size={13} className="icon-spin" /> : <Download size={13} />}
          <span>Export Excel</span>
        </button>
      </div>

      <div className="br-body">
        {loading && <div className="br-empty"><Loader2 size={16} className="icon-spin" /> Loading…</div>}
        {!loading && error && <div className="br-empty error"><AlertTriangle size={13} /> {error}</div>}
        {!loading && !error && vessels.length === 0 && (
          <div className="br-empty">
            No Bunker Report data has been scraped yet — see backend/mariapps_pipeline/bunker_report_scraper.py.
          </div>
        )}
        {!loading && !error && vessels.length > 0 && rows.length === 0 && (
          <div className="br-empty">No bunker records for this vessel.</div>
        )}

        {!loading && !error && rows.length > 0 && (
          <div className="br-table-wrap">
            <table className="br-table">
              <thead>
                <tr>
                  <th></th>
                  <th>Transaction Type</th>
                  <th>Voyage Leg</th>
                  <th>Port</th>
                  <th>Fuel Type</th>
                  <th>Grade</th>
                  <th>BDN Reference</th>
                  <th>Quantity (MT)</th>
                  <th>Sulphur (%)</th>
                  <th>Density (kg/m³)</th>
                  <th>Viscosity (cSt)</th>
                  <th>Flash Pt (°C)</th>
                  <th>Supplier</th>
                  <th>Begin of Bunkering</th>
                  <th>End of Bunkering</th>
                  <th>Time Zone</th>
                  <th>MARPOL Sample No.</th>
                  <th>Bunker Analysis</th>
                  <th>Lab Report Date</th>
                  <th>Lab Density</th>
                  <th>Lab Sulphur</th>
                  <th>Lab Viscosity</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.id}>
                    <td className="br-dl-cell">
                      {r.download_url ? (
                        <button
                          type="button"
                          className="br-dl-btn"
                          onClick={() => setPreviewRow(r)}
                          title={`Preview ${r.attachment_file_name || 'attachment'}${r.attachments?.length > 1 ? ` (+${r.attachments.length - 1} more)` : ''}`}
                        >
                          <Eye size={13} />
                          {r.attachments?.length > 1 && <span className="br-dl-count">{r.attachments.length}</span>}
                        </button>
                      ) : (
                        <span className="br-dl-none" title="No attachment"><FileX size={13} /></span>
                      )}
                    </td>
                    <td>{r.transaction_type || '—'}</td>
                    <td>{r.voyage_leg || '—'}</td>
                    <td className="br-port">{r.port || '—'}</td>
                    <td>{r.fuel_type || '—'}</td>
                    <td>{r.imo_fuel_grade || '—'}</td>
                    <td className="br-bdn">{r.bdn_reference_no || '—'}</td>
                    <td className="br-num">{fmt(r.quantity_mt)}</td>
                    <td className="br-num">{fmt(r.sulphur_content, 3)}</td>
                    <td className="br-num">{fmt(r.density_15c, 1)}</td>
                    <td className="br-num">{fmt(r.kinematic_viscosity, 2)}</td>
                    <td className="br-num">{fmt(r.flash_point_c, 0)}</td>
                    <td>{r.supplier_company || '—'}</td>
                    <td className="br-dt">{r.begin_of_bunkering || '—'}</td>
                    <td className="br-dt">{r.end_of_bunkering || '—'}</td>
                    <td>{r.time_zone || '—'}</td>
                    <td>{r.marpol_sample_no || '—'}</td>
                    <td><StatusPill status={r.bunker_analysis_status} /></td>
                    <td className="br-dt">{r.lab_report_date || '—'}</td>
                    <td className="br-num">{fmt(r.lab_density_15c, 1)}</td>
                    <td className="br-num">{fmt(r.lab_sulphur_content, 3)}</td>
                    <td className="br-num">{fmt(r.lab_kinematic_viscosity, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {previewRow && (
        <AttachmentPreviewModal row={previewRow} onClose={() => setPreviewRow(null)} />
      )}
    </div>
  )
}
