import { CATEGORY, URGENCY, actionText, fmtHours, sortAlerts } from '../status'

// Active problems, most urgent first. Click one to open its facility. New ones slide in during replay.
function AlertPanel({ alerts, selectedFacilityId, onSelect, fresh = new Set(), loading }) {
  const active = sortAlerts(alerts.filter((a) => a.status === 'ongoing'))

  return (
    <aside className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <h2 className="text-lg font-semibold">Active problems ({active.length})</h2>
      {loading && active.length === 0 && (
        <div className="mt-3 space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton h-24" />
          ))}
        </div>
      )}
      {!loading && active.length === 0 && (
        <p className="mt-3 rounded-lg bg-emerald-500/10 p-3 text-sm text-emerald-300">
          Nothing is wrong at this time. Press play to watch the week, or use Next problem.
        </p>
      )}
      <ul className="mt-3 max-h-[36rem] space-y-3 overflow-y-auto pr-1">
        {active.map((a) => {
          const urgency = URGENCY[a.urgency] ?? URGENCY.low
          const reasons = a.reasons?.length ? a.reasons : (a.evidence ?? [])
          const selected = a.facility_id === selectedFacilityId
          return (
            <li key={a.event_id} className={fresh.has(a.event_id) ? 'pop-in rounded-lg' : ''}>
              <button
                type="button"
                onClick={() => onSelect(a)}
                className={`w-full rounded-lg border-l-4 bg-slate-800 p-3 text-left hover:bg-slate-700 ${
                  selected ? 'ring-2 ring-cyan-400' : ''
                }`}
                style={{ borderLeftColor: urgency.color }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold">{CATEGORY[a.category] ?? a.category}</span>
                  <span className="flex items-center gap-1">
                    {a.simulated && (
                      <span className="rounded bg-red-500 px-2 py-0.5 text-xs font-bold text-white">SIMULATED</span>
                    )}
                    <span className="rounded px-2 py-0.5 text-xs font-semibold text-slate-900" style={{ background: urgency.color }}>
                      {urgency.label}
                    </span>
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-400">
                  {a.asset_id}
                  {a.hours_to_limit?.p50 != null && ` | shutdown in ${fmtHours(a.hours_to_limit.p50)}`}
                </p>
                <div className="mt-2 flex items-center gap-2" title="How sure the app is">
                  <div className="h-2 flex-1 overflow-hidden rounded bg-slate-700">
                    <div className="h-full rounded bg-cyan-400" style={{ width: `${Math.round((a.confidence ?? 0) * 100)}%` }} />
                  </div>
                  <span className="w-20 text-right text-xs text-slate-300">{Math.round((a.confidence ?? 0) * 100)}% sure</span>
                </div>
                {reasons[0] && <p className="mt-2 text-xs text-slate-300">{reasons[0]}</p>}
                <div className="mt-2 flex items-center justify-between text-xs">
                  <span className="font-semibold text-cyan-300">{actionText(a)}</span>
                  <span className="text-slate-500">source: {a.source ?? 'rules'}</span>
                </div>
              </button>
            </li>
          )
        })}
      </ul>
    </aside>
  )
}

export default AlertPanel
