import { fmtClock } from '../status'

const usd = (x) => `$${Math.round(x).toLocaleString()}`

const isDoNothing = (p) => p.cost_breakdown.trucks === 0 && p.cost_breakdown.shut_in === 0

// Ranked options for one system. The cheapest is highlighted.
function PlanCards({ systemPlan, facilityId }) {
  if (!systemPlan) return null
  const cheapest = Math.min(...systemPlan.plans.map((p) => p.cost_usd))
  const best = systemPlan.plans[0]
  const sep = systemPlan.planned_separately

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-6 rounded-xl border border-slate-800 bg-slate-900 p-4 text-sm">
        <div>
          <p className="text-slate-400">Do nothing</p>
          <p className="text-2xl font-bold text-red-400">{usd(systemPlan.do_nothing_cost_usd)}</p>
        </div>
        {sep && (
          <div>
            <p className="text-slate-400">Planning each tank separately</p>
            <p className="text-2xl font-bold text-amber-300">{usd(sep.cost_usd)}</p>
          </div>
        )}
        <div>
          <p className="text-slate-400">Our system plan</p>
          <p className="text-2xl font-bold text-emerald-400">{usd(best.cost_usd)}</p>
        </div>
        {sep && sep.extra_cost_vs_system_plan_usd > 0 && (
          <p className="max-w-xs self-center text-slate-300">
            Separate planning wants {sep.trucks_wanted_if_independent} trucks but the system owns{' '}
            {systemPlan.fleet_size}. Planning together saves {usd(sep.extra_cost_vs_system_plan_usd)}.
          </p>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {systemPlan.plans.map((p) => {
          const isBest = p.cost_usd === cheapest
          const mine = p.per_facility.find((f) => f.facility_id === facilityId)
          return (
            <article
              key={p.rank}
              className={`rounded-xl border-2 bg-slate-900 p-5 ${isBest ? 'border-emerald-400' : 'border-slate-800'}`}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-400">
                  {isDoNothing(p) ? 'Do nothing' : `Option ${p.rank}`}
                </span>
                {isBest && (
                  <span className="rounded bg-emerald-400 px-2 py-0.5 text-xs font-bold text-slate-900">CHEAPEST</span>
                )}
              </div>
              <p className="mt-2 text-3xl font-bold">{usd(p.cost_usd)}</p>
              <p className="mt-2 text-sm text-slate-200">{p.summary}</p>
              {mine && (
                <p className="mt-3 rounded bg-slate-800 px-3 py-2 text-xs text-cyan-200">
                  This facility: {mine.summary}
                  {mine.trip_arrivals.length > 0 &&
                    ` (truck arrives ${mine.trip_arrivals.map((a) => fmtClock(a.arrives_unix) + 'Z').join(', ')})`}
                </p>
              )}
              <p className="mt-3 text-xs text-slate-400">{p.cost_math}</p>
              <p className="mt-2 text-xs">
                {p.keeps_tank_under_shutdown ? (
                  <span className="text-emerald-400">Keeps every tank under shutdown</span>
                ) : (
                  <span className="text-red-400">A tank still hits shutdown</span>
                )}
                <span className="text-slate-500"> | {p.trucks_used} of {systemPlan.fleet_size} trucks</span>
              </p>
            </article>
          )
        })}
      </div>
    </div>
  )
}

export default PlanCards
