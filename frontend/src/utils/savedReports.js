const LS_KEY = 'vp_saved_reports'

/** Read all saved reports from localStorage */
export function getSavedReports() {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY) ?? '[]')
  } catch {
    return []
  }
}

/**
 * Save a new report.
 * @param {{ name, expression, vesselImo, fromDate, toDate }} report
 */
export function saveReport(report) {
  const all = getSavedReports()
  const entry = {
    ...report,
    id:          Date.now(),
    createdAt:   new Date().toISOString(),
    lastRunAt:   null,
    lastCount:   null,
  }
  all.unshift(entry)
  localStorage.setItem(LS_KEY, JSON.stringify(all))
  return all
}

/** Delete a report by id */
export function deleteReport(id) {
  const all = getSavedReports().filter(r => r.id !== id)
  localStorage.setItem(LS_KEY, JSON.stringify(all))
  return all
}

/** Rename a saved report */
export function renameReport(id, newName) {
  const all = getSavedReports().map(r =>
    r.id === id ? { ...r, name: newName.trim() } : r
  )
  localStorage.setItem(LS_KEY, JSON.stringify(all))
  return all
}

/** Update lastRunAt and lastCount after running a report */
export function markReportRun(id, count) {
  const all = getSavedReports().map(r =>
    r.id === id
      ? { ...r, lastRunAt: new Date().toISOString(), lastCount: count }
      : r
  )
  localStorage.setItem(LS_KEY, JSON.stringify(all))
  return all
}
