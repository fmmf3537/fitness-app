import { useCallback, useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api, clearToken } from '../api/client'
import useIsMobile from '../hooks/useIsMobile'
import useAndroidBackButton from '../hooks/useAndroidBackButton'
import useNativeStatusBar from '../hooks/useNativeStatusBar'
import BottomTabs from './BottomTabs'

const NAV_LINKS = [
  { to: '/', label: '训练日历', end: true },
  { to: '/candidates', label: '待确认队列', badge: true },
  { to: '/plans', label: '训练计划' },
  { to: '/ai-reports', label: 'AI 报告' },
  { to: '/reviews', label: '复盘中心' },
  { to: '/trends', label: '趋势' },
  { to: '/body-metrics', label: '身体数据' },
  { to: '/backfill', label: '导入' },
  { to: '/screenshot-import', label: '截图补录' },
  { to: '/fit-import', label: '文件导入' },
  { to: '/settings', label: '设置' },
]

// 移动端汉堡菜单仅保留次级入口；五个主入口由 BottomTabs 承载
const SECONDARY_LINKS = [
  { to: '/candidates', label: '待确认队列', badge: true },
  { to: '/reviews', label: '复盘中心' },
  { to: '/body-metrics', label: '身体数据' },
  { to: '/screenshot-import', label: '截图导入' },
  { to: '/fit-import', label: '文件导入' },
  { to: '/backfill', label: '历史补录' },
]

export default function Layout() {
  const navigate = useNavigate()
  const isMobile = useIsMobile()
  const [pendingCount, setPendingCount] = useState(0)
  const [menuOpen, setMenuOpen] = useState(false)

  const closeMenu = useCallback(() => setMenuOpen(false), [])
  useAndroidBackButton({ isOverlayOpen: menuOpen, closeOverlay: closeMenu })
  useNativeStatusBar()

  useEffect(() => {
    api('/api/match-candidates')
      .then((data) => {
        const count = (data.candidates || []).filter((c) => c.status === 'pending').length
        setPendingCount(count)
      })
      .catch(() => {})
  }, [])

  const handleLogout = () => {
    clearToken()
    navigate('/login', { replace: true })
  }

  const linkClass = ({ isActive }) =>
    `px-3 py-2 rounded-md text-sm font-medium ${
      isActive ? 'bg-indigo-600 text-white' : 'text-gray-700 hover:bg-gray-200'
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
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm pt-[env(safe-area-inset-top)]">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-gray-900">健身看板</span>
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
              className="rounded-md px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-200"
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
                className="rounded-md px-3 py-2 text-lg leading-none text-gray-700 hover:bg-gray-200"
              >
                ☰
              </button>
            )}
          </div>
        </div>
        {isMobile && menuOpen && (
          <nav data-testid="mobile-nav" className="border-t border-gray-100 px-4 py-2">
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
      <main className="mx-auto max-w-5xl px-4 py-6 max-md:pb-32">
        <Outlet />
      </main>
      <BottomTabs />
    </div>
  )
}
