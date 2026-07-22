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

export default function CPSummaryPanel({ imo, vesselName, source, voyages, loadingCond }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [pdfLoadingVoyage, setPdfLoadingVoyage] = useState(null)

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
      </div>

      {loading && <div className="cp-panel-msg">Loading…</div>}
      {error && <div className="cp-panel-msg cp-err">{error}</div>}
      {!loading && data && !data.cp_configured && (
        <div className="cp-panel-msg cp-warn">
          No CP warranties for this vessel — set them on ISO 19030 → Configuration to see Loss/Saving &amp; compliance.
        </div>
      )}

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
  )
}
