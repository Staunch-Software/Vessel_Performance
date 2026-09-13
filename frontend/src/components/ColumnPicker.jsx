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
// `emission` is ADDITIVE (unlike `performance`, which replaces the category): a
// column keeps its normal category AND is also pushed into an "Emission" bucket,
// so the same field/toggle appears in both places in the picker.
//
// Category ORDER follows the incoming order (which already reflects any saved
// category-level drag) once a source has ever been manually reordered — detected
// via `user_sort_order` being set on any column, which `persist()` stamps on
// every column for the source in one go. Until then, Performance/Emission are
// pinned first as the out-of-the-box default. Without this distinction, the
// picker would re-force Performance/Emission to the front on every reload,
// permanently undoing a category drag the moment the panel is reopened even
// though the new order was saved correctly.
function buildOrder(cols) {
  const nonId = cols.filter(c => !c.is_identity)
  const hasCustomOrder = cols.some(c => c.user_sort_order != null)
  const order = []
  const map = {}
  for (const c of nonId) {
    const cat = c.performance ? 'Performance' : (c.category || 'Other')
    if (!map[cat]) { map[cat] = []; order.push(cat) }
    map[cat].push(c)
    if (c.emission && cat !== 'Emission') {
      if (!map['Emission']) { map['Emission'] = []; order.push('Emission') }
      map['Emission'].push(c)
    }
  }

  // Ensure 'Performance' is at the top and always exists
  if (!map['Performance']) {
    map['Performance'] = [];
    order.push('Performance');
  }

  // Every column in 'Emission' is a duplicate of its primary-category listing
  // (see comment above `emission_sort_order` in models.py), so it needs its
  // OWN order field — sorting by `user_sort_order` here would just reproduce
  // wherever it sits in Performance/its real category, making an Emission
  // drag look like it did nothing. Fall back to the incoming (primary-order-
  // derived) position for anything that's never been dragged inside Emission.
  if (map['Emission']) {
    const hasEmissionOrder = map['Emission'].some(c => c.emission_sort_order != null)
    if (hasEmissionOrder) {
      map['Emission'] = map['Emission']
        .map((c, i) => ({ c, key: c.emission_sort_order ?? (1e6 + i) }))
        .sort((a, b) => a.key - b.key)
        .map(x => x.c)
    }
  }

  let finalOrder
  if (hasCustomOrder) {
    finalOrder = order
  } else {
    // Pin 'Performance' first, then 'Emission' right after — both near the
    // front, ahead of the rest — as the default before any manual reorder.
    const rest = order.filter(c => c !== 'Performance' && c !== 'Emission')
    finalOrder = [
      'Performance',
      ...(order.includes('Emission') ? ['Emission'] : []),
      ...rest,
    ]
  }

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
function SortableCategory({ group, expanded, onToggleExpand, visibleSet, onToggleField, onFieldDragEnd, onGroupAction, onResetCategoryOrder }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: group.cat })
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  }
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))
  const shownCount = group.columns.filter(c => visibleSet.has(c.db_column)).length

  const groupCls = group.cat === 'Emission' ? ' cp-group-emission'
    : group.cat === 'Performance' ? ' cp-group-performance' : ''

  return (
    <div ref={setNodeRef} style={style} className={`cp-group${groupCls}`}>
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
          <button
            className="cp-action-btn"
            title="Revert this category's column order to default (other categories are untouched)"
            onClick={(e) => { e.stopPropagation(); onResetCategoryOrder(group) }}
          ><RotateCcw size={11} /></button>
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
  const [scope,      setScope]     = useState('vessel') // 'vessel' | 'global'
  // Surfaces a save failure instead of the old silent .catch(console.error) —
  // e.g. the vessel_column_defaults.vessel_imo NOT NULL bug threw on every
  // Global-scope save while looking, in this component's own state, like it
  // had succeeded. Cleared automatically on the next successful save.
  const [saveError,  setSaveError] = useState(null)
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
  const loadCols = useCallback(async (source, modeIsAdmin, currentScope) => {
    setLoading(true)
    try {
      // activeImo drives both visibility (defaults/prefs) AND column order —
      // fetching with it lets this vessel's own saved order (if any) win.
      const activeImo = currentScope === 'global' ? null : vesselImo
      const fetched = await fetchExpandedColumns(source, activeImo)
      const perfColsLower = new Set([...PERFORMANCE_COLUMNS].map(c => c.toLowerCase()))
      const withPerf = fetched.map(c => ({
        ...c, performance: c.performance || PERFORMANCE_COLUMNS.has(c.db_column) || perfColsLower.has((c.db_column || '').toLowerCase()),
      }))

      let finalCols = withPerf
      let activeVisible = new Set()

      if (source === pageSource && currentScope === 'vessel') {
        // If viewing the active page source for this vessel, we can use the pre-fetched sets
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
        // Fetching for inactive tab or global scope
        if (modeIsAdmin) {
          const defaults = await fetchVesselColumnDefaults(source, activeImo).catch(() => ({}))
          const defSet = new Set(defaults.visible || [])
          activeVisible = defSet.size > 0 
            ? defSet
            : new Set(withPerf.map(c => c.db_column))
        } else {
          const [defaults, userPrefs] = await Promise.all([
            fetchVesselColumnDefaults(source, activeImo).catch(() => ({})),
            fetchUserColumnPrefs(source, activeImo).catch(() => ({}))
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

  useEffect(() => { loadCols(src, modeIsAdmin, scope) }, [src, modeIsAdmin, scope, loadCols])

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

  // Persist the current ordering (category order + field order) to the backend.
  // scope === 'vessel' saves it for vesselImo only ("This Vessel"); scope ===
  // 'global' saves the shared order AND overrides any vessel-specific order
  // already saved for these same columns (see reorder_columns() docstring).
  const persist = useCallback(async (nextOrder) => {
    // A dual-membership column (performance=true AND emission=true, e.g.
    // "Destination Port") is deliberately listed TWICE in `nextOrder` — once
    // under its primary "Performance" group, once again under "Emission" — so
    // it can be toggled from either bucket (see buildOrder() above). Naively
    // flattening both copies into the saved order means whichever copy comes
    // LATER in the list (Emission always follows Performance) silently
    // overwrites the position of whichever copy you actually dragged, so the
    // column always snaps back near its Emission-group spot no matter where
    // you move it in Performance. Keep only the first occurrence per
    // db_column — that's always its primary-category placement.
    const seen = new Set()
    const list = []
    for (const g of nextOrder) {
      for (const c of g.columns) {
        if (seen.has(c.db_column)) continue
        seen.add(c.db_column)
        list.push(c.db_column)
      }
    }
    const activeImo = scope === 'global' ? null : vesselImo
    setSaving(true)
    try {
      await reorderColumns(src, list, 'primary', activeImo)
      setSaveError(null)
      if (src === pageSource) onOrderChanged?.()
    } catch (e) {
      console.error(e)
      setSaveError('Could not save the new order — your change may not persist. Try again.')
    } finally {
      setSaving(false)
    }
  }, [src, pageSource, onOrderChanged, scope, vesselImo])

  // Persist a drag done WITHIN the Emission bucket specifically. Every column
  // there is a duplicate of its primary-category listing, so this must never
  // touch user_sort_order (that column's real Performance/category position)
  // — it saves to emission_sort_order instead, which only governs how the
  // Emission bucket itself is arranged.
  const persistEmissionOrder = useCallback(async (emissionCols) => {
    const list = emissionCols.map(c => c.db_column)
    setSaving(true)
    try {
      await reorderColumns(src, list, 'emission')
      setSaveError(null)
      if (src === pageSource) onOrderChanged?.()
    } catch (e) {
      console.error(e)
      setSaveError('Could not save the new Emission order — your change may not persist. Try again.')
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
      if (cat === 'Emission') {
        const emissionGroup = next.find(g => g.cat === 'Emission')
        if (emissionGroup) persistEmissionOrder(emissionGroup.columns)
      } else {
        persist(next)
      }
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

  // NOTE: builds `next` from the current `visibleSet` state directly (not a
  // setVisible(prev => ...) functional updater) because this runs once per
  // click, synchronously, so `visibleSet` is never stale here. The updater
  // form was avoided deliberately: React calls that callback during its
  // render pass, and it used to call onPageSetVisible/onAdminDefaultsChanged
  // (which setState a DIFFERENT component, LogbookPage) from inside it —
  // triggering "Cannot update a component while rendering a different
  // component". Doing the parent notification here, in the handler body
  // (a plain event-handler execution, not a render), avoids that entirely.
  function toggleField(dbCol) {
    const next = new Set(visibleSet)
    next.has(dbCol) ? next.delete(dbCol) : next.add(dbCol)
    setVisible(next)

    const payload = { visible: [...next] }
    const activeImo = scope === 'global' ? null : vesselImo
    const failMsg = `Could not save this ${scope === 'global' ? 'Global' : 'vessel'} column change — it may not persist. Try again.`

    if (modeIsAdmin) {
      saveVesselColumnDefaults(src, activeImo, payload)
        .then(() => setSaveError(null))
        .catch(e => { console.error(e); setSaveError(failMsg) })
      // Sync the live page regardless of scope — a Global-scope edit still
      // affects the vessel currently on screen (unless it has its own
      // vessel-specific override, a rare edge case corrected by the next
      // reload anyway). Previously gated to scope==='vessel' only, which
      // meant Global edits saved correctly to the DB but the table behind
      // the picker never learned about them until a full page reload.
      if (src === pageSource) onAdminDefaultsChanged?.(next)
    } else {
      saveUserColumnPrefs(src, activeImo, payload)
        .then(() => setSaveError(null))
        .catch(e => { console.error(e); setSaveError(failMsg) })
      // Same reasoning as onAdminDefaultsChanged above — sync regardless of scope.
      if (src === pageSource) onPageSetVisible(next)
    }
  }

  // See the note on toggleField above — same reasoning applies here: build
  // `next` from current state directly and setVisible(next) as a plain
  // value, rather than doing the parent-notifying side effects inside a
  // setVisible(prev => ...) updater (which React runs during its render pass).
  function handleGroupAction(group, action) {
    const next = new Set(visibleSet)
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
    setVisible(next)

    const payload = { visible: [...next] }
    const activeImo = scope === 'global' ? null : vesselImo
    const failMsg = `Could not save this ${scope === 'global' ? 'Global' : 'vessel'} column change — it may not persist. Try again.`

    if (modeIsAdmin) {
      saveVesselColumnDefaults(src, activeImo, payload)
        .then(() => setSaveError(null))
        .catch(e => { console.error(e); setSaveError(failMsg) })
      // Sync the live page regardless of scope — a Global-scope edit still
      // affects the vessel currently on screen (unless it has its own
      // vessel-specific override, a rare edge case corrected by the next
      // reload anyway). Previously gated to scope==='vessel' only, which
      // meant Global edits saved correctly to the DB but the table behind
      // the picker never learned about them until a full page reload.
      if (src === pageSource) onAdminDefaultsChanged?.(next)
    } else {
      saveUserColumnPrefs(src, activeImo, payload)
        .then(() => setSaveError(null))
        .catch(e => { console.error(e); setSaveError(failMsg) })
      // Same reasoning as onAdminDefaultsChanged above — sync regardless of scope.
      if (src === pageSource) onPageSetVisible(next)
    }
  }

  async function handleReset() {
    setSaving(true)
    try {
      // Clears both order fields for the current scope — the primary order
      // (this vessel's own, or the shared Global one) AND the Emission
      // bucket's own order (always global) — so "Reset all order" really
      // means all of it.
      const activeImo = scope === 'global' ? null : vesselImo
      await resetColumnOrder(src, null, 'primary', activeImo)
      await resetColumnOrder(src, null, 'emission')
      await loadCols(src, modeIsAdmin, scope)
      if (src === pageSource) onOrderChanged?.()
    } finally {
      setSaving(false)
    }
  }

  // Reset order for just ONE category's columns, leaving every other
  // category's saved order untouched — unlike handleReset() above, which
  // wipes the whole source's order. For the Emission bucket specifically,
  // this must reset emission_sort_order, NOT user_sort_order — the columns
  // shown there are duplicates, and their user_sort_order is their REAL
  // position in Performance/their actual category, which this button has no
  // business touching. For any other category, resets whichever scope
  // (This Vessel / Global) is currently selected.
  async function handleResetCategoryOrder(group) {
    setSaving(true)
    try {
      const isEmission = group.cat === 'Emission'
      const target = isEmission ? 'emission' : 'primary'
      const activeImo = isEmission ? null : (scope === 'global' ? null : vesselImo)
      await resetColumnOrder(src, group.columns.map(c => c.db_column), target, activeImo)
      await loadCols(src, modeIsAdmin, scope)
      if (src === pageSource) onOrderChanged?.()
    } finally {
      setSaving(false)
    }
  }

  // Clears the CURRENT USER's own saved column-visibility preference for this
  // scope (This Vessel / Global), so their view falls back to the admin/Global
  // default instead of a stale personal snapshot — e.g. one saved before a
  // batch of new columns existed, which otherwise persists indefinitely with
  // no other way to clear it (a personal preference, once non-empty, always
  // wins over the admin default for that user's own view). Only meaningful in
  // non-admin mode — admin mode already IS the shared default being edited.
  async function handleResetVisibility() {
    setSaving(true)
    try {
      const activeImo = scope === 'global' ? null : vesselImo
      await saveUserColumnPrefs(src, activeImo, { visible: [] })
      setSaveError(null)
      await loadCols(src, modeIsAdmin, scope)
      // Reuse onOrderChanged (a generic "refetch everything" signal, not
      // onPageSetVisible) — the page's own load effect is what implements the
      // fallback-to-admin-default logic when prefs.visible comes back empty.
      // Calling onPageSetVisible(new Set()) directly would instead render zero
      // columns until the next unrelated refetch.
      if (src === pageSource) onOrderChanged?.()
    } catch (e) {
      console.error(e)
      setSaveError('Could not reset your column selection. Try again.')
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
                marginTop: '4px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between'
              }}>
                <div>
                  {modeIsAdmin ? 'Configuring defaults for: ' : 'Viewing approved columns for: '}
                  <span style={{ 
                    color: modeIsAdmin ? '#ef4444' : '#38bdf8', 
                    fontWeight: 'bold',
                    fontSize: 13,
                    marginLeft: 4
                  }}>
                    {scope === 'global' ? 'All Vessels (Global)' : (vesselName || vesselImo || 'All Vessels')}
                  </span>
                </div>
                
                {/* Mini Segmented Control */}
                <div className={`cp-mini-scope ${modeIsAdmin ? 'admin-mode' : 'user-mode'}`} data-active={scope}>
                  <div className="cp-mini-indicator"></div>
                  <div className={`cp-mini-tab ${scope === 'vessel' ? 'active' : ''}`} onClick={() => setScope('vessel')}>
                    This Vessel
                  </div>
                  <div className={`cp-mini-tab ${scope === 'global' ? 'active' : ''}`} onClick={() => setScope('global')}>
                    Global
                  </div>
                </div>
              </div>
            </div>
            <button className="cp-close" onClick={onClose}><X size={15} /></button>
          </div>
        </div>

        {saveError && (
          <div className="cp-save-error" role="alert">
            {saveError}
          </div>
        )}

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
                    onResetCategoryOrder={handleResetCategoryOrder}
                  />
                ))}
                {order.length === 0 && <div className="cp-empty">No columns for this source.</div>}
              </SortableContext>
            </DndContext>
          )}
        </div>

        {/* Footer */}
        <div className="cp-footer">
          <button className="cp-reset-btn" onClick={handleReset} disabled={saving} title="Revert the ENTIRE column order for this source to default — every category, not just one">
            <RotateCcw size={12} /> Reset all order
          </button>
          {!modeIsAdmin && (
            <button
              className="cp-reset-btn"
              onClick={handleResetVisibility}
              disabled={saving}
              title="Clear your personal column selection for this scope and fall back to the admin/Global default"
            >
              <RotateCcw size={12} /> Reset my columns
            </button>
          )}
          <span className="cp-footer-hint">Order changes save automatically</span>
        </div>
      </div>
    </div>
  )
}
