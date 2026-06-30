import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, LabelList,
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
function filterUnderway(rows) {
  const byVoyage = {}
  for (const r of rows) {
    const key = r.Voyage_No ?? '∅'
    ;(byVoyage[key] ||= []).push(r)
  }
  const out = []
  for (const group of Object.values(byVoyage)) {
    const sorted = [...group].sort((a, b) =>
      (new Date(a.Date) - new Date(b.Date)) ||
      String(a.Time_UTC ?? '').localeCompare(String(b.Time_UTC ?? ''))
    )
    const hasBOSP = sorted.some(r => {
      const u = (r.event_type ?? '').toUpperCase()
      return u.includes('BOSP') || u.includes('COSP')
    })
    if (hasBOSP) {
      let underway = false
      for (const r of sorted) {
        const u = (r.event_type ?? '').toUpperCase()
        const isBOSP = u.includes('BOSP') || u.includes('COSP')
        const isEOSP = u.includes('EOSP')
        if (isBOSP)        { underway = true;  out.push(r) }
        else if (isEOSP)   { out.push(r);      underway = false }
        else if (underway) { out.push(r) }
      }
    } else {
      // No sea-passage markers — exclude obvious port-side events
      for (const r of sorted) {
        if (!PORT_EVENT_RE.test((r.event_type ?? '').toUpperCase())) out.push(r)
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
function buildData(rows, mode) {
  if (mode === 'event') {
    return [...rows]
      .sort((a, b) =>
        (new Date(a.Date) - new Date(b.Date)) ||
        String(a.Time_UTC ?? '').localeCompare(String(b.Time_UTC ?? ''))
      )
      .map((r, i) => {
        const me = r.ME_FOC_MT ?? 0
        const ae = r.AE_FOC_MT ?? 0
        const ab = eventAbbr(r.event_type)
        return {
          key:     `e${i}`,                                // non-numeric unique key → correct tooltip/cursor
          label:   `${fmt(r.Date)}${ab ? '  ' + ab : ''}`, // clean display label
          'ME FOC': me,
          'AE FOC': ae,
          total:   me + ae,
        }
      })
  }

  const source = mode === 'underway' ? filterUnderway(rows) : rows
  // Daily aggregation (sum per calendar date)
  const byDate = {}
  for (const r of source) {
    if (!r.Date) continue
    const key = r.Date.slice(0, 10)
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

const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null
  const total = payload.reduce((s, p) => s + (p.value ?? 0), 0)
  const label = payload[0]?.payload?.label ?? ''
  return (
    <div style={{
      background: '#1a2a3a', border: '1px solid #2d4a6a',
      padding: '8px 12px', borderRadius: 4, fontSize: 12,
    }}>
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

// Custom label showing total on top of stacked bar
function TotalLabel(props) {
  const { x, y, width, value } = props
  if (!value || value === 0) return null
  return (
    <text
      x={x + width / 2}
      y={y - 3}
      fill="#94a3b8"
      textAnchor="middle"
      fontSize={9}
      fontFamily="Inter, sans-serif"
    >
      {value.toFixed(1)}
    </text>
  )
}

export default function FuelBarChart({ rows, mode = 'daily' }) {
  const data = buildData(rows, mode)

  if (!data.length) return null

  return (
    <ResponsiveContainer width="100%" height={205}>
      <BarChart data={data} margin={{ top: 14, right: 10, left: 2, bottom: 8 }} barSize={12}>
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
        <YAxis
          tick={{ fill: '#94a3b8', fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          width={36}
          tickFormatter={v => v.toFixed(0)}
        />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
        <Legend
          wrapperStyle={{ fontSize: 11, color: '#94a3b8', paddingTop: 4 }}
          iconType="square"
          iconSize={10}
        />
        {/* Stacked bars — combined height = total fuel */}
        <Bar dataKey="ME FOC" fill="#d946ef" stackId="fuel" radius={[0,0,0,0]} />
        <Bar dataKey="AE FOC" fill="#38bdf8" stackId="fuel" radius={[2,2,0,0]}>
          {/* Total label on top of the stacked bar */}
          <LabelList dataKey="total" content={<TotalLabel />} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
