import PlanCards from './PlanCards'
import SensorChart from './SensorChart'
import TankChart from './TankChart'
import { fmtClock, fmtCountdown, fmtHours } from '../status'

// Everything about one facility: countdown, tank chart, pump chart, plans.
// `t` is the replay clock; `snapT` is the moment the forecast was computed, so the countdown keeps ticking between refreshes.
function FacilityDetail({
  facility, network, t, snapT, forecastRow, systemPlan, planLoading, usingMock, onApprove, approveDisabled, approveReason, planHeader,
}) {
  const limits = network.defaults?.tank_limits_pct ?? {}
  const shutdownPct = forecastRow?.shutdown_pct ?? limits.shutdown ?? null
  const h = forecastRow?.hours_to_limit
  const repairHours = forecastRow?.repair_hours_remaining
  const elapsed = Math.max(0, t - snapT)
  const secondsLeft = h?.p50 != null ? h.p50 * 3600 - elapsed : null
  const repairLeft = repairHours != null ? repairHours * 3600 - elapsed : null
  const repairFirst = h?.p50 != null && repairHours != null && h.p50 > repairHours

  return (
    <section className="mt-8">
      <h2 className="text-2xl font-semibold">{facility.id}</h2>

      <div className="mt-4 grid gap-4 lg:grid-cols-[20rem_1fr]">
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          {forecastRow ? (
            forecastRow.already_shut_in ? (
              <>
                <p className="text-sm text-slate-400">Tank status</p>
                <p className="mt-2 text-3xl font-bold text-slate-300">Already shut in</p>
                <p className="mt-2 text-sm text-slate-400">The wells are off until the pump is repaired.</p>
              </>
            ) : (
              <>
                <p className="text-sm text-slate-400">Time until shutdown</p>
                <p
                  className={`mt-2 font-mono text-5xl font-bold tabular-nums ${repairFirst ? 'text-emerald-400' : 'text-red-400'}`}
                  aria-live="off"
                >
                  {secondsLeft != null ? fmtCountdown(secondsLeft) : '-'}
                </p>
                {h?.p10 != null && h?.p90 != null && (
                  <p className="mt-1 text-xs text-slate-400">
                    Range {fmtHours(h.p10)} to {fmtHours(h.p90)} from when this was computed
                  </p>
                )}
                {forecastRow.trips_at_unix && (
                  <p className="mt-3 text-sm text-slate-300">Hits {shutdownPct}% at {fmtClock(forecastRow.trips_at_unix)}Z</p>
                )}
                <p className="mt-1 text-sm text-slate-300">
                  Repair done in {fmtHours(Math.max(0, repairLeft) / 3600)} ({fmtClock(forecastRow.repair_ends_unix)}Z)
                </p>
                {repairFirst && (
                  <p className="mt-3 rounded bg-emerald-500/15 px-3 py-2 text-xs text-emerald-300">
                    Repair finishes first, so no shutdown is expected.
                  </p>
                )}
              </>
            )
          ) : (
            <>
              <p className="text-sm text-slate-400">Countdown</p>
              <p className="mt-2 text-lg text-slate-300">No pump failure at this facility right now.</p>
              <p className="mt-2 text-xs text-slate-500">A countdown and plans appear here when its pump fails.</p>
            </>
          )}
        </div>
        <TankChart
          tankId={facility.tank.id}
          t={snapT}
          shutdownPct={shutdownPct}
          warningPct={limits.warning}
          usingMock={usingMock}
        />
      </div>

      <div className="mt-6">
        <SensorChart assetId={facility.pump.id} t={snapT} usingMock={usingMock} />
      </div>

      <div className="mt-8">
        <h3 className="mb-3 text-xl font-semibold">What to do</h3>
        {planHeader}
        {systemPlan ? (
          <div className={planLoading ? 'opacity-60 transition-opacity' : 'transition-opacity'} aria-busy={planLoading}>
            <PlanCards
              systemPlan={systemPlan}
              facilityId={facility.id}
              onApprove={onApprove}
              approveDisabled={approveDisabled}
              approveReason={approveReason}
            />
          </div>
        ) : planLoading ? (
          <div className="grid gap-4 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="skeleton h-48" aria-label="Working out the cheapest plan" />
            ))}
          </div>
        ) : (
          <p className="rounded-xl border border-slate-800 bg-slate-900 p-5 text-sm text-slate-400">
            Plans appear when a pump in this system fails. Press play, or use Next problem.
          </p>
        )}
      </div>
    </section>
  )
}

export default FacilityDetail
