function AlertPanel({ alerts, systemId }) {
  const visibleAlerts = alerts
    .filter((alert) => alert.system_id === systemId)
    .slice()
    .sort((a, b) => a.order - b.order)

  return (
    <section className="mt-6 rounded-xl border border-slate-800 bg-slate-900 p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Active alerts</h2>
        <span className="text-xs text-amber-400">SAMPLE DATA</span>
      </div>

      {visibleAlerts.length === 0 ? (
        <p className="mt-4 text-slate-400">
          No sample alerts for this system.
        </p>
      ) : (
        <div className="mt-4 space-y-4">
          {visibleAlerts.map((alert) => {
            const hours = alert.hours_to_limit?.p50
            const confidence = alert.confidence

            return (
              <article
                key={alert.event_id}
                className="rounded-lg border border-red-400/40 bg-red-400/5 p-4"
              >
                <h3 className="font-semibold capitalize text-red-400">
                  {alert.category.replaceAll('_', ' ')}
                </h3>

                <p className="mt-1 text-sm text-slate-300">
                  {alert.facility_id}
                </p>

                {alert.evidence.map((reason, index) => (
                  <p key={index} className="mt-3 text-sm text-slate-400">
                    {reason}
                  </p>
                ))}

                <div className="mt-4 flex flex-wrap gap-4 text-sm">
                  <span>
                    Confidence:{' '}
                    {confidence == null
                      ? 'Unavailable'
                      : `${Math.round(confidence * 100)}%`}
                  </span>

                  {hours != null && (
                    <span className="text-amber-400">
                      Estimated shutdown in {hours.toFixed(1)} hours
                    </span>
                  )}

                  <span className="text-slate-400">
                    Source: {alert.source}
                  </span>
                </div>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}

export default AlertPanel