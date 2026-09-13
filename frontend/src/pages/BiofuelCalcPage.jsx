import { useState, useEffect, useCallback } from 'react'
import { memoryStore } from '../utils/memoryStore'
import { Loader2, AlertTriangle, Droplet, Plus, Pencil, Trash2, X, Info, Link2 } from 'lucide-react'
import {
  fetchVessels, fetchBiofuelStems, fetchBiofuelBunkerCandidates,
  createBiofuelStem, updateBiofuelStem, deleteBiofuelStem,
} from '../api/vesselApi'
import './BiofuelCalcPage.css'

// This page is a 1:1 rebuild of the "Biofuel_Calc" worksheet in the
// client's Unified_Emissions_2026_v6 - Final.xlsx — same input columns
// (A-I, R on that sheet), same calculated columns (J-Q, S, T), same
// weighted-average summary row. See backend/emission/biofuel_calculator.py
// for the cell-by-cell formula citations. Do not add fields the sheet
// doesn't have (feedstock, certification, PoS, etc. were an earlier,
// non-matching design — removed).

const BASE_GRADES = ['HFO', 'LFO', 'MDO']
const INPUT_BASES = ['Mass%', 'Vol%']

const EMPTY_FORM = {
  bunker_report_id: null, bdn_number: '', delivery_date: '', port: '', base_fuel_grade: 'HFO',
  biofuel_type: 'FAME Biodiesel', input_basis: 'Mass%', bio_pct: '', rho_base: '', rho_bio: '', quantity_mt: '',
}

const fmt = (v, d = 2) => (v === null || v === undefined || isNaN(v) ? '—' : (+v).toFixed(d))

function StemModal({ imo, initial, onClose, onSaved }) {
  const [form, setForm] = useState(initial ? {
    ...EMPTY_FORM,
    ...Object.fromEntries(Object.entries(initial).map(([k, v]) => [k, v === null ? '' : v])),
  } : EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [candidates, setCandidates] = useState([])
  const [candidatesLoading, setCandidatesLoading] = useState(false)
  // 'bunker' (pick a real scraped delivery) vs 'manual' (type everything by
  // hand) — defaults to 'bunker' once candidates load if any exist and this
  // is a new, unlinked stem; an existing linked stem always shows as bunker.
  const [source, setSource] = useState(initial?.bunker_report_id ? 'bunker' : 'manual')
  const isEdit = !!initial
  const isVol = form.input_basis === 'Vol%'
  const isLinked = !!form.bunker_report_id

  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    if (isEdit) return  // don't offer re-picking a source on an existing stem
    setCandidatesLoading(true)
    fetchBiofuelBunkerCandidates(imo)
      .then(list => { setCandidates(list); if (list.length > 0) setSource('bunker') })
      .catch(() => setCandidates([]))
      .finally(() => setCandidatesLoading(false))
  }, [imo, isEdit])

  function set(field, val) { setForm(f => ({ ...f, [field]: val })) }

  function pickCandidate(bunkerReportId) {
    const c = candidates.find(x => String(x.bunker_report_id) === String(bunkerReportId))
    if (!c) { setForm(f => ({ ...f, bunker_report_id: null })); return }
    setForm(f => ({
      ...f,
      bunker_report_id: c.bunker_report_id,
      bdn_number: c.bdn_number || '',
      delivery_date: c.delivery_date || '',
      port: c.port || '',
      base_fuel_grade: c.base_fuel_grade || f.base_fuel_grade,
      quantity_mt: c.quantity_mt ?? '',
    }))
  }

  function switchToManual() {
    setSource('manual')
    setForm(f => ({ ...f, bunker_report_id: null }))
  }

  async function handleSave() {
    setError(null)
    const payload = {
      vessel_imo: imo,
      bunker_report_id: form.bunker_report_id || null,
      bdn_number: form.bdn_number || null,
      delivery_date: form.delivery_date || null,
      port: form.port || null,
      base_fuel_grade: form.base_fuel_grade,
      biofuel_type: form.biofuel_type || 'FAME Biodiesel',
      input_basis: form.input_basis,
      bio_pct: Number(form.bio_pct) || 0,
      rho_base: form.rho_base === '' ? null : Number(form.rho_base),
      rho_bio: form.rho_bio === '' ? null : Number(form.rho_bio),
      quantity_mt: Number(form.quantity_mt),
    }
    if (source === 'bunker' && !isLinked) { setError('Select a bunker report from the list, or switch to manual entry.'); return }
    if (!payload.quantity_mt || payload.quantity_mt <= 0) { setError('Total Qty (mt) must be a positive number.'); return }
    if (payload.bio_pct < 0 || payload.bio_pct > 100) { setError('Bio % must be between 0 and 100.'); return }
    if (isVol && (payload.rho_base === null || payload.rho_bio === null)) { setError('ρ Base and ρ Bio are required when Input Basis is Vol%.'); return }
    setSaving(true)
    try {
      if (isEdit) await updateBiofuelStem(initial.id, payload)
      else await createBiofuelStem(payload)
      onSaved()
    } catch (e) {
      setError(e?.response?.data?.detail ?? 'Failed to save stem.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bf-modal-backdrop" onClick={onClose}>
      <div className="bf-modal" onClick={e => e.stopPropagation()}>
        <div className="bf-modal-header">
          <span className="bf-modal-title">{isEdit ? 'Edit Bunker Stem' : 'Add Bunker Stem'}</span>
          <button className="bf-modal-close" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="bf-modal-body">
          {!isEdit && (
            <div className="bf-source-toggle">
              <button type="button" className={`bf-source-tab${source === 'bunker' ? ' active' : ''}`}
                onClick={() => setSource('bunker')} disabled={candidatesLoading || candidates.length === 0}>
                From Bunker Report {candidates.length > 0 ? `(${candidates.length})` : ''}
              </button>
              <button type="button" className={`bf-source-tab${source === 'manual' ? ' active' : ''}`} onClick={switchToManual}>
                Manual Entry
              </button>
            </div>
          )}

          {!isEdit && source === 'bunker' && (
            <div className="bf-candidate-picker">
              {candidatesLoading && <div className="bf-empty small"><Loader2 size={13} className="icon-spin" /> Loading scraped deliveries…</div>}
              {!candidatesLoading && candidates.length === 0 && (
                <div className="bf-empty small">No scraped bunker deliveries for this vessel — use Manual Entry.</div>
              )}
              {!candidatesLoading && candidates.length > 0 && (
                <select value={form.bunker_report_id || ''} onChange={e => pickCandidate(e.target.value)}>
                  <option value="">— select a delivery —</option>
                  {candidates.map(c => (
                    <option key={c.bunker_report_id} value={c.bunker_report_id}>
                      BDN {c.bdn_number || '—'} · {c.delivery_date || 'no date'} · {c.port || 'unknown port'} · {c.imo_fuel_grade || '?'} · {c.quantity_mt ?? '?'} MT
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}

          {isEdit && isLinked && (
            <div className="bf-linked-banner"><Link2 size={13} /> Linked to scraped bunker report — BDN #/Date/Port/Total Qty are read-only.</div>
          )}

          <div className="bf-form-grid">
            <label className={isLinked ? 'bf-field-inactive' : ''}>BDN #
              <input type="text" value={form.bdn_number} onChange={e => set('bdn_number', e.target.value)} disabled={isLinked} />
            </label>
            <label className={isLinked ? 'bf-field-inactive' : ''}>Date
              <input type="date" value={form.delivery_date} onChange={e => set('delivery_date', e.target.value)} disabled={isLinked} />
            </label>
            <label className={isLinked ? 'bf-field-inactive' : ''}>Port
              <input type="text" value={form.port} onChange={e => set('port', e.target.value)} disabled={isLinked} />
            </label>
            <label>Base Fuel
              <select value={form.base_fuel_grade} onChange={e => set('base_fuel_grade', e.target.value)}>
                {BASE_GRADES.map(g => <option key={g} value={g}>{g}</option>)}
              </select>
            </label>
            <label>Biofuel Type
              <select value={form.biofuel_type} onChange={e => set('biofuel_type', e.target.value)}>
                <option value="FAME Biodiesel">FAME Biodiesel</option>
              </select>
            </label>
            <label>Input Basis
              <select value={form.input_basis} onChange={e => set('input_basis', e.target.value)}>
                {INPUT_BASES.map(b => <option key={b} value={b}>{b}</option>)}
              </select>
            </label>
            <label>Bio % {isVol ? '(by volume)' : '(by mass)'}
              <input type="number" step="0.01" min="0" max="100" value={form.bio_pct} onChange={e => set('bio_pct', e.target.value)} />
            </label>
            <label className={isVol ? '' : 'bf-field-inactive'}>ρ Base (kg/m³)
              <input type="number" step="1" value={form.rho_base} onChange={e => set('rho_base', e.target.value)} placeholder="e.g. 991 (HFO)" disabled={!isVol} />
            </label>
            <label className={isVol ? '' : 'bf-field-inactive'}>ρ Bio (kg/m³)
              <input type="number" step="1" value={form.rho_bio} onChange={e => set('rho_bio', e.target.value)} placeholder="e.g. 880 (FAME)" disabled={!isVol} />
            </label>
            <label className={isLinked ? 'bf-field-inactive' : ''}>Total Qty (MT)
              <input type="number" step="0.01" value={form.quantity_mt} onChange={e => set('quantity_mt', e.target.value)} disabled={isLinked} />
            </label>
          </div>
          <p className="bf-form-hint">
            Densities from the BDN where stated; typical values: HFO ≈ 991, LFO ≈ 960, MDO ≈ 850, FAME
            biofuel ≈ 880 kg/m³. ρ columns are only used when Input Basis = Vol% — Bio % by Mass is then
            derived as (V%×ρ_bio) / ((1-V%)×ρ_base + V%×ρ_bio); with Mass%, Bio % is used as entered.
          </p>
          {error && <div className="bf-form-error"><AlertTriangle size={13} /> {error}</div>}
        </div>
        <div className="bf-modal-footer">
          <button className="bf-btn secondary" onClick={onClose}>Cancel</button>
          <button className="bf-btn" onClick={handleSave} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </div>
    </div>
  )
}

export default function BiofuelCalcPage() {
  const [vessels, setVessels] = useState([])
  const [selectedImo, setImo] = useState('')
  const [stems, setStems] = useState([])
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [modal, setModal] = useState(null) // null | 'new' | stem object

  useEffect(() => {
    fetchVessels().then(list => {
      setVessels(list)
      if (list.length > 0) {
        const saved = memoryStore.getItem('vp_last_vessel_biofuel')
        setImo(saved && list.find(v => v.imo_number === saved) ? saved : list[0].imo_number)
      }
    }).catch(console.error)
  }, [])

  const load = useCallback((imo) => {
    if (!imo) return
    setLoading(true)
    setError(null)
    fetchBiofuelStems(imo)
      .then(r => { setStems(r.stems || []); setSummary(r.summary || null) })
      .catch(e => { setError(e?.response?.data?.detail ?? 'Failed to load biofuel stems.'); setStems([]); setSummary(null) })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load(selectedImo) }, [selectedImo, load])

  async function handleDelete(id) {
    if (!window.confirm('Delete this bunker stem record? This cannot be undone.')) return
    try {
      await deleteBiofuelStem(id)
      load(selectedImo)
    } catch (e) {
      alert(e?.response?.data?.detail ?? 'Failed to delete stem.')
    }
  }

  return (
    <div className="bf-page">
      <div className="bf-topbar">
        <div className="bf-topbar-left">
          <span className="bf-title"><Droplet size={14} /> Biofuel Calc</span>
          <select
            className="bf-vessel-select"
            value={selectedImo}
            onChange={e => { setImo(e.target.value); memoryStore.setItem('vp_last_vessel_biofuel', e.target.value) }}
          >
            {vessels.map(v => <option key={v.imo_number} value={v.imo_number}>{v.vessel_name} ({v.imo_number})</option>)}
          </select>
        </div>
        <button className="bf-btn" onClick={() => setModal('new')}><Plus size={14} /> Add Stem</button>
      </div>

      <div className="bf-body">
        <div className="bf-section-title">A. Methodology <span>MEPC.1/Circ.905-Rev.1</span></div>
        <div className="bf-methodology">
          <div><b>Blended Cf:</b> Cf_blend = Σ(mᵢ × Cfᵢ) / Σ(mᵢ) — mass-weighted (biogenic Cf = 0 for CII).</div>
          <div><b>Volume vs Mass:</b> B24 = 24% by volume (industry convention); the regulation uses mass fractions — select Vol% or Mass% per BDN; a Vol% entry is converted automatically.</div>
          <div><b>FuelEU (WtW):</b> Biodiesel WtW = 16.38 vs. HFO/LFO 91.16, MDO 91.76 gCO2e/MJ — energy-weighted blend.</div>
        </div>

        {loading && <div className="bf-empty"><Loader2 size={16} className="icon-spin" /> Loading…</div>}
        {!loading && error && <div className="bf-empty error"><AlertTriangle size={13} /> {error}</div>}

        <div className="bf-section-title">B. Per-Bunker Calculations <span>one row per bunker stem (BDN)</span></div>

        {!loading && !error && stems.length === 0 && (
          <div className="bf-empty">No bunker stems logged for this vessel yet — click "Add Stem" to record one.</div>
        )}

        {!loading && !error && stems.length > 0 && (
          <div className="bf-table-wrap">
            <table className="bf-table">
              <thead>
                <tr>
                  <th title="Whether this row was linked to a real scraped bunker report, or typed by hand">Src</th>
                  <th className="bf-col-input">BDN #</th>
                  <th className="bf-col-input">Date</th>
                  <th className="bf-col-input">Port</th>
                  <th className="bf-col-input">Base Fuel</th>
                  <th className="bf-col-input">Biofuel Type</th>
                  <th className="bf-col-input">Input Basis</th>
                  <th className="bf-col-input">Bio %</th>
                  <th className="bf-col-input">ρ Base</th>
                  <th className="bf-col-input">ρ Bio</th>
                  <th className="bf-col-calc">Bio % by Mass</th>
                  <th className="bf-col-calc">Cf Base (t/t)</th>
                  <th className="bf-col-calc">Cf Blend (t/t)</th>
                  <th className="bf-col-calc">LCV Base</th>
                  <th className="bf-col-calc">LCV Bio</th>
                  <th className="bf-col-calc">WtW Base</th>
                  <th className="bf-col-calc">WtW Bio</th>
                  <th className="bf-col-calc">WtW Blend</th>
                  <th className="bf-col-input">Total Qty (MT)</th>
                  <th className="bf-col-calc">Fossil (MT)</th>
                  <th className="bf-col-calc">Bio (MT)</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {stems.map(s => (
                  <tr key={s.id}>
                    <td className="bf-src-cell" title={s.bunker_report_id ? 'Linked to a scraped bunker report' : 'Manually entered'}>
                      {s.bunker_report_id ? <Link2 size={12} /> : <span className="bf-src-manual">—</span>}
                    </td>
                    <td className="bf-col-input">{s.bdn_number || '—'}</td>
                    <td className="bf-col-input bf-dt">{s.delivery_date || '—'}</td>
                    <td className="bf-col-input">{s.port || '—'}</td>
                    <td className="bf-col-input">{s.base_fuel_grade}</td>
                    <td className="bf-col-input">{s.biofuel_type}</td>
                    <td className="bf-col-input">{s.input_basis}</td>
                    <td className="bf-col-input bf-num">{fmt(s.bio_pct, 2)}%</td>
                    <td className="bf-col-input bf-num">{s.rho_base ?? '—'}</td>
                    <td className="bf-col-input bf-num">{s.rho_bio ?? '—'}</td>
                    <td className="bf-col-calc bf-num">{fmt(s.bio_pct_by_mass, 2)}%</td>
                    <td className="bf-col-calc bf-num">{fmt(s.cf_base, 3)}</td>
                    <td className="bf-col-calc bf-num bf-highlight">{fmt(s.cf_blend, 4)}</td>
                    <td className="bf-col-calc bf-num">{fmt(s.lcv_base, 1)}</td>
                    <td className="bf-col-calc bf-num">{fmt(s.lcv_bio, 1)}</td>
                    <td className="bf-col-calc bf-num">{fmt(s.wtw_base, 2)}</td>
                    <td className="bf-col-calc bf-num">{fmt(s.wtw_bio, 2)}</td>
                    <td className="bf-col-calc bf-num bf-highlight">{fmt(s.wtw_blend, 2)}</td>
                    <td className="bf-col-input bf-num">{fmt(s.quantity_mt)}</td>
                    <td className="bf-col-calc bf-num">{fmt(s.fossil_portion_mt)}</td>
                    <td className="bf-col-calc bf-num">{fmt(s.bio_portion_mt)}</td>
                    <td className="bf-actions">
                      <button className="bf-icon-btn" onClick={() => setModal(s)} title="Edit"><Pencil size={13} /></button>
                      <button className="bf-icon-btn danger" onClick={() => handleDelete(s.id)} title="Delete"><Trash2 size={13} /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
              {summary && (
                <tfoot>
                  <tr className="bf-summary-row-tr">
                    <td colSpan={12} className="bf-summary-label">WEIGHTED AVG / TOTAL</td>
                    <td className="bf-num bf-highlight">{fmt(summary.cf_blend_avg, 4)}</td>
                    <td colSpan={4}></td>
                    <td className="bf-num bf-highlight">{fmt(summary.wtw_blend_avg, 2)}</td>
                    <td className="bf-num">{fmt(summary.total_qty_mt)}</td>
                    <td className="bf-num">{fmt(summary.total_fossil_mt)}</td>
                    <td className="bf-num">{fmt(summary.total_bio_mt)}</td>
                    <td></td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        )}

        <div className="bf-section-title">C. Quick Reference <span>regulatory notes</span></div>
        <div className="bf-refnotes">
          <div><b>MEPC.1/Circ.905-Rev.1:</b> Guidance on Cf calculation for fuel oil blends containing biofuel.</div>
          <div><b>IMO DCS:</b> Reports fuel consumption in tonnes by type/consumer/status — no Cf calculation at DCS level.</div>
          <div><b>CII/AER (Reg. 28):</b> Uses DCS data for AER = CO2/(DWT×Dist). Cf_bio = 0 for sustainable biofuel — use Cf Blend. B24 ≈ 19% CII reduction.</div>
          <div><b>EU MRV/ETS:</b> Biofuel CO2 (Cf=2.834) calculated in the IMO DCS pages — all regimes treat biogenic CO2 as zero or separate.</div>
          <div><b>FuelEU:</b> WtW approach — Biodiesel WtW = 16.38 vs HFO 91.16 gCO2e/MJ. B24 blend ≈ 19% WtW reduction — use WtW Blend.</div>
          <div><b>Sustainability:</b> Biofuel must meet EU RED II/III sustainability criteria for FuelEU WtW credit and for CII Cf_bio=0 credit.</div>
          <div><b>FAME sources:</b> UCOME (used cooking oil), TME (tallow), RME (rapeseed), SME (soybean), PME (palm) — all share Cf=2.834, LCV=37.2, WtW=16.38.</div>
        </div>

        <div className="bf-note">
          <Info size={13} />
          <span>
            This calculator prices what was bunkered per stem, exactly reproducing the Biofuel_Calc
            worksheet's formulas (see backend/emission/biofuel_calculator.py). It is not yet reconciled
            against the daily consumption figures FuelEU Maritime / EU ETS use elsewhere in this app.
          </span>
        </div>
      </div>

      {modal && (
        <StemModal
          imo={selectedImo}
          initial={modal === 'new' ? null : modal}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); load(selectedImo) }}
        />
      )}
    </div>
  )
}
