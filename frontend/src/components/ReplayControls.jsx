import Icon from './Icon'
import { fmtTime } from '../status'

const SPEEDS = [1, 10, 60, 300]

// Play the week forward. 60x means one minute of data passes every real second.
function ReplayControls({ playing, speed, onToggle, onSpeed, onNext, onJump, t, range, disabled }) {
  const atEnd = t != null && t >= range.max
  return (
    <div className="panel flex flex-wrap items-center gap-2 p-2">
      <button
        type="button"
        onClick={onToggle}
        disabled={disabled}
        className={`btn btn-primary min-h-12 min-w-32 px-6 text-base ${playing ? 'glow-data' : ''}`}
      >
        <Icon name={playing ? 'pause' : 'play'} size={18} />
        {playing ? 'Pause' : atEnd ? 'Replay' : 'Play'}
      </button>
      <div className="flex h-10 overflow-hidden rounded-sm border border-line-strong" role="group" aria-label="Replay speed">
        {SPEEDS.map((s) => (
          <button
            type="button"
            key={s}
            onClick={() => onSpeed(s)}
            disabled={disabled}
            aria-pressed={speed === s}
            className={`num border-l border-line-strong px-3 text-sm font-semibold first:border-l-0 ${
              speed === s ? 'bg-fg text-ink' : 'text-muted hover:bg-surface-2 hover:text-fg'
            } disabled:cursor-not-allowed disabled:opacity-40`}
          >
            {s}x
          </button>
        ))}
      </div>
      <button
        type="button"
        onClick={onNext}
        disabled={disabled}
        className="btn btn-ghost"
        title="Jump to just before the next problem starts"
      >
        Next problem
      </button>
      <button type="button" onClick={onJump} disabled={disabled} className="btn btn-ghost">
        Latest data
      </button>
      <span className="num ml-auto flex items-center gap-2 px-2 text-sm text-muted">
        {t != null && fmtTime(t)}
        {playing && <span className="led led-live text-crit" aria-label="live" />}
      </span>
    </div>
  )
}

export default ReplayControls
