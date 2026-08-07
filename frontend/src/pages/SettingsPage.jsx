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

  const loadSettings = useCallback(() => {
    return api('/api/settings/llm')
      .then((data) => setSettings(data))
      .catch((err) => setError(err.status === 401 ? '未登录' : err.message))
  }, [])

  useEffect(() => {
    setError('')
    loadSettings()
    api('/api/settings/llm/usage')
      .then((data) => setUsage(data))
      .catch((err) => setError(err.status === 401 ? '未登录' : err.message))
  }, [loadSettings])

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
            <table className="w-full text-left text-xs text-gray-600">
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
        )}
      </section>
    </div>
  )
}
