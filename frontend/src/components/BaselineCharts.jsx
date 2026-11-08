import { Area, CartesianGrid, ComposedChart, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmtClock } from '../status'
import { AXIS, C, GRID, TOOLTIP, refLabel } from '../theme'

export function SampleTag({ source }) {
  if (source !== 'mock') return null
  return <SampleBadge>sample data: live baseline not available</SampleBadge>
}

// Yellow "this is sample data" marker. Lemon, not copper, so it never reads as brand.
export function SampleBadge({ children }) {
  return <span className="tag border border-warn/35 bg-warn/10 font-medium normal-case tracking-normal text-warn">{children}</span>
}

// The one chart card: caption on top, the plot in a recessed screen, optional instrument on the left.
export function ChartCard({ caption, height = 'h-72', aside, children }) {
  return (
    <div className="panel p-4">
      <p className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">{caption}</p>
      <div className={`flex gap-3 ${height}`}>
        {aside}
        <div className="screen min-w-0 flex-1 p-2">{children}</div>
      </div>
    </div>
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
    <ChartCard
      height={height}
      caption={
        <>
          <span>
            <span className="num text-fg">{data.asset_id}</span> {data.metric} ({data.unit}) against its learned normal.
          </span>
          <SampleTag source={source} />
        </>
      }
    >
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={fmtClock} {...AXIS} />
          <YAxis {...AXIS} />
          <Tooltip labelFormatter={fmtClock} {...TOOLTIP} />
          <Area dataKey="lo" stackId="band" stroke="none" fill="transparent" isAnimationActive={false} tooltipType="none" />
          <Area dataKey="band" stackId="band" stroke="none" fill={C.data} fillOpacity={0.15} isAnimationActive={false} tooltipType="none" />
          <Line dataKey="expected" name="Learned normal" stroke={C.data} strokeWidth={1.5} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
          <Line dataKey="actual" name="Actual" stroke={C.fg} strokeWidth={2} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

// How far from normal, in the equipment's own healthy spreads. The band edge is 3.
export function ScoreChart({ result, height = 'h-56' }) {
  const { data, source } = result
  const rows = data.points.map((p) => ({ ts: p.ts_unix, score: p.score }))
  const peak = rows.reduce((m, r) => Math.max(m, r.score ?? 0), 0)
  return (
    <ChartCard
      height={height}
      caption={
        <>
          <span>
            Anomaly score over time: distance from learned normal. Above 3 means outside the band. Peak{' '}
            <span className="num text-fg">{peak.toFixed(1)}</span>.
          </span>
          <SampleTag source={source} />
        </>
      }
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={fmtClock} {...AXIS} />
          <YAxis {...AXIS} scale="sqrt" domain={[0, (max) => Math.max(5, Math.ceil(max))]} />
          <Tooltip labelFormatter={fmtClock} {...TOOLTIP} />
          <ReferenceLine y={3} stroke={C.warn} strokeDasharray="4 4" label={refLabel('outside normal', C.warn)} />
          <Line dataKey="score" name="Score" stroke={C.data} strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}
