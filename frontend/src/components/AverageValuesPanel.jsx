import { useState } from 'react'
import './AverageValuesPanel.css'

function sum(rows, key) {
  return rows.reduce((acc, r) => acc + (r[key] ?? 0), 0)
}
function avg(rows, key) {
  const valid = rows.filter(r => r[key] != null)
  if (!valid.length) return null
  return valid.reduce((a, r) => a + r[key], 0) / valid.length
}
function fmt(val, decimals = 2) {
  if (val == null || isNaN(val)) return '—'
  return val.toFixed(decimals)
}

export default function AverageValuesPanel({ rows }) {
  const [show24h, setShow24h] = useState(false)
  const n = rows.length || 1

  const totalME  = sum(rows, 'ME_FOC_MT')
  const totalAE  = sum(rows, 'AE_FOC_MT')
  const avgSOG   = avg(rows, 'SOG_kn')
  const avgPower = avg(rows, 'Shaft_Power_kW')
  const totalDist= sum(rows, 'Distance_nm')
  const avgSFOC  = avg(rows, 'SFOC_gkWh')
  const avgSpeedLoss = avg(rows, 'Speed_Loss_pct')
  const avgPowerDev  = avg(rows, 'Power_Dev_pct')

  const div = show24h ? n : 1

  const metrics = [
    { label: 'Total HFO / ME FOC (mt)', value: fmt(totalME / div) },
    { label: 'Total AE FOC (mt)',        value: fmt(totalAE / div) },
    { label: 'Avg SOG (kn)',             value: fmt(avgSOG) },
    { label: 'Avg Shaft Power (kW)',     value: fmt(avgPower) },
    { label: 'Total Distance (nm)',      value: fmt(totalDist / div, 1) },
    { label: 'Avg SFOC (g/kWh)',         value: fmt(avgSFOC) },
    { label: 'Avg Speed Loss (%)',       value: fmt(avgSpeedLoss) },
    { label: 'Avg Power Dev (%)',        value: fmt(avgPowerDev) },
  ]

  return (
    <div className="avg-panel">
      <div className="avg-panel-header">Average Values</div>

      <div className="avg-toggle-row">
        <span className="avg-toggle-label">Show 24h Average (mt/day)</span>
        <label className="toggle-switch">
          <input
            type="checkbox"
            checked={show24h}
            onChange={e => setShow24h(e.target.checked)}
          />
          <span className="toggle-track" />
        </label>
      </div>

      {metrics.map(({ label, value }) => (
        <div key={label} className="avg-row">
          <span className="avg-row-label">{label}</span>
          <span className={`avg-row-value ${value === '0.00' ? 'zero' : ''}`}>{value}</span>
        </div>
      ))}

      <hr className="avg-divider" />
      <div className="report-count">
        Display Report Count<br />
        <strong style={{ color: 'var(--text-primary)' }}>Report Count: {rows.length}</strong>
      </div>
    </div>
  )
}
