/**
 * voyagePdfExport.js
 * ------------------
 * Generates a WNI-style Voyage Audit Report PDF using jsPDF + jsPDF-AutoTable.
 *
 * Page Structure (reordered per client request 2026-09 — Speed & Weather
 * Analysis and Fuel Consumption Analysis moved up right after the cover
 * page; CP Performance Charts and the weather-current chart image moved
 * down to where those used to sit; Message Traffic removed entirely):
 *   Page 1   — Cover / Voyage Header
 *   Page 2   — Speed & Weather Analysis Summary Table
 *   Next     — Positions & Weather Detail (8 rows / page)
 *   Next     — Fuel Consumption Analysis
 *   Next     — Speed & Consumption Summary (Good Wx / All Wx)
 *   Next     — Consumption Calculation Methodology
 *   Next     — CP Performance Charts: (A) Good-Weather Speed & Fuel/Day vs CP
 *              Warranty + allowance bands, trended across this vessel's last
 *              10 voyages in this voyage's loading condition, and (B) Time &
 *              Fuel Loss/Saving, last 10 voyages of that SAME condition (see
 *              CPChartsRenderer.jsx)
 *   Next     — Ship Speed / FO Consumption+RPM / DO-GO Consumption+RPM /
 *              Wind Speed / Wave Height+Current charts (see
 *              PdfHiddenRenderer.jsx)
 *   Last 2   — CP Compliance Audit Methodology (static)
 */

import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'
import { capturePdfAssets } from './PdfHiddenRenderer'
import { captureCPCharts } from './CPChartsRenderer'
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
  if (!iso || typeof iso !== 'string' || iso.length < 10) return iso || '—'
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const yr = iso.substring(0, 4)
  const m = parseInt(iso.substring(5, 7), 10) - 1
  const day = iso.substring(8, 10)
  return `${day} ${months[m]} ${yr}`
}

const fmtDateTime = (iso) => {
  if (!iso || typeof iso !== 'string' || iso.length < 16) return iso || '—'
  const months = ['January','February','March','April','May','June','July','August','September','October','November','December']
  const yr = iso.substring(0, 4)
  const m = parseInt(iso.substring(5, 7), 10) - 1
  const day = iso.substring(8, 10)
  const hr = iso.substring(11, 13)
  const min = iso.substring(14, 16)
  return `${months[m]} ${day}, ${yr} ${hr}:${min}UTC`
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

// Matches backend cp_calculator.py's _is_fair_weather() EXACTLY: reads
// BF_Wind directly (not recomputed from True_Wind_Spd_ms via bfScale — that
// used a different, narrower day-set than the backend's own good_wx/entire
// aggregates, causing this table's distance/duration figures to disagree
// with its own FO/GO figures — manager feedback 2026-09). Missing just one
// of BF/Hs → not fair (can't verify); missing BOTH → treat as good weather
// (client-approved 2026-08) rather than penalise a logging gap.
const FAIR_BF_MAX = 4.0
const FAIR_WAVE_MAX_M = 3.0
// Displays the master's actual reported Beaufort figure (BF_Wind) — the
// SAME field the fair-weather calculation itself reads — falling back to
// the derived bfScale(True_Wind_Spd_ms) only when BF_Wind is genuinely
// missing. Found 2026-09 (verified against raw source data on two real
// voyages): the WEATHERNEWS ANALYSIS table's "WIND RF" column and the
// synthesized message-traffic text were both showing bfScale(wind speed)
// unconditionally, which can disagree with BF_Wind even though BF_Wind is
// confirmed to match the master's own raw-entered figure exactly — making
// the report's own displayed wind force number contradict the one that
// actually decided good/adverse weather for that day.
function bfDisplay(r) {
  return r.BF_Wind != null && r.BF_Wind !== '' ? String(Math.round(+r.BF_Wind)) : bfScale(r.True_Wind_Spd_ms)
}

function isFairWeatherRow(r) {
  const bf = r.BF_Wind != null && r.BF_Wind !== '' ? +r.BF_Wind : null
  const hs = r.Sig_Wave_Ht_m != null && r.Sig_Wave_Ht_m !== '' ? +r.Sig_Wave_Ht_m : null
  if (bf == null && hs == null) return true
  if (bf == null || hs == null) return false
  return bf <= FAIR_BF_MAX && hs <= FAIR_WAVE_MAX_M
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

// Groups a voyage's per-day parsed CP remarks (r.cp_instruction, from
// /voyage/series — see cp_remarks_parser.py) into consecutive same-
// instruction blocks. Returns null when there's 0 or 1 block (nothing to
// show beyond the existing CP Warranty box), or an array of
// { instr, days, startDate, endDate } when the voyage genuinely had more
// than one distinct instruction in force.
function computeVaryingCpInstruction(seriesRows) {
  const withInstr = (seriesRows || [])
    .filter(r => r.cp_instruction)
    .map(r => ({ date: r.Date, instr: r.cp_instruction }))
  if (withInstr.length === 0) return null

  const sameKey = (a, b) => a.speed_kn === b.speed_kn && a.total_mt_day === b.total_mt_day

  const blocks = []
  for (const { date, instr } of withInstr) {
    const last = blocks[blocks.length - 1]
    if (last && sameKey(last.instr, instr)) {
      last.days += 1
      last.endDate = date
    } else {
      blocks.push({ instr, days: 1, startDate: date, endDate: date })
    }
  }
  return blocks.length > 1 ? blocks : null
}

// Filters a voyage's seriesRows down to the "event-wise CP calculation"
// scope (client request 2026-09): excludes the COSP/BOSP boundary report
// itself, keeping every event from the next report (e.g. "Noon at Sea")
// through EOSP inclusive. /voyage/series already trims the series to the
// BOSP..EOSP window (see vessel_routes.py's dep_record/arr_record), so this
// just needs to drop the leading COSP/BOSP row.
function eventWiseCpRows(seriesRows) {
  return (seriesRows || []).filter(r => !/COSP|BOSP/i.test(r.event_type || ''))
}

// Resolves the CP speed/FO/GO that actually applied on ONE event/day:
// that day's parsed CP remarks instruction (cp_instruction) if one exists,
// otherwise the vessel's standing CP warranty. GO falls back to the standing
// warranty EXCEPT when the remarks parser found a real LSMGO figure
// (Format C — "INSTRUCTED CP SPEED ... / VLSFO CONSUMPTION ... / LSMGO
// CONSUMPTION: Z MT" — the only remarks format with its own GO figure); most
// remarks formats only ever specify one combined IFO figure and have no
// go_mt_day to use (manager feedback 2026-09: LSMGO for CP wasn't being
// captured even when the remarks explicitly stated it).
function eventCpFigures(row, cpW) {
  const instr = row.cp_instruction
  return {
    speed: instr?.speed_kn ?? +(cpW.speed_kn || 0),
    fo:    instr?.total_mt_day ?? +(cpW.fo_mtpd || 0),
    go:    instr?.go_mt_day ?? +(cpW.dogo_mtpd || 0),
  }
}

// Cumulative event-wise Time-at-Warranted-Speed figures (formulas b/c) and
// Max/Min Warranted Consumption figures (formulas e/f) — client request
// 2026-09: previously ONE division using a single fixed CP warranty figure
// for the whole voyage; now summed per-event using whichever CP instruction
// actually applied that day.
//
// DOUBT — flagged for the client to confirm, not yet answered: should the
// ±tolerance in (b)/(e)/(f) apply per-event (that day's own applicable
// speed/consumption ± tolerance, as implemented here per explicit
// instruction 2026-09), or should tolerance only ever apply around the
// single standing warranty regardless of a day having its own override?
function computeEventWiseCp(seriesRows, cpW, tolKn, tolPct) {
  const rows = eventWiseCpRows(seriesRows)
  let bHours = 0, cHours = 0, eTot = 0, fTot = 0, eventCount = 0
  rows.forEach(r => {
    const dist = +(r.Distance_nm) || 0
    const { speed, fo, go } = eventCpFigures(r, cpW)
    if (dist <= 0 || !speed) return
    eventCount += 1
    const effSpeed  = speed - tolKn
    const totalMax  = (fo + go) * (1 + tolPct / 100)
    const totalMin  = (fo + go) * (1 - tolPct / 100)
    cHours += dist / speed
    fTot   += (dist / speed) * (totalMin / 24)
    if (effSpeed > 0) {
      bHours += dist / effSpeed
      eTot   += (dist / effSpeed) * (totalMax / 24)
    }
  })
  return { bHours, cHours, eTot, fTot, eventCount }
}

// Same cumulative event-wise Max/Min Warranted Consumption as
// computeEventWiseCp(), but keeping FO and GO separate instead of combining
// them — needed so the cover page's FO/GO Lost-Saved boxes and Section C's
// combined total can both be derived from one source (eFO+eGO === the old
// combined eTot, exactly, since the tolerance % applies linearly either way).
function computeEventWiseCpSplit(seriesRows, cpW, tolKn, tolPct) {
  const rows = eventWiseCpRows(seriesRows)
  let eFO = 0, fFO = 0, eGO = 0, fGO = 0, eventCount = 0
  rows.forEach(r => {
    const dist = +(r.Distance_nm) || 0
    const { speed, fo, go } = eventCpFigures(r, cpW)
    if (dist <= 0 || !speed) return
    eventCount += 1
    const effSpeed = speed - tolKn
    fFO += (dist / speed) * (fo * (1 - tolPct / 100) / 24)
    fGO += (dist / speed) * (go * (1 - tolPct / 100) / 24)
    if (effSpeed > 0) {
      eFO += (dist / effSpeed) * (fo * (1 + tolPct / 100) / 24)
      eGO += (dist / effSpeed) * (go * (1 + tolPct / 100) / 24)
    }
  })
  return { eFO, fFO, eGO, fGO, eventCount }
}

const numOr0 = (v) => { const n = +v; return isNaN(n) ? 0 : n }

// Reclassifies GO into the FO/Total comparison figure using that day's own
// CP-remarks GO allowance (manager methodology 2026-09): in rough weather a
// vessel may be forced to burn GO in place of its normal fuel, so for
// FO-warranty comparison purposes that GO needs folding into the FO figure.
// This is deliberately ADDITIVE, not a bucket-move — GO's own separate
// consumption and its own comparison against the GO warranty are untouched;
// only the FO/Total side gains this amount ("GO to be included ON the FO
// calculation itself", manager's own wording).
//   a = that day's CP-remarks GO allowance (0 if the day has no per-day GO
//       instruction at all — explicit fallback, NOT the standing GO warranty)
//   b = that day's actual raw GO consumption
//   b - a > 0  -> add the EXCESS (b - a) to that day's FO figure
//   b - a <= 0 -> add the FULL raw GO amount (b) to that day's FO figure
function reclassifiedFO(hfoRaw, goRaw, goAllowanceOrNull) {
  const a = goAllowanceOrNull ?? 0
  const excess = goRaw - a
  return hfoRaw + (excess > 0 ? excess : goRaw)
}

// Per-row TRUE FO (HFO+LFO) vs GO (MDO) totals, summed across all 4
// consumers (ME, AE, Aux Boiler "bl", Composite Boiler "combl"), plus the
// reclassified FO figure (see reclassifiedFO above) for CP comparison.
function sumFuelGrades(rows) {
  let fo = 0, go = 0, foReclassified = 0
  rows.forEach(r => {
    const hfo = numOr0(r.me_hfo) + numOr0(r.me_lfo) + numOr0(r.ae_hfo) + numOr0(r.ae_lfo)
              + numOr0(r.bl_hfo) + numOr0(r.bl_lfo) + numOr0(r.combl_hfo) + numOr0(r.combl_lfo)
    const mdo = numOr0(r.me_mdo) + numOr0(r.ae_mdo) + numOr0(r.bl_mdo) + numOr0(r.combl_mdo)
    fo += hfo
    go += mdo
    foReclassified += reclassifiedFO(hfo, mdo, r.cp_instruction?.go_mt_day)
  })
  return { fo, go, foReclassified }
}

// Actual-side (d)-style figures, split FO/GO, extrapolated over the entire
// voyage distance at the achieved good-weather speed — same shape as the
// existing combined (d')/(d_tot), just split so FO uses the reclassified
// total and GO uses the raw total, each compared against its own warranty.
function computeActualConsumptionSplit(seriesRows, cp) {
  const goodRows  = (seriesRows || []).filter(isFairWeatherRow)
  const { go, foReclassified } = sumFuelGrades(goodRows)
  const goodTimeB = cp.good_wx?.time_h ?? 0
  const gwSpeedB  = cp.good_wx?.avg_speed_kn || 0
  const distE     = cp.entire?.distance_nm || (seriesRows || []).reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  if (!(goodTimeB > 0) || !(gwSpeedB > 0)) return { dFO: 0, dGO: 0, distE, gwSpeedB, goodTimeB, foReclassified, go }
  return {
    dFO: (distE / gwSpeedB) * (foReclassified / goodTimeB),
    dGO: (distE / gwSpeedB) * (go / goodTimeB),
    distE, gwSpeedB, goodTimeB, foReclassified, go,
  }
}

// The full Time Lost/Gained conclusion (formulas a/b/c) — factored out so
// the cover page's Lost/Saved box and Section B's own detailed workings
// always show the SAME number, computed the SAME (event-wise) way, instead
// of the cover page pulling a different figure from the backend's simpler
// single-warranty cp.loss.time_h (client request 2026-09).
function computeTimeLostGained(seriesRows, cp, cpW, tolKn) {
  const gwSpeedB = cp.good_wx?.avg_speed_kn || 0
  const distE    = cp.entire?.distance_nm || (seriesRows || []).reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const tolPct   = cp.allowance?.cons_pct != null ? +cp.allowance.cons_pct : 5.0
  const evCp = computeEventWiseCp(seriesRows, cpW, tolKn, tolPct)
  const a = gwSpeedB > 0 ? distE / gwSpeedB : 0
  const b = evCp.bHours
  const c = evCp.cHours
  const timeLost   = a - b
  const timeGained = c - a
  let concludedHours = 0, concludedIsLoss = false, concludedNeutral = false
  if (timeLost > 0) {
    concludedIsLoss = true
    concludedHours = timeLost
  } else if (timeGained > 0) {
    concludedHours = timeGained
  } else {
    concludedNeutral = true
  }
  return { a, b, c, timeLost, timeGained, concludedHours, concludedIsLoss, concludedNeutral, eventCount: evCp.eventCount }
}

// ── Equipment x fuel-type consumption breakdown (client request 2026-09) ──
// Replaces the old flat "FO (mt)" / "DO/GO (mt)" columns wherever they
// appear (the compact Periods table — duplicated 3x across the report — and
// the daily Fuel Consumption Analysis table) with a real per-consumer,
// per-grade breakdown. "BLR" combines Aux Boiler ("bl") + Composite Boiler
// ("combl") for this summary-level view (kept separate on the Logbook+
// column list per a separate, later manager decision — this report table
// is a different, simpler context). "Others" catches every other tracked
// consumer (Incinerator "inc", Emergency Generator "eg", and the 2
// remaining schema consumers "aeb"/"blfo").
//
// FO category = HFO + LFO + BIO per consumer; DO/GO category = MDO per
// consumer — matches the established FO/GO convention used elsewhere in
// this codebase (cp_routes.py, emission_routes.py). Confirmed against real
// data: MDO consumption can occur on ANY consumer (ME/AE/Boiler), not just
// as a separate bunker type, so "GO" here means "MDO burned by any
// equipment", not "fuel from a separate GO tank".
const _EQUIPMENT_GROUPS = [
  { label: 'ME',     prefixes: ['me'] },
  { label: 'AE',     prefixes: ['ae'] },
  { label: 'BLR',    prefixes: ['bl', 'combl'] },
  { label: 'Others', prefixes: ['inc', 'eg', 'aeb', 'blfo'] },
]
const _FO_GRADES = ['hfo', 'lfo', 'bio_fuel']
const _GO_GRADES = ['mdo']
const _GRADE_LABEL = { hfo: 'HFO', lfo: 'LFO', bio_fuel: 'BIO', mdo: 'MDO' }

function _numOrNull(v) {
  if (v == null || v === '') return null
  const n = +v
  return isNaN(n) ? null : n
}

// Determines which FO/GO grade columns actually have any NON-ZERO value
// anywhere across the WHOLE voyage — computed once from the full
// seriesRows (never per-subset), so a column's presence is consistent
// across every row of a table built from different row subsets (e.g. the
// Entire/Good/Adverse/Excluded rows of the same Periods table).
//
// Client correction 2026-09: a column that's always exactly 0 (not null,
// just zero — e.g. "Others" consumers with no real activity this voyage)
// conveys nothing useful and must be hidden the same as a genuinely null
// column — treating 0 as "has a value" was the actual bug that left
// all-zero Others/BIO columns cluttering the report.
function activeGradesForVoyage(seriesRows) {
  const hasAny = (grade) => _EQUIPMENT_GROUPS.some(g =>
    g.prefixes.some(p => seriesRows.some(r => (_numOrNull(r[`${p}_${grade}`]) || 0) !== 0))
  )
  return {
    fo: _FO_GRADES.filter(hasAny),
    go: _GO_GRADES.filter(hasAny),
  }
}

// Sums one equipment group's one grade across a set of rows. Returns 0 if
// nothing summed (used for the actual displayed total) — the decision of
// whether a grade column should exist AT ALL is activeGradesForVoyage's job
// (voyage-wide), not this function's.
function _sumGroupGrade(rows, prefixes, grade) {
  let sum = 0
  rows.forEach(r => {
    prefixes.forEach(p => { sum += _numOrNull(r[`${p}_${grade}`]) || 0 })
  })
  return sum
}

// Builds the full equipment x fuel-type breakdown for one set of rows (e.g.
// one period, or one day). Returns an array of 5 entries — ME/AE/BLR/
// Others/Total — each { label, cells: {grade: value}, foTotal, goTotal,
// total }. activeFoGrades/activeGoGrades come from activeGradesForVoyage()
// so hidden columns stay hidden consistently across every row.
function computeEquipmentFuelBreakdown(rows, activeFoGrades, activeGoGrades) {
  const allGrades = [...activeFoGrades, ...activeGoGrades]
  const perEquip = _EQUIPMENT_GROUPS.map(g => {
    const cells = {}
    allGrades.forEach(gr => { cells[gr] = _sumGroupGrade(rows, g.prefixes, gr) })
    const foTotal = activeFoGrades.reduce((s, gr) => s + cells[gr], 0)
    const goTotal = activeGoGrades.reduce((s, gr) => s + cells[gr], 0)
    return { label: g.label, cells, foTotal, goTotal, total: foTotal + goTotal }
  })
  const totalRow = {
    label: 'Total',
    cells: Object.fromEntries(allGrades.map(gr => [gr, perEquip.reduce((s, e) => s + e.cells[gr], 0)])),
    foTotal: perEquip.reduce((s, e) => s + e.foTotal, 0),
    goTotal: perEquip.reduce((s, e) => s + e.goTotal, 0),
    total: perEquip.reduce((s, e) => s + e.total, 0),
  }
  return [...perEquip, totalRow]
}

// Builds the nested autoTable head rows for the equipment x fuel-type
// breakdown, given the columns that come BEFORE it (e.g. Periods/Distance/
// Time/Speed) as `leadCols` (each a {content, rowSpan} head cell spanning
// all header rows) and how many header rows this table has above the
// fuel-breakdown block (`headRows`, so rowSpan lines up). Returns
// {head: [...rows], flatCols} where flatCols is the ordered list of
// {equip, grade|'foTotal'|'goTotal'} used to build body rows in the same
// column order.
function buildEquipmentFuelHead(leadCols, activeFoGrades, activeGoGrades, trailCols = []) {
  const equipLabels = ['ME', 'AE', 'BLR', 'Others', 'Total']
  const flatCols = []
  const foSubCols = []
  equipLabels.forEach(label => {
    activeFoGrades.forEach(gr => { foSubCols.push({ content: _GRADE_LABEL[gr] }); flatCols.push({ equip: label, grade: gr }) })
    // Client correction 2026-09: no per-equipment Total sub-column for
    // ME/AE/BLR/Others (redundant with the raw grade values) — only the
    // aggregate "Total" equipment-group keeps one, which doubles as the
    // single overall "FO Total" figure requested separately.
    if (label === 'Total') { foSubCols.push({ content: 'Total' }); flatCols.push({ equip: label, grade: 'foTotal' }) }
  })
  const goSubCols = []
  equipLabels.forEach(label => {
    activeGoGrades.forEach(gr => { goSubCols.push({ content: _GRADE_LABEL[gr] }); flatCols.push({ equip: label, grade: gr }) })
    if (label === 'Total') { goSubCols.push({ content: 'Total' }); flatCols.push({ equip: label, grade: 'goTotal' }) }
  })
  flatCols.push({ equip: 'Grand', grade: 'total' })

  const equipHeaderRowFo = equipLabels.map(label => ({
    content: label, colSpan: activeFoGrades.length + (label === 'Total' ? 1 : 0), styles: { halign: 'center' },
  }))
  const equipHeaderRowGo = equipLabels.map(label => ({
    content: label, colSpan: activeGoGrades.length + (label === 'Total' ? 1 : 0), styles: { halign: 'center' },
  }))

  const foGroupSpan = activeFoGrades.length * equipLabels.length + 1 // +1 for Total's own extra sub-column
  const goGroupSpan = activeGoGrades.length * equipLabels.length + 1
  const head = [
    [
      ...leadCols,
      { content: 'FO (mt)', colSpan: foGroupSpan, styles: { halign: 'center' } },
      { content: 'DO/GO (mt)', colSpan: goGroupSpan, styles: { halign: 'center' } },
      { content: 'Total (mt)', rowSpan: 3, styles: { valign: 'middle' } },
      ...trailCols,
    ],
    [...equipHeaderRowFo, ...equipHeaderRowGo],
    [...foSubCols, ...goSubCols],
  ]
  return { head, flatCols }
}

// Renders one breakdown row (e.g. one Period, or one day) as a flat array
// of formatted cell strings, in the same order as buildEquipmentFuelHead's
// flatCols.
function equipmentFuelRowCells(rows, activeFoGrades, activeGoGrades, decimals = 2) {
  const breakdown = computeEquipmentFuelBreakdown(rows, activeFoGrades, activeGoGrades)
  const byLabel = Object.fromEntries(breakdown.map(b => [b.label, b]))
  const cells = []
  ;['ME', 'AE', 'BLR', 'Others', 'Total'].forEach(label => {
    const b = byLabel[label]
    activeFoGrades.forEach(gr => cells.push(fmt(b.cells[gr], decimals)))
    if (label === 'Total') cells.push(fmt(b.foTotal, decimals))
  })
  ;['ME', 'AE', 'BLR', 'Others', 'Total'].forEach(label => {
    const b = byLabel[label]
    activeGoGrades.forEach(gr => cells.push(fmt(b.cells[gr], decimals)))
    if (label === 'Total') cells.push(fmt(b.goTotal, decimals))
  })
  cells.push(fmt(byLabel.Total.total, decimals))
  return cells
}

// ── Page builders ──────────────────────────────────────────────────────────

/** Page 1 — Cover / Voyage Header */
function buildCoverPage(doc, sum, cpData, vesselName, voyageNo, routeId, reportDate, series, dataWarning) {
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

  // Visible warning when one or more of the report's data fetches genuinely
  // failed (server/network error, not just "no data") — surfaces the
  // failure instead of silently rendering blank charts/zeroed tables as if
  // that were the real answer (found 2026-09: a Postgres connection-pool
  // exhaustion caused /voyage/series to fail mid-report with no visible
  // sign in the PDF at all).
  if (dataWarning) {
    doc.setFillColor(255, 235, 235)
    doc.setDrawColor(200, 40, 40)
    doc.setLineWidth(0.4)
    const boxH = 14
    doc.rect(14, y, W - 28, boxH, 'FD')
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(9)
    doc.setTextColor(180, 20, 20)
    doc.text('⚠ Some data could not be loaded — this report may be incomplete', W / 2, y + 6, { align: 'center' })
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7.5)
    doc.text(dataWarning, W / 2, y + 11, { align: 'center' })
    doc.setTextColor(0, 0, 0)
    y += boxH + 6
  }

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

  // This box now mirrors Sections B/C's own event-wise, CP-remarks-aware
  // conclusions (manager request 2026-09) instead of the backend's simpler
  // single-warranty cp.loss figures — so page 1's headline numbers always
  // match the detailed workings on pages 4-5, not a different calculation.
  const tolKn  = cp.allowance?.speed_kn != null ? +cp.allowance.speed_kn : 0.5
  const tolPct = cp.allowance?.cons_pct != null ? +cp.allowance.cons_pct : 5.0
  const timeConclusion = computeTimeLostGained(series, cp, cpW, tolKn)
  const { dFO } = computeActualConsumptionSplit(series, cp)
  const { eFO, fFO } = computeEventWiseCpSplit(series, cpW, tolKn, tolPct)
  const foLossCover = dFO > eFO ? dFO - eFO : (dFO < fFO ? -(fFO - dFO) : 0)

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  const lblX = 14
  const valX = 45
  const dtX = 100
  let dy = y
  
  doc.text('Vessel Name:', lblX, dy); doc.setFont('helvetica', 'normal'); doc.text(vesselName, valX, dy); dy += 5;
  doc.setFont('helvetica', 'bold'); doc.text('Prepared for:', lblX, dy); doc.setFont('helvetica', 'normal'); doc.text('Ozellar', valX, dy); dy += 5;
  doc.setFont('helvetica', 'bold'); doc.text('Departure - COSP :', lblX, dy); doc.setFont('helvetica', 'normal'); doc.text(sum.From_Port || '—', valX, dy); doc.text(fmtDateTime(sum.Departure_Time) || '', dtX, dy); dy += 5;
  doc.setFont('helvetica', 'bold'); doc.text('Arrival - EOSP :', lblX, dy); doc.setFont('helvetica', 'normal'); doc.text(sum.To_Port || '—', valX, dy); doc.text(fmtDateTime(sum.Arrival_Time) || '', dtX, dy); dy += 5;
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
  // cpGD.wind/sea_state are already human-formatted strings from the backend
  // ("BF 4", "Sig.Wave 3.0m") — don't prepend "Wind Beaufort Force"/"Significant
  // wave height" in front of them, that duplicates the wording (produced
  // "Significant wave height Sig.Wave 3.0m meters").
  const gwText = `Wind ${cpGD.wind || 'BF 4'}, Sea State ${cpGD.sea_state || 'Sig.Wave 3.0m'} (Douglas Sea State 3), no adverse current`
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
    
    const tLoss = timeConclusion.concludedNeutral ? 0 : (timeConclusion.concludedIsLoss ? timeConclusion.concludedHours : -timeConclusion.concludedHours)
    if (tLoss > 0) {
      doc.setFillColor(255, 0, 0)
      doc.rect(80, y + 14, 20, 5, 'F')
      doc.setTextColor(255, 255, 255)
      doc.text(`${tLoss.toFixed(2)} hrs`, 90, y + 17.5, { align: 'center' })
    } else if (tLoss < 0) {
      doc.setFillColor(0, 153, 0)
      doc.rect(80, y + 21, 20, 5, 'F')
      doc.setTextColor(255, 255, 255)
      doc.text(`${Math.abs(tLoss).toFixed(2)} hrs`, 90, y + 24.5, { align: 'center' })
    }
    doc.setTextColor(0, 0, 0)
    
    // FO
    const foLoss = foLossCover
    doc.setFont('helvetica', 'bold')
    if (foLoss > 0) {
      doc.setFillColor(255, 0, 0)
      doc.rect(120, y + 14, 20, 5, 'F')
      doc.setTextColor(255, 255, 255)
      doc.text(`${foLoss.toFixed(2)} MT`, 130, y + 17.5, { align: 'center' })
    } else if (foLoss < 0) {
      doc.setFillColor(0, 153, 0)
      doc.rect(120, y + 21, 20, 5, 'F')
      doc.setTextColor(255, 255, 255)
      doc.text(`${Math.abs(foLoss).toFixed(2)} MT`, 130, y + 24.5, { align: 'center' })
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
    
    // GO — no separate comparison shown here any more (manager instruction
    // 2026-09): GO is already folded into the FO figure above via the
    // reclassification, so a second, independent GO-vs-GO-warranty verdict
    // on the same cover page would double up on (and could contradict) the
    // FO box's own conclusion. GO's raw consumption is still visible on its
    // own in Section A's table; this box just no longer renders a verdict.
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    doc.setTextColor(0, 0, 0)
    doc.text('No GO', 170, y + 12, { align: 'center' })
    doc.text('Over-consumption/', 170, y + 16, { align: 'center' })
    doc.text('Saving', 170, y + 20, { align: 'center' })
    doc.setFontSize(7.5)
    
    // CP Warranty Footer
    doc.line(14, y + 33, W - 14, y + 33)
    doc.setFont('helvetica', 'normal')
    doc.text('CP Warranty', 70, y + 38, { align: 'right' })
    doc.text(`about ${fmt(cpW.speed_kn)} Knots`, 90, y + 38, { align: 'center' })
    doc.text(`about ${fmt(cpW.fo_mtpd)} MT/day`, 130, y + 38, { align: 'center' })
    doc.text(`about ${fmt(cpW.dogo_mtpd)} MT/day`, 170, y + 38, { align: 'center' })

    // ── Varying CP Instruction (client request 2026-09) ────────────────────
    // The CP Warranty box above is always ONE fixed figure — but the
    // master's day-to-day remarks (cpx_remarks, parsed via
    // cp_remarks_parser.py) can carry a DIFFERENT instruction for some days
    // of this same voyage (Eco vs Full speed, an ETA-driven order, a
    // mid-voyage revision). When that happened, show the per-day breakdown
    // here IN ADDITION TO the box above (never replacing it) so a reader
    // sees exactly how many days each instruction was actually in force.
    //
    // NOTE: most remarks formats only ever specify ONE combined IFO figure
    // (split M/E vs A/E), never a separate GO/DO figure — "GO" below shows
    // that day's parsed go_mt_day when the remarks format did carry one
    // (Format C — LSMGO consumption; manager feedback 2026-09), otherwise
    // "—" reflecting that the source remarks genuinely didn't state one.
    const cpBlocks = computeVaryingCpInstruction(series)
    if (cpBlocks) {
      let vy = y + 48
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(9)
      doc.text('Varying CP instruction', 14, vy)
      vy += 6

      const colX = { days: 20, speed: 70, fo: 120, go: 170 }
      doc.setFontSize(8)
      doc.text('No. of Days', colX.days, vy)
      doc.text('Speed', colX.speed, vy, { align: 'center' })
      doc.text('FO', colX.fo, vy, { align: 'center' })
      doc.text('GO', colX.go, vy, { align: 'center' })
      vy += 2
      doc.setDrawColor(...MGRAY)
      doc.line(14, vy, W - 14, vy)
      vy += 5

      doc.setFont('helvetica', 'normal')
      cpBlocks.forEach((b, i) => {
        doc.text(`D${i + 1} (${b.days} day${b.days > 1 ? 's' : ''})`, colX.days, vy)
        doc.text(`${fmt(b.instr.speed_kn)} kn`, colX.speed, vy, { align: 'center' })
        doc.text(`${fmt(b.instr.total_mt_day)} MT/day`, colX.fo, vy, { align: 'center' })
        doc.text(b.instr.go_mt_day != null ? `${fmt(b.instr.go_mt_day)} MT/day` : '—', colX.go, vy, { align: 'center' })
        vy += 5
      })
    }
}

/** Page 2 — Speed & Consumption Calculation */
function buildSpeedConsPage(doc, sum, seriesRows, cpData, routeId, reportDate, voyageNo) {
  doc.addPage()
  let y = addHeader(doc, voyageNo, routeId, reportDate, 'Speed and Consumption Calculation')

  const W = doc.internal.pageSize.getWidth()
  const cp = cpData?.results?.[0] || {}

  // Route label now lives on the CP Charts page instead — see
  // CPChartsRenderer.jsx's routeCaption — so it isn't repeated here.
  y = sectionTitle(doc, y, 'A. Good Weather Analysis')
  y += 5
  
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.text("The following days were analyzed as 'Good Weather Days'.", 14, y)
  y += 4

  // Good/All weather figures come straight from the backend's cp.good_wx /
  // cp.entire aggregates (same source as the CP Performance table, Section B,
  // and Section C) — NOT a local re-filter of seriesRows. That local filter
  // used to read good_wx_def.wind/sea_state as numbers, but those fields are
  // human-readable strings ("BF 4", "Sig.Wave 3.0m"); `+"Sig.Wave 3.0m"` is
  // NaN, so it silently fell back to a hardcoded 1.25m wave cutoff instead of
  // the real 3.0m fair-weather threshold (backend FAIR_WAVE_MAX_M) — pulling
  // in a much smaller/wrong subset of "good weather" days and producing
  // numbers that didn't match the rest of the report. The displayed date
  // range and the FO/GO breakdown below both use isFairWeatherRow(), the
  // same definition as the backend's cp.good_wx aggregate, so every figure
  // in this section describes the same set of days (manager feedback
  // 2026-09: a locally-recomputed filter here previously disagreed with
  // cp.good_wx's day count, e.g. "1 day" shown next to "115.00 hours").
  const goodRows = seriesRows.filter(isFairWeatherRow)

  let dateRangeStr = '—'
  if (goodRows.length > 0) {
    const startStr = fmtDate(goodRows[0].Date)
    const endStr = fmtDate(goodRows[goodRows.length - 1].Date)
    dateRangeStr = `${startStr} to ${endStr}`
  }
  doc.text(dateRangeStr, 14, y)
  y += 6

  const totalDist  = cp.entire?.distance_nm ?? seriesRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const totalDur   = cp.entire?.time_h ?? seriesRows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)

  const goodDist   = cp.good_wx?.distance_nm ?? 0
  const goodDur    = cp.good_wx?.time_h ?? 0

  const totalSpeed = cp.entire?.avg_speed_kn ?? (totalDur > 0 ? totalDist / totalDur : 0)
  const goodSpeed  = cp.good_wx?.avg_speed_kn ?? (goodDur > 0 ? goodDist / goodDur : 0)

  // TRUE FO (HFO+LFO) vs GO (MDO) totals, summed per-row across all 4
  // consumers (ME, AE, Aux Boiler "bl", Composite Boiler "combl") — client
  // request 2026-09: replaces the previous approximation that treated all
  // ME consumption as FO and all AE+Boiler consumption as GO. Fields come
  // straight from /voyage/series (me_hfo/me_lfo/me_mdo etc.), not from the
  // cp.entire/cp.good_wx aggregates (those don't carry a grade split).
  //
  // "FO Consumption" below is the RECLASSIFIED figure (manager methodology
  // 2026-09 — see reclassifiedFO()'s doc comment): GO burned in place of
  // normal fuel during rough weather is folded into this FO figure for CP
  // comparison purposes. "GO Consumption" stays the raw, un-reclassified
  // actual GO burn — it's still tracked and compared against the GO
  // warranty on its own; only FO/Total gains this amount, nothing is
  // subtracted out of GO.
  const goodGrades  = sumFuelGrades(goodRows)
  const totalGrades = sumFuelGrades(seriesRows)
  const goodFO  = goodGrades.foReclassified,  goodGO  = goodGrades.go
  const totalFO = totalGrades.foReclassified, totalGO = totalGrades.go

  const goodDailyFO  = goodDur > 0 ? goodFO / (goodDur / 24) : 0
  const totalDailyFO = totalDur > 0 ? totalFO / (totalDur / 24) : 0

  const goodDailyGO  = goodDur > 0 ? goodGO / (goodDur / 24) : 0
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
      ['Total FO Consumption** [MT]',   fmt(goodFO, 2), '-',    fmt(totalFO, 2), '-'],
      ['Total GO Consumption [MT]',     fmt(goodGO, 2), '-',    fmt(totalGO, 2), '-'],
      ['Total Fuel Consumption [MT]',   fmt(goodFO + goodGO, 2), '-', fmt(totalFO + totalGO, 2), '-'],
      ['Averaged Daily Total Consumption', fmt(goodDailyFO + goodDailyGO, 2), '-', fmt(totalDailyFO + totalDailyGO, 2), '-'],
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
  y += 3
  doc.text('**FO includes GO consumed in excess of (or, when not exceeded, in full) that period\'s CP-remarks GO allowance.', W - 24, y, { align: 'right' })

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

  // Use the SAME inputs the backend's good_wx/entire aggregates are built from
  // (cp.good_wx.avg_speed_kn, cp.entire.distance_nm, cp.allowance.speed_kn) so this
  // section is internally consistent — one set of (a)/(b)/(c) numbers feeding both
  // the formula text and the conclusion banner, never two different calculations.
  //
  // Two separate comparisons, per CP convention:
  //   Time Lost   = (a) - (b)  — (b) gets the 'about' allowance, benefit of the doubt to the vessel
  //   Time Gained = (c) - (a)  — (c) uses the full warranted speed, no allowance, to claim a saving
  // Only one of these can be positive at a time (or neither, inside the tolerance band) —
  // whichever is positive is the conclusion.
  const tolKn    = cp.allowance?.speed_kn != null ? +cp.allowance.speed_kn : 0.5
  const tolPct   = cp.allowance?.cons_pct != null ? +cp.allowance.cons_pct : 5.0
  const gwSpeedB = cp.good_wx?.avg_speed_kn || 0
  const distE    = cp.entire?.distance_nm || totalDist

  // (b)/(c) — cumulative EVENT-WISE Time at Warranted Speed (client request
  // 2026-09): a voyage with more than one CP instruction (varying speed/
  // consumption across days, see the Varying CP instruction table on page
  // 1) no longer gets ONE division against a single fixed warranted speed
  // for the whole voyage — each event from just after COSP through EOSP
  // uses whichever CP instruction actually applied that day, and the
  // resulting hours are summed. (a) is unchanged — it's the vessel's own
  // ACTUAL good-weather speed, not a CP instruction, so it's out of scope
  // for this change and still uses the full voyage distance (distE).
  const evCp = computeEventWiseCp(seriesRows, cpW, tolKn, tolPct)

  const p1 = "Time loss or gained is calculated by comparing (a) Total Time at Good Weather Performance Speed to (b) and (c) listed below. Both (b) and (c) are now computed cumulatively, event by event (excluding the COSP report), using whichever CP instruction actually applied on each day of the voyage — see the Varying CP instruction table on page 1 for voyages with more than one. Time loss calculation (b) applies a minus " + fmt(tolKn, 2) + " knot allowance for 'about' on each event's applicable speed, while no allowance is applied in (c)."
  const splitText = doc.splitTextToSize(p1, W - 28)
  doc.text(splitText, 14, y)
  y += splitText.length * 4 + 4

  // Math logic for time calculation
  const a = gwSpeedB > 0 ? distE / gwSpeedB : 0
  const b = evCp.bHours
  const c = evCp.cHours
  const timeLost   = a - b
  const timeGained = c - a

  // Formula table
  doc.rect(14, y, W - 28, 30)
  let fy = y + 5
  doc.setFontSize(7.5)

  doc.text('Total Time at Good Weather Performance Speed', 18, fy + 3)
  doc.text('=', 85, fy + 3)
  doc.text('Total Distance', 115, fy, { align: 'center' })
  doc.line(95, fy + 1, 135, fy + 1)
  doc.text('Good Weather Performance Speed', 115, fy + 4, { align: 'center' })
  doc.text(`= ${fmt(distE, 0)} / ${fmt(gwSpeedB, 2)} = ${fmt(a, 2)} Hours (a)`, 138, fy + 3)
  fy += 10

  doc.text(`Cumulative Time at Warranted Speed - ${fmt(tolKn, 2)} knots`, 18, fy + 3)
  doc.text('=', 85, fy + 3)
  doc.text('Total (Event Distance', 115, fy, { align: 'center' })
  doc.line(95, fy + 1, 135, fy + 1)
  doc.text(`Event Applicable CP Speed - ${fmt(tolKn, 2)} kn)`, 115, fy + 4, { align: 'center' })
  doc.text(`= ${fmt(b, 2)} Hours (b)  [${evCp.eventCount} events]`, 138, fy + 3)
  fy += 10

  doc.text('Cumulative Time at Warranted Speed', 18, fy + 3)
  doc.text('=', 85, fy + 3)
  doc.text('Total (Event Distance', 115, fy, { align: 'center' })
  doc.line(95, fy + 1, 135, fy + 1)
  doc.text('Event Applicable CP Speed)', 115, fy + 4, { align: 'center' })
  doc.text(`= ${fmt(c, 2)} Hours (c)  [${evCp.eventCount} events]`, 138, fy + 3)

  y += 36

  // Whichever of timeLost / timeGained is positive is the conclusion — same numbers,
  // same decision, feeding both the formula line below and the banner.
  let concludedHours = 0
  let concludedIsLoss = false
  let concludedNeutral = false
  if (wSpeed === 0) {
    doc.setFont('helvetica', 'italic')
    doc.text('No Warranted Speed data available for calculation.', 18, y)
    doc.setFont('helvetica', 'normal')
  } else if (timeLost > 0) {
    concludedIsLoss = true
    concludedHours = timeLost
    doc.text('Time Lost = (a) - (b)', 18, y)
    doc.text(`=  ${fmt(a, 2)} - ${fmt(b, 2)}  =  ${fmt(timeLost, 2)} Hours`, 55, y)
  } else if (timeGained > 0) {
    concludedIsLoss = false
    concludedHours = timeGained
    doc.text('Time Gained = (c) - (a)', 18, y)
    doc.text(`=  ${fmt(c, 2)} - ${fmt(a, 2)}  =  ${fmt(timeGained, 2)} Hours`, 55, y)
  } else {
    // Neither (a)-(b) nor (c)-(a) is positive — the voyage's actual time falls
    // inside the tolerance band (between the full-speed and allowance-adjusted
    // benchmarks). This is genuinely neither a loss nor a gain, so show the true
    // (negative) arithmetic honestly rather than mislabeling it "Time Gained"
    // and silently clamping the displayed result to 0.
    concludedNeutral = true
    concludedIsLoss = false
    concludedHours = 0
    doc.text('Within Tolerance', 18, y)
    doc.text(`(a) ${fmt(a, 2)} is between (b) ${fmt(b, 2)} and (c) ${fmt(c, 2)}  =  No Claim`, 50, y)
  }

  y += 10
  const bannerR = concludedIsLoss ? 255 : (concludedNeutral ? 120 : 34)
  const bannerG = concludedIsLoss ? 0   : (concludedNeutral ? 120 : 211)
  const bannerB = concludedIsLoss ? 0   : (concludedNeutral ? 120 : 153)
  doc.setFillColor(bannerR, bannerG, bannerB)
  doc.rect(14, y, W - 28, 6, 'F')
  doc.setTextColor(255, 255, 255)
  doc.setFont('helvetica', 'bold')
  if (wSpeed === 0) {
    doc.text('Conclusion: No Warranted Speed data available.', W / 2, y + 4.2, { align: 'center' })
  } else if (concludedNeutral) {
    doc.text('Conclusion: Within Tolerance — No Time Lost or Gained', W / 2, y + 4.2, { align: 'center' })
  } else if (concludedIsLoss) {
    doc.text(`Conclusion: ${concludedHours.toFixed(2)} Hours Lost`, W / 2, y + 4.2, { align: 'center' })
  } else {
    doc.text(`Conclusion: ${concludedHours.toFixed(2)} Hours Gained`, W / 2, y + 4.2, { align: 'center' })
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

  const cp   = cpData?.results?.[0] || {}
  const cpW  = cp.warranty || {}
  const wSpeed  = +(cpW.speed_kn || 0)
  const foW     = +(cpW.fo_mtpd || 0)
  const goW     = +(cpW.dogo_mtpd || 0)
  const tolKn   = cp.allowance?.speed_kn != null ? +cp.allowance.speed_kn : 0.5
  const tolPct  = cp.allowance?.cons_pct != null ? +cp.allowance.cons_pct : 5.0

  // Same backend-sourced inputs the Loss/Saving fo_mt/dogo_mt figures (shown in the
  // Charter-Party Performance table) are built from — good_wx avg speed/daily rates +
  // entire voyage distance + the actual configured allowance — so this section's
  // formula and its conclusion always resolve to those same numbers.
  const gwSpeedB = cp.good_wx?.avg_speed_kn || 0
  const distE    = cp.entire?.distance_nm || seriesRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const effSpd   = wSpeed - tolKn
  // Formula (d)'s own denominator is the voyage's REAL total Good Weather
  // Time (in hours), not the "24 hours" constant (e)/(f) use — confirmed
  // against WNI's own reference Voyage Audit Report (client-supplied
  // 2026-09, e.g. "20.02 / 18.8" where 18.8 is the real measured
  // Good-Weather Time, not 24). The numerator is the reclassified FO total
  // + raw GO total (manager methodology 2026-09, see reclassifiedFO()) —
  // computed here on the frontend from seriesRows/cp_instruction, not
  // pulled from the backend's cp.good_wx.fo_mt/dogo_mt any more, so this
  // figure and Section A's own FO/GO table stay consistent with each other.
  const { dFO, dGO, goodTimeB, foReclassified: goodTotalFOB, go: goodTotalGOB } = computeActualConsumptionSplit(seriesRows, cp)

  // Cumulative EVENT-WISE Max/Min Warranted Consumption (formulas e'/f') —
  // client request 2026-09: same event-by-event methodology as Section B's
  // (b)/(c), using whichever CP instruction actually applied each day
  // (excluding COSP). (d') is unchanged — it's the vessel's own ACTUAL
  // good-weather consumption rate, not a CP instruction, so out of scope.
  // Split FO/GO (see computeEventWiseCpSplit) so this page's numbers derive
  // from the same source as the cover page's separate FO/GO Lost-Saved
  // boxes — eFO+eGO here is identical to the old combined eTot.
  const cpSplit = computeEventWiseCpSplit(seriesRows, cpW, tolKn, tolPct)
  const evCp = { eTot: cpSplit.eFO + cpSplit.eGO, fTot: cpSplit.fFO + cpSplit.fGO, eventCount: cpSplit.eventCount }

  const foMax = foW * (1 + tolPct / 100)
  const foMin = foW * (1 - tolPct / 100)
  const goMax = goW * (1 + tolPct / 100)
  const goMin = goW * (1 - tolPct / 100)

  doc.setFontSize(8)
  doc.setFont('helvetica', 'normal')
  doc.text(`Unless otherwise specified, the fuel over-consumption assessment as well as fuel under-consumption assessment`, 14, y)
  y += 4
  doc.text(`employ a ${fmt(tolPct, 1)}% tolerance. Effective warranted consumption`, 14, y)
  y += 5

  if (wSpeed > 0) {
    doc.text(`Fuel over-consumption: ${fmt(foMax, 2)} MT (a plus ${fmt(tolPct, 1)}% tolerance applied) and ${fmt(goMax, 2)} MT DO/GO (a plus ${fmt(tolPct, 1)}% tolerance applied)`, 14, y)
    y += 4
    doc.text(`Fuel under-consumption: ${fmt(foMin, 2)} MT (a minus ${fmt(tolPct, 1)}% tolerance applied) and ${fmt(goMin, 2)} MT DO/GO (a minus ${fmt(tolPct, 1)}% tolerance applied)`, 14, y)
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
  
  // Total Consumption Block
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  doc.text('Total Consumption', 14, y)
  y += 5
  
  if (wSpeed === 0) {
     doc.setFont('helvetica', 'italic')
     doc.text('No Warranted Speed data available for calculation.', 22, y + 2)
     doc.setFont('helvetica', 'normal')
     y += 10
  } else {
     doc.setFont('helvetica', 'normal')
     doc.setFontSize(7)
     // Total = FO + GO combined, matching the "Total Consumption" heading —
     // NOT FO alone. Same backend-sourced a_h/b_h/c_h time-equivalents used
     // for Section B — see cp_calculator.compute_cp_voyage_table.
     const goodTotalConsB = goodTotalFOB + goodTotalGOB
     const totalW    = foW + goW
     const totalMax   = totalW * (1 + tolPct / 100)
     const totalMin   = totalW * (1 - tolPct / 100)
     const d_tot = dFO + dGO
     const e_tot = evCp.eTot
     const f_tot = evCp.fTot

     // D
     let blockY = y
     doc.text('Entire Voyage Consumption using', 22, blockY + 2)
     doc.text('vessel Good Weather Consumption', 22, blockY + 5)
     doc.text('=', 72, blockY + 4)
     doc.text(fmt(distE, 0), 92, blockY + 1.5, { align: 'center' })
     doc.line(78, blockY + 2.5, 106, blockY + 2.5)
     doc.text(fmt(gwSpeedB, 2), 92, blockY + 5.5, { align: 'center' })
     doc.text('x', 112, blockY + 4)
     doc.text(fmt(goodTotalConsB, 2), 128, blockY + 1.5, { align: 'center' })
     doc.line(116, blockY + 2.5, 140, blockY + 2.5)
     doc.text(fmt(goodTimeB, 1), 128, blockY + 5.5, { align: 'center' })
     doc.text(`=  ${fmt(d_tot, 2)} MT`, 145, blockY + 4)
     doc.text("(d')", 175, blockY + 4)

     blockY += 10
     // E — cumulative event-wise sum, see computeEventWiseCp; the old
     // "Total Distance / Warranted Speed x Consumption / 24" single-division
     // layout no longer applies once each event can carry its own CP
     // instruction, so this shows the cumulative result directly instead of
     // a formula whose arithmetic wouldn't match e_tot any more.
     doc.text('Maximum Warranted Consumption', 22, blockY + 2)
     doc.text('for over-consumption (cumulative, event-wise)', 22, blockY + 5)
     doc.text('=', 145, blockY + 4)
     doc.text(`Total (Event Dist / (Event Speed - ${fmt(tolKn, 2)}kn)) x (Event FO+GO + ${fmt(tolPct, 1)}% / 24)`, 22, blockY + 8)
     doc.text(`=  ${fmt(e_tot, 2)} MT  [${evCp.eventCount} events]`, 145, blockY + 4)
     doc.text("(e')", 185, blockY + 4)

     blockY += 12
     // F — same cumulative treatment as E, minus tolerance instead of plus.
     doc.text('Minimum Warranted Consumption', 22, blockY + 2)
     doc.text('for fuel saving (cumulative, event-wise)', 22, blockY + 5)
     doc.text('=', 145, blockY + 4)
     doc.text(`Total (Event Dist / Event Speed) x (Event FO+GO - ${fmt(tolPct, 1)}% / 24)`, 22, blockY + 8)
     doc.text(`=  ${fmt(f_tot, 2)} MT  [${evCp.eventCount} events]`, 145, blockY + 4)
     doc.text("(f')", 185, blockY + 4)

     blockY += 10
     // Computed from THIS page's own (d')/(e')/(f') numbers — not the
     // backend's single-warranty cp.loss figure any more, since that would
     // make the "(d') - (e') = totalLoss" line below literally false once
     // (e')/(f') are event-wise sums instead of one blanket calculation.
     const totalLoss = d_tot > e_tot ? d_tot - e_tot : (d_tot < f_tot ? -(f_tot - d_tot) : 0)
     if (totalLoss > 0) {
        doc.text(`Over-consumption = (d') - (e')  =  ${fmt(d_tot, 2)}  -  ${fmt(e_tot, 2)}  =  ${fmt(totalLoss, 2)} MT`, 40, blockY + 2)
     } else if (totalLoss < 0) {
        doc.text(`Saving = (f') - (d')  =  ${fmt(f_tot, 2)}  -  ${fmt(d_tot, 2)}  =  ${fmt(Math.abs(totalLoss), 2)} MT`, 40, blockY + 2)
     }
     y = blockY + 4

     // Total Consumption Conclusion
     doc.setDrawColor(0)
     doc.setFillColor(totalLoss > 0 ? 255 : (totalLoss < 0 ? 34 : 255), totalLoss > 0 ? 0 : (totalLoss < 0 ? 211 : 255), totalLoss > 0 ? 0 : (totalLoss < 0 ? 153 : 255))
     if (totalLoss === 0) {
        doc.rect(22, y, W - 44, 4)
        doc.setTextColor(0, 0, 0)
     } else {
        doc.rect(22, y, W - 44, 4, 'F')
        doc.setTextColor(255, 255, 255)
     }
     doc.setFont('helvetica', 'bold')
     if (totalLoss > 0) {
        doc.text(`Conclusion: ${totalLoss.toFixed(2)} MT Over-consumption`, W / 2, y + 3, { align: 'center' })
     } else if (totalLoss < 0) {
        doc.text(`Conclusion: ${Math.abs(totalLoss).toFixed(2)} MT Saving`, W / 2, y + 3, { align: 'center' })
     } else {
        doc.text(`Conclusion: No Over-consumption/Saving`, W / 2, y + 3, { align: 'center' })
     }
     doc.setTextColor(0, 0, 0)
     y += 10
  }
}

/** Page 4 — Speed & Weather Analysis Summary */
function buildSummaryTablePage(doc, sum, seriesRows, cpData, routeId, reportDate, voyageNo) {
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
  const goodRows   = seriesRows.filter(isFairWeatherRow)
  const adverseRows = seriesRows.filter(r => !isFairWeatherRow(r))
  const goodDist   = goodRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const goodDur    = goodRows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)
  const advDist    = adverseRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const advDur     = adverseRows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)

  // Equipment x fuel-type FO/DO-GO breakdown (client request 2026-09) —
  // active grade columns determined ONCE across the whole voyage so the
  // Entire/Good/Adverse/Excluded rows below share the same column set.
  const activeGrades = activeGradesForVoyage(seriesRows)
  const { head: fuelHead, flatCols } = buildEquipmentFuelHead(
    [
      { content: 'Periods', rowSpan: 3, styles: { valign: 'middle' } },
      { content: 'Distance (nm)', rowSpan: 3, styles: { valign: 'middle' } },
      { content: 'Time (hrs)', rowSpan: 3, styles: { valign: 'middle' } },
      { content: 'Avg Speed (kts)', rowSpan: 3, styles: { valign: 'middle' } },
    ],
    activeGrades.fo, activeGrades.go,
  )
  const excludedCells = flatCols.map(() => '0.00')

  autoTable(doc, {
    startY: y,
    head: fuelHead,
    body: [
      ['Entire period',       fmt(totalDist,0), fmt(totalDur,2), fmt(totalDur>0?totalDist/totalDur:0), ...equipmentFuelRowCells(seriesRows, activeGrades.fo, activeGrades.go)],
      ['Good weather period', fmt(goodDist,0),  fmt(goodDur,2),  fmt(goodDur>0?goodDist/goodDur:0),    ...equipmentFuelRowCells(goodRows, activeGrades.fo, activeGrades.go)],
      ['Adverse weather period', fmt(advDist,0), fmt(advDur,2), fmt(advDur>0?advDist/advDur:0),        ...equipmentFuelRowCells(adverseRows, activeGrades.fo, activeGrades.go)],
      ['Excluded period',     '0', '0.00', '0.00', ...excludedCells],
    ],
    theme: 'grid',
    headStyles: { fillColor: NAVY, textColor: WHITE, fontSize: 6, fontStyle: 'bold', halign: 'center' },
    bodyStyles: { fontSize: 6, cellPadding: 1.2, halign: 'center' },
    alternateRowStyles: { fillColor: LGRAY },
    columnStyles: { 0: { cellWidth: 32, halign: 'left', fontSize: 6.5 } },
    margin: { left: 14, right: 14 },
  })
}

/** Pages 5+ — Detailed Position & Weather Data */
function buildPositionPages(doc, sum, seriesRows, cpData, vesselName, routeId, reportDate, voyageNo) {
  const ROWS_PER_PAGE = 25
  const W = doc.internal.pageSize.getWidth()

  const allRows = seriesRows
  const goodRows = seriesRows.filter(isFairWeatherRow)
  const adverseRows = seriesRows.filter(r => !isFairWeatherRow(r))

  const calcSum = (rows) => {
    const dist = rows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
    const dur = rows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)
    const speed = dur > 0 ? dist / dur : 0
    return { dist, dur, speed }
  }

  const total = calcSum(allRows)
  const good = calcSum(goodRows)
  const adverse = calcSum(adverseRows)

  // Equipment x fuel-type FO/DO-GO breakdown (client request 2026-09) —
  // same helper/columns as buildSummaryTablePage, applied here too for
  // consistency (this table is a near-duplicate of that one).
  const activeGrades = activeGradesForVoyage(seriesRows)

  const cpW = cpData?.results?.[0]?.warranty || {}
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

      const { head: fuelHead, flatCols } = buildEquipmentFuelHead(
        [
          { content: 'Seg', rowSpan: 3 },
          { content: 'Periods', rowSpan: 3 },
          { content: 'Distance\n(nm)', rowSpan: 3 },
          { content: 'Time\n(hrs)', rowSpan: 3 },
          { content: 'Average Speed\n(kts)', rowSpan: 3 },
        ],
        activeGrades.fo, activeGrades.go,
      )
      const excludedCells = flatCols.map(() => '0.00')

      autoTable(doc, {
        startY: y,
        theme: 'grid',
        styles: { fontSize: 6, textColor: 0, cellPadding: 1, halign: 'center', valign: 'middle', lineColor: [0, 0, 0], lineWidth: 0.1 },
        headStyles: { fillColor: [255, 255, 255], textColor: 0, fontStyle: 'bold' },
        bodyStyles: { fillColor: [255, 255, 255], textColor: 0 },
        head: [
          [
            { content: `${vesselName || '—'}`, colSpan: 3, styles: { halign: 'left', fontStyle: 'bold' } },
            { content: '', colSpan: flatCols.length + 2, styles: { halign: 'left' } }
          ],
          [
            { content: 'Departure', styles: { halign: 'left', fontStyle: 'normal' } },
            { content: sum.From_Port || '—', colSpan: 2, styles: { halign: 'left', fontStyle: 'normal' } },
            { content: startStr, colSpan: flatCols.length + 2, styles: { halign: 'left', fontStyle: 'normal' } }
          ],
          [
            { content: 'Arrival', styles: { halign: 'left', fontStyle: 'normal' } },
            { content: sum.To_Port || '—', colSpan: 2, styles: { halign: 'left', fontStyle: 'normal' } },
            { content: endStr, colSpan: flatCols.length + 2, styles: { halign: 'left', fontStyle: 'normal' } }
          ],
          ...fuelHead,
        ],
        body: [
          ['1', 'Entire period', fmt(total.dist, 0), fmt(total.dur, 2), fmt(total.speed, 2), ...equipmentFuelRowCells(allRows, activeGrades.fo, activeGrades.go)],
          ['1', 'Good weather period', fmt(good.dist, 0), fmt(good.dur, 2), fmt(good.speed, 2), ...equipmentFuelRowCells(goodRows, activeGrades.fo, activeGrades.go)],
          ['1', 'Adverse weather period', fmt(adverse.dist, 0), fmt(adverse.dur, 2), fmt(adverse.speed, 2), ...equipmentFuelRowCells(adverseRows, activeGrades.fo, activeGrades.go)],
          ['', 'Excluded period', '0', '0.00', '0.00', ...excludedCells]
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
        r.Date && typeof r.Date === 'string' && r.Date.length >= 10 ? `${r.Date.substring(8, 10)}/${r.Date.substring(5, 7)}` : '—',
        r.Date && typeof r.Date === 'string' && r.Date.length >= 16 ? r.Date.substring(11, 16) : '—',
        formatCoord(r.lat_degree, r.lat_minutes, r.lat_direction),
        formatCoord(r.lon_degree, r.lon_minutes, r.lon_direction),
        // Per-day CP speed (client request 2026-09): that day's own CP
        // remarks instruction if one exists, otherwise the standing CP
        // warranty — same resolution rule used by eventCpFigures() above.
        fmt(r.cp_instruction?.speed_kn ?? +(cpW.speed_kn || 0), 2),
        fmt(r.SOG_kn),
        fmt(r.Distance_nm, 1),
        windDir(r.True_Wind_Dir_deg),
        bfDisplay(r),
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
          if (isFairWeatherRow(rowData)) {
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

  const cpW = cpData?.results?.[0]?.warranty || {}
  const foW = +(cpW.fo_mtpd || 0)
  const goW = +(cpW.dogo_mtpd || 0)

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

  // ── 2. Summary Table (equipment x fuel-type breakdown, client request
  // 2026-09 — same helper/columns as buildSummaryTablePage/
  // buildPositionPages, applied here too since this is a 3rd near-
  // duplicate of the same table) ──
  const totalDist   = seriesRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const totalDur    = seriesRows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)

  const goodRows    = seriesRows.filter(isFairWeatherRow)
  const advRows     = seriesRows.filter(r => !isFairWeatherRow(r))

  const goodDist    = goodRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const goodDur     = goodRows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)

  const advDist     = advRows.reduce((s, r) => s + (+(r.Distance_nm) || 0), 0)
  const advDur      = advRows.reduce((s, r) => s + (+(r.Duration_h) || 0), 0)

  const activeGrades = activeGradesForVoyage(seriesRows)
  const { head: fuelHead, flatCols } = buildEquipmentFuelHead(
    [
      { content: 'Seg', rowSpan: 3, styles: { valign: 'middle' } },
      { content: 'Periods', rowSpan: 3, styles: { valign: 'middle' } },
      { content: 'Distance\n(nm)', rowSpan: 3, styles: { valign: 'middle' } },
      { content: 'Time\n(hrs)', rowSpan: 3, styles: { valign: 'middle' } },
      { content: 'Average Speed\n(kts)', rowSpan: 3, styles: { valign: 'middle' } },
    ],
    activeGrades.fo, activeGrades.go,
  )
  const excludedCells = flatCols.map(() => '0.00')

  autoTable(doc, {
    startY: y,
    head: fuelHead,
    body: [
      ['1', 'Entire period',       fmt(totalDist,0), fmt(totalDur,2), fmt(totalDur>0?totalDist/totalDur:0), ...equipmentFuelRowCells(seriesRows, activeGrades.fo, activeGrades.go)],
      ['1', 'Good weather period', fmt(goodDist,0),  fmt(goodDur,2),  fmt(goodDur>0?goodDist/goodDur:0),    ...equipmentFuelRowCells(goodRows, activeGrades.fo, activeGrades.go)],
      ['1', 'Adverse weather period', fmt(advDist,0), fmt(advDur,2), fmt(advDur>0?advDist/advDur:0),        ...equipmentFuelRowCells(advRows, activeGrades.fo, activeGrades.go)],
      ['1', 'Excluded period',     '0', '0.00', '0.00', ...excludedCells],
    ],
    theme: 'grid',
    headStyles: { fillColor: [255,255,255], textColor: 0, lineColor: 0, lineWidth: 0.1, fontSize: 5.5, fontStyle: 'normal', halign: 'center' },
    bodyStyles: { fontSize: 5.5, cellPadding: 1.2, halign: 'center', lineColor: 0, lineWidth: 0.1 },
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

  // ── 4. Detailed Position Table (client request 2026-09) ──
  // - POSITIONS (LAT/LON) removed entirely.
  // - "Seg" replaced with the real Event type per row.
  // - ROB (was always static placeholder dashes) removed entirely.
  // - CP FO/DO-GO now per-day: that day's CP remarks instruction if present,
  //   else a fallback — FO falls back to the standing FO warranty (foW,
  //   same rule as everywhere else in this report); DO/GO uses that day's
  //   parsed go_mt_day when the remarks carried one (Format C — LSMGO,
  //   manager feedback 2026-09), otherwise falls back to the standing GO
  //   warranty (goW) — same rule as FO, no longer a hardcoded 0.05.
  // - Daily Consumption restructured to the same equipment x fuel-type
  //   breakdown as the Summary Table above, computed per single day.
  const { head: dailyFuelHead, flatCols: dailyFlatCols } = buildEquipmentFuelHead(
    [
      { content: 'Event type', rowSpan: 3, styles: { valign: 'middle' } },
      { content: 'DATE', rowSpan: 3, styles: { valign: 'middle' } },
      { content: 'TIME\n(UTC)', rowSpan: 3, styles: { valign: 'middle' } },
      { content: 'CP', colSpan: 2, rowSpan: 2, styles: { valign: 'middle' } },
    ],
    activeGrades.fo, activeGrades.go,
    [
      { content: 'RPM', rowSpan: 3, styles: { valign: 'middle' } },
      { content: 'Inside\nECA', rowSpan: 3, styles: { valign: 'middle' } },
    ],
  )
  // The 'CP' leadCol has rowSpan:2 (spans header rows 1-2), so its own
  // FO/DO-GO sub-labels belong in row 3 ONLY — matching the original
  // table's POSITIONS/CP pattern (a rowSpan:2 group cell's own sub-columns
  // are defined in the row directly below where the span ends, not the row
  // in between). Row 2 needs no entry for CP at all.
  dailyFuelHead[2] = ['FO\n(mt)', 'DO/GO\n(mt)', ...dailyFuelHead[2]]

  autoTable(doc, {
    startY: y,
    head: dailyFuelHead,
    body: seriesRows.map((r, idx) => {
      const cpFo = r.cp_instruction?.total_mt_day ?? foW
      const cpGo = r.cp_instruction?.go_mt_day ?? goW
      return [
        r.event_type || '—',
        r.Date && typeof r.Date === 'string' && r.Date.length >= 10 ? `${r.Date.substring(8, 10)}/${r.Date.substring(5, 7)}` : '—',
        r.Date && typeof r.Date === 'string' && r.Date.length >= 16 ? r.Date.substring(11, 16) : '—',
        fmt(cpFo, 2), fmt(cpGo, 2), // CP
        ...equipmentFuelRowCells([r], activeGrades.fo, activeGrades.go), // Daily Cons
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
    },
    didParseCell: function (data) {
      if (data.section === 'body') {
        const rowData = seriesRows[data.row.index]
        if (isFairWeatherRow(rowData)) {
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
 * @returns {Promise<{filename: string, pages: number, dataWarning: string|null}>}
 *   dataWarning is non-null when a genuine fetch failure (network/5xx, not
 *   just "no records") happened during generation — the PDF itself also
 *   shows this on its cover page, but callers should surface it too (e.g.
 *   an alert) since a user watching only the download might miss it.
 */
export async function generateVoyagePdf({ vesselImo, vesselName, voyageNo, voyageNos, source, loadingCond, onProgress }) {
  onProgress?.('Fetching voyage summary…')

  // ── 1. Fetch all data in parallel ────────────────────────────────────────
  // cpDataAll is UNFILTERED by voyageNos/loadingCond — it's the vessel+source's
  // full CP history, used only to give the CP charts a real multi-voyage trend
  // to plot even when this report itself was downloaded for a single voyage.
  // Bug found 2026-09 (client report, AM UMANG voy 82B — distance/time ~2x
  // actual): WNI and MariApps can share the exact literal Voyage_No string
  // for one vessel, and /voyage/summary + /voyage/series used to blend
  // both sources together unfiltered whenever that happened, double-
  // counting every day. Always pass the actually-selected single source
  // now — same 'all' -> undefined mapping already used for CP performance
  // just below, so an explicit "All" selection still blends deliberately.
  const seriesSource = source === 'all' ? undefined : source

  // Distinguish a genuine fetch failure (network drop, 5xx — e.g. the
  // Postgres connection-pool exhaustion found 2026-09 that silently
  // produced an all-zero, structurally-broken-looking report) from a
  // legitimate "no records" response (404 from /voyage/summary when a
  // voyage really has none under the selected source) — only the former
  // should surface a warning; the latter is expected, already-handled
  // behaviour (see the `if (series.length > 0)` gating below).
  const failedFetches = []
  function catchFetch(label, fallback) {
    return (err) => {
      const status = err?.response?.status
      const isRealFailure = !status || status >= 500
      if (isRealFailure) {
        console.error(`[Voyage PDF] ${label} fetch failed:`, err)
        failedFetches.push(label)
      }
      return fallback
    }
  }

  const [sum, series, cpData, cpDataAll] = await Promise.all([
    fetchVoyageSummary(voyageNo, vesselImo, seriesSource).catch(catchFetch('voyage summary', {})),
    fetchVoyageSeries(voyageNo, vesselImo, seriesSource).catch(catchFetch('daily voyage data (charts/tables)', [])),
    fetchCPPerformance(vesselImo, voyageNos, source === 'all' ? undefined : source, loadingCond === 'all' ? undefined : loadingCond).catch(catchFetch('CP performance', null)),
    fetchCPPerformance(vesselImo, undefined, source === 'all' ? undefined : source, undefined).catch(catchFetch('CP performance (trend charts)', null)),
  ])
  const dataWarning = failedFetches.length
    ? `Failed to load: ${failedFetches.join(', ')} — likely a temporary server/database issue. Please regenerate this report.`
    : null

  onProgress?.('Rendering charts & maps...')
  const [pdfAssets, cpCharts] = await Promise.all([
    capturePdfAssets(sum, series, cpData),
    captureCPCharts(cpDataAll, voyageNo),
  ])

  onProgress?.('Building PDF…')

  // ── 2. Prepare metadata ───────────────────────────────────────────────────
  const now       = new Date()
  const reportDate = now.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
  const datestamp  = `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}`
  const paddedVoy  = String(voyageNo).padStart(6, '0')
  const routeId    = `sid${datestamp}_${paddedVoy}`
  const fromPort = sum?.From_Port ? sum.From_Port.trim() : ''
  const toPort = sum?.To_Port ? sum.To_Port.trim() : ''
  
  let routeStr = ''
  if (fromPort && toPort) {
    routeStr = `${fromPort} to ${toPort}`
  } else if (fromPort) {
    routeStr = `From ${fromPort}`
  } else if (toPort) {
    routeStr = `To ${toPort}`
  }

  const voyagePrefix = String(voyageNo).toUpperCase().includes(String(vesselName).toUpperCase()) 
    ? voyageNo 
    : `${vesselName} ${voyageNo}`

  const baseName = routeStr ? `${voyagePrefix} ${routeStr}` : voyagePrefix
  const filename = `${baseName}.pdf`.replace(/[^a-zA-Z0-9 _.-]/g, '_')

  // ── 3. Create jsPDF instance (A4) ────────────────────────────────────────
  const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' })

  // ── 4. Build all pages ────────────────────────────────────────────────────
  // Order per client request 2026-09: Speed and Weather Analysis + Fuel
  // Consumption Analysis moved up right after the cover page; Charter-Party
  // Performance Charts + the Speed/Consumption weather-current chart image
  // moved down to where those used to sit.
  buildCoverPage(doc, sum, cpData, vesselName, voyageNo, routeId, reportDate, series, dataWarning)
  buildSummaryTablePage(doc, sum, series, cpData, routeId, reportDate, voyageNo)

  if (series.length > 0) {
    buildPositionPages(doc, sum, series, cpData, vesselName, routeId, reportDate, voyageNo)
    buildFuelPage(doc, sum, series, cpData, routeId, reportDate, voyageNo, vesselName)
  }

  buildSpeedConsPage(doc, sum, series, cpData, routeId, reportDate, voyageNo)
  buildMethodologyPage1(doc, sum, series, cpData, routeId, reportDate, voyageNo)
  buildCPChartsPage(doc, cpCharts)
  if (pdfAssets?.chartsDataUrl) buildChartsPage(doc, pdfAssets.chartsDataUrl)

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

  return { filename, pages: totalPages, dataWarning }
}

/**
 * CP Performance charts — near the end of the report, after Speed and
 * Consumption Calculation. One combined page holding both: (A) Good-Weather
 * speed & fuel/day vs CP warranty + allowance bands, trended across this
 * vessel's full history for
 * this voyage's own loading condition, and (B) the combined Time/Fuel
 * Loss(-)/Saving(+) diverging bar chart across all of this vessel's voyages,
 * both conditions together (never split by condition — see cp_calculator).
 */
function buildCPChartsPage(doc, cpCharts) {
  if (!cpCharts?.chartsDataUrl) return
  doc.addPage('a4', 'portrait')
  // The charts DOM was 1000x1400 (ratio 1:1.4), same full-bleed pattern as buildChartsPage —
  // the title is rendered inside the captured image itself, so no separate header here.
  doc.addImage(cpCharts.chartsDataUrl, 'JPEG', 0, 0, 210, 297)
}

function buildChartsPage(doc, imgDataUrl) {
  doc.addPage('a4', 'portrait')
  // The charts DOM was 1000x1400 (ratio 1:1.4)
  // A4 portrait is 210 x 297 mm (ratio ~1:1.41)
  doc.addImage(imgDataUrl, 'JPEG', 0, 0, 210, 297)
}
