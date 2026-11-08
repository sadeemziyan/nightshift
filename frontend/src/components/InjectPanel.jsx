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
    <details className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <summary className="cursor-pointer font-semibold text-slate-200">
        Inject a failure <span className="ml-2 rounded bg-red-500 px-2 py-0.5 text-xs font-bold text-white">SIMULATED</span>
      </summary>
      <div className="mt-4 flex flex-wrap items-end gap-4">
        <div>
          <label htmlFor="inject-kind" className="mb-1 block text-sm text-slate-400">Type</label>
          <select
            id="inject-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
          >
            {KINDS.map((k) => (
              <option key={k.id} value={k.id}>{k.label}</option>
            ))}
          </select>
        </div>
        <p className="text-sm text-slate-300">
          On <span className="font-semibold">{asset ?? 'no facility selected'}</span>, starting now
        </p>
        {spec.severity && (
          <div>
            <label htmlFor="inject-severity" className="mb-1 block text-sm text-slate-400">
              Severity {Math.round(severity * 100)}%
            </label>
            <input
              id="inject-severity"
              type="range"
              min={0.1}
              max={1}
              step={0.1}
              value={severity}
              onChange={(e) => setSeverity(Number(e.target.value))}
              className="accent-red-400"
            />
          </div>
        )}
        <button
          type="button"
          onClick={submit}
          disabled={disabled || busy || !asset}
          className="rounded-lg bg-red-500 px-4 py-2 font-semibold text-white hover:bg-red-400 disabled:opacity-40"
        >
          {busy ? 'Injecting...' : 'Inject (simulated)'}
        </button>
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Nothing is written to the data files. Press play to watch the system find it.
        {disabled && reason ? ` Unavailable: ${reason}` : ''}
      </p>
      {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
    </details>
  )
}

export default InjectPanel
