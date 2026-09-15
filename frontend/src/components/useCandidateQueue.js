import { createContext, useContext } from 'react'

export const CandidateQueueContext = createContext(null)

export function useCandidateQueue() {
  const queue = useContext(CandidateQueueContext)
  if (!queue) throw new Error('CandidateQueueProvider is required')
  return queue
}
