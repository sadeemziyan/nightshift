import { useCallback, useEffect, useMemo, useState } from 'react'
import NetworkMap from './components/NetworkMap'
import SensorChart from './components/SensorChart'
import * as api from './api'
import { mock, MOCK_T } from './mock'
import { TONE, buildStatus, fmtTime } from './status'

const STEP_S = 300 // telemetry is one reading every 5 minutes

function App() {
  const [datasets, setDatasets] = useState([])
  const [datasetId, setDatasetId] = useState('')
  const [network, setNetwork] = useState(null)
  const [snapshot, setSnapshot] = useState({ state: null, alerts: [] })
  const [t, setT] = useState(null)
  const [range, setRange] = useState({ min: 0, max: 0 })
  const [usingMock, setUsingMock] = useState(false)
  const [notice, setNotice] = useState('Connecting to the backend...')
  const [selectedSystemId, setSelectedSystemId] = useState('')
  const [chartFacilityId, setChartFacilityId] = useState('')

  const fallToMock = useCallback((reason) => {
    setUsingMock(true)
    setNotice(`${reason} Showing sample data.`)
    setDatasets(mock.datasets.datasets)
    setDatasetId(mock.load.dataset)
    setNetwork(mock.network)
    setSnapshot({ state: mock.state, alerts: mock.alerts.alerts })
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
        setSelectedSystemId(net.systems[0]?.id ?? '')
        setChartFacilityId('')
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
  const chartFacility =
    system?.facilities.find((f) => f.id === chartFacilityId) ??
    system?.facilities.find((f) =>
      active.some((a) => a.category === 'pump_failure' && a.facility_id === f.id)
    ) ??
    system?.facilities[0]

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
            onChange={(e) => openDataset(e.target.value)}
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
                setChartFacilityId('')
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
          <section className="mt-6">
            <h2 className="text-xl font-semibold">{system.id} facilities</h2>
            <NetworkMap system={system} status={status.byAsset} />
            <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {system.facilities.map((facility) => {
                const tone = TONE[status.byFacility[facility.id] ?? 'ok']
                const alerts = active.filter((a) => a.facility_id === facility.id)
                return (
                  <article
                    key={facility.id}
                    className="rounded-xl border-2 bg-slate-900 p-5"
                    style={{ borderColor: tone.border }}
                  >
                    <div className="flex items-center justify-between">
                      <h3 className="font-semibold text-cyan-400">{facility.id}</h3>
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
                          {status.byAsset[facility.tank.id]?.detail ?? '-'} of{' '}
                          {facility.tank.capacity_bbl.toLocaleString()} {network.meta.units.volume}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-slate-400">Pump</dt>
                        <dd>
                          {facility.pump.id}: {status.byAsset[facility.pump.id]?.detail ?? '-'}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-slate-400">Wells</dt>
                        <dd>
                          {facility.wells.length}
                          {' ('}
                          {facility.wells.filter((w) => status.byAsset[w.id]?.tone === 'off').length} shut in)
                        </dd>
                      </div>
                    </dl>
                    {alerts.map((a) => (
                      <p key={a.event_id} className="mt-3 rounded bg-slate-800 px-3 py-2 text-xs text-slate-200">
                        {a.category.replace('_', ' ')}: {a.evidence?.[0] ?? a.asset_id}
                      </p>
                    ))}
                  </article>
                )
              })}
            </div>
          </section>

          {chartFacility && (
            <section className="mt-8">
              <div className="mb-3 flex flex-wrap items-center gap-4">
                <h2 className="text-xl font-semibold">Pump behavior</h2>
                <select
                  aria-label="Facility for the chart"
                  value={chartFacility.id}
                  onChange={(e) => setChartFacilityId(e.target.value)}
                  className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
                >
                  {system.facilities.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.pump.id}
                    </option>
                  ))}
                </select>
              </div>
              <SensorChart assetId={chartFacility.pump.id} t={t} usingMock={usingMock} />
            </section>
          )}
        </>
      ) : (
        <p className="mt-8 text-slate-400">No systems available.</p>
      )}
    </main>
  )
}

export default App
