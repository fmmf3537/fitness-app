import { useEffect, useRef } from 'react'
import Button from './ui/Button'
import { useSyncTask, syncResultText } from './useSyncTask'

export default function SyncButton({ onSynced }) {
  const { task, checking, submitting, queryError, startError, revision, start, refresh } = useSyncTask()
  const seen = useRef(revision)
  useEffect(() => {
    if (seen.current !== revision) {
      seen.current = revision
      // A failed sync may have imported some records too.
      onSynced?.()
    }
  }, [revision, onSynced])
  const running = task?.running
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <Button variant="primary" ariaLabel="同步今日" onClick={start}
        disabled={checking || submitting || running || !!queryError || !task}>
        {submitting ? '正在发起…' : running ? '同步中…' : checking && !task ? '查询同步状态…' : '同步今日'}
      </Button>
      {running && <span role="status" className="min-w-0 text-sm text-gray-600 dark:text-gray-400 max-md:w-full">
        {task.date || '当前任务'} 同步中，可继续浏览其他页面。
      </span>}
      {!queryError && !running && task?.status && <p role={task.status === 'failed' ? 'alert' : 'status'}
        className={`min-w-0 text-sm max-md:w-full ${task.status === 'failed' ? 'text-red-600' : 'text-gray-600 dark:text-gray-400'}`}>
        最近一次任务{task.date ? `（${task.date}）` : ''}：{syncResultText(task)}
        {task.finished_at && <span className="block">结束时间（服务端记录）：{task.finished_at.replace('T', ' ')}</span>}
      </p>}
      {!queryError && task?.status === null && <span className="min-w-0 text-sm text-gray-600 dark:text-gray-400 max-md:w-full">服务端暂无最近任务记录</span>}
      {queryError && <div><p role="alert" className="text-sm text-amber-700 dark:text-amber-300">{queryError}</p>
        <Button variant="secondary" onClick={refresh} disabled={checking}>重新查询状态</Button></div>}
      {startError && !queryError && <p role="alert" className="text-sm text-amber-700 dark:text-amber-300">{startError}</p>}
    </div>
  )
}
