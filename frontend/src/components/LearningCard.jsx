// Shown while a dataset loads: the models fit themselves to the network, then we say how many pumps were calibrated.
function LearningCard({ state }) {
  if (!state) return null
  if (state.phase === 'learning') {
    return (
      <div className="banner mt-4 flex-col items-stretch border-data/40 bg-data/6 py-3" role="status">
        <p className="font-semibold text-data">Learning this network...</p>
        <p className="text-sm text-muted">Fitting each pump's normal behavior from <span className="num text-fg">{state.dataset}</span>.</p>
        <div className="mt-1 h-1 overflow-hidden rounded-[1px] bg-surface-2">
          <div className="indeterminate h-full" />
        </div>
      </div>
    )
  }
  const m = state.models ?? {}
  const ready = m.status === 'ready'
  return (
    <div className={`banner mt-4 ${ready ? 'border-ok/40 bg-ok/8 text-ok' : 'border-warn/40 bg-warn/8 text-warn'}`} role="status">
      <span className="led mt-1.5 self-start" aria-hidden="true" />
      {ready ? (
        <p className="min-w-0 flex-1 font-semibold">
          Learning complete: <span className="num">{m.pumps_calibrated}</span> pumps calibrated in <span className="num">{m.seconds}</span> s
        </p>
      ) : (
        <p className="min-w-0 flex-1 font-semibold">Models are not available, so Nightshift is running on rules alone.</p>
      )}
    </div>
  )
}

export default LearningCard
