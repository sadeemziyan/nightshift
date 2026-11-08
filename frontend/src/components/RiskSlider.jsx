import { RISK_LEVELS } from '../status'

// How sure do you want to be that the tank never reaches shutdown? Higher safety can cost more.
const LABELS = ['Cheapest', '80%', '90%', '95%', '99%', '99.9%']

function RiskSlider({ risk, onChange, disabled }) {
  const index = Math.max(0, RISK_LEVELS.indexOf(risk))
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <label htmlFor="risk" className="block text-sm text-slate-400">
        Safety level: chance of avoiding shutdown.{' '}
        <span className="font-semibold text-slate-100">{LABELS[index]}</span>
      </label>
      <input
        id="risk"
        type="range"
        min={0}
        max={RISK_LEVELS.length - 1}
        step={1}
        value={index}
        disabled={disabled}
        onChange={(e) => onChange(RISK_LEVELS[Number(e.target.value)])}
        className="mt-2 w-full accent-cyan-400 disabled:opacity-40"
      />
      <div className="mt-1 flex justify-between text-xs text-slate-500">
        {LABELS.map((l) => (
          <span key={l}>{l}</span>
        ))}
      </div>
    </div>
  )
}

export default RiskSlider
