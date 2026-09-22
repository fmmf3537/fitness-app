import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import PageHeader from '../components/PageHeader'
import { useCandidateQueue } from '../components/useCandidateQueue'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import Icon from '../components/ui/Icon'
import IconChip from '../components/ui/IconChip'
import Skeleton from '../components/ui/Skeleton'

/** 分组列表行：图标 chip + 标题(+副标题) + 计数徽标 + 尾箭头 */
function MenuRow({ to, icon, chip, label, sub, count, testId }) {
  return (
    <Link
      to={to}
      aria-label={label}
      data-testid={testId}
      className="flex min-h-[56px] items-center gap-3 border-b border-line px-2 py-2.5 text-sm transition last:border-b-0 hover:bg-canvas/60 dark:border-gray-800 dark:text-gray-200 dark:hover:bg-gray-800"
    >
      <IconChip icon={icon} variant={chip} />
      <span className="min-w-0 flex-1">
        <span className="block font-medium text-ink-900 dark:text-gray-100">{label}</span>
        {sub && <span className="mt-0.5 block text-xs text-ink-400 dark:text-gray-400">{sub}</span>}
      </span>
      {count != null && (
        <span className="rounded-full bg-canvas px-2 py-0.5 text-[11px] text-ink-400 dark:bg-gray-800">
          {count}
        </span>
      )}
      <span className="text-ink-400" aria-hidden="true">
        <Icon name="arrow" size={16} strokeWidth={1.8} />
      </span>
    </Link>
  )
}

function GroupTitle({ children }) {
  return <h2 className="mx-1 mb-2 mt-5 text-[11.5px] font-semibold tracking-wide text-ink-400">{children}</h2>
}

export default function SettingsPage() {
  const { pendingCount } = useCandidateQueue()
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

  const llmConfigured = (settings?.providers || []).filter((p) => p.has_key).length

  return (
    <div className="space-y-1">
      <PageHeader title="设置" subtitle="数据、资料与模型配置" />

      {/* 数据状态条（替代原头像卡：无账号体系，只呈现真实数据） */}
      <div className="mt-4 grid grid-cols-3 gap-2">
        <div className="rounded-2xl border border-line bg-white p-3 shadow-card dark:border-gray-800 dark:bg-gray-900">
          <p className="text-[10.5px] text-ink-400">待确认队列</p>
          <p className={`mt-1 text-base font-black ${pendingCount > 0 ? 'text-amber-600' : 'text-ink-900 dark:text-white'}`}>
            {pendingCount ?? '—'}
          </p>
        </div>
        <div className="rounded-2xl border border-line bg-white p-3 shadow-card dark:border-gray-800 dark:bg-gray-900">
          <p className="text-[10.5px] text-ink-400">本月 AI 用量</p>
          <p className="mt-1 text-base font-black text-ink-900 dark:text-white">
            {usage ? `¥${usage.total_cost.toFixed(2)}` : '—'}
          </p>
        </div>
        <div className="rounded-2xl border border-line bg-white p-3 shadow-card dark:border-gray-800 dark:bg-gray-900">
          <p className="text-[10.5px] text-ink-400">LLM</p>
          <p className={`mt-1 text-base font-black ${llmConfigured > 0 ? 'text-emerald-600' : 'text-ink-900 dark:text-white'}`}>
            {settings ? (llmConfigured > 0 ? '已配置' : '未配置') : '—'}
          </p>
        </div>
      </div>

      <GroupTitle>训练数据</GroupTitle>
      <Card className="px-3.5 py-1.5" testId="feature-menu">
        <MenuRow to="/import" icon="sync" chip="blue" label="数据导入" />
        <MenuRow to="/candidates" icon="alert" chip="amber" label="待确认队列" count={pendingCount ?? null} />
        <MenuRow to="/reviews" icon="doc" chip="green" label="复盘中心" />
        <MenuRow to="/ai-reports" icon="sparkle" chip="violet" label="AI 报告" />
      </Card>

      <GroupTitle>身体数据</GroupTitle>
      <Card className="px-3.5 py-1.5">
        <MenuRow to="/body-metrics" icon="heart" chip="violet" label="体重与体脂" />
      </Card>

      {error && (
        <ErrorState message={error} onRetry={loadSettings} testId="settings-error" />
      )}
      {message && <p className="mt-3 text-sm font-medium text-emerald-600">{message}</p>}

      {settings?.suggested_fallback && (
        <div
          data-testid="llm-fallback-banner"
          className="mt-3 flex flex-wrap items-center gap-3 rounded-2xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:bg-amber-950/50"
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

      <GroupTitle>体脂计算资料</GroupTitle>
      <Card testId="profile-section">
        <p className="mb-3 text-xs text-ink-500 dark:text-gray-400">
          性别与出生日期仅用于皮脂钳体脂率公式计算，保存在本地
        </p>
        {profileLoadError && (
          <p data-testid="profile-load-error" className="mb-2 text-xs text-red-600">{profileLoadError}</p>
        )}
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <label className="sr-only" htmlFor="profile-gender">性别</label>
          <select
            id="profile-gender"
            data-testid="profile-gender"
            value={profileGender}
            onChange={(e) => setProfileGender(e.target.value)}
            className="h-11 rounded-xl border border-line bg-canvas/50 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-brand-200 dark:border-gray-700 dark:bg-gray-950"
          >
            <option value="">性别</option>
            <option value="male">男</option>
            <option value="female">女</option>
          </select>
          <label className="sr-only" htmlFor="profile-birth-date">出生日期</label>
          <input
            id="profile-birth-date"
            type="date"
            data-testid="profile-birth-date"
            value={profileBirthDate}
            onChange={(e) => setProfileBirthDate(e.target.value)}
            className="h-11 flex-1 rounded-xl border border-line bg-canvas/50 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-brand-200 dark:border-gray-700 dark:bg-gray-950 sm:max-w-44"
          />
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

      <GroupTitle>AI 教练</GroupTitle>
      <Card className="px-3.5 py-1.5">
        <MenuRow to="/coach?tab=prefs" icon="coach" chip="blue" label="教练须知" />
      </Card>

      <Card className="mt-3">
        <h2 className="mb-3 text-sm font-bold text-ink-900 dark:text-gray-100">LLM Key 配置</h2>
        {!settings && !error && <Skeleton className="h-20" />}
        <div className="space-y-3">
          {(settings?.providers || []).map((p) => (
            <div
              key={p.name}
              data-testid={`llm-provider-${p.name}`}
              className="rounded-2xl border border-line p-3 dark:border-gray-800"
            >
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-semibold text-ink-900 dark:text-gray-100">{p.name}</span>
                <span className="text-xs text-ink-500 dark:text-gray-400">{p.default_model}</span>
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
                <label htmlFor={`api-key-input-${p.name}`} className="text-sm text-ink-600 dark:text-gray-300">
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
                  className="w-64 rounded-xl border border-line bg-canvas/50 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-200 dark:border-gray-700 dark:bg-gray-950"
                />
                <label className="flex items-center gap-1 text-sm text-ink-600 dark:text-gray-300">
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
                  size="compact"
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

      <Card testId="llm-usage" className="mt-3">
        <h2 className="mb-3 text-sm font-bold text-ink-900 dark:text-gray-100">
          本月用量{usage?.month ? `（${usage.month}）` : ''}
        </h2>
        {!usage && !error && <Skeleton className="h-16" />}
        {usage && (
          <div className="space-y-3 text-sm">
            <div className="flex gap-6">
              <p data-testid="usage-total-calls" className="text-ink-600 dark:text-gray-300">
                总调用：<span className="font-semibold text-ink-900 dark:text-gray-100">{usage.total_calls}</span> 次
              </p>
              <p data-testid="usage-total-cost" className="text-ink-600 dark:text-gray-300">
                总费用：
                <span className="font-semibold text-ink-900 dark:text-gray-100">¥{usage.total_cost.toFixed(4)}</span>
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs whitespace-nowrap text-ink-500 dark:text-gray-400">
              <thead>
                <tr className="border-b border-line text-ink-500 dark:text-gray-400">
                  <th className="py-1 pr-2 font-medium">Provider</th>
                  <th className="py-1 pr-2 font-medium">模型</th>
                  <th className="py-1 pr-2 font-medium">调用</th>
                  <th className="py-1 pr-2 font-medium">tokens</th>
                  <th className="py-1 font-medium">费用</th>
                </tr>
              </thead>
              <tbody>
                {(usage.by_provider || []).map((row) => (
                  <tr key={row.provider} className="border-b border-line dark:border-gray-800">
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

      <section data-testid="deleted-workouts" className="mt-6">
        <h2 className="mb-2 text-base font-bold text-ink-900 dark:text-gray-100">已删除的训练</h2>
        {deleted.length === 0 ? (
          <EmptyState title="暂无已删除的训练" description="删除的训练会出现在这里，可随时恢复" />
        ) : (
          <ul className="space-y-2">
            {deleted.map((w) => (
              <li
                key={w.id}
                data-testid={`deleted-workout-${w.id}`}
                className="flex items-center justify-between rounded-2xl border border-line bg-white p-3 text-sm shadow-card dark:border-gray-800 dark:bg-gray-900"
              >
                <span className="text-ink-600 dark:text-gray-300">
                  {w.date} · {w.title || '未命名训练'}
                </span>
                <Button
                  variant="secondary"
                  size="compact"
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

      <p className="mt-8 text-center text-[11px] leading-5 text-ink-400">
        健身看板 · 数据保存在本地
      </p>
    </div>
  )
}
