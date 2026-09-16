import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import BodyImageImport from '../components/BodyImageImport'
import SkinfoldPanel from '../components/SkinfoldPanel'
import TrendChart from '../components/TrendChart'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
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
  // V4-4 皮脂钳测量面板
  const [showSkinfold, setShowSkinfold] = useState(false)
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
  const latestWeight = grouped.weight?.at(-1)
  const latestBodyfat = grouped.bodyfat?.at(-1)

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
      <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">身体数据</h1>

      {error && (
        <ErrorState message={error} onRetry={load} testId="bodymetrics-error" />
      )}
      {message && <p className="text-sm text-green-600">{message}</p>}
      {importMsg && (
        <p data-testid="import-success" className="text-sm text-green-600">
          {importMsg}
        </p>
      )}

      {records && (latestWeight || latestBodyfat) && (
        <div className="grid grid-cols-2 gap-3" data-testid="bodymetrics-hero">
          {latestWeight && <Card className="bg-white text-gray-950 shadow-sm dark:bg-gray-900 dark:text-white">
            <p className="text-xs text-gray-600 dark:text-gray-300">当前体重</p>
            <p className="mt-2 text-3xl font-black">{latestWeight.value}<span className="ml-1 text-sm font-medium text-gray-500">{latestWeight.unit}</span></p>
            <p className="mt-1 text-xs text-emerald-600">记录于 {latestWeight.date}</p>
          </Card>}
          {latestBodyfat && <Card className="bg-white text-gray-950 shadow-sm dark:bg-gray-900 dark:text-white">
            <p className="text-xs text-gray-600 dark:text-gray-300">当前体脂</p>
            <p className="mt-2 text-3xl font-black">{latestBodyfat.value}<span className="ml-1 text-sm font-medium">{latestBodyfat.unit}</span></p>
            <p className="mt-1 text-xs text-gray-500">记录于 {latestBodyfat.date}</p>
          </Card>}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
      <Card className="transition hover:-translate-y-0.5 hover:shadow-md">
        <p className="mb-1 text-sm font-semibold text-gray-900 dark:text-gray-100">用图片估算体脂</p>
        <p className="mb-3 text-xs text-gray-600 dark:text-gray-300">识别体脂秤截图并导入真实数据</p>
        <Button
          variant="primary"
          testId="open-image-import"
          onClick={() => {
            setShowImport((v) => !v)
            setImportMsg('')
          }}
        >
          {showImport ? '收起图片导入' : '选择图片'}
        </Button>
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
      </Card>

      <Card className="transition hover:-translate-y-0.5 hover:shadow-md">
        <p className="mb-1 text-sm font-semibold text-gray-900 dark:text-gray-100">用皮脂钳估算</p>
        <p className="mb-3 text-xs text-gray-600 dark:text-gray-300">根据测量点数据计算体脂率</p>
        <Button
          variant="secondary"
          testId="open-skinfold"
          onClick={() => setShowSkinfold((v) => !v)}
        >
          {showSkinfold ? '收起皮脂钳测量' : '开始测量'}
        </Button>
        {showSkinfold && (
          <div className="mt-3">
            <SkinfoldPanel onSaved={() => load()} />
          </div>
        )}
      </Card>
      </div>

      {records && !hasHeight && (
        <div
          data-testid="height-guide"
          className="rounded-lg border border-amber-200 bg-amber-50 dark:bg-amber-950/50 p-3 text-sm text-amber-800"
        >
          首次使用建议先录入身高（变化频率低，录一次即可），便于后续 BMI 等指标分析。
        </div>
      )}

      <Card>
        <form data-testid="metric-form" onSubmit={handleSubmit}>
        <h2 className="mb-3 text-sm font-medium text-gray-900 dark:text-gray-100">录入指标</h2>
        <div className="flex flex-wrap items-center gap-2">
          <select
            data-testid="metric-type"
            value={formType}
            onChange={(e) => setFormType(e.target.value)}
            className="rounded-md border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-100 dark:focus:ring-indigo-900"
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
            className="rounded-md border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-100 dark:focus:ring-indigo-900"
          />
          {formType === 'blood_pressure' ? (
            <div className="flex items-center overflow-hidden rounded-lg border border-gray-300 bg-white dark:border-gray-600 dark:bg-gray-900">
              <input
                type="number"
                inputMode="decimal"
                step="0.1"
                placeholder="收缩压"
                data-testid="metric-bp-systolic"
                value={formBpSystolic}
                onChange={(e) => setFormBpSystolic(e.target.value)}
                className="w-24 border-0 bg-transparent px-3 py-2 text-sm focus:outline-none"
              />
              <span className="text-gray-400">/</span>
              <input
                type="number"
                inputMode="decimal"
                step="0.1"
                placeholder="舒张压"
                data-testid="metric-bp-diastolic"
                value={formBpDiastolic}
                onChange={(e) => setFormBpDiastolic(e.target.value)}
                className="w-24 border-0 bg-transparent px-3 py-2 text-sm focus:outline-none"
              />
            </div>
          ) : (
            <input
              type="number"
              inputMode="decimal"
              step="0.01"
              placeholder="数值"
              data-testid="metric-value"
              value={formValue}
              onChange={(e) => setFormValue(e.target.value)}
              className="w-28 rounded-md border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-100 dark:focus:ring-indigo-900"
            />
          )}
          <input
            type="text"
            placeholder="备注（可选）"
            data-testid="metric-note"
            value={formNote}
            onChange={(e) => setFormNote(e.target.value)}
            className="w-36 rounded-md border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-100 dark:focus:ring-indigo-900"
          />
          <Button
            type="submit"
            variant="primary"
            testId="submit-metric"
            disabled={submitting}
          >
            {submitting ? '保存中…' : '保存'}
          </Button>
        </div>
        </form>
      </Card>

      {records && (
        <Card>
          <h2 className="mb-3 text-sm font-medium text-gray-900 dark:text-gray-100">体重 × 训练容量对照</h2>
          <TrendChart
            testId="trend-chart-weight-volume"
            option={buildWeightVolumeOption(
              trends?.weekly_volume || [],
              grouped.weight || [],
              chartOpts,
            )}
          />
        </Card>
      )}

      {records && activeDef && (
        <Card>
          <div className="mb-3 flex items-center gap-2">
            <h2 className="text-sm font-medium text-gray-900 dark:text-gray-100">指标趋势</h2>
            <select
              data-testid="trend-type-select"
              value={activeTrend}
              onChange={(e) => setTrendType(e.target.value)}
              className="rounded-md border border-gray-300 dark:border-gray-600 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-100 dark:focus:ring-indigo-900"
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
        </Card>
      )}

      {records && (
        <Card>
          <h2 className="mb-3 text-sm font-medium text-gray-900 dark:text-gray-100">最近记录</h2>
          {records.length === 0 && (
            <EmptyState title="暂无记录" description="在上方录入第一条身体指标" />
          )}
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
                  <span className="text-gray-700 dark:text-gray-300">
                    {r.date} · {metricLabel(r.type)} ·
                    <span className="font-medium text-gray-900 dark:text-gray-100">
                      {' '}{r.value} {r.unit}
                    </span>
                    {r.note && <span className="ml-1 text-gray-600 dark:text-gray-400">（{r.note}）</span>}
                  </span>
                  <span className="flex items-center gap-2">
                    {!isSyncable(r.type) && (
                      <Badge variant="gray" testId={`local-only-${r.id}`}>
                        仅本地
                      </Badge>
                    )}
                    {isSyncable(r.type) && r.synced_to_xunji && (
                      <Badge variant="green" testId={`synced-${r.id}`}>
                        已同步
                      </Badge>
                    )}
                    {isSyncable(r.type) && !r.synced_to_xunji && (
                      <Button
                        variant="ghost"
                        testId={`sync-btn-${r.id}`}
                        onClick={() => handleSyncPreview(r)}
                        className="text-xs"
                      >
                        同步到训记
                      </Button>
                    )}
                  </span>
                </li>
              ))}
          </ul>
        </Card>
      )}

      {syncPreview && (
        <div
          data-testid="sync-modal"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
          role="dialog"
          aria-modal="true"
        >
          <div className="w-full max-w-sm rounded-xl bg-white dark:bg-gray-900 p-4 shadow-xl mb-[env(safe-area-inset-bottom)]">
            <h3 className="mb-2 text-sm font-medium text-gray-900 dark:text-gray-100">确认同步到训记</h3>
            <p data-testid="sync-summary" className="mb-4 text-sm text-gray-700 dark:text-gray-300">
              {syncPreview.summary || '训记将更新该条记录'}
            </p>
            <div className="flex justify-end gap-2">
              <button
                data-testid="sync-cancel"
                onClick={() => setSyncPreview(null)}
                className="rounded-md px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
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
