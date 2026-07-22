import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, LabelList, ReferenceLine, ReferenceArea
} from 'recharts'

function fmt(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return `${d.toLocaleString('en', { month: 'short' })}-${String(d.getDate()).padStart(2,'0')}`
}

// Short label for an event type (used in event-wise mode)
function eventAbbr(et) {
  if (!et) return ''
  const u = et.toUpperCase()
  if (u.includes('BOSP') || u.includes('COSP')) return 'BOSP'
  if (u.includes('EOSP'))                       return 'EOSP'
  if (u.includes('NOON AT SEA'))                return 'Sea'
  if (u.includes('NOON AT PORT'))               return 'Port'
  if (u.includes('ARRIVAL'))                    return 'Arr'
  if (u.includes('DEPARTURE'))                  return 'Dep'
  if (u.includes('ANCHOR'))                     return 'Anch'
  if (u.includes('BUNKER'))                     return 'Bnkr'
  return et.slice(0, 6)
}

// Keep only rows that fall between BOSP and EOSP within each voyage.
// Falls back (per voyage with no BOSP marker) to dropping clearly port-side events.
const PORT_EVENT_RE = /PORT|ARRIVAL|DEPARTURE|ANCHOR|BUNKER|BERTH/
const SEA_EVENT_RE  = /NOON AT SEA|NOON_AT_SEA|SEA PASSAGE|AT SEA/
function filterUnderway(rows) {
  const byVoyage = {}
  for (const r of rows) {
    const key = r.Voyage_No ?? '∅'
    ;(byVoyage[key] ||= []).push(r)
  }
  const out = []
  for (const group of Object.values(byVoyage)) {
    const sorted = [...group].sort((a, b) =>
      (new Date(a.log_date || a.Date) - new Date(b.log_date || b.Date)) ||
      String(a.Time_UTC ?? '').localeCompare(String(b.Time_UTC ?? ''))
    )
    const hasBOSP = sorted.some(r => {
      const u = (r.event_type ?? '').toUpperCase()
      return u.includes('BOSP') || u.includes('COSP')
    })
    if (hasBOSP) {
      // Voyage has an explicit BOSP/COSP in this window — use strict state machine.
      // However, infer initial state in case the voyage started before this time window:
      // if the very first event is already sea-side (EOSP or NOON AT SEA), the vessel
      // was already underway when the window began, so start as underway=true.
      const firstEventType = (sorted[0]?.event_type ?? '').toUpperCase()
      const startsAlreadyUnderway =
        firstEventType.includes('EOSP') ||
        SEA_EVENT_RE.test(firstEventType)
      let underway = startsAlreadyUnderway
      for (const r of sorted) {
        const u = (r.event_type ?? '').toUpperCase()
        const isBOSP = u.includes('BOSP') || u.includes('COSP')
        const isEOSP = u.includes('EOSP')
        if (isBOSP)        { underway = true;  out.push(r) }
        else if (isEOSP)   { out.push(r);      underway = false }
        else if (underway) { out.push(r) }
      }
    } else {
      // No BOSP/COSP in this window at all — voyage either straddles the window boundary
      // (started before, may end after) or is entirely within and has no sea markers.
      // Infer initial underway state from the first event.
      const firstEventType = (sorted[0]?.event_type ?? '').toUpperCase()
      const startsAlreadyUnderway =
        firstEventType.includes('EOSP') ||
        SEA_EVENT_RE.test(firstEventType) ||
        // Null / blank event_type alongside non-port data → assume underway
        (firstEventType === '' && !PORT_EVENT_RE.test(firstEventType))

      if (startsAlreadyUnderway) {
        // Vessel was underway at the start of the window — run state machine from underway=true.
        // Stop at the first EOSP encountered (end of sea passage).
        let underway = true
        for (const r of sorted) {
          const u = (r.event_type ?? '').toUpperCase()
          const isEOSP = u.includes('EOSP')
          const isBOSP = u.includes('BOSP') || u.includes('COSP')
          if (isBOSP)        { underway = true;  out.push(r) }
          else if (isEOSP)   { out.push(r);      underway = false }
          else if (underway) {
            // Only include if not a clear port-side event
            if (!PORT_EVENT_RE.test(u)) out.push(r)
          }
        }
      } else {
        // Vessel was at port at start of window — exclude obvious port-side events.
        for (const r of sorted) {
          if (!PORT_EVENT_RE.test((r.event_type ?? '').toUpperCase())) out.push(r)
        }
      }
    }
  }
  return out
}

// Build chart data from rows for the given mode. Always ascending by date.
// Each datum has a unique `key` (XAxis category) and a clean `label` (display).
// daily    → sum ME/AE per calendar date (one bar/day)
// event    → one bar per report row (date + event type)
// underway → underway rows only, summed per calendar date
function buildData(rows, mode, voyageView) {
  // If in voyage view, determine the earliest date for each voyage to sort them chronologically
  const voyageMinDate = {}
  if (voyageView) {
    for (const r of rows) {
      if (!(r.log_date || r.Date)) continue
      const v = r.Voyage_No ?? 'Unknown'
      const d = new Date(r.log_date || r.Date).getTime()
      if (!voyageMinDate[v] || d < voyageMinDate[v]) {
        voyageMinDate[v] = d
      }
    }
  }

  const sortVoyages = (a, b) => {
    const da = voyageMinDate[a] ?? 0
    const db = voyageMinDate[b] ?? 0
    return da - db || String(a).localeCompare(String(b))
  }

  if (mode === 'event') {
    let sortedRows = [...rows]
    if (voyageView) {
      sortedRows.sort((a, b) => {
        const vA = a.Voyage_No ?? 'Unknown'
        const vB = b.Voyage_No ?? 'Unknown'
        if (vA !== vB) return sortVoyages(vA, vB)
        return (new Date(a.log_date || a.Date) - new Date(b.log_date || b.Date)) ||
               String(a.Time_UTC ?? '').localeCompare(String(b.Time_UTC ?? ''))
      })
    } else {
      sortedRows.sort((a, b) =>
        (new Date(a.log_date || a.Date) - new Date(b.log_date || b.Date)) ||
        String(a.Time_UTC ?? '').localeCompare(String(b.Time_UTC ?? ''))
      )
    }

    const data = []
    let lastVoyage = null

    sortedRows.forEach((r, i) => {
      const me = r.ME_FOC_MT ?? 0
      const ae = r.AE_FOC_MT ?? 0
      const ab = eventAbbr(r.event_type)
      const v = r.Voyage_No ?? 'Unknown'

      if (voyageView && lastVoyage !== null && v !== lastVoyage) {
        data.push({
          key: `gap_${lastVoyage}_${v}`,
          label: ` `, // make it empty so it doesn't show slanted on axis
          'ME FOC': 0,
          'AE FOC': 0,
          total: 0,
          isGap: true,
        })
      }
      lastVoyage = v

      data.push({
        key: `e${i}`,
        label: `${fmt(r.log_date || r.Date)}${ab ? '  ' + ab : ''}`,
        voyage: v,
        'ME FOC': me,
        'AE FOC': ae,
        total: me + ae,
      })
    })
    return data
  }

  const source = mode === 'underway' ? filterUnderway(rows) : rows
  
  if (voyageView) {
    const byVoyageAndDate = {}
    for (const r of source) {
      if (!(r.log_date || r.Date)) continue
      const v = r.Voyage_No ?? 'Unknown'
      const d = (r.log_date || r.Date).slice(0, 10)
      const key = `${v}___${d}`
      const e = (byVoyageAndDate[key] ||= { voyage: v, date: d, me: 0, ae: 0 })
      e.me += r.ME_FOC_MT ?? 0
      e.ae += r.AE_FOC_MT ?? 0
    }

    const groupedList = Object.values(byVoyageAndDate)
    groupedList.sort((a, b) => {
      if (a.voyage !== b.voyage) return sortVoyages(a.voyage, b.voyage)
      return new Date(a.date) - new Date(b.date)
    })

    const data = []
    let lastVoyage = null
    groupedList.forEach((item, i) => {
      if (lastVoyage !== null && item.voyage !== lastVoyage) {
        data.push({
          key: `gap_${lastVoyage}_${item.voyage}_${i}`,
          label: ` `, // make it empty so it doesn't show slanted on axis
          'ME FOC': 0,
          'AE FOC': 0,
          total: 0,
          isGap: true,
        })
      }
      lastVoyage = item.voyage
      
      data.push({
        key: `${item.voyage}_${item.date}_${i}`,
        label: fmt(item.date),
        voyage: item.voyage,
        'ME FOC': item.me,
        'AE FOC': item.ae,
        total: item.me + item.ae,
      })
    })
    return data
  } else {
    // Daily aggregation (sum per calendar date)
    const byDate = {}
    for (const r of source) {
      if (!(r.log_date || r.Date)) continue
      const key = (r.log_date || r.Date).slice(0, 10)
      const e = (byDate[key] ||= { me: 0, ae: 0 })
      e.me += r.ME_FOC_MT ?? 0
      e.ae += r.AE_FOC_MT ?? 0
    }
    return Object.keys(byDate)
      .sort((a, b) => new Date(a) - new Date(b))
      .map(key => {
        const { me, ae } = byDate[key]
        return { key, label: fmt(key), 'ME FOC': me, 'AE FOC': ae, total: me + ae }
      })
  }
}

const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null
  const isGap = payload[0]?.payload?.isGap
  if (isGap) return null
  const total = payload.reduce((s, p) => s + (p.value ?? 0), 0)
  const label   = payload[0]?.payload?.label ?? ''
  const voyage  = payload[0]?.payload?.voyage
  return (
    <div style={{
      background: '#1a2a3a', border: '1px solid #2d4a6a',
      padding: '8px 12px', borderRadius: 4, fontSize: 12,
    }}>
      {voyage && (
        <p style={{ color: '#64748b', fontSize: 10, marginBottom: 2 }}>Voyage {voyage}</p>
      )}
      <p style={{ color: '#94a3b8', marginBottom: 5 }}>{label}</p>
      {payload.map(p => (
        <p key={p.name} style={{ color: p.fill, margin: '2px 0' }}>
          {p.name}: <strong>{p.value?.toFixed(2) ?? '—'}</strong> mt
        </p>
      ))}
      <p style={{ color: '#e2e8f0', borderTop: '1px solid #2d4a6a', marginTop: 5, paddingTop: 5 }}>
        Total: <strong>{total.toFixed(2)}</strong> mt
      </p>
    </div>
  )
}

// Voyage section colours (shared by badge overlay and ReferenceArea)
const V_COLORS  = ['#f472b6', '#38bdf8', '#a78bfa', '#fbbf24', '#34d399', '#f87171']
const V_FILLS   = [
  'rgba(244,114,182,0.22)', 'rgba(56,189,248,0.22)', 'rgba(167,139,250,0.22)',
  'rgba(251,191,36,0.22)',  'rgba(52,211,153,0.22)', 'rgba(248,113,113,0.22)',
]
const V_BORDERS = [
  'rgba(244,114,182,0.5)', 'rgba(56,189,248,0.5)', 'rgba(167,139,250,0.5)',
  'rgba(251,191,36,0.5)',  'rgba(52,211,153,0.5)', 'rgba(248,113,113,0.5)',
]
function shortVoyageName(v) {
  let s = String(v)
  if (s.includes(' V ')) return s.split(' V ').pop()
  if (s.includes(' v ')) return s.split(' v ').pop()
  return s
}

// Custom label showing total on top of stacked bar
function TotalLabel(props) {
  const { x, y, width, value } = props
  if (!value || value === 0) return null
  return (
    <text
      x={x + width / 2}
      y={y - 3}
      fill="#cbd5e1"
      textAnchor="middle"
      fontSize={9}
      fontFamily="Inter, sans-serif"
    >
      {value.toFixed(1)}
    </text>
  )
}

export default function FuelBarChart({ rows, mode = 'daily', voyageView = false }) {
  const data = buildData(rows, mode, voyageView)

  if (!data.length) return null

  const minChartWidth = data.length * 26

  const voyageRegions = []
  if (voyageView && data.length) {
    let currentV = null
    let startKey = null
    let endKey = null
    data.forEach(d => {
      if (d.isGap) return
      if (d.voyage !== currentV) {
        if (currentV !== null) {
          voyageRegions.push({ voyage: currentV, startKey, endKey })
        }
        currentV = d.voyage
        startKey = d.key
      }
      endKey = d.key
    })
    if (currentV !== null) {
      voyageRegions.push({ voyage: currentV, startKey, endKey })
    }
  }

  // HTML badge positions — account for XAxis padding so centres are accurate
  // Chart: margin.left=0, XAxis padding.left=26, padding.right=8, margin.right=10
  const xPadL    = 26
  const usable   = minChartWidth - 40 - xPadL - 8 - 10 // content minus Y-axis, xAxis padding, right margin
  const slotWidth = data.length > 0 ? usable / data.length : 0
  const voyageBadges = voyageRegions.length > 1
    ? voyageRegions.map((r, idx) => {
        const fi = data.findIndex(d => d.key === r.startKey)
        const li = data.findIndex(d => d.key === r.endKey)
        const regionWidth = (li - fi + 1) * slotWidth
        return { voyage: r.voyage, centerX: 40 + xPadL + ((fi + li) / 2 + 0.5) * slotWidth, regionWidth, idx }
      })
    : []

  return (
    <>

      <div style={{ position: 'relative', width: '100%', height: 260 }}>
        {/* 1) Scrollable Chart Area */}
        <div className="fuel-chart-scroll-container" style={{ width: '100%', overflowX: 'auto', overflowY: 'hidden', paddingBottom: '4px', height: 260 }}>
          <div style={{ position: 'relative', height: 245, minWidth: '100%', width: minChartWidth, paddingLeft: 40 }}>

            {/* Voyage badge overlay — HTML so it is never clipped by SVG */}
            {voyageBadges.map(b => (
              b.regionWidth >= 35 && (
                <span key={b.voyage} style={{
                  position: 'absolute', top: 4, left: b.centerX,
                  transform: 'translateX(-50%)',
                  background: V_FILLS[b.idx % V_FILLS.length],
                  border: `1px solid ${V_BORDERS[b.idx % V_BORDERS.length]}`,
                  color: V_COLORS[b.idx % V_COLORS.length],
                  borderRadius: 3, padding: '0px 5px',
                  fontSize: 10, fontWeight: 700,
                  whiteSpace: 'nowrap', fontFamily: 'Inter, sans-serif',
                  lineHeight: '15px', zIndex: 4, pointerEvents: 'none',
                }}>
                  {shortVoyageName(b.voyage)}
                </span>
              )
            ))}
            <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
              <BarChart data={data} margin={{ top: 45, right: 10, left: 0, bottom: 8 }} barSize={16}>
                {voyageRegions.map((r, idx) => {
                  const isSingle = voyageRegions.length === 1;
                  const bgColors = V_FILLS.map(f => f.replace('0.22', '0.12'))
                  const borderColors = V_BORDERS
                  const fillColor   = isSingle ? 'transparent' : bgColors[idx % bgColors.length]
                  const strokeColor = isSingle ? 'none'        : borderColors[idx % borderColors.length]
                  return (
                    <ReferenceArea
                      key={`area_${r.voyage}_${idx}`}
                      x1={r.startKey}
                      x2={r.endKey}
                      fill={fillColor}
                      stroke={strokeColor}
                      strokeWidth={1}
                    />
                  )
                })}
                <CartesianGrid strokeDasharray="3 3" stroke="#2d4a6a" vertical={false} />
                <XAxis
                  dataKey="key"
                  tickFormatter={(value, index) => data[index]?.label ?? value}
                  tick={{ fill: '#94a3b8', fontSize: 9.5 }}
                  tickLine={false}
                  axisLine={{ stroke: '#2d4a6a' }}
                  interval={0}
                  angle={-30}
                  textAnchor="end"
                  tickMargin={4}
                  height={50}
                  padding={{ left: 26, right: 8 }}
                />
                <YAxis hide />
                <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                <Legend content={() => <div />} height={24} />
                <Bar dataKey="ME FOC" fill="#d946ef" stackId="fuel" radius={[0,0,0,0]} />
                <Bar dataKey="AE FOC" fill="#38bdf8" stackId="fuel" radius={[2,2,0,0]}>
                  <LabelList dataKey="total" content={<TotalLabel />} />
                </Bar>
                {data.filter(d => d.isGap).map(gap => (
                  <ReferenceLine key={`ref_${gap.key}`} x={gap.key} stroke="#3d5a78" strokeWidth={2} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* 2) Sticky Y-Axis Overlay */}
        <div style={{ position: 'absolute', top: 0, left: 0, width: 40, height: 245, background: 'var(--bg-panel)', boxShadow: '2px 0 4px rgba(13,27,42,0.8)', zIndex: 10, pointerEvents: 'none' }}>
          <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
            <BarChart data={data} margin={{ top: 45, right: 0, left: 2, bottom: 8 }}>
              <Legend content={() => <div />} height={24} />
              <XAxis
                dataKey="key"
                height={50}
                tick={false}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: '#94a3b8', fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                width={36}
                tickFormatter={v => v.toFixed(0)}
              />
              {/* Invisible bars to force correct Y-Axis domain calculation */}
              <Bar dataKey="ME FOC" fill="transparent" stackId="fuel" isAnimationActive={false} />
              <Bar dataKey="AE FOC" fill="transparent" stackId="fuel" isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* 3) Sticky Legend Overlay */}
        <div style={{ position: 'absolute', bottom: 18, left: '50%', transform: 'translateX(-50%)', zIndex: 3, pointerEvents: 'none' }}>
           <div style={{ fontSize: 11, color: '#94a3b8', display: 'flex', gap: '16px', alignItems: 'center', background: 'var(--bg-panel)', padding: '2px 10px', borderRadius: 4 }}>
              <span><span style={{ backgroundColor: '#d946ef', display: 'inline-block', width: 10, height: 10, marginRight: 4, verticalAlign: 'middle' }} />ME FOC</span>
              <span><span style={{ backgroundColor: '#38bdf8', display: 'inline-block', width: 10, height: 10, marginRight: 4, verticalAlign: 'middle' }} />AE FOC</span>
           </div>
        </div>
      </div>
    </>
  )
}
