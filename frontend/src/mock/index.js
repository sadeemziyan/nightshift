// Mock API responses for building screens before the backend is wired in.
// Every file is a snapshot of the real endpoint at MOCK_T (2026-10-08T10:05:00Z, dataset full_week),
// when three pumps in S2 are down at once, one pipeline leaks and two pumps are wearing out.
// See README.md in this folder. Field names come from docs/api.md.
import datasets from './datasets.json'
import load from './load.json'
import network from './network.json'
import state from './state.json'
import alerts from './alerts.json'
import forecast from './forecast.json'
import plan from './plan.json'
import timeseries from './timeseries.json'
import approve from './approve.json'
import modelStatus from './model_status.json'
import modelStatusFitting from './model_status_fitting.json'
import modelStatusReady from './model_status_ready.json'
import modelBaseline from './model_baseline.json'
import modelEval from './model_eval.json'
import simulateInject from './simulate_inject.json'

export const MOCK_T = 1791453900

export const mock = {
  datasets, // GET  /datasets
  load, // POST /load?dataset=full_week
  network, // GET  /network
  state, // GET  /state?t=MOCK_T
  alerts, // GET  /alerts?t=MOCK_T
  forecast, // GET  /forecast?t=MOCK_T
  plan, // GET  /plan?t=MOCK_T
  timeseries, // GET  /timeseries?id=S2_TANK_B&metric=level_pct&from=...&to=MOCK_T
  approve, // POST /approve
  modelStatus, // GET  /model/status (real: rules-only)
  modelStatusFitting, // placeholder: models fitting
  modelStatusReady, // placeholder: models ready
  modelBaseline, // GET  /model/baseline?id=S2_PUMP_B&metric=flow_bpd (learned-normal band)
  modelEval, // GET  /model/eval (PLACEHOLDER numbers)
  simulateInject, // POST /simulate/inject
}

export default mock
