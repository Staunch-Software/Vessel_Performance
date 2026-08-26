import { useState, useEffect } from 'react'
import { memoryStore } from '../utils/memoryStore'
import { Loader2, AlertTriangle, Fuel, Download, FileX, Eye, X } from 'lucide-react'
import { fetchBunkerReportVessels, fetchBunkerReport } from '../api/vesselApi'
import './BunkerReportPage.css'

const fmt = (v, d = 2) =>
  v === null || v === undefined || isNaN(v) ? '—' : (+v).toFixed(d)

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
function AttachmentPreviewModal({ row, onClose }) {
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="br-modal-backdrop" onClick={onClose}>
      <div className="br-modal" onClick={e => e.stopPropagation()}>
        <div className="br-modal-header">
          <span className="br-modal-title">{row.attachment_file_name || 'Attachment'}</span>
          <div className="br-modal-actions">
            <a
              className="br-modal-dl-btn"
              href={row.download_url}
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
        <div className="br-modal-body">
          <iframe
            title={row.attachment_file_name || 'Attachment preview'}
            src={row.download_url}
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
                          title={`Preview ${r.attachment_file_name || 'attachment'}`}
                        >
                          <Eye size={13} />
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
