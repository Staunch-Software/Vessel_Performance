import {
  ComposedChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer
} from 'recharts'

function fmt(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return `${d.toLocaleString('en', { month: 'short' })}-${String(d.getDate()).padStart(2,'0')}`
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: '#1a2a3a', border: '1px solid #2d4a6a',
      padding: '8px 12px', borderRadius: 4, fontSize: 12
    }}>
      <p style={{ color: '#94a3b8', marginBottom: 4 }}>{label}</p>
      {payload.map(p => (
        <p key={p.name} style={{ color: p.stroke, margin: '2px 0' }}>
          {p.name}: <strong>{p.value?.toFixed(2) ?? '—'}</strong>
        </p>
      ))}
    </div>
  )
}

export default function SpeedPowerChart({ rows }) {
  const data = [...rows]
    .sort((a, b) => new Date(a.Date) - new Date(b.Date))
    .map(r => ({
      date: fmt(r.Date),
      'SOG (kn)': r.SOG_kn ?? null,
      'Shaft Power (kW)': r.Shaft_Power_kW ?? null,
    }))

  if (!data.length) return null

  return (
    <ResponsiveContainer width="100%" height={190} minWidth={1} minHeight={1}>
      <ComposedChart data={data} margin={{ top: 4, right: 48, left: -10, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#2d4a6a" vertical={false} />
        <XAxis
          dataKey="date"
          tick={{ fill: '#94a3b8', fontSize: 10 }}
          tickLine={false}
          axisLine={{ stroke: '#2d4a6a' }}
        />
        <YAxis
          yAxisId="speed"
          tick={{ fill: '#38bdf8', fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          width={36}
          label={{ value: 'kn', angle: -90, position: 'insideLeft', fill: '#38bdf8', fontSize: 10 }}
        />
        <YAxis
          yAxisId="power"
          orientation="right"
          tick={{ fill: '#f59e0b', fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          width={44}
          label={{ value: 'kW', angle: 90, position: 'insideRight', fill: '#f59e0b', fontSize: 10 }}
        />
        <Tooltip content={<CustomTooltip />} />
        <Legend
          wrapperStyle={{ fontSize: 11, color: '#94a3b8', paddingTop: 4 }}
          iconType="line"
          iconSize={14}
        />
        <Line
          yAxisId="speed"
          type="monotone"
          dataKey="SOG (kn)"
          stroke="#38bdf8"
          dot={false}
          strokeWidth={2}
          connectNulls
        />
        <Line
          yAxisId="power"
          type="monotone"
          dataKey="Shaft Power (kW)"
          stroke="#f59e0b"
          dot={false}
          strokeWidth={2}
          connectNulls
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
