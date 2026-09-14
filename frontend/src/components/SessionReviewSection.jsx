import { useEffect, useState } from 'react'
import { api } from '../api/client'
import ReportChatSection from './ReportChatSection'
import SharePosterButton from './SharePosterButton'
import SimpleMarkdown from './SimpleMarkdown'
import Button from './ui/Button'
import Card from './ui/Card'
import ConfirmDialog from './ui/ConfirmDialog'

// V4-6：统一的中文护栏提示（按 status 映射，避免依赖 api() 对 4xx detail 的提取）
const REGEN_ERROR_MAP = {
  429: '今日重生成次数已达上限（5 次），明天再来',
  422: '无训记计划缓存，暂时无法生成下次建议',
  404: '无法重新生成：记录不存在',
}

function regenErrorMessage(err) {
  const status = err?.status
  return REGEN_ERROR_MAP[status] || err?.message || '重新生成失败，请稍后重试'
}

/**
 * V2-7b 缺陷4：单次训练点评（session_review）展示区块。
 * 进入页面时按 date+type 拉取报告，取本 workout 对应的一条展示 Markdown 正文；
 * 无报告时不渲染任何内容（与 NextAdviceSection 并列使用）。
 * V4-6：内嵌对话 + 「根据以上讨论重新生成」按钮。
 */
export default function SessionReviewSection({ workout }) {
  const [report, setReport] = useState(null)
  const [loaded, setLoaded] = useState(false)
  const [regenLoading, setRegenLoading] = useState(false)
  const [regenError, setRegenError] = useState('')
  const [regenSuccess, setRegenSuccess] = useState('')
  const [regenConfirmOpen, setRegenConfirmOpen] = useState(false)

  useEffect(() => {
    if (!workout?.id || !workout?.date) return
    let cancelled = false
    api(`/api/ai-reports?date=${workout.date}&type=session_review`)
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

  if (!loaded || !report) return null

  const handleRegen = async () => {
    setRegenConfirmOpen(false)
    if (regenLoading) return
    setRegenLoading(true)
    setRegenError('')
    try {
      const data = await api(
        `/api/ai-reports/session_review/${workout.id}/regenerate_with_feedback`,
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
    <Card className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-base font-bold text-gray-900 dark:text-gray-100">本次训练点评</h3>
        <SharePosterButton key={report.id} report={report} workout={workout} />
      </div>
      <SimpleMarkdown text={report.content_md} />
      <ReportChatSection reportId={report.id} />
      <Button
        variant="secondary"
        testId="regen-review-btn"
        disabled={regenLoading}
        onClick={() => setRegenConfirmOpen(true)}
        className="text-xs"
      >
        {regenLoading ? '重新生成中…' : '根据以上讨论重新生成'}
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
        title="将根据以上讨论重新生成点评并覆盖当前内容，确认继续？"
        onConfirm={handleRegen}
        onCancel={() => setRegenConfirmOpen(false)}
      />
    </Card>
  )
}
