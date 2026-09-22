import { NavLink } from 'react-router-dom'
import useIsMobile from '../hooks/useIsMobile'

/** lucide 风格线条图标（内联 SVG，不引新依赖） */
function Icon({ children }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

const CalendarIcon = () => (
  <Icon>
    <rect x="3" y="4" width="18" height="18" rx="2" />
    <line x1="16" y1="2" x2="16" y2="6" />
    <line x1="8" y1="2" x2="8" y2="6" />
    <line x1="3" y1="10" x2="21" y2="10" />
  </Icon>
)

const PlansIcon = () => (
  <Icon>
    <rect x="8" y="2" width="8" height="4" rx="1" />
    <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
    <path d="M12 11h4" />
    <path d="M12 16h4" />
    <path d="M8 11h.01" />
    <path d="M8 16h.01" />
  </Icon>
)

const TrendIcon = () => (
  <Icon>
    <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
    <polyline points="16 7 22 7 22 13" />
  </Icon>
)

const UserIcon = () => (
  <Icon>
    <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
    <circle cx="12" cy="7" r="4" />
  </Icon>
)

const ChatIcon = () => (
  <Icon>
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </Icon>
)

// UIX-06：底部 5 Tab — 日历 / 计划 / 趋势 / 教练 / 设置
const TABS = [
  { to: '/', label: '日历', end: true, Icon: CalendarIcon },
  { to: '/plans', label: '计划', Icon: PlansIcon },
  { to: '/trends', label: '趋势', Icon: TrendIcon },
  { to: '/coach', label: '教练', Icon: ChatIcon },
  { to: '/settings', label: '设置', Icon: UserIcon },
]

/**
 * 移动端底部 Tab 栏（仅 <md 渲染）。
 * UIX-11：激活项 = 品牌紫文字 + 淡紫图标底 + 圆点指示。
 */
export default function BottomTabs() {
  const isMobile = useIsMobile()
  if (!isMobile) return null

  return (
    <nav
      data-testid="bottom-tabs"
      className="fixed inset-x-0 bottom-0 z-40 flex border-t border-line bg-white/95 pb-[env(safe-area-inset-bottom)] shadow-[0_-8px_24px_rgba(46,49,90,0.06)] backdrop-blur-xl dark:border-gray-700 dark:bg-gray-900/95"
    >
      {TABS.map(({ to, label, end, Icon: TabIcon }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            `flex min-h-[56px] flex-1 flex-col items-center justify-center gap-0.5 py-1.5 text-[11px] font-semibold ${
              isActive ? 'text-brand-700 dark:text-brand-300' : 'text-ink-400 dark:text-gray-500'
            }`
          }
        >
          {({ isActive }) => (
            <>
              <span
                className={`flex h-[30px] w-[30px] items-center justify-center rounded-[10px] transition ${
                  isActive ? 'bg-brand-100 dark:bg-brand-900/50' : ''
                }`}
              >
                <TabIcon />
              </span>
              <span>{label}</span>
              <span
                aria-hidden="true"
                className={`h-1 w-1 rounded-full ${isActive ? 'bg-brand-600 dark:bg-brand-400' : 'bg-transparent'}`}
              />
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}
