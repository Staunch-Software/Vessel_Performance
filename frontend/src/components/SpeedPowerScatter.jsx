import { useState, useEffect, useMemo } from 'react'
import {
  ComposedChart, Scatter, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, Legend,
} from 'recharts'
import { fetchSpeedPowerData, fetchSpeedPowerISO } from '../api/vesselApi'

// ── Tooltip ───────────────────────────────────────────────────────────────────
function SpTooltip({ active, payload, corrected }) {
  if (!active || !payload?.[0]?.payload) return null
  const d = payload[0].payload
  return (
    <div style={{
      background: '#1a2a3a', border: '1px solid #2d4a6a',
      padding: '7px 12px', borderRadius: 4, fontSize: 11,
    }}>
      <div style={{ color: '#94a3b8', marginBottom: 3 }}>
        {corrected ? 'ISO corrected' : (d.data_source === 'wni' ? 'WNI' : 'MariApps')} · {d.loading_condition}
      </div>
      <div style={{ color: '#e2e8f0' }}>
        {corrected ? 'STW_corr' : 'Speed'}: <strong style={{ color: '#38bdf8' }}>{d.speed?.toFixed(2)} kn</strong>
      </div>
      <div style={{ color: '#e2e8f0' }}>
        {corrected ? 'P_corr' : 'Power'}: <strong style={{ color: '#f59e0b' }}>{d.power?.toFixed(0)} kW</strong>
      </div>
    </div>
  )
}

// ── Source label mapping ──────────────────────────────────────────────────────
const SOURCE_LABELS = {
  sea_trials:              'Sea Trials (corrected)',
  vessel_particulars:      'Vessel Particulars (propeller law)',
  vessel_particulars_approx: 'Vessel Particulars (cubic approx.)',
}

// ── Main component ────────────────────────────────────────────────────────────
export default function SpeedPowerScatter({ vesselImo }) {
  const [cond,       setCond]     = useState('Laden')
  const [rawData,    setRawData]  = useState(null)
  const [isoData,    setIsoData]  = useState(null)   // ISO corrected data (preferred)
  const [loading,    setLoading]  = useState(false)
  const [error,      setError]    = useState(null)

  // Fetch ISO corrected first, fall back to raw if no ISO results
  useEffect(() => {
    if (!vesselImo) return
    setLoading(true)
    setError(null)

    // Try ISO corrected data first
    fetchSpeedPowerISO(vesselImo, cond)
      .then(data => {
        if (data.count > 0) {
          setIsoData(data)
          setRawData(null)
        } else {
          // No ISO results yet — fall back to raw expanded data
          setIsoData(null)
          return fetchSpeedPowerData(vesselImo, cond).then(setRawData)
        }
      })
      .catch(() => {
        setIsoData(null)
        // Fall back to raw
        fetchSpeedPowerData(vesselImo, cond)
          .then(setRawData)
          .catch(e => setError(e?.response?.data?.detail ?? e.message))
      })
      .finally(() => setLoading(false))
  }, [vesselImo, cond])

  // Use ISO data when available, raw data otherwise
  const activeData = isoData || rawData
  const isISO      = !!isoData

  const dotColor = cond === 'Laden' ? '#ef4444' : '#60a5fa'

  // ISO corrected: single set of dots; raw: split by source
  const isoPts = useMemo(() => isoData?.actual ?? [], [isoData])
  const { wniPts, maPts } = useMemo(() => {
    if (!rawData?.actual) return { wniPts: [], maPts: [] }
    return {
      wniPts: rawData.actual.filter(r => r.data_source === 'wni'),
      maPts:  rawData.actual.filter(r => r.data_source === 'mari_apps'),
    }
  }, [rawData])

  const baselinePts   = activeData?.baseline_points ?? []
  const baselineSource = activeData?.baseline_source ?? null
  const totalPts      = activeData?.count ?? 0

  // X/Y domain with padding
  const { xMin, xMax, yMax } = useMemo(() => {
    const all = activeData?.actual ?? []
    if (!all.length) return { xMin: 6, xMax: 18, yMax: 20000 }
    const speeds = all.map(r => r.speed)
    const powers = all.map(r => r.power)
    return {
      xMin: Math.max(0, Math.floor(Math.min(...speeds)) - 0.5),
      xMax: Math.ceil(Math.max(...speeds)) + 0.5,
      yMax: Math.ceil((Math.max(...powers) + 500) / 1000) * 1000,
    }
  }, [activeData])

  // ── States ────────────────────────────────────────────────────────────────
  if (!vesselImo) {
    return <div className="chart-empty">Select a vessel to view Speed-Power chart.</div>
  }
  if (loading) {
    return <div className="chart-empty"><div className="spinner" /> Loading speed-power data…</div>
  }
  if (error) {
    return <div className="chart-empty" style={{ color: '#f87171' }}>Error: {error}</div>
  }
  if (!activeData || totalPts === 0) {
    return (
      <div className="chart-empty">
        No speed-power data available for {cond} condition.
        <span style={{ fontSize: 10, color: '#456a8a', marginTop: 4, display: 'block' }}>
          {isISO
            ? 'Run ISO 19030 calculation to populate corrected data.'
            : 'Ensure expanded tables have ME power and speed columns filled.'}
        </span>
      </div>
    )
  }

  // ISO label for axes
  const xLabel = isISO ? 'STW_corr (kn)' : 'Speed (kn)'
  const yLabel = isISO ? 'P_corr (kW)'   : 'ME Power (kW)'

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>

      {/* ── Header ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 10px 2px', flexShrink: 0 }}>

        {/* Laden / Ballast toggle */}
        <div style={{ display: 'flex', border: '1px solid #2d4a6a', borderRadius: 6, overflow: 'hidden', flexShrink: 0 }}>
          {['Laden', 'Ballast'].map(c => (
            <button key={c} onClick={() => setCond(c)} style={{
              padding: '3px 14px', border: 'none', cursor: 'pointer',
              fontFamily: 'inherit', fontSize: 11, fontWeight: cond === c ? 700 : 400,
              background: cond === c
                ? (c === 'Laden' ? 'rgba(239,68,68,0.15)' : 'rgba(96,165,250,0.15)')
                : 'transparent',
              color: cond === c ? (c === 'Laden' ? '#ef4444' : '#60a5fa') : '#94a3b8',
              transition: 'all 0.12s',
            }}>{c}</button>
          ))}
        </div>

        {/* ISO badge */}
        {isISO && (
          <span style={{ background:'rgba(26,107,181,.2)', color:'#60a5fa',
            border:'1px solid #1a6bb5', borderRadius:10, padding:'1px 8px', fontSize:10, fontWeight:700 }}>
            ISO 19030
          </span>
        )}

        {/* Info */}
        <span style={{ fontSize: 11, color: '#94a3b8', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {cond} — {isISO ? 'STW_corr (kn) vs P_corr (kW)' : 'Speed (kn) vs ME Power (kW)'} &nbsp;
          <span style={{ color: '#64748b' }}>
            {totalPts} records
            {isISO && ' · weather-filtered PASS'}
            {baselineSource && ` · baseline: ${baselineSource}`}
            {!baselineSource && !isISO && ' · no baseline configured'}
          </span>
        </span>
      </div>

      {/* ── Chart ── */}
      <div style={{ flex: 1, minHeight: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart margin={{ top: 12, right: 24, bottom: 24, left: 56 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(45,74,106,0.35)" />

            <XAxis
              dataKey="speed"
              type="number"
              domain={[xMin, xMax]}
              tickFormatter={v => `${v} kn`}
              tick={{ fill: '#94a3b8', fontSize: 10 }}
              stroke="#2d4a6a"
              label={{ value: xLabel, position: 'insideBottomRight', offset: -8, fill: '#64748b', fontSize: 10 }}
            />

            <YAxis
              dataKey="power"
              type="number"
              domain={[0, yMax]}
              tickFormatter={v => `${(v / 1000).toFixed(0)}k`}
              tick={{ fill: '#94a3b8', fontSize: 10 }}
              stroke="#2d4a6a"
              label={{ value: yLabel, angle: -90, position: 'insideLeft', offset: -8, fill: '#64748b', fontSize: 10 }}
            />

            <Tooltip content={<SpTooltip corrected={isISO} />} />

            {/* ISO corrected scatter (single set) */}
            {isISO && isoPts.length > 0 && (
              <Scatter
                name={`${cond} ISO corrected`}
                data={isoPts}
                fill={dotColor}
                opacity={0.75}
                r={3.5}
              />
            )}

            {/* WNI scatter (raw fallback) */}
            {!isISO && wniPts.length > 0 && (
              <Scatter
                name="WNI"
                data={wniPts}
                fill={dotColor}
                opacity={0.7}
                r={3}
              />
            )}

            {/* MariApps scatter — raw fallback only */}
            {!isISO && maPts.length > 0 && (
              <Scatter
                name="MariApps"
                data={maPts}
                fill={cond === 'Laden' ? '#fb923c' : '#818cf8'}
                opacity={0.7}
                r={3}
              />
            )}

            {/* Baseline curve — shown for both ISO and raw */}
            {baselinePts.length > 0 && (
              <Line
                name={isISO ? `${activeData?.baseline_source ?? 'Baseline'}` : (SOURCE_LABELS[baselineSource] ?? 'Baseline')}
                data={baselinePts}
                dataKey="power"
                type="monotone"
                stroke="#34d399"
                strokeWidth={2}
                dot={false}
                activeDot={false}
                isAnimationActive={false}
              />
            )}

            <Legend
              wrapperStyle={{ fontSize: 10, color: '#94a3b8', paddingTop: 4 }}
              iconType="circle"
              iconSize={8}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
