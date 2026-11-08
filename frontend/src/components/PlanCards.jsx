import { useState } from 'react'
import { fmtClock, fmtRisk, usd } from '../status'

const isDoNothing = (p) => p.cost_breakdown.trucks === 0 && p.cost_breakdown.shut_in === 0
const SENT = {
  sent: { label: 'sent', cls: 'bg-emerald-500/20 text-emerald-300' },
  simulated: { label: 'not sent (no phone set)', cls: 'bg-amber-500/20 text-amber-300' },
  failed: { label: 'failed', cls: 'bg-red-500/20 text-red-300' },
}

function Approval({ plan, onApprove, disabled, reason }) {
  const [step, setStep] = useState('idle') // idle | confirm | sending | done | error
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  async function send() {
    setStep('sending')
    try {
      setResult(await onApprove(plan))
      setStep('done')
    } catch (err) {
      setError(err.message)
      setStep('error')
    }
  }

  if (step === 'done' && result) {
    return (
      <div className="mt-4 rounded-lg bg-emerald-500/10 p-3 text-sm">
        <p className="font-semibold text-emerald-300">Approved. The crew was texted:</p>
        <ul className="mt-2 space-y-1">
          {result.dispatches.map((d, i) => {
            const tag = SENT[d.status] ?? SENT.failed
            return (
              <li key={i} className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
                <span className={`rounded px-2 py-0.5 ${tag.cls}`}>{tag.label}</span>
                <span className="text-slate-400">{d.to.replace('_', ' ')}:</span> {d.message}
              </li>
            )
          })}
        </ul>
      </div>
    )
  }
  if (step === 'confirm') {
    return (
      <div className="mt-4 rounded-lg border border-cyan-500/40 p-3 text-sm">
        <p className="text-slate-200">This sends real text messages to the crew.</p>
        <div className="mt-2 flex gap-2">
          <button type="button" onClick={send} className="rounded bg-cyan-500 px-3 py-1.5 font-semibold text-slate-950 hover:bg-cyan-400">
            Yes, text the crew
          </button>
          <button type="button" onClick={() => setStep('idle')} className="rounded border border-slate-600 px-3 py-1.5 text-slate-300">
            Cancel
          </button>
        </div>
      </div>
    )
  }
  return (
    <div className="mt-4">
      <button
        type="button"
        onClick={() => setStep('confirm')}
        disabled={disabled || step === 'sending' || isDoNothing(plan)}
        className="w-full rounded-lg bg-cyan-500 px-4 py-2 font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-40"
      >
        {step === 'sending' ? 'Sending...' : isDoNothing(plan) ? 'Nothing to approve' : 'Approve this plan'}
      </button>
      {disabled && reason && <p className="mt-1 text-xs text-slate-500">{reason}</p>}
      {step === 'error' && <p className="mt-1 text-xs text-red-400">Could not send: {error}</p>}
    </div>
  )
}

// Ranked options for one system. The cheapest is highlighted; each can be approved.
function PlanCards({ systemPlan, facilityId, onApprove, approveDisabled, approveReason }) {
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

      {systemPlan.risk_level != null && systemPlan.cost_of_safety_usd != null && (
        <p className="mb-3 rounded-lg bg-cyan-500/10 px-4 py-2 text-sm text-cyan-200">
          At {fmtRisk(systemPlan.risk_level)} safety the best plan costs {usd(systemPlan.cost_of_safety_usd)} more than the cheapest one.
        </p>
      )}
      {systemPlan.risk_note && (
        <p className="mb-3 rounded-lg bg-amber-500/10 px-4 py-2 text-sm text-amber-300">{systemPlan.risk_note}</p>
      )}

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {systemPlan.plans.map((p) => {
          const isBest = p.cost_usd === cheapest
          const mine = p.per_facility.find((f) => f.facility_id === facilityId)
          return (
            <article
              key={`${systemPlan.event_ids.join('|')}-${p.rank}-${p.cost_usd}`}
              className={`rounded-xl border-2 bg-slate-900 p-5 ${isBest ? 'border-emerald-400' : 'border-slate-800'}`}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-400">{isDoNothing(p) ? 'Do nothing' : `Option ${p.rank}`}</span>
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
              {p.shutdown_risk != null && (
                <p className="mt-1 text-xs text-slate-300">
                  Chance a tank still shuts down: <span className="font-semibold">{fmtRisk(p.shutdown_risk)}</span>
                  {p.meets_risk === false && <span className="ml-2 text-red-400">misses the safety level</span>}
                </p>
              )}
              <Approval plan={p} onApprove={onApprove} disabled={approveDisabled} reason={approveReason} />
            </article>
          )
        })}
      </div>
    </div>
  )
}

export default PlanCards
