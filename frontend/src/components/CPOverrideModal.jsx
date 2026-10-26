import { useState, useEffect, useCallback } from 'react'
import { X, Loader2, Trash2, Pencil } from 'lucide-react'
import { fetchCPOverrides, saveCPOverride, deleteCPOverride } from '../api/vesselApi'
import './CPOverrideModal.css'

// Manager request 2026-10 (prompted by the AMNSI MAXIMUS 62L/02 case — a real
// scraper gap left one day's remarks missing). Lets shore staff correct a
// voyage's (or one specific day's) CP speed/consumption once confirmed; flows
// into the same priority chain the remarks instruction already uses — see
// backend/cp/cp_overrides.py — so this is a REAL correction, not just a
// display tweak: it changes the Loss/Saving verdict too.
const emptyForm = { scope: 'voyage', log_date: '', speed_kn: '', total_mt_day: '', go_mt_day: '', note: '' }

export default function CPOverrideModal({ imo, source, voyageNo, onClose, onSaved }) {
  const [overrides, setOverrides] = useState([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState(emptyForm)
  const [editingId, setEditingId] = useState(null)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    fetchCPOverrides(imo, voyageNo, source)
      .then(setOverrides)
      .catch(() => setErr('Could not load existing overrides.'))
      .finally(() => setLoading(false))
  }, [imo, voyageNo, source])

  useEffect(() => { load() }, [load])

  function startEdit(o) {
    setEditingId(o.id)
    setForm({
      scope: o.log_date ? 'day' : 'voyage',
      log_date: o.log_date || '',
      speed_kn: o.speed_kn ?? '',
      total_mt_day: o.total_mt_day ?? '',
      go_mt_day: o.go_mt_day ?? '',
      note: o.note || '',
    })
  }

  function resetForm() {
    setEditingId(null)
    setForm(emptyForm)
  }

  async function handleSave() {
    if (!form.speed_kn && !form.total_mt_day && !form.go_mt_day) {
      setErr('Enter at least one of Speed / Total Consumption / GO.')
      return
    }
    if (form.scope === 'day' && !form.log_date) {
      setErr('Pick a date for a day-specific override, or switch scope to "Whole voyage".')
      return
    }
    setErr(null)
    setSaving(true)
    try {
      await saveCPOverride(imo, {
        source_id: source,
        voyage_no: voyageNo,
        log_date: form.scope === 'day' ? form.log_date : null,
        speed_kn: form.speed_kn === '' ? null : +form.speed_kn,
        total_mt_day: form.total_mt_day === '' ? null : +form.total_mt_day,
        go_mt_day: form.go_mt_day === '' ? null : +form.go_mt_day,
        note: form.note || null,
      })
      resetForm()
      load()
      onSaved?.()
    } catch (e) {
      setErr(e?.response?.data?.detail ?? 'Save failed.')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id) {
    try {
      await deleteCPOverride(imo, id)
      if (editingId === id) resetForm()
      load()
      onSaved?.()
    } catch {
      setErr('Delete failed.')
    }
  }

  return (
    <div className="cpo-backdrop" onClick={onClose}>
      <div className="cpo-modal" onClick={e => e.stopPropagation()}>
        <div className="cpo-head">
          <div>
            <span className="cpo-eyebrow">CP Manual Override</span>
            <h2>Voyage {voyageNo}</h2>
          </div>
          <button className="cpo-close" onClick={onClose}><X size={16} /></button>
        </div>

        <p className="cpo-help">
          Overrides take priority over the master's remarks instruction and the
          standing CP warranty — a correction here changes the Loss/Saving
          verdict and the Voyage Audit PDF, not just the display.
        </p>

        <div className="cpo-section">
          <span className="cpo-section-title">Existing overrides</span>
          {loading && <div className="cpo-empty"><Loader2 size={14} className="icon-spin" /> Loading…</div>}
          {!loading && overrides.length === 0 && <div className="cpo-empty">None set for this voyage.</div>}
          {!loading && overrides.map(o => (
            <div key={o.id} className={`cpo-row${editingId === o.id ? ' editing' : ''}`}>
              <div className="cpo-row-main">
                <span className="cpo-scope">{o.log_date ? o.log_date : 'Whole voyage'}</span>
                <span className="cpo-vals">
                  {o.speed_kn != null && <span>{o.speed_kn} kn</span>}
                  {o.total_mt_day != null && <span>{o.total_mt_day} mt/day</span>}
                  {o.go_mt_day != null && <span>GO {o.go_mt_day} mt/day</span>}
                </span>
                {o.note && <span className="cpo-note" title={o.note}>{o.note}</span>}
              </div>
              <div className="cpo-row-actions">
                <button className="cpo-icon-btn" title="Edit" onClick={() => startEdit(o)}><Pencil size={13} /></button>
                <button className="cpo-icon-btn danger" title="Delete" onClick={() => handleDelete(o.id)}><Trash2 size={13} /></button>
              </div>
            </div>
          ))}
        </div>

        <div className="cpo-section">
          <span className="cpo-section-title">{editingId ? 'Edit override' : 'Add override'}</span>

          <div className="cpo-field-row">
            <label className="cpo-radio">
              <input type="radio" checked={form.scope === 'voyage'} onChange={() => setForm(f => ({ ...f, scope: 'voyage' }))} />
              Whole voyage
            </label>
            <label className="cpo-radio">
              <input type="radio" checked={form.scope === 'day'} onChange={() => setForm(f => ({ ...f, scope: 'day' }))} />
              Specific day
            </label>
            {form.scope === 'day' && (
              <input
                type="date"
                className="cpo-input"
                value={form.log_date}
                onChange={e => setForm(f => ({ ...f, log_date: e.target.value }))}
              />
            )}
          </div>

          <div className="cpo-field-row">
            <label className="cpo-field">
              Speed (kn)
              <input type="number" step="0.1" className="cpo-input" value={form.speed_kn}
                onChange={e => setForm(f => ({ ...f, speed_kn: e.target.value }))} />
            </label>
            <label className="cpo-field">
              Total Consumption (mt/day)
              <input type="number" step="0.1" className="cpo-input" value={form.total_mt_day}
                onChange={e => setForm(f => ({ ...f, total_mt_day: e.target.value }))} />
            </label>
            <label className="cpo-field">
              GO (mt/day)
              <input type="number" step="0.1" className="cpo-input" value={form.go_mt_day}
                onChange={e => setForm(f => ({ ...f, go_mt_day: e.target.value }))} />
            </label>
          </div>

          <label className="cpo-field cpo-field-wide">
            Note (why this was overridden)
            <textarea className="cpo-input" rows={2} value={form.note}
              onChange={e => setForm(f => ({ ...f, note: e.target.value }))}
              placeholder="e.g. confirmed with master — remarks missing due to a scraper gap" />
          </label>

          {err && <div className="cpo-err">{err}</div>}

          <div className="cpo-actions">
            {editingId && <button className="cpo-btn" onClick={resetForm}>Cancel edit</button>}
            <button className="cpo-btn primary" disabled={saving} onClick={handleSave}>
              {saving ? <Loader2 size={13} className="icon-spin" /> : null}
              {editingId ? 'Update override' : 'Save override'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
