import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'

export default function SettingsPage() {
  const [settings, setSettings] = useState(null)
  const [usage, setUsage] = useState(null)
  const [keyInputs, setKeyInputs] = useState({})
  const [defaultFlags, setDefaultFlags] = useState({})
  const [saving, setSaving] = useState({})
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [deleted, setDeleted] = useState([])

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

  useEffect(() => {
    setError('')
    loadSettings()
    api('/api/settings/llm/usage')
      .then((data) => setUsage(data))
      .catch((err) => setError(err.status === 401 ? '未登录' : err.message))
    loadDeleted()
  }, [loadSettings, loadDeleted])

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

      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
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
          <button
            onClick={() => handleSwitchDefault(settings.suggested_fallback)}
            data-testid="fallback-switch-btn"
            className="rounded-md bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700"
          >
            切换到 {settings.suggested_fallback} 并重试
          </button>
        </div>
      )}

      <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-sm font-medium text-gray-900">LLM Key 配置</h2>
        {!settings && !error && <p className="text-sm text-gray-500">加载中…</p>}
        <div className="space-y-3">
          {(settings?.providers || []).map((p) => (
            <div
              key={p.name}
              data-testid={`llm-provider-${p.name}`}
              className="rounded-md border border-gray-200 p-3"
            >
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-medium text-gray-900">{p.name}</span>
                <span className="text-xs text-gray-500">{p.default_model}</span>
                {p.has_key ? (
                  <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-700">
                    已配置
                  </span>
                ) : (
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
                    未配置
                  </span>
                )}
                {settings.default_llm === p.name && (
                  <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs text-indigo-700">
                    默认
                  </span>
                )}
                {p.has_key && settings.default_llm !== p.name && (
                  <button
                    onClick={() => handleSwitchDefault(p.name)}
                    data-testid={`quick-default-${p.name}`}
                    className="rounded-md border border-indigo-300 px-2 py-0.5 text-xs text-indigo-700 hover:bg-indigo-50"
                  >
                    设为默认
                  </button>
                )}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <input
                  type="password"
                  placeholder="输入新的 API Key"
                  value={keyInputs[p.name] || ''}
                  onChange={(e) =>
                    setKeyInputs((s) => ({ ...s, [p.name]: e.target.value }))
                  }
                  data-testid={`key-input-${p.name}`}
                  className="w-64 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
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
                <button
                  onClick={() => handleSave(p.name)}
                  disabled={saving[p.name] || !(keyInputs[p.name] || '').trim()}
                  data-testid={`save-key-${p.name}`}
                  className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {saving[p.name] ? '保存中…' : '保存'}
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section
        data-testid="llm-usage"
        className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      >
        <h2 className="mb-3 text-sm font-medium text-gray-900">
          本月用量{usage?.month ? `（${usage.month}）` : ''}
        </h2>
        {!usage && !error && <p className="text-sm text-gray-500">加载中…</p>}
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
                <tr className="border-b border-gray-200 text-gray-500">
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
      </section>

      <section data-testid="deleted-workouts">
        <h2 className="mb-2 text-lg font-semibold text-gray-900">已删除的训练</h2>
        {deleted.length === 0 ? (
          <p className="text-sm text-gray-500">暂无已删除的训练</p>
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
                <button
                  data-testid={`restore-workout-${w.id}`}
                  onClick={() => handleRestore(w.id)}
                  className="rounded-md bg-indigo-600 px-3 py-1 text-white hover:bg-indigo-500"
                >
                  恢复
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
