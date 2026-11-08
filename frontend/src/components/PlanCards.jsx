import { useState } from 'react'
import { fmtClock, fmtRisk, usd } from '../status'

const isDoNothing = (p) => p.cost_breakdown.trucks === 0 && p.cost_breakdown.shut_in === 0
const SENT = {
  sent: { label: 'sent', cls: 'border-ok/40 bg-ok/12 text-ok' },
  simulated: { label: 'not sent (no phone set)', cls: 'border-brand/80 text-brand' },
  failed: { label: 'failed', cls: 'border-bad/40 bg-bad/12 text-bad' },
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
      <div className="mt-4 rounded-sm border border-ok/30 bg-ok/8 p-3 text-sm">
        <p className="font-semibold text-ok">Approved. The crew was texted:</p>
        <ul className="mt-2 space-y-1">
          {result.dispatches.map((d, i) => {
            const tag = SENT[d.status] ?? SENT.failed
            return (
              <li key={i} className="flex flex-wrap items-center gap-2 text-sm text-fg">
                <span className={`tag border font-medium normal-case tracking-normal ${tag.cls}`}>{tag.label}</span>
                <span className="text-muted">{d.to.replace('_', ' ')}:</span> {d.message}
              </li>
            )
          })}
        </ul>
      </div>
    )
  }
  if (step === 'confirm') {
    return (
      <div className="mt-4 rounded-sm border border-warn/50 bg-warn/8 p-3 text-sm">
        <p className="text-fg">This sends real text messages to the crew.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" onClick={send} className="btn border-warn/80 text-warn hover:bg-warn/15">
            Yes, text the crew
          </button>
          <button type="button" onClick={() => setStep('idle')} className="btn btn-ghost">
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
        className="btn btn-primary w-full"
      >
        {step === 'sending' ? 'Sending...' : isDoNothing(plan) ? 'Nothing to approve' : 'Approve this plan'}
      </button>
      {disabled && reason && <p className="mt-2 text-sm text-faint">{reason}</p>}
      {step === 'error' && <p className="mt-2 text-sm text-bad">Could not send: {error}</p>}
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
      <div className="readout mb-4 grid gap-4 px-4 py-3 text-sm sm:flex sm:flex-wrap sm:gap-x-8">
        <div>
          <p className="eyebrow text-muted">Do nothing</p>
          <p className="num mt-1 text-2xl font-bold text-bad">{usd(systemPlan.do_nothing_cost_usd)}</p>
        </div>
        {sep && (
          <div className="sm:border-l sm:border-line sm:pl-8">
            <p className="eyebrow text-muted">Planning each tank separately</p>
            <p className="num mt-1 text-2xl font-bold text-warn">{usd(sep.cost_usd)}</p>
          </div>
        )}
        <div className="sm:border-l sm:border-line sm:pl-8">
          <p className="eyebrow text-muted">Our system plan</p>
          <p className="num mt-1 text-2xl font-bold text-ok">{usd(best.cost_usd)}</p>
        </div>
        {sep && sep.extra_cost_vs_system_plan_usd > 0 && (
          <p className="max-w-sm self-center text-muted">
            Separate planning wants {sep.trucks_wanted_if_independent} trucks but the system owns{' '}
            {systemPlan.fleet_size}. Planning together saves {usd(sep.extra_cost_vs_system_plan_usd)}.
          </p>
        )}
      </div>

      {systemPlan.risk_level != null && systemPlan.cost_of_safety_usd != null && (
        <p className="banner mb-4 border-data/30 bg-data/6 text-fg">
          At {fmtRisk(systemPlan.risk_level)} safety the best plan costs {usd(systemPlan.cost_of_safety_usd)} more than the cheapest one.
        </p>
      )}
      {systemPlan.risk_note && (
        <p className="banner mb-4 border-warn/40 bg-warn/8 text-warn">{systemPlan.risk_note}</p>
      )}

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {systemPlan.plans.map((p) => {
          const isBest = p.cost_usd === cheapest
          const mine = p.per_facility.find((f) => f.facility_id === facilityId)
          return (
            <article
              key={`${systemPlan.event_ids.join('|')}-${p.rank}-${p.cost_usd}`}
              className={`panel flex flex-col p-4 ${isBest ? 'border-ok ring-1 ring-ok' : ''}`}
              style={isBest ? { '--tick': 'var(--color-ok)' } : undefined}
            >
              <div className="flex min-h-6 items-center justify-between">
                <span className="eyebrow text-muted">{isDoNothing(p) ? 'Do nothing' : `Option ${p.rank}`}</span>
                {isBest && <span className="tag bg-ok text-ink">CHEAPEST</span>}
              </div>
              <p className="num mt-2 text-3xl font-bold">{usd(p.cost_usd)}</p>
              <p className="mt-2 text-sm text-fg">{p.summary}</p>
              {mine && (
                <p className="mt-4 rounded-sm border-l-2 border-data bg-surface-2 px-3 py-2 text-sm text-fg">
                  This facility: {mine.summary}
                  {mine.trip_arrivals.length > 0 &&
                    ` (truck arrives ${mine.trip_arrivals.map((a) => fmtClock(a.arrives_unix) + 'Z').join(', ')})`}
                </p>
              )}
              <p className="num mt-4 text-xs leading-relaxed text-muted">{p.cost_math}</p>
              <p className="mt-2 text-sm">
                {p.keeps_tank_under_shutdown ? (
                  <span className="text-ok">Keeps every tank under shutdown</span>
                ) : (
                  <span className="text-bad">A tank still hits shutdown</span>
                )}
                <span className="num text-faint"> | {p.trucks_used} of {systemPlan.fleet_size} trucks</span>
              </p>
              {p.shutdown_risk != null && (
                <p className="mt-1 text-sm text-muted">
                  Chance a tank still shuts down: <span className="num font-semibold text-fg">{fmtRisk(p.shutdown_risk)}</span>
                  {p.meets_risk === false && <span className="ml-2 text-bad">misses the safety level</span>}
                </p>
              )}
              <div className="mt-auto">
                <Approval plan={p} onApprove={onApprove} disabled={approveDisabled} reason={approveReason} />
              </div>
            </article>
          )
        })}
      </div>
    </div>
  )
}

export default PlanCards
