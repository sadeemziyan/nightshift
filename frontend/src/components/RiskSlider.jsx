import { RISK_LEVELS } from '../status'

// How sure do you want to be that the tank never reaches shutdown? Higher safety can cost more.
const LABELS = ['Cheapest', '80%', '90%', '95%', '99%', '99.9%']

function RiskSlider({ risk, onChange, disabled }) {
  const index = Math.max(0, RISK_LEVELS.indexOf(risk))
  const last = RISK_LEVELS.length - 1
  return (
    <div className="panel p-4">
      <label htmlFor="risk" className="block text-sm text-muted">
        Safety level: chance of avoiding shutdown.{' '}
        <span className="num font-semibold text-fg">{LABELS[index]}</span>
      </label>
      <input
        id="risk"
        type="range"
        min={0}
        max={last}
        step={1}
        value={index}
        disabled={disabled}
        onChange={(e) => onChange(RISK_LEVELS[Number(e.target.value)])}
        className="slider mt-2"
        style={{ '--fill': `${(index / last) * 100}%` }}
      />
      {/* labelled ticks, inset by half the thumb width so each sits under its stop */}
      <div className="relative mx-[6px] mt-1 h-12 sm:h-8">
        {LABELS.map((l, i) => {
          const shift = i === 0 ? '0' : i === last ? '-100%' : '-50%'
          return (
            <span
              key={l}
              className={`num absolute top-0 flex flex-col text-xs ${i === 0 ? 'items-start' : i === last ? 'items-end' : 'items-center'} ${
                i === index ? 'text-fg' : 'text-muted'
              }`}
              style={{ left: `${(i / last) * 100}%`, transform: `translateX(${shift})` }}
            >
              <span className={`w-px ${i % 2 ? 'h-5 sm:h-1.5' : 'h-1.5'} ${i === index ? 'bg-data' : 'bg-line-strong'}`} />
              <span className="mt-1">{l}</span>
            </span>
          )
        })}
      </div>
    </div>
  )
}

export default RiskSlider
