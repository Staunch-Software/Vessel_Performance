import { useEffect, useState, useRef } from 'react'
import { createPortal } from 'react-dom'
import { ChevronLeft, ChevronRight, Columns, Plus, X, Check, Loader2 } from 'lucide-react'
import { fetchVessels, fetchVoyages, addVessel, updateVesselSources } from '../api/vesselApi'
import './TopFilterBar.css'

const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

function formatMonthLabel(date) {
  return `${MONTHS[date.getMonth()]} ${date.getFullYear()}`
}

const pad2 = n => String(n).padStart(2, '0')
// Local YYYY-MM-DD (never via toISOString — that shifts to UTC, see note below)
const fmtDate = d => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`

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

// Preset period → {fromDate, toDate} ending today, going back the chosen span.
function presetBounds(preset) {
  const to   = new Date()
  const from = new Date(to)
  if      (preset === '1m') from.setMonth(from.getMonth() - 1)
  else if (preset === '3m') from.setMonth(from.getMonth() - 3)
  else if (preset === '6m') from.setMonth(from.getMonth() - 6)
  else if (preset === '1y') from.setFullYear(from.getFullYear() - 1)
  return { fromDate: fmtDate(from), toDate: fmtDate(to) }
}

// ── Add Vessel Modal ──────────────────────────────────────────────────────────
function AddVesselModal({ onClose, onAdded }) {
  const [imo,     setImo]     = useState('')
  const [name,    setName]    = useState('')
  const [wni,     setWni]     = useState(true)   // include in WNI scrape
  const [mari,    setMari]    = useState(true)   // include in MariApps scrape
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
      // Apply the chosen pipeline flags to the freshly created vessel
      const withSources = await updateVesselSources(vessel.imo_number, {
        wni_enabled: wni,
        mari_enabled: mari,
      })
      onAdded(withSources)
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

          <div className="av-field">
            <label className="av-label">Data Pipelines</label>
            <div className="av-sources">
              <label className="av-source-toggle">
                <input type="checkbox" checked={wni} onChange={e => setWni(e.target.checked)} />
                <span>WNI (Weathernews)</span>
              </label>
              <label className="av-source-toggle">
                <input type="checkbox" checked={mari} onChange={e => setMari(e.target.checked)} />
                <span>MariApps</span>
              </label>
            </div>
            <span className="av-hint">Which scrapers should include this vessel.</span>
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
export default function TopFilterBar({ graphType, onGraphTypeChange, fuelMode, onFuelModeChange, source, onSourceChange, onFiltersChange, defaultVesselImo, onColumnsClick }) {
  const [vessels, setVessels]         = useState([])
  const [selectedVessel, setVessel]   = useState('')
  const [displayType, setDisplayType] = useState('month')
  const [currentMonth, setMonth]      = useState(new Date())
  const [voyages, setVoyages]         = useState([])
  const [selectedVoyages, setSelVoyages] = useState([])   // multi-select
  const [voyageOpen, setVoyageOpen]   = useState(false)
  const [voyagePos, setVoyagePos]     = useState({ top: 0, left: 0, width: 220 })
  const voyageBoxRef   = useRef(null)   // trigger wrapper
  const voyagePanelRef = useRef(null)   // portal panel
  const [showAddModal, setShowModal]  = useState(false)
  const [loadingCond, setLoadingCond] = useState('all')   // all | Laden | Ballast
  // Period mode (replaces old "All Period")
  const [periodType, setPeriodType]   = useState('preset') // preset | custom
  const [periodPreset, setPreset]     = useState('3m')     // 1m | 3m | 6m | 1y
  const [customFrom, setCustomFrom]   = useState('')
  const [customTo, setCustomTo]       = useState('')

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
      .then(list => {
        setVoyages(list)
        setSelVoyages(list.length ? [String(list[0])] : [])   // default to first voyage
      })
      .catch(console.error)
  }, [selectedVessel, source])

  // Close the voyage multi-select when clicking outside the trigger AND the portal panel
  useEffect(() => {
    if (!voyageOpen) return
    function onDocClick(e) {
      const inTrigger = voyageBoxRef.current?.contains(e.target)
      const inPanel   = voyagePanelRef.current?.contains(e.target)
      if (!inTrigger && !inPanel) setVoyageOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [voyageOpen])

  // Open the voyage dropdown, anchoring the portal panel under the trigger
  function toggleVoyageOpen() {
    if (!voyageOpen) {
      const r = voyageBoxRef.current?.getBoundingClientRect()
      if (r) setVoyagePos({ top: r.bottom + 4, left: r.left, width: Math.max(r.width, 220) })
    }
    setVoyageOpen(o => !o)
  }

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
    } else if (displayType === 'voyage' && selectedVoyages.length) {
      filters.voyageNos = selectedVoyages.map(String)
      if (loadingCond !== 'all') {
        filters.loadingCond = loadingCond
        filters.loadingConditions = [loadingCond]
      }
    } else if (displayType === 'period') {
      if (periodType === 'preset') {
        Object.assign(filters, presetBounds(periodPreset))
      } else if (customFrom && customTo) {
        filters.fromDate = customFrom
        filters.toDate   = customTo
      } else {
        // Custom range chosen but incomplete — don't fire a half-filter
        return
      }
    }

    if (source !== 'all') filters.source_id = source
    onFiltersChange(filters)
  }, [selectedVessel, displayType, currentMonth, selectedVoyages, source, loadingCond,
      periodType, periodPreset, customFrom, customTo])

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
            {[['month','Month'], ['voyage','Voyage Number'], ['period','Period']].map(([val, label]) => (
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

        {/* Period selector — preset span or custom date range */}
        {displayType === 'period' && (
          <div className="filter-group">
            <span className="filter-label">Period</span>
            <div className="period-controls">
              <div className="radio-group">
                {[['preset','Preset'], ['custom','Custom Range']].map(([val, label]) => (
                  <label key={val} className={`radio-option source-pill${periodType === val ? ' active' : ''}`}>
                    <input type="radio" name="periodType" value={val}
                      checked={periodType === val} onChange={() => setPeriodType(val)} />
                    {label}
                  </label>
                ))}
              </div>
              {periodType === 'preset' ? (
                <select className="filter-select period-preset-select" value={periodPreset}
                  onChange={e => setPreset(e.target.value)}>
                  <option value="1m">Last 1 Month</option>
                  <option value="3m">Last 3 Months</option>
                  <option value="6m">Last 6 Months</option>
                  <option value="1y">Last 1 Year</option>
                </select>
              ) : (
                <div className="date-range">
                  <input type="date" className="date-input" value={customFrom}
                    max={customTo || undefined}
                    onChange={e => setCustomFrom(e.target.value)} />
                  <span className="date-range-sep">→</span>
                  <input type="date" className="date-input" value={customTo}
                    min={customFrom || undefined}
                    onChange={e => setCustomTo(e.target.value)} />
                </div>
              )}
            </div>
          </div>
        )}

        {/* Voyage selector — multi-select with checkboxes */}
        {displayType === 'voyage' && (
          <div className="filter-group">
            <span className="filter-label">Voyage No</span>
            <div className="voyage-multi" ref={voyageBoxRef}>
              <button
                type="button"
                className="filter-select voyage-multi-trigger"
                onClick={toggleVoyageOpen}
                title="Select one or more voyages"
              >
                {selectedVoyages.length === 0
                  ? 'Select voyages…'
                  : selectedVoyages.length === 1
                    ? selectedVoyages[0]
                    : `${selectedVoyages.length} voyages selected`}
              </button>
              {voyageOpen && createPortal(
                <div
                  className="voyage-multi-panel"
                  ref={voyagePanelRef}
                  style={{ position: 'fixed', top: voyagePos.top, left: voyagePos.left, minWidth: voyagePos.width, zIndex: 1300 }}
                >
                  <div className="voyage-multi-actions">
                    <button type="button" onClick={() => setSelVoyages(voyages.map(String))}>All</button>
                    <button type="button" onClick={() => setSelVoyages([])}>None</button>
                  </div>
                  {voyages.length === 0 && <div className="voyage-multi-empty">No voyages</div>}
                  {voyages.map(v => {
                    const val = String(v)
                    const checked = selectedVoyages.includes(val)
                    return (
                      <label key={val} className="voyage-multi-item">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => setSelVoyages(prev =>
                            prev.includes(val) ? prev.filter(x => x !== val) : [...prev, val]
                          )}
                        />
                        {val}
                      </label>
                    )
                  })}
                </div>,
                document.body
              )}
            </div>
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
                  checked={source === val} onChange={() => onSourceChange(val)} />
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

        {/* Fuel granularity — only for Total Fuel */}
        {graphType === 'fuel' && onFuelModeChange && (
          <div className="filter-group">
            <span className="filter-label">Fuel Data</span>
            <select className="filter-select graph-type-select" value={fuelMode}
              onChange={e => onFuelModeChange(e.target.value)}>
              <option value="daily">Daily Data</option>
              <option value="event">Event-wise Data</option>
              <option value="underway">Underway Data</option>
            </select>
          </div>
        )}

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
