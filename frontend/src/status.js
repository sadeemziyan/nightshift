// Turns /state and /alerts into one color per asset: green normal, yellow warning, red failing,
// gray shut in. Nothing here knows a facility name; everything is looked up by id.

import { C, tint } from './theme'

export const TONE = {
  ok: { border: C.ok, bg: tint(C.ok, 10), text: C.ok, label: 'Normal' },
  warn: { border: C.warn, bg: tint(C.warn, 10), text: C.warn, label: 'Warning' },
  bad: { border: C.bad, bg: tint(C.bad, 14), text: C.bad, label: 'Failing' },
  off: { border: C.off, bg: tint(C.off, 12), text: C.off, label: 'Shut in' },
  idle: { border: C.lineStrong, bg: C.surface, text: C.fg, label: '' },
}

const SEVERITY = { idle: 0, ok: 0, off: 1, warn: 2, bad: 3 }

export function worst(tones) {
  return tones.reduce((a, b) => (SEVERITY[b] > SEVERITY[a] ? b : a), 'ok')
}

const num = (x, digits = 0) =>
  x == null ? '-' : Number(x).toLocaleString(undefined, { maximumFractionDigits: digits })

export function buildStatus(network, state, alerts) {
  const byAsset = {}
  const byFacility = {}
  if (!network) return { byAsset, byFacility }

  const find = (list, id) => (list ?? []).find((x) => x.id === id)
  const ongoing = (alerts ?? []).filter((a) => a.status === 'ongoing')
  const alertFor = (assetId) => ongoing.find((a) => a.asset_id === assetId)

  for (const system of network.systems) {
    byAsset[system.disposal_site.id] = { tone: 'idle', detail: 'disposal site' }
    for (const fac of system.facilities) {
      const tones = []
      const put = (id, tone, detail) => {
        byAsset[id] = { tone, detail }
        tones.push(tone)
      }

      const tank = find(state?.tanks, fac.tank.id)
      if (!tank) put(fac.tank.id, 'idle', 'no data')
      else {
        const tone = { normal: 'ok', warning: 'warn', shutdown: 'bad' }[tank.state] ?? 'idle'
        put(fac.tank.id, tone, `${num(tank.level_pct, 1)}% full`)
      }

      const pump = find(state?.pumps, fac.pump.id)
      const pumpAlert = alertFor(fac.pump.id)
      if (pumpAlert?.category === 'pump_failure') put(fac.pump.id, 'bad', 'failed: no flow')
      else if (pumpAlert?.category === 'pump_degradation') put(fac.pump.id, 'warn', 'wearing out')
      else if (!pump) put(fac.pump.id, 'idle', 'no data')
      else if (pump.status === 2) put(fac.pump.id, 'bad', 'fault')
      else put(fac.pump.id, 'ok', pump.status === 1 ? `running, ${num(pump.flow_bpd)} bpd` : 'idle')

      const pipe = find(state?.pipelines, fac.pipeline.id)
      const pipeAlert = alertFor(fac.pipeline.id)
      if (pipeAlert?.category === 'pipeline_leak') put(fac.pipeline.id, 'bad', 'leak suspected')
      else put(fac.pipeline.id, pipe ? 'ok' : 'idle', pipe ? `${num(pipe.pressure_psi)} psi` : 'no data')

      for (const well of fac.wells) {
        const w = find(state?.wells, well.id)
        if (!w) put(well.id, 'idle', 'no data')
        else if (w.status === 0) put(well.id, 'off', 'shut in')
        else put(well.id, 'ok', `${num(w.water_bpd)} bpd water`)
      }
      byFacility[fac.id] = worst(tones)
    }
  }
  return { byAsset, byFacility }
}

export function fmtTime(unix) {
  if (unix == null) return ''
  return new Date(unix * 1000).toLocaleString('en-US', {
    timeZone: 'UTC', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  }) + 'Z'
}

export function fmtClock(unix) {
  return new Date(unix * 1000).toLocaleTimeString('en-US', {
    timeZone: 'UTC', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

// "3.32" hours -> "3h 19m"
export function fmtHours(h) {
  if (h == null) return '-'
  const mins = Math.max(0, Math.round(h * 60))
  return `${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, '0')}m`
}

export const URGENCY = {
  critical: { rank: 0, label: 'Critical', color: C.crit },
  high: { rank: 1, label: 'High', color: C.high },
  medium: { rank: 2, label: 'Medium', color: C.warn },
  low: { rank: 3, label: 'Low', color: C.ok },
}

export const CATEGORY = {
  pump_failure: 'Pump failure',
  pump_degradation: 'Pump wearing out',
  pipeline_leak: 'Pipeline leak',
}

// Most urgent first; ties go to whichever tank hits shutdown sooner.
export function sortAlerts(alerts) {
  const rank = (a) => URGENCY[a.urgency]?.rank ?? 9
  const eta = (a) => a.hours_to_limit?.p50 ?? Infinity
  return [...alerts].sort((a, b) => rank(a) - rank(b) || eta(a) - eta(b))
}

// One short line saying what the app recommends for an alert.
export function actionText(alert) {
  const a = alert.recommended_actions?.[0]
  if (!a) return ''
  if (a.type === 'dispatch_truck') return `Send ${a.trucks} truck${a.trucks === 1 ? '' : 's'}`
  if (a.type === 'shut_in_wells') return `Shut in ${a.wells.join(', ')} in ${a.start_after_min} min`
  if (a.type === 'field_inspection') return 'Send an inspector'
  return a.type.replace(/_/g, ' ')
}

// Seconds -> "3:19:42" (a ticking countdown)
export function fmtCountdown(seconds) {
  const s = Math.max(0, Math.round(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return `${h}:${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

export const usd = (x) => `$${Math.round(x).toLocaleString()}`

// 0.03 -> "3%"; tiny but nonzero -> "<1%"
export function fmtRisk(r) {
  if (r == null) return '-'
  if (r > 0 && r < 0.01) return '<1%'
  return `${Math.round(r * 100)}%`
}

// Safety levels on the plan slider: null = just the cheapest plan.
export const RISK_LEVELS = [null, 0.8, 0.9, 0.95, 0.99, 0.999]
