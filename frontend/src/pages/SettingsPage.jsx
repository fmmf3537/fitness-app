import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import Skeleton from '../components/ui/Skeleton'

export default function SettingsPage() {
  const [settings, setSettings] = useState(null)
  const [usage, setUsage] = useState(null)
  const [keyInputs, setKeyInputs] = useState({})
  const [defaultFlags, setDefaultFlags] = useState({})
  const [saving, setSaving] = useState({})
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [deleted, setDeleted] = useState([])

  // V4-4：个人资料（性别 + 出生日期，皮脂钳公式所需）
  const [profileGender, setProfileGender] = useState('')
  const [profileBirthDate, setProfileBirthDate] = useState('')
  const [profileSaving, setProfileSaving] = useState(false)
  const [profileLoadError, setProfileLoadError] = useState('')

  const loadSettings = useCallback(() => {
    return api('/api/settings/llm')
      .then((data) => setSettings(data))
      .catch((err) => setError(err.status === 401 ? '未登录' : err.message))
  }, [])

  // V3-11：已删除训练列表（加载失败静默置空，不干扰设置主流程）
  const loadDeleted = useCallback(() => {
    return api('/api/workouts/deleted')
      .then((data) => setDeleted(data.workouts || []))
      .catch(() => setDeleted([]))
  }, [])

  const loadProfile = useCallback(() => {
    return api('/api/settings/profile')
      .then((data) => {
        setProfileGender(data.gender || '')
        setProfileBirthDate(data.birth_date || '')
      })
      .catch((err) => setProfileLoadError(err.status === 401 ? '未登录' : err.message))
  }, [])

  useEffect(() => {
    setError('')
    loadSettings()
    api('/api/settings/llm/usage')
      .then((data) => setUsage(data))
      .catch((err) => setError(err.status === 401 ? '未登录' : err.message))
    loadDeleted()
    loadProfile()
  }, [loadSettings, loadDeleted, loadProfile])

  const handleRestore = (id) => {
    setError('')
    setMessage('')
    api(`/api/workouts/${id}/restore`, { method: 'POST' })
      .then(() => {
        setMessage('已恢复，可在日历中查看')
        loadDeleted()
      })
      .catch((err) => setError(err.status === 401 ? '未登录' : err.detail || err.message))
  }

  // V2-1：仅切换默认模型（不重传 Key）
  const handleSwitchDefault = (name) => {
    setError('')
    setMessage('')
    api('/api/settings/llm', {
      method: 'PUT',
      body: JSON.stringify({ provider: name, api_key: '', set_default: true }),
    })
      .then(() => {
        setMessage(`已切换默认模型为 ${name}`)
        loadSettings()
      })
      .catch((err) => setError(err.status === 401 ? '未登录' : err.message))
  }

  // V4-4：保存个人资料（性别 + 出生日期）；PATCH 语义一起传
  const handleSaveProfile = () => {
    setProfileSaving(true)
    setError('')
    setMessage('')
    const payload = {}
    if (profileGender) payload.gender = profileGender
    if (profileBirthDate) payload.birth_date = profileBirthDate
    api('/api/settings/profile', {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
      .then((data) => {
        setProfileGender(data.gender || '')
        setProfileBirthDate(data.birth_date || '')
        setMessage('个人资料已保存')
      })
      .catch((err) => setError(err.status === 401 ? '未登录' : err.detail || err.message))
      .finally(() => setProfileSaving(false))
  }

  const handleSave = (name) => {
    const apiKey = (keyInputs[name] || '').trim()
    if (!apiKey) return
    setSaving((s) => ({ ...s, [name]: true }))
    setError('')
    setMessage('')
    api('/api/settings/llm', {
      method: 'PUT',
      body: JSON.stringify({
        provider: name,
        api_key: apiKey,
        set_default: Boolean(defaultFlags[name]),
      }),
    })
      .then(() => {
        setMessage(`provider ${name} 保存成功`)
        setKeyInputs((s) => ({ ...s, [name]: '' }))
        loadSettings()
      })
      .catch((err) => setError(err.status === 401 ? '未登录' : err.message))
      .finally(() => setSaving((s) => ({ ...s, [name]: false })))
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-gray-900">设置</h1>

      {error && (
        <ErrorState message={error} onRetry={loadSettings} testId="settings-error" />
      )}
      {message && <p className="text-sm text-green-600">{message}</p>}

      {settings?.suggested_fallback && (
        <div
          data-testid="llm-fallback-banner"
          className="flex flex-wrap items-center gap-3 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800"
        >
          <span>
            默认模型 {settings.default_llm} 已连续失败 2 次，可一键切换备用模型（
            {settings.suggested_fallback}）重试。
          </span>
          <Button
            variant="secondary"
            onClick={() => handleSwitchDefault(settings.suggested_fallback)}
            testId="fallback-switch-btn"
          >
            切换到 {settings.suggested_fallback} 并重试
          </Button>
        </div>
      )}

      <Card testId="profile-section">
        <h2 className="mb-1 text-sm font-medium text-gray-900">个人资料</h2>
        <p className="mb-3 text-xs text-gray-600">
          性别与出生日期用于皮脂钳体脂率等公式计算，录入一次即可
        </p>
        {profileLoadError && (
          <p data-testid="profile-load-error" className="mb-2 text-xs text-red-600">{profileLoadError}</p>
        )}
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <label className="text-gray-700">
            性别
            <select
              data-testid="profile-gender"
              value={profileGender}
              onChange={(e) => setProfileGender(e.target.value)}
              className="ml-2 rounded-md border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-100"
            >
              <option value="">未设置</option>
              <option value="male">男</option>
              <option value="female">女</option>
            </select>
          </label>
          <label className="text-gray-700">
            出生日期
            <input
              type="date"
              data-testid="profile-birth-date"
              value={profileBirthDate}
              onChange={(e) => setProfileBirthDate(e.target.value)}
              className="ml-2 rounded-md border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-100"
            />
          </label>
          <Button
            variant="primary"
            onClick={handleSaveProfile}
            disabled={profileSaving || !profileGender || !profileBirthDate}
            testId="profile-save"
          >
            {profileSaving ? '保存中…' : '保存'}
          </Button>
        </div>
      </Card>

      <Card>
        <h2 className="mb-3 text-sm font-medium text-gray-900">LLM Key 配置</h2>
        {!settings && !error && <Skeleton className="h-20" />}
        <div className="space-y-3">
          {(settings?.providers || []).map((p) => (
            <div
              key={p.name}
              data-testid={`llm-provider-${p.name}`}
              className="rounded-md border border-gray-200 p-3"
            >
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-medium text-gray-900">{p.name}</span>
                <span className="text-xs text-gray-600">{p.default_model}</span>
                {p.has_key ? (
                  <Badge variant="green">已配置</Badge>
                ) : (
                  <Badge variant="gray">未配置</Badge>
                )}
                {settings.default_llm === p.name && (
                  <Badge variant="indigo">默认</Badge>
                )}
                {p.has_key && settings.default_llm !== p.name && (
                  <Button
                    variant="ghost"
                    onClick={() => handleSwitchDefault(p.name)}
                    testId={`quick-default-${p.name}`}
                    className="text-xs"
                  >
                    设为默认
                  </Button>
                )}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <label htmlFor={`api-key-input-${p.name}`} className="text-sm text-gray-700">
                  API Key
                </label>
                <input
                  id={`api-key-input-${p.name}`}
                  type="password"
                  placeholder="输入新的 API Key"
                  value={keyInputs[p.name] || ''}
                  onChange={(e) =>
                    setKeyInputs((s) => ({ ...s, [p.name]: e.target.value }))
                  }
                  data-testid={`key-input-${p.name}`}
                  className="w-64 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100"
                />
                <label className="flex items-center gap-1 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={Boolean(defaultFlags[p.name])}
                    onChange={(e) =>
                      setDefaultFlags((s) => ({ ...s, [p.name]: e.target.checked }))
                    }
                    data-testid={`set-default-${p.name}`}
                  />
                  设为默认
                </label>
                <Button
                  variant="primary"
                  onClick={() => handleSave(p.name)}
                  disabled={saving[p.name] || !(keyInputs[p.name] || '').trim()}
                  testId={`save-key-${p.name}`}
                >
                  {saving[p.name] ? '保存中…' : '保存'}
                </Button>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card testId="llm-usage">
        <h2 className="mb-3 text-sm font-medium text-gray-900">
          本月用量{usage?.month ? `（${usage.month}）` : ''}
        </h2>
        {!usage && !error && <Skeleton className="h-16" />}
        {usage && (
          <div className="space-y-3 text-sm">
            <div className="flex gap-6">
              <p data-testid="usage-total-calls" className="text-gray-700">
                总调用：<span className="font-medium text-gray-900">{usage.total_calls}</span> 次
              </p>
              <p data-testid="usage-total-cost" className="text-gray-700">
                总费用：
                <span className="font-medium text-gray-900">¥{usage.total_cost.toFixed(4)}</span>
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs whitespace-nowrap text-gray-600">
              <thead>
                <tr className="border-b border-gray-200 text-gray-600">
                  <th className="py-1 pr-2 font-medium">Provider</th>
                  <th className="py-1 pr-2 font-medium">模型</th>
                  <th className="py-1 pr-2 font-medium">调用</th>
                  <th className="py-1 pr-2 font-medium">tokens</th>
                  <th className="py-1 font-medium">费用</th>
                </tr>
              </thead>
              <tbody>
                {(usage.by_provider || []).map((row) => (
                  <tr key={row.provider} className="border-b border-gray-100">
                    <td className="py-1 pr-2">{row.provider}</td>
                    <td className="py-1 pr-2">{row.model}</td>
                    <td className="py-1 pr-2">{row.calls}</td>
                    <td className="py-1 pr-2">
                      {row.prompt_tokens}+{row.completion_tokens}
                    </td>
                    <td className="py-1">¥{row.cost.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
              </table>
            </div>
          </div>
        )}
      </Card>

      <section data-testid="deleted-workouts">
        <h2 className="mb-2 text-lg font-semibold text-gray-900">已删除的训练</h2>
        {deleted.length === 0 ? (
          <EmptyState title="暂无已删除的训练" description="删除的训练会出现在这里，可随时恢复" />
        ) : (
          <ul className="space-y-2">
            {deleted.map((w) => (
              <li
                key={w.id}
                data-testid={`deleted-workout-${w.id}`}
                className="flex items-center justify-between rounded-md border border-gray-200 bg-white p-3 text-sm"
              >
                <span className="text-gray-700">
                  {w.date} · {w.title || '未命名训练'}
                </span>
                <Button
                  variant="secondary"
                  testId={`restore-workout-${w.id}`}
                  onClick={() => handleRestore(w.id)}
                >
                  恢复
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
