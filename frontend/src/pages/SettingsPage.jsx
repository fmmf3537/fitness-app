import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { useCurrentUser } from '../contexts/CurrentUserContext'

function BindingsSection() {
  const [bindings, setBindings] = useState(null)
  const [localError, setLocalError] = useState('')
  const [message, setMessage] = useState('')

  const load = useCallback(() => {
    return api('/api/settings/bindings')
      .then(setBindings)
      .catch((err) => {
        if (err.status === 401) setLocalError('请重新登录')
        else setBindings({ garmin: { bound: false }, xunji: { bound: false }, llm: { bound: false, providers: [] } })
      })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const unbind = async (type, provider) => {
    setLocalError('')
    setMessage('')
    const url = provider
      ? `/api/settings/bindings/${type}?provider=${provider}`
      : `/api/settings/bindings/${type}`
    try {
      await api(url, { method: 'DELETE' })
      setMessage('已解绑')
      await load()
    } catch (err) {
      setLocalError(err.message || '解绑失败')
    }
  }

  const handleBindClick = () => {
    window.alert('请在 API 调用 bind 端点，UI 暂未实现')
  }

  return (
    <div data-testid="bindings-section">
      {localError && <p className="mb-2 text-sm text-red-600">{localError}</p>}
      {message && <p className="mb-2 text-sm text-green-600">{message}</p>}
      {!bindings && !localError && <p className="text-sm text-gray-500">加载中…</p>}
      {bindings && (
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-md border border-gray-200 p-3" data-testid="binding-garmin">
            <h3 className="font-medium text-gray-900">佳明</h3>
            <p className="text-sm text-gray-600">
              {bindings.garmin?.bound ? '已绑定' : '未绑定'}
              {bindings.garmin?.has_token ? ' · 有 token' : ''}
            </p>
            <div className="mt-2 flex gap-2">
              <button type="button" onClick={handleBindClick} className="text-xs text-indigo-600">绑定</button>
              {bindings.garmin?.bound && (
                <button type="button" onClick={() => unbind('garmin')} className="text-xs text-red-600">解绑</button>
              )}
            </div>
          </div>
          <div className="rounded-md border border-gray-200 p-3" data-testid="binding-xunji">
            <h3 className="font-medium text-gray-900">训记</h3>
            <p className="text-sm text-gray-600">
              {bindings.xunji?.bound ? '已绑定' : '未绑定'}
              {bindings.xunji?.body_bound ? ' · 身体数据已绑' : ''}
            </p>
            <div className="mt-2 flex gap-2">
              <button type="button" onClick={handleBindClick} className="text-xs text-indigo-600">绑定</button>
              {bindings.xunji?.bound && (
                <button type="button" onClick={() => unbind('xunji')} className="text-xs text-red-600">解绑</button>
              )}
            </div>
          </div>
          <div className="rounded-md border border-gray-200 p-3" data-testid="binding-llm">
            <h3 className="font-medium text-gray-900">LLM</h3>
            <p className="text-sm text-gray-600">
              {bindings.llm?.bound ? '已绑定' : '未绑定'}
              {bindings.llm?.default_provider ? ` · 默认 ${bindings.llm.default_provider}` : ''}
            </p>
            {(bindings.llm?.providers || []).length > 0 && (
              <p className="text-xs text-gray-500">{(bindings.llm.providers || []).join(', ')}</p>
            )}
            <div className="mt-2 flex flex-wrap gap-2">
              <button type="button" onClick={handleBindClick} className="text-xs text-indigo-600">绑定</button>
              {(bindings.llm?.providers || []).map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => unbind('llm', p)}
                  className="text-xs text-red-600"
                >
                  解绑 {p}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function PrivacySection({ bindings }) {
  const optedOut = false
  return (
    <div data-testid="privacy-section" className="text-sm text-gray-700">
      <p>
        排行榜参与状态：
        <span className="font-medium">{optedOut ? '已 opt-out' : '参与中'}</span>
      </p>
      <p className="mt-1 text-xs text-gray-500">前端暂不可切换，后端支持中</p>
      {bindings?.llm?.providers?.length > 0 && (
        <p className="mt-2 text-xs text-gray-500">
          已配置 LLM：{bindings.llm.providers.join(', ')}
        </p>
      )}
    </div>
  )
}

function AccountSection() {
  const currentUser = useCurrentUser()
  return (
    <div data-testid="account-section" className="text-sm text-gray-700">
      <p>用户 ID：{currentUser?.user_id ?? '—'}</p>
      <button
        type="button"
        disabled
        className="mt-2 rounded-md bg-gray-200 px-3 py-2 text-sm text-gray-500"
      >
        修改密码（功能即将上线）
      </button>
    </div>
  )
}

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

      <nav className="flex flex-wrap gap-3 text-sm">
        <a href="#bindings" className="text-indigo-600 hover:underline">我的绑定</a>
        <a href="#llm" className="text-indigo-600 hover:underline">LLM 设置</a>
        <a href="#privacy" className="text-indigo-600 hover:underline">我的隐私</a>
        <a href="#account" className="text-indigo-600 hover:underline">账号</a>
      </nav>

      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      {message && <p className="text-sm text-green-600">{message}</p>}

      <section id="bindings" className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-sm font-medium text-gray-900">我的绑定</h2>
        <BindingsSection />
      </section>

      <section id="llm" className="space-y-4">
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

        <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
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
        </div>

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
      </section>

      <section id="privacy" className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-sm font-medium text-gray-900">我的隐私</h2>
        <PrivacySection bindings={null} />
      </section>

      <section id="account" className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-sm font-medium text-gray-900">账号</h2>
        <AccountSection />
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
