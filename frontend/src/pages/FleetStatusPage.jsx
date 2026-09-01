// =============================================================================
// FleetStatusPage.jsx
// Fleet Status Monitoring - mirrors the WNI SSM (https://vp.weathernews.com/#/ssm?top)
// Dark-navy MapLibre map + data table with Alert columns, CSV download
// =============================================================================

import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import './FleetStatusPage.css'
// MapLibre is loaded from CDN in index.html to avoid Vite worker minification bugs (wm is not defined)
// Do NOT import maplibre-gl here — use window.maplibregl directly
// Use a getter so it is evaluated lazily (after CDN script has loaded)
const getMaplibre = () => window.maplibregl
import { fetchFleetVoyages, fetchVesselTrack } from '../api/vesselApi'
import { memoryStore } from '../utils/memoryStore'

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

// ── Alert dot component - matches WNI colored circle indicators ─────────────────────
function AlertDot({ value }) {
  const active = isAlertActive(value)
  return (
    <span
      className={`fsm-alert-dot ${active ? 'active' : 'inactive'}`}
      title={active ? String(value) : 'No alert'}
    />
  )
}

// ── Port Source Badge ─────────────────────────────────────────────────────────────────────
// Small pill badge showing whether port/ETA data comes from MA or WNI.
// Shown next to Last Port and Next Port cells.
function PortSourceBadge({ source }) {
        display: 'inline-block',
        marginLeft: 5,
        padding: '1px 5px',
        borderRadius: 3,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: '0.04em',
        color,
        background: bg,
        border: `1px solid ${color}55`,
        verticalAlign: 'middle',
        lineHeight: '14px',
      }}
    >
      {label}
    </span>
  )
}

// ── Excel export helper ────────────────────────────────────────────────────────
async function exportExcel(data) {
  const ExcelJS = (await import('exceljs')).default
  const { saveAs } = (await import('file-saver')).default

  const workbook = new ExcelJS.Workbook()
  const sheet = workbook.addWorksheet('Fleet Status', {
    views: [{ state: 'frozen', ySplit: 2, xSplit: 1 }] // freeze Vessel Name col + 2 header rows
  })

  // 1. Define column widths and keys ONLY — no header (header writes to row 1 and conflicts)
  sheet.columns = [
    { key: 'vessel_name',        width: 22 }, // A
    { key: 'port_alert',         width: 14 }, // B
    { key: 'coastal_storm',      width: 15 }, // C
    { key: 'ocean_storm',        width: 14 }, // D
    { key: 'tropical_cyclone',   width: 18 }, // E
    { key: 'pos_diff',           width: 12 }, // F
    { key: 'voyage_number',      width: 14 }, // G
    { key: 'speed',              width: 12 }, // H
    { key: 'heading',            width: 14 }, // I
    { key: 'pos_date',           width: 20 }, // J
    { key: 'status',             width: 14 }, // K
    { key: 'last_port',          width: 20 }, // L
    { key: 'etd',                width: 20 }, // M
    { key: 'next_port',          width: 20 }, // N
    { key: 'eta',                width: 20 }, // O
    { key: 'etb',                width: 20 }, // P
    { key: 'loading_condition',  width: 14 }, // Q
    { key: 'lat',                width: 14 }, // R
    { key: 'lon',                width: 14 }, // S
    { key: 'port_source',        width: 12 }, // T
  ]

  // 2. Row 1 — Group headers (merged)
  sheet.mergeCells('B1:F1') // Alert (5 cols)
  sheet.mergeCells('G1:K1') // AIS Information (5 cols)
  sheet.mergeCells('L1:T1') // Report Information (9 cols)

  const setGroupStyle = (cellRef, label, bgColor) => {
    const cell = sheet.getCell(cellRef)
    cell.value = label
    cell.fill  = { type: 'pattern', pattern: 'solid', fgColor: { argb: bgColor } }
    cell.font  = { bold: true, color: { argb: 'FFFFFFFF' }, size: 11 }
    cell.alignment = { horizontal: 'center', vertical: 'middle' }
    cell.border = {
      bottom: { style: 'medium', color: { argb: 'FF000000' } },
      right:  { style: 'thin',   color: { argb: 'FF334155' } }
    }
  }

  setGroupStyle('A1', 'Vessel Name',        'FF1E293B') // Slate 800
  setGroupStyle('B1', 'Alert',              'FF7F1D1D') // Red 900
  setGroupStyle('G1', 'AIS Information',    'FF1E3A8A') // Blue 900
  setGroupStyle('L1', 'Report Information (MA Primary)', 'FF14532D') // Green 900

  sheet.getRow(1).height = 24

  // 3. Row 2 — Sub-headers written manually so they always appear
  const subHeaders = [
    'Vessel Name',
    'Port Alert', 'Coastal Storm', 'Ocean Storm', 'Tropical Cyclone', 'Pos Diff',
    'Voyage No.', 'Speed (kts)', 'Heading (deg)', 'Pos. Date', 'Status',
    'Last Port', 'ETD', 'Next Port', 'ETA', 'ETB', 'Loading', 'Lat', 'Lon', 'Port Source',
  ]
  const row2 = sheet.getRow(2)
  subHeaders.forEach((label, idx) => {
    const cell = row2.getCell(idx + 1)
    cell.value     = label
    cell.fill      = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF0F172A' } }
    cell.font      = { bold: true, color: { argb: 'FF94A3B8' }, size: 10 }
    cell.alignment = { vertical: 'middle', horizontal: 'left' }
    cell.border    = { bottom: { style: 'thin', color: { argb: 'FF334155' } } }
  })
  row2.height = 20

  // 4. Helper for alert display
  const fmtAlert = (val) => {
    const v = String(val || '').trim().toLowerCase()
    if (v === 'null' || v === 'none' || v === 'false' || v === '0' || !v) return '-'
    return val
  }

  // 5. Append Data Rows
  data.forEach((r) => {
    sheet.addRow({
      vessel_name:       fmt(r.vessel_name),
      port_alert:        fmtAlert(r.port_alert),
      coastal_storm:     fmtAlert(r.coastal_storm),
      ocean_storm:       fmtAlert(r.ocean_storm),
      tropical_cyclone:  fmtAlert(r.tropical_cyclone),
      pos_diff:          fmtAlert(r.pos_diff),
      voyage_number:     fmt(r.voyage_number),
      speed:             formatDecimal(r.speed, 1),
      heading:           formatDecimal(r.heading, 1),
      pos_date:          formatDate(r.pos_date),
      status:            fmt(r.status),
      last_port:         cleanPort(r.last_port),
      etd:               formatDate(r.etd),
      next_port:         cleanPort(r.next_port),
      eta:               formatDate(r.eta),
      etb:               formatDate(r.etb),
      loading_condition: fmt(r.loading_condition),          // NEW
      lat:               formatLat(r.lat),
      lon:               formatLon(r.lon),
      port_source:       fmt(r.port_source),               // NEW
    })
  })

  // 6. Generate and Save File
  const buffer = await workbook.xlsx.writeBuffer()
  const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  saveAs(blob, `Fleet_Status_${new Date().toISOString().slice(0, 10)}.xlsx`)
}


// ── Map Style Definitions ────────────────────────────────────────────────────
const MAP_STYLES = {
  Dark: {
    label: 'Dark Map',
    style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
    isDark: true,
  },
  Light: {
    label: 'Light Map',
    style: 'https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json',
    isDark: false,
  },
  Satellite: {
    label: 'Satellite Map',
    style: {
      version: 8,
      sources: {
        'esri-satellite': {
          type: 'raster',
          tiles: [
            'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
          ],
          tileSize: 256,
          attribution: '© Esri',
        },
      },
      layers: [{
        id: 'esri-satellite-layer',
        type: 'raster',
        source: 'esri-satellite',
        minzoom: 0,
        maxzoom: 20,
      }],
    },
    isDark: true,
  },
  Nautical: {
    label: 'Nautical Chart',
    style: {
      version: 8,
      sources: {
        'osm-base': {
          type: 'raster',
          tiles: [
            'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
          ],
          tileSize: 256,
          attribution: '© OpenStreetMap contributors',
        },
        'openseamap': {
          type: 'raster',
          tiles: [
            'https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png',
          ],
          tileSize: 256,
          attribution: '© OpenSeaMap contributors',
        },
      },
      layers: [
        { id: 'osm-base-layer',    type: 'raster', source: 'osm-base',   minzoom: 0, maxzoom: 20 },
        { id: 'openseamap-layer',  type: 'raster', source: 'openseamap', minzoom: 0, maxzoom: 20 },
      ],
    },
    isDark: false,
  },
}

// ── Shared helper: apply/update vessel track layers on the map ───────────────
// Extracted so both the "vessel selected" effect and the "style changed" callback
// can call the same logic without duplication.
function applyTrackToMap(map, data) {
    try {
      // Only keep LineString features — skip individual Point (actual_point) features
      // so we draw clean route lines without thousands of dot markers.
      // We also adjust longitudes to prevent straight lines cutting across the map at the antimeridian.
      const lineOnly = {
        type: 'FeatureCollection',
        features: data.features
          .filter(f => f.geometry && f.geometry.type === 'LineString')
          .map(f => {
            const coords = f.geometry.coordinates
            if (!coords || coords.length === 0) return f

            const newCoords = [[...coords[0]]]
            for (let i = 1; i < coords.length; i++) {
              const prevLon = newCoords[i - 1][0]
              let currLon = coords[i][0]
              const diff = currLon - prevLon
              
              if (diff > 180) {
                currLon -= 360
              } else if (diff < -180) {
                currLon += 360
              }
              
              newCoords.push([currLon, coords[i][1]])
            }

            return {
              ...f,
              geometry: {
                ...f.geometry,
                coordinates: newCoords
              }
            }
          }),
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

      // Next voyage route — purple dashed line
      map.addLayer({
        id:     'vessel-track-next-voyage',
        type:   'line',
        source: 'vessel-track',
        filter: ['==', ['get', 'routetype'], 'next_voyage'],
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint:  { 'line-color': '#a855f7', 'line-width': 2, 'line-dasharray': [4, 4] },
      })

      // Any other route types — orange solid line
      map.addLayer({
        id:     'vessel-track-other',
        type:   'line',
        source: 'vessel-track',
        filter: ['!', ['in', ['get', 'routetype'], ['literal', ['actual', 'future', 'intention', 'next_voyage']]]],
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint:  { 'line-color': '#f97316', 'line-width': 2 },
      })
    }
  } catch (e) {
    console.warn('Track layer error:', e)
  }
}

// ── MapLibre Map Component ──────────────────────────────────────────────────
function MapLibreMap({ vessels, selectedVessel, onVesselClick }) {
  const [activeStyleKey, setActiveStyleKey] = useState(() => {
    return localStorage.getItem('vp_fsm_map_style') || 'Dark'
  })
  
  useEffect(() => {
    localStorage.setItem('vp_fsm_map_style', activeStyleKey)
  }, [activeStyleKey])

  const [showLayers, setShowLayers] = useState(false)
  const mapContainerRef = useRef(null)
  const mapRef          = useRef(null)
  const markersRef      = useRef({})

  // Keep a ref to the current selected vessel so track can be re-applied after style changes
  const selectedVesselRef = useRef(null)

  // Helper: apply dark water colors (Dark style only)
  const applyDarkWater = useCallback((map, isDark) => {
    if (!isDark) return
    try {
      if (map.getLayer('water'))     map.setPaintProperty('water',     'fill-color', '#0a1628')
      if (map.getLayer('landcover')) map.setPaintProperty('landcover', 'fill-color', '#152238')
      if (map.getLayer('waterway'))  map.setPaintProperty('waterway',  'fill-color', '#0a1628')
    } catch (_) {}
  }, [])

  // Initialize map once
  useEffect(() => {
    const maplibregl = getMaplibre()
    if (!mapContainerRef.current || mapRef.current || !maplibregl) return
    mapRef.current = new maplibregl.Map({
      container: mapContainerRef.current,
      style: MAP_STYLES.Dark.style,
      center: [55.0, 10.0],
      zoom: 3,
      minZoom: 1,
      maxZoom: 10,
      attributionControl: false,
    })
    mapRef.current.addControl(new maplibregl.NavigationControl(), 'top-right')
    mapRef.current.on('styledata', () => {
      const map = mapRef.current
      if (!map) return
      applyDarkWater(map, MAP_STYLES[activeStyleKey]?.isDark)
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Handle style switching
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const styleConfig = MAP_STYLES[activeStyleKey]
    if (!styleConfig) return

    // setStyle triggers a full style reload — sources/layers added dynamically
    // (vessel tracks) will be stripped. We listen for 'styledata' to re-apply them.
    map.setStyle(styleConfig.style)

    const onStyleLoaded = () => {
      applyDarkWater(map, styleConfig.isDark)
      // Re-draw the vessel track if a vessel is selected
      if (selectedVesselRef.current?.imo) {
        fetchVesselTrack(selectedVesselRef.current.imo)
          .then(data => {
            if (!mapRef.current) return
            applyTrackToMap(mapRef.current, data)
          })
          .catch(() => {})
      }
    }

    // 'styledata' fires when the style has been applied
    map.once('styledata', onStyleLoaded)
    return () => { map.off('styledata', onStyleLoaded) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeStyleKey])

  // Rebuild markers whenever vessels list changes
  useEffect(() => {
    if (!mapRef.current || !vessels) return

    // Remove old markers
    Object.values(markersRef.current).forEach(m => m.remove())
    markersRef.current = {}

    const maplibregl = getMaplibre()
    if (!maplibregl) return
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
                       isAlertActive(v.pos_diff)

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
      const fmtHead    = formatDecimal(v.heading, 0)
      const headingStr = fmtHead !== '-' ? `${String(fmtHead).padStart(3, '0')}°` : '-'
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

      const popup = new maplibregl.Popup({  // maplibregl in scope from above
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

    // Update the ref so style-switch re-draws know the current vessel
    selectedVesselRef.current = selectedVessel

    fetchVesselTrack(selectedVessel.imo)
      .then(data => {
        const map = mapRef.current
        if (!map) return
        if (map.isStyleLoaded()) {
          applyTrackToMap(map, data)
        } else {
          map.once('load', () => applyTrackToMap(map, data))
        }
      })
      .catch(() => {
        const map = mapRef.current
        if (map?.getSource('vessel-track')) {
          map.getSource('vessel-track').setData({ type: 'FeatureCollection', features: [] })
        }
      })
  }, [selectedVessel])

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <div ref={mapContainerRef} style={{ width: '100%', height: '100%' }} />

      {/* ── Map Style Switcher (Collapsible Layers) ────────────────────────── */}
      <div className="fsm-layer-control" onMouseLeave={() => setShowLayers(false)}>
        <button
          className="fsm-layer-toggle"
          title="Map Layers"
          onClick={() => setShowLayers(!showLayers)}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
            <polyline points="2 12 12 17 22 12"></polyline>
            <polyline points="2 17 12 22 22 17"></polyline>
          </svg>
        </button>
        {showLayers && (
          <div className="fsm-layer-menu">
            {Object.entries(MAP_STYLES).map(([key, cfg]) => (
              <button
                key={key}
                className={`fsm-layer-item${activeStyleKey === key ? ' active' : ''}`}
                title={cfg.label}
                onClick={() => {
                  setActiveStyleKey(key)
                  setShowLayers(false)
                }}
              >
                {cfg.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Vessel Details Modal ─────────────────────────────────────────────────────
function VesselModal({ vessel, onClose }) {
  const [activeTab, setActiveTab] = useState('ais')
  if (!vessel) return null

  const tabs = [
    { id: 'ais',     label: 'AIS / Position' },
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
              {/* Data source badge row */}
              {vessel.port_source && (
                <div style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ color: '#94a3b8', fontSize: 12 }}>Port / ETA data source:</span>
                  <PortSourceBadge source={vessel.port_source} />
                  {vessel.ma_report_age_hours != null && (
                    <span style={{ color: '#64748b', fontSize: 11 }}>
                      (MA report {vessel.ma_report_age_hours}h ago)
                    </span>
                  )}
                </div>
              )}
              <div className="fsm-info-grid">
                {[
                  ['Voyage No.',         fmt(vessel.voyage_number)],
                  ['Speed',              `${formatDecimal(vessel.speed, 1)} kn`],
                  ['Heading',            `${formatDecimal(vessel.heading, 1)}°`],
                  ['Status',             fmt(vessel.status)],
                  ['Loading Condition',  fmt(vessel.loading_condition)],   // NEW
                  ['Position',           `${formatLat(vessel.lat)}, ${formatLon(vessel.lon)}`],
                  ['Pos. Date',          formatDate(vessel.pos_date)],
                  ['Last Port',          cleanPort(vessel.last_port)],
                  ['ETD',                formatDate(vessel.etd)],
                  ['Next Port',          cleanPort(vessel.next_port)],
                  ['ETA',                formatDate(vessel.eta)],
                  ['ETB',                formatDate(vessel.etb)],           // NEW
                  ['RTA',                formatDate(vessel.rta)],
                  ['Last Report',        `${fmt(vessel.rep_type)} @ ${formatDate(vessel.rep_time)}`],
                  ['Service',            fmt(vessel.service)],
                  ['DWT',                fmt(vessel.dwt)],
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

  const [topHeight, setTopH]        = useState(() => {
    const saved = parseInt(memoryStore.getItem('vp_fsm_top_height'), 10)
    if (saved) return saved
    // Default to 55% of screen height, but cap it at 700px for very large screens
    return Math.min(window.innerHeight * 0.55, 700)
  })
  const [dragging, setDrag]         = useState(false)
  const dragStartY                  = useRef(0)
  const dragStartH                  = useRef(0)

  useEffect(() => { memoryStore.setItem('vp_fsm_top_height', topHeight) }, [topHeight])

  function onDragMouseDown(e) {
    e.preventDefault()
    dragStartY.current = e.clientY
    dragStartH.current = topHeight
    setDrag(true)
    function onMove(ev) {
      setTopH(Math.max(160, Math.min(window.innerHeight - 100, dragStartH.current + (ev.clientY - dragStartY.current))))
    }
    function onUp() {
      setDrag(false)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

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

  // Filter by search, then sort — memoized so map markers only rebuild when data/search/sort changes
  const displayedVoyages = useMemo(() => {
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
  }, [voyages, search, sortCol, sortDir])

  const mappableVessels = useMemo(() =>
    displayedVoyages.filter(v =>
      isFinite(parseFloat(v.lat)) && isFinite(parseFloat(v.lon))
    )
  , [displayedVoyages])

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
        <div className="fsm-map-card" style={{ height: topHeight }}>
          <MapLibreMap
            vessels={mappableVessels}
            selectedVessel={selectedVessel}
            onVesselClick={handleVesselClick}
          />
        </div>

        <div className={`fsm-drag-handle${dragging ? ' dragging' : ''}`} onMouseDown={onDragMouseDown} title="Drag to resize">
          <div className="fsm-drag-handle-grip" />
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
                  <th colSpan={5} className="fsm-th-alert-group">Alert</th>
                  {/* AIS: 5 cols */}
                  <th colSpan={5} className="fsm-th-ais-group">AIS Information</th>
                  {/* Report: 8 cols (Last Port, ETD, Next Port, ETA, ETB, Loading, Lat, Lon) */}
                  <th colSpan={8} className="fsm-th-report-group">Report Information (MA Primary)</th>
                </tr>
                <tr>
                  {/* Alert (6) */}
                  <th className="fsm-th-alert">Port Alert</th>
                  <th className="fsm-th-alert">Coastal Storm</th>
                  <th className="fsm-th-alert">Ocean Storm</th>
                  <th className="fsm-th-alert">Tropical Cyclone</th>
                  <th className="fsm-th-alert">Pos Diff</th>

                  {/* AIS Information (5) — added Voyage No. */}
                  <th className="fsm-th-ais fsm-sortable" onClick={() => handleSort('voyage_number')}>Voyage No.{sortIcon('voyage_number')}</th>
                  <th className="fsm-th-ais fsm-sortable" onClick={() => handleSort('speed')}>Speed (kts){sortIcon('speed')}</th>
                  <th className="fsm-th-ais fsm-sortable" onClick={() => handleSort('heading')}>Heading (deg){sortIcon('heading')}</th>
                  <th className="fsm-th-ais fsm-sortable" onClick={() => handleSort('pos_date')}>Pos.Date{sortIcon('pos_date')}</th>
                  <th className="fsm-th-ais fsm-sortable" onClick={() => handleSort('status')}>Status{sortIcon('status')}</th>
                  {/* Report Information (MA-primary) */}
                  <th className="fsm-th-report fsm-sortable" onClick={() => handleSort('last_port')}>Last Port{sortIcon('last_port')}</th>
                  <th className="fsm-th-report fsm-sortable" onClick={() => handleSort('etd')}>ETD{sortIcon('etd')}</th>
                  <th className="fsm-th-report fsm-sortable" onClick={() => handleSort('next_port')}>Next Port{sortIcon('next_port')}</th>
                  <th className="fsm-th-report fsm-sortable" onClick={() => handleSort('eta')}>ETA{sortIcon('eta')}</th>
                  <th className="fsm-th-report fsm-sortable" onClick={() => handleSort('etb')}>ETB{sortIcon('etb')}</th>
                  <th className="fsm-th-report fsm-sortable" onClick={() => handleSort('loading_condition')}>Loading{sortIcon('loading_condition')}</th>
                  <th className="fsm-th-report">Lat</th>
                  <th className="fsm-th-report">Lon</th>
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
                    {/* Report Information (MA-primary) */}
                    <td>
                      {cleanPort(v.last_port)}
                      <PortSourceBadge source={v.port_source} />
                    </td>
                    <td className="fsm-date-cell">{formatDate(v.etd)}</td>
                    <td>
                      {cleanPort(v.next_port)}
                      <PortSourceBadge source={v.port_source} />
                    </td>
                    <td className="fsm-date-cell">{formatDate(v.eta)}</td>
                    <td className="fsm-date-cell">{formatDate(v.etb)}</td>
                    <td>{fmt(v.loading_condition)}</td>
                    <td>{formatLat(v.lat)}</td>
                    <td>{formatLon(v.lon)}</td>
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

