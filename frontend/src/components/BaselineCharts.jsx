import { Area, CartesianGrid, ComposedChart, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmtClock } from '../status'

const TOOLTIP = { background: '#0f172a', border: '1px solid #334155' }

export function SampleTag({ source }) {
  if (source !== 'mock') return null
  return (
    <span className="ml-2 rounded bg-amber-500/20 px-2 py-0.5 text-amber-300">
      sample data: live baseline not available
    </span>
  )
}

// The sensor line with the learned-normal band drawn behind it.
export function BandChart({ result, height = 'h-72' }) {
  const { data, source } = result
  const rows = data.points.map((p) => ({
    ts: p.ts_unix,
    actual: p.actual,
    expected: p.expected,
    lo: p.lower,
    band: Math.max(0, p.upper - p.lower),
  }))
  return (
    <div>
      <p className="mb-2 text-sm text-slate-400">
        {data.asset_id} {data.metric} ({data.unit}) against its learned normal.
        <SampleTag source={source} />
      </p>
      <div className={`${height} rounded-xl border border-slate-800 bg-slate-900 p-3`}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows}>
            <CartesianGrid stroke="#1e293b" />
            <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={fmtClock} stroke="#64748b" />
            <YAxis stroke="#64748b" />
            <Tooltip labelFormatter={fmtClock} contentStyle={TOOLTIP} />
            <Area dataKey="lo" stackId="band" stroke="none" fill="transparent" isAnimationActive={false} tooltipType="none" />
            <Area dataKey="band" stackId="band" stroke="none" fill="#22d3ee" fillOpacity={0.18} isAnimationActive={false} tooltipType="none" />
            <Line dataKey="expected" name="Learned normal" stroke="#22d3ee" strokeDasharray="5 4" dot={false} isAnimationActive={false} />
            <Line dataKey="actual" name="Actual" stroke="#f8fafc" strokeWidth={2} dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

// How far from normal, in the equipment's own healthy spreads. The band edge is 3.
export function ScoreChart({ result, height = 'h-56' }) {
  const { data, source } = result
  const rows = data.points.map((p) => ({ ts: p.ts_unix, score: p.score }))
  const peak = rows.reduce((m, r) => Math.max(m, r.score ?? 0), 0)
  return (
    <div>
      <p className="mb-2 text-sm text-slate-400">
        Anomaly score over time: distance from learned normal. Above 3 means outside the band. Peak {peak.toFixed(1)}.
        <SampleTag source={source} />
      </p>
      <div className={`${height} rounded-xl border border-slate-800 bg-slate-900 p-3`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows}>
            <CartesianGrid stroke="#1e293b" />
            <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={fmtClock} stroke="#64748b" />
            <YAxis stroke="#64748b" scale="sqrt" domain={[0, (max) => Math.max(5, Math.ceil(max))]} />
            <Tooltip labelFormatter={fmtClock} contentStyle={TOOLTIP} />
            <ReferenceLine y={3} stroke="#eab308" strokeDasharray="4 4" label={{ value: 'outside normal', fill: '#eab308', fontSize: 11, position: 'insideTopLeft' }} />
            <Line dataKey="score" name="Score" stroke="#f97316" strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
