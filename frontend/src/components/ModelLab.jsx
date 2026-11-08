import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from 'recharts'
import * as api from '../api'
import { mock } from '../mock'
import { useBaseline } from '../hooks'
import { BandChart, ScoreChart } from './BaselineCharts'
import { CATEGORY } from '../status'

const TOOLTIP = { background: '#0f172a', border: '1px solid #334155' }
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

function Card({ title, children, note }) {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
      <h3 className="text-lg font-semibold">{title}</h3>
      {note && <p className="mt-1 text-sm text-slate-400">{note}</p>}
      <div className="mt-4">{children}</div>
    </section>
  )
}

function Reasons({ alert }) {
  const reasons = alert.reasons?.length ? alert.reasons : (alert.evidence ?? [])
  const m3 = alert.m3
  return (
    <li className="rounded-lg bg-slate-800 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{CATEGORY[alert.category] ?? alert.category}</span>
        <span className="rounded bg-slate-700 px-2 py-0.5 text-xs text-slate-300">source: {alert.source ?? 'rules'}</span>
        {alert.score != null && (
          <span className="rounded bg-cyan-500/20 px-2 py-0.5 text-xs text-cyan-300">score {Number(alert.score).toFixed(1)}</span>
        )}
        {alert.simulated && <span className="rounded bg-red-500 px-2 py-0.5 text-xs font-bold text-white">SIMULATED</span>}
      </div>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-slate-300">
        {reasons.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
      {m3 && (
        <p className="mt-2 text-xs text-slate-400">
          Second opinion (M3): says <span className="font-semibold text-slate-200">{CATEGORY[m3.call] ?? m3.call}</span>
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
      <h1 className="text-3xl font-bold">Model Lab</h1>
      <p className="mt-1 text-slate-400">How the app learns what normal looks like, and how well it spots problems it has not seen before.</p>

      {simulated && (
        <p className="mt-3 rounded-lg bg-red-500/15 px-4 py-2 text-sm font-semibold text-red-300">
          SIMULATED: a fault was injected into this view. Charts include fake data.
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
                className={`rounded-full border px-3 py-1 text-sm ${
                  ready ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300' : 'border-slate-600 bg-slate-900 text-slate-400'
                }`}
              >
                {id} {name}: {ready ? 'ready' : 'not loaded'}
              </span>
            )
          })}
        {status && (
          <span className="rounded-full border border-slate-700 px-3 py-1 text-sm text-slate-300">
            {status.data.pumps_calibrated} of {status.data.pumps_total} pumps calibrated
            {status.source === 'mock' && ' (sample)'}
          </span>
        )}
      </div>

      <div className="mt-6 flex flex-wrap items-end gap-4">
        <div>
          <label htmlFor="lab-facility" className="mb-2 block text-sm text-slate-400">Facility</label>
          <select
            id="lab-facility"
            value={facility?.id ?? ''}
            onChange={(e) => setFacilityId(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-3"
          >
            {facilities.map((f) => (
              <option key={f.id} value={f.id}>{f.id}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="lab-metric" className="mb-2 block text-sm text-slate-400">Sensor</label>
          <select
            id="lab-metric"
            value={`${kind}:${metric}`}
            onChange={(e) => {
              const [k, m] = e.target.value.split(':')
              setKind(k)
              setMetric(m)
            }}
            className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-3"
          >
            {Object.entries(METRICS).flatMap(([k, list]) =>
              list.map(([m, label]) => (
                <option key={`${k}:${m}`} value={`${k}:${m}`}>{k === 'pump' ? 'Pump' : 'Pipeline'}: {label}</option>
              ))
            )}
          </select>
        </div>
        <div>
          <label htmlFor="lab-hours" className="mb-2 block text-sm text-slate-400">Window</label>
          <select
            id="lab-hours"
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
            className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-3"
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
            <p className="text-sm text-slate-400">Nothing flagged on this asset at this time. Pick another facility, or move the time slider to a problem.</p>
          ) : (
            <ul className="space-y-3">
              {assetAlerts.map((a) => (
                <Reasons key={a.event_id} alert={a} />
              ))}
            </ul>
          )}
        </Card>
      </div>

      <h2 className="mt-10 text-2xl font-semibold">How well does it work?</h2>
      {sample && (
        <p className="mt-2 rounded-lg bg-amber-500/10 px-4 py-2 text-sm text-amber-300">
          {evalRes?.source === 'mock'
            ? 'Evaluation results are not available yet. These are placeholder numbers for layout only.'
            : 'Placeholder numbers for layout only.'}
        </p>
      )}
      {!evalRes && <div className="skeleton mt-4 h-72" />}
      {evalEmpty && !sample && (
        <p className="mt-4 rounded-xl border border-slate-800 bg-slate-900 p-5 text-slate-300">
          The evaluation has not been run yet. Run the evaluation script to fill this section.
        </p>
      )}
      {ev && !evalEmpty && (
        <div className="mt-4 grid gap-6 xl:grid-cols-2">
          <Card title="Tested on a system it never saw" note={`Method: ${ev.method}. Each row hides one whole system while learning, then tries to find that system's problems.`}>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-slate-400">
                  <tr>
                    <th className="py-2 pr-4">Held-out system</th>
                    <th className="py-2 pr-4">Precision</th>
                    <th className="py-2 pr-4">Recall</th>
                    <th className="py-2 pr-4">Minutes late</th>
                  </tr>
                </thead>
                <tbody>
                  {ev.folds.map((f) => (
                    <tr key={f.held_out_system} className="border-t border-slate-800">
                      <td className="py-2 pr-4 font-semibold">{f.held_out_system}</td>
                      <td className="py-2 pr-4">{pct(f.precision)}</td>
                      <td className="py-2 pr-4">{pct(f.recall)}</td>
                      <td className="py-2 pr-4">{f.mean_minutes_late ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="How early it catches problems" note="Average minutes after a problem starts before it is flagged. Lower is better.">
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={compare}>
                  <CartesianGrid stroke="#1e293b" />
                  <XAxis dataKey="name" stroke="#64748b" />
                  <YAxis stroke="#64748b" />
                  <Tooltip contentStyle={TOOLTIP} />
                  <Bar dataKey="minutes" name="Minutes late" fill="#22d3ee" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-2 text-xs text-slate-400">
              Recall: {compare.map((c) => `${c.name} ${pct(c.recall)}`).join(' | ')}
            </p>
          </Card>
          <Card title="Can you trust the confidence?" note="When it says 70% sure, it should be right about 70% of the time. The dashed line is perfect.">
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={calibration}>
                  <CartesianGrid stroke="#1e293b" />
                  <XAxis dataKey="p_mean" type="number" domain={[0, 1]} tickFormatter={pct} stroke="#64748b" name="Said" />
                  <YAxis domain={[0, 1]} tickFormatter={pct} stroke="#64748b" />
                  <Tooltip contentStyle={TOOLTIP} formatter={pct} labelFormatter={(v) => `Said ${pct(v)}`} />
                  <Legend />
                  <Line dataKey="ideal" name="Perfect" stroke="#64748b" strokeDasharray="5 4" dot={false} isAnimationActive={false} />
                  <Line dataKey="observed" name="Actually right" stroke="#34d399" strokeWidth={2} dot isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>
          {ev.notes && (
            <Card title="Notes">
              <p className="text-sm text-slate-300">{Array.isArray(ev.notes) ? ev.notes.join(' ') : String(ev.notes)}</p>
            </Card>
          )}
        </div>
      )}
    </div>
  )
}

export default ModelLab
