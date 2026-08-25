import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, setToken } from '../api/client'

export default function LoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (!username.trim() || !password) {
      setError('请输入用户名和密码')
      return
    }
    setLoading(true)
    try {
      // P0-1 修复：登录协议改为 {username, password}，与后端 LoginRequest 对齐
      // (M2-3 / M5-3)
      const data = await login(username.trim(), password)
      setToken(data.token)
      navigate('/', { replace: true })
    } catch (err) {
      setError(
        err.status === 401
          ? '用户名或密码错误'
          : err.status === 422
            ? '请输入用户名和密码'
            : '登录失败，请稍后重试',
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-lg bg-white p-6 shadow"
      >
        <h1 className="mb-6 text-center text-xl font-bold text-gray-900">健身看板登录</h1>
        <label
          htmlFor="username"
          className="mb-1 block text-sm font-medium text-gray-700"
        >
          用户名
        </label>
        <input
          id="username"
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          className="mb-4 w-full rounded-md border border-gray-300 px-3 py-2 focus:border-indigo-500 focus:outline-none"
          placeholder="请输入用户名"
          required
        />
        <label
          htmlFor="password"
          className="mb-1 block text-sm font-medium text-gray-700"
        >
          密码
        </label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          className="mb-4 w-full rounded-md border border-gray-300 px-3 py-2 focus:border-indigo-500 focus:outline-none"
          placeholder="请输入密码"
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
          className="w-full rounded-md bg-indigo-600 py-2 text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading ? '登录中…' : '登录'}
        </button>
      </form>
    </div>
  )
}
