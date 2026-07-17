import axios from 'axios'

// --- LOCAL (original hardcoded dev URL — uncomment to use against a local backend) ---
const api = axios.create({ baseURL: 'http://127.0.0.1:8000/api/v1' })
// --- VM / PRODUCTION: relative path (same origin via nginx); override with VITE_API_BASE_URL ---
// const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1' })

// ── Auth token interceptor ────────────────────────────────────────────
// Automatically attaches the JWT token (stored in localStorage) to every request.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('vp_auth_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export async function fetchVessels() {
  const { data } = await api.get('/vessels')
  return Array.isArray(data) ? data : []
}

export async function addVessel(imoNumber, vesselName) {
  const { data } = await api.post('/vessels', { imo_number: imoNumber, vessel_name: vesselName })
  return data
}

// Toggle which pipelines include a vessel. payload: { wni_enabled?, mari_enabled? }
export async function updateVesselSources(imo, payload) {
  const { data } = await api.patch(`/vessels/${imo}/sources`, payload)
  return data
}

export async function fetchVoyages(vesselImo, sourceId, loadingCond) {
  const params = { vessel_imo: vesselImo }
  if (sourceId && sourceId !== 'all') params.source_id = sourceId
  if (loadingCond && loadingCond !== 'all') params.loading_cond = loadingCond
  const { data } = await api.get('/voyages', { params })
  return Array.isArray(data) ? data : []
}

export async function queryAnalysis(filters) {
  const { data } = await api.post('/query', filters)
  return data
}

export async function fetchVesselReport(year, shipGroup) {
  const params = {}
  if (year)                            params.year       = year
  if (shipGroup && shipGroup !== 'All') params.ship_group = shipGroup
  const { data } = await api.get('/vessel-report', { params })
  return data
}

export async function fetchShipGroups() {
  const { data } = await api.get('/vessel-report/groups')
  return data
}

export async function runScan(payload) {
  const { data } = await api.post('/scan/run', payload)
  return data
}

export async function fetchExpandedColumns(source) {
  const { data } = await api.get('/expanded/columns', { params: { source } })
  return Array.isArray(data) ? data : []
}

export async function queryExpandedData(source, filters) {
  const endpoint = source === 'mari_apps' ? '/expanded/mariapps' : '/expanded/wni'
  const params = {}
  if (filters.vessel_imo)    params.vessel_imo   = filters.vessel_imo
  if (filters.fromDate)      params.from_date    = filters.fromDate
  if (filters.toDate)        params.to_date      = filters.toDate
  // Multi-voyage: send comma-separated; fall back to single voyageNo
  if (Array.isArray(filters.voyageNos) && filters.voyageNos.length)
                             params.voyage_no    = filters.voyageNos.join(',')
  else if (filters.voyageNo) params.voyage_no    = filters.voyageNo
  if (filters.loadingCond && filters.loadingCond !== 'all')
                             params.loading_cond = filters.loadingCond
  const { data } = await api.get(endpoint, { params })
  return Array.isArray(data) ? data : []
}

export async function toggleExpandedColumn(colId, isActive) {
  const { data } = await api.patch(`/expanded/columns/${colId}`, { is_active: isActive })
  return data
}

// Persist a user-defined column order (shared by all users) for a source.
// order = array of db_column names in the desired order.
export async function reorderColumns(source, order) {
  const { data } = await api.put('/expanded/columns/reorder', { source, order })
  return data
}

// Revert a source's column order back to the default.
export async function resetColumnOrder(source) {
  const { data } = await api.delete('/expanded/columns/reorder', { params: { source } })
  return data
}

// ── Data sync status (read-only) ───────────────────────────────────────────────
export async function fetchSyncStatus(vesselImo) {
  const params = {}
  if (vesselImo) params.vessel_imo = vesselImo
  const { data } = await api.get('/sync/status', { params })
  return Array.isArray(data?.vessels) ? data : { vessels: [] }
}

// ── MDM / Vessel Design Data ──────────────────────────────────────────────────
export async function fetchDesignData(imo) {
  const { data } = await api.get(`/vessels/${imo}/design-data`)
  return data
}

export async function saveDesignData(imo, payload) {
  const { data } = await api.post(`/vessels/${imo}/design-data`, payload)
  return data
}

export async function patchDesignData(imo, payload) {
  const { data } = await api.patch(`/vessels/${imo}/design-data`, payload)
  return data
}

export async function fetchSpeedPowerData(imo, loadingCondition = 'all') {
  const { data } = await api.get(`/vessels/${imo}/speed-power-data`, {
    params: { loading_condition: loadingCondition },
  })
  return data
}

// ── ISO 19030 ─────────────────────────────────────────────────────────────────
export async function fetchISOConfig(imo) {
  const { data } = await api.get(`/iso19030/${imo}/config`)
  return data
}
export async function saveISOConfig(imo, payload) {
  const { data } = await api.post(`/iso19030/${imo}/config`, payload)
  return data
}
export async function fetchBaselineCurves(imo) {
  const { data } = await api.get(`/iso19030/${imo}/baseline-curves`)
  return data
}
export async function saveBaselineCurve(imo, payload) {
  const { data } = await api.post(`/iso19030/${imo}/baseline-curves`, payload)
  return data
}
export async function fetchMaintenanceEvents(imo) {
  const { data } = await api.get(`/iso19030/${imo}/events`)
  return data
}
export async function addMaintenanceEvent(imo, payload) {
  const { data } = await api.post(`/iso19030/${imo}/events`, payload)
  return data
}
export async function deleteMaintenanceEvent(imo, eventId) {
  const { data } = await api.delete(`/iso19030/${imo}/events/${eventId}`)
  return data
}
export async function fetchISOKPIs(imo, dataSource = 'mariapps') {
  const { data } = await api.get(`/iso19030/${imo}/kpis`, { params: { data_source: dataSource } })
  return data
}
export async function fetchISOSpeedLoss(imo, loadingCondition = 'all', baseline = 'B2', dataSource = 'mariapps') {
  const { data } = await api.get(`/iso19030/${imo}/speed-loss`, {
    params: { loading_condition: loadingCondition, baseline, data_source: dataSource }
  })
  return data
}
export async function runISO19030(imo, dataSource = 'mariapps') {
  const { data } = await api.post(`/iso19030/${imo}/run`, null, { params: { data_source: dataSource } })
  return data
}

export async function fetchSpeedPowerISO(imo, loadingCondition = 'all') {
  const { data } = await api.get(`/iso19030/${imo}/speed-power-iso`, {
    params: { loading_condition: loadingCondition },
  })
  return data
}

// ── Charter-Party (CP) performance config ───────────────────────────────────────
// Returns { vessel_imo, configs: { Laden: {...}, Ballast: {...} }, _empty }
export async function fetchCPConfig(imo) {
  const { data } = await api.get(`/cp/${imo}/config`)
  return data
}
// payload must include loading_cond ('Laden' | 'Ballast') plus warranty fields
export async function saveCPConfig(imo, payload) {
  const { data } = await api.post(`/cp/${imo}/config`, payload)
  return data
}

// Per-voyage CP performance (all-weather vs fair-weather, compliance, time, fuel).
// voyages: array of Voyage_No; source: 'wni' | 'mari_apps' | undefined (both)
export async function fetchCPPerformance(imo, voyages, source, loadingCond) {
  const params = {}
  if (Array.isArray(voyages) && voyages.length) params.voyages = voyages.join(',')
  if (source && source !== 'all') params.source = source
  if (loadingCond && loadingCond !== 'all') params.loading_cond = loadingCond
  const { data } = await api.get(`/cp/${imo}/performance`, { params })
  return data
}

// ── Auth API ─────────────────────────────────────────────────────────────

export async function loginUser(username, password) {
  const { data } = await api.post('/auth/login', { username, password })
  return data   // { access_token, role, username, user_id }
}

export async function fetchCurrentUser() {
  const { data } = await api.get('/auth/me')
  return data
}

export async function fetchUsers() {
  const { data } = await api.get('/auth/users')
  return Array.isArray(data) ? data : []
}

export async function createUser(payload) {
  const { data } = await api.post('/auth/users', payload)
  return data
}

export async function updateUser(userId, payload) {
  const { data } = await api.patch(`/auth/users/${userId}`, payload)
  return data
}

export async function deleteUser(userId) {
  await api.delete(`/auth/users/${userId}`)
}

// ── Column Preferences ───────────────────────────────────────────────────────

export async function fetchUserColumnPrefs(source, vesselImo = null) {
  const params = { source }
  if (vesselImo) params.vessel_imo = vesselImo
  const { data } = await api.get('/column-prefs', { params })
  return data // returns { visible: [...], order: [...] } or {}
}

export async function saveUserColumnPrefs(source, vesselImo = null, columnPrefs) {
  const payload = { source, column_prefs: columnPrefs }
  if (vesselImo) payload.vessel_imo = vesselImo
  const { data } = await api.put('/column-prefs', payload)
  return data
}

export async function fetchVesselColumnDefaults(source, vesselImo) {
  const { data } = await api.get('/vessel-column-defaults', { params: { source, vessel_imo: vesselImo } })
  return data
}

export async function saveVesselColumnDefaults(source, vesselImo, columnPrefs) {
  const payload = { source, vessel_imo: vesselImo, column_prefs: columnPrefs }
  const { data } = await api.put('/vessel-column-defaults', payload)
  return data
}
