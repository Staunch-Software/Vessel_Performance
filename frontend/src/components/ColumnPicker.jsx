import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { memoryStore } from '../utils/memoryStore'

import {
  X, Lock, Search, Eye, EyeOff, GripVertical,
  ChevronDown, ChevronRight, RotateCcw, Loader2, CheckSquare, Square,
  Shield, Columns
} from 'lucide-react'
import {
  DndContext, closestCenter, PointerSensor, useSensor, useSensors,
} from '@dnd-kit/core'
import {
  SortableContext, verticalListSortingStrategy, useSortable, arrayMove,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { 
  fetchExpandedColumns, reorderColumns, resetColumnOrder,
  fetchUserColumnPrefs, saveUserColumnPrefs,
  fetchVesselColumnDefaults, saveVesselColumnDefaults
} from '../api/vesselApi'
import { PERFORMANCE_COLUMNS } from '../utils/performanceColumns'
import './ColumnPicker.css'

const LS_VISIBLE_KEY_PREFIX = 'vp_visible_cols_'

// Group non-identity columns by category, preserving the incoming (backend) order.
function buildOrder(cols) {
  const nonId = cols.filter(c => !c.is_identity)
  const order = []
  const map = {}
  for (const c of nonId) {
    const cat = c.performance ? 'Performance' : (c.category || 'Other')
    if (!map[cat]) { map[cat] = []; order.push(cat) }
    map[cat].push(c)
  }
  
  // Ensure 'Performance' is at the top and always exists
  if (!map['Performance']) {
    map['Performance'] = [];
    order.push('Performance');
  }
  const finalOrder = order.includes('Performance') 
    ? ['Performance', ...order.filter(c => c !== 'Performance')] 
    : order;
    
  return finalOrder.map(cat => ({ cat, columns: map[cat] }))
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
        onClick={() => onToggle(col.db_column)}
        title={col.description || col.display_name}
      >
        <span className="cp-col-indicator">
          {isOn ? <CheckSquare size={13} color="var(--accent-2)" /> : <Square size={13} color="var(--text-muted)" style={{ opacity: 0.5 }} />}
        </span>
        <span className="cp-col-name">{String((col.display_name && col.display_name.trim() !== '') ? col.display_name : (col.db_column || 'Unknown'))}</span>
        {col.performance && <span className="cp-perf-dot" title="Performance column">⚡</span>}
        {col.unit && <span className="cp-col-unit">{col.unit}</span>}
      </button>
    </div>
  )
}

// ── Sortable category block ─────────────────────────────────────────────────
function SortableCategory({ group, expanded, onToggleExpand, visibleSet, onToggleField, onFieldDragEnd, onGroupAction }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: group.cat })
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  }
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))
  const shownCount = group.columns.filter(c => visibleSet.has(c.db_column)).length

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
        <div style={{ display: 'flex', gap: '6px', marginLeft: 'auto', marginRight: '8px' }}>
          <button className="cp-action-btn" onClick={(e) => { e.stopPropagation(); onGroupAction(group, 'default') }}>Default</button>
          <button className="cp-action-btn" onClick={(e) => { e.stopPropagation(); onGroupAction(group, 'all') }}>All</button>
        </div>
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
                  isOn={visibleSet.has(col.db_column)}
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
export default function ColumnPicker({ 
  pageSource, 
  pageUserVisible, 
  pageVesselDefaults,
  vesselImo,
  vesselName,
  currentUser,
  onPageSetVisible, 
  onOrderChanged, 
  onClose,
  onAdminDefaultsChanged,
  modeIsAdmin,
  onModeChange
}) {
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

  const isAdmin = currentUser?.role === 'admin'

  // Read latest page visibility without re-triggering column loads on every toggle
  const pageVisRef = useRef(pageUserVisible)
  const pageDefaultsRef = useRef(pageVesselDefaults)
  useEffect(() => { pageVisRef.current = pageUserVisible }, [pageUserVisible])
  useEffect(() => { pageDefaultsRef.current = pageVesselDefaults }, [pageVesselDefaults])

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // Load columns for the picker's selected source + restore its visibility prefs
  const loadCols = useCallback(async (source, modeIsAdmin) => {
    setLoading(true)
    try {
      const fetched = await fetchExpandedColumns(source)
      const perfColsLower = new Set([...PERFORMANCE_COLUMNS].map(c => c.toLowerCase()))
      const withPerf = fetched.map(c => ({
        ...c, performance: c.performance || PERFORMANCE_COLUMNS.has(c.db_column) || perfColsLower.has((c.db_column || '').toLowerCase()),
      }))
      
      let finalCols = withPerf
      let activeVisible = new Set()

      if (source === pageSource) {
        // If viewing the active page source, we can use the pre-fetched sets
        if (modeIsAdmin) {
          const defs = pageDefaultsRef.current
          activeVisible = defs && defs.size > 0 
            ? new Set(defs)
            : new Set(withPerf.map(c => c.db_column))
        } else {
          // In user mode, strictly filter out columns that are not in vessel defaults.
          // If the admin hasn't set any, this means the user will see zero columns.
          const defs = pageDefaultsRef.current || new Set()
          const adminAllowed = defs.size > 0 ? defs : new Set(withPerf.map(c => c.db_column))
          finalCols = withPerf.filter(c => c.is_identity || adminAllowed.has(c.db_column))
          activeVisible = new Set(pageVisRef.current)
        }
      } else {
        // Fetching for the inactive tab
        if (modeIsAdmin) {
          const defaults = await fetchVesselColumnDefaults(source, vesselImo).catch(() => ({}))
          const defSet = new Set(defaults.visible || [])
          activeVisible = defSet.size > 0 
            ? defSet
            : new Set(withPerf.map(c => c.db_column))
        } else {
          const [defaults, userPrefs] = await Promise.all([
            fetchVesselColumnDefaults(source, vesselImo).catch(() => ({})),
            fetchUserColumnPrefs(source, vesselImo).catch(() => ({}))
          ])
          const defSet = new Set(defaults.visible || [])
          const adminAllowed = defSet.size > 0 ? defSet : new Set(withPerf.map(c => c.db_column))
          finalCols = withPerf.filter(c => c.is_identity || adminAllowed.has(c.db_column))
          
          let uVis = new Set(userPrefs.visible || [])
          if (uVis.size === 0) {
            const defaultCols = withPerf.filter(c => c.is_active).map(c => c.db_column)
            if (defSet.size > 0) {
              uVis = new Set(defaultCols.filter(col => defSet.has(col)))
            } else {
              uVis = new Set(defaultCols)
            }
          }
          activeVisible = uVis
        }
      }

      setCols(finalCols)
      setOrder(buildOrder(finalCols))
      setVisible(activeVisible)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [pageSource, vesselImo])

  useEffect(() => { loadCols(src, modeIsAdmin) }, [src, modeIsAdmin, loadCols])

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
      
      const payload = { visible: [...next] }
      
      if (modeIsAdmin) {
        saveVesselColumnDefaults(src, vesselImo, payload).catch(console.error)
        if (src === pageSource) onAdminDefaultsChanged?.(next)
      } else {
        saveUserColumnPrefs(src, vesselImo, payload).catch(console.error)
        if (src === pageSource) onPageSetVisible(next)
      }
      return next
    })
  }

  function handleGroupAction(group, action) {
    setVisible(prev => {
      const next = new Set(prev)
      let colsToAdd = []
      
      if (action === 'all') {
        colsToAdd = group.columns.map(c => c.db_column)
      } else if (action === 'default') {
        colsToAdd = group.columns.filter(c => c.is_active).map(c => c.db_column)
      }

      // First remove all columns in this group
      group.columns.forEach(c => next.delete(c.db_column))
      // Then add the targeted ones
      colsToAdd.forEach(c => next.add(c))
      
      const payload = { visible: [...next] }
      
      if (modeIsAdmin) {
        saveVesselColumnDefaults(src, vesselImo, payload).catch(console.error)
        if (src === pageSource) onAdminDefaultsChanged?.(next)
      } else {
        saveUserColumnPrefs(src, vesselImo, payload).catch(console.error)
        if (src === pageSource) onPageSetVisible(next)
      }
      return next
    })
  }

  async function handleReset() {
    setSaving(true)
    try {
      await resetColumnOrder(src)
      await loadCols(src, modeIsAdmin)
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
    <div className="cp-backdrop" ref={backdropRef} onClick={e => { if (e.target === backdropRef.current) onClose() }}>
      <div className={`cp-panel ${modeIsAdmin ? 'cp-panel-admin' : ''}`}>
        
        <div className="cp-header">
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', width: '100%' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div className="cp-title">
                {modeIsAdmin ? <Shield size={16} /> : <Columns size={16} />}
                {modeIsAdmin ? 'Vessel Defaults Manager' : 'Column Manager'}
                <span className="cp-badge">{totalShown} shown</span>
                {saving && <Loader2 size={12} className="icon-spin" />}
                {isAdmin && (
                  <label className="cp-admin-toggle" title="Toggle Admin Mode to configure global vessel defaults">
                    <input 
                      type="checkbox" 
                      checked={modeIsAdmin} 
                      onChange={(e) => onModeChange(e.target.checked)}
                    />
                    <div className="cp-toggle-track">
                      <div className="cp-toggle-thumb"></div>
                    </div>
                    <span>Edit Vessel Defaults</span>
                  </label>
                )}
              </div>
              <div style={{ 
                fontSize: 12, 
                color: modeIsAdmin ? '#f59e0b' : 'var(--accent-2)', 
                background: modeIsAdmin ? 'rgba(245, 158, 11, 0.1)' : 'rgba(56, 189, 248, 0.1)',
                padding: '6px 10px',
                borderRadius: '6px',
                border: `1px solid ${modeIsAdmin ? 'rgba(245, 158, 11, 0.3)' : 'rgba(56, 189, 248, 0.2)'}`,
                marginTop: '4px'
              }}>
                {modeIsAdmin ? 'Configuring defaults for: ' : 'Viewing approved columns for: '}
                <span style={{ 
                  color: modeIsAdmin ? '#ef4444' : '#38bdf8', 
                  fontWeight: 'bold',
                  fontSize: 13,
                  marginLeft: 4
                }}>
                  {vesselName || vesselImo || 'All Vessels'}
                </span>
              </div>
            </div>
            <button className="cp-close" onClick={onClose}><X size={15} /></button>
          </div>
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

        <div className="cp-legend">
          <span className="cp-legend-item">
            <span className="cp-dot pink" /> Drag to reorder
          </span>
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
                const isOn   = visibleSet.has(col.db_column)
                return (
                  <button
                    key={col.db_column}
                    className={`cp-col-row cp-col-main${isOn ? ' on' : ''}`}
                    onClick={() => toggleField(col.db_column)}
                    title={col.description || col.display_name}
                  >
                    <span className="cp-col-indicator">
                      {isOn ? <CheckSquare size={13} color="var(--accent-2)" /> : <Square size={13} color="var(--text-muted)" style={{ opacity: 0.5 }} />}
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
                    onGroupAction={handleGroupAction}
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
