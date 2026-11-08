import { useId } from 'react'

// A copper drop with a crescent moon cut out of it.
function Logo({ size = 32, className = '' }) {
  const id = `ns-logo${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} className={`shrink-0 text-brand ${className}`} aria-hidden="true">
      <mask id={id}>
        <rect width="32" height="32" fill="#fff" />
        <circle cx="14.2" cy="19.6" r="5.6" fill="#000" />
        <circle cx="16.9" cy="17.6" r="4.9" fill="#fff" />
      </mask>
      <path d="M16 2.5C21.2 9 25 14 25 19.5a9 9 0 0 1-18 0C7 14 10.8 9 16 2.5z" fill="currentColor" mask={`url(#${id})`} />
    </svg>
  )
}

export default Logo
