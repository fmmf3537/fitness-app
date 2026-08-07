import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { formatParams, groupSuggestions, parseNextAdvice } from '../utils/nextAdvice'

const MANUAL_GUIDE =
  '训记 App 操作路径：打开训记 App → 计划 → 找到对应训练日 → 长按动作修改重量/组数/次数后保存。'

function SimpleMarkdown({ text }) {
  return (
    <div className="space-y-2">
      {(text || '').split('\n').map((line, i) => {
        if (line.startsWith('## ')) {
          return (
            <h3 key={i} className="text-base font-bold text-gray-900">
              {line.slice(3)}
            </h3>
          )
        }
        if (line.startsWith('# ')) {
          return (
            <h3 key={i} className="text-lg font-bold text-gray-900">
              {line.slice(2)}
            </h3>
          )
        }
        if (line.trim() === '') return null
        return (
          <p key={i} className="text-sm text-gray-800">
            {line}
          </p>
        )
      })}
    </div>
  )
}

function SuggestionCard({ suggestion, index, autoWritable }) {
  const [previewOpen, setPreviewOpen] = useState(false)
  return (
    <li className="rounded-md border border-gray-200 p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-gray-900">{suggestion.movement}</p>
          <p className="mt-1 text-xs text-gray-600">
            原参数：{formatParams(suggestion.original)} → 建议：{formatParams(suggestion.suggested)}
          </p>
          <p className="mt-1 text-xs text-gray-500">{suggestion.reason}</p>
        </div>
        {autoWritable && (
          <button
            type="button"
            onClick={() => setPreviewOpen((v) => !v)}
            className="shrink-0 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
          >
            生成写回预览
          </button>
        )}
      </div>
      {autoWritable && previewOpen && (
        <div
          data-testid={`writeback-preview-${index}`}
          className="mt-2 rounded-md bg-gray-50 p-3 text-xs text-gray-700"
        >
          <p className="font-medium text-gray-800">写回预览（本地生成，确认写回功能将在 V1-5 上线）</p>
          <p className="mt-1">原值：{JSON.stringify(suggestion.original)}</p>
          <p className="mt-1">新值：{JSON.stringify(suggestion.suggested)}</p>
        </div>
      )}
      {!autoWritable && (
        <p className="mt-2 rounded-md bg-amber-50 p-2 text-xs text-amber-800">{MANUAL_GUIDE}</p>
      )}
    </li>
  )
}

export default function NextAdviceSection({ workout }) {
  const [report, setReport] = useState(null)
  const [loaded, setLoaded] = useState(false)

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

  const { markdown, advice } = useMemo(
    () => parseNextAdvice(report?.content_md),
    [report],
  )
  const grouped = useMemo(() => groupSuggestions(advice), [advice])

  if (!loaded) return null
  if (!report) {
    return <p className="text-sm text-gray-500">暂无下次训练建议</p>
  }

  return (
    <section className="space-y-4 rounded-lg bg-white p-4 shadow">
      <h3 className="text-base font-bold text-gray-900">下次训练建议</h3>

      {markdown && <SimpleMarkdown text={markdown} />}

      {advice && (
        <div className="grid gap-4 md:grid-cols-2">
          <div data-testid="auto-writable-block">
            <h4 className="mb-2 text-sm font-bold text-green-700">可自动写回</h4>
            {grouped.auto_writable.length === 0 ? (
              <p className="text-xs text-gray-500">无</p>
            ) : (
              <ul className="space-y-2">
                {grouped.auto_writable.map((s, i) => (
                  <SuggestionCard key={i} suggestion={s} index={i} autoWritable />
                ))}
              </ul>
            )}
          </div>
          <div data-testid="manual-block">
            <h4 className="mb-2 text-sm font-bold text-amber-700">需手动调整</h4>
            {grouped.manual.length === 0 ? (
              <p className="text-xs text-gray-500">无</p>
            ) : (
              <ul className="space-y-2">
                {grouped.manual.map((s, i) => (
                  <SuggestionCard key={i} suggestion={s} index={i} autoWritable={false} />
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
