import { useState, useEffect, useCallback, useMemo } from 'react'
import { Plus, X, GripVertical, Trash2, Loader2 } from 'lucide-react'
import {
  DndContext, closestCenter, PointerSensor, useSensor, useSensors,
} from '@dnd-kit/core'
import {
  SortableContext, verticalListSortingStrategy, useSortable, arrayMove,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import {
  fetchExpandedColumns, reorderColumns,
  fetchCategoryOrder, saveCategoryOrder,
  fetchCalculationCategories, createCalculationCategory, deleteCalculationCategory,
  fetchCalcCategoryColumns, saveCalcCategoryColumns,
} from '../api/vesselApi'
import './ColumnConfigPage.css'

// ── Sortable row (used for category order, calc-category output, and All
// mode's per-category field reorder). `onClick`/`active` let a row (e.g. a
// category in Section 1) also act as a selector — clicking anywhere except
// the grip handle selects it, dragging the grip handle reorders it; the two
// never conflict since dnd-kit's listeners are only spread onto the handle.
function SortableRow({ id, label, tag, onRemove, onClick, active }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id })
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }
  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`ccfg-row${onClick ? ' ccfg-row-clickable' : ''}${active ? ' active' : ''}`}
      onClick={onClick}
    >
      <span className="ccfg-drag" {...attributes} {...listeners}>
        <GripVertical size={13} />
      </span>
      <span className="ccfg-row-label">{label}</span>
      {tag && <span className="ccfg-tag">{tag}</span>}
      {onRemove && (
        <button className="ccfg-rm" onClick={(e) => { e.stopPropagation(); onRemove(id) }} title="Remove">
          <X size={13} />
        </button>
      )}
    </div>
  )
}

export default function ColumnConfigPage() {
  const [source, setSource] = useState('mari_apps')
  const [columnsMeta, setColumnsMeta] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  // mode: 'all' | a calc category id (number)
  const [mode, setMode] = useState('all')
  const [calcCategories, setCalcCategories] = useState([])
  const [categoryOrder, setCategoryOrder] = useState([])   // All mode — Section 1 + 3
  const [selectedSrcCat, setSelectedSrcCat] = useState(null) // which src category Section 2 shows (both modes)
  const [calcColumns, setCalcColumns] = useState([])       // calc mode — Section 3
  const [catFieldOrder, setCatFieldOrder] = useState([])   // All mode — Section 2's field order for selectedSrcCat

  const [addingCategory, setAddingCategory] = useState(false)
  const [newCategoryName, setNewCategoryName] = useState('')

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

  // Distinct active source categories for this source, excluding identity columns.
  const sourceCategories = useMemo(() => {
    return [...new Set(
      columnsMeta.filter(c => c.is_active && !c.is_identity).map(c => c.category || 'Other')
    )]
  }, [columnsMeta])

  const loadAll = useCallback(async (src) => {
    setLoading(true)
    try {
      const [cols, catOrder, calcCats] = await Promise.all([
        fetchExpandedColumns(src),
        fetchCategoryOrder(src),
        fetchCalculationCategories(src),
      ])
      setColumnsMeta(cols)
      setCalcCategories(calcCats)
      const activeCats = new Set(cols.filter(c => c.is_active && !c.is_identity).map(c => c.category || 'Other'))
      // Category order might be stale vs. currently-active categories (a category
      // could have been fully pruned since this was last saved) — filter to what
      // still exists, then append any new category not yet in the saved order.
      const filtered = catOrder.filter(c => activeCats.has(c))
      const missing = [...activeCats].filter(c => !filtered.includes(c)).sort()
      setCategoryOrder([...filtered, ...missing])
      setMode('all')
      setSelectedSrcCat(null)
      setCalcColumns([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadAll(source) }, [source, loadAll])

  const loadCalcColumns = useCallback(async (categoryId) => {
    const cols = await fetchCalcCategoryColumns(categoryId)
    setCalcColumns(cols)
  }, [])

  function handleModeChange(newMode) {
    setMode(newMode)
    setSelectedSrcCat(null)
    setCatFieldOrder([])
    if (newMode !== 'all') loadCalcColumns(newMode)
  }

  // Both modes: clicking a source category in Section 1 shows its fields in
  // Section 2. In All mode, columnsMeta already arrives sorted by the
  // backend's coalesce(user_sort_order, sort_order), so filtering to this
  // category preserves its current field order as the drag's starting point.
  function handleSelectSrcCat(cat) {
    setSelectedSrcCat(cat)
    if (isAllMode) {
      const fields = columnsMeta
        .filter(c => c.is_active && !c.is_identity && (c.category || 'Other') === cat)
        .map(c => c.db_column)
      setCatFieldOrder(fields)
    }
  }

  // ── All mode: Section 2 drag reorders fields WITHIN the selected category.
  // Writes user_sort_order via the existing (shared, admin-authored) reorder
  // endpoint — only the listed columns' order changes, every other column's
  // position is left untouched, so this can't scatter one category's fields
  // into another's territory.
  async function handleCatFieldDragEnd(e) {
    const { active, over } = e
    if (!over || active.id === over.id) return
    const oldIndex = catFieldOrder.indexOf(active.id)
    const newIndex = catFieldOrder.indexOf(over.id)
    const next = arrayMove(catFieldOrder, oldIndex, newIndex)
    setCatFieldOrder(next)
    setSaving(true)
    try {
      await reorderColumns(source, next)
    } finally {
      setSaving(false)
    }
  }

  // ── All mode: Section 1 drag reorders categoryOrder, auto-saves ──
  async function handleCategoryDragEnd(e) {
    const { active, over } = e
    if (!over || active.id === over.id) return
    const oldIndex = categoryOrder.indexOf(active.id)
    const newIndex = categoryOrder.indexOf(over.id)
    const next = arrayMove(categoryOrder, oldIndex, newIndex)
    setCategoryOrder(next)
    setSaving(true)
    try {
      await saveCategoryOrder(source, next)
    } finally {
      setSaving(false)
    }
  }

  // ── Calc mode: Section 3 drag reorders calcColumns, auto-saves ──
  async function handleCalcColumnDragEnd(e) {
    const { active, over } = e
    if (!over || active.id === over.id) return
    const oldIndex = calcColumns.indexOf(active.id)
    const newIndex = calcColumns.indexOf(over.id)
    const next = arrayMove(calcColumns, oldIndex, newIndex)
    setCalcColumns(next)
    setSaving(true)
    try {
      await saveCalcCategoryColumns(mode, next)
    } finally {
      setSaving(false)
    }
  }

  // ── Calc mode: Section 2 checkbox toggles a field in/out of calcColumns ──
  async function toggleField(dbColumn) {
    const next = calcColumns.includes(dbColumn)
      ? calcColumns.filter(c => c !== dbColumn)
      : [...calcColumns, dbColumn]
    setCalcColumns(next)
    setSaving(true)
    try {
      await saveCalcCategoryColumns(mode, next)
    } finally {
      setSaving(false)
    }
  }

  async function handleRemoveCalcColumn(dbColumn) {
    await toggleField(dbColumn)
  }

  async function handleAddCategory() {
    const name = newCategoryName.trim()
    if (!name) return
    try {
      const created = await createCalculationCategory(source, name)
      setCalcCategories(prev => [...prev, created])
      setAddingCategory(false)
      setNewCategoryName('')
      handleModeChange(created.id)
    } catch (e) {
      alert(e?.response?.data?.detail || 'Could not create category.')
    }
  }

  async function handleDeleteCategory(id, e) {
    e.stopPropagation()
    if (!window.confirm('Delete this calculation category? This cannot be undone.')) return
    await deleteCalculationCategory(id)
    setCalcCategories(prev => prev.filter(c => c.id !== id))
    if (mode === id) handleModeChange('all')
  }

  const isAllMode = mode === 'all'
  const activeCalcCat = calcCategories.find(c => c.id === mode)
  const fieldsInSelectedCat = selectedSrcCat
    ? columnsMeta.filter(c => c.is_active && !c.is_identity && (c.category || 'Other') === selectedSrcCat)
    : []

  return (
    <div className="ccfg-wrap">
      <div className="ccfg-toolbar">
        <div className="ccfg-source-toggle">
          <button className={source === 'mari_apps' ? 'active' : ''} onClick={() => setSource('mari_apps')}>MariApps</button>
          <button className={source === 'wni' ? 'active' : ''} onClick={() => setSource('wni')}>WNI</button>
        </div>
        {saving && <span className="ccfg-saving"><Loader2 size={13} className="ccfg-spin" /> Saving…</span>}
      </div>

      <div className="ccfg-pillbar">
        <span className="ccfg-pillbar-label">Calculation category</span>
        <button className={`ccfg-pill${isAllMode ? ' active' : ''}`} onClick={() => handleModeChange('all')}>All</button>
        {calcCategories.map(cat => (
          <button
            key={cat.id}
            className={`ccfg-pill${mode === cat.id ? ' active' : ''}`}
            onClick={() => handleModeChange(cat.id)}
          >
            {cat.name}
            {!cat.is_builtin && (
              <Trash2 size={11} className="ccfg-pill-del" onClick={(e) => handleDeleteCategory(cat.id, e)} />
            )}
          </button>
        ))}
        {addingCategory ? (
          <span className="ccfg-add-form">
            <input
              autoFocus
              placeholder="Category name"
              value={newCategoryName}
              onChange={e => setNewCategoryName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleAddCategory(); if (e.key === 'Escape') setAddingCategory(false) }}
            />
            <button onClick={handleAddCategory}>Add</button>
            <button onClick={() => { setAddingCategory(false); setNewCategoryName('') }}>Cancel</button>
          </span>
        ) : (
          <button className="ccfg-pill ccfg-pill-add" onClick={() => setAddingCategory(true)}>
            <Plus size={13} /> Add category
          </button>
        )}
      </div>

      <p className="ccfg-hint">
        {isAllMode
          ? 'All mode — drag categories on the left to set the default table\'s category order, or click one to reorder its own fields in the middle.'
          : `${activeCalcCat?.name || ''} mode — pick fields from any source category on the left to add them to this category's output.`}
      </p>

      {loading ? (
        <div className="ccfg-loading"><Loader2 size={18} className="ccfg-spin" /> Loading…</div>
      ) : (
        <div className="ccfg-panes">
          <div className="ccfg-pane">
            <p className="ccfg-pane-head">
              {isAllMode ? 'Source categories · drag to reorder' : 'Source categories'}
            </p>
            {isAllMode ? (
              <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleCategoryDragEnd}>
                <SortableContext items={categoryOrder} strategy={verticalListSortingStrategy}>
                  {categoryOrder.map(cat => (
                    <SortableRow
                      key={cat}
                      id={cat}
                      label={cat}
                      active={selectedSrcCat === cat}
                      onClick={() => handleSelectSrcCat(cat)}
                    />
                  ))}
                </SortableContext>
              </DndContext>
            ) : (
              sourceCategories.map(cat => (
                <div
                  key={cat}
                  className={`ccfg-src-row${selectedSrcCat === cat ? ' active' : ''}`}
                  onClick={() => handleSelectSrcCat(cat)}
                >
                  {cat}
                </div>
              ))
            )}
          </div>

          <div className="ccfg-pane">
            <p className="ccfg-pane-head">
              {isAllMode
                ? (selectedSrcCat ? `${selectedSrcCat} fields · drag to reorder` : 'Select a category on the left')
                : (selectedSrcCat ? `${selectedSrcCat} fields` : 'Select a category on the left')}
            </p>
            {isAllMode && selectedSrcCat && (
              <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleCatFieldDragEnd}>
                <SortableContext items={catFieldOrder} strategy={verticalListSortingStrategy}>
                  {catFieldOrder.map(dbCol => {
                    const meta = columnsMeta.find(c => c.db_column === dbCol)
                    return <SortableRow key={dbCol} id={dbCol} label={meta?.display_name || dbCol} />
                  })}
                </SortableContext>
              </DndContext>
            )}
            {!isAllMode && fieldsInSelectedCat.map(col => (
              <label key={col.db_column} className="ccfg-field-row">
                <input
                  type="checkbox"
                  checked={calcColumns.includes(col.db_column)}
                  onChange={() => toggleField(col.db_column)}
                />
                <span>{col.display_name || col.db_column}</span>
              </label>
            ))}
          </div>

          <div className="ccfg-pane">
            <p className="ccfg-pane-head">
              {isAllMode ? 'Default table order (preview)' : `${activeCalcCat?.name || ''} output · drag to reorder`}
            </p>
            {isAllMode ? (
              categoryOrder.map(cat => (
                <div key={cat} className="ccfg-row ccfg-row-static">
                  <span className="ccfg-row-label">{cat}</span>
                </div>
              ))
            ) : (
              <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleCalcColumnDragEnd}>
                <SortableContext items={calcColumns} strategy={verticalListSortingStrategy}>
                  {calcColumns.map(dbCol => {
                    const meta = columnsMeta.find(c => c.db_column === dbCol)
                    return (
                      <SortableRow
                        key={dbCol}
                        id={dbCol}
                        label={meta?.display_name || dbCol}
                        tag={meta?.category}
                        onRemove={handleRemoveCalcColumn}
                      />
                    )
                  })}
                </SortableContext>
              </DndContext>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
