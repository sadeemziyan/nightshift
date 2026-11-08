import { useState } from 'react'
import { buildJobs } from '../jobs'
import { URGENCY, fmtClock } from '../status'

const KEY = 'nightshift.jobs.done'

function loadDone() {
  try {
    return new Set(JSON.parse(window.localStorage.getItem(KEY) ?? '[]'))
  } catch {
    return new Set()
  }
}

function saveDone(set) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify([...set]))
  } catch {
    // private mode: the checkmarks just won't survive a reload
  }
}

const KIND = {
  truck: { label: 'TRUCK', color: '#22d3ee' },
  shutin: { label: 'SHUT IN', color: '#f59e0b' },
  inspect: { label: 'INSPECT', color: '#a78bfa' },
}

function until(when, t) {
  const m = Math.round((when - t) / 60)
  if (m <= 0) return 'now'
  if (m < 60) return `in ${m} min`
  return `in ${Math.floor(m / 60)} h ${m % 60} min`
}

// One card per truck trip or inspection. Built for a phone held in one hand.
function JobsPage({ plan, alerts, t, loading, usingMock }) {
  const [done, setDone] = useState(loadDone)
  const jobs = buildJobs(plan, alerts, t)
  const open = jobs.filter((j) => !done.has(j.id))
  const finished = jobs.length - open.length

  function toggle(id) {
    setDone((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      saveDone(next)
      return next
    })
  }

  return (
    <div className="mx-auto max-w-xl">
      <h1 className="text-3xl font-bold">My jobs</h1>
      <p className="mt-1 text-sm text-slate-400">
        {open.length} to do{finished > 0 && `, ${finished} done`}. As of {fmtClock(t)}Z.
        {usingMock && ' Sample data.'}
      </p>

      {loading && jobs.length === 0 && (
        <div className="mt-4 space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton h-32" />
          ))}
        </div>
      )}

      {!loading && jobs.length === 0 && (
        <p className="mt-6 rounded-xl bg-emerald-500/10 p-5 text-emerald-300">
          No jobs right now. New ones show up here when a plan is approved or a pump needs a look.
        </p>
      )}

      <ul className="mt-4 space-y-3">
        {jobs.map((j) => {
          const isDone = done.has(j.id)
          const k = KIND[j.kind]
          return (
            <li
              key={j.id}
              className={`rounded-xl border-l-8 bg-slate-900 p-4 ${isDone ? 'opacity-50' : ''}`}
              style={{ borderLeftColor: k.color }}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="rounded px-2 py-0.5 text-xs font-bold text-slate-900" style={{ background: k.color }}>
                  {k.label}
                </span>
                <span className="text-sm font-semibold text-slate-200">{until(j.when, t)}</span>
              </div>
              <p className={`mt-3 text-lg font-semibold leading-snug ${isDone ? 'line-through' : ''}`}>{j.title}</p>
              <p className="mt-1 text-sm text-slate-300">{j.detail}</p>
              <div className="mt-3 flex items-center justify-between gap-3">
                <span className="text-xs text-slate-500">
                  {j.where} | {(URGENCY[j.urgency] ?? URGENCY.low).label}
                </span>
                <button
                  type="button"
                  onClick={() => toggle(j.id)}
                  className={`min-h-12 min-w-28 rounded-lg px-4 font-semibold ${
                    isDone ? 'border border-slate-600 text-slate-300' : 'bg-emerald-400 text-slate-950'
                  }`}
                >
                  {isDone ? 'Undo' : 'Done'}
                </button>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export default JobsPage
