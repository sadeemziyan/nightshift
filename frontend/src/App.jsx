import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import AlertPanel from './components/AlertPanel'
import FacilityDetail from './components/FacilityDetail'
import Icon from './components/Icon'
import InjectPanel from './components/InjectPanel'
import JobsPage from './components/JobsPage'
import LearningCard from './components/LearningCard'
import Logo from './components/Logo'
import ModelLab from './components/ModelLab'
import NetworkMap from './components/NetworkMap'
import ReplayControls from './components/ReplayControls'
import RiskSlider from './components/RiskSlider'
import * as api from './api'
import { useHashRoute } from './hooks'
import { mock, MOCK_T } from './mock'
import { TONE, buildStatus, fmtClock, fmtTime } from './status'

const STEP_S = 300 // telemetry is one reading every 5 minutes
const NO_PLANS = { forecasts: [], plan: null }
const LEAD_S = 1800 // "Next problem" lands this long before the problem starts

const TABS = [
  ['console', '#/', 'Console'],
  ['lab', '#/lab', 'Model Lab'],
  ['jobs', '#/jobs', 'My Jobs'],
]

function App() {
  const route = useHashRoute()
  const [datasets, setDatasets] = useState([])
  const [datasetId, setDatasetId] = useState('')
  const [network, setNetwork] = useState(null)
  const [snapshot, setSnapshot] = useState({ state: null, alerts: [] })
  const [decision, setDecision] = useState(NO_PLANS) // /forecast rows and /plan, both at time tSnap
  const [planLoading, setPlanLoading] = useState(false)
  const [t, setT] = useState(null) // the replay clock, in seconds, moves smoothly
  const [range, setRange] = useState({ min: 0, max: 0 })
  const [usingMock, setUsingMock] = useState(false)
  const [notice, setNotice] = useState('Connecting to the backend...')
  const [selectedSystemId, setSelectedSystemId] = useState('')
  const [selectedFacilityId, setSelectedFacilityId] = useState('')
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(60)
  const [risk, setRisk] = useState(null)
  const [fresh, setFresh] = useState(() => new Set())
  const [toast, setToast] = useState(null)
  const [simulated, setSimulated] = useState(false)
  const [learning, setLearning] = useState(null)
  const [refresh, setRefresh] = useState(0)
  const [eventTimes, setEventTimes] = useState([])

  const tRef = useRef(null)
  const playingRef = useRef(false)
  const reqRef = useRef(0) // numbers each data request so a slow old answer never overwrites a newer one
  const appliedRef = useRef(0)
  const seenRef = useRef(null) // event ids shown last time, to spot new ones
  const pumpsDownRef = useRef(0)
  const timers = useRef({})

  useEffect(() => {
    tRef.current = t
  }, [t])
  useEffect(() => {
    playingRef.current = playing
  }, [playing])
  useEffect(() => {
    const all = timers.current
    return () => Object.values(all).forEach(clearTimeout)
  }, [])

  const later = useCallback((name, fn, ms) => {
    clearTimeout(timers.current[name])
    timers.current[name] = setTimeout(fn, ms)
  }, [])
  const flash = useCallback(
    (text, tone = 'info', ms = 7000) => {
      setToast({ text, tone })
      later('toast', () => setToast(null), ms)
    },
    [later]
  )

  const fallToMock = useCallback((reason) => {
    setUsingMock(true)
    setPlaying(false)
    setNotice(`${reason} Showing sample data.`)
    setDatasets(mock.datasets.datasets)
    setDatasetId(mock.load.dataset)
    setNetwork(mock.network)
    setSnapshot({ state: mock.state, alerts: mock.alerts.alerts })
    setDecision({ forecasts: mock.forecast.forecasts, plan: mock.plan })
    setSelectedSystemId('S2') // the sample snapshot has its three failed pumps in S2
    setSelectedFacilityId('')
    setRange({ min: MOCK_T, max: MOCK_T })
    setT(MOCK_T)
    setLearning(null)
  }, [])

  const openDataset = useCallback(
    async (id) => {
      setNotice(`Loading ${id}...`)
      setPlaying(false)
      setLearning({ phase: 'learning', dataset: id })
      appliedRef.current = reqRef.current // answers still in flight belong to the old dataset
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
        let times = []
        try {
          const all = await api.getAlerts(info.now_unix, { resolved: true })
          times = [...new Set(all.alerts.map((a) => a.onset_unix))].sort((a, b) => a - b)
        } catch {
          // "Next problem" just stays unavailable
        }
        seenRef.current = null
        pumpsDownRef.current = 0
        setUsingMock(false)
        setDatasetId(id)
        setNetwork(net)
        setSnapshot({ state: null, alerts: [] })
        setDecision(NO_PLANS)
        setSimulated(false)
        setEventTimes(times)
        setSelectedSystemId(net.systems[0]?.id ?? '')
        setSelectedFacilityId('')
        setRange({ min: start, max: info.now_unix })
        setT(info.now_unix)
        setNotice('')
        setLearning({ phase: 'done', models: info.models })
        later('learning', () => setLearning(null), 8000)
      } catch (err) {
        fallToMock(`Backend not reachable (${err.message}).`)
      }
    },
    [fallToMock, later]
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

  // The replay clock: while playing, move time forward once a second.
  useEffect(() => {
    if (!playing) return undefined
    const id = setInterval(() => {
      const next = Math.min((tRef.current ?? 0) + speed, range.max)
      tRef.current = next
      setT(next)
      if (next >= range.max) setPlaying(false)
    }, 1000)
    return () => clearInterval(id)
  }, [playing, speed, range.max])

  // Data is read on the 5-minute grid; the clock above moves between grid points so countdowns tick.
  const tSnap =
    t == null ? null : Math.min(range.max, range.min + Math.floor((t - range.min) / STEP_S) * STEP_S)

  // Whenever the grid time (or the safety level) changes, ask the backend what everything looks like then.
  useEffect(() => {
    if (usingMock || tSnap == null || !network) return undefined
    const id = ++reqRef.current
    const timer = setTimeout(
      async () => {
        const stale = () => id < appliedRef.current
        try {
          const [state, alertsRes] = await Promise.all([api.getState(tSnap), api.getAlerts(tSnap)])
          if (stale()) return
          appliedRef.current = id
          const ongoing = alertsRes.alerts.filter((a) => a.status === 'ongoing')
          const ids = new Set(ongoing.map((a) => a.event_id))
          const downNow = ongoing.filter((a) => a.category === 'pump_failure')
          if (playingRef.current && seenRef.current) {
            const added = ongoing.filter((a) => !seenRef.current.has(a.event_id))
            if (added.length) {
              setFresh(new Set(added.map((a) => a.event_id)))
              later('fresh', () => setFresh(new Set()), 4500)
              const newPumps = added.filter((a) => a.category === 'pump_failure')
              if (newPumps.length && pumpsDownRef.current > 0) {
                flash(`${newPumps[0].asset_id} just failed too. The plan is being recomputed for ${downNow.length} pumps.`, 'bad')
              }
            }
          }
          seenRef.current = ids
          pumpsDownRef.current = downNow.length
          setSnapshot({ state, alerts: alertsRes.alerts })
          setSimulated(!!alertsRes.simulated)
          setNotice('')
          // Countdowns and plans only exist while a pump is down.
          if (downNow.length === 0) {
            setDecision(NO_PLANS)
            return
          }
          setPlanLoading(true)
          try {
            const [forecast, plan] = await Promise.all([api.getForecast(tSnap), api.getPlan(tSnap, risk)])
            if (!stale()) setDecision({ forecasts: forecast.forecasts, plan })
          } catch {
            if (!stale()) setDecision(NO_PLANS)
          } finally {
            setPlanLoading(false)
          }
        } catch (err) {
          if (!stale()) setNotice(`Could not read data at this time: ${err.message}`)
        }
      },
      playingRef.current ? 0 : 200
    )
    return () => clearTimeout(timer)
  }, [tSnap, risk, refresh, usingMock, network, later, flash])

  const status = useMemo(() => buildStatus(network, snapshot.state, snapshot.alerts), [network, snapshot])

  const system = network?.systems.find((s) => s.id === selectedSystemId) ?? network?.systems[0]
  const active = snapshot.alerts.filter((a) => a.status === 'ongoing')

  // The facility shown in detail: the one picked, else the first with a pump failure, else the first.
  const facility =
    system?.facilities.find((f) => f.id === selectedFacilityId) ??
    system?.facilities.find((f) => active.some((a) => a.category === 'pump_failure' && a.facility_id === f.id)) ??
    system?.facilities[0]

  const forecastRow = decision.forecasts.find((f) => f.facility_id === facility?.id)
  const systemPlan = decision.plan?.systems.find((s) => s.system_id === system?.id)

  const pickAlert = (alert) => {
    setSelectedSystemId(alert.system_id)
    setSelectedFacilityId(alert.facility_id)
  }

  const togglePlay = () => {
    if (!playing && t != null && t >= range.max) {
      tRef.current = range.min
      setT(range.min)
    }
    setPlaying((p) => !p)
  }
  const nextProblem = () => {
    const target = eventTimes.find((x) => x - LEAD_S > (t ?? 0) + 1)
    if (target == null) {
      flash('No more problems this week.', 'info', 4000)
      return
    }
    const to = Math.max(range.min, target - LEAD_S)
    tRef.current = to
    setT(to)
    setPlaying(true)
  }
  const jumpLatest = () => {
    setPlaying(false)
    tRef.current = range.max
    setT(range.max)
  }

  // Approve a plan: the backend texts the crew, then we show who was told.
  const approve = async (plan) => {
    const body = { event_id: systemPlan.event_ids[0], plan_rank: plan.rank, t: tSnap }
    if (risk != null) body.risk = risk
    return api.approvePlan(body)
  }

  // Inject a fault on stage. It is marked SIMULATED everywhere and lives only in server memory.
  const inject = async (body) => {
    const res = await api.injectFault(body)
    setSimulated(true)
    setRefresh((n) => n + 1)
    flash(`SIMULATED ${body.category.replace(/_/g, ' ')} on ${body.asset_id} at ${fmtClock(body.onset_unix)}Z. Press play to watch it get caught.`, 'sim', 10000)
    return res
  }

  const isCurrent = (id) => route === id || (id === 'console' && !TABS.some((x) => x[0] === route))
  const tabs = (
    <nav className="flex gap-1 rounded-t-md border border-b-0 border-line bg-surface p-1 pb-0" aria-label="Screens">
      {TABS.map(([id, href, label]) => (
        <a
          key={id}
          href={href}
          aria-current={isCurrent(id) ? 'page' : undefined}
          className={`nav-tab rounded-t-sm px-4 py-2 text-sm font-semibold ${
            isCurrent(id) ? 'bg-data text-ink' : 'text-muted hover:bg-surface-2 hover:text-fg'
          }`}
        >
          {label}
        </a>
      ))}
    </nav>
  )

  const banners = (
    <>
      {notice && (
        <p
          className={`banner mt-4 ${usingMock ? 'border-warn/40 bg-warn/8 text-warn' : 'bg-surface text-muted'}`}
          role="status"
        >
          <span className="led" aria-hidden="true" />
          {notice}
        </p>
      )}
      {simulated && (
        <div className="banner mt-4 border-crit/60 bg-crit/12 text-fg" role="status">
          <span className="tag tag-sim">SIMULATED</span>
          <span>A fault was injected. What you see includes made-up data.</span>
          <button
            type="button"
            onClick={() => openDataset(datasetId)}
            className="btn ml-auto min-h-8 border-crit/70 px-3 text-fg hover:bg-crit/20"
          >
            Back to real data
          </button>
        </div>
      )}
      {toast && (
        <p
          className={`banner pop-in mt-4 font-semibold text-fg ${
            toast.tone === 'bad' || toast.tone === 'sim' ? 'border-crit/60 bg-crit/12' : 'border-data/40 bg-data/8'
          }`}
          role="status"
        >
          {toast.text}
        </p>
      )}
      <LearningCard state={learning} />
    </>
  )

  return (
    <main className="min-h-screen p-4 text-fg sm:p-6 xl:p-8">
      <div className="mx-auto max-w-[120rem]">
        <header className="pipeline flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
          <div className="pb-4">
            <p className="eyebrow text-brand">Operations console</p>
            <div className="mt-2 flex items-center gap-3">
              <Logo size={36} />
              <p className="font-display text-4xl font-semibold tracking-tight">Nightshift</p>
            </div>
            <p className="mt-2 text-muted">Detect problems. Compare plans. Dispatch crews.</p>
          </div>
          <div className="flex flex-col items-start gap-4 sm:items-end">
            <ShiftClock t={t} speed={speed} playing={playing} />
            {tabs}
          </div>
        </header>

        {banners}

        {route === 'jobs' ? (
          <div className="mt-6">
            <JobsPage
              plan={decision.plan}
              alerts={snapshot.alerts}
              t={tSnap ?? 0}
              loading={!network || planLoading || snapshot.state == null}
              usingMock={usingMock}
            />
          </div>
        ) : route === 'lab' ? (
          <div className="mt-6">
            <ModelLab network={network} t={tSnap ?? range.max} usingMock={usingMock} alerts={snapshot.alerts} simulated={simulated} />
          </div>
        ) : (
          <>
            <div className="mt-6 flex flex-wrap items-end gap-x-6 gap-y-4">
              <div>
                <label htmlFor="dataset" className="eyebrow mb-2 block text-muted">
                  Dataset
                </label>
                <select
                  id="dataset"
                  value={datasetId}
                  disabled={usingMock || learning?.phase === 'learning'}
                  onChange={(e) => openDataset(e.target.value)}
                  className="field min-w-44"
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
                  <label htmlFor="system" className="eyebrow mb-2 block text-muted">
                    System
                  </label>
                  <select
                    id="system"
                    value={system?.id ?? ''}
                    onChange={(e) => {
                      setSelectedSystemId(e.target.value)
                      setSelectedFacilityId('')
                    }}
                    className="field min-w-24"
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
                  <label htmlFor="time" className="eyebrow mb-2 block text-muted">
                    Time: <span className="num text-sm font-semibold normal-case tracking-normal text-fg">{fmtTime(tSnap)}</span> |{' '}
                    <span className="num text-sm text-fg">{active.length}</span> active problem
                    {active.length === 1 ? '' : 's'}
                  </label>
                  <input
                    id="time"
                    type="range"
                    min={range.min}
                    max={range.max}
                    step={STEP_S}
                    value={tSnap}
                    disabled={usingMock || range.max <= range.min}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      tRef.current = v
                      setT(v)
                    }}
                    className="slider"
                    style={{ '--fill': `${range.max > range.min ? ((tSnap - range.min) / (range.max - range.min)) * 100 : 100}%` }}
                  />
                </div>
              )}
            </div>

            {t != null && (
              <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_auto]">
                <ReplayControls
                  playing={playing}
                  speed={speed}
                  onToggle={togglePlay}
                  onSpeed={setSpeed}
                  onNext={nextProblem}
                  onJump={jumpLatest}
                  t={t}
                  range={range}
                  disabled={usingMock || range.max <= range.min}
                />
                <InjectPanel
                  facility={facility}
                  t={tSnap}
                  disabled={usingMock}
                  reason={usingMock ? 'Needs the backend. Sample data cannot be changed.' : ''}
                  onInject={inject}
                />
              </div>
            )}

            <ul className="eyebrow mt-6 flex flex-wrap gap-x-6 gap-y-2 text-muted">
              {['ok', 'warn', 'bad', 'off'].map((k) => (
                <li key={k} className="flex items-center gap-2">
                  <span className="led" style={{ color: TONE[k].border }} />
                  {TONE[k].label}
                </li>
              ))}
            </ul>

            {system ? (
              <>
                <div className="mt-4 grid gap-6 xl:grid-cols-[20rem_minmax(0,1fr)] 2xl:grid-cols-[24rem_minmax(0,1fr)]">
                  <AlertPanel
                    alerts={snapshot.alerts}
                    selectedFacilityId={facility?.id}
                    onSelect={pickAlert}
                    fresh={fresh}
                    loading={!usingMock && snapshot.state == null}
                  />
                  <section className="min-w-0">
                    <h2 className="text-xl font-semibold">
                      <span className="num">{system.id}</span> facilities
                    </h2>
                    <NetworkMap system={system} status={status.byAsset} />
                    <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                      {system.facilities.map((f) => {
                        const tone = TONE[status.byFacility[f.id] ?? 'ok']
                        const selected = f.id === facility?.id
                        return (
                          <button
                            type="button"
                            key={f.id}
                            onClick={() => setSelectedFacilityId(f.id)}
                            className={`panel p-4 text-left transition-transform hover:-translate-y-0.5 hover:bg-surface-2 ${
                              selected ? 'ring-2 ring-data ring-offset-2 ring-offset-ink' : ''
                            }`}
                            style={{ borderColor: tone.border, '--tick': tone.border }}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <h3 className="num truncate text-base font-semibold text-data">{f.id}</h3>
                              <span className="tag" style={{ background: tone.bg, color: tone.text }}>
                                <span className="led" />
                                {tone.label}
                              </span>
                            </div>
                            <dl className="mt-4 grid gap-2 text-sm">
                              <div className="flex gap-2">
                                <Icon name="tank" className="mt-0.5 text-faint" />
                                <div>
                                  <dt className="eyebrow text-faint">Tank</dt>
                                  <dd className="num">
                                    {status.byAsset[f.tank.id]?.detail ?? '-'} of {f.tank.capacity_bbl.toLocaleString()}{' '}
                                    {network.meta.units.volume}
                                  </dd>
                                </div>
                              </div>
                              <div className="flex gap-2">
                                <Icon name="pump" className="mt-0.5 text-faint" />
                                <div>
                                  <dt className="eyebrow text-faint">Pump</dt>
                                  <dd className="num">
                                    {f.pump.id}: {status.byAsset[f.pump.id]?.detail ?? '-'}
                                  </dd>
                                </div>
                              </div>
                              <div className="flex gap-2">
                                <Icon name="drop" className="mt-0.5 text-faint" />
                                <div>
                                  <dt className="eyebrow text-faint">Wells</dt>
                                  <dd className="num">
                                    {f.wells.length}
                                    {' ('}
                                    {f.wells.filter((w) => status.byAsset[w.id]?.tone === 'off').length} shut in)
                                  </dd>
                                </div>
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
                    snapT={tSnap}
                    forecastRow={forecastRow}
                    systemPlan={systemPlan}
                    planLoading={planLoading}
                    usingMock={usingMock}
                    onApprove={approve}
                    approveDisabled={usingMock || planLoading}
                    approveReason={usingMock ? 'Sample data: connect the backend to send messages.' : planLoading ? 'Plan is updating.' : ''}
                    planHeader={
                      <div className="mb-4">
                        <RiskSlider risk={risk} onChange={setRisk} disabled={usingMock} />
                      </div>
                    }
                  />
                )}
              </>
            ) : (
              <div className="mt-8 grid gap-6 xl:grid-cols-[24rem_1fr]" aria-label="Loading">
                <div className="skeleton h-96" />
                <div className="skeleton h-96" />
              </div>
            )}
          </>
        )}
        <footer className="num mt-12 border-t border-line pt-4 text-xs text-faint">Nightshift - HackUTD 2026</footer>
      </div>
    </main>
  )
}

// Slim strip in the header: replay clock, speed, and a red dot while the replay runs.
function ShiftClock({ t, speed, playing }) {
  if (t == null) return null
  return (
    <div className="num flex items-center gap-4 text-sm text-muted">
      <span className="flex items-center gap-2">
        <span className={`led ${playing ? 'led-live text-crit' : 'led-hollow text-faint'}`} />
        <span className="text-fg">{fmtTime(t)}</span>
      </span>
      <span className="h-4 w-px bg-line-strong" aria-hidden="true" />
      <span>{speed}x</span>
    </div>
  )
}

export default App
