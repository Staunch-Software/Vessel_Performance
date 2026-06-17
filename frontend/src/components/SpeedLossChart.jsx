import { useState, useMemo } from 'react'
import {
  ComposedChart, Scatter, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'

// ── Hardcoded baselines (per client request) ──────────────────────────────────
const BASELINES = {
  Laden:   { speed: 10.92, fuel: 22.46 },
  Ballast: { speed: 11.71, fuel: 22.96 },
}

const WAVE_MAX = 2.5   // m  — weather filter default

// ── Maths helpers ─────────────────────────────────────────────────────────────
function linReg(pts) {
  const n = pts.length
  if (n < 4) return null
  let sx = 0, sy = 0, sxy = 0, sx2 = 0
  for (const { x, y } of pts) { sx += x; sy += y; sxy += x * y; sx2 += x * x }
  const den = n * sx2 - sx * sx
  if (!den) return null
  const m = (n * sxy - sx * sy) / den
  const b = (sy - m * sx) / n
  return (x) => m * x + b
}

function quarterStarts(minMs, maxMs) {
  const dates = []
  const d = new Date(minMs)
  d.setUTCDate(1)
  d.setUTCMonth(Math.floor(d.getUTCMonth() / 3) * 3)
  d.setUTCHours(0, 0, 0, 0)
  while (d.getTime() <= maxMs) {
    dates.push(d.getTime())
    d.setUTCMonth(d.getUTCMonth() + 3)
  }
  return dates
}

// ── Custom dot for quarterly label on the trend line ─────────────────────────
function QuarterDot(props) {
  const { cx, cy, payload } = props
  if (!payload?.isQuarter || cx == null || cy == null) return null
  const label = (payload.y >= 0 ? '' : '') + payload.y.toFixed(1) + '%'
  return (
    <g>
      <circle cx={cx} cy={cy} r={4.5} fill="#38bdf8" stroke="none" />
      <text
        x={cx} y={cy - 10}
        textAnchor="middle"
        fontSize={10}
        fill="#38bdf8"
        fontWeight={700}
        fontFamily="Inter, sans-serif"
      >
        {label}
      </text>
    </g>
  )
}

// ── Tooltip ───────────────────────────────────────────────────────────────────
function SlTooltip({ active, payload }) {
  if (!active || !payload?.[0]?.payload) return null
  const { x, y } = payload[0].payload
  return (
    <div style={{
      background: '#1a2a3a', border: '1px solid #2d4a6a',
      padding: '7px 12px', borderRadius: 4, fontSize: 11,
    }}>
      <div style={{ color: '#94a3b8', marginBottom: 3 }}>
        {new Date(x).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}
      </div>
      <div style={{ color: '#e2e8f0' }}>
        Speed Loss:&nbsp;
        <strong style={{ color: y > 0 ? '#f87171' : '#34d399' }}>
          {y >= 0 ? '+' : ''}{y.toFixed(2)}%
        </strong>
      </div>
    </div>
  )
}

// ── X-axis tick formatter ─────────────────────────────────────────────────────
function fmtTick(ms) {
  return new Date(ms).toLocaleString('en', { month: 'short', year: '2-digit' })
}

// ── Main component ────────────────────────────────────────────────────────────
export default function SpeedLossChart({ rows }) {
  const [cond, setCond] = useState('Laden')
  const bl = BASELINES[cond]
  const dotColor = cond === 'Laden' ? '#ef4444' : '#60a5fa'

  // ── Filter rows ───────────────────────────────────────────────────────────
  const pts = useMemo(() => {
    return rows
      .filter(r => {
        const lc = (r.Loading_Cond ?? '').toLowerCase()
        const condMatch = cond === 'Laden'
          ? lc.startsWith('l') || lc === 'laden'
          : lc.startsWith('b') || lc === 'ballast'
        const waveOk  = r.Sig_Wave_Ht_m == null || +r.Sig_Wave_Ht_m <= WAVE_MAX
        const hasVal  = r.Speed_Loss_pct != null && !isNaN(+r.Speed_Loss_pct)
        const hasDate = r.Date != null
        return condMatch && waveOk && hasVal && hasDate
      })
      .map(r => ({ x: new Date(r.Date).getTime(), y: +r.Speed_Loss_pct }))
      .filter(p => isFinite(p.x) && isFinite(p.y))
      .sort((a, b) => a.x - b.x)
  }, [rows, cond])

  // ── Regression ───────────────────────────────────────────────────────────
  const predict = useMemo(() => linReg(pts), [pts])

  // ── Trend line data — includes quarterly points with isQuarter flag ────────
  const trendData = useMemo(() => {
    if (!predict || pts.length < 4) return []
    const xMin = pts[0].x
    const xMax = pts[pts.length - 1].x
    const qSet = new Set(quarterStarts(xMin, xMax))

    // Collect: endpoints + all quarter starts
    const allX = new Set([xMin, xMax, ...qSet])
    return [...allX]
      .sort((a, b) => a - b)
      .map(x => ({ x, y: predict(x), isQuarter: qSet.has(x) }))
  }, [predict, pts])

  // ── Y domain ─────────────────────────────────────────────────────────────
  const { yMin, yMax } = useMemo(() => {
    if (!pts.length) return { yMin: -30, yMax: 40 }
    const ys = pts.map(p => p.y)
    const mn = Math.min(...ys)
    const mx = Math.max(...ys)
    return {
      yMin: Math.floor((mn - 8) / 10) * 10,
      yMax: Math.ceil((mx + 8) / 10) * 10,
    }
  }, [pts])

  // ── Empty state ───────────────────────────────────────────────────────────
  if (!rows.length) return null
  if (!pts.length) {
    return (
      <div className="chart-empty">
        No weather-filtered Speed Loss data for {cond} condition.
      </div>
    )
  }

  const totalPts = pts.length

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>

      {/* ── Header ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '4px 10px 2px', flexShrink: 0,
      }}>
        {/* Laden / Ballast toggle */}
        <div style={{
          display: 'flex', border: '1px solid #2d4a6a',
          borderRadius: 6, overflow: 'hidden', flexShrink: 0,
        }}>
          {['Laden', 'Ballast'].map(c => (
            <button
              key={c}
              onClick={() => setCond(c)}
              style={{
                padding: '3px 14px', border: 'none', cursor: 'pointer',
                fontFamily: 'inherit', fontSize: 11, fontWeight: cond === c ? 700 : 400,
                background: cond === c
                  ? (c === 'Laden' ? 'rgba(239,68,68,0.15)' : 'rgba(96,165,250,0.15)')
                  : 'transparent',
                color: cond === c
                  ? (c === 'Laden' ? '#ef4444' : '#60a5fa')
                  : '#94a3b8',
                transition: 'all 0.12s',
              }}
            >{c}</button>
          ))}
        </div>

        {/* Title */}
        <span style={{
          fontSize: 11, color: '#94a3b8',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1,
        }}>
          {cond}&nbsp;— Power-Normalised Speed Loss % vs Date&nbsp;
          <span style={{ color: '#64748b' }}>
            (baseline&nbsp;{bl.speed}&nbsp;kn @{bl.fuel}&nbsp;MT&nbsp;|&nbsp;wave&nbsp;≤{WAVE_MAX}m&nbsp;|&nbsp;{totalPts}&nbsp;records)
          </span>
        </span>
      </div>

      {/* ── Chart ── */}
      <div style={{ flex: 1, minHeight: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart margin={{ top: 18, right: 24, bottom: 24, left: 48 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(45,74,106,0.35)" />

            <XAxis
              dataKey="x"
              type="number"
              scale="time"
              domain={['dataMin', 'dataMax']}
              tickFormatter={fmtTick}
              tick={{ fill: '#94a3b8', fontSize: 10 }}
              stroke="#2d4a6a"
              tickCount={14}
            />

            <YAxis
              tickFormatter={v => `${v}%`}
              tick={{ fill: '#94a3b8', fontSize: 10 }}
              stroke="#2d4a6a"
              domain={[yMin, yMax]}
            />

            <Tooltip content={<SlTooltip />} />

            {/* 0 % baseline */}
            <ReferenceLine
              y={0}
              stroke="rgba(148,163,184,0.3)"
              strokeDasharray="4 4"
            />

            {/* Daily scatter dots */}
            <Scatter
              data={pts}
              fill={dotColor}
              opacity={0.72}
              r={3.5}
              name={`${cond} PN Speed Loss (daily)`}
            />

            {/* Regression trend + quarterly labels */}
            <Line
              data={trendData}
              dataKey="y"
              type="linear"
              stroke="#cbd5e1"
              strokeWidth={2}
              dot={<QuarterDot />}
              activeDot={false}
              isAnimationActive={false}
              name={`Linear trend`}
              legendType="line"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
