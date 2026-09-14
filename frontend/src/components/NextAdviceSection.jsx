import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import ReportChatSection from './ReportChatSection'
import SimpleMarkdown from './SimpleMarkdown'
import Button from './ui/Button'
import Card from './ui/Card'
import ConfirmDialog from './ui/ConfirmDialog'
import EmptyState from './ui/EmptyState'
import { formatParams, groupSuggestions, parseNextAdvice } from '../utils/nextAdvice'
import { buildChanges } from '../utils/writeback'

const MANUAL_GUIDE =
  '训记 App 操作路径：打开训记 App → 计划 → 找到对应训练日 → 长按动作修改重量/组数/次数后保存。'

// V4-6：统一的中文护栏提示（按 status 映射）。next_advice 端点 422 表示"旧建议已清理、无训记计划缓存"。
const REGEN_ERROR_MAP = {
  429: '今日重生成次数已达上限（5 次），明天再来',
  422: '无训记计划缓存，暂时无法生成下次建议（旧建议已清理）',
  404: '无法重新生成：记录不存在',
}

function regenErrorMessage(err) {
  const status = err?.status
  return REGEN_ERROR_MAP[status] || err?.message || '重新生成失败，请稍后重试'
}

function formatValue(v) {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/** diff 表格：字段/原值/新值三列，变更行高亮。 */
function DiffTable({ diff }) {
  return (
    <div className="overflow-x-auto">
      <table className="mt-2 w-full border-collapse text-xs whitespace-nowrap">
      <thead>
        <tr className="border-b border-gray-300 text-left text-gray-600">
          <th className="py-1 pr-2 font-medium">字段</th>
          <th className="py-1 pr-2 font-medium">原值</th>
          <th className="py-1 font-medium">新值</th>
        </tr>
      </thead>
      <tbody>
        {(diff || []).map((row, i) => (
          <tr
            key={i}
            className={`border-b border-gray-100 ${row.changed ? 'bg-amber-100 font-medium' : 'text-gray-600'}`}
          >
            <td className="py-1 pr-2">{row.field}</td>
            <td className="py-1 pr-2">{formatValue(row.old)}</td>
            <td className="py-1">{formatValue(row.new)}</td>
          </tr>
        ))}
      </tbody>
      </table>
    </div>
  )
}

function SuggestionCard({ suggestion, index, autoWritable, workout }) {
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const handlePreview = async () => {
    setError(null)
    setResult(null)
    const localid = workout?.xunji_raw?.localid
    if (localid === null || localid === undefined) {
      setError('该训练无训记原始记录，无法写回')
      return
    }
    const changes = buildChanges(suggestion, workout?.movements)
    if (!changes) {
      setError('本次训练中未找到同名动作，无法生成写回预览')
      return
    }
    setLoading(true)
    try {
      const data = await api('/api/writeback/preview', {
        method: 'POST',
        body: JSON.stringify({ datestr: workout.date, localid, changes }),
      })
      setPreview(data)
    } catch (e) {
      setError(`生成预览失败：${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  const handleConfirmWriteback = async () => {
    setConfirmOpen(false)
    if (!preview) return
    setLoading(true)
    setError(null)
    try {
      const localid = workout?.xunji_raw?.localid
      const changes = buildChanges(suggestion, workout?.movements)
      await api('/api/writeback/confirm', {
        method: 'POST',
        body: JSON.stringify({ datestr: workout.date, localid, changes }),
      })
      setResult('写回成功，本地缓存已用服务端数据覆盖')
      setPreview(null)
    } catch (e) {
      setError(`写回失败：${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <li className="rounded-md border border-gray-200 p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-gray-900">{suggestion.movement}</p>
          <p className="mt-1 text-xs text-gray-600">
            原参数：{formatParams(suggestion.original)} → 建议：{formatParams(suggestion.suggested)}
          </p>
          <p className="mt-1 text-xs text-gray-600">{suggestion.reason}</p>
        </div>
        {autoWritable && !result && (
          <Button
            variant="primary"
            disabled={loading}
            onClick={handlePreview}
            className="shrink-0 text-xs"
          >
            生成写回预览
          </Button>
        )}
      </div>
      {error && <p className="mt-2 rounded-md bg-red-50 p-2 text-xs text-red-700">{error}</p>}
      {result && (
        <p className="mt-2 rounded-md bg-green-50 p-2 text-xs text-green-700">{result}</p>
      )}
      {autoWritable && preview && (
        <div
          data-testid={`writeback-preview-${index}`}
          className="mt-2 rounded-md bg-gray-50 p-3 text-xs text-gray-700"
        >
          <p className="font-medium text-gray-800">
            写回预览（{preview.datestr} · localid {preview.localid}）——元数据（localid/起止时间/备注）将原样保留
          </p>
          <DiffTable diff={preview.diff} />
          <Button
            variant="primary"
            disabled={loading}
            onClick={() => setConfirmOpen(true)}
            className="mt-3 text-xs"
          >
            确认写回
          </Button>
        </div>
      )}
      {!autoWritable && (
        <p className="mt-2 rounded-md bg-amber-50 p-2 text-xs text-amber-800">{MANUAL_GUIDE}</p>
      )}
      <ConfirmDialog
        open={confirmOpen}
        title="确认执行写回？"
        description="该操作将直接修改训记 App 中的训练记录。"
        danger
        confirmText="确认"
        onConfirm={handleConfirmWriteback}
        onCancel={() => setConfirmOpen(false)}
      />
    </li>
  )
}

export default function NextAdviceSection({ workout }) {
  const [report, setReport] = useState(null)
  const [loaded, setLoaded] = useState(false)
  const [regenLoading, setRegenLoading] = useState(false)
  const [regenError, setRegenError] = useState('')
  const [regenSuccess, setRegenSuccess] = useState('')
  const [regenConfirmOpen, setRegenConfirmOpen] = useState(false)

  useEffect(() => {
    if (!workout?.id || !workout?.date) return
    let cancelled = false
    api(`/api/ai-reports?date=${workout.date}&type=next_advice`)
      .then((data) => {
        if (cancelled) return
        const mine = (data.reports || []).find((r) => r.workout_id === workout.id)
        setReport(mine || null)
        setLoaded(true)
      })
      .catch(() => {
        if (!cancelled) setLoaded(true)
      })
    return () => {
      cancelled = true
    }
  }, [workout?.id, workout?.date])

  useEffect(() => {
    if (!regenSuccess) return
    const t = setTimeout(() => setRegenSuccess(''), 3000)
    return () => clearTimeout(t)
  }, [regenSuccess])

  const { markdown, advice } = useMemo(
    () => parseNextAdvice(report?.content_md),
    [report],
  )
  const grouped = useMemo(() => groupSuggestions(advice), [advice])

  if (!loaded) return null
  if (!report) {
    return (
      <EmptyState
        title="暂无下次训练建议"
        description="完成本次训练点评后将生成下次建议"
      />
    )
  }

  const handleRegen = async () => {
    setRegenConfirmOpen(false)
    if (regenLoading) return
    setRegenLoading(true)
    setRegenError('')
    try {
      const data = await api(
        `/api/ai-reports/next_advice/${workout.id}/regenerate_with_feedback`,
        { method: 'POST' },
      )
      if (data?.report) setReport(data.report)
      setRegenSuccess('已根据讨论重新生成')
    } catch (err) {
      setRegenError(regenErrorMessage(err))
    } finally {
      setRegenLoading(false)
    }
  }

  return (
    <Card className="space-y-4">
      <h3 className="text-base font-bold text-gray-900">下次训练建议</h3>

      {markdown && <SimpleMarkdown text={markdown} />}

      {advice && (
        <div className="grid gap-4 md:grid-cols-2">
          <div data-testid="auto-writable-block">
            <h4 className="mb-2 text-sm font-bold text-green-700">可自动写回</h4>
            {grouped.auto_writable.length === 0 ? (
              <p className="text-xs text-gray-600">无</p>
            ) : (
              <ul className="space-y-2">
                {grouped.auto_writable.map((s, i) => (
                  <SuggestionCard key={i} suggestion={s} index={i} autoWritable workout={workout} />
                ))}
              </ul>
            )}
          </div>
          <div data-testid="manual-block">
            <h4 className="mb-2 text-sm font-bold text-amber-700">需手动调整</h4>
            {grouped.manual.length === 0 ? (
              <p className="text-xs text-gray-600">无</p>
            ) : (
              <ul className="space-y-2">
                {grouped.manual.map((s, i) => (
                  <SuggestionCard key={i} suggestion={s} index={i} autoWritable={false} workout={workout} />
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      <ReportChatSection reportId={report.id} />
      <Button
        variant="secondary"
        testId="regen-advice-btn"
        disabled={regenLoading}
        onClick={() => setRegenConfirmOpen(true)}
        className="text-xs"
      >
        {regenLoading ? '重新生成中…' : '重新生成下次建议'}
      </Button>
      {regenSuccess && (
        <p data-testid="regen-success" className="text-xs text-green-600">
          {regenSuccess}
        </p>
      )}
      {regenError && (
        <p data-testid="regen-error" className="text-xs text-red-600">
          {regenError}
        </p>
      )}
      <ConfirmDialog
        open={regenConfirmOpen}
        title="将根据以上讨论重新生成下次建议并覆盖当前内容，确认继续？"
        onConfirm={handleRegen}
        onCancel={() => setRegenConfirmOpen(false)}
      />
    </Card>
  )
}
