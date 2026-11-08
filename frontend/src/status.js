// Turns /state and /alerts into one color per asset: green normal, yellow warning, red failing,
// gray shut in. Nothing here knows a facility name; everything is looked up by id.

export const TONE = {
  ok: { border: '#22c55e', bg: 'rgba(34,197,94,0.10)', text: '#bbf7d0', label: 'Normal' },
  warn: { border: '#eab308', bg: 'rgba(234,179,8,0.12)', text: '#fef08a', label: 'Warning' },
  bad: { border: '#ef4444', bg: 'rgba(239,68,68,0.15)', text: '#fecaca', label: 'Failing' },
  off: { border: '#64748b', bg: 'rgba(100,116,139,0.14)', text: '#cbd5e1', label: 'Shut in' },
  idle: { border: '#475569', bg: '#0f172a', text: '#e2e8f0', label: '' },
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
