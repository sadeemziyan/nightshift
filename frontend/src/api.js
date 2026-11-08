// Calls to the Nightshift backend (docs/api.md). Base URL: VITE_API_URL, else http://localhost:8000.
export const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function request(path, options) {
  const res = await fetch(API_BASE + path, options)
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.error ?? `HTTP ${res.status}`)
  return body
}

export const getDatasets = () => request('/datasets')
export const loadDataset = (id) =>
  request(`/load?dataset=${encodeURIComponent(id)}`, { method: 'POST' })
export const getNetwork = () => request('/network')
export const getState = (t) => request(`/state?t=${t}`)
export const getAlerts = (t) => request(`/alerts?t=${t}`)
export const getTimeseries = (id, metric, { from, to }) =>
  request(`/timeseries?id=${encodeURIComponent(id)}&metric=${metric}&from=${from}&to=${to}`)
export const getBaseline = (id, metric, t, hours = 6) =>
  request(`/model/baseline?id=${encodeURIComponent(id)}&metric=${metric}&t=${t}&hours=${hours}`)
