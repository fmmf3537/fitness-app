/**
 * UIX-11 全站线条图标集（lucide 风格内联 SVG，不引新依赖）。
 * 用法：<Icon name="dumbbell" size={18} />
 */

function Svg({ size, strokeWidth, className, children }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {children}
    </svg>
  )
}

const ICONS = {
  calendar: (p) => (
    <Svg {...p}>
      <rect x="3" y="4" width="18" height="17" rx="3" />
      <path d="M8 2v4M16 2v4M3 9h18" />
    </Svg>
  ),
  plan: (p) => (
    <Svg {...p}>
      <path d="M9 5h6M9 3v4M9 5a3 3 0 0 0-3 3v10a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V8a3 3 0 0 0-3-3M9 12h6M9 16h4" />
    </Svg>
  ),
  trend: (p) => (
    <Svg {...p}>
      <path d="M3 17l6-6 4 4 8-8M21 7v6h-6" />
    </Svg>
  ),
  coach: (p) => (
    <Svg {...p}>
      <path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </Svg>
  ),
  dumbbell: (p) => (
    <Svg {...p}>
      <path d="M4 9v6M8 7v10M16 7v10M20 9v6M8 12h8" />
    </Svg>
  ),
  flame: (p) => (
    <Svg {...p}>
      <path d="M12 3s5.5 4.2 5.5 9.2a5.5 5.5 0 0 1-11 0c0-2.1 1-3.8 2.1-5.4.4 1.6 1.4 2.3 2.4 2.3-.2-2.3.4-4.6 1-6.1z" />
    </Svg>
  ),
  clock: (p) => (
    <Svg {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </Svg>
  ),
  check: (p) => (
    <Svg {...p}>
      <path d="M4 12.5l5 5L20 6.5" />
    </Svg>
  ),
  alert: (p) => (
    <Svg {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v5M12 16.5v.01" />
    </Svg>
  ),
  camera: (p) => (
    <Svg {...p}>
      <path d="M4 8h3l2-3h6l2 3h3v12H4z" />
      <circle cx="12" cy="13" r="3.2" />
    </Svg>
  ),
  ruler: (p) => (
    <Svg {...p}>
      <path d="M3 15L15 3l6 6L9 21z" />
      <path d="M7.5 13.5l1.8 1.8M10.5 10.5l1.8 1.8M13.5 7.5l1.8 1.8" />
    </Svg>
  ),
  heart: (p) => (
    <Svg {...p}>
      <path d="M12 20s-7.5-4.6-9.3-9A5.2 5.2 0 0 1 12 6.4 5.2 5.2 0 0 1 21.3 11c-1.8 4.4-9.3 9-9.3 9z" />
    </Svg>
  ),
  doc: (p) => (
    <Svg {...p}>
      <path d="M6 2h9l5 5v15H6z" />
      <path d="M14 2v6h6M9 13h6M9 17h6" />
    </Svg>
  ),
  sync: (p) => (
    <Svg {...p}>
      <path d="M21 12a9 9 0 1 1-2.6-6.3M21 4v5h-5" />
    </Svg>
  ),
  arrow: (p) => (
    <Svg {...p}>
      <path d="M9 6l6 6-6 6" />
    </Svg>
  ),
  back: (p) => (
    <Svg {...p}>
      <path d="M15 6l-6 6 6 6" />
    </Svg>
  ),
  sparkle: (p) => (
    <Svg {...p}>
      <path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4z" />
    </Svg>
  ),
  user: (p) => (
    <Svg {...p}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c1.5-3.5 4.5-5 8-5s6.5 1.5 8 5" />
    </Svg>
  ),
  key: (p) => (
    <Svg {...p}>
      <circle cx="8" cy="15" r="4.5" />
      <path d="M11.5 11.5L20 3M16 7l3 3M13 10l2 2" />
    </Svg>
  ),
  moon: (p) => (
    <Svg {...p}>
      <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4 7 7 0 0 0 20 14.5z" />
    </Svg>
  ),
}

export default function Icon({ name, size = 18, strokeWidth = 2, className = '' }) {
  const Cmp = ICONS[name]
  if (!Cmp) return null
  return <Cmp size={size} strokeWidth={strokeWidth} className={className} />
}
