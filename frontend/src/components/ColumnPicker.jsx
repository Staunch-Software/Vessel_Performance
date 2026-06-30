import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import {
  X, Lock, Search, Eye, EyeOff, GripVertical,
  ChevronDown, ChevronRight, RotateCcw, Loader2,
} from 'lucide-react'
import {
  DndContext, closestCenter, PointerSensor, useSensor, useSensors,
} from '@dnd-kit/core'
import {
  SortableContext, verticalListSortingStrategy, useSortable, arrayMove,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { fetchExpandedColumns, reorderColumns, resetColumnOrder } from '../api/vesselApi'
import { PERFORMANCE_COLUMNS } from '../utils/performanceColumns'
import './ColumnPicker.css'

const LS_VISIBLE_KEY_PREFIX = 'vp_visible_cols_'

// Group non-identity columns by category, preserving the incoming (backend) order.
function buildOrder(cols) {
  const nonId = cols.filter(c => !c.is_identity)
  const order = []
  const map = {}
  for (const c of nonId) {
    const cat = c.category || 'Other'
    if (!map[cat]) { map[cat] = []; order.push(cat) }
    map[cat].push(c)
  }
  return order.map(cat => ({ cat, columns: map[cat] }))
}

// ── Sortable field row ──────────────────────────────────────────────────────
function SortableField({ col, isOn, locked, onToggle }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: col.db_column })
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }
  return (
    <div ref={setNodeRef} style={style}
      className={`cp-col-row${isOn ? ' on' : ''}${locked ? ' locked' : ''}`}>
      <span className="cp-drag-handle" {...attributes} {...listeners} title="Drag to reorder">
        <GripVertical size={12} />
      </span>
      <button
        className="cp-col-main"
        onClick={() => !locked && onToggle(col.db_column)}
        title={col.description || col.display_name}
      >
        <span className="cp-col-indicator">
          {locked ? <Lock size={10} className="cp-lock" />
            : isOn ? <Eye size={11} /> : <EyeOff size={11} className="cp-eye-off" />}
        </span>
        <span className="cp-col-name">{col.display_name}</span>
        {col.performance && <span className="cp-perf-dot" title="Performance column">⚡</span>}
        {col.unit && <span className="cp-col-unit">{col.unit}</span>}
      </button>
    </div>
  )
}

// ── Sortable category block ─────────────────────────────────────────────────
function SortableCategory({ group, expanded, onToggleExpand, visibleSet, onToggleField, onFieldDragEnd }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: group.cat })
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  }
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))
  const shownCount = group.columns.filter(c => c.is_active || visibleSet.has(c.db_column)).length

  return (
    <div ref={setNodeRef} style={style} className="cp-group">
      <div className="cp-group-header">
        <span className="cp-drag-handle" {...attributes} {...listeners} title="Drag to reorder category">
          <GripVertical size={13} />
        </span>
        <button className="cp-group-expand" onClick={() => onToggleExpand(group.cat)}>
          {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          <span className="cp-group-label">{group.cat}</span>
        </button>
        <span className="cp-group-count">{shownCount}/{group.columns.length}</span>
      </div>
      {expanded && (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={e => onFieldDragEnd(group.cat, e)}
        >
          <SortableContext
            items={group.columns.map(c => c.db_column)}
            strategy={verticalListSortingStrategy}
          >
            <div className="cp-col-list">
              {group.columns.map(col => (
                <SortableField
                  key={col.db_column}
                  col={col}
                  locked={col.is_active}
                  isOn={col.is_active || visibleSet.has(col.db_column)}
                  onToggle={onToggleField}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}
    </div>
  )
}

// ── Main component ──────────────────────────────────────────────────────────
export default function ColumnPicker({ pageSource, pageUserVisible, onPageToggle, onOrderChanged, onClose }) {
  const initialSource = pageSource === 'wni' ? 'wni' : 'mari_apps'
  const [src,        setSrc]       = useState(initialSource)
  const [cols,       setCols]      = useState([])
  const [order,      setOrder]     = useState([])
  const [visibleSet, setVisible]   = useState(new Set())
  const [expanded,   setExpanded]  = useState(new Set())
  const [search,     setSearch]    = useState('')
  const [saving,     setSaving]    = useState(false)
  const [loading,    setLoading]   = useState(true)
  const backdropRef = useRef(null)

  // Read latest page visibility without re-triggering column loads on every toggle
  const pageVisRef = useRef(pageUserVisible)
  useEffect(() => { pageVisRef.current = pageUserVisible }, [pageUserVisible])

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // Load columns for the picker's selected source + restore its visibility prefs
  const loadCols = useCallback(async (source) => {
    setLoading(true)
    try {
      const fetched = await fetchExpandedColumns(source)
      const withPerf = fetched.map(c => ({
        ...c, performance: c.performance || PERFORMANCE_COLUMNS.has(c.db_column),
      }))
      setCols(withPerf)
      setOrder(buildOrder(withPerf))
      if (source === pageSource) {
        setVisible(new Set(pageVisRef.current))
      } else {
        try {
          const saved = localStorage.getItem(LS_VISIBLE_KEY_PREFIX + source)
          setVisible(new Set(saved ? JSON.parse(saved) : []))
        } catch { setVisible(new Set()) }
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [pageSource])

  useEffect(() => { loadCols(src) }, [src, loadCols])

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

  // Persist the current ordering (category order + field order) to the backend
  const persist = useCallback(async (nextOrder) => {
    const list = nextOrder.flatMap(g => g.columns.map(c => c.db_column))
    setSaving(true)
    try {
      await reorderColumns(src, list)
      if (src === pageSource) onOrderChanged?.()
    } catch (e) {
      console.error(e)
    } finally {
      setSaving(false)
    }
  }, [src, pageSource, onOrderChanged])

  function handleCatDragEnd(e) {
    const { active, over } = e
    if (!over || active.id === over.id) return
    setOrder(prev => {
      const oldI = prev.findIndex(g => g.cat === active.id)
      const newI = prev.findIndex(g => g.cat === over.id)
      if (oldI < 0 || newI < 0) return prev
      const next = arrayMove(prev, oldI, newI)
      persist(next)
      return next
    })
  }

  function handleFieldDragEnd(cat, e) {
    const { active, over } = e
    if (!over || active.id === over.id) return
    setOrder(prev => {
      const next = prev.map(g => {
        if (g.cat !== cat) return g
        const oldI = g.columns.findIndex(c => c.db_column === active.id)
        const newI = g.columns.findIndex(c => c.db_column === over.id)
        if (oldI < 0 || newI < 0) return g
        return { ...g, columns: arrayMove(g.columns, oldI, newI) }
      })
      persist(next)
      return next
    })
  }

  function toggleExpand(cat) {
    setExpanded(prev => {
      const next = new Set(prev)
      next.has(cat) ? next.delete(cat) : next.add(cat)
      return next
    })
  }

  function toggleField(dbCol) {
    setVisible(prev => {
      const next = new Set(prev)
      next.has(dbCol) ? next.delete(dbCol) : next.add(dbCol)
      if (src === pageSource) {
        onPageToggle(dbCol)   // page owns localStorage + live table state for active source
      } else {
        localStorage.setItem(LS_VISIBLE_KEY_PREFIX + src, JSON.stringify([...next]))
      }
      return next
    })
  }

  async function handleReset() {
    setSaving(true)
    try {
      await resetColumnOrder(src)
      await loadCols(src)
      if (src === pageSource) onOrderChanged?.()
    } finally {
      setSaving(false)
    }
  }

  // Search results — flat list, no drag
  const searchResults = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return null
    return cols.filter(c =>
      !c.is_identity && (
        (c.display_name || '').toLowerCase().includes(q) ||
        (c.db_column || '').toLowerCase().includes(q) ||
        (c.category || '').toLowerCase().includes(q)
      )
    )
  }, [search, cols])

  const totalShown = useMemo(
    () => cols.filter(c => !c.is_identity && (c.is_active || visibleSet.has(c.db_column))).length,
    [cols, visibleSet]
  )

  return (
    <div className="cp-backdrop" ref={backdropRef}
      onClick={e => { if (e.target === backdropRef.current) onClose() }}>
      <div className="cp-panel">
        {/* Header */}
        <div className="cp-header">
          <div className="cp-title">
            <Eye size={14} />
            Column Manager
            <span className="cp-badge">{totalShown} shown</span>
            {saving && <Loader2 size={12} className="icon-spin" />}
          </div>
          <button className="cp-close" onClick={onClose}><X size={15} /></button>
        </div>

        {/* Source toggle */}
        <div className="cp-source-bar">
          <span className="cp-source-label">Source</span>
          {[['mari_apps', 'MariApps'], ['wni', 'WNI']].map(([val, label]) => (
            <button
              key={val}
              className={`cp-source-pill${src === val ? ' active' : ''}`}
              onClick={() => setSrc(val)}
            >{label}</button>
          ))}
          {src !== pageSource && (
            <span className="cp-source-note">Arranging {src === 'wni' ? 'WNI' : 'MariApps'} (not the active table)</span>
          )}
        </div>

        {/* Legend */}
        <div className="cp-legend">
          <div className="cp-legend-item"><Lock size={11} className="cp-lock" /><span>Always visible</span></div>
          <div className="cp-legend-item"><GripVertical size={11} /><span>Drag to reorder</span></div>
        </div>

        {/* Search */}
        <div className="cp-search">
          <Search size={12} />
          <input placeholder="Search columns…" value={search} onChange={e => setSearch(e.target.value)} />
          {search && <button className="cp-search-clear" onClick={() => setSearch('')}><X size={11} /></button>}
        </div>

        {/* Body */}
        <div className="cp-body">
          {loading && <div className="cp-empty"><Loader2 size={16} className="icon-spin" /> Loading…</div>}

          {!loading && searchResults && (
            <div className="cp-col-list">
              {searchResults.map(col => {
                const locked = col.is_active
                const isOn   = locked || visibleSet.has(col.db_column)
                return (
                  <button
                    key={col.db_column}
                    className={`cp-col-row cp-col-main${isOn ? ' on' : ''}${locked ? ' locked' : ''}`}
                    onClick={() => !locked && toggleField(col.db_column)}
                    title={col.description || col.display_name}
                  >
                    <span className="cp-col-indicator">
                      {locked ? <Lock size={10} className="cp-lock" />
                        : isOn ? <Eye size={11} /> : <EyeOff size={11} className="cp-eye-off" />}
                    </span>
                    <span className="cp-col-name">{col.display_name}</span>
                    {col.performance && <span className="cp-perf-dot">⚡</span>}
                    {col.unit && <span className="cp-col-unit">{col.unit}</span>}
                  </button>
                )
              })}
              {searchResults.length === 0 && <div className="cp-empty">No columns match your search.</div>}
            </div>
          )}

          {!loading && !searchResults && (
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleCatDragEnd}>
              <SortableContext items={order.map(g => g.cat)} strategy={verticalListSortingStrategy}>
                {order.map(group => (
                  <SortableCategory
                    key={group.cat}
                    group={group}
                    expanded={expanded.has(group.cat)}
                    onToggleExpand={toggleExpand}
                    visibleSet={visibleSet}
                    onToggleField={toggleField}
                    onFieldDragEnd={handleFieldDragEnd}
                  />
                ))}
                {order.length === 0 && <div className="cp-empty">No columns for this source.</div>}
              </SortableContext>
            </DndContext>
          )}
        </div>

        {/* Footer */}
        <div className="cp-footer">
          <button className="cp-reset-btn" onClick={handleReset} disabled={saving} title="Revert to the default column order">
            <RotateCcw size={12} /> Reset order
          </button>
          <span className="cp-footer-hint">Order changes save automatically</span>
        </div>
      </div>
    </div>
  )
}
