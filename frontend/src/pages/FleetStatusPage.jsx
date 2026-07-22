// =============================================================================
// FleetStatusPage.jsx
// Fleet Status Monitoring - mirrors the WNI SSM (https://vp.weathernews.com/#/ssm?top)
// Dark-navy MapLibre map + data table with Alert columns, CSV download
// =============================================================================

import { useState, useEffect, useRef, useCallback } from 'react'
import './FleetStatusPage.css'
// MapLibre is loaded from CDN in index.html to avoid Vite worker minification bugs (wm is not defined)
// Do NOT import maplibre-gl here — use window.maplibregl directly
const maplibregl = window.maplibregl
import { fetchFleetVoyages, fetchVesselTrack } from '../api/vesselApi'

// ── Helper: clean port name ──────────────────────────────────────────────────
function cleanPort(str) {
  if (!str || str === 'N/A' || str.toLowerCase() === 'null') return '-'
  return str.replace(/\s*\{[^}]*\}/g, '').trim() || '-'
}

// - Helper: safe display value --------------------------------------
function fmt(val, fallback = '-') {
  if (val === null || val === undefined) return fallback
  let s = String(val).trim()
  if (!s || s.toLowerCase() === 'null' || s.toLowerCase() === 'n/a') return fallback
  
  // Clean up mojibake that might exist in the database from earlier scrapes
  s = s.replace(/â€“/g, '-').replace(/â€”/g, '-')
  if (s === '-') return fallback // if it was purely a dash, return fallback
  
  return s
}

// ── Helper: format ISO/date string → WNI style (YYYY/MM/DD HH:MM) ───────────
// Handles both ISO strings and WNI's long format:
//   "Mon Jul 20 2026 10:01:42 GMT+0000 (Coordinated Universal Time)"
function formatDate(val, fallback = '-') {
  if (!val) return fallback
  const s = String(val).trim()
  if (!s || s.toLowerCase() === 'null' || s === '-') return fallback
  try {
    // WNI long format: strip the parenthetical timezone label so Date() can parse it
    const cleaned = s.replace(/\s*\([^)]*\)\s*$/, '').trim()
    const d = new Date(cleaned)
    if (isNaN(d.getTime())) return s   // unrecognised — show raw
    const y  = d.getUTCFullYear()
    const mo = String(d.getUTCMonth() + 1).padStart(2, '0')
    const dd = String(d.getUTCDate()).padStart(2, '0')
    const hh = String(d.getUTCHours()).padStart(2, '0')
    const mm = String(d.getUTCMinutes()).padStart(2, '0')
    return `${y}/${mo}/${dd} ${hh}:${mm}`
  } catch {
    return s
  }
}

// ── Helper: format Lat/Lon to DMS (e.g. 12° 34.5' N) ───────────
function formatLat(decimal, fallback = '-') {
  if (decimal === null || decimal === undefined || decimal === '') return fallback;
  const val = parseFloat(decimal);
  if (isNaN(val)) return fmt(decimal, fallback);
  const dir = val >= 0 ? 'N' : 'S';
  const abs = Math.abs(val);
  const deg = Math.floor(abs);
  const min = ((abs - deg) * 60).toFixed(1);
  return `${deg}° ${min}' ${dir}`;
}

function formatLon(decimal, fallback = '-') {
  if (decimal === null || decimal === undefined || decimal === '') return fallback;
  const val = parseFloat(decimal);
  if (isNaN(val)) return fmt(decimal, fallback);
  const dir = val >= 0 ? 'E' : 'W';
  const abs = Math.abs(val);
  const deg = Math.floor(abs).toString().padStart(3, '0');
  const min = ((abs - deg) * 60).toFixed(1);
  return `${deg}° ${min}' ${dir}`;
}

function formatDecimal(val, dec = 1, fallback = '-') {
  if (val === null || val === undefined || val === '') return fallback;
  const num = parseFloat(val);
  if (isNaN(num)) return fmt(val, fallback);
  return num.toFixed(dec);
}

// â”€â”€ Helper: status badge class â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function statusClass(status) {
  if (!status) return ''
  const s = status.toLowerCase()
  if (s.includes('run') || s.includes('underway') || s.includes('sailing')) return 'underway'
  if (s.includes('anchor') || s.includes('drift')) return 'anchor'
  if (s.includes('berth') || s.includes('port') || s.includes('moored')) return 'port'
  return ''
}

// ── Helper: detect if alert value is active ─────────────────────────────────
function isAlertActive(value) {
  if (!value) return false
  const s = String(value).trim().toLowerCase()
  return s !== '' && s !== '0' && s !== 'none' && s !== 'null' && s !== '-'
}

// ── Alert dot component - matches WNI colored circle indicators ─────────────
function AlertDot({ value }) {
  const active = isAlertActive(value)
  return (
    <span
      className={`fsm-alert-dot ${active ? 'active' : 'inactive'}`}
      title={active ? String(value) : 'No alert'}
    />
  )
}

// ── Excel export helper ────────────────────────────────────────────────────────
async function exportExcel(data) {
  const ExcelJS = (await import('exceljs')).default
  const { saveAs } = (await import('file-saver')).default

  const workbook = new ExcelJS.Workbook()
  const sheet = workbook.addWorksheet('Fleet Status', {
    views: [{ state: 'frozen', ySplit: 2, xSplit: 1 }]
  })

  // 1. Group Headers (Row 1)
  sheet.getRow(1).values = [
    'Detail', // A
    'Alert', '', '', '', '', '', // B-G (6 columns)
    'AIS Information', '', '', '', '', // H-L (5 columns)
    'Report Information', '', '', '', '', '', // M-R (6 columns)
    'General Information' // S-AJ (18 columns)
  ]

  // 2. Column Configurations (Row 2 headers and widths)
  sheet.columns = [
    // Detail (1)
    { header: 'Vessel Name', key: 'vessel_name', width: 22 },
    
    // Alert (6)
    { header: 'Port Alert', key: 'port_alert', width: 15 },
    { header: 'Coastal Storm', key: 'coastal_storm', width: 15 },
    { header: 'Ocean Storm', key: 'ocean_storm', width: 15 },
    { header: 'Tropical Cyclone', key: 'tropical_cyclone', width: 18 },
    { header: 'Pos Diff', key: 'pos_diff', width: 12 },
    { header: 'Report Missing', key: 'report_missing', width: 16 },
    
    // AIS Information (5)
    { header: 'Voyage No.', key: 'voyage_number', width: 14 },
    { header: 'Speed (kts)', key: 'speed', width: 12 },
    { header: 'Heading (deg)', key: 'heading', width: 14 },
    { header: 'Pos.Date', key: 'pos_date', width: 18 },
    { header: 'Status', key: 'status', width: 12 },
    
    // Report Information (6)
    { header: 'Last Port', key: 'last_port', width: 20 },
    { header: 'ETD', key: 'etd', width: 18 },
    { header: 'Next Port', key: 'next_port', width: 20 },
    { header: 'ETA', key: 'eta', width: 18 },
    { header: 'Lat', key: 'lat', width: 14 },
    { header: 'Lon', key: 'lon', width: 14 },
    
    // General Information (18)
    { header: 'IMO', key: 'imo', width: 12 },
    { header: 'Ship Type', key: 'ship_type', width: 18 },
    { header: 'Callsign', key: 'callsign', width: 12 },
    { header: 'Flag Code', key: 'flag_code', width: 14 },
    { header: 'Build Date', key: 'build_date', width: 12 },
    { header: 'Length(m)', key: 'length', width: 12 },
    { header: 'Breadth(m)', key: 'breadth', width: 12 },
    { header: 'Depth(m)', key: 'depth', width: 12 },
    { header: 'Draft(m)', key: 'draft', width: 12 },
    { header: 'DWT(tons)', key: 'dwt', width: 15 },
    { header: 'Gross Tonnage(tons)', key: 'gross_tonnage', width: 22 },
    { header: 'Engine Builder', key: 'engine_builder', width: 28 },
    { header: 'Power at MCR(kW)', key: 'power_mcr', width: 20 },
    { header: 'RPM at MCR', key: 'rpm_mcr', width: 15 },
    { header: 'TEU', key: 'teu', width: 10 },
    { header: 'Email', key: 'email', width: 22 },
    { header: 'Fax', key: 'fax', width: 18 },
    { header: 'Phone', key: 'phone', width: 20 }
  ]

  // 3. Merging Row 1 Group Headers
  sheet.mergeCells('B1:G1') // Alert
  sheet.mergeCells('H1:L1') // AIS Info
  sheet.mergeCells('M1:R1') // Report Info
  sheet.mergeCells('S1:AJ1') // General Info

  // 4. Styling Row 1 (Group Headers)
  const groupStyle = {
    font: { bold: true, color: { argb: 'FFFFFFFF' } },
    alignment: { horizontal: 'center', vertical: 'middle' },
    border: {
      bottom: { style: 'medium', color: { argb: 'FF000000' } },
      right: { style: 'thin', color: { argb: 'FF334155' } }
    }
  }

  const setGroupStyle = (cellRef, bgColor) => {
    const cell = sheet.getCell(cellRef)
    cell.value = cell.value // Re-assign to ensure it holds
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: bgColor } }
    cell.font = groupStyle.font
    cell.alignment = groupStyle.alignment
    cell.border = groupStyle.border
  }

  setGroupStyle('A1', 'FF1E293B') // Detail (Slate 800)
  setGroupStyle('B1', 'FF7F1D1D') // Alert (Red 900)
  setGroupStyle('H1', 'FF1E3A8A') // AIS Info (Blue 900)
  setGroupStyle('M1', 'FF14532D') // Report Info (Green 900)
  setGroupStyle('S1', 'FF334155') // General Info (Slate 700)

  // 5. Styling Row 2 (Column Headers)
  sheet.getRow(2).eachCell((cell) => {
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF0F172A' } } // Slate 900
    cell.font = { bold: true, color: { argb: 'FF94A3B8' } } // Slate 400
    cell.alignment = { vertical: 'middle', horizontal: 'left' }
    cell.border = { bottom: { style: 'thin', color: { argb: 'FF334155' } } }
  })
  
  // Make row 1 and 2 a bit taller
  sheet.getRow(1).height = 25
  sheet.getRow(2).height = 20

  // Helper for alert display (Yes or detail text instead of just boolean)
  const fmtAlert = (val) => {
    const v = String(val || '').trim().toLowerCase()
    if (v === 'null' || v === 'none' || v === 'false' || v === '0' || !v) return '-'
    return val
  }

  // 6. Append Data Rows
  data.forEach(r => {
    sheet.addRow({
      vessel_name: fmt(r.vessel_name),
      port_alert: fmtAlert(r.port_alert),
      coastal_storm: fmtAlert(r.coastal_storm),
      ocean_storm: fmtAlert(r.ocean_storm),
      tropical_cyclone: fmtAlert(r.tropical_cyclone),
      pos_diff: fmtAlert(r.pos_diff),
      report_missing: fmtAlert(r.report_missing),
      voyage_number: fmt(r.voyage_number),
      speed: formatDecimal(r.speed, 1),
      heading: formatDecimal(r.heading, 1),
      pos_date: formatDate(r.pos_date),
      status: fmt(r.status),
      last_port: cleanPort(r.last_port),
      etd: formatDate(r.etd),
      next_port: cleanPort(r.next_port),
      eta: formatDate(r.eta),
      lat: formatLat(r.lat),
      lon: formatLon(r.lon),
      imo: fmt(r.imo),
      ship_type: fmt(r.ship_type),
      callsign: fmt(r.callsign),
      flag_code: fmt(r.flag_code),
      build_date: fmt(r.build_date),
      length: fmt(r.length),
      breadth: fmt(r.breadth),
      depth: fmt(r.depth),
      draft: fmt(r.draft),
      dwt: fmt(r.dwt),
      gross_tonnage: fmt(r.gross_tonnage),
      engine_builder: fmt(r.engine_builder),
      power_mcr: fmt(r.power_mcr),
      rpm_mcr: fmt(r.rpm_mcr),
      teu: fmt(r.teu),
      email: fmt(r.email),
      fax: fmt(r.fax),
      phone: fmt(r.phone)
    })
  })

  // 7. Generate and Save File
  const buffer = await workbook.xlsx.writeBuffer()
  const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  saveAs(blob, `Fleet_Status_${new Date().toISOString().slice(0, 10)}.xlsx`)
}

// ── MapLibre Map Component ──────────────────────────────────────────────────
function MapLibreMap({ vessels, selectedVessel, onVesselClick }) {
  const mapContainerRef = useRef(null)
  const mapRef          = useRef(null)
  const markersRef      = useRef({})

  // Initialize map once
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return
    mapRef.current = new maplibregl.Map({
      container: mapContainerRef.current,
      style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
      center: [55.0, 10.0],
      zoom: 3,
      attributionControl: false,
    })
    mapRef.current.addControl(new maplibregl.NavigationControl(), 'top-right')
    mapRef.current.on('styledata', () => {
      const map = mapRef.current
      if (!map) return
      try {
        if (map.getLayer('water'))     map.setPaintProperty('water',     'fill-color', '#0a1628')
        if (map.getLayer('landcover')) map.setPaintProperty('landcover', 'fill-color', '#152238')
        if (map.getLayer('waterway'))  map.setPaintProperty('waterway',  'fill-color', '#0a1628')
      } catch (_) {}
    })
  }, [])

  // Rebuild markers whenever vessels list changes
  useEffect(() => {
    if (!mapRef.current || !vessels) return

    // Remove old markers
    Object.values(markersRef.current).forEach(m => m.remove())
    markersRef.current = {}

    const bounds = new maplibregl.LngLatBounds()
    let hasPoints = false

    vessels.forEach((v) => {
      const lat = parseFloat(v.lat)
      const lon = parseFloat(v.lon)
      if (!isFinite(lat) || !isFinite(lon)) return

      const heading = parseFloat(v.heading) || 0
      const vStatus = (v.status || '').toLowerCase()
      const hasAlert = isAlertActive(v.port_alert) || isAlertActive(v.coastal_storm) ||
                       isAlertActive(v.ocean_storm) || isAlertActive(v.tropical_cyclone) ||
                       isAlertActive(v.pos_diff)    || isAlertActive(v.report_missing)

      let color = '#38bdf8'   // cyan - underway default
      if (hasAlert)                                                       color = '#ef4444'
      else if (vStatus.includes('anchor') || vStatus.includes('drift'))  color = '#f59e0b'
      else if (vStatus.includes('berth')  || vStatus.includes('moored')) color = '#22c55e'

      // ── Marker element ──────────────────────────────────────────────────────
      const ICON_W = 14, ICON_H = 26;

      // wrapper: zero-size div — MapLibre anchors its top-left to [lon, lat].
      // All children are absolutely positioned and do NOT affect the wrapper's
      // bounding box, so the anchor calculation is stable at every zoom level.
      const wrapper = document.createElement('div')
      wrapper.style.cssText = 'position:relative;width:0;height:0;cursor:pointer;pointer-events:none;'
      wrapper.style.zIndex  = hasAlert ? '10' : '1'
      if (hasAlert) wrapper.classList.add('fsm-marker-alert')

      // iconDiv: the rotating ship SVG, offset so its bow tip sits at the anchor point.
      // transform-origin:'top center' = pivot at (ICON_W/2, 0) of iconDiv = the bow tip.
      const iconDiv = document.createElement('div')
      iconDiv.style.cssText = [
        `position:absolute`,
        `width:${ICON_W}px`,
        `height:${ICON_H}px`,
        `left:${-ICON_W / 2}px`,  // shift left so bow tip x = wrapper x = lon
        `top:0px`,                  // bow tip y = wrapper y = lat
        `transform:rotate(${heading}deg)`,
        `transform-origin:${ICON_W / 2}px 0px`,  // pivot exactly at the bow tip
        `pointer-events:auto`,
      ].join(';')
      iconDiv.innerHTML = `
        <svg width="${ICON_W}" height="${ICON_H}" viewBox="0 0 14 26" fill="none" xmlns="http://www.w3.org/2000/svg"
             style="filter:drop-shadow(0 1px 4px rgba(0,0,0,0.9))">
          <path fill-rule="evenodd" clip-rule="evenodd"
            d="M7 1C11 5.5 13 10 13 14V25H1V14C1 10 3 5.5 7 1Z"
            fill="${color}" stroke="#0f172a" stroke-width="1.2"/>
        </svg>`
      wrapper.appendChild(iconDiv)

      // labelDiv: floats to the right of the icon, independent of the rotation.
      const labelDiv = document.createElement('div')
      labelDiv.innerText = v.vessel_name
      labelDiv.className = 'fsm-marker-label'
      // Override inline to ensure it doesn't bleed into wrapper bounding box
      labelDiv.style.cssText = 'position:absolute;left:10px;top:-6px;pointer-events:none;white-space:nowrap;'
      wrapper.appendChild(labelDiv)

      const el = wrapper  // alias so the rest of the code is unchanged

      // ── Hover popup matching WNI style ──────────────────────────────────────
      const posDate    = v.pos_date ? formatDate(v.pos_date) : '-'
      const posStr     = `${formatLat(lat)}, ${formatLon(lon)}`
      const speedStr   = v.speed   != null ? `${formatDecimal(v.speed,   2)} kts`     : '-'
      const headingStr = v.heading != null ? `${formatDecimal(v.heading, 0)} degrees`  : '-'
      const pointType  = v.rep_type || 'AIS'

      const popupEl = document.createElement('div')
      popupEl.className = 'fsm-popup-inner'
      popupEl.innerHTML = `
        <div class="fsm-popup-title">${v.vessel_name}</div>
        <table class="fsm-popup-table">
          <tr><td class="fsm-popup-label">Pos.Date</td><td class="fsm-popup-val">${posDate}</td></tr>
          <tr><td class="fsm-popup-label">Position</td><td class="fsm-popup-val">${posStr}</td></tr>
          <tr><td class="fsm-popup-label">Speed</td><td class="fsm-popup-val">${speedStr}</td></tr>
          <tr><td class="fsm-popup-label">Heading</td><td class="fsm-popup-val">${headingStr}</td></tr>
          <tr><td class="fsm-popup-label">Point type</td><td class="fsm-popup-val">${pointType}</td></tr>
        </table>`

      const popup = new maplibregl.Popup({
        closeButton: false, closeOnClick: false,
        className: 'fsm-vessel-popup',
        // No fixed anchor — MapLibre auto-flips (top/bottom/left/right)
        // depending on available viewport space
        offset: 16,
      }).setDOMContent(popupEl)

      // anchor:'top-left' pins wrapper's top-left corner exactly to [lon,lat].
      // The iconDiv is already shifted left by ICON_W/2 so the bow tip = coordinate.
      const marker = new maplibregl.Marker({ element: el, anchor: 'top-left' }).setLngLat([lon, lat]).addTo(mapRef.current)

      el.addEventListener('mouseenter', () => popup.setLngLat(marker.getLngLat()).addTo(mapRef.current))
      el.addEventListener('mouseleave', () => popup.remove())
      el.addEventListener('click', (e) => { e.stopPropagation(); onVesselClick(v) })

      markersRef.current[v.imo] = marker
      bounds.extend([lon, lat])
      hasPoints = true
    })

    if (hasPoints) mapRef.current.fitBounds(bounds, { padding: 60, maxZoom: 7 })
  }, [vessels, onVesselClick])

  // On vessel selection: fly to vessel position + draw track
  useEffect(() => {
    if (!selectedVessel || !mapRef.current) return

    const vesselLat = parseFloat(selectedVessel.lat)
    const vesselLon = parseFloat(selectedVessel.lon)

    // Always fly to the vessel's actual DB position — never modify the marker position
    if (isFinite(vesselLat) && isFinite(vesselLon)) {
      mapRef.current.flyTo({ center: [vesselLon, vesselLat], zoom: 6, duration: 1200 })
    }

    if (!selectedVessel.imo) return

    const applyTrack = (map, data) => {
      try {
        // Only keep LineString features — skip individual Point (actual_point) features
        // so we draw clean route lines without thousands of dot markers
        const lineOnly = {
          type: 'FeatureCollection',
          features: data.features.filter(
            f => f.geometry && f.geometry.type === 'LineString'
          ),
        }

        if (map.getSource('vessel-track')) {
          map.getSource('vessel-track').setData(lineOnly)
        } else {
          map.addSource('vessel-track', { type: 'geojson', data: lineOnly })

          // Historical AIS track — white dashed line
          map.addLayer({
            id:     'vessel-track-actual',
            type:   'line',
            source: 'vessel-track',
            filter: ['==', ['get', 'routetype'], 'actual'],
            layout: { 'line-join': 'round', 'line-cap': 'round' },
            paint:  { 'line-color': '#ffffff', 'line-width': 2, 'line-dasharray': [2, 2] },
          })

          // Future / planned route — yellow dashed line
          map.addLayer({
            id:     'vessel-track-future',
            type:   'line',
            source: 'vessel-track',
            filter: ['in', ['get', 'routetype'], ['literal', ['future', 'intention']]],
            layout: { 'line-join': 'round', 'line-cap': 'round' },
            paint:  { 'line-color': '#eab308', 'line-width': 2, 'line-dasharray': [4, 4] },
          })

          // Any other route types — orange solid line
          map.addLayer({
            id:     'vessel-track-other',
            type:   'line',
            source: 'vessel-track',
            filter: ['!', ['in', ['get', 'routetype'], ['literal', ['actual', 'future', 'intention']]]],
            layout: { 'line-join': 'round', 'line-cap': 'round' },
            paint:  { 'line-color': '#f97316', 'line-width': 2 },
          })
        }
      } catch (e) {
        console.warn('Track layer error:', e)
      }
    }

    fetchVesselTrack(selectedVessel.imo)
      .then(data => {
        const map = mapRef.current
        if (!map) return
        // No marker snapping — vessel stays at its real DB lat/lon
        if (map.isStyleLoaded()) {
          applyTrack(map, data)
        } else {
          map.once('load', () => applyTrack(map, data))
        }
      })
      .catch(() => {
        const map = mapRef.current
        if (map?.getSource('vessel-track')) {
          map.getSource('vessel-track').setData({ type: 'FeatureCollection', features: [] })
        }
      })
  }, [selectedVessel])

  return <div ref={mapContainerRef} style={{ width: '100%', height: '100%' }} />
}

// ── Vessel Details Modal ─────────────────────────────────────────────────────
function VesselModal({ vessel, onClose }) {
  const [activeTab, setActiveTab] = useState('ais')
  if (!vessel) return null

  const tabs = [
    { id: 'ais',     label: 'AIS / Position' },
    { id: 'general', label: 'General Information' },
    { id: 'alerts',  label: 'Alerts' },
  ]

  return (
    <div className="fsm-modal-overlay" onClick={onClose}>
      <div className="fsm-modal" onClick={e => e.stopPropagation()}>

        <div className="fsm-modal-header">
          <div>
            <h2 className="fsm-modal-vessel-name">{vessel.vessel_name}</h2>
            <span className="fsm-modal-ship-type">
              {fmt(vessel.ship_type)} · IMO {fmt(vessel.imo)} · {fmt(vessel.callsign)}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className={`fsm-status ${statusClass(vessel.status)}`}>{vessel.status || '-'}</span>
            <button className="fsm-modal-close" onClick={onClose}>&times;</button>
          </div>
        </div>

        <div className="fsm-modal-tabs">
          {tabs.map(t => (
            <button key={t.id}
              className={`fsm-tab-btn${activeTab === t.id ? ' active' : ''}`}
              onClick={() => setActiveTab(t.id)}
            >{t.label}</button>
          ))}
        </div>

        <div className="fsm-modal-content">

          {activeTab === 'ais' && (
            <div className="fsm-tab-pane">
              <div className="fsm-info-grid">
                {[
                  ['Voyage No.',   fmt(vessel.voyage_number)],
                  ['Speed',        `${formatDecimal(vessel.speed, 1)} kn`],
                  ['Heading',      `${formatDecimal(vessel.heading, 1)}°`],
                  ['Status',       fmt(vessel.status)],
                  ['Position',     `${formatLat(vessel.lat)}, ${formatLon(vessel.lon)}`],
                  ['Pos. Date',    formatDate(vessel.pos_date)],
                  ['Last Port',    cleanPort(vessel.last_port)],
                  ['ETD',          formatDate(vessel.etd)],
                  ['Next Port',    cleanPort(vessel.next_port)],
                  ['ETA',          formatDate(vessel.eta)],
                  ['RTA',          formatDate(vessel.rta)],
                  ['Last Report',  `${fmt(vessel.rep_type)} @ ${formatDate(vessel.rep_time)}`],
                  ['Service',      fmt(vessel.service)],
                  ['DWT',          fmt(vessel.dwt)],
                ].map(([label, val]) => (
                  <div className="fsm-info-item" key={label}>
                    <span className="fsm-info-label">{label}</span>
                    <span className="fsm-info-value">{val}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'general' && (
            <div className="fsm-tab-pane">
              <div className="fsm-info-grid">
                {[
                  ['Build Date',        fmt(vessel.build_date)],
                  ['Length (m)',        fmt(vessel.length)],
                  ['Breadth (m)',       fmt(vessel.breadth)],
                  ['Depth (m)',         fmt(vessel.depth)],
                  ['Draft (m)',         fmt(vessel.draft)],
                  ['Gross Tonnage',     fmt(vessel.gross_tonnage)],
                  ['Engine Builder',    fmt(vessel.engine_builder)],
                  ['Power at MCR (kW)', fmt(vessel.power_mcr)],
                  ['RPM at MCR',        fmt(vessel.rpm_mcr)],
                  ['TEU',               fmt(vessel.teu)],
                  ['Email',             fmt(vessel.email)],
                  ['Fax',               fmt(vessel.fax)],
                  ['Phone',             fmt(vessel.phone)],
                ].map(([label, val]) => (
                  <div className="fsm-info-item" key={label}>
                    <span className="fsm-info-label">{label}</span>
                    <span className="fsm-info-value">{val}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'alerts' && (
            <div className="fsm-tab-pane">
              <div className="fsm-info-grid">
                {[
                  ['Port Alert',       vessel.port_alert],
                  ['Coastal Storm',    vessel.coastal_storm],
                  ['Ocean Storm',      vessel.ocean_storm],
                  ['Tropical Cyclone', vessel.tropical_cyclone],
                  ['Pos. Difference',  vessel.pos_diff],
                  ['Report Missing',   vessel.report_missing],
                ].map(([label, val]) => (
                  <div className="fsm-info-item" key={label}>
                    <span className="fsm-info-label">{label}</span>
                    <span className="fsm-info-value" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <AlertDot value={val} />
                      {isAlertActive(val)
                        ? <span style={{ color: '#fca5a5' }}>{val}</span>
                        : <span style={{ color: '#6b7280' }}>No alert</span>}
                    </span>
                  </div>
                ))}
              </div>
              {vessel.alert_detail && (
                <div className="fsm-alert-details-box" style={{ marginTop: 16 }}>
                  <h4>Alert Detail</h4>
                  <p>{vessel.alert_detail}</p>
                </div>
              )}
            </div>
          )}

        </div>
      </div>
    </div>
  )
}

// =============================================================================
// MAIN PAGE COMPONENT
// =============================================================================
export default function FleetStatusPage() {
  const [voyages,        setVoyages]        = useState([])
  const [loading,        setLoading]        = useState(true)
  const [lastUpdated,    setLastUpdated]    = useState(null)
  const [selectedVessel, setSelectedVessel] = useState(null)
  const [modalVessel,    setModalVessel]    = useState(null)
  const [search,         setSearch]         = useState('')
  const [sortCol,        setSortCol]        = useState(null)
  const [sortDir,        setSortDir]        = useState('asc')

  const handleSort = (col) => {
    if (sortCol === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortCol(col)
      setSortDir('asc')
    }
  }

  const sortIcon = (col) => {
    if (sortCol !== col) return ' ↕'
    return sortDir === 'asc' ? ' ↑' : ' ↓'
  }

  useEffect(() => {
    setLoading(true)
    fetchFleetVoyages()
      .then(data => {
        setVoyages(data)
        if (data.length > 0 && data[0].scraped_at) {
          const d = new Date(data[0].scraped_at)
          setLastUpdated(d.toLocaleString('en-GB', {
            day: '2-digit', month: 'short', year: 'numeric',
            hour: '2-digit', minute: '2-digit',
          }))
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  // Filter by search, then sort
  const displayedVoyages = (() => {
    let rows = voyages
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      rows = rows.filter(v =>
        (v.vessel_name || '').toLowerCase().includes(q) ||
        (v.imo        || '').toString().includes(q)
      )
    }
    if (sortCol) {
      rows = [...rows].sort((a, b) => {
        const av = a[sortCol] ?? ''
        const bv = b[sortCol] ?? ''
        const an = parseFloat(av), bn = parseFloat(bv)
        const cmp = (!isNaN(an) && !isNaN(bn))
          ? an - bn
          : String(av).localeCompare(String(bv))
        return sortDir === 'asc' ? cmp : -cmp
      })
    }
    return rows
  })()

  const mappableVessels = displayedVoyages.filter(v =>
    isFinite(parseFloat(v.lat)) && isFinite(parseFloat(v.lon))
  )

  const handleVesselClick = useCallback((v) => {
    setSelectedVessel(v)
  }, [])

  return (
    <div className="fsm-page">

      {/* ── Vessel Detail Modal ─────────────────────────────────────────────── */}
      <VesselModal vessel={modalVessel} onClose={() => setModalVessel(null)} />

      {/* ── Top bar ─────────────────────────────────────────────────────────── */}
      <div className="fsm-topbar">
        <div>
          <div className="fsm-title">Fleet Status Monitoring</div>
          <div className="fsm-subtitle">Powered by Weathernews</div>
        </div>
        {/* Search box */}
        <div className="fsm-search-wrap">
          <svg className="fsm-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            className="fsm-search-input"
            type="text"
            placeholder="Search vessel name / IMO…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          {search && (
            <button className="fsm-search-clear" onClick={() => setSearch('')}>✕</button>
          )}
        </div>
        <div className="fsm-spacer" />
        {lastUpdated && (
          <span className="fsm-last-updated">AIS Updated at {lastUpdated}</span>
        )}
        {voyages.length > 0 && (
          <button className="fsm-csv-btn" title="Download Excel" onClick={() => exportExcel(displayedVoyages)}>
            ⬇ Excel
          </button>
        )}
      </div>

      {/* ── Body ────────────────────────────────────────────────────────────── */}
      <div className="fsm-body">

        {/* Map */}
        <div className="fsm-map-card">
          <MapLibreMap
            vessels={mappableVessels}
            selectedVessel={selectedVessel}
            onVesselClick={handleVesselClick}
          />
        </div>

        {/* Table */}
        <div className="fsm-table-card">
          {loading ? (
            <div className="fsm-loading"><div className="fsm-spinner" /> Loading fleet data…</div>
          ) : voyages.length === 0 ? (
            <div className="fsm-empty">
              No fleet data available. Data will populate after the next pipeline run.
            </div>
          ) : (
            <table className="fsm-table">
              <thead>
                <tr>
                  <th rowSpan={2} className="fsm-th-detail">Detail</th>
                  <th rowSpan={2} className="fsm-th-vessel fsm-sortable" onClick={() => handleSort('vessel_name')}>
                    Vessel Name{sortIcon('vessel_name')}
                  </th>
                  <th colSpan={6} className="fsm-th-alert-group">Alert</th>
                  {/* AIS: 5 cols now includes Voyage No. */}
                  <th colSpan={5} className="fsm-th-ais-group">AIS Information</th>
                  <th colSpan={6} className="fsm-th-report-group">Report Information</th>
                  <th colSpan={18} className="fsm-th-general-group">General Information</th>
                </tr>
                <tr>
                  {/* Alert (6) */}
                  <th className="fsm-th-alert">Port Alert</th>
                  <th className="fsm-th-alert">Coastal Storm</th>
                  <th className="fsm-th-alert">Ocean Storm</th>
                  <th className="fsm-th-alert">Tropical Cyclone</th>
                  <th className="fsm-th-alert">Pos Diff</th>
                  <th className="fsm-th-alert">Report Missing</th>
                  {/* AIS Information (5) — added Voyage No. */}
                  <th className="fsm-th-ais fsm-sortable" onClick={() => handleSort('voyage_number')}>Voyage No.{sortIcon('voyage_number')}</th>
                  <th className="fsm-th-ais fsm-sortable" onClick={() => handleSort('speed')}>Speed (kts){sortIcon('speed')}</th>
                  <th className="fsm-th-ais fsm-sortable" onClick={() => handleSort('heading')}>Heading (deg){sortIcon('heading')}</th>
                  <th className="fsm-th-ais fsm-sortable" onClick={() => handleSort('pos_date')}>Pos.Date{sortIcon('pos_date')}</th>
                  <th className="fsm-th-ais fsm-sortable" onClick={() => handleSort('status')}>Status{sortIcon('status')}</th>
                  {/* Report Information (6) */}
                  <th className="fsm-th-report fsm-sortable" onClick={() => handleSort('last_port')}>Last Port{sortIcon('last_port')}</th>
                  <th className="fsm-th-report fsm-sortable" onClick={() => handleSort('etd')}>ETD{sortIcon('etd')}</th>
                  <th className="fsm-th-report fsm-sortable" onClick={() => handleSort('next_port')}>Next Port{sortIcon('next_port')}</th>
                  <th className="fsm-th-report fsm-sortable" onClick={() => handleSort('eta')}>ETA{sortIcon('eta')}</th>
                  <th className="fsm-th-report">Lat</th>
                  <th className="fsm-th-report">Lon</th>
                  {/* General Information (18) */}
                  <th className="fsm-th-general">IMO</th>
                  <th className="fsm-th-general">Ship Type</th>
                  <th className="fsm-th-general">Callsign</th>
                  <th className="fsm-th-general">Flag Code</th>
                  <th className="fsm-th-general fsm-sortable" onClick={() => handleSort('build_date')}>Build Date{sortIcon('build_date')}</th>
                  <th className="fsm-th-general">Length (m)</th>
                  <th className="fsm-th-general">Breadth (m)</th>
                  <th className="fsm-th-general">Depth (m)</th>
                  <th className="fsm-th-general">Draft (m)</th>
                  <th className="fsm-th-general fsm-sortable" onClick={() => handleSort('dwt')}>DWT (tons){sortIcon('dwt')}</th>
                  <th className="fsm-th-general">Gross Tonnage (tons)</th>
                  <th className="fsm-th-general">Engine Builder</th>
                  <th className="fsm-th-general">Power at MCR (kW)</th>
                  <th className="fsm-th-general">RPM at MCR</th>
                  <th className="fsm-th-general">TEU</th>
                  <th className="fsm-th-general">Email</th>
                  <th className="fsm-th-general">Fax</th>
                  <th className="fsm-th-general">Phone</th>
                </tr>
              </thead>
              <tbody>
                {displayedVoyages.map((v, i) => (
                  <tr
                    key={i}
                    className={selectedVessel?.vessel_name === v.vessel_name ? 'fsm-row-selected' : ''}
                    onClick={() => setSelectedVessel(v)}
                    title="Click to locate vessel on map"
                  >
                    <td className="fsm-detail-cell">
                      <button
                        className="fsm-detail-btn"
                        title={`View details: ${v.vessel_name}`}
                        onClick={e => { e.stopPropagation(); setModalVessel(v) }}
                      >
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
                          stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <rect x="3" y="3" width="18" height="18" rx="2"/>
                          <path d="M3 9h18M9 21V9"/>
                        </svg>
                      </button>
                    </td>
                    <td className="fsm-vessel-name">{v.vessel_name}</td>
                    {/* Alert */}
                    <td><AlertDot value={v.port_alert} /></td>
                    <td><AlertDot value={v.coastal_storm} /></td>
                    <td><AlertDot value={v.ocean_storm} /></td>
                    <td><AlertDot value={v.tropical_cyclone} /></td>
                    <td><AlertDot value={v.pos_diff} /></td>
                    <td><AlertDot value={v.report_missing} /></td>
                    {/* AIS Information — Voyage No. first */}
                    <td>{fmt(v.voyage_number)}</td>
                    <td>{formatDecimal(v.speed, 1)}</td>
                    <td>{formatDecimal(v.heading, 1)}</td>
                    <td className="fsm-pos-date">{formatDate(v.pos_date)}</td>
                    <td>
                      {v.status
                        ? <span className={`fsm-status ${statusClass(v.status)}`}>{v.status}</span>
                        : '-'}
                    </td>
                    {/* Report Information */}
                    <td>{cleanPort(v.last_port)}</td>
                    <td className="fsm-date-cell">{formatDate(v.etd)}</td>
                    <td>{cleanPort(v.next_port)}</td>
                    <td className="fsm-date-cell">{formatDate(v.eta)}</td>
                    <td>{formatLat(v.lat)}</td>
                    <td>{formatLon(v.lon)}</td>
                    {/* General Information */}
                    <td>{fmt(v.imo)}</td>
                    <td>{fmt(v.ship_type)}</td>
                    <td>{fmt(v.callsign)}</td>
                    <td>{fmt(v.flag_code)}</td>
                    <td>{fmt(v.build_date)}</td>
                    <td>{fmt(v.length)}</td>
                    <td>{fmt(v.breadth)}</td>
                    <td>{fmt(v.depth)}</td>
                    <td>{fmt(v.draft)}</td>
                    <td>{fmt(v.dwt)}</td>
                    <td>{fmt(v.gross_tonnage)}</td>
                    <td>{fmt(v.engine_builder)}</td>
                    <td>{fmt(v.power_mcr)}</td>
                    <td>{fmt(v.rpm_mcr)}</td>
                    <td>{fmt(v.teu)}</td>
                    <td>{fmt(v.email)}</td>
                    <td>{fmt(v.fax)}</td>
                    <td>{fmt(v.phone)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

      </div>
    </div>
  )
}

