import { useEffect, useState, useRef } from 'react'
import { ChevronLeft, ChevronRight, Columns, Plus, X, Check, Loader2 } from 'lucide-react'
import { fetchVessels, fetchVoyages, addVessel } from '../api/vesselApi'
import './TopFilterBar.css'

const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

function formatMonthLabel(date) {
  return `${MONTHS[date.getMonth()]} ${date.getFullYear()}`
}

function monthBounds(date) {
  const y = date.getFullYear(), m = date.getMonth()
  const pad = n => String(n).padStart(2, '0')
  // Build YYYY-MM-DD directly from local year/month/day.
  // DO NOT use .toISOString() here — it converts to UTC and shifts the date
  // by the local UTC offset, causing the last day of every month to fall
  // into the next month's range for UTC+ timezones (e.g. IST UTC+5:30).
  const lastDay = new Date(y, m + 1, 0).getDate()  // last calendar day of month
  return {
    fromDate: `${y}-${pad(m + 1)}-01`,
    toDate:   `${y}-${pad(m + 1)}-${pad(lastDay)}`,
  }
}

// ── Add Vessel Modal ──────────────────────────────────────────────────────────
function AddVesselModal({ onClose, onAdded }) {
  const [imo,     setImo]     = useState('')
  const [name,    setName]    = useState('')
  const [saving,  setSaving]  = useState(false)
  const [error,   setError]   = useState('')
  const imoRef = useRef(null)

  useEffect(() => {
    imoRef.current?.focus()
    function onKey(e) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function handleSubmit(e) {
    e.preventDefault()
    const trimImo  = imo.trim()
    const trimName = name.trim()
    if (!trimImo || !trimName) { setError('Both fields are required.'); return }

    setSaving(true)
    setError('')
    try {
      const vessel = await addVessel(trimImo, trimName)
      onAdded(vessel)
      onClose()
    } catch (err) {
      setError(err?.response?.data?.detail ?? err.message ?? 'Failed to create vessel.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="av-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="av-modal">
        <div className="av-header">
          <span className="av-title"><Plus size={14} /> Add New Vessel</span>
          <button className="av-close" onClick={onClose}><X size={15} /></button>
        </div>

        <form className="av-body" onSubmit={handleSubmit}>
          <div className="av-field">
            <label className="av-label">IMO Number</label>
            <input
              ref={imoRef}
              className="av-input"
              placeholder="e.g. 9832913"
              value={imo}
              onChange={e => { setImo(e.target.value); setError('') }}
              maxLength={10}
            />
          </div>
          <div className="av-field">
            <label className="av-label">Vessel Name</label>
            <input
              className="av-input"
              placeholder="e.g. AM KIRTI"
              value={name}
              onChange={e => { setName(e.target.value); setError('') }}
              maxLength={120}
            />
          </div>

          {error && <div className="av-error">{error}</div>}

          <div className="av-actions">
            <button type="button" className="av-cancel" onClick={onClose}>Cancel</button>
            <button type="submit" className="av-submit" disabled={saving}>
              {saving
                ? <><Loader2 size={13} className="icon-spin" /> Saving…</>
                : <><Check size={13} /> Add Vessel</>
              }
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function TopFilterBar({ graphType, onGraphTypeChange, onFiltersChange, defaultVesselImo, onColumnsClick }) {
  const [vessels, setVessels]         = useState([])
  const [selectedVessel, setVessel]   = useState('')
  const [displayType, setDisplayType] = useState('month')
  const [currentMonth, setMonth]      = useState(new Date())
  const [voyages, setVoyages]         = useState([])
  const [selectedVoyage, setVoyage]   = useState('')
  const [source, setSource]           = useState('mari_apps')
  const [showAddModal, setShowModal]  = useState(false)
  const [loadingCond, setLoadingCond] = useState('all')   // all | Laden | Ballast

  // Load vessel list on mount
  useEffect(() => {
    fetchVessels()
      .then(list => {
        setVessels(list)
        if (list.length > 0) {
          if (defaultVesselImo) {
            const match = list.find(v => v.imo_number === defaultVesselImo)
            setVessel(match ? defaultVesselImo : list[0].imo_number)
          } else {
            const amKirti = list.find(v => v.vessel_name.toLowerCase().includes('am kirti'))
            setVessel(amKirti ? amKirti.imo_number : list[0].imo_number)
          }
        }
      })
      .catch(console.error)
  }, []) // eslint-disable-line

  // Reload voyages when vessel OR source changes (so dropdown only shows relevant voyages)
  useEffect(() => {
    if (!selectedVessel) return
    fetchVoyages(selectedVessel, source)
      .then(list => { setVoyages(list); setVoyage(list[0] ?? '') })
      .catch(console.error)
  }, [selectedVessel, source])

  // Reset loading condition when switching away from voyage mode
  useEffect(() => {
    if (displayType !== 'voyage') setLoadingCond('all')
  }, [displayType])

  // Fire filter change whenever any filter state changes
  useEffect(() => {
    if (!selectedVessel) return
    const filters = { vessel_imo: selectedVessel }

    if (displayType === 'month') {
      Object.assign(filters, monthBounds(currentMonth))
    } else if (displayType === 'voyage' && selectedVoyage) {
      filters.voyageNo = String(selectedVoyage)
      if (loadingCond !== 'all') {
        filters.loadingCond = loadingCond
        filters.loadingConditions = [loadingCond]
      }
    }

    if (source !== 'all') filters.source_id = source
    onFiltersChange(filters)
  }, [selectedVessel, displayType, currentMonth, selectedVoyage, source, loadingCond])

  // Called when a new vessel is successfully added
  function handleVesselAdded(newVessel) {
    setVessels(prev => [...prev, newVessel].sort((a, b) => a.vessel_name.localeCompare(b.vessel_name)))
    setVessel(newVessel.imo_number)   // auto-select the new vessel
  }

  return (
    <>
      <div className="filter-bar">

        {/* Vessel selector + Add button */}
        <div className="filter-group">
          <span className="filter-label">Vessel</span>
          <div className="vessel-select-wrap">
            <select className="filter-select" value={selectedVessel} onChange={e => setVessel(e.target.value)}>
              {vessels.map(v => <option key={v.imo_number} value={v.imo_number}>{v.vessel_name}</option>)}
            </select>
            <button
              className="add-vessel-btn"
              onClick={() => setShowModal(true)}
              title="Add new vessel"
            >
              <Plus size={13} />
            </button>
          </div>
        </div>

        <div className="filter-divider" />

        {/* Display type */}
        <div className="filter-group">
          <span className="filter-label">Display Type</span>
          <div className="radio-group">
            {[['month','Month'], ['voyage','Voyage Number'], ['all','All Period']].map(([val, label]) => (
              <label key={val} className="radio-option">
                <input type="radio" name="displayType" value={val}
                  checked={displayType === val} onChange={() => setDisplayType(val)} />
                {label}
              </label>
            ))}
          </div>
        </div>

        {/* Month nav */}
        {displayType === 'month' && (
          <div className="filter-group">
            <span className="filter-label">&nbsp;</span>
            <div className="month-nav">
              <button className="nav-btn" onClick={() => setMonth(d => new Date(d.getFullYear(), d.getMonth()-1, 1))}><ChevronLeft size={14} /></button>
              <span className="month-label">{formatMonthLabel(currentMonth)}</span>
              <button className="nav-btn" onClick={() => setMonth(d => new Date(d.getFullYear(), d.getMonth()+1, 1))}><ChevronRight size={14} /></button>
            </div>
          </div>
        )}

        {/* Voyage selector */}
        {displayType === 'voyage' && (
          <div className="filter-group">
            <span className="filter-label">Voyage No</span>
            <select className="filter-select" value={selectedVoyage} onChange={e => setVoyage(e.target.value)}>
              {voyages.map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          </div>
        )}

        {/* Loading condition — shown when Voyage Number is selected */}
        {displayType === 'voyage' && (
          <div className="filter-group">
            <span className="filter-label">Condition</span>
            <div className="radio-group">
              {[['all','All'], ['Laden','Laden'], ['Ballast','Ballast']].map(([val, label]) => (
                <label key={val} className={`radio-option source-pill${loadingCond === val ? ' active' : ''}`}>
                  <input type="radio" name="loadingCond" value={val}
                    checked={loadingCond === val} onChange={() => setLoadingCond(val)} />
                  {label}
                </label>
              ))}
            </div>
          </div>
        )}

        <div className="filter-divider" />

        {/* Source toggle */}
        <div className="filter-group">
          <span className="filter-label">Source</span>
          <div className="radio-group">
            {[['all','All'], ['wni','WNI'], ['mari_apps','MariApps']].map(([val, label]) => (
              <label key={val} className={`radio-option source-pill${source === val ? ' active' : ''}`}>
                <input type="radio" name="source" value={val}
                  checked={source === val} onChange={() => setSource(val)} />
                {label}
              </label>
            ))}
          </div>
        </div>

        <div className="filter-divider" />

        {/* Graph type */}
        <div className="filter-group">
          <span className="filter-label">Graph Type</span>
          <select className="filter-select graph-type-select" value={graphType}
            onChange={e => onGraphTypeChange(e.target.value)}>
            <option value="fuel">Total Fuel</option>
            <option value="speed">Speed-Power Scatter</option>
            <option value="speed_loss">Speed Loss %</option>
          </select>
        </div>

        <div className="filter-divider" />

        {/* Column picker trigger */}
        {onColumnsClick && (
          <button className="columns-btn" onClick={onColumnsClick} title="Show/hide columns">
            <Columns size={13} />
            Columns
          </button>
        )}

      </div>

      {/* Add Vessel Modal */}
      {showAddModal && (
        <AddVesselModal
          onClose={() => setShowModal(false)}
          onAdded={handleVesselAdded}
        />
      )}
    </>
  )
}
