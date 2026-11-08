import { fmtTime } from '../status'

const SPEEDS = [1, 10, 60, 300]

// Play the week forward. 60x means one minute of data passes every real second.
function ReplayControls({ playing, speed, onToggle, onSpeed, onNext, onJump, t, range, disabled }) {
  const atEnd = t != null && t >= range.max
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-800 bg-slate-900 p-3">
      <button
        type="button"
        onClick={onToggle}
        disabled={disabled}
        className="min-w-24 rounded-lg bg-cyan-500 px-4 py-2 font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-40"
      >
        {playing ? 'Pause' : atEnd ? 'Replay' : 'Play'}
      </button>
      <div className="flex overflow-hidden rounded-lg border border-slate-700" role="group" aria-label="Replay speed">
        {SPEEDS.map((s) => (
          <button
            type="button"
            key={s}
            onClick={() => onSpeed(s)}
            disabled={disabled}
            aria-pressed={speed === s}
            className={`px-3 py-2 text-sm font-semibold ${
              speed === s ? 'bg-slate-200 text-slate-950' : 'bg-slate-900 text-slate-300 hover:bg-slate-800'
            } disabled:opacity-40`}
          >
            {s}x
          </button>
        ))}
      </div>
      <button
        type="button"
        onClick={onNext}
        disabled={disabled}
        className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-40"
        title="Jump to just before the next problem starts"
      >
        Next problem
      </button>
      <button
        type="button"
        onClick={onJump}
        disabled={disabled}
        className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-40"
      >
        Latest data
      </button>
      <span className="ml-auto text-sm text-slate-400">
        {t != null && fmtTime(t)}
        {playing && <span className="ml-2 inline-block h-2 w-2 animate-pulse rounded-full bg-red-500" aria-label="live" />}
      </span>
    </div>
  )
}

export default ReplayControls
