import { useCallback, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { clearToken } from '../api/client'
import useIsMobile from '../hooks/useIsMobile'
import useAndroidBackButton from '../hooks/useAndroidBackButton'
import useNativeStatusBar from '../hooks/useNativeStatusBar'
import BottomTabs from './BottomTabs'
import { ToastProvider } from './ui/Toast'
import SyncTaskProvider from './SyncTaskProvider'
import CandidateQueueProvider from './CandidateQueueProvider'
import { useCandidateQueue } from './useCandidateQueue'
import Onboarding from './Onboarding'
import PageErrorBoundary from './PageErrorBoundary'
import NetworkStatus from './NetworkStatus'

// UIX-06：桌面导航 13→8；导入/身体数据/教练须知撤入「我的」或汉堡
const NAV_LINKS = [
  { to: '/', label: '训练日历', end: true },
  { to: '/candidates', label: '待确认队列', badge: true },
  { to: '/plans', label: '训练计划' },
  { to: '/reviews', label: '复盘中心' },
  { to: '/ai-reports', label: 'AI 报告' },
  { to: '/trends', label: '趋势' },
  { to: '/goals', label: '目标' },
  { to: '/coach', label: '教练' },
  { to: '/settings', label: '我的' },
]

// 移动端汉堡：次级入口；主入口由 BottomTabs 承载
const SECONDARY_LINKS = [
  { to: '/candidates', label: '待确认队列', badge: true },
  { to: '/reviews', label: '复盘中心' },
  { to: '/ai-reports', label: 'AI 报告' },
  { to: '/body-metrics', label: '身体数据' },
  { to: '/goals', label: '训练目标' },
  { to: '/import', label: '数据导入' },
]

export default function Layout() {
  return (
    <ToastProvider>
      <SyncTaskProvider>
        <CandidateQueueProvider>
          <LayoutContent />
        </CandidateQueueProvider>
      </SyncTaskProvider>
    </ToastProvider>
  )
}

function LayoutContent() {
  const navigate = useNavigate()
  const location = useLocation()
  const isMobile = useIsMobile()
  const { pendingCount } = useCandidateQueue()
  const [menuOpen, setMenuOpen] = useState(false)

  // UIX-11：已迁移 PageHeader 渐变页头的路由，移动端隐藏全局白色页头，避免双层页头
  const HEADERLESS_MOBILE = new Set(['/', '/trends', '/body-metrics', '/reviews', '/plans', '/coach', '/settings', '/workouts'])
  const hasPageHeader = HEADERLESS_MOBILE.has(location.pathname)

  const closeMenu = useCallback(() => setMenuOpen(false), [])
  useAndroidBackButton({ isOverlayOpen: menuOpen, closeOverlay: closeMenu })
  useNativeStatusBar()

  const handleLogout = () => {
    clearToken()
    navigate('/login', { replace: true })
  }

  const linkClass = ({ isActive }) =>
    `px-3 py-2 rounded-md text-sm font-medium ${
      isActive ? 'bg-indigo-600 text-white' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
    }`

  const mobileLinkClass = ({ isActive }) => `block ${linkClass({ isActive })}`

  const renderBadge = (link) =>
    link.badge && pendingCount > 0 ? (
      <span
        data-testid="pending-badge"
        className="ml-1 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-orange-500 px-1 text-xs text-white"
      >
        {pendingCount}
      </span>
    ) : null

  return (
    <div className="min-h-screen bg-[#f5f7fb] dark:bg-gray-950 md:bg-gradient-to-b md:from-gray-50 md:to-gray-100/60 md:dark:from-gray-950 md:dark:to-black">
      <a href="#main-content" className="sr-only z-50 rounded-md bg-white px-4 py-2 text-sm font-semibold text-indigo-700 shadow focus:not-sr-only focus:fixed focus:left-4 focus:top-4">
        跳到主要内容
      </a>
      <header className={`sticky top-0 z-40 border-b border-white/70 bg-white/90 shadow-sm backdrop-blur-xl dark:border-gray-800 dark:bg-gray-900/90 pt-[env(safe-area-inset-top)] ${hasPageHeader ? 'max-md:hidden' : ''}`}>
        <div className="mx-auto flex max-w-6xl items-center justify-between px-3 py-2.5 md:px-4 md:py-3">
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-2 text-lg font-black tracking-tight text-gray-950 dark:text-white"><span className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-brand text-sm text-white shadow-glow max-md:hidden">F</span>健身看板</span>
            {!isMobile && (
              <nav className="ml-4 flex gap-1">
                {NAV_LINKS.map((link) => (
                  <NavLink key={link.to} to={link.to} end={link.end} className={linkClass}>
                    {link.label}
                    {renderBadge(link)}
                  </NavLink>
                ))}
              </nav>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleLogout}
              className="rounded-md px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 max-md:hidden"
            >
              退出登录
            </button>
            {isMobile && (
              <button
                type="button"
                data-testid="nav-toggle"
                aria-label="菜单"
                aria-expanded={menuOpen}
                onClick={() => setMenuOpen((open) => !open)}
                className="rounded-md px-3 py-2 text-lg leading-none text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
              >
                ☰
              </button>
            )}
          </div>
        </div>
        {isMobile && menuOpen && (
          <nav data-testid="mobile-nav" className="border-t border-gray-100 dark:border-gray-800 px-4 py-2">
            <div className="mx-auto flex max-w-5xl flex-col gap-1">
              {SECONDARY_LINKS.map((link) => (
                <NavLink
                  key={link.to}
                  to={link.to}
                  end={link.end}
                  className={mobileLinkClass}
                  onClick={() => setMenuOpen(false)}
                >
                  {link.label}
                  {renderBadge(link)}
                </NavLink>
              ))}
            </div>
          </nav>
        )}
      </header>
      <NetworkStatus />
      <main id="main-content" tabIndex={-1} className="mx-auto max-w-6xl px-4 py-6 max-md:px-3 max-md:py-4 max-md:pb-28">
        <PageErrorBoundary>
          <Outlet />
        </PageErrorBoundary>
      </main>
      <BottomTabs />
      <Onboarding />
    </div>
  )
}
