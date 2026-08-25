import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useCurrentUser } from '../contexts/CurrentUserContext'

const GARMIN_COLORS = {
  ok: 'bg-green-100 text-green-800',
  expired: 'bg-yellow-100 text-yellow-800',
  missing: 'bg-red-100 text-red-800',
  'n/a': 'bg-gray-100 text-gray-600',
}

function formatBytes(n) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export default function AdminHealthPage() {
  const currentUser = useCurrentUser()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!currentUser?.isAdmin) {
      setLoading(false)
      return
    }
    api('/api/admin/health')
      .then(setData)
      .catch((err) => {
        if (err.status === 403) setError('无权访问')
        else setError(err.message || '加载失败')
      })
      .finally(() => setLoading(false))
  }, [currentUser])

  if (!currentUser?.isAdmin) {
    return (
      <div data-testid="admin-forbidden" className="rounded-lg border border-red-200 bg-red-50 p-6 text-red-700">
        403 — 需要管理员权限
      </div>
    )
  }

  if (loading) return <p className="text-sm text-gray-500">加载中…</p>
  if (error) return <p role="alert" className="text-sm text-red-600">{error}</p>
  if (!data) return null

  const sys = data.system || {}

  return (
    <div className="space-y-4" data-testid="admin-health-page">
      <h1 className="text-xl font-bold text-gray-900">健康面板</h1>

      <section className="grid gap-3 sm:grid-cols-3" data-testid="system-cards">
        <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <p className="text-xs text-gray-500">数据库大小</p>
          <p data-testid="db-size" className="text-lg font-semibold text-gray-900">
            {formatBytes(sys.db_size_bytes)}
          </p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <p className="text-xs text-gray-500">最近备份</p>
          <p className="text-sm font-medium text-gray-900">{sys.last_backup_at || '—'}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <p className="text-xs text-gray-500">调度器</p>
          <p className="text-sm font-medium text-gray-900">
            {sys.scheduler_running ? '运行中' : '已停止'}
          </p>
        </div>
      </section>

      <section className="grid gap-3 sm:grid-cols-2" data-testid="user-health-grid">
        {(data.users || []).map((u) => (
          <div
            key={u.user_id}
            data-testid={`user-health-${u.user_id}`}
            className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="font-medium text-gray-900">{u.username}</span>
              <span className={`rounded-full px-2 py-0.5 text-xs ${GARMIN_COLORS[u.garmin_token_state] || GARMIN_COLORS['n/a']}`}>
                佳明 {u.garmin_token_state}
              </span>
            </div>
            <dl className="space-y-1 text-xs text-gray-600">
              <div>状态：{u.is_active ? '活跃' : '停用'}</div>
              <div>最近同步：{u.last_sync_at || '—'}</div>
              <div>本月 LLM 费用：¥{(u.monthly_llm_cost ?? 0).toFixed(4)}</div>
              <div>待确认匹配：{u.pending_match_count ?? 0}</div>
            </dl>
          </div>
        ))}
      </section>
    </div>
  )
}
