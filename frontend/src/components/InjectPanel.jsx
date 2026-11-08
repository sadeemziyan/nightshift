import { useState } from 'react'

const KINDS = [
  { id: 'pump_failure', label: 'Pump failure', needs: 'pump', severity: false },
  { id: 'pump_degradation', label: 'Pump wearing out', needs: 'pump', severity: true },
  { id: 'pipeline_leak', label: 'Pipeline leak', needs: 'pipeline', severity: true },
]

// Make a fault happen on stage. Everything it creates is SIMULATED, lives only in memory, and can be undone.
function InjectPanel({ facility, t, disabled, reason, onInject }) {
  const [kind, setKind] = useState('pump_failure')
  const [severity, setSeverity] = useState(0.7)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const spec = KINDS.find((k) => k.id === kind)
  const asset = facility?.[spec.needs]?.id

  async function submit() {
    setBusy(true)
    setError('')
    try {
      await onInject({ asset_id: asset, category: kind, onset_unix: Math.floor(t), severity: spec.severity ? severity : 1 })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <details className="panel group p-4">
      <summary className="flex min-h-8 cursor-pointer list-none items-center gap-2 font-semibold text-fg [&::-webkit-details-marker]:hidden">
        <svg viewBox="0 0 12 12" width="12" height="12" className="text-faint transition-transform group-open:rotate-90" aria-hidden="true">
          <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Inject a failure <span className="tag tag-sim ml-2">SIMULATED</span>
      </summary>
      <div className="mt-4 flex flex-wrap items-end gap-4">
        <div>
          <label htmlFor="inject-kind" className="eyebrow mb-2 block text-muted">Type</label>
          <select id="inject-kind" value={kind} onChange={(e) => setKind(e.target.value)} className="field">
            {KINDS.map((k) => (
              <option key={k.id} value={k.id}>{k.label}</option>
            ))}
          </select>
        </div>
        <p className="pb-3 text-sm text-muted">
          On <span className="num font-semibold text-fg">{asset ?? 'no facility selected'}</span>, starting now
        </p>
        {spec.severity && (
          <div className="min-w-40">
            <label htmlFor="inject-severity" className="eyebrow mb-1 block text-muted">
              Severity <span className="num text-fg">{Math.round(severity * 100)}%</span>
            </label>
            <input
              id="inject-severity"
              type="range"
              min={0.1}
              max={1}
              step={0.1}
              value={severity}
              onChange={(e) => setSeverity(Number(e.target.value))}
              className="slider"
              style={{ '--fill': `${((severity - 0.1) / 0.9) * 100}%` }}
            />
          </div>
        )}
        <button
          type="button"
          onClick={submit}
          disabled={disabled || busy || !asset}
          className="btn border-crit/70 text-fg hover:bg-crit/15"
        >
          {busy ? 'Injecting...' : 'Inject (simulated)'}
        </button>
      </div>
      <p className="mt-4 text-sm text-faint">
        Nothing is written to the data files. Press play to watch the system find it.
        {disabled && reason ? ` Unavailable: ${reason}` : ''}
      </p>
      {error && <p className="mt-2 text-sm text-bad">{error}</p>}
    </details>
  )
}

export default InjectPanel
