import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { useCurrentUser } from '../contexts/CurrentUserContext'

function formatBindings(b) {
  if (!b) return '—'
  const parts = []
  if (b.garmin) parts.push('佳明')
  if (b.xunji) parts.push('训记')
  if (b.llm) parts.push('LLM')
  return parts.length ? parts.join(' / ') : '无'
}

export default function AdminUsersPage() {
  const currentUser = useCurrentUser()
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [form, setForm] = useState({ username: '', password: '', role: 'user' })
  const [creating, setCreating] = useState(false)

  const loadUsers = useCallback(() => {
    setLoading(true)
    setError('')
    return api('/api/admin/users')
      .then((data) => setUsers(Array.isArray(data) ? data : []))
      .catch((err) => {
        if (err.status === 403) setError('无权访问')
        else if (err.status === 401) setError('请重新登录')
        else setError(err.message || '加载失败')
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (currentUser?.isAdmin) loadUsers()
    else setLoading(false)
  }, [currentUser, loadUsers])

  if (!currentUser?.isAdmin) {
    return (
      <div data-testid="admin-forbidden" className="rounded-lg border border-red-200 bg-red-50 p-6 text-red-700">
        403 — 需要管理员权限
      </div>
    )
  }

  const handleCreate = async (e) => {
    e.preventDefault()
    setCreating(true)
    setError('')
    setMessage('')
    try {
      await api('/api/admin/users', {
        method: 'POST',
        body: JSON.stringify(form),
      })
      setMessage('用户创建成功')
      setForm({ username: '', password: '', role: 'user' })
      await loadUsers()
    } catch (err) {
      if (err.status === 409) setError('用户名重复')
      else setError(err.message || '创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleDeactivate = async (id) => {
    setError('')
    try {
      await api(`/api/admin/users/${id}/deactivate`, { method: 'PUT' })
      setMessage('已停用')
      await loadUsers()
    } catch (err) {
      setError(err.message || '操作失败')
    }
  }

  const handleActivate = async (id) => {
    setError('')
    try {
      await api(`/api/admin/users/${id}/activate`, { method: 'PUT' })
      setMessage('已激活')
      await loadUsers()
    } catch (err) {
      setError(err.message || '操作失败')
    }
  }

  const handleResetPassword = async (id) => {
    const pwd = window.prompt('输入新密码（至少 6 位）')
    if (!pwd) return
    setError('')
    try {
      await api(`/api/admin/users/${id}/reset-password`, {
        method: 'PUT',
        body: JSON.stringify({ new_password: pwd }),
      })
      setMessage('密码已重置')
    } catch (err) {
      setError(err.message || '重置失败')
    }
  }

  return (
    <div className="space-y-4" data-testid="admin-users-page">
      <h1 className="text-xl font-bold text-gray-900">用户管理</h1>
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      {message && <p className="text-sm text-green-600">{message}</p>}

      <form onSubmit={handleCreate} className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-sm font-medium text-gray-900">创建用户</h2>
        <div className="flex flex-wrap gap-2">
          <input
            data-testid="create-username"
            placeholder="用户名"
            value={form.username}
            onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm"
            required
          />
          <input
            data-testid="create-password"
            type="password"
            placeholder="密码"
            value={form.password}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm"
            required
          />
          <select
            data-testid="create-role"
            value={form.role}
            onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm"
          >
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
          <button
            type="submit"
            data-testid="create-submit"
            disabled={creating}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {creating ? '创建中…' : '创建'}
          </button>
        </div>
      </form>

      {loading ? (
        <p className="text-sm text-gray-500">加载中…</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
          <table className="w-full text-left text-sm" data-testid="users-table">
            <thead className="border-b border-gray-200 bg-gray-50 text-gray-600">
              <tr>
                <th className="px-3 py-2">ID</th>
                <th className="px-3 py-2">用户名</th>
                <th className="px-3 py-2">角色</th>
                <th className="px-3 py-2">状态</th>
                <th className="px-3 py-2">绑定</th>
                <th className="px-3 py-2">操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} data-testid={`user-row-${u.id}`} className="border-b border-gray-100">
                  <td className="px-3 py-2">{u.id}</td>
                  <td className="px-3 py-2">{u.username}</td>
                  <td className="px-3 py-2">{u.role}</td>
                  <td className="px-3 py-2">{u.is_active ? '活跃' : '停用'}</td>
                  <td className="px-3 py-2">{formatBindings(u.bindings)}</td>
                  <td className="px-3 py-2 space-x-1">
                    {u.is_active ? (
                      <button
                        type="button"
                        data-testid={`deactivate-${u.id}`}
                        onClick={() => handleDeactivate(u.id)}
                        className="text-xs text-red-600 hover:underline"
                      >
                        停用
                      </button>
                    ) : (
                      <button
                        type="button"
                        data-testid={`activate-${u.id}`}
                        onClick={() => handleActivate(u.id)}
                        className="text-xs text-green-600 hover:underline"
                      >
                        激活
                      </button>
                    )}
                    <button
                      type="button"
                      data-testid={`reset-pwd-${u.id}`}
                      onClick={() => handleResetPassword(u.id)}
                      className="text-xs text-indigo-600 hover:underline"
                    >
                      重置密码
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
