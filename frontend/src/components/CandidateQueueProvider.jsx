import { useCallback, useEffect, useRef, useState } from 'react'
import { api, getToken } from '../api/client'
import { CandidateQueueContext } from './useCandidateQueue'
import { useSyncTask } from './useSyncTask'

const initialState = { candidates: null, loading: true, refreshing: false, error: '' }

/** Single source of truth for the authenticated user's pending match candidates. */
export default function CandidateQueueProvider({ children }) {
  const [state, setState] = useState(initialState)
  const requestId = useRef(0)
  const actions = useRef(null)
  const { revision: syncRevision } = useSyncTask()
  const seenSyncRevision = useRef(syncRevision)

  useEffect(() => {
    const token = getToken()
    let alive = true
    const valid = () => alive && getToken() === token

    async function refresh() {
      if (!valid()) return
      const id = ++requestId.current
      setState((s) => ({
        ...s,
        loading: s.candidates === null,
        refreshing: s.candidates !== null,
        error: '',
      }))
      try {
        const data = await api('/api/match-candidates')
        if (!valid() || id !== requestId.current) return
        const candidates = (data.candidates || []).filter((candidate) => candidate.status === 'pending')
        setState({ candidates, loading: false, refreshing: false, error: '' })
      } catch (error) {
        if (!valid() || id !== requestId.current) return
        setState((s) => ({
          ...s,
          loading: false,
          refreshing: false,
          error: error.message || '待确认记录加载失败',
        }))
      }
    }

    function removeCandidate(id) {
      if (!valid()) return
      // Invalidate a slower list response that started before this mutation.
      requestId.current += 1
      setState((s) => ({
        ...s,
        candidates: s.candidates?.filter((candidate) => candidate.id !== id) ?? [],
        loading: false,
        refreshing: false,
        error: '',
      }))
    }

    const resume = () => {
      if (document.visibilityState !== 'hidden') refresh()
    }
    actions.current = { refresh, removeCandidate }
    setState(initialState)
    refresh()
    window.addEventListener('focus', resume)
    document.addEventListener('visibilitychange', resume)
    return () => {
      alive = false
      requestId.current += 1
      actions.current = null
      window.removeEventListener('focus', resume)
      document.removeEventListener('visibilitychange', resume)
    }
  }, [])

  useEffect(() => {
    if (seenSyncRevision.current === syncRevision) return
    seenSyncRevision.current = syncRevision
    actions.current?.refresh()
  }, [syncRevision])

  const refresh = useCallback(() => actions.current?.refresh(), [])
  const removeCandidate = useCallback((id) => actions.current?.removeCandidate(id), [])
  return (
    <CandidateQueueContext.Provider
      value={{ ...state, pendingCount: state.candidates?.length ?? null, refresh, removeCandidate }}
    >
      {children}
    </CandidateQueueContext.Provider>
  )
}
