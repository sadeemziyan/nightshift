// Hand-drawn line icons, all on a 24px grid with the same 1.6 stroke and round joints.
const PATHS = {
  drop: <path d="M12 3.5c3.4 4.3 5.6 7.5 5.6 10.4a5.6 5.6 0 0 1-11.2 0c0-2.9 2.2-6.1 5.6-10.4z" />,
  pump: (
    <>
      <circle cx="10" cy="12" r="5" />
      <circle cx="10" cy="12" r="1.3" />
      <path d="M10 7h9.5v4M2.5 12H5M6 20.5h8M8 16.6 7 20.5M12 16.6l1 3.9" />
    </>
  ),
  tank: (
    <>
      <ellipse cx="12" cy="5.8" rx="6.5" ry="2.3" />
      <path d="M5.5 5.8v12.4c0 1.3 2.9 2.3 6.5 2.3s6.5-1 6.5-2.3V5.8" />
      <path d="M5.5 13c0 1.3 2.9 2.3 6.5 2.3s6.5-1 6.5-2.3" strokeDasharray="1.6 2" />
    </>
  ),
  truck: (
    <>
      <rect x="2" y="7" width="11" height="7.5" rx="3.75" />
      <path d="M13 10h3.8l3.2 3.6V17h-1.2M13 10v7M2 17h2.2M7.8 17h7.4" />
      <circle cx="6" cy="17.5" r="1.8" />
      <circle cx="17" cy="17.5" r="1.8" />
    </>
  ),
  wrench: (
    <path d="M14.8 3.8a4.6 4.6 0 0 0-4.4 6.1l-6 6a1.9 1.9 0 0 0 2.7 2.7l6-6a4.6 4.6 0 0 0 6.1-4.4l-2.5 2.5-2.6-.6-.6-2.6z" />
  ),
  pipe: <path d="M2.5 9.5h19M2.5 14.5h19M7 7.5v9M9 7.5v9M15 7.5v9M17 7.5v9" />,
  valve: <path d="M3.5 9.5 12 14l-8.5 4.5zM20.5 9.5 12 14l8.5 4.5zM12 14V6.5M8.5 5h7" />,
  disposal: <path d="M3 20.5h18M12 3.5v10M8.6 10.3 12 13.7l3.4-3.4M8.5 20.5V17h7v3.5" />,
  play: <path d="M8 5.5v13l10-6.5z" fill="currentColor" />,
  pause: <path d="M8.5 5.5v13M15.5 5.5v13" strokeWidth="2.4" />,
}

function Icon({ name, size = 18, className = '', title }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 ${className}`}
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
    >
      {title && <title>{title}</title>}
      {PATHS[name]}
    </svg>
  )
}

export default Icon
