import { useEffect, useState } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import * as api from '../api'
import { mock } from '../mock'
import { fmtClock } from '../status'

const HOURS_BACK = 12

// Tank level over the last 12 hours with the shutdown line drawn on it.
function TankChart({ tankId, t, shutdownPct, warningPct, usingMock }) {
  const [result, setResult] = useState(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      let next
      try {
        if (usingMock) throw new Error('mock mode')
        next = {
          data: await api.getTimeseries(tankId, 'level_pct', { from: t - HOURS_BACK * 3600, to: t }),
          source: 'live',
        }
      } catch {
        next = { data: mock.timeseries, source: 'mock' }
      }
      if (!cancelled) setResult(next)
    })()
    return () => {
      cancelled = true
    }
  }, [tankId, t, usingMock])

  if (!result) return <p className="text-sm text-slate-400">Loading chart...</p>
  const { data, source } = result
  const rows = data.points.map(([ts, level]) => ({ ts, level }))
  const top = shutdownPct ?? 100

  return (
    <div>
      <p className="mb-2 text-sm text-slate-400">
        {data.asset_id} level (%), last {HOURS_BACK} hours.
        {source === 'mock' && (
          <span className="ml-2 rounded bg-amber-500/20 px-2 py-0.5 text-amber-300">sample data</span>
        )}
      </p>
      <div className="h-72 rounded-xl border border-slate-800 bg-slate-900 p-3">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows}>
            <CartesianGrid stroke="#1e293b" />
            <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={fmtClock} stroke="#64748b" />
            <YAxis
              stroke="#64748b"
              domain={[(min) => Math.max(0, Math.floor(min - 3)), (max) => Math.ceil(Math.max(max, top) + 3)]}
            />
            <Tooltip labelFormatter={fmtClock} contentStyle={{ background: '#0f172a', border: '1px solid #334155' }} />
            {warningPct != null && (
              <ReferenceLine y={warningPct} stroke="#eab308" strokeDasharray="4 4" label={{ value: `warning ${warningPct}%`, fill: '#eab308', fontSize: 11, position: 'insideTopLeft' }} />
            )}
            {shutdownPct != null && (
              <ReferenceLine y={shutdownPct} stroke="#ef4444" strokeWidth={2} label={{ value: `SHUTDOWN ${shutdownPct}%`, fill: '#ef4444', fontSize: 11, position: 'insideTopLeft' }} />
            )}
            <Line dataKey="level" name="Level %" stroke="#22d3ee" strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export default TankChart
