import { useState, useEffect, useCallback, useMemo } from 'react'
import { memoryStore } from '../utils/memoryStore'
import { Save, Pencil, X, CheckCircle2, AlertCircle, Loader2, AlertTriangle, FileText } from 'lucide-react'
import {
  fetchCPDescriptionVessels, fetchCPDescription,
  updateCPHeader, replaceCPSeaWarranty, replaceCPPortWarranty, updateCPConditions,
} from '../api/vesselApi'
import CPComplianceSection from '../components/CPComplianceSection'
import './CPDescriptionPage.css'

const SEA_COLS = [
  { key: 'loading_condition', label: 'Loading Cond.', type: 'text', calc: false },
  { key: 'speed_mode',        label: 'Speed Mode',    type: 'text', calc: false },
  { key: 'warranted_speed_kn',label: 'Speed (kn)',    type: 'number', calc: false },
  { key: 'me_load_pct',       label: 'ME Load (% MCR)', type: 'number', calc: false },
  { key: 'me_rpm',            label: 'ME RPM',        type: 'number', calc: false },
  { key: 'me_cons_mt_day',    label: 'ME Cons (mt/d)', type: 'number', calc: false },
  { key: 'ae_cons_mt_day',    label: 'AE Cons (mt/d)', type: 'number', calc: false },
  { key: 'boiler_cons_sea_mt_day', label: 'Boiler (mt/d)', type: 'number', calc: false },
  { key: 'total_cons_mt_day', label: 'Total (mt/d)',  type: 'number', calc: true },
  { key: 'me_fuel_grade',     label: 'Fuel Grade',    type: 'text', calc: false },
]

const PORT_COLS = [
  { key: 'port_condition',      label: 'Condition',        type: 'text', calc: false },
  { key: 'ae_cons_mt_day',      label: 'AE Cons (mt/d)',    type: 'number', calc: false },
  { key: 'boiler_cons_mt_day',  label: 'Boiler Cons (mt/d)', type: 'number', calc: false },
  { key: 'total_cons_mt_day',   label: 'Total (mt/d)',      type: 'number', calc: true },
  { key: 'fuel_grade',          label: 'Fuel Grade',        type: 'text', calc: false },
]

const HEADER_FIELDS = [
  ['vessel_name', 'Vessel Name', 'text'],
  ['vessel_type', 'Vessel Type', 'text'],
  ['dwt_summer_mt', 'Summer DWT (mt)', 'number'],
  ['year_built', 'Year Built', 'number'],
  ['me_make_model', 'Main Engine (Make/Model)', 'text'],
  ['me_mcr_kw', 'ME MCR (kW)', 'number'],
  ['me_mcr_rpm', 'ME MCR (rpm)', 'number'],
  ['me_ncr_kw', 'ME NCR (kW)', 'number'],
  ['me_ncr_rpm', 'ME NCR (rpm)', 'number'],
  ['epl_kw', 'EPL (kW)', 'number'],
  ['epl_rpm', 'EPL (rpm)', 'number'],
  ['eexi_compliance_method', 'EEXI Compliance Method', 'text'],
  ['cp_type', 'Charter Type', 'text'],
  ['cp_form', 'CP Form', 'text'],
  ['charterer_name', 'Charterer', 'text'],
  ['doc_status', 'Status', 'text'],
]

function num(v) {
  const n = parseFloat(v)
  return Number.isFinite(n) ? n : null
}

function recomputeSeaRow(row, meMcrKw) {
  const me = num(row.me_cons_mt_day) || 0
  const ae = num(row.ae_cons_mt_day) || 0
  const boiler = num(row.boiler_cons_sea_mt_day) || 0
  const meLoad = num(row.me_load_pct)
  return {
    ...row,
    total_cons_mt_day: +(me + ae + boiler).toFixed(3),
    me_shaft_power_kw: (meLoad != null && meMcrKw) ? +(meLoad * meMcrKw / 100).toFixed(1) : row.me_shaft_power_kw,
  }
}

function recomputePortRow(row) {
  const ae = num(row.ae_cons_mt_day) || 0
  const boiler = num(row.boiler_cons_mt_day) || 0
  return { ...row, total_cons_mt_day: +(ae + boiler).toFixed(3) }
}

// ── Vessel Particulars card ───────────────────────────────────────────────
function ParticularsCard({ header, editMode, onChange }) {
  return (
    <div className="cpd-card">
      <div className="cpd-card-title">
        <FileText size={13} /> 1. Vessel Particulars
        <span className="cpd-card-meta">{header.cp_id} · v{header.version_no} · {header.doc_status}</span>
      </div>
      <div className="cpd-particulars-grid">
        {HEADER_FIELDS.map(([key, label, type]) => (
          <div className="cpd-field" key={key}>
            <span className="cpd-field-label">{label}</span>
            {editMode ? (
              <input
                className="cpd-input"
                type={type}
                value={header[key] ?? ''}
                onChange={e => onChange(key, type === 'number' ? (e.target.value === '' ? null : e.target.value) : e.target.value)}
              />
            ) : (
              <span className="cpd-field-value">{header[key] ?? '—'}</span>
            )}
          </div>
        ))}
        <div className="cpd-field">
          <span className="cpd-field-label">NCR (% MCR) — calc.</span>
          <span className="cpd-field-value calc">{header.me_ncr_pct_mcr != null ? header.me_ncr_pct_mcr.toFixed(1) + '%' : '—'}</span>
        </div>
        <div className="cpd-field">
          <span className="cpd-field-label">EPL (% MCR) — calc.</span>
          <span className="cpd-field-value calc">{header.epl_pct_mcr != null ? header.epl_pct_mcr.toFixed(1) + '%' : '—'}</span>
        </div>
      </div>
      {header.source_notes && (
        <div className="cpd-source-notes">
          <AlertTriangle size={11} /> <span>{header.source_notes}</span>
        </div>
      )}
    </div>
  )
}

// ── Generic warranty table (sea / port) ──────────────────────────────────
function WarrantyTable({ title, cols, rows, editMode, onCellChange }) {
  return (
    <div className="cpd-card">
      <div className="cpd-card-title">{title}</div>
      <div className="cpd-table-wrap">
        <table className="cpd-table">
          <thead>
            <tr>{cols.map(c => <th key={c.key}>{c.label}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {cols.map(c => (
                  <td key={c.key} className={c.calc ? 'cpd-calc-cell' : ''}>
                    {editMode && !c.calc ? (
                      <input
                        className="cpd-cell-input"
                        type={c.type}
                        value={row[c.key] ?? ''}
                        onChange={e => onCellChange(i, c.key, e.target.value)}
                      />
                    ) : (
                      <span title={row.raw_value_notes || ''}>
                        {row[c.key] != null && row[c.key] !== '' ? row[c.key] : (row.raw_value_notes && c.key !== 'total_cons_mt_day' ? '⚠' : '—')}
                      </span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.some(r => r.raw_value_notes) && (
        <div className="cpd-source-notes">
          <AlertTriangle size={11} />
          <span>
            {rows.filter(r => r.raw_value_notes).map((r, i) => (
              <span key={i}>{r.raw_value_notes}{i < rows.length - 1 ? '  ' : ''}</span>
            ))}
          </span>
        </div>
      )}
    </div>
  )
}

// ── Warranty Conditions & Notes ───────────────────────────────────────────
function ConditionsCard({ conditions, editMode, onChange }) {
  if (!conditions) return null
  const exclusions = Array.isArray(conditions.exclusions) ? conditions.exclusions : []
  return (
    <div className="cpd-card">
      <div className="cpd-card-title">Warranty Conditions &amp; Notes</div>
      <div className="cpd-conditions-grid">
        <div className="cpd-field">
          <span className="cpd-field-label">Max Wind (Beaufort)</span>
          {editMode
            ? <input className="cpd-input" type="number" value={conditions.weather_max_bf ?? ''} onChange={e => onChange('weather_max_bf', e.target.value)} />
            : <span className="cpd-field-value">BF {conditions.weather_max_bf}</span>}
        </div>
        <div className="cpd-field">
          <span className="cpd-field-label">Max Sea State (Douglas)</span>
          {editMode
            ? <input className="cpd-input" type="number" value={conditions.weather_max_douglas ?? ''} onChange={e => onChange('weather_max_douglas', e.target.value)} />
            : <span className="cpd-field-value">DSS {conditions.weather_max_douglas}</span>}
        </div>
        <div className="cpd-field">
          <span className="cpd-field-label">Max Swell (m)</span>
          {editMode
            ? <input className="cpd-input" type="number" value={conditions.max_swell_m ?? ''} onChange={e => onChange('max_swell_m', e.target.value)} />
            : <span className="cpd-field-value">{conditions.max_swell_m} m</span>}
        </div>
        <div className="cpd-field">
          <span className="cpd-field-label">Hull &amp; Prop Clean Window</span>
          {editMode
            ? <input className="cpd-input" type="number" value={conditions.hull_prop_clean_months ?? ''} onChange={e => onChange('hull_prop_clean_months', e.target.value)} />
            : <span className="cpd-field-value">{conditions.hull_prop_clean_months} months</span>}
        </div>
        <div className="cpd-field">
          <span className="cpd-field-label">Evaluation Basis</span>
          <span className="cpd-field-value">{conditions.evaluation_basis}</span>
        </div>
        <div className="cpd-field">
          <span className="cpd-field-label">Fuel Spec</span>
          <span className="cpd-field-value">{conditions.fuel_spec_standard}</span>
        </div>
      </div>
      <div className="cpd-exclusions">
        <span className="cpd-field-label">Excluded Periods</span>
        <div className="cpd-chip-row">
          {exclusions.map((ex, i) => <span key={i} className="cpd-chip">{ex}</span>)}
        </div>
      </div>
      <div className="cpd-clause-basis">
        <span className="cpd-field-label">Clause Basis</span>
        <span className="cpd-field-value">{conditions.clause_basis}</span>
      </div>
      {conditions.remarks && (
        <div className="cpd-notes-block">
          {conditions.remarks.split('\n').map((line, i) => <div key={i}>• {line}</div>)}
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────
export default function CPDescriptionPage() {
  const [vessels, setVessels]     = useState([])
  const [selectedImo, setImo]     = useState('')
  const [data, setData]           = useState(null)
  const [loading, setLoading]     = useState(false)
  const [saving, setSaving]       = useState(false)
  const [editMode, setEditMode]   = useState(false)
  const [toast, setToast]         = useState(null)
  const [notFound, setNotFound]   = useState(false)

  useEffect(() => {
    fetchCPDescriptionVessels()
      .then(list => {
        setVessels(list)
        if (list.length > 0) {
          const saved = memoryStore.getItem('vp_last_vessel_cpd')
          setImo(saved && list.find(v => v.vessel_imo === saved) ? saved : list[0].vessel_imo)
        }
      })
      .catch(console.error)
  }, [])

  const loadVessel = useCallback((imo) => {
    if (!imo) return
    setLoading(true)
    setNotFound(false)
    fetchCPDescription(imo)
      .then(d => setData(d))
      .catch(() => { setData(null); setNotFound(true) })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { loadVessel(selectedImo) }, [selectedImo, loadVessel])

  function showToast(type, msg) {
    setToast({ type, msg })
    setTimeout(() => setToast(null), 3500)
  }

  function handleHeaderChange(key, value) {
    setData(prev => ({ ...prev, header: { ...prev.header, [key]: value } }))
  }
  function handleConditionsChange(key, value) {
    setData(prev => ({ ...prev, conditions: { ...prev.conditions, [key]: value } }))
  }
  function handleSeaCellChange(i, key, value) {
    setData(prev => {
      const rows = [...prev.sea_warranty]
      rows[i] = recomputeSeaRow({ ...rows[i], [key]: value }, prev.header.me_mcr_kw)
      return { ...prev, sea_warranty: rows }
    })
  }
  function handlePortCellChange(i, key, value) {
    setData(prev => {
      const rows = [...prev.port_warranty]
      rows[i] = recomputePortRow({ ...rows[i], [key]: value })
      return { ...prev, port_warranty: rows }
    })
  }

  async function handleSaveAll() {
    if (!data) return
    setSaving(true)
    try {
      const meMcr = num(data.header.me_mcr_kw)
      const headerPatch = { ...data.header }
      if (meMcr && num(data.header.me_ncr_kw)) headerPatch.me_ncr_pct_mcr = +(num(data.header.me_ncr_kw) / meMcr * 100).toFixed(2)
      if (meMcr && num(data.header.epl_kw)) headerPatch.epl_pct_mcr = +(num(data.header.epl_kw) / meMcr * 100).toFixed(2)

      const [header, sea, port, conditions] = await Promise.all([
        updateCPHeader(selectedImo, headerPatch),
        replaceCPSeaWarranty(selectedImo, data.sea_warranty.map(r => recomputeSeaRow(r, meMcr))),
        replaceCPPortWarranty(selectedImo, data.port_warranty.map(recomputePortRow)),
        updateCPConditions(selectedImo, data.conditions),
      ])
      setData({ header, sea_warranty: sea, port_warranty: port, conditions })
      setEditMode(false)
      showToast('success', 'Charter-Party description saved.')
    } catch (e) {
      showToast('error', e?.response?.data?.detail ?? 'Save failed.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="cpd-page">
      <div className="cpd-topbar">
        <div className="cpd-topbar-left">
          <span className="cpd-title">Charter-Party Description</span>
          <select
            className="cpd-vessel-select"
            value={selectedImo}
            onChange={e => {
              setImo(e.target.value)
              memoryStore.setItem('vp_last_vessel_cpd', e.target.value)
              setEditMode(false)
            }}
          >
            {vessels.map(v => (
              <option key={v.vessel_imo} value={v.vessel_imo}>{v.vessel_name} ({v.vessel_imo})</option>
            ))}
          </select>
        </div>
        <div className="cpd-topbar-actions">
          {editMode ? (
            <>
              <button className="cpd-btn cpd-btn-ghost" onClick={() => { setEditMode(false); loadVessel(selectedImo) }}>
                <X size={13} /> Cancel
              </button>
              <button className="cpd-btn cpd-btn-primary" onClick={handleSaveAll} disabled={saving}>
                {saving ? <><Loader2 size={13} className="icon-spin" /> Saving…</> : <><Save size={13} /> Save</>}
              </button>
            </>
          ) : (
            <button className="cpd-btn cpd-btn-primary" onClick={() => setEditMode(true)} disabled={!data}>
              <Pencil size={13} /> Edit
            </button>
          )}
        </div>
      </div>

      <div className="cpd-body">
        {loading && <div className="cpd-loading"><Loader2 size={20} className="icon-spin" /> Loading…</div>}
        {!loading && notFound && (
          <div className="cpd-empty">No Charter-Party description has been loaded for this vessel yet.</div>
        )}
        {!loading && data && (
          <>
            <ParticularsCard header={data.header} editMode={editMode} onChange={handleHeaderChange} />
            <WarrantyTable
              title="2. Sea Passage — Speed / Power / Consumption Warranty"
              cols={SEA_COLS}
              rows={data.sea_warranty}
              editMode={editMode}
              onCellChange={handleSeaCellChange}
            />
            <WarrantyTable
              title="3. Port / Anchorage Fuel Consumption Warranty"
              cols={PORT_COLS}
              rows={data.port_warranty}
              editMode={editMode}
              onCellChange={handlePortCellChange}
            />
            <ConditionsCard conditions={data.conditions} editMode={editMode} onChange={handleConditionsChange} />
            <CPComplianceSection imo={selectedImo} />
          </>
        )}
      </div>

      {toast && (
        <div className={`cpd-toast ${toast.type}`}>
          {toast.type === 'success' ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
          {toast.msg}
        </div>
      )}
    </div>
  )
}
