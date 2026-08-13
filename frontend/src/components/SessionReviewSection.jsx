import { useEffect, useState } from 'react'
import { api } from '../api/client'
import SharePosterButton from './SharePosterButton'
import SimpleMarkdown from './SimpleMarkdown'

/**
 * V2-7b 缺陷4：单次训练点评（session_review）展示区块。
 * 进入页面时按 date+type 拉取报告，取本 workout 对应的一条展示 Markdown 正文；
 * 无报告时不渲染任何内容（与 NextAdviceSection 并列使用）。
 */
export default function SessionReviewSection({ workout }) {
  const [report, setReport] = useState(null)
  const [loaded, setLoaded] = useState(false)

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

  if (!loaded || !report) return null

  return (
    <section className="space-y-2 rounded-lg bg-white p-4 shadow">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-base font-bold text-gray-900">本次训练点评</h3>
        <SharePosterButton report={report} workout={workout} />
      </div>
      <SimpleMarkdown text={report.content_md} />
    </section>
  )
}
