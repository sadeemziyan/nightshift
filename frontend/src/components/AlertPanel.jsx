import Icon from './Icon'
import { CATEGORY, URGENCY, actionText, fmtHours, sortAlerts } from '../status'

const ICON = { pump_failure: 'pump', pump_degradation: 'wrench', pipeline_leak: 'pipe' }

// Active problems, most urgent first. Click one to open its facility. New ones slide in during replay.
function AlertPanel({ alerts, selectedFacilityId, onSelect, fresh = new Set(), loading }) {
  const active = sortAlerts(alerts.filter((a) => a.status === 'ongoing'))

  return (
    <aside className="panel self-start p-4">
      <h2 className="text-lg font-semibold">
        Active problems (<span className="num">{active.length}</span>)
      </h2>
      {loading && active.length === 0 && (
        <div className="mt-4 space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton h-24" />
          ))}
        </div>
      )}
      {!loading && active.length === 0 && (
        <p className="banner mt-4 flex-nowrap items-start border-ok/30 bg-ok/8 text-ok">
          <span className="led mt-1.5" aria-hidden="true" />
          Nothing is wrong at this time. Press play to watch the week, or use Next problem.
        </p>
      )}
      <ul className="mt-4 max-h-[36rem] space-y-2 overflow-y-auto pr-1">
        {active.map((a) => {
          const urgency = URGENCY[a.urgency] ?? URGENCY.low
          const reasons = a.reasons?.length ? a.reasons : (a.evidence ?? [])
          const selected = a.facility_id === selectedFacilityId
          const confidence = Math.round((a.confidence ?? 0) * 100)
          return (
            <li key={a.event_id} className={fresh.has(a.event_id) ? 'pop-in rounded-sm' : ''}>
              <button
                type="button"
                onClick={() => onSelect(a)}
                className={`w-full rounded-sm border border-l-4 border-line bg-surface-2 p-3 text-left hover:border-line-strong ${
                  selected ? 'ring-2 ring-data' : ''
                }`}
                style={{ borderLeftColor: urgency.color }}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="flex items-center gap-2 font-semibold">
                    <Icon name={ICON[a.category] ?? 'drop'} size={16} className="text-muted" />
                    {CATEGORY[a.category] ?? a.category}
                  </span>
                  <span className="flex items-center gap-1">
                    {a.simulated && <span className="tag tag-sim">SIMULATED</span>}
                    <span className="tag text-ink" style={{ background: urgency.color }}>
                      {urgency.label}
                    </span>
                  </span>
                </div>
                <p className="num mt-1 text-xs text-muted">
                  {a.asset_id}
                  {a.hours_to_limit?.p50 != null && ` | shutdown in ${fmtHours(a.hours_to_limit.p50)}`}
                </p>
                <div className="mt-2 flex items-center gap-2" title="How sure the app is">
                  <div className="relative h-1.5 flex-1 overflow-hidden rounded-[1px] bg-ink">
                    <div className="h-full bg-data" style={{ width: `${confidence}%` }} />
                    {[25, 50, 75].map((x) => (
                      <span key={x} className="absolute top-0 h-full w-px bg-surface-2" style={{ left: `${x}%` }} />
                    ))}
                  </div>
                  <span className="num w-20 text-right text-xs text-muted">{confidence}% sure</span>
                </div>
                {reasons[0] && <p className="mt-2 text-sm leading-snug text-fg">{reasons[0]}</p>}
                <div className="mt-2 flex flex-wrap items-center justify-between gap-x-2 text-sm">
                  <span className="font-semibold text-data">{actionText(a)}</span>
                  <span className="num text-xs text-faint">source: {a.source ?? 'rules'}</span>
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
