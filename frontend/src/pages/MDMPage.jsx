import { useState, useEffect, useCallback } from 'react'
import { memoryStore } from '../utils/memoryStore'

import { Save, ChevronDown, ChevronUp, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react'
import { fetchVessels, updateVesselSources } from '../api/vesselApi'
import { fetchDesignData, saveDesignData } from '../api/vesselApi'
import { MDM_FIELDS, MDM_CATEGORIES } from '../utils/mdmFields'
import './MDMPage.css'

// ── Mandatory badge ───────────────────────────────────────────────────────────
function MandatoryBadge({ level }) {
  if (!level) return null
  const map = { '*': ['mand-1', 'M'], '**': ['mand-2', 'HM'], '***': ['mand-3', 'CM'] }
  const [cls, label] = map[level] || []
  if (!cls) return null
  return <span className={`mdm-mand ${cls}`}>{label}</span>
}

// ── Single field input ────────────────────────────────────────────────────────
function FieldInput({ field, value, onChange }) {
  const isNum = field.type === 'Scalar' || field.type === 'Integer'
  return (
    <div className="mdm-field">
      <label className="mdm-label">
        <span className="mdm-field-name">{field.name}</span>
        {field.unit && <span className="mdm-unit">[{field.unit}]</span>}
        <MandatoryBadge level={field.mandatory} />
      </label>
      <input
        className="mdm-input"
        type={isNum ? 'number' : 'text'}
        step={field.type === 'Scalar' ? 'any' : undefined}
        value={value ?? ''}
        placeholder={field.symbol}
        onChange={e => onChange(field.col, e.target.value)}
      />
    </div>
  )
}

// ── Category accordion section ────────────────────────────────────────────────
function CategorySection({ category, fields, formData, onChange, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen)

  const filled  = fields.filter(f => formData[f.col] !== undefined && formData[f.col] !== '' && formData[f.col] !== null).length
  const total   = fields.length
  const pct     = Math.round((filled / total) * 100)

  return (
    <div className={`mdm-section${open ? ' open' : ''}`}>
      <button className="mdm-section-header" onClick={() => setOpen(o => !o)}>
        <span className="mdm-section-title">{category}</span>
        <span className="mdm-section-meta">
          <span className="mdm-progress-pill" style={{ '--pct': `${pct}%` }}>
            {filled}/{total}
          </span>
        </span>
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {open && (
        <div className="mdm-section-body">
          {fields.map(f => (
            <FieldInput
              key={f.col}
              field={f}
              value={formData[f.col]}
              onChange={onChange}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function MDMPage() {
  const [vessels,    setVessels]   = useState([])
  const [selectedImo, setImo]     = useState('')
  const [formData,   setFormData] = useState({})
  const [loading,    setLoading]  = useState(false)
  const [saving,     setSaving]   = useState(false)
  const [toast,      setToast]    = useState(null)   // { type: 'success'|'error', msg }
  const [search,     setSearch]   = useState('')
  const [activeCat,  setActiveCat] = useState('all') // 'all' or category_full

  // Load vessel list
  useEffect(() => {
    fetchVessels()
      .then(list => {
        setVessels(list)
        if (list.length > 0) {
          const saved = memoryStore.getItem('vp_last_vessel_mdm');
          if (saved && list.find(v => v.imo_number === saved)) {
            setImo(saved);
          } else {
            setImo(list[0].imo_number);
          }
        }
      })
      .catch(console.error)
  }, [])

  // Currently selected vessel's source flags
  const selectedVessel = vessels.find(v => v.imo_number === selectedImo)

  const handleToggleSource = async (key) => {
    if (!selectedVessel) return
    const next = !selectedVessel[key]
    // Optimistic update
    setVessels(prev => prev.map(v =>
      v.imo_number === selectedImo ? { ...v, [key]: next } : v
    ))
    try {
      await updateVesselSources(selectedImo, { [key]: next })
      showToast('success', `${key === 'wni_enabled' ? 'WNI' : 'MariApps'} ${next ? 'enabled' : 'disabled'} for ${selectedVessel.vessel_name}.`)
    } catch (e) {
      // Revert on failure
      setVessels(prev => prev.map(v =>
        v.imo_number === selectedImo ? { ...v, [key]: !next } : v
      ))
      showToast('error', e?.response?.data?.detail ?? 'Failed to update source.')
    }
  }

  // Load design data when vessel changes
  useEffect(() => {
    if (!selectedImo) return
    setLoading(true)
    fetchDesignData(selectedImo)
      .then(data => setFormData(data._empty ? {} : data))
      .catch(() => setFormData({}))
      .finally(() => setLoading(false))
  }, [selectedImo])

  const handleChange = useCallback((col, value) => {
    setFormData(prev => ({ ...prev, [col]: value === '' ? null : value }))
  }, [])

  const handleSave = async () => {
    if (!selectedImo) return
    setSaving(true)
    try {
      await saveDesignData(selectedImo, formData)
      showToast('success', 'Design data saved successfully.')
    } catch (e) {
      showToast('error', e?.response?.data?.detail ?? 'Save failed.')
    } finally {
      setSaving(false)
    }
  }

  function showToast(type, msg) {
    setToast({ type, msg })
    setTimeout(() => setToast(null), 3500)
  }

  // Filter fields by search + active category
  const filteredFields = MDM_FIELDS.filter(f => {
    if (activeCat !== 'all' && f.category_full !== activeCat) return false
    if (search) {
      const q = search.toLowerCase()
      return (
        f.name.toLowerCase().includes(q) ||
        f.symbol.toLowerCase().includes(q) ||
        f.col.toLowerCase().includes(q)
      )
    }
    return true
  })

  // Group filtered fields by category
  const grouped = {}
  for (const f of filteredFields) {
    if (!grouped[f.category_full]) grouped[f.category_full] = []
    grouped[f.category_full].push(f)
  }

  const totalFilled = MDM_FIELDS.filter(f =>
    formData[f.col] !== undefined && formData[f.col] !== '' && formData[f.col] !== null
  ).length

  return (
    <div className="mdm-page">

      {/* ── Top bar ─────────────────────────────────────────────── */}
      <div className="mdm-topbar">
        <div className="mdm-topbar-left">
          <span className="mdm-title">Vessel Design Data <span className="mdm-subtitle">Master Data Management</span></span>
          <select
            className="mdm-vessel-select"
            value={selectedImo}
            onChange={e => {
              setImo(e.target.value);
              memoryStore.setItem('vp_last_vessel_mdm', e.target.value);
            }}
          >
            {vessels.map(v => (
              <option key={v.imo_number} value={v.imo_number}>{v.vessel_name}</option>
            ))}
          </select>
          <span className="mdm-fill-count">{totalFilled} / {MDM_FIELDS.length} fields filled</span>
        </div>
        <button
          className="mdm-save-btn"
          onClick={handleSave}
          disabled={saving || !selectedImo}
        >
          {saving
            ? <><Loader2 size={13} className="icon-spin" /> Saving…</>
            : <><Save size={13} /> Save</>
          }
        </button>
      </div>

      {/* ── Pipeline source toggles (per selected vessel) ───────── */}
      {selectedVessel && (
        <div className="mdm-source-bar">
          <span className="mdm-source-label">Data pipelines:</span>
          <label className="mdm-source-toggle">
            <input
              type="checkbox"
              checked={!!selectedVessel.wni_enabled}
              onChange={() => handleToggleSource('wni_enabled')}
            />
            <span>WNI (Weathernews)</span>
          </label>
          <label className="mdm-source-toggle">
            <input
              type="checkbox"
              checked={!!selectedVessel.mari_enabled}
              onChange={() => handleToggleSource('mari_enabled')}
            />
            <span>MariApps</span>
          </label>
          <span className="mdm-source-hint">Controls which scrapers include this vessel. Applies on the next pipeline run.</span>
        </div>
      )}

      {/* ── Category filter pills ───────────────────────────────── */}
      <div className="mdm-cat-bar">
        <button
          className={`mdm-cat-pill${activeCat === 'all' ? ' active' : ''}`}
          onClick={() => setActiveCat('all')}
        >All</button>
        {MDM_CATEGORIES.map(c => (
          <button
            key={c.full}
            className={`mdm-cat-pill${activeCat === c.full ? ' active' : ''}`}
            onClick={() => setActiveCat(c.full)}
          >{c.short}</button>
        ))}
      </div>

      {/* ── Search bar ─────────────────────────────────────────── */}
      <div className="mdm-search-bar">
        <input
          className="mdm-search-input"
          placeholder="Search fields by name, symbol or column…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        {search && (
          <button className="mdm-search-clear" onClick={() => setSearch('')}>✕</button>
        )}
      </div>

      {/* ── Body ───────────────────────────────────────────────── */}
      <div className="mdm-body">
        {loading ? (
          <div className="mdm-loading"><Loader2 size={20} className="icon-spin" /> Loading…</div>
        ) : Object.keys(grouped).length === 0 ? (
          <div className="mdm-empty">No fields match your search.</div>
        ) : (
          Object.entries(grouped).map(([cat, fields], i) => (
            <CategorySection
              key={cat}
              category={cat}
              fields={fields}
              formData={formData}
              onChange={handleChange}
              defaultOpen={i === 0}
            />
          ))
        )}
      </div>

      {/* ── Legend ─────────────────────────────────────────────── */}
      <div className="mdm-legend">
        <span className="mdm-mand mand-1">M</span> Mandatory &nbsp;
        <span className="mdm-mand mand-2">HM</span> Highly Mandatory &nbsp;
        <span className="mdm-mand mand-3">CM</span> Critically Mandatory
      </div>

      {/* ── Toast ──────────────────────────────────────────────── */}
      {toast && (
        <div className={`mdm-toast ${toast.type}`}>
          {toast.type === 'success'
            ? <CheckCircle2 size={14} />
            : <AlertCircle size={14} />
          }
          {toast.msg}
        </div>
      )}
    </div>
  )
}
