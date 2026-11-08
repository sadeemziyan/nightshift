// Shown while a dataset loads: the models fit themselves to the network, then we say how many pumps were calibrated.
function LearningCard({ state }) {
  if (!state) return null
  if (state.phase === 'learning') {
    return (
      <div className="mt-4 rounded-xl border border-cyan-500/40 bg-cyan-500/10 p-4" role="status">
        <p className="font-semibold text-cyan-300">Learning this network...</p>
        <p className="mt-1 text-sm text-slate-300">Fitting each pump's normal behavior from {state.dataset}.</p>
        <div className="mt-3 h-2 overflow-hidden rounded bg-slate-800">
          <div className="indeterminate h-full rounded bg-cyan-400" />
        </div>
      </div>
    )
  }
  const m = state.models ?? {}
  const ready = m.status === 'ready'
  return (
    <div
      className={`mt-4 rounded-xl border p-4 ${ready ? 'border-emerald-500/40 bg-emerald-500/10' : 'border-amber-500/40 bg-amber-500/10'}`}
      role="status"
    >
      {ready ? (
        <p className="font-semibold text-emerald-300">
          Learning complete: {m.pumps_calibrated} pumps calibrated in {m.seconds} s
        </p>
      ) : (
        <p className="font-semibold text-amber-300">Models are not available, so Nightshift is running on rules alone.</p>
      )}
    </div>
  )
}

export default LearningCard
