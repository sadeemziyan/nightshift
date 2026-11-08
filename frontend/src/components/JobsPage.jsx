import { useState } from 'react'
import Icon from './Icon'
import { buildJobs } from '../jobs'
import { URGENCY, fmtClock } from '../status'
import { C } from '../theme'

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
  truck: { label: 'TRUCK', color: C.data, icon: 'truck' },
  shutin: { label: 'SHUT IN', color: C.warn, icon: 'valve' },
  inspect: { label: 'INSPECT', color: C.violet, icon: 'wrench' },
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
      <h1 className="text-3xl font-semibold">My jobs</h1>
      <p className="mt-1 text-sm text-muted">
        <span className="num text-fg">{open.length}</span> to do{finished > 0 && `, ${finished} done`}. As of{' '}
        <span className="num text-fg">{fmtClock(t)}Z</span>.
        {usingMock && ' Sample data.'}
      </p>

      {loading && jobs.length === 0 && (
        <div className="mt-4 space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton h-32" />
          ))}
        </div>
      )}

      {!loading && jobs.length === 0 && (
        <p className="banner mt-6 border-ok/30 bg-ok/8 p-4 text-base text-ok">
          No jobs right now. New ones show up here when a plan is approved or a pump needs a look.
        </p>
      )}

      <ul className="mt-4 space-y-2">
        {jobs.map((j) => {
          const isDone = done.has(j.id)
          const k = KIND[j.kind]
          return (
            <li
              key={j.id}
              className="panel border-l-4 p-4"
              style={{ borderLeftColor: isDone ? C.lineStrong : k.color }}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="tag text-ink" style={{ background: isDone ? C.off : k.color }}>
                  <Icon name={k.icon} size={14} />
                  {k.label}
                </span>
                <span className="num text-sm font-semibold text-fg">{until(j.when, t)}</span>
              </div>
              <p className={`mt-4 text-lg font-semibold leading-snug ${isDone ? 'text-muted line-through' : ''}`}>{j.title}</p>
              <p className={`mt-1 text-sm ${isDone ? 'text-faint' : 'text-muted'}`}>{j.detail}</p>
              <div className="mt-4 flex items-center justify-between gap-4">
                <span className="num text-xs text-faint">
                  {j.where} | {(URGENCY[j.urgency] ?? URGENCY.low).label}
                </span>
                <button
                  type="button"
                  onClick={() => toggle(j.id)}
                  className={`btn min-h-12 min-w-32 text-base ${isDone ? 'btn-ghost' : 'bg-ok text-ink hover:bg-ok/85'}`}
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
