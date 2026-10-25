import { useState, useEffect, useCallback, useRef } from 'react'
import { Loader2, AlertTriangle, MessageSquare, Send, RefreshCw } from 'lucide-react'
import {
  fetchVessels, fetchDataQualityFindings, updateDataQualityFindingStatus,
  fetchDataQualityThreads, postDataQualityThread,
} from '../api/vesselApi'
import './DataQualityReviewPage.css'

// "Data Discrepancy & Voyage Review" — manager request 2026-10, modeled on the
// Drs module's Defect/Thread pattern: a queue of DataQualityFinding rows (the
// daily data-quality job already populates these), each with a discussion
// thread split into an Internal (shore-only) channel and a Vessel-facing one.
//
// Voyage-completion reviews (Phase 2 — triggered on EOSP) aren't built yet, so
// this page only lists data-quality discrepancies for now. The "Voyage
// Reviews" filter is left in place (disabled, empty) so the shape doesn't need
// to change once Phase 2 lands — same DataQualityThread table is meant to be
// reused for it.

const STATUS_LABEL = { open: 'Open', acknowledged: 'Acknowledged', resolved: 'Resolved' }

function fmtWhen(iso) {
  if (!iso) return ''
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  if (isNaN(d)) return iso
  return d.toLocaleString(undefined, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function initials(name) {
  const parts = (name || '?').trim().split(/\s+/)
  return ((parts[0]?.[0] || '') + (parts[1]?.[0] || '')).toUpperCase()
}

export default function DataQualityReviewPage() {
  const [vessels, setVessels] = useState([])
  const [vesselFilter, setVesselFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('open')
  const [findings, setFindings] = useState([])
  const [loadingFindings, setLoadingFindings] = useState(true)
  const [findingsError, setFindingsError] = useState(null)

  const [activeId, setActiveId] = useState(null)
  const [activeTab, setActiveTab] = useState('internal')
  const [threads, setThreads] = useState([])
  const [threadsLoading, setThreadsLoading] = useState(false)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const threadEndRef = useRef(null)

  useEffect(() => { fetchVessels().then(setVessels).catch(() => {}) }, [])

  const loadFindings = useCallback(() => {
    setLoadingFindings(true)
    setFindingsError(null)
    fetchDataQualityFindings(vesselFilter, statusFilter)
      .then(rows => {
        setFindings(rows)
        setActiveId(prev => {
          if (prev && rows.some(r => r.id === prev)) return prev
          return rows.length ? rows[0].id : null
        })
      })
      .catch(() => setFindingsError('Could not load findings.'))
      .finally(() => setLoadingFindings(false))
  }, [vesselFilter, statusFilter])

  useEffect(() => { loadFindings() }, [loadFindings])

  const loadThreads = useCallback(() => {
    if (!activeId) { setThreads([]); return }
    setThreadsLoading(true)
    fetchDataQualityThreads(activeId, activeTab === 'internal' ? 'internal' : 'vessel')
      .then(setThreads)
      .catch(() => setThreads([]))
      .finally(() => setThreadsLoading(false))
  }, [activeId, activeTab])

  useEffect(() => { loadThreads() }, [loadThreads])
  useEffect(() => { threadEndRef.current?.scrollIntoView({ block: 'nearest' }) }, [threads])

  const active = findings.find(f => f.id === activeId) || null

  async function handleSend() {
    if (!draft.trim() || !activeId || sending) return
    setSending(true)
    try {
      await postDataQualityThread(activeId, draft.trim(), activeTab === 'internal')
      setDraft('')
      loadThreads()
      loadFindings()
    } catch {
      // keep draft so the user doesn't lose it
    } finally {
      setSending(false)
    }
  }

  async function handleStatusChange(e) {
    const newStatus = e.target.value
    if (!active) return
    try {
      await updateDataQualityFindingStatus(active.id, newStatus)
      loadFindings()
    } catch {}
  }

  return (
    <div className="dqr-page">
      <div className="dqr-topbar">
        <div>
          <span className="dqr-eyebrow">Vessel Performance · Review</span>
          <h1>Data Discrepancy &amp; Voyage Review</h1>
        </div>
        <div className="dqr-topbar-right">
          <select className="dqr-select" value={vesselFilter} onChange={e => setVesselFilter(e.target.value)}>
            <option value="all">All vessels</option>
            {vessels.map(v => (
              <option key={v.imo_number} value={v.imo_number}>{v.vessel_name}</option>
            ))}
          </select>
          <select className="dqr-select" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="open">Open</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
            <option value="">All statuses</option>
          </select>
          <button className="dqr-icon-btn" title="Refresh" onClick={() => { loadFindings(); loadThreads() }}>
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      <div className="dqr-workspace">
        <div className="dqr-queue">
          <div className="dqr-queue-head">
            <span>Discrepancies</span>
            <span className="dqr-queue-count">{findings.length}</span>
          </div>
          <div className="dqr-queue-list">
            {loadingFindings && (
              <div className="dqr-empty"><Loader2 className="spin" size={16} /> Loading…</div>
            )}
            {!loadingFindings && findingsError && (
              <div className="dqr-empty dqr-error"><AlertTriangle size={14} /> {findingsError}</div>
            )}
            {!loadingFindings && !findingsError && findings.length === 0 && (
              <div className="dqr-empty">No findings for this filter.</div>
            )}
            {findings.map(f => (
              <button
                key={f.id}
                className={`dqr-item${f.id === activeId ? ' active' : ''}`}
                onClick={() => { setActiveId(f.id); setActiveTab('internal') }}
              >
                <div className="dqr-item-top">
                  <span className="dqr-item-type">Discrepancy</span>
                  {(f.vessel_count > 0 || f.internal_count > 0) && (
                    <span className="dqr-count-chip"><MessageSquare size={10} />{f.internal_count + f.vessel_count}</span>
                  )}
                </div>
                <div className="dqr-item-vessel">{f.vessel_name}</div>
                <div className="dqr-item-title">{f.rule_label}</div>
                <div className="dqr-item-meta">
                  <span className="mono">{f.report_date}</span>
                  <span className="dqr-dot" />
                  <span className={`dqr-badge ${f.status}`}>{STATUS_LABEL[f.status] || f.status}</span>
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="dqr-detail">
          {!active && (
            <div className="dqr-detail-empty">
              {loadingFindings ? 'Loading…' : 'Select a finding to view its review thread.'}
            </div>
          )}
          {active && (
            <>
              <div className="dqr-detail-head">
                <div className="dqr-detail-head-top">
                  <div>
                    <span className="dqr-eyebrow">Data Discrepancy · {active.source_id}</span>
                    <h2>{active.rule_label}</h2>
                  </div>
                  <select className="dqr-status-select" value={active.status} onChange={handleStatusChange}>
                    <option value="open">Open</option>
                    <option value="acknowledged">Acknowledged</option>
                    <option value="resolved">Resolved</option>
                  </select>
                </div>
                <div className="dqr-detail-sub">
                  <span><b>{active.vessel_name}</b></span>
                  <span className="mono">{active.report_date}</span>
                  {active.notify_count > 0 && <span>Notified {active.notify_count}×</span>}
                </div>
              </div>

              {active.detail && (
                <div className="dqr-note">
                  <b>Finding:</b>&nbsp;{active.detail.note || JSON.stringify(active.detail)}
                </div>
              )}

              <div className="dqr-tabs">
                <button className={`dqr-tab${activeTab === 'internal' ? ' active' : ''}`} onClick={() => setActiveTab('internal')}>
                  <span className="dqr-swatch internal" />Internal
                  <span className="dqr-n">{active.internal_count}</span>
                </button>
                <button className={`dqr-tab${activeTab === 'vessel' ? ' active' : ''}`} onClick={() => setActiveTab('vessel')}>
                  <span className="dqr-swatch vessel" />Vessel-facing
                  <span className="dqr-n">{active.vessel_count}</span>
                </button>
              </div>
              <div className={`dqr-banner ${activeTab}`}>
                {activeTab === 'internal'
                  ? 'Shore team only — never sent to the vessel.'
                  : 'Visible to the vessel and included in the emailed digest.'}
              </div>

              <div className="dqr-thread">
                {threadsLoading && <div className="dqr-empty"><Loader2 className="spin" size={16} /> Loading…</div>}
                {!threadsLoading && threads.length === 0 && (
                  <div className="dqr-system-msg">No messages yet in this channel.</div>
                )}
                {!threadsLoading && threads.map(m => (
                  <div key={m.id} className="dqr-msg">
                    <div className={`dqr-avatar ${m.is_internal ? 'internal' : 'vessel'}`}>{initials(m.author_name)}</div>
                    <div className="dqr-bubble">
                      <div className="dqr-who">
                        <span>{m.author_name}</span>
                        <span className={`dqr-tag ${m.is_internal ? 'internal' : 'vessel'}`}>
                          {m.is_internal ? 'Shore · Internal' : 'Vessel-facing'}
                        </span>
                        <span className="dqr-when">{fmtWhen(m.created_at)}</span>
                      </div>
                      <p>{m.body}</p>
                    </div>
                  </div>
                ))}
                <div ref={threadEndRef} />
              </div>

              <div className="dqr-composer">
                <textarea
                  value={draft}
                  onChange={e => setDraft(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) handleSend() }}
                  placeholder={activeTab === 'internal' ? 'Add an internal note… (Ctrl+Enter to send)' : 'Write to the vessel… (Ctrl+Enter to send)'}
                />
                <button className="dqr-btn primary" disabled={!draft.trim() || sending} onClick={handleSend}>
                  <Send size={14} /> Send
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
