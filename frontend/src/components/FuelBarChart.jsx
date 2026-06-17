import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, LabelList,
} from 'recharts'

function fmt(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return `${d.toLocaleString('en', { month: 'short' })}-${String(d.getDate()).padStart(2,'0')}`
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  const total = payload.reduce((s, p) => s + (p.value ?? 0), 0)
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

export default function FuelBarChart({ rows }) {
  const data = [...rows]
    .sort((a, b) => new Date(a.Date) - new Date(b.Date))
    .map(r => {
      const me = r.ME_FOC_MT ?? 0
      const ae = r.AE_FOC_MT ?? 0
      return {
        date:    fmt(r.Date),
        'ME FOC': me,
        'AE FOC': ae,
        total:   me + ae,
      }
    })

  if (!data.length) return null

  return (
    <ResponsiveContainer width="100%" height={190}>
      <BarChart data={data} margin={{ top: 14, right: 8, left: -10, bottom: 0 }} barSize={12}>
        <CartesianGrid strokeDasharray="3 3" stroke="#2d4a6a" vertical={false} />
        <XAxis
          dataKey="date"
          tick={{ fill: '#94a3b8', fontSize: 10 }}
          tickLine={false}
          axisLine={{ stroke: '#2d4a6a' }}
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
