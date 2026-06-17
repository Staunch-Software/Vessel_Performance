import { useState, useEffect, useRef, useMemo } from 'react'
import { X, Lock, Search, Eye, EyeOff, CheckSquare, Square } from 'lucide-react'
import './ColumnPicker.css'

export default function ColumnPicker({ columns, userVisible, onToggle, onClose }) {
  const [search,      setSearch]   = useState('')
  const [activeCat,   setActiveCat] = useState('All')
  const backdropRef = useRef(null)

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const nonIdCols = useMemo(() => columns.filter(c => !c.is_identity), [columns])

  // All distinct categories in stable order
  const allCategories = useMemo(() => {
    const cats = [...new Set(nonIdCols.map(c => c.category || 'Other'))]
    return cats.sort((a, b) => a.localeCompare(b))
  }, [nonIdCols])

  // Filtered + grouped columns
  const groups = useMemo(() => {
    const q   = search.trim().toLowerCase()
    let cols  = nonIdCols

    // 'Performance' is a special filter — shows only NoonData/Calc Engine columns
    if (activeCat === 'Performance') cols = cols.filter(c => c.performance)
    else if (activeCat !== 'All')    cols = cols.filter(c => (c.category || 'Other') === activeCat)

    if (q) cols = cols.filter(c =>
      c.display_name.toLowerCase().includes(q) ||
      c.db_column.toLowerCase().includes(q) ||
      (c.category || '').toLowerCase().includes(q)
    )

    const map = {}
    for (const col of cols) {
      const cat = col.category || 'Other'
      if (!map[cat]) map[cat] = []
      map[cat].push(col)
    }
    return Object.entries(map).sort(([a], [b]) => a.localeCompare(b))
  }, [nonIdCols, activeCat, search])

  // Toggle all optional (pink) columns in a category
  function toggleAllInCategory(cat, cols) {
    const optionals = cols.filter(c => !c.is_active)
    if (!optionals.length) return
    const allOn = optionals.every(c => userVisible?.has(c.db_column))
    optionals.forEach(c => {
      const isOn = userVisible?.has(c.db_column)
      if (allOn && isOn) onToggle(c.db_column)
      else if (!allOn && !isOn) onToggle(c.db_column)
    })
  }

  const activeCount  = nonIdCols.filter(c => c.is_active).length
  const userCount    = userVisible ? userVisible.size : 0

  return (
    <div
      className="cp-backdrop"
      ref={backdropRef}
      onClick={e => { if (e.target === backdropRef.current) onClose() }}
    >
      <div className="cp-panel">
        {/* Header */}
        <div className="cp-header">
          <div className="cp-title">
            <Eye size={14} />
            Column Visibility
            <span className="cp-badge">{activeCount + userCount} shown</span>
          </div>
          <button className="cp-close" onClick={onClose}><X size={15} /></button>
        </div>

        {/* Legend */}
        <div className="cp-legend">
          <div className="cp-legend-item">
            <Lock size={11} className="cp-lock" />
            <span>Always visible</span>
          </div>
          <div className="cp-legend-item">
            <div className="cp-dot pink" />
            <span>Optional — toggle to show</span>
          </div>
        </div>

        {/* Category filter chips */}
        <div className="cp-cat-bar">
          <button
            className={`cp-cat-chip${activeCat === 'All' ? ' active' : ''}`}
            onClick={() => setActiveCat('All')}
          >All</button>
          {/* Performance filter — NoonData + Calc Engine columns */}
          <button
            className={`cp-cat-chip cp-perf-chip${activeCat === 'Performance' ? ' active' : ''}`}
            onClick={() => setActiveCat('Performance')}
            title="Show only columns used in ISO 19030 NoonData & Calc Engine sheets"
          >⚡ Performance</button>
          {allCategories.map(cat => (
            <button
              key={cat}
              className={`cp-cat-chip${activeCat === cat ? ' active' : ''}`}
              onClick={() => setActiveCat(cat)}
            >{cat}</button>
          ))}
        </div>

        {/* Search */}
        <div className="cp-search">
          <Search size={12} />
          <input
            placeholder="Search columns…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          {search && (
            <button className="cp-search-clear" onClick={() => setSearch('')}>
              <X size={11} />
            </button>
          )}
        </div>

        {/* Column groups */}
        <div className="cp-body">
          {groups.map(([cat, cols]) => {
            const optionals = cols.filter(c => !c.is_active)
            const allOptionalOn = optionals.length > 0 && optionals.every(c => userVisible?.has(c.db_column))
            return (
              <div key={cat} className="cp-group">
                <div className="cp-group-header">
                  <span className="cp-group-label">{cat}</span>
                  {optionals.length > 0 && (
                    <button
                      className="cp-toggle-all"
                      onClick={() => toggleAllInCategory(cat, cols)}
                      title={allOptionalOn ? 'Hide all optional in this category' : 'Show all optional in this category'}
                    >
                      {allOptionalOn ? <CheckSquare size={12} /> : <Square size={12} />}
                      <span>{allOptionalOn ? 'Deselect all' : 'Select all'}</span>
                    </button>
                  )}
                </div>
                <div className="cp-col-list">
                  {cols.map(col => {
                    const isAlwaysOn = col.is_active
                    const isUserOn   = userVisible?.has(col.db_column)
                    const isOn       = isAlwaysOn || isUserOn
                    return (
                      <button
                        key={col.db_column}
                        className={`cp-col-row${isOn ? ' on' : ''}${isAlwaysOn ? ' locked' : ''}`}
                        onClick={() => !isAlwaysOn && onToggle(col.db_column)}
                        title={col.description || col.display_name}
                      >
                        <span className="cp-col-indicator">
                          {isAlwaysOn
                            ? <Lock size={10} className="cp-lock" />
                            : isUserOn
                              ? <Eye size={11} />
                              : <EyeOff size={11} className="cp-eye-off" />
                          }
                        </span>
                        <span className="cp-col-name">{col.display_name}</span>
                        {col.performance && <span className="cp-perf-dot" title="Performance column (NoonData / Calc Engine)">⚡</span>}
                        {col.unit && <span className="cp-col-unit">{col.unit}</span>}
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })}
          {groups.length === 0 && (
            <div className="cp-empty">No columns match your search.</div>
          )}
        </div>
      </div>
    </div>
  )
}
