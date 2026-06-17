import { useState, useEffect, useMemo } from 'react'
import { Play, Save, Plus, Trash2, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react'
import {
  ComposedChart, Scatter, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, Legend,
} from 'recharts'
import {
  fetchVessels,
  fetchISOConfig, saveISOConfig,
  fetchBaselineCurves, saveBaselineCurve, deleteMaintenanceEvent,
  fetchMaintenanceEvents, addMaintenanceEvent,
  fetchISOKPIs, runISO19030, fetchISOSpeedLoss,
} from '../api/vesselApi'
import './ISO19030Page.css'

// ── ISO Speed Loss Chart ──────────────────────────────────────────────────────
function ISOSpeedLossChart({ rows, events = [] }) {
  const [cond, setCond] = useState('Laden')

  // Regression helper
  function linReg(pts) {
    const n = pts.length
    if (n < 4) return null
    let sx = 0, sy = 0, sxy = 0, sx2 = 0
    for (const { x, y } of pts) { sx += x; sy += y; sxy += x*y; sx2 += x*x }
    const den = n*sx2 - sx*sx
    if (!den) return null
    const m = (n*sxy - sx*sy) / den
    const b = (sy - m*sx) / n
    return x => m*x + b
  }

  const pts = useMemo(() => {
    return rows
      .filter(r => {
        const lc = (r.Loading_Cond || '').toLowerCase()
        const match = cond === 'Laden' ? lc.startsWith('l') : lc.startsWith('b')
        return match && r.Speed_Loss_pct != null && r.Date != null
      })
      .map(r => ({ x: new Date(r.Date).getTime(), y: +r.Speed_Loss_pct }))
      .filter(p => isFinite(p.x) && isFinite(p.y))
      .sort((a, b) => a.x - b.x)
  }, [rows, cond])

  const predict = useMemo(() => linReg(pts), [pts])

  const trendData = useMemo(() => {
    if (!predict || pts.length < 4) return []
    return [pts[0], pts[pts.length - 1]].map(p => ({ x: p.x, y: predict(p.x) }))
  }, [predict, pts])

  const { yMin, yMax } = useMemo(() => {
    if (!pts.length) return { yMin: -30, yMax: 20 }
    const ys = pts.map(p => p.y)
    return {
      yMin: Math.floor((Math.min(...ys) - 5) / 10) * 10,
      yMax: Math.ceil((Math.max(...ys) + 5) / 10) * 10,
    }
  }, [pts])

  // One tick per calendar month — avoids Recharts crowding labels
  const monthlyTicks = useMemo(() => {
    if (!pts.length) return []
    const ticks = []
    const d = new Date(pts[0].x)
    d.setDate(1); d.setHours(0, 0, 0, 0)
    const end = pts[pts.length - 1].x
    while (d.getTime() <= end) {
      ticks.push(d.getTime())
      d.setMonth(d.getMonth() + 1)
    }
    return ticks
  }, [pts])

  // Maintenance event reference lines
  const eventLines = useMemo(() =>
    events.map(ev => ({ x: new Date(ev.event_date).getTime(), type: ev.event_type })),
  [events])

  const fmtTick = ms => {
    const d = new Date(ms)
    const mon = d.toLocaleString('en', { month: 'short' })
    const yr  = String(d.getFullYear()).slice(2)
    return `${mon} '${yr}`
  }

  const SlTooltip = ({ active, payload }) => {
    if (!active || !payload?.[0]?.payload) return null
    const { x, y } = payload[0].payload
    return (
      <div style={{ background:'#1a2a3a', border:'1px solid #2d4a6a', padding:'7px 12px', borderRadius:4, fontSize:11 }}>
        <div style={{ color:'#94a3b8', marginBottom:3 }}>
          {new Date(x).toLocaleDateString('en-GB', { day:'2-digit', month:'short', year:'numeric' })}
        </div>
        <div style={{ color:'#e2e8f0' }}>
          ISO Speed Loss: <strong style={{ color: y > 0 ? '#f87171' : '#34d399' }}>
            {y >= 0 ? '+' : ''}{y.toFixed(2)}%
          </strong>
        </div>
      </div>
    )
  }

  if (!rows.length) return (
    <div className="iso-chart-empty">No ISO 19030 speed loss data. Run the calculation first.</div>
  )

  const dotColor = cond === 'Laden' ? '#ef4444' : '#60a5fa'

  return (
    <div className="iso-chart-wrap">
      <div className="iso-chart-header">
        <div style={{ display:'flex', border:'1px solid #2d4a6a', borderRadius:6, overflow:'hidden' }}>
          {['Laden','Ballast'].map(c => (
            <button key={c} onClick={() => setCond(c)} style={{
              padding:'3px 14px', border:'none', cursor:'pointer',
              fontFamily:'inherit', fontSize:11, fontWeight: cond===c ? 700 : 400,
              background: cond===c ? (c==='Laden' ? 'rgba(239,68,68,.15)' : 'rgba(96,165,250,.15)') : 'transparent',
              color: cond===c ? (c==='Laden' ? '#ef4444' : '#60a5fa') : '#94a3b8',
              transition:'all .12s',
            }}>{c}</button>
          ))}
        </div>
        <span style={{ fontSize:11, color:'#94a3b8', flex:1, marginLeft:12 }}>
          {cond} — ISO 19030 Power-Normalised Speed Loss % vs Date
          <span style={{ color:'#64748b' }}> · {pts.length} PASS records · vs active baseline</span>
        </span>
      </div>
      <div style={{ height:280 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart margin={{ top:12, right:24, bottom:40, left:48 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(45,74,106,.35)" />
            <XAxis dataKey="x" type="number" scale="time"
              domain={['dataMin','dataMax']} tickFormatter={fmtTick}
              ticks={monthlyTicks}
              tick={{ fill:'#94a3b8', fontSize:10, angle:-35, textAnchor:'end', dy:4 }}
              stroke="#2d4a6a" />
            <YAxis tickFormatter={v => `${v}%`} tick={{ fill:'#94a3b8', fontSize:10 }}
              stroke="#2d4a6a" domain={[yMin, yMax]} />
            <Tooltip content={<SlTooltip />} />
            <ReferenceLine y={0} stroke="rgba(148,163,184,.3)" strokeDasharray="4 4" />
            {/* Maintenance event lines */}
            {eventLines.map((ev, i) => {
              const abbr = ev.type.split(/[\s-]+/).map(w => w[0].toUpperCase()).join('')
              return (
                <ReferenceLine key={i} x={ev.x} stroke="#f59e0b" strokeDasharray="3 3"
                  label={{ value: abbr, position:'top', fill:'#f59e0b', fontSize:9, fontWeight:700 }} />
              )
            })}
            {/* Trend line first so dots render on top */}
            {trendData.length > 1 && (
              <Line data={trendData} dataKey="y" type="linear" stroke="#cbd5e1"
                strokeWidth={2} dot={false} activeDot={false}
                isAnimationActive={false} name="Linear trend" />
            )}
            <Scatter data={pts} fill={dotColor} opacity={0.85} r={4}
              name={`${cond} ISO Speed Loss`} />
            <Legend wrapperStyle={{ fontSize:10, color:'#94a3b8', paddingTop:4 }} iconSize={8} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

// ── RAG badge ─────────────────────────────────────────────────────────────────
function RagBadge({ rag }) {
  if (!rag || rag === 'grey') return <span className="rag rag-grey">—</span>
  return <span className={`rag rag-${rag}`}>{rag.toUpperCase()}</span>
}

// ── KPI card ──────────────────────────────────────────────────────────────────
function KPICard({ title, value, unit, rag, extra }) {
  return (
    <div className={`kpi-card kpi-${rag || 'grey'}`}>
      <div className="kpi-title">{title}</div>
      <div className="kpi-value">
        {value !== null && value !== undefined
          ? <><strong>{typeof value === 'number' ? value.toFixed(2) : value}</strong> <span className="kpi-unit">{unit}</span></>
          : <span className="kpi-na">No data</span>
        }
      </div>
      <RagBadge rag={rag} />
      {extra && <div className="kpi-extra">{extra}</div>}
    </div>
  )
}

// ── Baseline curve row ────────────────────────────────────────────────────────
function BaselineRow({ curve, onSave }) {
  const [vals, setVals] = useState({
    a3: curve?.a3 ?? 0, a2: curve?.a2 ?? 0,
    a1: curve?.a1 ?? '', a0: curve?.a0 ?? '',
    effective_from: curve?.effective_from ?? '',
  })
  const [saving, setSaving] = useState(false)
  const change = (k, v) => setVals(p => ({ ...p, [k]: v }))

  const save = async () => {
    setSaving(true)
    await onSave({ ...vals, generation: curve.generation, condition: curve.condition })
    setSaving(false)
  }

  return (
    <tr>
      <td className="bl-label">{curve.generation} {curve.condition}</td>
      {['a3','a2','a1','a0'].map(k => (
        <td key={k}>
          <input className="bl-input" type="number" step="any"
            value={vals[k]} onChange={e => change(k, e.target.value)} />
        </td>
      ))}
      <td>
        <input className="bl-input bl-date" type="date"
          value={vals.effective_from} onChange={e => change('effective_from', e.target.value)} />
      </td>
      <td>
        <button className="bl-save-btn" onClick={save} disabled={saving}>
          {saving ? <Loader2 size={12} className="icon-spin" /> : <Save size={12} />}
        </button>
      </td>
    </tr>
  )
}

// ── SFOC row editor ───────────────────────────────────────────────────────────
function SFOCEditor({ curve, onChange }) {
  const defaultCurve = [
    { load_pct: 25,  sfoc_gkwh: 182, lcv_kjkg: 42700 },
    { load_pct: 50,  sfoc_gkwh: 172, lcv_kjkg: 42700 },
    { load_pct: 75,  sfoc_gkwh: 168, lcv_kjkg: 42700 },
    { load_pct: 85,  sfoc_gkwh: 166, lcv_kjkg: 42700 },
    { load_pct: 100, sfoc_gkwh: 170, lcv_kjkg: 42700 },
    { load_pct: 110, sfoc_gkwh: 176, lcv_kjkg: 42700 },
  ]
  const [rows, setRows] = useState(curve || defaultCurve)

  const update = (i, k, v) => {
    const next = rows.map((r, idx) => idx === i ? { ...r, [k]: parseFloat(v) || 0 } : r)
    setRows(next)
    onChange(next)
  }

  return (
    <table className="sfoc-table">
      <thead>
        <tr><th>ME Load (%)</th><th>SFOC (g/kWh)</th><th>LCV (kJ/kg)</th></tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            <td><input className="sfoc-inp" type="number" value={r.load_pct} onChange={e => update(i, 'load_pct', e.target.value)} /></td>
            <td><input className="sfoc-inp" type="number" value={r.sfoc_gkwh} onChange={e => update(i, 'sfoc_gkwh', e.target.value)} /></td>
            <td><input className="sfoc-inp" type="number" value={r.lcv_kjkg} onChange={e => update(i, 'lcv_kjkg', e.target.value)} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function ISO19030Page() {
  const [vessels,    setVessels]   = useState([])
  const [imo,        setImo]       = useState('')
  const [dataSource, setDataSource] = useState('wni')    // 'wni' | 'mariapps'
  const [tab,        setTab]       = useState('config')  // 'config' | 'kpis'
  const [config,    setConfig]    = useState({})
  const [curves,    setCurves]    = useState([])
  const [events,    setEvents]    = useState([])
  const [kpis,          setKpis]      = useState(null)
  const [speedLossRows, setSlRows]  = useState([])
  const [loading,   setLoading]   = useState(false)
  const [running,   setRunning]   = useState(false)
  const [toast,     setToast]     = useState(null)
  const [newEvent,  setNewEvent]  = useState({ event_type: 'Dry-dock', event_date: '', notes: '' })

  // Load vessels
  useEffect(() => {
    fetchVessels().then(list => {
      setVessels(list)
      if (list.length > 0) setImo(list[0].imo_number)
    }).catch(console.error)
  }, [])

  // Load data when vessel changes
  useEffect(() => {
    if (!imo) return
    setLoading(true)
    Promise.all([
      fetchISOConfig(imo).catch(() => ({})),
      fetchBaselineCurves(imo).catch(() => []),
      fetchMaintenanceEvents(imo).catch(() => []),
    ]).then(([cfg, crv, evts]) => {
      setConfig(cfg._empty ? {} : cfg)
      // Ensure all 4 curves exist as stubs if not in DB
      const COMBOS = [
        { generation: 'B1', condition: 'Laden' },
        { generation: 'B1', condition: 'Ballast' },
        { generation: 'B2', condition: 'Laden' },
        { generation: 'B2', condition: 'Ballast' },
      ]
      const filled = COMBOS.map(c =>
        crv.find(r => r.generation === c.generation && r.condition === c.condition) || c
      )
      setCurves(filled)
      setEvents(evts)
    }).finally(() => setLoading(false))
  }, [imo])

  // Load KPIs + speed loss data when KPI tab selected or data source changes
  useEffect(() => {
    if (tab !== 'kpis' || !imo) return
    fetchISOKPIs(imo, dataSource).then(setKpis).catch(() => setKpis(null))
    fetchISOSpeedLoss(imo, 'all', 'B2', dataSource)
      .then(rows => setSlRows(rows.map(r => ({
        Date: r.Date, Speed_Loss_pct: r.Speed_Loss_pct, Loading_Cond: r.Loading_Cond
      }))))
      .catch(() => setSlRows([]))
  }, [tab, imo, dataSource])

  const cfgVal = (k, def = '') => config[k] !== undefined && config[k] !== null ? config[k] : def
  const setCfg = (k, v) => setConfig(p => ({ ...p, [k]: v === '' ? null : v }))

  const showToast = (type, msg) => {
    setToast({ type, msg })
    setTimeout(() => setToast(null), 3000)
  }

  const handleSaveConfig = async () => {
    try {
      await saveISOConfig(imo, config)
      showToast('success', 'Configuration saved.')
    } catch (e) {
      showToast('error', e?.response?.data?.detail ?? 'Save failed.')
    }
  }

  const handleSaveCurve = async (payload) => {
    try {
      const saved = await saveBaselineCurve(imo, payload)
      setCurves(prev => prev.map(c =>
        c.generation === saved.generation && c.condition === saved.condition ? saved : c
      ))
      showToast('success', `${saved.generation} ${saved.condition} baseline saved.`)
    } catch (e) {
      showToast('error', e?.response?.data?.detail ?? 'Curve save failed.')
    }
  }

  const handleAddEvent = async () => {
    if (!newEvent.event_date) { showToast('error', 'Event date is required.'); return }
    try {
      const ev = await addMaintenanceEvent(imo, newEvent)
      setEvents(prev => [ev, ...prev])
      setNewEvent({ event_type: 'Dry-dock', event_date: '', notes: '' })
      showToast('success', 'Event added.')
    } catch (e) {
      showToast('error', e?.response?.data?.detail ?? 'Add event failed.')
    }
  }

  const handleDeleteEvent = async (id) => {
    try {
      await deleteMaintenanceEvent(imo, id)
      setEvents(prev => prev.filter(e => e.id !== id))
    } catch (e) {
      showToast('error', 'Delete failed.')
    }
  }

  const handleRun = async () => {
    setRunning(true)
    try {
      const res = await runISO19030(imo, dataSource)
      showToast('success', `Done: ${res.pass} PASS, ${res.excl} EXCL, ${res.errors} errors`)
      if (tab === 'kpis') {
        const [fresh, sl] = await Promise.all([
          fetchISOKPIs(imo, dataSource),
          fetchISOSpeedLoss(imo, 'all', 'B2', dataSource),
        ])
        setKpis(fresh)
        setSlRows(sl.map(r => ({ Date: r.Date, Speed_Loss_pct: r.Speed_Loss_pct, Loading_Cond: r.Loading_Cond })))
      }
    } catch (e) {
      showToast('error', e?.response?.data?.detail ?? 'Run failed.')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="iso-page">

      {/* ── Top bar ─────────────────────────────────────────────────────── */}
      <div className="iso-topbar">
        <span className="iso-title">ISO 19030 <span className="iso-sub">Performance Analysis</span></span>
        <select className="iso-vessel-sel" value={imo} onChange={e => setImo(e.target.value)}>
          {vessels.map(v => <option key={v.imo_number} value={v.imo_number}>{v.vessel_name}</option>)}
        </select>
        <div className="iso-tabs">
          {[['config','Configuration'], ['kpis','KPI Dashboard']].map(([id, label]) => (
            <button key={id} className={`iso-tab${tab === id ? ' active' : ''}`}
              onClick={() => setTab(id)}>{label}</button>
          ))}
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:6, marginLeft:8 }}>
          <span style={{ fontSize:11, color:'#64748b' }}>Source:</span>
          <div style={{ display:'flex', border:'1px solid #2d4a6a', borderRadius:6, overflow:'hidden' }}>
            {['wni','mariapps'].map(src => (
              <button key={src} onClick={() => setDataSource(src)} style={{
                padding:'3px 10px', border:'none', cursor:'pointer',
                fontFamily:'inherit', fontSize:11, fontWeight: dataSource===src ? 700 : 400,
                background: dataSource===src ? 'rgba(96,165,250,.2)' : 'transparent',
                color: dataSource===src ? '#60a5fa' : '#64748b',
                transition:'all .12s', textTransform:'uppercase',
              }}>{src}</button>
            ))}
          </div>
        </div>
        <button className="iso-run-btn" onClick={handleRun} disabled={running || !imo}>
          {running
            ? <><Loader2 size={13} className="icon-spin" /> Running…</>
            : <><Play size={13} /> Run ISO 19030</>}
        </button>
      </div>

      {loading && <div className="iso-loading"><Loader2 size={18} className="icon-spin" /> Loading…</div>}

      {/* ── Config tab ──────────────────────────────────────────────────── */}
      {!loading && tab === 'config' && (
        <div className="iso-body">

          {/* Section 1: Vessel Particulars */}
          <section className="iso-section">
            <h3 className="iso-section-title">Vessel Particulars <span className="iso-src">(from Sea Trial / Spec Sheet)</span></h3>
            <div className="iso-grid">
              {[
                ['lpp_m',              'Lpp (m)',                     185],
                ['breadth_m',          'Breadth B (m)',               30.5],
                ['block_coeff_cb',     'Block coefficient Cb',        0.82],
                ['transverse_area_m2', 'Transverse area A_T (m²)',    780],
                ['propeller_pitch_m',  'Propeller pitch (m)',         4.2],
                ['propulsive_eff_eta_d','Propulsive efficiency η_D',  0.70],
                ['shaft_eff_eta_shaft', 'Shaft efficiency η_shaft',   0.98],
                ['rho_ref_kgm3',       'Reference seawater ρ_ref (kg/m³)', 1025],
              ].map(([k, label, placeholder]) => (
                <div key={k} className="iso-field">
                  <label className="iso-label">{label}</label>
                  <input className="iso-input" type="number" step="any"
                    placeholder={placeholder}
                    value={cfgVal(k)} onChange={e => setCfg(k, e.target.value)} />
                </div>
              ))}
            </div>
          </section>

          {/* Section 2: SFOC Curve */}
          <section className="iso-section">
            <h3 className="iso-section-title">Shop-Trial SFOC Curve <span className="iso-src">(for fuel-derived power)</span></h3>
            <SFOCEditor
              curve={config.sfoc_curve}
              onChange={curve => setCfg('sfoc_curve', curve)}
            />
          </section>

          {/* Section 3: Reference Baseline Curves */}
          <section className="iso-section">
            <h3 className="iso-section-title">Reference Baseline Curves
              <span className="iso-src"> V_exp = (a3×10⁻¹²)P³ + (a2×10⁻⁸)P² + (a1×10⁻³)P + a0  (P in kW, V in kn)</span>
            </h3>
            <div className="iso-grid-2">
              <div className="iso-field">
                <label className="iso-label">Reference displacement LADEN (t)</label>
                <input className="iso-input" type="number" value={cfgVal('ref_displacement_laden_t')}
                  placeholder="e.g. 57000" onChange={e => setCfg('ref_displacement_laden_t', e.target.value)} />
              </div>
              <div className="iso-field">
                <label className="iso-label">Reference displacement BALLAST (t)</label>
                <input className="iso-input" type="number" value={cfgVal('ref_displacement_ballast_t')}
                  placeholder="e.g. 31700" onChange={e => setCfg('ref_displacement_ballast_t', e.target.value)} />
              </div>
              <div className="iso-field">
                <label className="iso-label">Condition split: ballast if mean draft ≤ (m)</label>
                <input className="iso-input" type="number" value={cfgVal('condition_split_draft_m', 8.5)}
                  onChange={e => setCfg('condition_split_draft_m', e.target.value)} />
              </div>
              <div className="iso-field">
                <label className="iso-label">Active baseline generation</label>
                <select className="iso-input iso-select" value={cfgVal('active_baseline', 'B2')}
                  onChange={e => setCfg('active_baseline', e.target.value)}>
                  <option value="B1">B1 — Sea Trial</option>
                  <option value="B2">B2 — Post Dry-Dock</option>
                </select>
              </div>
            </div>
            <table className="bl-table">
              <thead>
                <tr>
                  <th>Curve</th>
                  <th>a3 (×10⁻¹²)</th>
                  <th>a2 (×10⁻⁸)</th>
                  <th>a1 (×10⁻³)</th>
                  <th>a0 (offset)</th>
                  <th>Effective from</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {curves.map(c => (
                  <BaselineRow key={`${c.generation}-${c.condition}`}
                    curve={c} onSave={handleSaveCurve} />
                ))}
              </tbody>
            </table>
          </section>

          {/* Section 4: Filter Settings */}
          <section className="iso-section">
            <h3 className="iso-section-title">Filter Settings & Thresholds
              <span className="iso-src"> (ISO 19030 defaults pre-filled)</span>
            </h3>
            <div className="iso-grid">
              {[
                ['wind_filter_ms',        'Wind filter max V_wind_rel (m/s)',  5.5],
                ['wave_hs_max_m',         'Sea-state filter max Hs (m)',        2],
                ['depth_draft_ratio_min', 'Depth/draft min ratio',              6],
                ['rudder_max_deg',        'Rudder filter max (deg)',             5],
                ['rot_max_degmin',        'Rate-of-turn max (deg/min)',         10],
                ['loading_window_pct',    'Loading window ± (%)',                5],
                ['c_aa',                  'Wind drag coeff C_AA',              0.8],
                ['c_aw',                  'Wave form coeff C_AW',             0.55],
                ['maintenance_trigger_pct','Maintenance trigger (% speed loss)',8],
                ['amber_slope_pct30d',    'In-service amber slope (%/30d)',    0.5],
                ['red_slope_pct30d',      'In-service red slope (%/30d)',        1],
                ['rolling_window_records','Rolling window size (records)',        7],
              ].map(([k, label, placeholder]) => (
                <div key={k} className="iso-field">
                  <label className="iso-label">{label}</label>
                  <input className="iso-input" type="number" step="any"
                    placeholder={placeholder}
                    value={cfgVal(k)} onChange={e => setCfg(k, e.target.value)} />
                </div>
              ))}
            </div>
          </section>

          {/* Section 5: Maintenance Events */}
          <section className="iso-section">
            <h3 className="iso-section-title">Dry-Dock & Maintenance Events</h3>
            {/* Add new event */}
            <div className="ev-add-row">
              <select className="iso-input iso-select ev-type"
                value={newEvent.event_type}
                onChange={e => setNewEvent(p => ({ ...p, event_type: e.target.value }))}>
                <option>Dry-dock</option>
                <option>Hull clean</option>
                <option>Prop polish</option>
              </select>
              <input className="iso-input ev-date" type="date"
                value={newEvent.event_date}
                onChange={e => setNewEvent(p => ({ ...p, event_date: e.target.value }))} />
              <input className="iso-input ev-notes" type="text" placeholder="Notes (optional)"
                value={newEvent.notes}
                onChange={e => setNewEvent(p => ({ ...p, notes: e.target.value }))} />
              <button className="ev-add-btn" onClick={handleAddEvent}>
                <Plus size={13} /> Add
              </button>
            </div>
            {/* Event list */}
            <table className="ev-table">
              <thead><tr><th>Event</th><th>Date</th><th>Notes</th><th></th></tr></thead>
              <tbody>
                {events.length === 0
                  ? <tr><td colSpan={4} className="ev-empty">No events recorded</td></tr>
                  : events.map(ev => (
                    <tr key={ev.id}>
                      <td><span className={`ev-badge ev-${ev.event_type.replace(/\s/g,'-').toLowerCase()}`}>{ev.event_type}</span></td>
                      <td>{ev.event_date}</td>
                      <td>{ev.notes || '—'}</td>
                      <td>
                        <button className="ev-del-btn" onClick={() => handleDeleteEvent(ev.id)}>
                          <Trash2 size={12} />
                        </button>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </section>

          <div className="iso-save-bar">
            <button className="iso-save-btn" onClick={handleSaveConfig}>
              <Save size={13} /> Save Configuration
            </button>
          </div>
        </div>
      )}

      {/* ── KPI Dashboard tab ────────────────────────────────────────────── */}
      {!loading && tab === 'kpis' && (
        <div className="iso-body">
          {kpis === null ? (
            <div className="iso-loading"><Loader2 size={18} className="icon-spin" /> Loading KPIs…</div>
          ) : (
            <>
              <div className="kpi-meta">
                {kpis.meta?.total_pass_records} PASS records ·
                {kpis.meta?.date_from} to {kpis.meta?.date_to}
              </div>

              {/* Summary metric — matches Excel "Current avg speed loss (B2, PASS pts)" */}
              {kpis.summary_avg_speed_loss?.value != null && (
                <div className={`kpi-summary-bar kpi-${kpis.summary_avg_speed_loss.rag}`}>
                  <span className="kpi-summary-label">
                    {kpis.summary_avg_speed_loss.label}
                  </span>
                  <span className="kpi-summary-value">
                    <strong>{kpis.summary_avg_speed_loss.value?.toFixed(2)}%</strong>
                  </span>
                  <RagBadge rag={kpis.summary_avg_speed_loss.rag} />
                  <span className="kpi-summary-note">{kpis.summary_avg_speed_loss.note}</span>
                </div>
              )}

              <div className="kpi-grid">
                <KPICard
                  title="Dry-Docking Performance"
                  value={kpis.kpi1_dry_docking?.value}
                  unit={kpis.kpi1_dry_docking?.unit}
                  rag={kpis.kpi1_dry_docking?.rag}
                  extra="Avg speed loss: current DD interval vs previous"
                />
                <KPICard
                  title="In-Service Performance"
                  value={kpis.kpi2_in_service?.value}
                  unit={kpis.kpi2_in_service?.unit}
                  rag={kpis.kpi2_in_service?.rag}
                  extra="Degradation rate since last dry-dock"
                />
                <KPICard
                  title="Maintenance Trigger"
                  value={kpis.kpi3_trigger?.triggered ? 'YES — Clean now' : 'NO — OK'}
                  unit=""
                  rag={kpis.kpi3_trigger?.triggered ? 'red' : 'green'}
                  extra={kpis.kpi3_trigger?.value != null
                    ? `Rolling avg: ${kpis.kpi3_trigger.value?.toFixed(2)}%`
                    : 'Insufficient data'}
                />
                <KPICard
                  title="Maintenance Effect"
                  value={kpis.kpi4_effect?.value}
                  unit={kpis.kpi4_effect?.unit}
                  rag={kpis.kpi4_effect?.value > 0 ? 'green'
                       : kpis.kpi4_effect?.value < -2 ? 'red' : 'amber'}
                  extra={kpis.kpi4_effect?.event_type
                    ? `Last: ${kpis.kpi4_effect.event_type} on ${kpis.kpi4_effect.event_date}`
                    : 'No maintenance events'}
                />
              </div>
              <div className="kpi-note">
                Negative speed loss = vessel slower than baseline (hull/propeller degradation).
                Run ISO 19030 calculation first to populate results.
              </div>

              {/* ── ISO Speed Loss Chart ─────────────────────────── */}
              <div className="kpi-chart-section">
                <div className="kpi-chart-title">
                  ISO 19030 Speed Loss % vs Date
                  <span className="kpi-chart-sub"> (weather-filtered PASS records · vs B2 baseline)</span>
                </div>
                <ISOSpeedLossChart rows={speedLossRows} events={events} />
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Toast ────────────────────────────────────────────────────────── */}
      {toast && (
        <div className={`iso-toast ${toast.type}`}>
          {toast.type === 'success' ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
          {toast.msg}
        </div>
      )}
    </div>
  )
}
