/**
 * voyagePdfExport.js
 * ------------------
 * Generates a WNI-style Voyage Audit Report PDF using jsPDF + jsPDF-AutoTable.
 *
 * Page Structure:
 *   Page 1   — Cover / Voyage Header
 *   Page 2   — Speed & Consumption Summary (Good Wx / All Wx)
 *   Page 3   — Consumption Calculation Methodology
 *   Page 4   — Speed & Weather Analysis Summary Table
 *   Pages 5+ — Positions & Weather Detail (8 rows / page)
 *   Next     — Fuel Consumption Analysis
 *   Next     — Message Traffic (one section per report record)
 *   Last 2   — CP Compliance Audit Methodology (static)
 */

import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'
import { capturePdfAssets } from './PdfHiddenRenderer'
import {
  fetchVoyageSummary,
  fetchVoyageSeries,
  fetchCPPerformance,
} from '../api/vesselApi'

// ── Colour palette (matching WNI report style) ─────────────────────────────
const NAVY   = [10, 36, 99]
const SKY    = [41, 128, 185]
const LGRAY  = [245, 246, 248]
const MGRAY  = [200, 206, 214]
const DGRAY  = [80, 90, 100]
const WHITE  = [255, 255, 255]
const RED    = [200, 40, 40]
const GREEN  = [22, 160, 133]

// ── Helpers ────────────────────────────────────────────────────────────────
const fmt = (v, d = 2) => {
  if (v === null || v === undefined || v === '' || isNaN(v)) return '—'
  return (+v).toFixed(d)
}

const fmtDate = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d)) return iso
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}

const fmtDateTime = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d)) return iso
  const months = ['January','February','March','April','May','June','July','August','September','October','November','December']
  const m = months[d.getUTCMonth()]
  const day = String(d.getUTCDate()).padStart(2, '0')
  const yr = d.getUTCFullYear()
  const hr = String(d.getUTCHours()).padStart(2, '0')
  const min = String(d.getUTCMinutes()).padStart(2, '0')
  return `${m} ${day}, ${yr} ${hr}:${min}UTC`
}

const windDir = (deg) => {
  if (deg === null || deg === undefined) return '—'
  const dirs = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW']
  return dirs[Math.round(((+deg) % 360) / 22.5) % 16]
}

const bfScale = (ms) => {
  if (!ms) return '—'
  const v = +ms
  if (v < 0.3)  return '0'
  if (v < 1.6)  return '1'
  if (v < 3.4)  return '2'
  if (v < 5.5)  return '3'
  if (v < 8.0)  return '4'
  if (v < 10.8) return '5'
  if (v < 13.9) return '6'
  if (v < 17.2) return '7'
  if (v < 20.8) return '8'
  if (v < 24.5) return '9'
  if (v < 28.5) return '10'
  if (v < 32.7) return '11'
  return '12'
}

// ── PDF helper functions ───────────────────────────────────────────────────

function addHeader(doc, voyageNo, routeId, reportDate, pageTitle) {
  const W = doc.internal.pageSize.getWidth()

  // Navy top bar
  doc.setFillColor(...NAVY)
  doc.rect(0, 0, W, 22, 'F')

  // Company name
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9)
  doc.setTextColor(...WHITE)
  doc.text('VESSEL PERFORMANCE SYSTEM', 14, 8)

  // Right side (Report created)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7)
  doc.text(`Report created: ${reportDate}`, W - 14, 8, { align: 'right' })

  // Report title (moved down onto its own vertical line to avoid overlap)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10)
  doc.text(pageTitle, W / 2, 16, { align: 'center' })

  doc.setTextColor(0, 0, 0)
  return 26
}

function addFooter(doc, pageNum, totalPages) {
  const W = doc.internal.pageSize.getWidth()
  const H = doc.internal.pageSize.getHeight()
  doc.setFillColor(...MGRAY)
  doc.rect(0, H - 8, W, 8, 'F')
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7)
  doc.setTextColor(...DGRAY)
  doc.text(`Page ${pageNum} of ${totalPages}`, W / 2, H - 3, { align: 'center' })
  doc.text('Confidential — Prepared for Ozellar', 14, H - 3)
  doc.setTextColor(0, 0, 0)
}

function sectionTitle(doc, y, title) {
  const W = doc.internal.pageSize.getWidth()
  doc.setFillColor(...SKY)
  doc.rect(0, y, W, 7, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  doc.setTextColor(...WHITE)
  doc.text(title, 14, y + 4.8)
  doc.setTextColor(0, 0, 0)
  return y + 10
}

function keyValue(doc, y, pairs, colW = 90) {
  const startX = 14
  pairs.forEach(([k, v], i) => {
    const col = i % 2
    const row = Math.floor(i / 2)
    const x   = startX + col * colW
    const lineY = y + row * 7
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(7.5)
    doc.setTextColor(...DGRAY)
    doc.text(k + ':', x, lineY)
    doc.setFont('helvetica', 'normal')
    doc.setTextColor(0, 0, 0)
    doc.text(String(v || '—'), x + 38, lineY)
  })
  const rows = Math.ceil(pairs.length / 2)
  return y + rows * 7 + 4
}

// ── Page builders ──────────────────────────────────────────────────────────

/** Page 1 — Cover / Voyage Header */
function buildCoverPage(doc, sum, cpData, vesselName, voyageNo, routeId, reportDate) {
  const W = doc.internal.pageSize.getWidth()
  let y = addHeader(doc, voyageNo, routeId, reportDate, '')

  // Cover Page Title block (matching original layout)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(22)
  doc.setTextColor(0, 0, 0)
  doc.text('Voyage Audit Report', W / 2, y + 20, { align: 'center' })
  
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.text(`Report created: ${reportDate}`, W / 2, y + 28, { align: 'center' })
  y += 40

  // Big vessel name
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(16)
  doc.setTextColor(...NAVY)
  doc.text(vesselName, W / 2, y, { align: 'center' })
  doc.setFontSize(9)
  doc.setTextColor(...DGRAY)
  doc.text(`IMO: ${sum.vessel_imo || '—'}`, W / 2, y + 7, { align: 'center' })
  doc.setTextColor(0, 0, 0)
  y += 16

  // Separator
  doc.setDrawColor(...SKY)
  doc.setLineWidth(0.5)
  doc.line(14, y, W - 14, y)
  y += 6

  // Key voyage details
  const cp = cpData?.results?.[0] || {}
  const cpW = cp.warranty || {}
  const cpGD = cp.good_wx_def || {}

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  const lblX = 14
  const valX = 45
  const dtX = 100
  let dy = y
  
  doc.text('Vessel Name:', lblX, dy); doc.setFont('helvetica', 'normal'); doc.text(vesselName, valX, dy); dy += 5;
  doc.setFont('helvetica', 'bold'); doc.text('Prepared for:', lblX, dy); doc.setFont('helvetica', 'normal'); doc.text('Ozellar', valX, dy); dy += 5;
  doc.setFont('helvetica', 'bold'); doc.text('Departure:', lblX, dy); doc.setFont('helvetica', 'normal'); doc.text(sum.From_Port || '—', valX, dy); doc.text(fmtDateTime(sum.Departure_Time) || '', dtX, dy); dy += 5;
  doc.setFont('helvetica', 'bold'); doc.text('Arrival:', lblX, dy); doc.setFont('helvetica', 'normal'); doc.text(sum.To_Port || '—', valX, dy); doc.text(fmtDateTime(sum.Arrival_Time) || '', dtX, dy); dy += 5;
  doc.setFont('helvetica', 'bold'); doc.text('Voyage No:', lblX, dy); doc.setFont('helvetica', 'normal'); doc.text(String(voyageNo), valX, dy); dy += 5;
  doc.setFont('helvetica', 'bold'); doc.text('Ship Type:', lblX, dy); doc.setFont('helvetica', 'normal'); doc.text('BULK CARRIER', valX, dy); dy += 5;
  doc.setFont('helvetica', 'bold'); doc.text('Loading Condition:', lblX, dy); doc.setFont('helvetica', 'normal'); doc.text(sum.Loading_Cond || '—', valX, dy); dy += 12;

  y = dy

  // Good Weather Definition Box
  doc.setDrawColor(0, 0, 0)
  doc.setLineWidth(0.4)
  doc.rect(14, y, W - 28, 16)
  
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9)
  doc.text('Good Weather Definition', W / 2, y + 6, { align: 'center' })
  
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  const gwText = `Wind Beaufort Force ${cpGD.wind || '4'}, Significant wave height ${cpGD.sea_state || '1.25'} meters (Douglas Sea State 3), no adverse current`
  doc.text(gwText, W / 2, y + 11, { align: 'center' })
  
  y += 20

  // CP Grid Box
  doc.rect(14, y, W - 28, 42)
  
  // Header row
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(7.5)
    doc.text('Time', 90, y + 5, { align: 'center' })
    doc.text('FO', 130, y + 5, { align: 'center' })
    doc.text('GO', 170, y + 5, { align: 'center' })
    
    doc.line(14, y + 7, W - 14, y + 7) // below header
    
    // Vertical lines
    doc.line(60, y + 7, 60, y + 33) 
    doc.line(110, y + 7, 110, y + 33)
    
    // Left col (Voyage route)
    doc.setFont('helvetica', 'bold')
    doc.text('(1)', 37, y + 13, { align: 'center' })
    doc.text(sum.From_Port || '—', 37, y + 18, { align: 'center' })
    doc.setFont('helvetica', 'normal')
    doc.text('to', 37, y + 22, { align: 'center' })
    doc.setFont('helvetica', 'bold')
    doc.text(sum.To_Port || '—', 37, y + 26, { align: 'center' })
    doc.text('(Economical speed)', 37, y + 30, { align: 'center' })
    
    // Time col - Lost/Saved
    doc.setFont('helvetica', 'normal')
    doc.text('Lost', 72, y + 18, { align: 'right' })
    doc.text('Saved', 72, y + 28, { align: 'right' })
    doc.line(60, y + 21, W - 14, y + 21) // horiz line between lost and saved
    
    const tLoss = cp.loss?.time_h || 0
    if (tLoss > 0) {
      doc.setFillColor(255, 0, 0)
      doc.rect(80, y + 14, 20, 5, 'F')
      doc.setTextColor(255, 255, 255)
      doc.text(`${tLoss.toFixed(2)} hrs`, 90, y + 17.5, { align: 'center' })
    } else if (tLoss < 0) {
      doc.setDrawColor(0, 0, 255)
      doc.setLineWidth(1.2)
      doc.line(80, y + 21, 100, y + 21)
      doc.setDrawColor(0, 0, 0)
      doc.setLineWidth(0.4)
      doc.setTextColor(0, 0, 0)
      doc.setFont('helvetica', 'bold')
      doc.text(`${Math.abs(tLoss).toFixed(2)} hrs`, 90, y + 25, { align: 'center' })
    }
    doc.setTextColor(0, 0, 0)
    
    // FO
    const foLoss = cp.loss?.fo_mt || 0
    doc.setFont('helvetica', 'bold')
    if (foLoss > 0) {
      doc.setFillColor(255, 0, 0)
      doc.rect(120, y + 14, 20, 5, 'F')
      doc.setTextColor(255, 255, 255)
      doc.text(`${foLoss.toFixed(2)} MT`, 130, y + 17.5, { align: 'center' })
    } else if (foLoss < 0) {
      doc.setDrawColor(0, 0, 255)
      doc.setLineWidth(1.2)
      doc.line(120, y + 21, 140, y + 21)
      doc.setDrawColor(0, 0, 0)
      doc.setLineWidth(0.4)
      doc.setTextColor(0, 0, 0)
      doc.setFont('helvetica', 'bold')
      doc.text(`${Math.abs(foLoss).toFixed(2)} MT`, 130, y + 25, { align: 'center' })
    } else {
      doc.setTextColor(0, 0, 0)
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(7)
      doc.text('No FO', 130, y + 12, { align: 'center' })
      doc.text('Over-consumption/', 130, y + 16, { align: 'center' })
      doc.text('Saving', 130, y + 20, { align: 'center' })
      doc.setFontSize(7.5)
    }
    doc.setTextColor(0, 0, 0)
    
    // GO
    const goLoss = cp.loss?.dogo_mt || 0
    doc.setFont('helvetica', 'bold')
    if (goLoss > 0) {
      doc.setFillColor(255, 0, 0)
      doc.rect(160, y + 14, 20, 5, 'F')
      doc.setTextColor(255, 255, 255)
      doc.text(`${goLoss.toFixed(2)} MT`, 170, y + 17.5, { align: 'center' })
    } else if (goLoss < 0) {
      doc.setDrawColor(0, 0, 255)
      doc.setLineWidth(1.2)
      doc.line(160, y + 21, 180, y + 21)
      doc.setDrawColor(0, 0, 0)
      doc.setLineWidth(0.4)
      doc.setTextColor(0, 0, 0)
      doc.setFont('helvetica', 'bold')
      doc.text(`${Math.abs(goLoss).toFixed(2)} MT`, 170, y + 25, { align: 'center' })
    } else {
      doc.setTextColor(0, 0, 0)
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(7)
      doc.text('No GO', 170, y + 12, { align: 'center' })
      doc.text('Over-consumption/', 170, y + 16, { align: 'center' })
      doc.text('Saving', 170, y + 20, { align: 'center' })
      doc.setFontSize(7.5)
    }
    doc.setTextColor(0, 0, 0)
    
    // CP Warranty Footer
    doc.line(14, y + 33, W - 14, y + 33)
    doc.setFont('helvetica', 'normal')
    doc.text('CP Warranty', 70, y + 38, { align: 'right' })
    doc.text(`about ${fmt(cpW.speed_kn)} Knots`, 90, y + 38, { align: 'center' })
    doc.text(`about ${fmt(cpW.fo_mt_day)} MT/day`, 130, y + 38, { align: 'center' })
    doc.text(`about ${fmt(cpW.go_mt_day)} MT/day`, 170, y + 38, { align: 'center' })
}

/** Page 2 — Speed & Consumption Calculation */
function buildSpeedConsPage(doc, sum, seriesRows, cpData, routeId, reportDate, voyageNo) {
  doc.addPage()
  let y = addHeader(doc, voyageNo, routeId, reportDate, 'Speed and Consumption Calculation')

  const W = doc.internal.pageSize.getWidth()
  const cp = cpData?.results?.[0] || {}

  // Route label
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  doc.text(`${sum.From_Port || '—'} to ${sum.To_Port || '—'} (Economical speed)`, W / 2, y, { align: 'center' })
  y += 8

  y = sectionTitle(doc, y, 'A. Good Weather Analysis')
  y += 5
  
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.text("The following days were analyzed as 'Good Weather Days'.", 14, y)
  y += 4

  // Compute good weather rows
  const goodRows = seriesRows.filter(r => {
    const bf = +bfScale(r.True_Wind_Spd_ms) || 0
    const wh = +(r.Sig_Wave_Ht_m) || 0
    return bf <= 4 && wh <= 1.25
  })
  const allRows = seriesRows

  let dateRangeStr = '—'
  if (goodRows.length > 0) {
    const startStr = fmtDate(goodRows[0].Date)
    const endStr = fmtDate(goodRows[goodRows.length - 1].Date)
    dateRangeStr = `${startStr} to ${endStr}`
  }
  doc.text(dateRangeStr, 14, y)
  y += 6

  const totalDist  = allRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const totalDur   = allRows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)
  const totalFO    = allRows.reduce((s, r) => s + (+(r.ME_FOC_MT) || 0), 0)
  const totalGO    = allRows.reduce((s, r) => s + (+(r.AE_FOC_MT) || 0) + (+(r.Boiler_FOC_MT) || 0), 0)
  
  const goodDist   = goodRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const goodDur    = goodRows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)
  const goodFO     = goodRows.reduce((s, r) => s + (+(r.ME_FOC_MT) || 0), 0)
  const goodGO     = goodRows.reduce((s, r) => s + (+(r.AE_FOC_MT) || 0) + (+(r.Boiler_FOC_MT) || 0), 0)

  const totalSpeed = totalDur > 0 ? totalDist / totalDur : 0
  const goodSpeed  = goodDur > 0 ? goodDist / goodDur : 0
  
  const goodDailyFO = goodDur > 0 ? goodFO / (goodDur / 24) : 0
  const totalDailyFO = totalDur > 0 ? totalFO / (totalDur / 24) : 0
  
  const goodDailyGO = goodDur > 0 ? goodGO / (goodDur / 24) : 0
  const totalDailyGO = totalDur > 0 ? totalGO / (totalDur / 24) : 0

  autoTable(doc, {
    startY: y,
    head: [
      [{ content: '', rowSpan: 2 }, { content: 'Good Weather', colSpan: 2, styles: { halign: 'center' } }, { content: 'All Weather', colSpan: 2, styles: { halign: 'center' } }],
      ['out of ECA', 'In ECA', 'out of ECA', 'In ECA']
    ],
    body: [
      ['Distance Sailed [Miles]',       fmt(goodDist, 0), '-',  fmt(totalDist, 0), '-'],
      ['Time on Route [Hours]',         fmt(goodDur, 2), '-',   fmt(totalDur, 2), '-'],
      ['Average Speed [Knots]',         fmt(goodSpeed, 2), '-', fmt(totalSpeed, 2), '-'],
      ['FO Consumption [MT]',           fmt(goodFO, 2), '-',    fmt(totalFO, 2), '-'],
      ['Averaged Daily FO Consumption', fmt(goodDailyFO, 2), '-', fmt(totalDailyFO, 2), '-'],
      ['GO Consumption [MT]',           fmt(goodGO, 2), '-',    fmt(totalGO, 2), '-'],
      ['Averaged Daily GO Consumption', fmt(goodDailyGO, 2), '-', fmt(totalDailyGO, 2), '-'],
    ],
    theme: 'grid',
    headStyles: { fillColor: WHITE, textColor: 0, lineWidth: 0.1, lineColor: 0, fontSize: 8, fontStyle: 'bold', halign: 'center' },
    bodyStyles: { fontSize: 8, cellPadding: 2, textColor: 0, lineColor: 0, lineWidth: 0.1 },
    alternateRowStyles: { fillColor: WHITE },
    columnStyles: { 0: { cellWidth: 70, halign: 'center' }, 1: { halign: 'right' }, 2: { halign: 'right' }, 3: { halign: 'right' }, 4: { halign: 'right' } },
    margin: { left: 24, right: 24 },
  })
  
  y = doc.lastAutoTable.finalY + 2
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(6)
  doc.text('*In ECA refers to the area where the bunker type is changed over.', W - 24, y, { align: 'right' })
  
  y += 8
  
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.text(`Total Distance: ${fmt(totalDist, 0)} [Miles]`, 50, y)
  doc.text(`Good Weather Time: ${fmt(goodDur, 1)} [Hours]`, 110, y)
  y += 5
  
  doc.setFont('helvetica', 'bold')
  doc.text('Good Weather Average Speed:', 50, y)
  doc.text(`${fmt(goodSpeed, 2)} Knots`, 110, y)
  y += 4
  doc.text('Good Weather Current Factor:', 50, y)
  doc.text('Negated', 110, y)
  y += 4
  
  // Under/Over performance rect
  const cpW = cp.warranty || {}
  const wSpeed = cpW.speed_kn || 0
  const isUnder = goodSpeed < wSpeed
  doc.setFillColor(isUnder ? 255 : 34, isUnder ? 0 : 211, isUnder ? 0 : 153)
  doc.rect(14, y, W - 28, 6, 'F')
  doc.setTextColor(255, 255, 255)
  doc.text(`Good Weather Performance Speed: ${fmt(goodSpeed, 2)} Knots (${isUnder ? 'Under' : 'Over'}-performance)`, W / 2, y + 4.2, { align: 'center' })
  doc.setTextColor(0, 0, 0)
  y += 12

  // B. Time Calculation
  y = sectionTitle(doc, y, 'B. Time Calculation')
  y += 5
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  
  const p1 = "Time loss or gained is calculated by comparing (a) Total Time at Good weather Performance Speed to (b) and (c) listed below. Time loss calculation (b) applies minus 0.5 knot allowance for 'about', an effective warranted speed of " + fmt(wSpeed - 0.5, 2) + " knots has been used, while no allowance in (c) time gained calculation."
  const splitText = doc.splitTextToSize(p1, W - 28)
  doc.text(splitText, 14, y)
  y += splitText.length * 4 + 4
  
  // Formula table
  doc.rect(14, y, W - 28, 30)
  let fy = y + 5
  doc.setFontSize(7.5)
  
  doc.text('Total Time at Good Weather Performance Speed', 18, fy + 3)
  doc.text('=', 85, fy + 3)
  doc.text('Total Distance', 115, fy, { align: 'center' })
  doc.line(95, fy + 1, 135, fy + 1)
  doc.text('Good Weather Performance Speed', 115, fy + 4, { align: 'center' })
  doc.text('(a)', 160, fy + 3)
  fy += 10
  
  doc.text('Total Time at Warranted Speed - 0.5 knots', 18, fy + 3)
  doc.text('=', 85, fy + 3)
  doc.text('Total Distance', 115, fy, { align: 'center' })
  doc.line(95, fy + 1, 135, fy + 1)
  doc.text('Warranted Speed - 0.5 knots', 115, fy + 4, { align: 'center' })
  doc.text('(b)', 160, fy + 3)
  fy += 10

  doc.text('Total Time at Warranted Speed', 18, fy + 3)
  doc.text('=', 85, fy + 3)
  doc.text('Total Distance', 115, fy, { align: 'center' })
  doc.line(95, fy + 1, 135, fy + 1)
  doc.text('Warranted Speed', 115, fy + 4, { align: 'center' })
  doc.text('(c)', 160, fy + 3)
  
  y += 36
  doc.text('Time Lost = (a) - (b)', 18, y)
  doc.text('Time Gained = (c) - (a)', 60, y)
  y += 10
  // Math logic
  const a = goodSpeed > 0 ? totalDist / goodSpeed : 0
  const b = (wSpeed - 0.5) > 0 ? totalDist / (wSpeed - 0.5) : 0
  const c = wSpeed > 0 ? totalDist / wSpeed : 0
  const tLoss = cp.loss?.time_h || 0
  
  if (wSpeed === 0) {
    doc.setFont('helvetica', 'italic')
    doc.text('No Warranted Speed data available for calculation.', 18, y + 2)
    doc.setFont('helvetica', 'normal')
  } else if (tLoss > 0) {
    doc.text('Time Lost', 18, y + 2)
    doc.text('=', 40, y + 2)
    doc.text(fmt(totalDist, 0), 60, y - 1, { align: 'center' })
    doc.line(50, y, 70, y)
    doc.text(fmt(goodSpeed, 2), 60, y + 3, { align: 'center' })
    
    doc.text('-', 75, y + 2)
    doc.text(fmt(totalDist, 0), 95, y - 1, { align: 'center' })
    doc.line(85, y, 105, y)
    doc.text(fmt(wSpeed - 0.5, 2), 95, y + 3, { align: 'center' })
    
    doc.text(`=     ${fmt(a, 2)} - ${fmt(b, 2)}      =    ${fmt(a - b, 2)} Hours`, 115, y + 2)
  } else {
    doc.text('Time Gained', 18, y + 2)
    doc.text('=', 40, y + 2)
    doc.text(fmt(totalDist, 0), 60, y - 1, { align: 'center' })
    doc.line(50, y, 70, y)
    doc.text(fmt(wSpeed, 2), 60, y + 3, { align: 'center' })
    
    doc.text('-', 75, y + 2)
    doc.text(fmt(totalDist, 0), 95, y - 1, { align: 'center' })
    doc.line(85, y, 105, y)
    doc.text(fmt(goodSpeed, 2), 95, y + 3, { align: 'center' })
    
    doc.text(`=     ${fmt(c, 2)} - ${fmt(a, 2)}      =    ${fmt(Math.abs(c - a), 2)} Hours`, 115, y + 2)
  }
  
  y += 10
  doc.setFillColor(tLoss > 0 ? 255 : 34, tLoss > 0 ? 0 : 211, tLoss > 0 ? 0 : 153)
  doc.rect(14, y, W - 28, 6, 'F')
  doc.setTextColor(255, 255, 255)
  doc.setFont('helvetica', 'bold')
  if (tLoss > 0) {
    doc.text(`Conclusion: ${tLoss.toFixed(2)} Hours Lost`, W / 2, y + 4.2, { align: 'center' })
  } else if (tLoss < 0) {
    doc.text(`Conclusion: ${Math.abs(tLoss).toFixed(2)} Hours Gained`, W / 2, y + 4.2, { align: 'center' })
  } else {
    doc.text(`Conclusion: 0.00 Hours Gained`, W / 2, y + 4.2, { align: 'center' })
  }
  doc.setTextColor(0, 0, 0)
}

/** Page 3 — Consumption Methodology */
function buildMethodologyPage1(doc, sum, seriesRows, cpData, routeId, reportDate, voyageNo) {
  doc.addPage()
  let y = addHeader(doc, voyageNo, routeId, reportDate, 'Speed and Consumption Calculation')
  const W = doc.internal.pageSize.getWidth()

  y = sectionTitle(doc, y, 'C. Consumption Calculation')
  y += 5

  const cpW = cpData?.warranty || {}
  const wSpeed = +(cpW.speed_kn || 0)
  const foW = +(cpW.fo_mt_day || 0)
  const goW = +(cpW.go_mt_day || 0)

  const totalDist = seriesRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  
  const goodRows = seriesRows.filter(r => {
    const bf = +bfScale(r.True_Wind_Spd_ms) || 0
    const wh = +(r.Sig_Wave_Ht_m) || 0
    return bf <= 4 && wh <= 1.25
  })
  const goodDist  = goodRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const goodDur   = goodRows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)
  const goodSpeed = goodDur > 0 ? goodDist / goodDur : 0
  const goodFO    = goodRows.reduce((s, r) => s + (+(r.ME_FOC_MT) || 0), 0)
  const goodGO    = goodRows.reduce((s, r) => s + (+(r.AE_FOC_MT) || 0) + (+(r.Boiler_FOC_MT) || 0), 0)

  const foMax = foW * 1.05
  const foMin = foW * 0.95
  const goMax = goW * 1.05
  const goMin = goW * 0.95

  doc.setFontSize(8)
  doc.setFont('helvetica', 'normal')
  doc.text('Unless otherwise specified, the fuel over-consumption assessment as well as fuel under-consumption assessment', 14, y)
  y += 4
  doc.text('employ a 5% tolerance. Effective warranted consumption', 14, y)
  y += 5
  
  if (wSpeed > 0) {
    doc.text(`Fuel over-consumption: ${fmt(foMax, 2)} MT (a plus 5% tolerance applied) and ${fmt(goMax, 2)} MT DO/GO (a plus 5% tolerance applied)`, 14, y)
    y += 4
    doc.text(`Fuel under-consumption: ${fmt(foMin, 2)} MT (a minus 5% tolerance applied) and ${fmt(goMin, 2)} MT DO/GO (a minus 5% tolerance applied)`, 14, y)
    y += 6
  }

  // Draw the generic formula box
  doc.setDrawColor(0)
  doc.setLineWidth(0.1)
  doc.rect(14, y, W - 28, 40)
  let fy = y + 4
  doc.setFontSize(7)
  
  // Formula D
  doc.text('Entire Voyage Consumption using', 16, fy + 2)
  doc.text('vessel Good Weather Consumption', 16, fy + 5)
  doc.text('=', 70, fy + 4)
  doc.text('Total Distance', 90, fy + 1.5, { align: 'center' })
  doc.line(75, fy + 2.5, 105, fy + 2.5)
  doc.text('Good Weather Performance Speed', 90, fy + 5.5, { align: 'center' })
  doc.text('x', 110, fy + 4)
  doc.text('Good Weather Consumption', 140, fy + 1.5, { align: 'center' })
  doc.line(115, fy + 2.5, 165, fy + 2.5)
  doc.text('Good Weather Time', 140, fy + 5.5, { align: 'center' })
  doc.text('(d)', 185, fy + 4)
  
  fy += 12
  // Formula E
  doc.text('Maximum Warranted Consumption', 16, fy + 2)
  doc.text('for over-consumption', 16, fy + 5)
  doc.text('=', 70, fy + 4)
  doc.text('Total Distance', 90, fy + 1.5, { align: 'center' })
  doc.line(75, fy + 2.5, 105, fy + 2.5)
  doc.text('Warranted Speed - 0.5 knots', 90, fy + 5.5, { align: 'center' })
  doc.text('x', 110, fy + 4)
  doc.text('Warranted Consumption + Tolerance', 140, fy + 1.5, { align: 'center' })
  doc.line(115, fy + 2.5, 165, fy + 2.5)
  doc.text('24 hours', 140, fy + 5.5, { align: 'center' })
  doc.text('(e)', 185, fy + 4)
  
  fy += 12
  // Formula F
  doc.text('Minimum Warranted Consumption', 16, fy + 2)
  doc.text('for fuel saving', 16, fy + 5)
  doc.text('=', 70, fy + 4)
  doc.text('Total Distance', 90, fy + 1.5, { align: 'center' })
  doc.line(75, fy + 2.5, 105, fy + 2.5)
  doc.text('Warranted Speed', 90, fy + 5.5, { align: 'center' })
  doc.text('x', 110, fy + 4)
  doc.text('Warranted Consumption - Tolerance', 140, fy + 1.5, { align: 'center' })
  doc.line(115, fy + 2.5, 165, fy + 2.5)
  doc.text('24 hours', 140, fy + 5.5, { align: 'center' })
  doc.text('(f)', 185, fy + 4)
  
  fy += 9
  doc.text('Fuel Over-consumption = (d) - (e)', 16, fy)
  doc.text('Fuel Saving = (f) - (d)', 80, fy)
  
  y += 45
  
  // (1) FO Block
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  doc.text('(1) FO', 14, y)
  y += 5
  
  if (wSpeed === 0) {
     doc.setFont('helvetica', 'italic')
     doc.text('No Warranted Speed data available for calculation.', 22, y + 2)
     doc.setFont('helvetica', 'normal')
     y += 10
  } else {
     doc.setFont('helvetica', 'normal')
     doc.setFontSize(7)
     const d_fo = (totalDist / goodSpeed) * (goodFO / goodDur)
     const e_fo = (totalDist / (wSpeed - 0.5)) * (foMax / 24)
     const f_fo = (totalDist / wSpeed) * (foMin / 24)
     
     // D
     let blockY = y
     doc.text('Entire Voyage Consumption using', 22, blockY + 2)
     doc.text('vessel Good Weather Consumption', 22, blockY + 5)
     doc.text('=', 72, blockY + 4)
     doc.text(fmt(totalDist, 0), 92, blockY + 1.5, { align: 'center' })
     doc.line(78, blockY + 2.5, 106, blockY + 2.5)
     doc.text(fmt(goodSpeed, 2), 92, blockY + 5.5, { align: 'center' })
     doc.text('x', 112, blockY + 4)
     doc.text(fmt(goodFO, 2), 128, blockY + 1.5, { align: 'center' })
     doc.line(116, blockY + 2.5, 140, blockY + 2.5)
     doc.text(fmt(goodDur, 1), 128, blockY + 5.5, { align: 'center' })
     doc.text(`=  ${fmt(d_fo, 2)} MT`, 145, blockY + 4)
     doc.text("(d')", 175, blockY + 4)
     
     blockY += 10
     // E
     doc.text('Maximum Warranted Consumption', 22, blockY + 2)
     doc.text('for over-consumption', 22, blockY + 5)
     doc.text('=', 72, blockY + 4)
     doc.text(fmt(totalDist, 0), 92, blockY + 1.5, { align: 'center' })
     doc.line(78, blockY + 2.5, 106, blockY + 2.5)
     doc.text(fmt(wSpeed - 0.5, 2), 92, blockY + 5.5, { align: 'center' })
     doc.text('x', 112, blockY + 4)
     doc.text(fmt(foMax, 2), 128, blockY + 1.5, { align: 'center' })
     doc.line(116, blockY + 2.5, 140, blockY + 2.5)
     doc.text('24.0', 128, blockY + 5.5, { align: 'center' })
     doc.text(`=  ${fmt(e_fo, 2)} MT`, 145, blockY + 4)
     doc.text("(e')", 175, blockY + 4)
     
     blockY += 10
     // F
     doc.text('Minimum Warranted Consumption', 22, blockY + 2)
     doc.text('for fuel saving', 22, blockY + 5)
     doc.text('=', 72, blockY + 4)
     doc.text(fmt(totalDist, 0), 92, blockY + 1.5, { align: 'center' })
     doc.line(78, blockY + 2.5, 106, blockY + 2.5)
     doc.text(fmt(wSpeed, 2), 92, blockY + 5.5, { align: 'center' })
     doc.text('x', 112, blockY + 4)
     doc.text(fmt(foMin, 2), 128, blockY + 1.5, { align: 'center' })
     doc.line(116, blockY + 2.5, 140, blockY + 2.5)
     doc.text('24.0', 128, blockY + 5.5, { align: 'center' })
     doc.text(`=  ${fmt(f_fo, 2)} MT`, 145, blockY + 4)
     doc.text("(f')", 175, blockY + 4)
     
     blockY += 10
     const foLoss = cpData.loss?.fo_mt || 0
     if (foLoss > 0) {
        doc.text(`FO Over-consumption = (d') - (e')  =  ${fmt(d_fo, 2)}  -  ${fmt(e_fo, 2)}  =  ${fmt(foLoss, 2)} MT`, 40, blockY + 2)
     } else if (foLoss < 0) {
        doc.text(`FO Saving = (f') - (d')  =  ${fmt(f_fo, 2)}  -  ${fmt(d_fo, 2)}  =  ${fmt(Math.abs(foLoss), 2)} MT`, 40, blockY + 2)
     }
     y = blockY + 4
     
     // FO Conclusion
     doc.setDrawColor(0)
     doc.setFillColor(foLoss > 0 ? 255 : (foLoss < 0 ? 34 : 255), foLoss > 0 ? 0 : (foLoss < 0 ? 211 : 255), foLoss > 0 ? 0 : (foLoss < 0 ? 153 : 255))
     if (foLoss === 0) {
        doc.rect(22, y, W - 44, 4)
        doc.setTextColor(0, 0, 0)
     } else {
        doc.rect(22, y, W - 44, 4, 'F')
        doc.setTextColor(255, 255, 255)
     }
     doc.setFont('helvetica', 'bold')
     if (foLoss > 0) {
        doc.text(`Conclusion: ${foLoss.toFixed(2)} MT FO Over-consumption`, W / 2, y + 3, { align: 'center' })
     } else if (foLoss < 0) {
        doc.text(`Conclusion: ${Math.abs(foLoss).toFixed(2)} MT FO Saving`, W / 2, y + 3, { align: 'center' })
     } else {
        doc.text(`Conclusion: No FO Over-consumption/Saving`, W / 2, y + 3, { align: 'center' })
     }
     doc.setTextColor(0, 0, 0)
     y += 10
  }

  // (2) GO Block
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  doc.text('(2) GO', 14, y)
  y += 5
  
  if (wSpeed === 0) {
     doc.setFont('helvetica', 'italic')
     doc.text('No Warranted Speed data available for calculation.', 22, y + 2)
     doc.setFont('helvetica', 'normal')
  } else {
     doc.setFont('helvetica', 'normal')
     doc.setFontSize(7)
     const d_go = (totalDist / goodSpeed) * (goodGO / goodDur)
     const e_go = (totalDist / (wSpeed - 0.5)) * (goMax / 24)
     const f_go = (totalDist / wSpeed) * (goMin / 24)
     
     // D
     let blockY = y
     doc.text('Entire Voyage Consumption using', 22, blockY + 2)
     doc.text('vessel Good Weather Consumption', 22, blockY + 5)
     doc.text('=', 72, blockY + 4)
     doc.text(fmt(totalDist, 0), 92, blockY + 1.5, { align: 'center' })
     doc.line(78, blockY + 2.5, 106, blockY + 2.5)
     doc.text(fmt(goodSpeed, 2), 92, blockY + 5.5, { align: 'center' })
     doc.text('x', 112, blockY + 4)
     doc.text(fmt(goodGO, 2), 128, blockY + 1.5, { align: 'center' })
     doc.line(116, blockY + 2.5, 140, blockY + 2.5)
     doc.text(fmt(goodDur, 1), 128, blockY + 5.5, { align: 'center' })
     doc.text(`=  ${fmt(d_go, 2)} MT`, 145, blockY + 4)
     doc.text("(d')", 175, blockY + 4)
     
     blockY += 10
     // E
     doc.text('Maximum Warranted Consumption', 22, blockY + 2)
     doc.text('for over-consumption', 22, blockY + 5)
     doc.text('=', 72, blockY + 4)
     doc.text(fmt(totalDist, 0), 92, blockY + 1.5, { align: 'center' })
     doc.line(78, blockY + 2.5, 106, blockY + 2.5)
     doc.text(fmt(wSpeed - 0.5, 2), 92, blockY + 5.5, { align: 'center' })
     doc.text('x', 112, blockY + 4)
     doc.text(fmt(goMax, 2), 128, blockY + 1.5, { align: 'center' })
     doc.line(116, blockY + 2.5, 140, blockY + 2.5)
     doc.text('24.0', 128, blockY + 5.5, { align: 'center' })
     doc.text(`=  ${fmt(e_go, 2)} MT`, 145, blockY + 4)
     doc.text("(e')", 175, blockY + 4)
     
     blockY += 10
     // F
     doc.text('Minimum Warranted Consumption', 22, blockY + 2)
     doc.text('for fuel saving', 22, blockY + 5)
     doc.text('=', 72, blockY + 4)
     doc.text(fmt(totalDist, 0), 92, blockY + 1.5, { align: 'center' })
     doc.line(78, blockY + 2.5, 106, blockY + 2.5)
     doc.text(fmt(wSpeed, 2), 92, blockY + 5.5, { align: 'center' })
     doc.text('x', 112, blockY + 4)
     doc.text(fmt(goMin, 2), 128, blockY + 1.5, { align: 'center' })
     doc.line(116, blockY + 2.5, 140, blockY + 2.5)
     doc.text('24.0', 128, blockY + 5.5, { align: 'center' })
     doc.text(`=  ${fmt(f_go, 2)} MT`, 145, blockY + 4)
     doc.text("(f')", 175, blockY + 4)
     
     blockY += 10
     const goLoss = cpData.loss?.go_mt || 0
     if (goLoss > 0) {
        doc.text(`GO Over-consumption = (d') - (e')  =  ${fmt(d_go, 2)}  -  ${fmt(e_go, 2)}  =  ${fmt(goLoss, 2)} MT`, 40, blockY + 2)
     } else if (goLoss < 0) {
        doc.text(`GO Saving = (f') - (d')  =  ${fmt(f_go, 2)}  -  ${fmt(d_go, 2)}  =  ${fmt(Math.abs(goLoss), 2)} MT`, 40, blockY + 2)
     }
     y = blockY + 4
     
     // GO Conclusion
     doc.setDrawColor(0)
     doc.setFillColor(goLoss > 0 ? 255 : (goLoss < 0 ? 34 : 255), goLoss > 0 ? 0 : (goLoss < 0 ? 211 : 255), goLoss > 0 ? 0 : (goLoss < 0 ? 153 : 255))
     if (goLoss === 0) {
        doc.rect(22, y, W - 44, 4)
        doc.setTextColor(0, 0, 0)
     } else {
        doc.rect(22, y, W - 44, 4, 'F')
        doc.setTextColor(255, 255, 255)
     }
     doc.setFont('helvetica', 'bold')
     if (goLoss > 0) {
        doc.text(`Conclusion: ${goLoss.toFixed(2)} MT GO Over-consumption`, W / 2, y + 3, { align: 'center' })
     } else if (goLoss < 0) {
        doc.text(`Conclusion: ${Math.abs(goLoss).toFixed(2)} MT GO Saving`, W / 2, y + 3, { align: 'center' })
     } else {
        doc.text(`Conclusion: No GO Over-consumption/Saving`, W / 2, y + 3, { align: 'center' })
     }
     doc.setTextColor(0, 0, 0)
  }
}

/** Page 4 — Speed & Weather Analysis Summary */
function buildSummaryTablePage(doc, sum, seriesRows, routeId, reportDate, voyageNo) {
  doc.addPage()
  let y = addHeader(doc, voyageNo, routeId, reportDate, 'Speed and Weather Analysis')
  const W = doc.internal.pageSize.getWidth()

  // Info header
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.text(`IMO: ${sum.vessel_imo || '—'}`, 14, y)
  y += 6
  doc.text(`Departure: ${sum.From_Port || '—'}   ${sum.Departure_Time || '—'}`, 14, y)
  y += 6
  doc.text(`Arrival:   ${sum.To_Port || '—'}   ${sum.Arrival_Time || '—'}`, 14, y)
  y += 8

  const totalDist  = seriesRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const totalDur   = seriesRows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)
  const totalFO    = seriesRows.reduce((s, r) => s + (+(r.ME_FOC_MT) || 0), 0)
  const goodRows   = seriesRows.filter(r => (+bfScale(r.True_Wind_Spd_ms) || 0) <= 4 && (+(r.Sig_Wave_Ht_m) || 0) <= 1.25)
  const adverseRows = seriesRows.filter(r => (+bfScale(r.True_Wind_Spd_ms) || 0) > 4 || (+(r.Sig_Wave_Ht_m) || 0) > 1.25)
  const goodDist   = goodRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const goodDur    = goodRows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)
  const goodFO     = goodRows.reduce((s, r) => s + (+(r.ME_FOC_MT) || 0), 0)
  const advDist    = adverseRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const advDur     = adverseRows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)
  const advFO      = adverseRows.reduce((s, r) => s + (+(r.ME_FOC_MT) || 0), 0)
  
  const totalGO    = seriesRows.reduce((s, r) => s + (+(r.AE_FOC_MT) || 0) + (+(r.Boiler_FOC_MT) || 0), 0)
  const goodGO     = goodRows.reduce((s, r) => s + (+(r.AE_FOC_MT) || 0) + (+(r.Boiler_FOC_MT) || 0), 0)
  const advGO      = adverseRows.reduce((s, r) => s + (+(r.AE_FOC_MT) || 0) + (+(r.Boiler_FOC_MT) || 0), 0)

  autoTable(doc, {
    startY: y,
    head: [['Periods', 'Distance (nm)', 'Time (hrs)', 'Avg Speed (kts)', 'FO (mt)', 'DO/GO (mt)']],
    body: [
      ['Entire period',       fmt(totalDist,0), fmt(totalDur,2), fmt(totalDur>0?totalDist/totalDur:0), fmt(totalFO), fmt(totalGO)],
      ['Good weather period', fmt(goodDist,0),  fmt(goodDur,2),  fmt(goodDur>0?goodDist/goodDur:0),    fmt(goodFO),  fmt(goodGO)],
      ['Adverse weather period', fmt(advDist,0), fmt(advDur,2), fmt(advDur>0?advDist/advDur:0),        fmt(advFO),   fmt(advGO)],
      ['Excluded period',     '0', '0.00', '0.00', '0.00', '0.00'],
    ],
    theme: 'grid',
    headStyles: { fillColor: NAVY, textColor: WHITE, fontSize: 7.5, fontStyle: 'bold' },
    bodyStyles: { fontSize: 7.5, cellPadding: 2 },
    alternateRowStyles: { fillColor: LGRAY },
    columnStyles: {
      0: { cellWidth: 55 },
      1: { halign: 'center' },
      2: { halign: 'center' },
      3: { halign: 'center' },
      4: { halign: 'center' },
      5: { halign: 'center' },
    },
    margin: { left: 14, right: 14 },
  })
}

/** Pages 5+ — Detailed Position & Weather Data */
function buildPositionPages(doc, sum, seriesRows, cpData, vesselName, routeId, reportDate, voyageNo) {
  const ROWS_PER_PAGE = 25
  const W = doc.internal.pageSize.getWidth()

  const allRows = seriesRows
  const goodRows = seriesRows.filter(r => {
    const bf = +bfScale(r.True_Wind_Spd_ms) || 0
    const wh = +(r.Sig_Wave_Ht_m) || 0
    return bf <= 4 && wh <= 1.25
  })
  const adverseRows = seriesRows.filter(r => !goodRows.includes(r))

  const calcSum = (rows) => {
    const dist = rows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
    const dur = rows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)
    const speed = dur > 0 ? dist / dur : 0
    const fo = rows.reduce((s, r) => s + (+(r.ME_FOC_MT) || 0), 0)
    const do_go = rows.reduce((s, r) => s + (+(r.AE_FOC_MT) || 0) + (+(r.Boiler_FOC_MT) || 0), 0)
    return { dist, dur, speed, fo, do_go }
  }

  const total = calcSum(allRows)
  const good = calcSum(goodRows)
  const adverse = calcSum(adverseRows)

  const cpSpeed = cpData?.results?.[0]?.speed || 0
  const formatCoord = (deg, min, dir) => deg != null ? `${deg}°${fmt(min, 1)}'${dir || ''}` : '—'

  for (let i = 0; i < seriesRows.length; i += ROWS_PER_PAGE) {
    doc.addPage()
    const pageRows = seriesRows.slice(i, i + ROWS_PER_PAGE)
    let y = addHeader(doc, voyageNo, routeId, reportDate, 'Speed and Weather Analysis')

    if (i === 0) {
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(8)
      doc.setTextColor(0, 0, 0)

      const startStr = allRows.length ? fmtDate(allRows[0].Date) : '—'
      const endStr = allRows.length ? fmtDate(allRows[allRows.length - 1].Date) : '—'

      autoTable(doc, {
        startY: y,
        theme: 'grid',
        styles: { fontSize: 7, textColor: 0, cellPadding: 1, halign: 'center', valign: 'middle', lineColor: [0, 0, 0], lineWidth: 0.1 },
        headStyles: { fillColor: [255, 255, 255], textColor: 0, fontStyle: 'bold' },
        bodyStyles: { fillColor: [255, 255, 255], textColor: 0 },
        head: [
          [
            { content: `${vesselName || '—'}`, colSpan: 3, styles: { halign: 'left', fontStyle: 'bold' } },
            { content: '', colSpan: 4, styles: { halign: 'left' } }
          ],
          [
            { content: 'Departure', styles: { halign: 'left', fontStyle: 'normal' } },
            { content: sum.From_Port || '—', colSpan: 2, styles: { halign: 'left', fontStyle: 'normal' } },
            { content: startStr, colSpan: 4, styles: { halign: 'left', fontStyle: 'normal' } }
          ],
          [
            { content: 'Arrival', styles: { halign: 'left', fontStyle: 'normal' } },
            { content: sum.To_Port || '—', colSpan: 2, styles: { halign: 'left', fontStyle: 'normal' } },
            { content: endStr, colSpan: 4, styles: { halign: 'left', fontStyle: 'normal' } }
          ],
          [
            { content: 'Seg', rowSpan: 2 },
            { content: 'Periods', rowSpan: 2 },
            { content: 'Distance\n(nm)', rowSpan: 2 },
            { content: 'Time\n(hrs)', rowSpan: 2 },
            { content: 'Average Speed\n(kts)', rowSpan: 2 },
            { content: 'Total Consumption (mt)', colSpan: 2 }
          ],
          [
            { content: 'FO' },
            { content: 'DO/GO' }
          ]
        ],
        body: [
          ['1', 'Entire period', fmt(total.dist, 0), fmt(total.dur, 2), fmt(total.speed, 2), fmt(total.fo, 2), fmt(total.do_go, 2)],
          ['1', 'Good weather period', fmt(good.dist, 0), fmt(good.dur, 2), fmt(good.speed, 2), fmt(good.fo, 2), fmt(good.do_go, 2)],
          ['1', 'Adverse weather period', fmt(adverse.dist, 0), fmt(adverse.dur, 2), fmt(adverse.speed, 2), fmt(adverse.fo, 2), fmt(adverse.do_go, 2)],
          ['', 'Excluded period', '0', '0.00', '0.00', '0.00', '0.00']
        ],
        margin: { left: 14, right: 14 }
      })
      y = doc.lastAutoTable.finalY + 4
    }

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(6.5)
    doc.setTextColor(0, 0, 0)
    
    // Legend
    doc.setFillColor(255, 242, 204)
    doc.setDrawColor(0)
    doc.setLineWidth(0.2)
    doc.rect(14, y - 2.5, 8, 3.5, 'FD')
    doc.text('Charter Party defined Good Weather Days', 24, y)
    
    doc.setFillColor(255, 255, 255)
    doc.rect(80, y - 2.5, 8, 3.5, 'FD')
    doc.text('Charter Party defined Adverse Weather Days', 90, y)
    
    doc.setFillColor(200, 200, 200)
    doc.rect(145, y - 2.5, 8, 3.5, 'FD')
    doc.text('Excluded periods from analysis', 155, y)
    
    y += 6

    autoTable(doc, {
      startY: y,
      head: [
        [
          { content: 'Seg', rowSpan: 2 },
          { content: 'DATE', rowSpan: 2 },
          { content: 'TIME\n(UTC)', rowSpan: 2 },
          { content: 'POSITIONS', colSpan: 2 },
          { content: 'CP Speed', rowSpan: 2 },
          { content: 'WEATHERNEWS ANALYSIS', colSpan: 9 }
        ],
        [
          { content: 'LAT' },
          { content: 'LON' },
          { content: 'SPEED\n(kts)' },
          { content: 'DISTANCE\n(nm)' },
          { content: 'WIND\nDIR' },
          { content: 'WIND\nRF' },
          { content: 'Sea HT\n(m)' },
          { content: 'SWELL\nHT(m)' },
          { content: 'SWELL\nDIR' },
          { content: 'CURRENT\nDIR' },
          { content: 'Daily FAC\n(kts)' }
        ]
      ],
      body: pageRows.map((r, idx) => [
        (idx === 0 && i === 0) ? '1' : '',
        r.Date ? new Date(r.Date).toLocaleDateString('en-GB', { day: '2-digit', month: '2-digit' }) : '—',
        r.Date ? (r.Date.substring(11, 16) || '12:00') : '—',
        formatCoord(r.lat_degree, r.lat_minutes, r.lat_direction),
        formatCoord(r.lon_degree, r.lon_minutes, r.lon_direction),
        fmt(cpSpeed, 2),
        fmt(r.SOG_kn),
        fmt(r.Distance_nm, 1),
        windDir(r.True_Wind_Dir_deg),
        bfScale(r.True_Wind_Spd_ms),
        fmt(r.Sig_Wave_Ht_m),
        fmt(r.Swell_Ht_m),
        windDir(r.Swell_Dir_deg),
        windDir(r.Current_Dir_deg),
        fmt(r.Current_Spd_kn)
      ]),
      theme: 'grid',
      styles: { fontSize: 5.5, textColor: 0, cellPadding: 1, halign: 'center', valign: 'middle', lineColor: [0, 0, 0], lineWidth: 0.1 },
      headStyles: { fillColor: [240, 240, 240], textColor: 0, fontStyle: 'bold' },
      bodyStyles: { fillColor: [255, 255, 255] },
      didParseCell: function (data) {
        if (data.section === 'body') {
          const rowData = pageRows[data.row.index]
          const bf = +bfScale(rowData.True_Wind_Spd_ms) || 0
          const wh = +(rowData.Sig_Wave_Ht_m) || 0
          if (bf <= 4 && wh <= 1.25) {
            data.cell.styles.fillColor = [255, 242, 204]
          }
        }
      },
      margin: { left: 14, right: 14 },
    })
  }
}

/** Fuel Consumption Analysis page */
function buildFuelPage(doc, sum, seriesRows, cpData, routeId, reportDate, voyageNo, vesselName) {
  // Use landscape if possible, but keeping portrait to match the rest of the flow is fine.
  // We'll scale the fonts down slightly to fit the massive table on Portrait.
  doc.addPage()
  let y = addHeader(doc, voyageNo, routeId, reportDate, 'Fuel Consumption Analysis')
  const W = doc.internal.pageSize.getWidth()

  const cpW = cpData?.warranty || {}
  const foW = +(cpW.fo_mt_day || 0)
  const goW = +(cpW.go_mt_day || 0)

  // ── 1. Top Header Box ──
  doc.setDrawColor(0)
  doc.setLineWidth(0.2)
  doc.rect(14, y, W - 28, 14)
  
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10)
  doc.text(vesselName || '—', 18, y + 5)

  doc.setFontSize(7)
  doc.setFont('helvetica', 'normal')
  doc.text('Departure:', 18, y + 9)
  doc.text(sum.From_Port || '—', 40, y + 9)
  doc.text('—', 80, y + 9)
  doc.text(sum.Departure_Time ? fmtDateTime(sum.Departure_Time) : '—', 120, y + 9)

  doc.text('Arrival:', 18, y + 12)
  doc.text(sum.To_Port || '—', 40, y + 12)
  doc.text('—', 80, y + 12)
  doc.text(sum.Arrival_Time ? fmtDateTime(sum.Arrival_Time) : '—', 120, y + 12)
  
  y += 16

  // ── 2. Summary Table (Nested Headers) ──
  const totalDist   = seriesRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const totalDur    = seriesRows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)
  const totalFO     = seriesRows.reduce((s, r) => s + (+(r.ME_FOC_MT) || 0), 0)
  const totalGO     = seriesRows.reduce((s, r) => s + (+(r.AE_FOC_MT) || 0) + (+(r.Boiler_FOC_MT) || 0), 0)
  
  const goodRows    = seriesRows.filter(r => {
    const bf = +bfScale(r.True_Wind_Spd_ms) || 0
    const wh = +(r.Sig_Wave_Ht_m) || 0
    return bf <= 4 && wh <= 1.25
  })
  const advRows     = seriesRows.filter(r => {
    const bf = +bfScale(r.True_Wind_Spd_ms) || 0
    const wh = +(r.Sig_Wave_Ht_m) || 0
    return bf > 4 || wh > 1.25
  })
  
  const goodDist    = goodRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const goodDur     = goodRows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)
  const goodFO      = goodRows.reduce((s, r) => s + (+(r.ME_FOC_MT) || 0), 0)
  const goodGO      = goodRows.reduce((s, r) => s + (+(r.AE_FOC_MT) || 0) + (+(r.Boiler_FOC_MT) || 0), 0)
  
  const advDist     = advRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const advDur      = advRows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)
  const advFO       = advRows.reduce((s, r) => s + (+(r.ME_FOC_MT) || 0), 0)
  const advGO       = advRows.reduce((s, r) => s + (+(r.AE_FOC_MT) || 0) + (+(r.Boiler_FOC_MT) || 0), 0)

  autoTable(doc, {
    startY: y,
    head: [
      [
        { content: 'Seg', rowSpan: 3, styles: { valign: 'middle' } },
        { content: 'Periods', rowSpan: 3, styles: { valign: 'middle' } },
        { content: 'Distance\n(nm)', rowSpan: 3, styles: { valign: 'middle' } },
        { content: 'Time\n(hrs)', rowSpan: 3, styles: { valign: 'middle' } },
        { content: 'Average Speed\n(kts)', rowSpan: 3, styles: { valign: 'middle' } },
        { content: 'Total Consumption (mt)', colSpan: 3 }
      ],
      [
        { content: 'FO', colSpan: 2 },
        { content: 'DO/GO', rowSpan: 2, styles: { valign: 'middle' } }
      ],
      [
        'over 1.0%', 'max 1.0%'
      ]
    ],
    body: [
      ['1', 'Entire period',       fmt(totalDist,0), fmt(totalDur,2), fmt(totalDur>0?totalDist/totalDur:0), '0.00', fmt(totalFO,2), fmt(totalGO,2)],
      ['1', 'Good weather period', fmt(goodDist,0),  fmt(goodDur,2),  fmt(goodDur>0?goodDist/goodDur:0),    '0.00', fmt(goodFO,2),  fmt(goodGO,2)],
      ['1', 'Adverse weather period', fmt(advDist,0), fmt(advDur,2), fmt(advDur>0?advDist/advDur:0),        '0.00', fmt(advFO,2),   fmt(advGO,2)],
      ['1', 'Excluded period',     '0', '0.00', '0.00', '0.00', '0.00', '0.00'],
    ],
    theme: 'grid',
    headStyles: { fillColor: [255,255,255], textColor: 0, lineColor: 0, lineWidth: 0.1, fontSize: 6.5, fontStyle: 'normal', halign: 'center' },
    bodyStyles: { fontSize: 6.5, cellPadding: 1.5, halign: 'right', lineColor: 0, lineWidth: 0.1 },
    columnStyles: {
      0: { halign: 'center', cellWidth: 10 },
      1: { halign: 'left' }
    },
    margin: { left: 14, right: 14 },
  })

  y = doc.lastAutoTable.finalY + 8

  // ── 3. Legend Line ──
  doc.setFontSize(6)
  doc.setTextColor(0, 0, 0)
  
  // Yellow box
  doc.setFillColor(255, 242, 204)
  doc.setDrawColor(0)
  doc.rect(14, y - 2.5, 8, 3.5, 'FD')
  doc.text('Charter Party defined Good Weather Days', 24, y)
  
  // White box
  doc.setFillColor(255, 255, 255)
  doc.rect(80, y - 2.5, 8, 3.5, 'FD')
  doc.text('Charter Party defined Adverse Weather Days', 90, y)
  
  // Grey box
  doc.setFillColor(200, 200, 200)
  doc.rect(140, y - 2.5, 8, 3.5, 'FD')
  doc.text('Excluded periods from analysis', 150, y)

  y += 6

  // ── 4. Detailed Position Table ──
  autoTable(doc, {
    startY: y,
    head: [
      [
        { content: 'Seg', rowSpan: 3, styles: { valign: 'middle' } },
        { content: 'DATE', rowSpan: 3, styles: { valign: 'middle' } },
        { content: 'TIME\n(UTC)', rowSpan: 3, styles: { valign: 'middle' } },
        { content: 'POSITIONS', colSpan: 2, rowSpan: 2, styles: { valign: 'middle' } },
        { content: 'CP', colSpan: 2, rowSpan: 2, styles: { valign: 'middle' } },
        { content: 'ROB', colSpan: 3 },
        { content: 'Daily Consumption', colSpan: 3 },
        { content: 'RPM', rowSpan: 3, styles: { valign: 'middle' } },
        { content: 'Inside\nECA', rowSpan: 3, styles: { valign: 'middle' } }
      ],
      [
        { content: 'FO', colSpan: 2 },
        { content: 'DO/GO', rowSpan: 2, styles: { valign: 'middle' } },
        { content: 'FO', colSpan: 2 },
        { content: 'DO/GO', rowSpan: 2, styles: { valign: 'middle' } }
      ],
      [
        'LAT', 'LON',
        'FO\n(mt)', 'DO/GO\n(mt)',
        'over 1.0%', 'max 1.0%',
        'over 1.0%', 'max 1.0%'
      ]
    ],
    body: seriesRows.map((r, idx) => {
      const isEca = false // Placeholder for ECA flag
      const formatCoord = (deg, min, dir) => deg != null ? `${deg}°${fmt(min, 1)}'${dir || ''}` : '—'
      return [
        '1', // Seg (default to 1 per layout)
        r.Date ? new Date(r.Date).toLocaleDateString('en-GB', {day:'2-digit',month:'2-digit'}) : '—',
        r.Date ? (r.Date.substring(11,16) || '12:00') : '—',
        formatCoord(r.lat_degree, r.lat_minutes, r.lat_direction),
        formatCoord(r.lon_degree, r.lon_minutes, r.lon_direction), // LAT, LON
        fmt(foW, 2), fmt(goW, 2), // CP
        '—', '—', '—', // ROB
        '0.00', fmt(r.ME_FOC_MT, 2), fmt((+(r.AE_FOC_MT) || 0) + (+(r.Boiler_FOC_MT) || 0), 2), // Daily Cons
        fmt(r.Shaft_RPM), '—' // RPM, ECA
      ]
    }),
    theme: 'grid',
    headStyles: { fillColor: [255,255,255], textColor: 0, lineColor: 0, lineWidth: 0.1, fontSize: 5, fontStyle: 'normal', halign: 'center' },
    bodyStyles: { fontSize: 5, cellPadding: 1, halign: 'right', lineColor: 0, lineWidth: 0.1 },
    columnStyles: {
      0: { halign: 'center' },
      1: { halign: 'center' },
      2: { halign: 'center' },
      3: { halign: 'center' },
      4: { halign: 'center' },
    },
    didParseCell: function (data) {
      if (data.section === 'body') {
        const rowData = seriesRows[data.row.index]
        const bf = rowData.BF_Wind != null ? +rowData.BF_Wind : (+bfScale(rowData.True_Wind_Spd_ms) || 0)
        const wh = +(rowData.Sig_Wave_Ht_m) || 0
        if (bf <= 4 && wh <= 1.25) {
          data.cell.styles.fillColor = [255, 242, 204]
        } else {
          data.cell.styles.fillColor = [255, 255, 255]
        }
      }
    },
    margin: { left: 14, right: 14, top: 40, bottom: 20 },
    didDrawPage: function(data) {
      if (data.pageNumber > 1) {
        addHeader(doc, voyageNo, routeId, reportDate, 'Fuel Consumption Analysis')
      }
    }
  })
  y = doc.lastAutoTable.finalY + 10
}

/** Message Traffic pages */
function buildMessageTrafficPages(doc, seriesRows, routeId, reportDate, voyageNo) {
  if (!seriesRows || seriesRows.length === 0) return;
  const W = doc.internal.pageSize.getWidth();
  const colWidth = (W - 28) / 2 - 4;

  let y = 297; // force new page trigger on first iteration
  let col = 0;
  let startY = 0;

  seriesRows.forEach((r, idx) => {
    const dt = r.Date ? new Date(r.Date) : null;
    const dateStr = dt
      ? dt.toLocaleDateString('en-GB', { month: '2-digit', day: '2-digit', year: 'numeric' }).replace(/\//g, '/') + ' ' + dt.toTimeString().substring(0, 5)
      : '—';

    const msgLines = [
      `[== Start of Message]`,
      `[Vessel Name : ${r.From_Port ? 'AM UMANG' : '—'}]`,
      `[Voyage number : ${r.Voyage_No || voyageNo}]`,
      `[Displayed REPORT TYPE : ${r.event_type || 'NOON REPORT'}]`,
      `[Load Condition : ${r.Loading_Cond || '—'}]`,
      `[Time (UTC) : ${dateStr}]`,
      `[Draft fore : ${fmt(r.Draft_Fwd_m)}m]   [Draft aft : ${fmt(r.Draft_Aft_m)}m]`,
      `[Average speed : ${fmt(r.STW_kn)}kts]   [Average RPM : ${fmt(r.Shaft_RPM)}rpm]`,
      `[Average M/E power : ${fmt(r.Shaft_Power_kW, 0)}kW]`,
      `[Distance SLR : ${fmt(r.Distance_nm,1)}nm]   [Report duration : ${fmt(r.Duration_h,1)}hrs]`,
      `[ME FOC : VLSFO/${fmt(r.ME_FOC_MT)}/////(MT)]`,
      `[AE FOC : VLSFO/${fmt(r.AE_FOC_MT)}/////(MT)]`,
      `[Wind : ${fmt(r.True_Wind_Spd_ms,0)}knots, ${bfScale(r.True_Wind_Spd_ms)} Beaufort Number, ${windDir(r.True_Wind_Dir_deg)}]`,
      `[Wave Height : ${fmt(r.Sig_Wave_Ht_m)}m]   [Swell Height : ${fmt(r.Swell_Ht_m)}m]`,
      `[Current speed : ${fmt(r.Current_Spd_kn)}kts]`,
      `[SFOC : ${fmt(r.SFOC_gkWh)}g/kWh]`,
      `[REPORT TYPE : ${r.event_type || 'NOON REPORT'}]`,
      `[== End of Message]`,
    ];

    const msgHeight = 5 + (msgLines.length * 4.5) + 7;
    
    // Check if we need to wrap to next column or next page
    if (y + msgHeight > 275) {
      if (col === 0 && startY > 0) {
        col = 1;
        y = startY;
      } else {
        doc.addPage();
        y = addHeader(doc, voyageNo, routeId, reportDate, 'Message Traffic');
        doc.setFont('helvetica', 'bold');
        doc.setFontSize(8);
        doc.text(`VOYAGE: ${seriesRows[0]?.From_Port || '—'} to ${seriesRows[seriesRows.length - 1]?.To_Port || '—'}`, 14, y);
        y += 5;
        doc.text(`CONDITION: ${seriesRows[0]?.Loading_Cond || '—'}`, 14, y);
        y += 8;
        doc.setDrawColor(...MGRAY);
        doc.line(14, y, W - 14, y);
        y += 5;
        startY = y;
        col = 0;
      }
    }

    const startX = col === 0 ? 14 : 14 + colWidth + 8;

    doc.setFont('helvetica', 'bold');
    doc.setFontSize(7.5);
    doc.setTextColor(...NAVY);
    doc.text(`FROM MASTER  ${dateStr}`, startX, y);
    doc.setTextColor(0,0,0);
    y += 5;

    doc.setFont('helvetica', 'normal');
    doc.setFontSize(7);
    msgLines.forEach(line => {
      doc.text(line, startX, y, { maxWidth: colWidth });
      y += 4.5;
    });

    y += 2;
    doc.setDrawColor(...MGRAY);
    doc.line(startX, y, startX + colWidth, y);
    y += 5;
  });
}

/** CP Performance page */
function buildCPPage(doc, cpData, routeId, reportDate, voyageNo) {
  if (!cpData?.results?.length) return
  doc.addPage()
  let y = addHeader(doc, voyageNo, routeId, reportDate, 'Charter-Party Performance Analysis')

  autoTable(doc, {
    startY: y + 4,
    head: [[
      'Voyage', 'L/B', 'Spd\nInstr', 'Seg',
      'Depart Port', 'ATD', 'Arrive Port', 'ATA',
      'Time\nLoss(h)', 'FO\nLoss(mt)', 'DO/GO\nLoss(mt)',
      'CP\nSpeed', 'CP\nFO/d', 'CP\nDO/d',
    ]],
    body: cpData.results.map(r => {
      const l = r.loss || {}
      const w = r.warranty || {}
      return [
        r.voyage_no,
        (r.loading_cond || '')[0] || '—',
        r.speed_instruction || '—',
        r.segment_no || '—',
        r.departure_port || '—',
        r.atd || '—',
        r.arrival_port || '—',
        r.ata || '—',
        fmt(l.time_h),
        fmt(l.fo_mt),
        fmt(l.dogo_mt),
        fmt(w.speed_kn),
        fmt(w.fo_mtpd),
        fmt(w.dogo_mtpd),
      ]
    }),
    theme: 'grid',
    headStyles: { fillColor: NAVY, textColor: WHITE, fontSize: 6.5, fontStyle: 'bold', cellPadding: 2 },
    bodyStyles: { fontSize: 7, cellPadding: 2, halign: 'center' },
    alternateRowStyles: { fillColor: LGRAY },
    margin: { left: 14, right: 14 },
  })
}

/** CP Compliance Methodology (last 2 pages — static) */
function buildCPMethodologyPages(doc, routeId, reportDate, voyageNo) {
  // Page 28
  doc.addPage()
  let y = addHeader(doc, voyageNo, routeId, reportDate, 'Charter Party Compliance Auditing Methodology')
  const W = doc.internal.pageSize.getWidth()

  const sections28 = [
    { title: '1. Good Weather Method', body: `Ship Performance is assessed based on the Good Weather Method as set out by The Didymi [1987] 2 Lloyd's Rep 166 and The Gas Enterprise [1993] 2 Lloyd's Rep. 352.\n\nThe vessel's performance in Charter Party good weather conditions is analyzed, and the average good weather speed is used for the performance calculations.\n\nNo adjustments are made for ocean currents unless otherwise dictated by the Charter Party, as set out by The Divinegate [2022] EWHC 2095 (Comm).\n\nA "day" is taken to be the period of time between consecutive daily noon positions: each day is categorized as a "good weather day" or "adverse weather day" according to the good weather definition stipulated in the Charter Party.` },
    { title: '2. Damage assessment due to ship under-performance', body: `Speed and Consumption Calculation applies allowed time and allowed consumption calculated based on warranted speed and consumption in good weather conditions. Complying with maritime arbitration standards, time loss and over/under-consumption is not calculated when there are no good weather days.` },
    { title: '3. Logbooks description vs. Vessel Performance System Analysis', body: `To complete the Good Weather Analysis method the Vessel Performance System requests daily noon positions (including time, distance, weather, seas, RPM, bunker consumption, etc.) from the Master, which are to be inspected in evaluation reports. The Vessel Performance System will apply its own analyzed distances.\n\nWeather and sea conditions in reports represent the Vessel Performance System's verified weather data.` },
    { title: '4. "About"', body: `Complying with arbitration standards, the speed calculation applies an allowance when an "about" is included with the speed warranty.\n\nAs per the High Court decision on The Gaz Energy (2012) 852 LMLN 2 a plus 5% tolerance in over consumption calculation and a minus 5 % tolerance in under-consumption are employed respectively when an "about" is included with the consumption warranty, unless otherwise stipulated.` }
  ]

  sections28.forEach(s => {
    if (y > 250) return
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(9)
    doc.setTextColor(...NAVY)
    doc.text(s.title, 14, y)
    doc.setTextColor(0,0,0)
    y += 6
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8)
    const textLines = doc.splitTextToSize(s.body, W - 28)
    doc.text(textLines, 14, y)
    y += textLines.length * 5 + 8
  })

  // Page 29
  doc.addPage()
  y = addHeader(doc, voyageNo, routeId, reportDate, 'Charter Party Compliance Auditing Methodology (cont.)')

  const sections29 = [
    { title: '5. Time Calculation', body: `Time loss or gained is calculated by comparing (a) Total Time at Good weather Performance Speed to (b) and (c) listed below. Time loss calculation (b) applies allowance for "about", while no allowance in (c) time gained calculation unless otherwise stipulated.\nThe report conclusion only reflects the Time Lost calculation result only.\n\n  Total Time at Good Weather Performance Speed = Total Distance / Good Weather Performance Speed (a)\n\n  Total Time at Warranted Speed - allowance = Total Distance / (Warranted Speed - Allowance) (b)\n\n  Total Time at Warranted Speed = Total Distance / Warranted Speed (c)\n\n  Time Lost = (a) - (b)          Time Gained = (c) - (a)` },
    { title: '6. Bunker Analysis Methodology for Bunker Type Switch-Over', body: `The following methodology will be applied to analyze bunker consumption when the bunker type is switched over, such as in ECA/SECA zone.\n\n6-1 DO/GO consumption in the switch over period will be compared to the charter party warranted IFO figure.\n6-2 Considering DO/GO consumption in the switch over period the amount of DO/GO consumed will initially be compared to the DO/GO warranted figure; the remaining DO/GO consumed in the switch over period will then be compared to the warranted IFO figure. In cases of partial steaming days, the DO/GO consumed will be converted basis a calculation for hourly consumption.` },
  ]

  sections29.forEach(s => {
    if (y > 250) return
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(9)
    doc.setTextColor(...NAVY)
    doc.text(s.title, 14, y)
    doc.setTextColor(0,0,0)
    y += 6
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8)
    const textLines = doc.splitTextToSize(s.body, W - 28)
    doc.text(textLines, 14, y)
    y += textLines.length * 5 + 8
  })
}

// ── Main export function ───────────────────────────────────────────────────

/**
 * generateVoyagePdf
 * @param {object} opts
 * @param {string} opts.vesselImo     - IMO number
 * @param {string} opts.vesselName    - Human-readable vessel name
 * @param {string} opts.voyageNo      - Voyage number (first if multi)
 * @param {string[]} opts.voyageNos   - All selected voyage numbers
 * @param {string} opts.source        - 'wni' | 'mari_apps' | 'all'
 * @param {string} opts.loadingCond   - 'Laden' | 'Ballast' | 'all'
 * @param {Function} opts.onProgress  - (msg) => void progress callback
 */
export async function generateVoyagePdf({ vesselImo, vesselName, voyageNo, voyageNos, source, loadingCond, onProgress }) {
  onProgress?.('Fetching voyage summary…')

  // ── 1. Fetch all data in parallel ────────────────────────────────────────
  const [sum, series, cpData] = await Promise.all([
    fetchVoyageSummary(voyageNo, vesselImo).catch(() => ({})),
    fetchVoyageSeries(voyageNo, vesselImo).catch(() => []),
    fetchCPPerformance(vesselImo, voyageNos, source === 'all' ? undefined : source, loadingCond === 'all' ? undefined : loadingCond).catch(() => null),
  ])

  onProgress?.('Rendering charts & maps...')
  const pdfAssets = await capturePdfAssets(sum, series, cpData)

  onProgress?.('Building PDF…')

  // ── 2. Prepare metadata ───────────────────────────────────────────────────
  const now       = new Date()
  const reportDate = now.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
  const datestamp  = `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}`
  const paddedVoy  = String(voyageNo).padStart(6, '0')
  const routeId    = `sid${datestamp}_${paddedVoy}`
  const safeSource = (source && source !== 'all') ? source.toLowerCase() : 'all_sources'
  const filename   = `${safeSource}_${vesselImo}_${voyageNo}.pdf`.replace(/[^a-zA-Z0-9_.-]/g, '_')

  // ── 3. Create jsPDF instance (A4) ────────────────────────────────────────
  const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' })

  // ── 4. Build all pages ────────────────────────────────────────────────────
  buildCoverPage(doc, sum, cpData, vesselName, voyageNo, routeId, reportDate)
  buildSpeedConsPage(doc, sum, series, cpData, routeId, reportDate, voyageNo)
  buildMethodologyPage1(doc, sum, series, cpData, routeId, reportDate, voyageNo)
  buildSummaryTablePage(doc, sum, series, routeId, reportDate, voyageNo)

  if (series.length > 0) {
    buildPositionPages(doc, sum, series, cpData, vesselName, routeId, reportDate, voyageNo)
    buildFuelPage(doc, sum, series, cpData, routeId, reportDate, voyageNo, vesselName)
    if (pdfAssets?.chartsDataUrl) buildChartsPage(doc, pdfAssets.chartsDataUrl)
    buildMessageTrafficPages(doc, series, routeId, reportDate, voyageNo)
  }

  buildCPMethodologyPages(doc, routeId, reportDate, voyageNo)

  // ── 5. Add page numbers retroactively ─────────────────────────────────────
  const totalPages = doc.internal.getNumberOfPages()
  for (let p = 1; p <= totalPages; p++) {
    doc.setPage(p)
    addFooter(doc, p, totalPages)
  }

  // ── 6. Save ──────────────────────────────────────────────────────────────
  onProgress?.(`Saving ${filename}…`)
  doc.save(filename)

  return { filename, pages: totalPages }
}

function buildChartsPage(doc, imgDataUrl) {
  doc.addPage('a4', 'portrait')
  // The charts DOM was 1000x1400 (ratio 1:1.4)
  // A4 portrait is 210 x 297 mm (ratio ~1:1.41)
  doc.addImage(imgDataUrl, 'JPEG', 0, 0, 210, 297)
}
