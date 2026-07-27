import { useState, useEffect } from 'react'
import { Gauge, Loader2, AlertTriangle } from 'lucide-react'
import { fetchCPCompliance, fetchCPCompliancePilotVessels } from '../api/vesselApi'
import './CPComplianceSection.css'

const SOURCE_TABS = [
  { id: '', label: 'All' },
  { id: 'wni', label: 'WNI' },
  { id: 'mari_apps', label: 'MariApps' },
]

function voyageStatus(v) {
  if (v.qualifying_count === 0) return { cls: 'amber', label: 'Not computable' }
  if ((v.speed_shortfall_kn && v.speed_shortfall_kn > 0) || (v.excess_cons_mt && v.excess_cons_mt > 0)) {
    return { cls: 'red', label: 'Non-compliant' }
  }
  return { cls: 'green', label: 'Compliant' }
}

/**
 * Charter-Party Compliance Evaluation (Phase 3a pilot — AM KIRTI & GCL FOS only).
 * Drop-in, self-contained: fetches its own pilot-vessel list and compliance data.
 *
 * `hideWhenNotPiloted`: when true, renders nothing at all for a non-pilot vessel
 * (used inside CPSummaryPanel/Logbook+ so the other 12 vessels' voyage view is
 * completely unchanged). When false (default), shows an explicit "not in this
 * pilot yet" message instead (used in the standalone CP Description tab).
 *
 * `voyages`: optional array of Voyage_No strings. When provided (Logbook+ passes
 * the currently-selected voyage(s)), results are scoped to just those voyages —
 * otherwise the vessel's full compliance history is shown (CP Description tab).
 */
export default function CPComplianceSection({ imo, hideWhenNotPiloted = false, voyages = null }) {
  const [pilotVessels, setPilotVessels] = useState([])
  const [pilotVesselsLoaded, setPilotVesselsLoaded] = useState(false)
  const [source, setSource] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchCPCompliancePilotVessels()
      .then(setPilotVessels)
      .catch(() => setPilotVessels([]))
      .finally(() => setPilotVesselsLoaded(true))
  }, [])

  const isPilotVessel = pilotVessels.includes(imo)

  useEffect(() => {
    if (!imo || !pilotVesselsLoaded || !isPilotVessel) { setData(null); return }
    setLoading(true)
    setError(null)
    fetchCPCompliance(imo, source || undefined)
      .then(d => setData(d))
      .catch(e => {
        setError(e?.response?.status === 403 ? null : (e?.response?.data?.detail ?? 'Failed to load compliance results.'))
        setData(null)
      })
      .finally(() => setLoading(false))
  }, [imo, source, isPilotVessel, pilotVesselsLoaded])

  if (!pilotVesselsLoaded) return null
  if (!isPilotVessel && hideWhenNotPiloted) return null

  const voyageFilter = voyages && voyages.length > 0 ? new Set(voyages) : null
  const visibleVoyages = data ? (voyageFilter ? data.voyages.filter(v => voyageFilter.has(v.voyage_no)) : data.voyages) : []
  const visibleExceptions = data ? (voyageFilter ? data.exceptions.filter(e => voyageFilter.has(e.voyage_no)) : data.exceptions) : []

  return (
    <div className="cpc-card">
      <div className="cpc-card-title">
        <Gauge size={13} /> Compliance Evaluation
        <span className="cpc-card-meta">Phase 3a pilot — AM KIRTI &amp; GCL FOS only</span>
      </div>

      {isPilotVessel && (
        <div className="cpc-source-tabs">
          {SOURCE_TABS.map(t => (
            <button
              key={t.id}
              className={`cpc-source-tab${source === t.id ? ' active' : ''}`}
              onClick={() => setSource(t.id)}
            >{t.label}</button>
          ))}
        </div>
      )}

      {!isPilotVessel && (
        <div className="cpc-empty">
          This vessel is not part of the Phase 3a compliance pilot yet — only AM KIRTI and GCL FOS
          are evaluated so far, pending review before fleet-wide rollout.
        </div>
      )}
      {isPilotVessel && loading && (
        <div className="cpc-empty"><Loader2 size={16} className="icon-spin" /> Evaluating…</div>
      )}
      {isPilotVessel && !loading && error && (
        <div className="cpc-empty error">{error}</div>
      )}
      {isPilotVessel && !loading && !error && data && visibleVoyages.length === 0 && (
        <div className="cpc-empty">
          {voyageFilter
            ? 'No compliance result for the selected voyage(s) — they may not have matched a good-weather period.'
            : (data.note || 'No voyages to evaluate for this source.')}
        </div>
      )}

      {isPilotVessel && !loading && !error && data && visibleVoyages.length > 0 && (
        <>
          {visibleExceptions.length > 0 && (
            <div className="cpc-exception-banner">
              <AlertTriangle size={13} />
              <span>
                {visibleExceptions.length} exception{visibleExceptions.length > 1 ? 's' : ''} raised —{' '}
                {visibleExceptions.map((e, i) => (
                  <span key={i}>{e.detail}{i < visibleExceptions.length - 1 ? '; ' : ''}</span>
                ))}
              </span>
            </div>
          )}
          <div className="cpc-table-wrap">
            <table className="cpc-table">
              <thead>
                <tr>
                  <th>Source</th><th>Voyage</th><th>Loading</th><th>Matched Warranty</th>
                  <th>Qual. Reports</th><th>Observed (kn)</th><th>Threshold (kn)</th>
                  <th>Shortfall (kn)</th><th>Excess Cons (mt)</th><th>Time Lost/Gain (h)</th><th>Status</th>
                </tr>
              </thead>
              <tbody>
                {visibleVoyages.map((v, i) => {
                  const st = voyageStatus(v)
                  return (
                    <tr key={i} className={`cpc-row ${st.cls}`}>
                      <td>{v.source}</td>
                      <td>{v.voyage_no}</td>
                      <td>{v.loading_cond || '—'}</td>
                      <td>{v.matched_warranty ? `${v.matched_warranty.speed_mode} @ ${v.matched_warranty.warranted_speed_kn}kn` : '—'}</td>
                      <td>{v.qualifying_count}</td>
                      <td>{v.observed?.observed_speed_kn ?? '—'}</td>
                      <td>{v.thresholds?.speed_threshold_kn ?? '—'}</td>
                      <td>{v.speed_shortfall_kn ?? '—'}</td>
                      <td>{v.excess_cons_mt ?? '—'}</td>
                      <td>{v.time_lost_gained_h ?? '—'}</td>
                      <td><span className={`cpc-status-pill ${st.cls}`}>{st.label}</span></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {isPilotVessel && (
        <div className="cpc-footnote">
          <AlertTriangle size={11} />
          <span>
            This is a pilot evaluation with known approximations vs. the full evaluation specification (no charterer-instructed
            speed mode, no per-report exclusion-event flags, no adverse-current direction, fuel not split by grade,
            no drydock date or hire-rate data) — see backend/cp/cp_compliance_v2.py for the full list before acting on these numbers.
          </span>
        </div>
      )}
    </div>
  )
}
