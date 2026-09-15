import { useCallback, useContext, useEffect, useRef, useState } from 'react'
import { api, getToken } from '../api/client'
import { ToastContext } from './ui/useToast'
import { SyncTaskContext, syncResultText } from './useSyncTask'

const initialState = { task: null, checking: true, submitting: false, queryError: '', startError: '', revision: 0 }
const INTERVAL = 3000

/** Owned by the authenticated layout, not by a page or button. No task state is persisted locally. */
export default function SyncTaskProvider({ children }) {
  const [state, setState] = useState(initialState)
  const actions = useRef(null)
  const toast = useContext(ToastContext)?.toast
  useEffect(() => {
    const token = getToken()
    const abort = new AbortController()
    let alive = true
    let timer
    let reading = null
    let submitting = false
    let known = false
    let lastTask = null
    let awaitingResult = false
    let terminalKey = null
    let uncertainBaseline = null
    const valid = () => alive && getToken() === token
    const update = (patch) => { if (valid()) setState((s) => ({ ...s, ...patch })) }
    const schedule = () => {
      clearTimeout(timer)
      if (valid()) timer = setTimeout(() => read(), INTERVAL)
    }
    function read() {
      if (!valid()) return Promise.resolve()
      if (reading) return reading
      clearTimeout(timer)
      update({ checking: true })
      reading = (async () => {
        try {
          const task = await api('/api/sync/status', { signal: abort.signal })
          if (!valid()) return
          if (!task || typeof task.running !== 'boolean' || ![null, 'running', 'success', 'failed'].includes(task.status)) {
            throw new Error('invalid sync status')
          }
          if (task.running !== (task.status === 'running')) throw new Error('inconsistent sync status')
          if (awaitingResult && task.status === null) throw new Error('task status unavailable')
          known = true
          lastTask = task
          update({ task, queryError: '' })
          if (task.running) {
            uncertainBaseline = null
            update({ startError: '' })
            awaitingResult = true
            schedule()
          } else if (task.status) {
            const key = JSON.stringify([task.date, task.started_at, task.finished_at, task.status, task.result])
            if (awaitingResult && uncertainBaseline && key === uncertainBaseline) {
              throw new Error('sync start result unavailable')
            }
            if (awaitingResult && key !== terminalKey) {
              setState((s) => ({ ...s, revision: s.revision + 1 }))
              toast?.(syncResultText(task), task.status === 'failed' ? 'error' : task.result?.detail?.ai_reviews_failed ? 'info' : 'success')
            }
            terminalKey = key
            uncertainBaseline = null
            awaitingResult = false
          }
        } catch {
          if (!valid()) return
          known = false
          update({ queryError: '暂时无法确认同步状态，正在重试查询。请勿重复发起同步。' })
          schedule()
        } finally {
          reading = null
          update({ checking: false })
        }
      })()
      return reading
    }
    async function start() {
      if (!valid() || submitting || reading || !known || lastTask?.running) return
      submitting = true
      clearTimeout(timer)
      update({ submitting: true, startError: '' })
      const now = new Date()
      const day = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
      try {
        await api(`/api/sync/${day}`, { method: 'POST', signal: abort.signal })
        if (!valid()) return
        awaitingResult = true
      } catch (error) {
        if (!valid()) return
        awaitingResult = true
        uncertainBaseline = terminalKey
        if (error.status !== 409) {
          update({ startError: '同步请求未确认成功，正在查询服务端状态；确认结果前不会重复发起。' })
        }
      } finally {
        submitting = false
        update({ submitting: false })
      }
      if (valid()) await read()
    }
    const resume = () => {
      if (document.visibilityState !== 'hidden' && !submitting) read()
    }
    actions.current = { start, refresh: resume }
    setState(initialState)
    read()
    window.addEventListener('focus', resume)
    document.addEventListener('visibilitychange', resume)
    return () => {
      alive = false
      abort.abort()
      clearTimeout(timer)
      actions.current = null
      window.removeEventListener('focus', resume)
      document.removeEventListener('visibilitychange', resume)
    }
  }, [toast])
  const start = useCallback(() => actions.current?.start(), [])
  const refresh = useCallback(() => actions.current?.refresh(), [])
  return <SyncTaskContext.Provider value={{ ...state, start, refresh }}>{children}</SyncTaskContext.Provider>
}
