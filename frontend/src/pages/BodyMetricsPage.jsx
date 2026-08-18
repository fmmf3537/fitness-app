import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import BodyImageImport from '../components/BodyImageImport'
import TrendChart from '../components/TrendChart'
import useIsMobile from '../hooks/useIsMobile'
import {
  METRIC_DEFS,
  METRIC_GROUPS,
  buildMetricTrendOption,
  buildWeightVolumeOption,
  groupByType,
  isSyncable,
  metricLabel,
} from '../utils/bodyMetrics'

const FORM_TYPES = [
  { value: 'height', label: '身高 (cm)' },
  { value: 'weight', label: '体重 (kg)' },
  { value: 'bodyfat', label: '体脂率 (%)' },
  { value: 'blood_pressure', label: '血压 (mmHg)' },
  { value: 'blood_glucose', label: '血糖 (mmol/L)' },
]

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}

export default function BodyMetricsPage() {
  const isMobile = useIsMobile()
  const [records, setRecords] = useState(null)
  const [trends, setTrends] = useState(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const [formType, setFormType] = useState('weight')
  const [formDate, setFormDate] = useState(todayStr())
  const [formValue, setFormValue] = useState('')
  const [formBpSystolic, setFormBpSystolic] = useState('')
  const [formBpDiastolic, setFormBpDiastolic] = useState('')
  const [formNote, setFormNote] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // 同步确认弹窗：{ metric, summary } | null
  const [syncPreview, setSyncPreview] = useState(null)
  const [syncing, setSyncing] = useState(false)

  // V3-9 体脂秤图片导入面板
  const [showImport, setShowImport] = useState(false)
  const [importMsg, setImportMsg] = useState('')
  // 指标趋势切换器：默认体重
  const [trendType, setTrendType] = useState('weight')

  const load = useCallback(() => {
    return api('/api/body-metrics')
      .then((data) => setRecords(data.metrics || []))
      .catch((err) => setError(err.status === 401 ? '未登录' : err.message))
  }, [])

  useEffect(() => {
    setError('')
    load()
    api('/api/stats/trends?weeks=12')
      .then((data) => setTrends(data))
      .catch((err) => setError(err.status === 401 ? '未登录' : err.message))
  }, [load])

  const grouped = useMemo(() => groupByType(records), [records])
  const hasHeight = Boolean(grouped.height?.length)
  const chartOpts = { mobile: isMobile }
  // 趋势切换器：仅展示有数据的类型；选中项无数据时回退到第一个有数据的
  const availableTypes = METRIC_DEFS.map((d) => d.type).filter((t) => grouped[t]?.length)
  const activeTrend = availableTypes.includes(trendType) ? trendType : availableTypes[0]
  const activeDef = METRIC_DEFS.find((d) => d.type === activeTrend)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setMessage('')
    const payloads = []
    if (formType === 'blood_pressure') {
      if (!formBpSystolic || !formBpDiastolic) {
        setError('请同时填写收缩压与舒张压')
        return
      }
      payloads.push(
        { date: formDate, type: 'bp_systolic', value: Number(formBpSystolic), note: formNote || null },
        { date: formDate, type: 'bp_diastolic', value: Number(formBpDiastolic), note: formNote || null },
      )
    } else {
      if (!formValue) {
        setError('请填写数值')
        return
      }
      payloads.push({ date: formDate, type: formType, value: Number(formValue), note: formNote || null })
    }
    setSubmitting(true)
    try {
      for (const payload of payloads) {
        await api('/api/body-metrics', { method: 'POST', body: JSON.stringify(payload) })
      }
      setMessage('已保存')
      setFormValue('')
      setFormBpSystolic('')
      setFormBpDiastolic('')
      setFormNote('')
      await load()
    } catch (err) {
      setError(err.status === 401 ? '未登录' : err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const handleSyncPreview = async (metric) => {
    setError('')
    try {
      const data = await api(`/api/body-metrics/${metric.id}/sync-xunji`, {
        method: 'POST',
        body: JSON.stringify({ confirmed: false }),
      })
      setSyncPreview({ metric, summary: data.summary })
    } catch (err) {
      setError(err.status === 401 ? '未登录' : err.message)
    }
  }

  const handleSyncConfirm = async () => {
    if (!syncPreview) return
    setSyncing(true)
    setError('')
    try {
      const data = await api(`/api/body-metrics/${syncPreview.metric.id}/sync-xunji`, {
        method: 'POST',
        body: JSON.stringify({ confirmed: true }),
      })
      const updated = data.metric
      if (updated) {
        setRecords((rows) => rows.map((r) => (r.id === updated.id ? updated : r)))
      }
      setMessage('已同步到训记')
      setSyncPreview(null)
    } catch (err) {
      setError(err.status === 401 ? '未登录' : err.message)
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-gray-900">身体数据</h1>

      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      {message && <p className="text-sm text-green-600">{message}</p>}
      {importMsg && (
        <p data-testid="import-success" className="text-sm text-green-600">
          {importMsg}
        </p>
      )}

      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <button
          data-testid="open-image-import"
          onClick={() => {
            setShowImport((v) => !v)
            setImportMsg('')
          }}
          className="rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700"
        >
          {showImport ? '收起图片导入' : '体脂秤图片导入'}
        </button>
        {showImport && (
          <div className="mt-3">
            <BodyImageImport
              onImported={(text) => {
                setImportMsg(text)
                setShowImport(false)
                load()
              }}
            />
          </div>
        )}
      </div>

      {records && !hasHeight && (
        <div
          data-testid="height-guide"
          className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"
        >
          首次使用建议先录入身高（变化频率低，录一次即可），便于后续 BMI 等指标分析。
        </div>
      )}

      <form
        data-testid="metric-form"
        onSubmit={handleSubmit}
        className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      >
        <h2 className="mb-3 text-sm font-medium text-gray-900">录入指标</h2>
        <div className="flex flex-wrap items-center gap-2">
          <select
            data-testid="metric-type"
            value={formType}
            onChange={(e) => setFormType(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm"
          >
            {FORM_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
          <input
            type="date"
            data-testid="metric-date"
            value={formDate}
            onChange={(e) => setFormDate(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          {formType === 'blood_pressure' ? (
            <>
              <input
                type="number"
                step="0.1"
                placeholder="收缩压"
                data-testid="metric-bp-systolic"
                value={formBpSystolic}
                onChange={(e) => setFormBpSystolic(e.target.value)}
                className="w-28 rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
              <input
                type="number"
                step="0.1"
                placeholder="舒张压"
                data-testid="metric-bp-diastolic"
                value={formBpDiastolic}
                onChange={(e) => setFormBpDiastolic(e.target.value)}
                className="w-28 rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </>
          ) : (
            <input
              type="number"
              step="0.01"
              placeholder="数值"
              data-testid="metric-value"
              value={formValue}
              onChange={(e) => setFormValue(e.target.value)}
              className="w-28 rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          )}
          <input
            type="text"
            placeholder="备注（可选）"
            data-testid="metric-note"
            value={formNote}
            onChange={(e) => setFormNote(e.target.value)}
            className="w-36 rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          <button
            type="submit"
            data-testid="submit-metric"
            disabled={submitting}
            className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {submitting ? '保存中…' : '保存'}
          </button>
        </div>
      </form>

      {records && (
        <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-sm font-medium text-gray-900">体重 × 训练容量对照</h2>
          <TrendChart
            testId="trend-chart-weight-volume"
            option={buildWeightVolumeOption(
              trends?.weekly_volume || [],
              grouped.weight || [],
              chartOpts,
            )}
          />
        </section>
      )}

      {records && activeDef && (
        <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <h2 className="text-sm font-medium text-gray-900">指标趋势</h2>
            <select
              data-testid="trend-type-select"
              value={activeTrend}
              onChange={(e) => setTrendType(e.target.value)}
              className="rounded-md border border-gray-300 px-2 py-1 text-sm"
            >
              {METRIC_GROUPS.map((g) => {
                const types = g.types.filter((t) => grouped[t]?.length)
                if (types.length === 0) return null
                return (
                  <optgroup key={g.key} label={g.label}>
                    {types.map((t) => (
                      <option key={t} value={t}>
                        {metricLabel(t)}
                      </option>
                    ))}
                  </optgroup>
                )
              })}
            </select>
          </div>
          <TrendChart
            testId={`trend-chart-${activeTrend}`}
            option={buildMetricTrendOption(
              grouped[activeTrend],
              activeDef.label,
              activeDef.unit,
              chartOpts,
            )}
          />
        </section>
      )}

      {records && (
        <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-sm font-medium text-gray-900">最近记录</h2>
          {records.length === 0 && <p className="text-sm text-gray-500">暂无记录</p>}
          <ul className="divide-y divide-gray-100">
            {[...records]
              .sort((a, b) => (a.date < b.date ? 1 : -1))
              .slice(0, 30)
              .map((r) => (
                <li
                  key={r.id}
                  data-testid={`metric-row-${r.id}`}
                  className="flex items-center justify-between py-2 text-sm"
                >
                  <span className="text-gray-700">
                    {r.date} · {metricLabel(r.type)} ·
                    <span className="font-medium text-gray-900">
                      {' '}{r.value} {r.unit}
                    </span>
                    {r.note && <span className="ml-1 text-gray-400">（{r.note}）</span>}
                  </span>
                  <span className="flex items-center gap-2">
                    {!isSyncable(r.type) && (
                      <span
                        data-testid={`local-only-${r.id}`}
                        className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500"
                      >
                        仅本地
                      </span>
                    )}
                    {isSyncable(r.type) && r.synced_to_xunji && (
                      <span
                        data-testid={`synced-${r.id}`}
                        className="rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-700"
                      >
                        已同步
                      </span>
                    )}
                    {isSyncable(r.type) && !r.synced_to_xunji && (
                      <button
                        data-testid={`sync-btn-${r.id}`}
                        onClick={() => handleSyncPreview(r)}
                        className="rounded-md bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-700 hover:bg-indigo-100"
                      >
                        同步到训记
                      </button>
                    )}
                  </span>
                </li>
              ))}
          </ul>
        </section>
      )}

      {syncPreview && (
        <div
          data-testid="sync-modal"
          className="fixed inset-0 z-10 flex items-center justify-center bg-black/30"
        >
          <div className="w-96 rounded-lg bg-white p-4 shadow-lg">
            <h3 className="mb-2 text-sm font-medium text-gray-900">确认同步到训记</h3>
            <p data-testid="sync-summary" className="mb-4 text-sm text-gray-700">
              {syncPreview.summary || '训记将更新该条记录'}
            </p>
            <div className="flex justify-end gap-2">
              <button
                data-testid="sync-cancel"
                onClick={() => setSyncPreview(null)}
                className="rounded-md px-3 py-2 text-sm text-gray-700 hover:bg-gray-100"
              >
                取消
              </button>
              <button
                data-testid="sync-confirm"
                onClick={handleSyncConfirm}
                disabled={syncing}
                className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {syncing ? '同步中…' : '确认同步'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
