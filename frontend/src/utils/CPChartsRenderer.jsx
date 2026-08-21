import React, { useEffect, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import html2canvas from 'html2canvas';
import {
  ComposedChart, BarChart, Line, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine
} from 'recharts';

const RED_HEX    = '#e63946'
const GREEN_HEX  = '#2a9d5c'
const NAVY_HEX   = '#0a2463'
const LBLUE_HEX  = '#5aa9e6'
const DRED_HEX   = '#8b0000'
const ORANGE_HEX = '#e07b00'

/**
 * captureCPCharts
 * ---------------
 * Renders (off-screen) and rasterizes ONE combined page holding both Charter-
 * Party charts requested by the client's CP-Performance-Charts skill:
 *   A) Good-Weather speed & fuel/day vs CP warranty + allowance bands, for
 *      ONE loading condition only (the condition of `voyageNo`'s own row) —
 *      trended across this vessel's LAST 10 voyages in this condition, not
 *      just the ones selected for this particular report, so a single-voyage
 *      download still shows a meaningful multi-point trend.
 *   B) A diverging Time/Fuel Loss(-)/Saving(+) bar chart across this vessel's
 *      LAST 10 voyages, both conditions combined (never split by condition).
 *
 * `allCpData` should come from an UNFILTERED fetchCPPerformance call (no
 * voyages param) so both charts have full vessel history to slice the last
 * 10 from, regardless of what's selected in the report itself.
 *
 * Returns { chartsDataUrl, conditionLabel } — chartsDataUrl is null if there
 * wasn't enough data to build anything (e.g. no CP warranty configured).
 */
export function captureCPCharts(allCpData, voyageNo) {
  return new Promise((resolve) => {
    const rows = allCpData?.results || []
    if (!rows.length) { resolve({ chartsDataUrl: null, conditionLabel: null }); return }

    const div = document.createElement('div')
    div.style.position = 'absolute'
    div.style.top = '-9999px'
    div.style.left = '-9999px'
    document.body.appendChild(div)

    const root = createRoot(div)
    const handleComplete = (assets) => {
      setTimeout(() => { root.unmount(); div.remove(); resolve(assets) }, 100)
    }
    root.render(<CPChartsInner rows={rows} voyageNo={voyageNo} onComplete={handleComplete} />)
  })
}

function shortLabel(voyageNo, atd) {
  const v = String(voyageNo || '').replace(/^.*\bV\s*/i, 'V ').trim() || String(voyageNo || '')
  if (!atd || typeof atd !== 'string' || atd.length < 10) return v
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  const m = parseInt(atd.substring(5, 7), 10) - 1
  const day = atd.substring(8, 10)
  return `${v} ${day}-${months[m] || ''}`
}

// Round a step up to a "nice" 1/2/5×10^n number so axis ticks read as clean
// values instead of the raw floating-point results of *1.15 / padding math
// (which otherwise render as ugly strings like "66.952999999999").
function niceStep(raw) {
  if (raw <= 0) return 1
  const pow = Math.pow(10, Math.floor(Math.log10(raw)))
  const frac = raw / pow
  const niceFrac = frac <= 1 ? 1 : frac <= 2 ? 2 : frac <= 5 ? 5 : 10
  return niceFrac * pow
}

// Pads a domain heavily on ONE side so the data cluster visually sits in
// either the top or bottom portion of the shared plot area — this is the
// same technique the client's own Excel prototype uses (Speed fixed to
// [4,14], Fuel fixed to [30,70], even though each series' real data only
// spans a fraction of that), just computed per-vessel instead of hardcoded,
// with clean rounded tick numbers (niceStep) instead of raw floats.
// zone='top': heavy padding below / light padding above → data sits high.
// zone='bottom': heavy padding above / light padding below → data sits low.
function zoneDomain(vals, zone) {
  if (!vals.length) return [0, 1]
  const min = Math.min(...vals), max = Math.max(...vals)
  const range = Math.max(max - min, max * 0.05 || 1)
  const step = niceStep(range / 4)
  const HEAVY = 2.5, LIGHT = 0.3
  const [padLo, padHi] = zone === 'top' ? [HEAVY, LIGHT] : [LIGHT, HEAVY]
  // Neither speed nor fuel consumption can be negative — clamp instead of
  // letting a wide-ranging voyage's heavy padding push the axis into a
  // nonsensical negative region (e.g. "-20 kts").
  const lo = Math.max(Math.floor((min - range * padLo) / step) * step, 0)
  const hi = Math.ceil((max + range * padHi) / step) * step
  return [+lo.toFixed(2), +hi.toFixed(2)]
}

// Symmetric domain for the diverging bar chart, rounded to a nice step.
function symmetricNiceDomain(maxAbs) {
  const step = niceStep(maxAbs / 4)
  const bound = Math.ceil(maxAbs / step) * step
  return bound
}

const axisTickFmt = (v) => {
  const n = +v
  if (!isFinite(n)) return ''
  return Math.abs(n - Math.round(n)) < 0.001 ? String(Math.round(n)) : n.toFixed(1)
}

// Plain HTML legend, laid out in explicit rows — guarantees the item order the
// caller intends (Recharts' own <Legend> doesn't reliably preserve declaration
// order in v3, see usage sites for why this replaces it everywhere in this file).
function LineSwatchLegend({ rows }) {
  return (
    <div style={{ fontFamily: 'sans-serif', fontSize: '13px', marginTop: '4px' }}>
      {rows.map((row, ri) => (
        <div key={ri} style={{ textAlign: 'center', marginTop: ri > 0 ? '4px' : 0 }}>
          {row.map((item, ii) => (
            <span key={ii} style={{ marginRight: ii < row.length - 1 ? '22px' : 0, whiteSpace: 'nowrap' }}>
              <svg width="22" height="10" style={{ verticalAlign: 'middle', marginRight: '5px' }}>
                <line x1="0" y1="5" x2="22" y2="5" stroke={item.color} strokeWidth="2.5" strokeDasharray={item.dashed ? '5 3' : undefined} />
              </svg>
              <span style={{ verticalAlign: 'middle' }}>{item.label}</span>
            </span>
          ))}
        </div>
      ))}
    </div>
  )
}

function CPChartsInner({ rows, voyageNo, onComplete }) {
  const pageRef = useRef(null)

  // Condition for THIS report's voyage — only that condition's rows are plotted (Part A),
  // trended across this vessel's last 10 same-condition voyages (client request
  // 2026-08: full history was too cluttered to read).
  const primaryRow = rows.find(r => String(r.voyage_no) === String(voyageNo)) || rows[0]
  const primaryCond = primaryRow?.loading_cond || null
  const condRows = (primaryCond ? rows.filter(r => r.loading_cond === primaryCond) : rows)
    .slice().sort((a, b) => String(a.atd || '').localeCompare(String(b.atd || '')))
    .slice(-10)

  const condData = condRows.map(r => {
    const tolKn  = r.allowance?.speed_kn != null ? +r.allowance.speed_kn : 0.5
    const tolPct = r.allowance?.cons_pct != null ? +r.allowance.cons_pct : 5.0
    const cpSpeed = +(r.warranty?.speed_kn || 0)
    const cpFo    = +(r.warranty?.fo_mtpd || 0)
    const minAllowSpeed = cpSpeed ? cpSpeed - tolKn : null
    const maxAllowFo    = cpFo ? cpFo * (1 + tolPct / 100) : null
    const gwSpeed = r.good_wx?.avg_speed_kn ?? null
    const gwFo    = r.good_wx?.daily_fo ?? null
    return {
      label: shortLabel(r.voyage_no, r.atd),
      cpSpeed, minAllowSpeed, gwSpeed, cpFo, maxAllowFo, gwFo,
      speedOk: gwSpeed != null && minAllowSpeed != null ? gwSpeed >= minAllowSpeed : null,
      fuelOk:  gwFo != null && maxAllowFo != null ? gwFo <= maxAllowFo : null,
    }
  })

  const speedVals = condData.flatMap(d => [d.cpSpeed, d.minAllowSpeed, d.gwSpeed]).filter(v => v != null && !isNaN(v))
  const fuelVals  = condData.flatMap(d => [d.cpFo, d.maxAllowFo, d.gwFo]).filter(v => v != null && !isNaN(v))
  const speedDomain = zoneDomain(speedVals, 'top')
  const fuelDomain  = zoneDomain(fuelVals, 'bottom')

  // Part B — combined Time/Fuel Loss(-)/Saving(+), last 10 voyages, both
  // conditions together (never split by condition — see cp_calculator).
  const lossData = rows
    .slice().sort((a, b) => String(a.atd || '').localeCompare(String(b.atd || '')))
    .slice(-10)
    .map(r => ({
      label: shortLabel(r.voyage_no, r.atd),
      timeSave: -(r.loss?.time_h ?? 0),
      fuelSave: -((r.loss?.fo_mt ?? 0) + (r.loss?.dogo_mt ?? 0)),
    }))
  const maxAbsTime = symmetricNiceDomain(Math.max(1, ...lossData.map(d => Math.abs(d.timeSave))) * 1.15)
  const maxAbsFuel = symmetricNiceDomain(Math.max(1, ...lossData.map(d => Math.abs(d.fuelSave))) * 1.15)

  useEffect(() => {
    const timer = setTimeout(async () => {
      try {
        const canvas = pageRef.current ? await html2canvas(pageRef.current, { scale: 2, useCORS: true, logging: false }) : null
        onComplete({
          chartsDataUrl: canvas ? canvas.toDataURL('image/jpeg', 0.95) : null,
          conditionLabel: primaryCond,
        })
      } catch (err) {
        console.error('Failed to capture CP charts', err)
        onComplete({ chartsDataUrl: null, conditionLabel: primaryCond })
      }
    }, 1300)
    return () => clearTimeout(timer)
  }, [onComplete]) // eslint-disable-line react-hooks/exhaustive-deps

  const condTitle = `${primaryCond === 'Ballast' ? 'Ballast' : 'Laden'} — Good-Weather Speed & Fuel/Day vs CP Warranty (Last 10 Voyages)`
  // Same "X to Y (Economical speed)" route caption shown on the cover page and
  // Section A — repeated here too so this page identifies its own voyage
  // without needing to flip to page 3 (sourced from the report's own primary
  // row, same departure_port/arrival_port used in the CP table itself).
  const routeCaption = primaryRow
    ? `${primaryRow.departure_port || '—'} to ${primaryRow.arrival_port || '—'} (Economical speed)`
    : null

  return (
    <div ref={pageRef} style={{ width: '1000px', height: '1500px', padding: '20px', background: 'white', color: '#000', boxSizing: 'border-box' }}>
      <h2 style={{ textAlign: 'center', fontFamily: 'sans-serif', margin: '0 0 4px', color: '#000', fontWeight: 'bold', fontSize: '20px' }}>
        Charter-Party Performance Charts
      </h2>
      {routeCaption && (
        <p style={{ textAlign: 'center', fontFamily: 'sans-serif', margin: '0 0 4px', color: '#000', fontWeight: 'bold', fontSize: '13px' }}>
          {routeCaption}
        </p>
      )}
      <p style={{ textAlign: 'center', fontFamily: 'sans-serif', margin: '0 0 20px', color: '#444', fontSize: '12px' }}>
        Solid = actual / warranty &nbsp;·&nbsp; Dotted = allowance band &nbsp;·&nbsp; Markers coloured green (within allowance) / red (outside allowance)
      </p>

      {/* Chart A */}
      <h4 style={{ textAlign: 'center', fontFamily: 'sans-serif', margin: '0 0 6px', color: '#000', fontWeight: 'bold', fontSize: '15px' }}>{condTitle}</h4>
      <div style={{ height: '580px', width: '100%' }}>
        <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
          <ComposedChart data={condData} margin={{ top: 24, right: 65, left: 60, bottom: 30 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" tick={{ fontSize: 13, fill: '#000' }} angle={-20} textAnchor="end" height={50} />
            <YAxis yAxisId="speed" domain={speedDomain} tickFormatter={axisTickFmt} tick={{ fontSize: 13, fill: '#000' }}
              label={{ value: 'Speed (kts)', angle: -90, position: 'insideLeft', fill: '#000', fontSize: 13 }} />
            <YAxis yAxisId="fuel" orientation="right" domain={fuelDomain} tickFormatter={axisTickFmt} tick={{ fontSize: 13, fill: '#000' }}
              label={{ value: 'Fuel (mt/day)', angle: 90, position: 'insideRight', fill: '#000', fontSize: 13 }} />
            <Tooltip />
            {/* No <Legend> here — Recharts v3 doesn't reliably preserve series
                declaration order in its auto-generated legend (renders items in a
                scrambled order unrelated to JSX order or axis grouping), which read
                as visually "misaligned"/confusing. A plain HTML legend below the
                chart, in two clearly-grouped rows (Speed / Fuel), replaces it. */}
            <Line yAxisId="speed" type="monotone" dataKey="cpSpeed" name="CP Warr Speed" stroke={NAVY_HEX} strokeWidth={2.5} dot={false} isAnimationActive={false} />
            <Line yAxisId="speed" type="monotone" dataKey="minAllowSpeed" name="Min Allow Speed" stroke={LBLUE_HEX} strokeWidth={2} strokeDasharray="6 4" dot={false} isAnimationActive={false} />
            <Line yAxisId="speed" type="monotone" dataKey="gwSpeed" name="GW Avg Speed (actual)" stroke="#444" strokeWidth={2.5}
              dot={(props) => {
                const { cx, cy, payload, index } = props
                const ok = payload.speedOk
                const fill = ok == null ? '#888' : (ok ? GREEN_HEX : RED_HEX)
                return <circle key={`sp-${index}`} cx={cx} cy={cy} r={6} fill={fill} stroke="#000" strokeWidth={0.5} />
              }}
              isAnimationActive={false} />
            <Line yAxisId="fuel" type="monotone" dataKey="cpFo" name="CP Warr FO/d" stroke={DRED_HEX} strokeWidth={2.5} dot={false} isAnimationActive={false} />
            <Line yAxisId="fuel" type="monotone" dataKey="maxAllowFo" name="Max Allow FO/d" stroke={ORANGE_HEX} strokeWidth={2} strokeDasharray="6 4" dot={false} isAnimationActive={false} />
            <Line yAxisId="fuel" type="monotone" dataKey="gwFo" name="GW Daily FO (actual)" stroke="#666" strokeWidth={2.5}
              dot={(props) => {
                const { cx, cy, payload, index } = props
                const ok = payload.fuelOk
                const fill = ok == null ? '#888' : (ok ? GREEN_HEX : RED_HEX)
                return <rect key={`fo-${index}`} x={cx - 5} y={cy - 5} width={10} height={10} fill={fill} stroke="#000" strokeWidth={0.5} />
              }}
              isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <LineSwatchLegend rows={[
        [
          { color: NAVY_HEX, dashed: false, label: 'CP Warr Speed' },
          { color: LBLUE_HEX, dashed: true, label: 'Min Allow Speed' },
          { color: '#444', dashed: false, label: 'GW Avg Speed (actual)' },
        ],
        [
          { color: DRED_HEX, dashed: false, label: 'CP Warr FO/d' },
          { color: ORANGE_HEX, dashed: true, label: 'Max Allow FO/d' },
          { color: '#666', dashed: false, label: 'GW Daily FO (actual)' },
        ],
      ]} />

      {/* Chart B */}
      <h4 style={{ textAlign: 'center', fontFamily: 'sans-serif', margin: '24px 0 2px', color: '#000', fontWeight: 'bold', fontSize: '15px' }}>
        Time & Fuel Loss/Saving — Last 10 Voyages (all conditions)
      </h4>
      <p style={{ textAlign: 'center', fontFamily: 'sans-serif', margin: '0 0 6px', color: '#444', fontSize: '12px' }}>
        Green = Saving, Red = Loss &nbsp;|&nbsp; Left bar (solid) Time (h), Right bar (shaded) Fuel FO+DO/GO (mt)
      </p>
      <div style={{ height: '580px', width: '100%' }}>
        <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
          <BarChart data={lossData} margin={{ top: 24, right: 65, left: 60, bottom: 30 }}>
            {/* Time bar = solid fill. Fuel bar = diagonal-hatch pattern, same
                green/red sign colour — so the two bars are distinguishable by
                texture alone, not just position/axis (client request). */}
            <defs>
              <pattern id="fuelHatchGreen" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
                <rect width="6" height="6" fill={GREEN_HEX} fillOpacity="0.35" />
                <line x1="0" y1="0" x2="0" y2="6" stroke={GREEN_HEX} strokeWidth="2.5" />
              </pattern>
              <pattern id="fuelHatchRed" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
                <rect width="6" height="6" fill={RED_HEX} fillOpacity="0.35" />
                <line x1="0" y1="0" x2="0" y2="6" stroke={RED_HEX} strokeWidth="2.5" />
              </pattern>
            </defs>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" tick={{ fontSize: 12, fill: '#000' }} angle={-20} textAnchor="end" height={50} tickLine={false} />
            <YAxis yAxisId="time" domain={[-maxAbsTime, maxAbsTime]} tickFormatter={axisTickFmt} tick={{ fontSize: 13, fill: '#000' }}
              label={{ value: 'Time (h)', angle: -90, position: 'insideLeft', fill: '#000', fontSize: 13 }} />
            <YAxis yAxisId="fuel" orientation="right" domain={[-maxAbsFuel, maxAbsFuel]} tickFormatter={axisTickFmt} tick={{ fontSize: 13, fill: '#000' }}
              label={{ value: 'Fuel (mt)', angle: 90, position: 'insideRight', fill: '#000', fontSize: 13 }} />
            <ReferenceLine yAxisId="time" y={0} stroke="#666" />
            <Tooltip />
            {/* No <Legend> here on purpose — Recharts v3's payload override doesn't
                take effect for a custom Saving/Loss legend (falls back to the raw
                series names), and a per-series legend would be misleading anyway
                since colour here encodes sign, not which bar is which. The caption
                above the chart already states the Green/Red + Left/Right convention;
                a plain HTML swatch legend below reinforces it without that bug. */}
            <Bar yAxisId="time" dataKey="timeSave" name="Time Saving(+)/Loss(-) h" isAnimationActive={false}>
              {lossData.map((d, i) => <Cell key={i} fill={d.timeSave >= 0 ? GREEN_HEX : RED_HEX} />)}
            </Bar>
            <Bar yAxisId="fuel" dataKey="fuelSave" name="Fuel Saving(+)/Loss(-) mt" isAnimationActive={false}>
              {lossData.map((d, i) => <Cell key={i} fill={d.fuelSave >= 0 ? 'url(#fuelHatchGreen)' : 'url(#fuelHatchRed)'} stroke={d.fuelSave >= 0 ? GREEN_HEX : RED_HEX} strokeWidth={1} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div style={{ textAlign: 'center', fontFamily: 'sans-serif', fontSize: '13px', marginTop: '6px' }}>
        <span style={{ display: 'inline-block', width: '12px', height: '12px', background: GREEN_HEX, marginRight: '6px', verticalAlign: 'middle' }} />
        <span style={{ verticalAlign: 'middle', marginRight: '18px' }}>Saving</span>
        <span style={{ display: 'inline-block', width: '12px', height: '12px', background: RED_HEX, marginRight: '6px', verticalAlign: 'middle' }} />
        <span style={{ verticalAlign: 'middle' }}>Loss</span>
      </div>
      {/* Second legend row: what the FILL STYLE means (solid vs shaded), separate
          from the row above (what the COLOUR means). Neutral grey swatches so
          this isn't confused with the green/red sign coding. */}
      <div style={{ textAlign: 'center', fontFamily: 'sans-serif', fontSize: '13px', marginTop: '4px' }}>
        <span style={{ display: 'inline-block', width: '12px', height: '12px', background: '#666', marginRight: '6px', verticalAlign: 'middle' }} />
        <span style={{ verticalAlign: 'middle', marginRight: '18px' }}>Time (solid)</span>
        <svg width="14" height="14" style={{ verticalAlign: 'middle', marginRight: '6px' }}>
          <defs>
            <pattern id="legendHatchGrey" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
              <rect width="6" height="6" fill="#666" fillOpacity="0.35" />
              <line x1="0" y1="0" x2="0" y2="6" stroke="#666" strokeWidth="2.5" />
            </pattern>
          </defs>
          <rect width="14" height="14" fill="url(#legendHatchGrey)" stroke="#666" strokeWidth="1" />
        </svg>
        <span style={{ verticalAlign: 'middle' }}>Fuel (shaded)</span>
      </div>
    </div>
  )
}
