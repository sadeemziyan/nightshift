import { useCallback, useEffect, useMemo, useState } from 'react'
import AlertPanel from './components/AlertPanel'
import FacilityDetail from './components/FacilityDetail'
import NetworkMap from './components/NetworkMap'
import * as api from './api'
import { mock, MOCK_T } from './mock'
import { TONE, buildStatus, fmtTime } from './status'

const STEP_S = 300 // telemetry is one reading every 5 minutes
const NO_PLANS = { forecasts: [], plan: null }

function App() {
  const [datasets, setDatasets] = useState([])
  const [datasetId, setDatasetId] = useState('')
  const [network, setNetwork] = useState(null)
  const [snapshot, setSnapshot] = useState({ state: null, alerts: [] })
  const [decision, setDecision] = useState(NO_PLANS) // /forecast rows and /plan, both at time t
  const [planLoading, setPlanLoading] = useState(false)
  const [t, setT] = useState(null)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(60)
  const [range, setRange] = useState({ min: 0, max: 0 })
  const [usingMock, setUsingMock] = useState(false)
  const [notice, setNotice] = useState('Connecting to the backend...')
  const [selectedSystemId, setSelectedSystemId] = useState('')
  const [selectedFacilityId, setSelectedFacilityId] = useState('')

  const fallToMock = useCallback((reason) => {
    setUsingMock(true)
    setNotice(`${reason} Showing sample data.`)
    setDatasets(mock.datasets.datasets)
    setDatasetId(mock.load.dataset)
    setNetwork(mock.network)
    setSnapshot({ state: mock.state, alerts: mock.alerts.alerts })
    setDecision({ forecasts: mock.forecast.forecasts, plan: mock.plan })
    setRange({ min: MOCK_T, max: MOCK_T })
    setT(MOCK_T)
  }, [])

  const openDataset = useCallback(
    async (id) => {
      setNotice(`Loading ${id}...`)
      try {
        const info = await api.loadDataset(id)
        const net = await api.getNetwork()
        let start = info.now_unix - 7 * 86400
        try {
          const firstTank = net.systems[0].facilities[0].tank.id
          const series = await api.getTimeseries(firstTank, 'level_pct', { from: 0, to: info.now_unix })
          if (series.points.length) start = series.points[0][0]
        } catch {
          // keep the one-week default
        }
        setUsingMock(false)
        setDatasetId(id)
        setNetwork(net)
        setSnapshot({ state: null, alerts: [] })
        setDecision(NO_PLANS)
        setSelectedSystemId(net.systems[0]?.id ?? '')
        setSelectedFacilityId('')
        setRange({ min: start, max: info.now_unix })
        setT(info.now_unix)
        setNotice('')
      } catch (err) {
        fallToMock(`Backend not reachable (${err.message}).`)
      }
    },
    [fallToMock]
  )

  // On first load: list the dataset folders, then open full_week (or the first one found).
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const { datasets: list } = await api.getDatasets()
        if (cancelled) return
        setDatasets(list)
        const first = list.find((d) => d.id === 'full_week') ?? list[0]
        if (!first) throw new Error('no dataset folders found')
        await openDataset(first.id)
      } catch (err) {
        if (!cancelled) fallToMock(`Backend not reachable (${err.message}).`)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [openDataset, fallToMock])

  // Whenever the time moves, ask the backend what every tank, pump and alert looks like then.
  useEffect(() => {
    if (usingMock || t == null || !network) return undefined
    let cancelled = false
    const timer = setTimeout(async () => {
      try {
        const [state, alertsRes] = await Promise.all([api.getState(t), api.getAlerts(t)])
        if (cancelled) return
        setSnapshot({ state, alerts: alertsRes.alerts })
        setNotice('')
        // Countdowns and plans only exist while a pump is down.
        const pumpDown = alertsRes.alerts.some((a) => a.category === 'pump_failure' && a.status === 'ongoing')
        if (!pumpDown) {
          setDecision(NO_PLANS)
          return
        }
        setPlanLoading(true)
        try {
          const [forecast, plan] = await Promise.all([api.getForecast(t), api.getPlan(t)])
          if (!cancelled) setDecision({ forecasts: forecast.forecasts, plan })
        } catch {
          if (!cancelled) setDecision(NO_PLANS)
        } finally {
          if (!cancelled) setPlanLoading(false)
        }
      } catch (err) {
        if (!cancelled) setNotice(`Could not read data at this time: ${err.message}`)
      }
    }, 200)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [t, usingMock, network])

  const status = useMemo(
    () => buildStatus(network, snapshot.state, snapshot.alerts),
    [network, snapshot]
  )

  const system = network?.systems.find((s) => s.id === selectedSystemId) ?? network?.systems[0]
  const active = snapshot.alerts.filter((a) => a.status === 'ongoing')

  // The facility shown in detail: the one picked, else the first with a pump failure, else the first.
  const facility =
    system?.facilities.find((f) => f.id === selectedFacilityId) ??
    system?.facilities.find((f) =>
      active.some((a) => a.category === 'pump_failure' && a.facility_id === f.id)
    ) ??
    system?.facilities[0]

  const forecastRow = decision.forecasts.find((f) => f.facility_id === facility?.id)
  const systemPlan = decision.plan?.systems.find((s) => s.system_id === system?.id)

  const pickAlert = (alert) => {
    setSelectedSystemId(alert.system_id)
    setSelectedFacilityId(alert.facility_id)
  }

  useEffect(() => {
    if (!playing || usingMock || t == null || t >= range.max) {
      return
    }

    const timer = setTimeout(() => {
      setT((current) => Math.min(current + speed, range.max))
    }, 1000)

    return () => clearTimeout(timer)
  }, [playing, speed, usingMock, t, range.max])

  return (
    <main className="min-h-screen bg-slate-950 p-8 text-slate-100">
      <p className="text-sm font-semibold uppercase tracking-widest text-cyan-400">Operations console</p>
      <h1 className="mt-2 text-4xl font-bold">Nightshift</h1>
      <p className="mt-3 text-slate-400">Detect problems. Compare plans. Dispatch crews.</p>

      {notice && (
        <p
          className={`mt-4 rounded-lg border px-4 py-2 text-sm ${
            usingMock
              ? 'border-amber-500/50 bg-amber-500/10 text-amber-300'
              : 'border-slate-700 bg-slate-900 text-slate-300'
          }`}
        >
          {notice}
        </p>
      )}

      <div className="mt-8 flex flex-wrap items-end gap-6">
        <div>
          <label htmlFor="dataset" className="mb-2 block text-sm text-slate-400">
            Dataset
          </label>
          <select
            id="dataset"
            value={datasetId}
            disabled={usingMock}
            onChange={(e) => {
              setPlaying(false)
              setT(Number(e.target.value))
            }}
            className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-3"
          >
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.id}
              </option>
            ))}
          </select>
        </div>

        {network && (
          <div>
            <label htmlFor="system" className="mb-2 block text-sm text-slate-400">
              System
            </label>
            <select
              id="system"
              value={system?.id ?? ''}
              onChange={(e) => {
                setSelectedSystemId(e.target.value)
                setSelectedFacilityId('')
              }}
              className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-3"
            >
              {network.systems.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.id}
                </option>
              ))}
            </select>
          </div>
        )}

        {t != null && (
          <div className="min-w-72 flex-1">
            <label htmlFor="time" className="mb-2 block text-sm text-slate-400">
              Time: <span className="font-semibold text-slate-100">{fmtTime(t)}</span>
              {' '}| {active.length} active problem{active.length === 1 ? '' : 's'}
            </label>
            <input
              id="time"
              type="range"
              min={range.min}
              max={range.max}
              step={STEP_S}
              value={t}
              disabled={usingMock || range.max <= range.min}
              onChange={(e) => setT(Number(e.target.value))}
              className="w-full accent-cyan-400"
            />
          </div>
        )}
      </div>
      
      <div className="mt-4 flex items-center gap-3">
    <button
      type="button"
      disabled={usingMock || t == null || range.max <= range.min}
      onClick={() => {
        if (t >= range.max) {
          setT(range.min)
          setPlaying(true)
        } else {
          setPlaying((current) => !current)
        }
      }}
      className="rounded-lg bg-cyan-400 px-4 py-2 font-semibold text-slate-950 disabled:opacity-40"
    >
      {playing && t < range.max ? 'Pause' : 'Play'}
    </button>

    <select
      aria-label="Replay speed"
      value={speed}
      onChange={(event) => setSpeed(Number(event.target.value))}
      className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2"
    >
      <option value={1}>1×</option>
      <option value={10}>10×</option>
      <option value={60}>60×</option>
    </select>
  </div>

      <ul className="mt-6 flex flex-wrap gap-4 text-sm text-slate-300">
        {['ok', 'warn', 'bad', 'off'].map((k) => (
          <li key={k} className="flex items-center gap-2">
            <span className="inline-block h-3 w-3 rounded-full" style={{ background: TONE[k].border }} />
            {TONE[k].label}
          </li>
        ))}
      </ul>

      {system ? (
        <>
          <div className="mt-6 grid gap-6 xl:grid-cols-[24rem_1fr]">
            <AlertPanel
              alerts={snapshot.alerts}
              selectedFacilityId={facility?.id}
              onSelect={pickAlert}
            />
            <section>
              <h2 className="text-xl font-semibold">{system.id} facilities</h2>
              <NetworkMap system={system} status={status.byAsset} />
              <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {system.facilities.map((f) => {
                  const tone = TONE[status.byFacility[f.id] ?? 'ok']
                  return (
                    <button
                      type="button"
                      key={f.id}
                      onClick={() => setSelectedFacilityId(f.id)}
                      className={`rounded-xl border-2 bg-slate-900 p-5 text-left hover:bg-slate-800 ${
                        f.id === facility?.id ? 'ring-2 ring-cyan-400' : ''
                      }`}
                      style={{ borderColor: tone.border }}
                    >
                      <div className="flex items-center justify-between">
                        <h3 className="font-semibold text-cyan-400">{f.id}</h3>
                        <span
                          className="rounded px-2 py-0.5 text-xs font-semibold"
                          style={{ background: tone.bg, color: tone.text }}
                        >
                          {tone.label}
                        </span>
                      </div>
                      <dl className="mt-4 space-y-2 text-sm">
                        <div>
                          <dt className="text-slate-400">Tank</dt>
                          <dd>
                            {status.byAsset[f.tank.id]?.detail ?? '-'} of{' '}
                            {f.tank.capacity_bbl.toLocaleString()} {network.meta.units.volume}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-slate-400">Pump</dt>
                          <dd>
                            {f.pump.id}: {status.byAsset[f.pump.id]?.detail ?? '-'}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-slate-400">Wells</dt>
                          <dd>
                            {f.wells.length}
                            {' ('}
                            {f.wells.filter((w) => status.byAsset[w.id]?.tone === 'off').length} shut in)
                          </dd>
                        </div>
                      </dl>
                    </button>
                  )
                })}
              </div>
            </section>
          </div>

          {facility && (
            <FacilityDetail
              facility={facility}
              network={network}
              t={t}
              forecastRow={forecastRow}
              systemPlan={systemPlan}
              planLoading={planLoading}
              usingMock={usingMock}
            />
          )}
        </>
      ) : (
        <p className="mt-8 text-slate-400">No systems available.</p>
      )}
    </main>
  )
}

export default App
