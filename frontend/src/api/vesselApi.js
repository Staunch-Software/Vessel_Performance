import axios from 'axios'

// --- LOCAL (original hardcoded dev URL — uncomment to use against a local backend) ---
// const api = axios.create({ baseURL: 'http://localhost:8000/api/v1' })
// --- VM / PRODUCTION: relative path (same origin via nginx); override with VITE_API_BASE_URL ---
const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1' })

export async function fetchVessels() {
  const { data } = await api.get('/vessels')
  return data
}

export async function addVessel(imoNumber, vesselName) {
  const { data } = await api.post('/vessels', { imo_number: imoNumber, vessel_name: vesselName })
  return data
}

export async function fetchVoyages(vesselImo, sourceId) {
  const params = { vessel_imo: vesselImo }
  if (sourceId && sourceId !== 'all') params.source_id = sourceId
  const { data } = await api.get('/voyages', { params })
  return data
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
  return data
}

export async function queryExpandedData(source, filters) {
  const endpoint = source === 'mari_apps' ? '/expanded/mariapps' : '/expanded/wni'
  const params = {}
  if (filters.vessel_imo)    params.vessel_imo   = filters.vessel_imo
  if (filters.fromDate)      params.from_date    = filters.fromDate
  if (filters.toDate)        params.to_date      = filters.toDate
  if (filters.voyageNo)      params.voyage_no    = filters.voyageNo
  if (filters.loadingCond && filters.loadingCond !== 'all')
                             params.loading_cond = filters.loadingCond
  const { data } = await api.get(endpoint, { params })
  return data
}

export async function toggleExpandedColumn(colId, isActive) {
  const { data } = await api.patch(`/expanded/columns/${colId}`, { is_active: isActive })
  return data
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
