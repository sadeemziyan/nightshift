// Colors for the places that need a value in JS (Recharts and React Flow props).
// They point at the tokens in index.css, so there is still only one place to change a color.
const v = (name) => `var(--color-${name})`

export const C = {
  ink: v('ink'),
  surface: v('surface'),
  surface2: v('surface-2'),
  line: v('line'),
  lineStrong: v('line-strong'),
  fg: v('fg'),
  muted: v('muted'),
  faint: v('faint'),
  data: v('data'),
  brand: v('brand'),
  ok: v('ok'),
  warn: v('warn'),
  bad: v('bad'),
  off: v('off'),
  crit: v('crit'),
  high: v('high'),
  violet: v('violet'),
}

// A token at some opacity, for tinted backgrounds.
export const tint = (color, pct) => `color-mix(in srgb, ${color} ${pct}%, transparent)`

// Shared chart look: faint grid, faint mono axis text, tooltips on the surface color.
export const AXIS = {
  stroke: C.lineStrong,
  tick: { fill: C.faint, fontSize: 12, fontFamily: 'var(--font-mono)' },
  tickLine: { stroke: C.lineStrong },
}
export const GRID = { stroke: C.line, strokeDasharray: '2 4' }
export const TOOLTIP = {
  contentStyle: {
    background: C.surface,
    border: `1px solid ${C.lineStrong}`,
    borderRadius: 2,
    fontFamily: 'var(--font-mono)',
    fontSize: 13,
    color: C.fg,
  },
  labelStyle: { color: C.muted, marginBottom: 4 },
  itemStyle: { color: C.fg, padding: 0 },
  cursor: { stroke: C.lineStrong },
}
export const refLabel = (value, color) => ({ value, fill: color, fontSize: 12, position: 'insideTopLeft' })
