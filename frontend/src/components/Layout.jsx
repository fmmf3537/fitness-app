import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api, clearToken } from '../api/client'

export default function Layout() {
  const navigate = useNavigate()
  const [pendingCount, setPendingCount] = useState(0)

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

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-gray-900">健身看板</span>
            <nav className="ml-4 flex gap-1">
              <NavLink to="/" end className={linkClass}>
                训练日历
              </NavLink>
              <NavLink to="/candidates" className={linkClass}>
                待确认队列
                {pendingCount > 0 && (
                  <span
                    data-testid="pending-badge"
                    className="ml-1 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-orange-500 px-1 text-xs text-white"
                  >
                    {pendingCount}
                  </span>
                )}
              </NavLink>
              <NavLink to="/ai-reports" className={linkClass}>
                AI 报告
              </NavLink>
              <NavLink to="/reviews" className={linkClass}>
                复盘中心
              </NavLink>
              <NavLink to="/trends" className={linkClass}>
                趋势
              </NavLink>
              <NavLink to="/body-metrics" className={linkClass}>
                身体数据
              </NavLink>
              <NavLink to="/backfill" className={linkClass}>
                导入
              </NavLink>
              <NavLink to="/screenshot-import" className={linkClass}>
                截图补录
              </NavLink>
              <NavLink to="/settings" className={linkClass}>
                设置
              </NavLink>
            </nav>
          </div>
          <button
            onClick={handleLogout}
            className="rounded-md px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-200"
          >
            退出登录
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
