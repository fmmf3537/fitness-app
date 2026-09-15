import { createContext, useContext } from 'react'

export const SyncTaskContext = createContext(null)
export function useSyncTask() {
  const task = useContext(SyncTaskContext)
  if (!task) throw new Error('SyncTaskProvider is required')
  return task
}
export function syncResultText(task) {
  if (task.status === 'failed') {
    const error = task.error || '未知错误'
    return `同步失败：${error}${/429|too many|too frequent/i.test(error) ? '（数据来源接口限频，请稍后重试）' : ''}`
  }
  const detail = task.result?.detail || {}
  const counts = [detail.workouts != null ? `训练 ${detail.workouts} 条` : '',
    detail.candidates != null ? `本次匹配产生候选 ${detail.candidates} 条` : ''].filter(Boolean).join('，')
  return `数据同步完成${counts ? `：${counts}` : ''}${detail.ai_reviews_failed ? '；AI 点评或下次建议未完成' : ''}`
}
