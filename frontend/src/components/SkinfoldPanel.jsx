// V4-4 皮脂钳测量面板：方案选择 → 部位录入 → 提交 → 自动算体脂率并落身体数据。
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'

const SELF_TEST_LABEL = {
  yes: '✅ 可自测',
  assist: '⚠️ 部分需辅助',
  no: '❌ 需辅助',
}

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}

function recommendKey(methods, gender) {
  if (gender === 'male') return 'jp3_male'
  if (gender === 'female') return 'jp3_female'
  return methods[0]?.key || null
}

export default function SkinfoldPanel({ onSaved }) {
  const [methods, setMethods] = useState([])
  const [profile, setProfile] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [selectedKey, setSelectedKey] = useState(null)
  const [showMore, setShowMore] = useState(false)
  const [date, setDate] = useState(todayStr())
  const [sites, setSites] = useState({})
  const [note, setNote] = useState('')
  const [siteErrors, setSiteErrors] = useState({})
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')
  const [lastRecord, setLastRecord] = useState(null)

  const profileMissing =
    profile && (!profile.gender || !profile.birth_date)

  useEffect(() => {
    let cancelled = false
    api('/api/skinfold/methods')
      .then((data) => {
        if (cancelled) return
        const list = data.methods || []
        setMethods(list)
        setProfile(data.profile || { gender: null, birth_date: null })
        const rec = recommendKey(list, data.profile?.gender)
        if (rec) setSelectedKey(rec)
      })
      .catch((err) => {
        if (cancelled) return
        setLoadError(err.status === 401 ? '未登录' : err.message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // 切换方案时拉取上次测量记录
  const loadLast = useCallback((methodKey) => {
    if (!methodKey) {
      setLastRecord(null)
      return
    }
    api(`/api/skinfold/records?method=${encodeURIComponent(methodKey)}`)
      .then((data) => {
        const first = (data.records || [])[0]
        if (first) {
          setLastRecord(first)
          setSites((prev) => {
            const next = { ...prev }
            Object.entries(first.sites || {}).forEach(([k, v]) => {
              next[k] = String(v)
            })
            return next
          })
        } else {
          setLastRecord(null)
        }
      })
      .catch(() => setLastRecord(null))
  }, [])

  useEffect(() => {
    setSuccessMsg('')
    setSubmitError('')
    loadLast(selectedKey)
  }, [selectedKey, loadLast])

  const selectedMethod = methods.find((m) => m.key === selectedKey) || null
  const recommendedKey = recommendKey(methods, profile?.gender)
  const recommendedMethod = methods.find((m) => m.key === recommendedKey) || null
  const otherMethods = methods.filter((m) => m.key !== recommendedKey)

  const handleSiteChange = (siteKey, value) => {
    setSites((prev) => ({ ...prev, [siteKey]: value }))
    setSiteErrors((prev) => ({ ...prev, [siteKey]: '' }))
  }

  const validate = () => {
    const errs = {}
    if (!selectedMethod) {
      setSubmitError('请先选择方案')
      return false
    }
    selectedMethod.sites.forEach((s) => {
      const raw = sites[s.key]
      if (raw === undefined || raw === '' || raw === null) {
        errs[s.key] = `请填写${s.name_zh}`
        return
      }
      const n = Number(raw)
      if (Number.isNaN(n)) {
        errs[s.key] = '请输入数字'
      } else if (n < 2 || n > 60) {
        errs[s.key] = '数值需在 2~60 mm'
      }
    })
    setSiteErrors(errs)
    if (Object.keys(errs).length > 0) return false
    return true
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitError('')
    setSuccessMsg('')
    if (!validate()) return
    setSubmitting(true)
    try {
      const payload = {
        date,
        method: selectedKey,
        sites: Object.fromEntries(
          selectedMethod.sites.map((s) => [s.key, Number(sites[s.key])]),
        ),
      }
      if (note.trim()) payload.note = note.trim()
      const data = await api('/api/skinfold/records', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      const bf = data.record?.bodyfat_result
      setSuccessMsg(`已保存 · 体脂率 ${bf}%（已写入身体数据）`)
      loadLast(selectedKey)
      onSaved?.()
    } catch (err) {
      setSubmitError(err.detail || '提交失败，请检查输入（mm 范围 2~60）')
    } finally {
      setSubmitting(false)
    }
  }

  if (loadError) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <p role="alert" className="text-sm text-red-600">{loadError}</p>
      </div>
    )
  }

  return (
    <div data-testid="skinfold-panel" className="space-y-3">
      {profileMissing && (
        <div
          data-testid="skinfold-profile-guide"
          className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800"
        >
          皮脂钳测量需要性别与出生日期，请先到设置页「个人资料」填写
        </div>
      )}

      {!methods.length && !loadError && (
        <p className="text-sm text-gray-500">加载方案中…</p>
      )}

      {recommendedMethod && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <MethodCard
            method={recommendedMethod}
            selected={selectedKey === recommendedMethod.key}
            onSelect={() => setSelectedKey(recommendedMethod.key)}
            disabled={profileMissing}
            recommended
          />
        </div>
      )}

      {otherMethods.length > 0 && (
        <div className="space-y-2">
          <button
            type="button"
            data-testid="more-methods"
            onClick={() => setShowMore((v) => !v)}
            disabled={profileMissing}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {showMore ? '收起更多方案' : `更多方案（${otherMethods.length}）`}
          </button>
          {showMore && (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {otherMethods.map((m) => (
                <MethodCard
                  key={m.key}
                  method={m}
                  selected={selectedKey === m.key}
                  onSelect={() => setSelectedKey(m.key)}
                  disabled={profileMissing}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {selectedMethod && (
        <form
          data-testid="skinfold-form"
          onSubmit={handleSubmit}
          className="space-y-3 rounded-md border border-gray-200 p-3"
        >
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-sm text-gray-700">
              日期
              <input
                type="date"
                data-testid="skinfold-date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                disabled={profileMissing || submitting}
                className="ml-2 rounded-md border border-gray-300 px-2 py-1 text-sm"
              />
            </label>
          </div>

          {lastRecord && (
            <p
              data-testid="last-record"
              className="rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-600"
            >
              上次测量：{lastRecord.date} · 体脂率 {lastRecord.bodyfat_result}%
            </p>
          )}

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {selectedMethod.sites.map((s) => (
              <label key={s.key} className="block text-sm text-gray-700">
                {s.name_zh}
                <input
                  type="number"
                  step="0.1"
                  placeholder="mm"
                  data-testid={`site-input-${s.key}`}
                  value={sites[s.key] ?? ''}
                  onChange={(e) => handleSiteChange(s.key, e.target.value)}
                  disabled={profileMissing || submitting}
                  className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 text-sm"
                />
                {siteErrors[s.key] && (
                  <span
                    role="alert"
                    data-testid={`site-error-${s.key}`}
                    className="mt-1 block text-xs text-red-600"
                  >
                    {siteErrors[s.key]}
                  </span>
                )}
              </label>
            ))}
          </div>

          <label className="block text-sm text-gray-700">
            备注（可选）
            <input
              type="text"
              data-testid="skinfold-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              disabled={profileMissing || submitting}
              className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 text-sm"
            />
          </label>

          {submitError && (
            <p role="alert" className="text-sm text-red-600">{submitError}</p>
          )}
          {successMsg && (
            <p
              data-testid="skinfold-success"
              className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-700"
            >
              {successMsg}
            </p>
          )}

          <button
            type="submit"
            data-testid="submit-skinfold"
            disabled={profileMissing || submitting}
            className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? '提交中…' : '保存测量'}
          </button>
        </form>
      )}
    </div>
  )
}

function MethodCard({ method, selected, onSelect, disabled, recommended = false }) {
  return (
    <button
      type="button"
      data-testid={`method-card-${method.key}`}
      onClick={onSelect}
      disabled={disabled}
      className={`rounded-md border p-3 text-left text-sm transition disabled:cursor-not-allowed disabled:opacity-50 ${
        selected
          ? 'border-indigo-500 bg-indigo-50'
          : 'border-gray-200 bg-white hover:border-indigo-300'
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="font-medium text-gray-900">{method.name_zh}</span>
        {recommended && (
          <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs text-indigo-700">
            推荐
          </span>
        )}
      </div>
      <p
        data-testid={`self-test-${method.key}`}
        className="mt-1 text-xs text-gray-600"
      >
        {SELF_TEST_LABEL[method.self_test] || method.self_test}
      </p>
      <p className="mt-1 text-xs text-gray-500">
        部位：{method.sites.map((s) => s.name_zh).join('、')}
      </p>
    </button>
  )
}