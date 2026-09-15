import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CandidateQueueProvider from '../CandidateQueueProvider'
import { useCandidateQueue } from '../useCandidateQueue'
import { SyncTaskContext } from '../useSyncTask'
import { api } from '../../api/client'

vi.mock('../../api/client', () => ({ api: vi.fn(), getToken: () => localStorage.getItem('fh_token') }))
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
const candidates = (...ids) => ({ candidates: ids.map((id) => ({ id, status: 'pending' })) })

function Probe() {
  const queue = useCandidateQueue()
  return <div>
    <span data-testid="count">{queue.pendingCount == null ? 'unknown' : queue.pendingCount}</span>
    <span data-testid="error">{queue.error}</span>
    <button onClick={queue.refresh}>刷新</button>
    <button onClick={() => queue.removeCandidate(1)}>移除 1</button>
  </div>
}

function App({ revision = 0 }) {
  return <SyncTaskContext.Provider value={{ revision }}>
    <CandidateQueueProvider><Probe /></CandidateQueueProvider>
  </SyncTaskContext.Provider>
}

describe('CandidateQueueProvider', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    api.mockReset()
  })

  it('只统计真实 pending 候选', async () => {
    api.mockResolvedValue({ candidates: [{ id: 1, status: 'pending' }, { id: 2, status: 'merged' }] })
    await act(async () => { render(<App />) })
    expect(screen.getByTestId('count')).toHaveTextContent('1')
  })

  it('同步任务完成后重新查询队列', async () => {
    api.mockResolvedValueOnce(candidates(1)).mockResolvedValue(candidates(1, 2))
    let view
    await act(async () => { view = render(<App />) })
    expect(screen.getByTestId('count')).toHaveTextContent('1')
    await act(async () => { view.rerender(<App revision={1} />) })
    expect(screen.getByTestId('count')).toHaveTextContent('2')
  })

  it('本地处理结果不会被更早的列表响应覆盖', async () => {
    const oldRead = deferred()
    api.mockReturnValueOnce(oldRead.promise)
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: '移除 1' }))
    expect(screen.getByTestId('count')).toHaveTextContent('0')
    await act(async () => { oldRead.resolve(candidates(1, 2)) })
    expect(screen.getByTestId('count')).toHaveTextContent('0')
  })

  it('刷新失败保留已有数量并显示错误', async () => {
    api.mockResolvedValueOnce(candidates(1)).mockRejectedValueOnce(new Error('offline'))
    await act(async () => { render(<App />) })
    await userEvent.click(screen.getByRole('button', { name: '刷新' }))
    expect(screen.getByTestId('count')).toHaveTextContent('1')
    expect(screen.getByTestId('error')).toHaveTextContent('offline')
  })
})
