import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from 'recharts'
import * as api from '../api'
import { mock } from '../mock'
import { useBaseline } from '../hooks'
import { BandChart, ScoreChart } from './BaselineCharts'
import Icon from './Icon'
import { CATEGORY } from '../status'
import { AXIS, C, GRID, TOOLTIP } from '../theme'
const MODELS = [
  ['M1', 'Learned normal'],
  ['M2', 'Wear detector'],
  ['M3', 'Failure classifier'],
  ['M4', 'Inflow forecast'],
]
const METRICS = {
  pump: [
    ['flow_bpd', 'Pump flow'],
    ['discharge_psi', 'Discharge pressure'],
  ],
  pipeline: [
    ['pressure_psi', 'Line pressure'],
    ['receive_flow_bpd', 'Receive flow'],
  ],
}
const pct = (x) => (x == null ? '-' : `${Math.round(x * 100)}%`)

function useLive(fetcher, fallback) {
  const [state, setState] = useState(null)
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      let next
      try {
        next = { data: await fetcher(), source: 'live' }
      } catch {
        next = { data: fallback, source: 'mock' }
      }
      if (!cancelled) setState(next)
    })()
    return () => {
      cancelled = true
    }
  }, [fetcher, fallback])
  return state
}

// Copper eyebrow over a section heading: a short length of pipe.
function Eyebrow() {
  return (
    <div className="mb-2 flex items-center gap-2 text-brand" aria-hidden="true">
      <Icon name="pipe" size={16} />
      <span className="h-px w-12 bg-brand/60" />
    </div>
  )
}

function Card({ title, children, note }) {
  return (
    <section className="panel p-4">
      <h3 className="text-lg font-semibold">{title}</h3>
      {note && <p className="mt-1 text-sm text-muted">{note}</p>}
      <div className="mt-4">{children}</div>
    </section>
  )
}

function Reasons({ alert }) {
  const reasons = alert.reasons?.length ? alert.reasons : (alert.evidence ?? [])
  const m3 = alert.m3
  return (
    <li className="rounded-sm border border-line bg-surface-2 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{CATEGORY[alert.category] ?? alert.category}</span>
        <span className="tag border border-line-strong font-medium normal-case tracking-normal text-muted">source: {alert.source ?? 'rules'}</span>
        {alert.score != null && (
          <span className="tag border border-data/30 bg-data/10 font-medium normal-case tracking-normal text-data">score {Number(alert.score).toFixed(1)}</span>
        )}
        {alert.simulated && <span className="tag tag-sim">SIMULATED</span>}
      </div>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-fg marker:text-faint">
        {reasons.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
      {m3 && (
        <p className="mt-2 text-sm text-muted">
          Second opinion (M3): says <span className="font-semibold text-fg">{CATEGORY[m3.call] ?? m3.call}</span>
          {m3.agrees === false ? ', which disagrees with the rules' : ', which agrees with the rules'}.
          {m3.factors?.length > 0 && ` Main factors: ${m3.factors.map((f) => (typeof f === 'string' ? f : (f.name ?? f.feature ?? ''))).filter(Boolean).join(', ')}.`}
        </p>
      )}
    </li>
  )
}

function ModelLab({ network, t, usingMock, alerts, simulated }) {
  const facilities = useMemo(() => network?.systems.flatMap((s) => s.facilities) ?? [], [network])
  const [facilityId, setFacilityId] = useState('')
  const [kind, setKind] = useState('pump')
  const [metric, setMetric] = useState('flow_bpd')
  const [hours, setHours] = useState(12)

  const facility = facilities.find((f) => f.id === facilityId) ?? facilities[0]
  const assetId = facility?.[kind]?.id
  const baseline = useBaseline(assetId, metric, t, hours, usingMock)

  const fetchStatus = useMemo(() => (usingMock ? () => Promise.reject(new Error('mock')) : api.getModelStatus), [usingMock])
  const fetchEval = useMemo(() => (usingMock ? () => Promise.reject(new Error('mock')) : api.getModelEval), [usingMock])
  const status = useLive(fetchStatus, mock.modelStatusReady)
  const evalRes = useLive(fetchEval, mock.modelEval)

  const assetAlerts = alerts.filter((a) => a.asset_id === assetId && a.status === 'ongoing')
  const ev = evalRes?.data
  const evalEmpty = ev && !ev.folds?.some((f) => f.recall != null)
  const sample = evalRes?.source === 'mock' || !!ev?.mock_notice

  const compare = ev
    ? [
        ['Rules only', ev.comparison?.rules],
        ['Learned models', ev.comparison?.models],
        ['Combined', ev.comparison?.ensemble],
      ].map(([name, v]) => ({ name, minutes: v?.mean_minutes_late, recall: v?.recall }))
    : []
  const calibration = (ev?.calibration_bins ?? []).filter((b) => b.p_mean != null).map((b) => ({ ...b, ideal: b.p_mean }))

  if (!network) return <div className="skeleton h-96" />

  return (
    <div>
      <Eyebrow />
      <h1 className="text-3xl font-semibold">Model Lab</h1>
      <p className="mt-1 text-muted">How the app learns what normal looks like, and how well it spots problems it has not seen before.</p>

      {simulated && (
        <p className="banner mt-4 border-crit/60 bg-crit/12 font-semibold text-fg">
          <span className="tag tag-sim">SIMULATED</span>
          <span>a fault was injected into this view. Charts include fake data.</span>
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2" aria-label="Model status">
        {!status && <div className="skeleton h-8 w-80" />}
        {status &&
          MODELS.map(([id, name]) => {
            const m = status.data.models?.[id]
            const ready = !!m?.ready
            return (
              <span
                key={id}
                className={`tag border text-sm leading-8 font-medium normal-case tracking-normal ${
                  ready ? 'border-ok/40 bg-ok/10 text-ok' : 'border-line-strong bg-surface text-off'
                }`}
              >
                <span className={`led ${ready ? '' : 'led-hollow'}`} />
                {id} {name}: {ready ? 'ready' : 'not loaded'}
              </span>
            )
          })}
        {status && (
          <span className="tag border border-line-strong text-sm leading-8 font-medium normal-case tracking-normal text-muted">
            {status.data.pumps_calibrated} of {status.data.pumps_total} pumps calibrated
            {status.source === 'mock' && ' (sample)'}
          </span>
        )}
      </div>

      <div className="mt-6 flex flex-wrap items-end gap-4">
        <div>
          <label htmlFor="lab-facility" className="eyebrow mb-2 block text-muted">Facility</label>
          <select
            id="lab-facility"
            value={facility?.id ?? ''}
            onChange={(e) => setFacilityId(e.target.value)}
            className="field"
          >
            {facilities.map((f) => (
              <option key={f.id} value={f.id}>{f.id}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="lab-metric" className="eyebrow mb-2 block text-muted">Sensor</label>
          <select
            id="lab-metric"
            value={`${kind}:${metric}`}
            onChange={(e) => {
              const [k, m] = e.target.value.split(':')
              setKind(k)
              setMetric(m)
            }}
            className="field"
          >
            {Object.entries(METRICS).flatMap(([k, list]) =>
              list.map(([m, label]) => (
                <option key={`${k}:${m}`} value={`${k}:${m}`}>{k === 'pump' ? 'Pump' : 'Pipeline'}: {label}</option>
              ))
            )}
          </select>
        </div>
        <div>
          <label htmlFor="lab-hours" className="eyebrow mb-2 block text-muted">Window</label>
          <select
            id="lab-hours"
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
            className="field"
          >
            {[6, 12, 24, 48].map((h) => (
              <option key={h} value={h}>Last {h} hours</option>
            ))}
          </select>
        </div>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Card title="Learned normal band" note="The shaded band is what this sensor normally does. The line leaving it is the clue.">
          {baseline ? <BandChart result={baseline} /> : <div className="skeleton h-72" />}
        </Card>
        <Card title="Anomaly score" note="How far from normal, in units of this pump's own healthy spread. Above 3 is outside normal.">
          {baseline ? <ScoreChart result={baseline} /> : <div className="skeleton h-72" />}
        </Card>
      </div>

      <div className="mt-6">
        <Card title={`Why the app flagged ${assetId ?? 'this asset'}`}>
          {assetAlerts.length === 0 ? (
            <p className="text-sm text-muted">Nothing flagged on this asset at this time. Pick another facility, or move the time slider to a problem.</p>
          ) : (
            <ul className="space-y-3">
              {assetAlerts.map((a) => (
                <Reasons key={a.event_id} alert={a} />
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-12">
        <Eyebrow />
        <h2 className="text-2xl font-semibold">How well does it work?</h2>
      </div>
      {sample && (
        <p className="banner mt-4 border-warn/40 bg-warn/8 text-warn">
          <span className="led mt-1.5 self-start" aria-hidden="true" />
          <span className="min-w-0 flex-1">
            {evalRes?.source === 'mock'
              ? 'Evaluation results are not available yet. These are placeholder numbers for layout only.'
              : 'Placeholder numbers for layout only.'}
          </span>
        </p>
      )}
      {!evalRes && <div className="skeleton mt-4 h-72" />}
      {evalEmpty && !sample && (
        <p className="panel mt-4 p-4 text-fg">
          The evaluation has not been run yet. Run the evaluation script to fill this section.
        </p>
      )}
      {ev && !evalEmpty && (
        <div className="mt-4 grid gap-6 xl:grid-cols-2">
          <Card title="Tested on a system it never saw" note={`Method: ${ev.method}. Each row hides one whole system while learning, then tries to find that system's problems.`}>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="eyebrow text-muted">
                  <tr>
                    <th className="py-2 pr-4 font-medium">Held-out system</th>
                    <th className="py-2 pr-4 text-right font-medium">Precision</th>
                    <th className="py-2 pr-4 text-right font-medium">Recall</th>
                    <th className="py-2 pr-4 text-right font-medium">Minutes late</th>
                  </tr>
                </thead>
                <tbody>
                  {ev.folds.map((f) => (
                    <tr key={f.held_out_system} className="num border-t border-line">
                      <td className="py-2 pr-4 font-semibold">{f.held_out_system}</td>
                      <td className="py-2 pr-4 text-right">{pct(f.precision)}</td>
                      <td className="py-2 pr-4 text-right">{pct(f.recall)}</td>
                      <td className="py-2 pr-4 text-right">{f.mean_minutes_late ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="How early it catches problems" note="Average minutes after a problem starts before it is flagged. Lower is better.">
            <div className="screen h-64 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={compare}>
                  <CartesianGrid {...GRID} vertical={false} />
                  <XAxis dataKey="name" {...AXIS} />
                  <YAxis {...AXIS} />
                  <Tooltip {...TOOLTIP} cursor={{ fill: C.surface2 }} />
                  <Bar dataKey="minutes" name="Minutes late" fill={C.data} maxBarSize={56} radius={[2, 2, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="num mt-2 text-sm text-muted">
              Recall: {compare.map((c) => `${c.name} ${pct(c.recall)}`).join(' | ')}
            </p>
          </Card>
          <Card title="Can you trust the confidence?" note="When it says 70% sure, it should be right about 70% of the time. The dashed line is perfect.">
            <div className="screen h-64 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={calibration}>
                  <CartesianGrid {...GRID} />
                  <XAxis dataKey="p_mean" type="number" domain={[0, 1]} tickFormatter={pct} {...AXIS} name="Said" />
                  <YAxis domain={[0, 1]} tickFormatter={pct} {...AXIS} />
                  <Tooltip {...TOOLTIP} formatter={pct} labelFormatter={(v) => `Said ${pct(v)}`} />
                  <Legend />
                  <Line dataKey="ideal" name="Perfect" stroke={C.faint} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
                  <Line dataKey="observed" name="Actually right" stroke={C.data} strokeWidth={2} dot={{ r: 3, fill: C.data, stroke: C.ink }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>
          {ev.notes && (
            <Card title="Notes">
              <p className="text-sm text-fg">{Array.isArray(ev.notes) ? ev.notes.join(' ') : String(ev.notes)}</p>
            </Card>
          )}
        </div>
      )}
    </div>
  )
}

export default ModelLab
