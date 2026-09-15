import { render as renderUI, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CandidatesPage from '../CandidatesPage'
import CandidateQueueProvider from '../../components/CandidateQueueProvider'
import { SyncTaskContext } from '../../components/useSyncTask'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const CANDIDATE_BOTH = {
  id: 1,
  reason: 'time_close',
  status: 'pending',
  created_at: '2026-08-03T12:00:00',
  workout_id: null,
  xunji_train: {
    id: 1,
    datestr: '2026-08-03',
    title: '胸',
    start_ms: 1754224800000,
    end_ms: 1754228400000,
  },
  garmin_activity: {
    id: 2,
    activity_id: 'g1',
    activity_type: 'strength_training',
    name: '力量训练',
    start_ts: '2026-08-03T10:05:00',
    end_ts: '2026-08-03T11:00:00',
    duration_s: 3300,
    calories: 300,
    avg_hr: 118,
    max_hr: 150,
  },
}

const CANDIDATE_GARMIN_ONLY = {
  ...CANDIDATE_BOTH,
  id: 2,
  reason: 'garmin_only_strength',
  xunji_train: null,
}

const MERGE_PREVIEW = {
  candidate_id: 1,
  workout: {
    date: '2026-08-03', title: '胸', match_status: 'manual_matched',
    tags: 'strength_training', duration_s: 3300, calories: 300,
    avg_hr: 118, max_hr: 150,
    movements: [{ name: '杠铃卧推', sets: [{ weight: 80, reps: 8 }] }],
    heart_rate: [{ t: 0, hr: 100 }, { t: 1, hr: 130 }],
  },
  field_sources: {
    date: 'xunji', title: 'xunji', movements: 'xunji', tags: 'garmin', duration_s: 'garmin',
    calories: 'garmin', avg_hr: 'garmin', max_hr: 'garmin', heart_rate: 'garmin',
  },
}

function setupFetch(candidates) {
  let pending = candidates
  globalThis.fetch = vi.fn((url) => {
    if (String(url).includes('/preview')) {
      return Promise.resolve(mockResponse(MERGE_PREVIEW))
    }
    if (String(url).includes('/resolve')) {
      const id = Number(String(url).match(/candidates\/(\d+)/)?.[1])
      pending = pending.filter((candidate) => candidate.id !== id)
      return Promise.resolve(
        mockResponse({ ok: true, candidate: {}, workout_ids: [1] }),
      )
    }
    return Promise.resolve(mockResponse({ candidates: pending }))
  })
}

function render(ui) {
  return renderUI(
    <MemoryRouter>
      <SyncTaskContext.Provider value={{ revision: 0 }}>
        <CandidateQueueProvider>{ui}</CandidateQueueProvider>
      </SyncTaskContext.Provider>
    </MemoryRouter>,
  )
}

describe('CandidatesPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
  })

  it('渲染候选列表，显示两侧信息', async () => {
    setupFetch([CANDIDATE_BOTH])
    render(<CandidatesPage />)
    expect(await screen.findByText('胸')).toBeInTheDocument()
    expect(screen.getByText('力量训练')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '合并' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保持分开' })).toBeInTheDocument()
  })

  it('点击「合并」先读取真实预览，确认后才调用 resolve API', async () => {
    setupFetch([CANDIDATE_BOTH])
    const user = userEvent.setup()
    render(<CandidatesPage />)
    await screen.findByTestId('candidate-1')
    await user.click(screen.getByRole('button', { name: '合并' }))

    expect(await screen.findByTestId('merge-preview')).toBeInTheDocument()
    expect(screen.getByText('杠铃卧推')).toBeInTheDocument()
    expect(screen.getByText('真实佳明心率序列 · 2 个采样点')).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/match-candidates/1/preview', expect.any(Object),
    )
    expect(globalThis.fetch).not.toHaveBeenCalledWith(
      '/api/match-candidates/1/resolve', expect.any(Object),
    )
    await user.click(screen.getByRole('button', { name: '确认合并' }))

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/match-candidates/1/resolve',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ action: 'merge' }),
        }),
      )
    })
    await waitFor(() => {
      expect(screen.queryByTestId('candidate-1')).not.toBeInTheDocument()
    })
  })

  it('点击「保持分开」以 action=split 调用', async () => {
    setupFetch([CANDIDATE_BOTH])
    const user = userEvent.setup()
    render(<CandidatesPage />)
    await screen.findByTestId('candidate-1')
    await user.click(screen.getByRole('button', { name: '保持分开' }))

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/match-candidates/1/resolve',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ action: 'split' }),
        }),
      )
    })
    await waitFor(() => {
      expect(screen.queryByTestId('candidate-1')).not.toBeInTheDocument()
    })
  })

  it('确认合并失败时保留预览并显示服务端错误', async () => {
    globalThis.fetch = vi.fn((url) => {
      if (String(url).includes('/preview')) return Promise.resolve(mockResponse(MERGE_PREVIEW))
      if (String(url).includes('/resolve')) return Promise.resolve(mockResponse({ detail: '写入失败' }, 500))
      return Promise.resolve(mockResponse({ candidates: [CANDIDATE_BOTH] }))
    })
    const user = userEvent.setup()
    render(<CandidatesPage />)
    await user.click(await screen.findByRole('button', { name: '合并' }))
    await user.click(await screen.findByRole('button', { name: '确认合并' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('合并失败：写入失败')
    expect(screen.getByTestId('merge-preview')).toBeInTheDocument()
  })

  it('xunji_train 为 null 的候选只显示「保持分开」', async () => {
    setupFetch([CANDIDATE_GARMIN_ONLY])
    render(<CandidatesPage />)
    expect(await screen.findByTestId('candidate-2')).toBeInTheDocument()
    expect(screen.getByText('无训记记录')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '合并' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保持分开' })).toBeInTheDocument()
  })

  it('候选已被其他页面处理时重新查询并移除旧卡片', async () => {
    let listCalls = 0
    globalThis.fetch = vi.fn((url) => {
      if (String(url).includes('/preview')) {
        return Promise.resolve(mockResponse({ detail: '候选已处理' }, 409))
      }
      if (String(url).includes('/resolve')) {
        return Promise.resolve(mockResponse({ detail: '候选已处理' }, 409))
      }
      listCalls += 1
      return Promise.resolve(mockResponse({ candidates: listCalls === 1 ? [CANDIDATE_BOTH] : [] }))
    })
    const user = userEvent.setup()
    render(<CandidatesPage />)
    await screen.findByTestId('candidate-1')
    await user.click(screen.getByRole('button', { name: '合并' }))
    await waitFor(() => expect(screen.queryByTestId('candidate-1')).not.toBeInTheDocument())
    expect(await screen.findByText('没有待确认的候选')).toBeInTheDocument()
    expect(listCalls).toBe(2)
  })
})
