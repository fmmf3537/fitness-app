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
    <div className="flex min-h-dvh items-center justify-center bg-gray-50 px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-lg bg-white p-6 shadow"
      >
        <h1 className="mb-6 text-center text-xl font-bold text-gray-900">健身看板登录</h1>
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
    </div>
  )
}
