import { useEffect, useState } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import * as api from '../api'
import { mock } from '../mock'
import { fmtClock } from '../status'
import { AXIS, C, GRID, TOOLTIP, refLabel } from '../theme'
import { ChartCard, SampleBadge } from './BaselineCharts'

const HOURS_BACK = 12

// Vertical tank gauge: 0-100% with a tick every 10%, marks at warning and shutdown, filled to the latest level.
function TankGauge({ level, warningPct, shutdownPct }) {
  const pct = Math.max(0, Math.min(100, level ?? 0))
  const color =
    shutdownPct != null && pct >= shutdownPct ? C.bad : warningPct != null && pct >= warningPct ? C.warn : C.data
  return (
    <div className="flex w-14 flex-none flex-col items-center gap-2" aria-hidden="true">
      <span className="num text-sm font-semibold text-fg">{level == null ? '-' : `${level.toFixed(1)}%`}</span>
      <div className="relative w-full flex-1">
        <div className="absolute inset-y-0 left-1 w-7 overflow-hidden rounded-[2px] border border-line-strong bg-ink">
          <div className="absolute inset-x-0 bottom-0" style={{ height: `${pct}%`, background: color, opacity: 0.85 }} />
        </div>
        {/* tick scale on the right */}
        <div
          className="absolute inset-y-0 right-0 w-3"
          style={{ background: `repeating-linear-gradient(to top, ${C.lineStrong} 0 1px, transparent 1px 10%)` }}
        />
        <div className="absolute right-0 bottom-1/2 h-px w-4 bg-faint" />
        {warningPct != null && <div className="absolute left-0 right-0 h-0.5 bg-warn" style={{ bottom: `${warningPct}%` }} />}
        {shutdownPct != null && <div className="absolute left-0 right-0 h-0.5 bg-bad" style={{ bottom: `${shutdownPct}%` }} />}
      </div>
    </div>
  )
}

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

  if (!result) return <p className="text-sm text-muted">Loading chart...</p>
  const { data, source } = result
  const rows = data.points.map(([ts, level]) => ({ ts, level }))
  const top = shutdownPct ?? 100
  const latest = rows.length ? rows[rows.length - 1].level : null

  return (
    <ChartCard
      caption={
        <>
          <span>
            <span className="num text-fg">{data.asset_id}</span> level (%), last {HOURS_BACK} hours.
          </span>
          {source === 'mock' && <SampleBadge>sample data</SampleBadge>}
        </>
      }
      aside={<TankGauge level={latest} warningPct={warningPct} shutdownPct={shutdownPct} />}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={fmtClock} {...AXIS} />
          <YAxis
            {...AXIS}
            domain={[(min) => Math.max(0, Math.floor(min - 3)), (max) => Math.ceil(Math.max(max, top) + 3)]}
          />
          <Tooltip labelFormatter={fmtClock} {...TOOLTIP} />
          {warningPct != null && (
            <ReferenceLine y={warningPct} stroke={C.warn} strokeDasharray="4 4" label={refLabel(`warning ${warningPct}%`, C.warn)} />
          )}
          {shutdownPct != null && (
            <ReferenceLine y={shutdownPct} stroke={C.bad} strokeWidth={2} label={refLabel(`SHUTDOWN ${shutdownPct}%`, C.bad)} />
          )}
          <Line dataKey="level" name="Level %" stroke={C.fg} strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

export default TankChart
