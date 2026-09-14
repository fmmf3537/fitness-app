import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { login, setToken } from '../api/client'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const data = await login(password)
      setToken(data.token)
      // 深链接回跳：RequireAuth state > 401 拦截 sessionStorage > 首页
      const from = location.state?.from
      let target = '/'
      if (from?.pathname) {
        target = from.pathname + (from.search || '')
      } else {
        try {
          const stored = sessionStorage.getItem('fh_auth_from')
          if (stored) {
            sessionStorage.removeItem('fh_auth_from')
            target = stored
          }
        } catch {
          // sessionStorage 不可用时静默回首页
        }
      }
      navigate(target, { replace: true })
    } catch (err) {
      setError(err.status === 401 ? '口令错误' : '登录失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-dvh flex-col bg-gradient-to-b from-indigo-600 via-indigo-700 to-indigo-900">
      {/* 品牌区 */}
      <div className="flex flex-1 flex-col items-center justify-center px-8">
        <div className="flex h-20 w-20 items-center justify-center rounded-3xl bg-white/15 shadow-lg backdrop-blur">
          <svg
            width="44"
            height="44"
            viewBox="0 0 24 24"
            fill="none"
            stroke="white"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M6.5 6.5 17.5 17.5" />
            <path d="m4 8 4-4" />
            <path d="m16 20 4-4" />
            <rect
              x="1.5"
              y="8.5"
              width="5"
              height="7"
              rx="1.5"
              transform="rotate(-45 4 12)"
            />
            <rect
              x="17.5"
              y="8.5"
              width="5"
              height="7"
              rx="1.5"
              transform="rotate(-45 20 12)"
            />
          </svg>
        </div>
        <h1 className="mt-5 text-3xl font-bold tracking-wide text-white">健身看板</h1>
        <p className="mt-2 text-sm text-indigo-200">训练数据整合 · AI 教练点评 · 趋势洞察</p>
      </div>

      {/* 登录卡片 */}
      <div className="rounded-t-3xl bg-white px-6 pb-[max(2rem,env(safe-area-inset-bottom))] pt-8 shadow-2xl">
        <h2 className="text-lg font-bold text-gray-900">登录</h2>
        <p className="mt-1 text-sm text-gray-600">输入访问口令继续</p>

        <form onSubmit={handleSubmit} className="mt-6">
          <label htmlFor="password" className="mb-1 block text-sm font-medium text-gray-700">
            口令
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mb-4 w-full min-h-[44px] rounded-md border border-gray-300 px-3 py-2 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 focus:outline-none"
            placeholder="请输入访问口令"
            required
          />
          {error && (
            <p role="alert" className="mb-4 text-sm text-red-600">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full min-h-[44px] rounded-md bg-indigo-600 text-sm font-medium text-white hover:bg-indigo-700 active:bg-indigo-800 disabled:opacity-50"
          >
            {loading ? '登录中…' : '登录'}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-gray-600">
          登录后自动返回你之前打开的页面
        </p>
      </div>
    </div>
  )
}
