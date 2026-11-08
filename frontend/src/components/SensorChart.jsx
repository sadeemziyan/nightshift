import { useEffect, useState } from 'react'
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import * as api from '../api'
import { mock } from '../mock'
import { fmtClock } from '../status'

// A sensor line with the learned-normal band drawn behind it.
// Data: GET /model/baseline. Until that endpoint is live, the mock snapshot is shown and labeled.
function SensorChart({ assetId, metric = 'flow_bpd', t, usingMock }) {
  const [result, setResult] = useState(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      let next
      try {
        if (usingMock) throw new Error('mock mode')
        next = { data: await api.getBaseline(assetId, metric, t, 6), source: 'live' }
      } catch {
        next = { data: mock.modelBaseline, source: 'mock' }
      }
      if (!cancelled) setResult(next)
    })()
    return () => {
      cancelled = true
    }
  }, [assetId, metric, t, usingMock])

  if (!result) return <p className="text-sm text-slate-400">Loading chart...</p>

  const { data, source } = result
  const rows = data.points.map((p) => ({
    ts: p.ts_unix,
    actual: p.actual,
    expected: p.expected,
    lo: p.lower,
    band: Math.max(0, p.upper - p.lower),
  }))
  const peak = data.points.reduce((m, p) => Math.max(m, p.score ?? 0), 0)

  return (
    <div>
      <p className="mb-2 text-sm text-slate-400">
        {data.asset_id} {data.metric} ({data.unit}) against its learned normal. Peak score {peak.toFixed(1)}.
        {source === 'mock' && (
          <span className="ml-2 rounded bg-amber-500/20 px-2 py-0.5 text-amber-300">
            sample data: live baseline not available yet
          </span>
        )}
      </p>
      <div className="h-72 rounded-xl border border-slate-800 bg-slate-900 p-3">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows}>
            <CartesianGrid stroke="#1e293b" />
            <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={fmtClock} stroke="#64748b" />
            <YAxis stroke="#64748b" />
            <Tooltip
              labelFormatter={fmtClock}
              contentStyle={{ background: '#0f172a', border: '1px solid #334155' }}
            />
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

export default SensorChart
