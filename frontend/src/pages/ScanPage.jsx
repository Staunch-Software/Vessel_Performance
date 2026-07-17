import { useState, useEffect, useMemo, useRef } from 'react'
import { memoryStore } from '../utils/memoryStore'

import { Search, Loader2, ScanSearch, SearchX, X, Zap, BookmarkPlus, Check, ChevronRight } from 'lucide-react'
import { fetchVessels, fetchExpandedColumns, runScan } from '../api/vesselApi'
import { saveReport } from '../utils/savedReports'
import './ScanPage.css'

// ── Operator button groups ────────────────────────────────────────────────────
const OP_GROUPS = [
  { key: 'compare', label: 'Compare', ops: [
    { label: '<',  ins: ' < '  },
    { label: '≤',  ins: ' <= ' },
    { label: '>',  ins: ' > '  },
    { label: '≥',  ins: ' >= ' },
    { label: '=',  ins: ' = '  },
    { label: '≠',  ins: ' != ' },
  ]},
  { key: 'logic', label: 'Logic', ops: [
    { label: 'AND',     ins: ' AND '     },
    { label: 'OR',      ins: ' OR '      },
    { label: 'NOT',     ins: ' NOT '     },
  ]},
  { key: 'group', label: 'Group', ops: [
    { label: '(', ins: '(' },
    { label: ')', ins: ')' },
  ]},
  { key: 'range', label: 'Range', ops: [
    { label: 'BETWEEN', ins: ' BETWEEN ' },
  ]},
  { key: 'math', label: 'Math', ops: [
    { label: '+', ins: ' + ' },
    { label: '−', ins: ' - ' },
    { label: '×', ins: ' * ' },
    { label: '÷', ins: ' / ' },
  ]},
]

function fmt(v) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (isNaN(n)) return v
  return Number.isInteger(n) ? n : n.toFixed(2)
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function ScanPage({ preload, onPreloadConsumed }) {
  const [vessels,     setVessels]   = useState([])
  const [vesselImo,   setVesselImo] = useState(() => memoryStore.getItem('vp_last_vessel_scan') || '')
  const [source,      setSource]    = useState(() => memoryStore.getItem('vp_scan_source') || 'wni')   // 'wni' | 'mariapps'

  useEffect(() => { memoryStore.setItem('vp_scan_source', source) }, [source])
  const [columnsMeta, setColsMeta]  = useState([])
  const [colsLoading, setColsLoading] = useState(false)
  const [expression,  setExpression] = useState('')
  const [openCats,    setOpenCats]   = useState({})
  const [results,     setResults]    = useState([])
  const [loading,     setLoading]    = useState(false)
  const [error,       setError]      = useState(null)
  const [ran,         setRan]        = useState(false)
  const [reportName,  setRepName]    = useState('')
  const [saveError,   setSaveErr]    = useState(null)
  const [saved,       setSaved]      = useState(false)
  const taRef = useRef(null)

  useEffect(() => { fetchVessels().then(setVessels).catch(console.error) }, [])

  // Load column metadata when source changes
  useEffect(() => {
    setColsLoading(true)
    setOpenCats({})
    fetchExpandedColumns(source === 'mariapps' ? 'mari_apps' : 'wni')
      .then(setColsMeta)
      .catch(console.error)
      .finally(() => setColsLoading(false))
  }, [source])

  // Non-identity columns grouped by category (sorted)
  const categories = useMemo(() => {
    const cats = [...new Set(
      columnsMeta.filter(c => !c.is_identity).map(c => c.category || 'Other')
    )].sort((a, b) => a.localeCompare(b))
    return cats
  }, [columnsMeta])

  const fieldsByCategory = useMemo(() => {
    const map = {}
    for (const c of columnsMeta) {
      if (c.is_identity) continue
      const cat = c.category || 'Other'
      if (!map[cat]) map[cat] = []
      map[cat].push(c)
    }
    return map
  }, [columnsMeta])

  // db_column → display_name lookup
  const colLabel = useMemo(() => {
    const m = {}
    for (const c of columnsMeta) m[c.db_column] = c.display_name
    return m
  }, [columnsMeta])

  // Identity columns from metadata (context cols in result table)
  const identityCols = useMemo(() =>
    columnsMeta.filter(c => c.is_identity),
  [columnsMeta])

  // db_columns mentioned in expression
  const scannedKeys = useMemo(() => {
    if (!expression) return []
    return columnsMeta
      .filter(c => !c.is_identity && expression.includes(c.db_column))
      .map(c => c.db_column)
  }, [expression, columnsMeta])

  // All result-table columns: identity + scanned non-identity
  const allCols = useMemo(() => {
    const identSet = new Set(identityCols.map(c => c.db_column))
    const extras = scannedKeys.filter(k => !identSet.has(k))
    return [
      ...identityCols.map(c => ({ key: c.db_column, label: c.display_name })),
      ...extras.map(k => ({ key: k, label: colLabel[k] || k })),
    ]
  }, [identityCols, scannedKeys, colLabel])

  // ── Insert text at cursor position ────────────────────────────────────────
  function insertAt(text) {
    const ta = taRef.current
    if (!ta) { setExpression(prev => (prev ? prev.trimEnd() + text : text)); return }
    ta.focus()
    const start = ta.selectionStart
    const end   = ta.selectionEnd
    const before = expression.slice(0, start)
    const after  = expression.slice(end)
    // Only add leading space if needed (operator strings already have spaces)
    const sep = before.length > 0 && !before.endsWith(' ') && !text.startsWith(' ') ? ' ' : ''
    const ins = sep + text
    setExpression(before + ins + after)
    requestAnimationFrame(() => {
      ta.focus()
      const p = start + ins.length
      ta.setSelectionRange(p, p)
    })
  }

  function deleteLastToken() {
    setExpression(prev => prev.trimEnd().replace(/\s*\S+$/, ''))
  }

  function toggleCat(cat) {
    setOpenCats(prev => ({ ...prev, [cat]: !prev[cat] }))
  }

  // ── Run ───────────────────────────────────────────────────────────────────
  async function handleRunWith(expr, imo, src) {
    setError(null)
    setLoading(true)
    setRan(false)
    const trimmed = (expr || '').trim()
    if (!trimmed) {
      setError('Enter a query expression first.')
      setLoading(false)
      return
    }
    try {
      const data = await runScan({
        expression: trimmed,
        source: src || 'wni',
        ...(imo && { vessel_imo: imo }),
      })
      setResults(data)
      setRan(true)
    } catch (e) {
      setError(e?.response?.data?.detail ?? e.message ?? 'Scan failed')
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  const handleRun = () => handleRunWith(expression, vesselImo, source)

  function handleClear() {
    setExpression('')
    setResults([])
    setError(null)
    setRan(false)
    setVesselImo('')
    setRepName('')
    setSaveErr(null)
  }

  // Sync vesselImo to memoryStore whenever it changes
  useEffect(() => {
    memoryStore.setItem('vp_last_vessel_scan', vesselImo)
  }, [vesselImo])

  // ── Preload from Vessel Reports ───────────────────────────────────────────
  useEffect(() => {
    if (!preload) return
    const { savedReport, vesselImo: pImo, editMode } = preload
    setExpression(savedReport.expression || '')
    setVesselImo(pImo || '')
    setRepName(savedReport.name)
    setRan(false)
    setResults([])
    setError(null)
    if (!editMode) {
      handleRunWith(savedReport.expression, pImo || '', source)
    }
    onPreloadConsumed?.()
  }, [preload]) // eslint-disable-line

  // ── Save report ───────────────────────────────────────────────────────────
  function handleSave() {
    setSaveErr(null)
    const name = reportName.trim()
    if (!name) { setSaveErr('Enter a report name.'); return }
    const expr = expression.trim()
    if (!expr) { setSaveErr('Write an expression first.'); return }
    saveReport({ name, expression: expr, vesselImo, source })
    setRepName('')
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="scan-page">

      <div className="scan-header">
        <div className="scan-header-title"><Zap size={14} /> Vessel Scan</div>
        <div className="scan-header-sub">Build a custom query expression to scan vessel performance data</div>
      </div>

      <div className="scan-body">

        {/* ── Query builder panel ── */}
        <div className="qb-panel">

          {/* Top row: filters + actions */}
          <div className="qb-toprow">
            <div className="qb-filters">
              <select className="scan-select" value={vesselImo} onChange={e => {
                setVesselImo(e.target.value);
              }}>
                <option value="">All Vessels</option>
                {vessels.map(v => (
                  <option key={v.imo_number} value={v.imo_number}>{v.vessel_name}</option>
                ))}
              </select>
              {/* Source toggle */}
              <div style={{ display:'flex', border:'1px solid #2d4a6a', borderRadius:5, overflow:'hidden' }}>
                {[['wni','WNI'],['mariapps','MariApps']].map(([val, label]) => (
                  <button key={val} onClick={() => setSource(val)} style={{
                    padding:'4px 12px', border:'none', cursor:'pointer',
                    fontFamily:'inherit', fontSize:11, fontWeight: source===val ? 700 : 400,
                    background: source===val ? 'rgba(56,189,248,.18)' : 'transparent',
                    color: source===val ? '#38bdf8' : '#64748b',
                    transition:'all .12s',
                  }}>{label}</button>
                ))}
              </div>
            </div>

            <div className="qb-actions">
              <button className="run-scan-btn" onClick={handleRun} disabled={loading}>
                {loading
                  ? <><Loader2 size={13} className="icon-spin" /> Scanning…</>
                  : <><Search size={13} /> Run Scan</>}
              </button>
              <button className="scan-clear-btn" onClick={handleClear}>Clear All</button>
              <div className="save-report-group">
                <input className="save-report-input" placeholder="Report name…"
                  value={reportName}
                  onChange={e => { setRepName(e.target.value); setSaveErr(null) }}
                  onKeyDown={e => e.key === 'Enter' && handleSave()}
                  maxLength={80} />
                <button className={`save-report-btn${saved ? ' saved' : ''}`}
                  onClick={handleSave} disabled={saved}>
                  {saved
                    ? <><Check size={13} /> Saved!</>
                    : <><BookmarkPlus size={13} /> Save</>}
                </button>
                {saveError && <span className="save-report-err">{saveError}</span>}
              </div>
              {ran && !loading && (
                <span className="scan-result-count">
                  <strong>{results.length}</strong> record{results.length !== 1 ? 's' : ''}
                  {results.length === 500 && ' (limit)'}
                </span>
              )}
            </div>
          </div>

          {/* Operator buttons */}
          <div className="qb-opbar">
            {OP_GROUPS.map(group => (
              <div key={group.key} className="qb-opgroup">
                <span className="qb-opgroup-label">{group.label}</span>
                {group.ops.map(op => (
                  <button key={op.label} className="qb-op" onClick={() => insertAt(op.ins)}>
                    {op.label}
                  </button>
                ))}
              </div>
            ))}
            <div className="qb-opgroup qb-opgroup-util">
              <button className="qb-op qb-op-del" onClick={deleteLastToken} title="Delete last token">⌫</button>
              <button className="qb-op qb-op-clr" onClick={() => setExpression('')} title="Clear expression">✕</button>
            </div>
          </div>

          {/* Query textarea */}
          <div className="qb-textarea-wrap">
            <textarea
              ref={taRef}
              className="qb-textarea"
              value={expression}
              onChange={e => setExpression(e.target.value)}
              placeholder={"Click a field below, then use operator buttons to build your query…\nExample:  Speed_Loss_pct <= -5 AND Sig_Wave_Ht_m < 2"}
              spellCheck={false}
              rows={3}
              onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) handleRun() }}
            />
            {expression && (
              <span className="qb-fields-hint">
                {scannedKeys.length} field{scannedKeys.length !== 1 ? 's' : ''} referenced
                &nbsp;·&nbsp; Ctrl+Enter to run
              </span>
            )}
          </div>

          {/* Category accordions — driven by DB metadata */}
          <div className="qb-fields">
            {colsLoading ? (
              <div style={{ padding:'14px', color:'#64748b', fontSize:12 }}>
                <Loader2 size={12} className="icon-spin" style={{ marginRight:6 }} />
                Loading fields…
              </div>
            ) : (
              <>
                <div className="qb-fields-title">
                  Fields ({source.toUpperCase()}) — click a field to insert it into the query
                </div>
                {categories.map(cat => (
                  <div key={cat} className={`qb-accordion${openCats[cat] ? ' open' : ''}`}>
                    <button className="qb-cat-header" onClick={() => toggleCat(cat)}>
                      <ChevronRight size={11} className={`qb-chevron${openCats[cat] ? ' rotated' : ''}`} />
                      <span className="qb-cat-name">{cat}</span>
                      <span className="qb-cat-count">{(fieldsByCategory[cat] || []).length}</span>
                    </button>
                    {openCats[cat] && (
                      <div className="qb-fields-row">
                        {(fieldsByCategory[cat] || []).map(f => (
                          <button
                            key={f.db_column}
                            className={`qb-field-chip${scannedKeys.includes(f.db_column) ? ' used' : ''}`}
                            onClick={() => insertAt(f.db_column)}
                            title={f.db_column}
                          >
                            {f.display_name}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </>
            )}
          </div>

        </div>

        {/* Error banner */}
        {error && (
          <div className="scan-error-bar"><X size={13} /> {error}</div>
        )}

        {/* Results */}
        <div className="scan-results">
          <div className="scan-results-header">
            Results
            {ran && !loading && ` — ${results.length} record${results.length !== 1 ? 's' : ''} matched`}
          </div>
          <div className="scan-results-table-wrap">
            {!ran && !loading ? (
              <div className="scan-empty">
                <span className="scan-empty-icon"><ScanSearch size={32} strokeWidth={1.2} /></span>
                Build a query above and click <strong>Run Scan</strong>
              </div>
            ) : loading ? (
              <div className="scan-empty">
                <span className="scan-empty-icon icon-spin"><Loader2 size={32} strokeWidth={1.5} /></span>
                Running scan…
              </div>
            ) : results.length === 0 ? (
              <div className="scan-empty">
                <span className="scan-empty-icon"><SearchX size={32} strokeWidth={1.2} /></span>
                No records matched your query
              </div>
            ) : (
              <ScanResultsTable rows={results} scannedKeys={scannedKeys} allCols={allCols} />
            )}
          </div>
        </div>

      </div>
    </div>
  )
}

// ── Results table (also exported for other pages) ─────────────────────────────
export function ScanResultsTable({ rows, scannedKeys, allCols }) {
  return (
    <table className="scan-table">
      <thead>
        <tr>
          {allCols.map(col => (
            <th key={col.key} className={scannedKeys.includes(col.key) ? 'highlight' : ''}>
              {col.label}
              {scannedKeys.includes(col.key) && <span style={{ marginLeft:4, fontSize:9, opacity:0.7 }}>▲</span>}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i}>
            {allCols.map(col => {
              const v = row[col.key]
              const isDate = col.key === 'date' || col.key === 'log_date'
              return (
                <td key={col.key} className={scannedKeys.includes(col.key) ? 'highlight' : ''}>
                  {isDate && v ? String(v).slice(0, 10) : fmt(v)}
                </td>
              )
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
