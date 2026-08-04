import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CandidatesPage from '../CandidatesPage'

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

function setupFetch(candidates) {
  globalThis.fetch = vi.fn((url) => {
    if (String(url).includes('/resolve')) {
      return Promise.resolve(
        mockResponse({ ok: true, candidate: {}, workout_ids: [1] }),
      )
    }
    return Promise.resolve(mockResponse({ candidates }))
  })
}

describe('CandidatesPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
  })

  it('渲染候选列表，显示两侧信息', async () => {
    setupFetch([CANDIDATE_BOTH])
    render(
      <MemoryRouter>
        <CandidatesPage />
      </MemoryRouter>,
    )
    expect(await screen.findByText('胸')).toBeInTheDocument()
    expect(screen.getByText('力量训练')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '合并' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保持分开' })).toBeInTheDocument()
  })

  it('点击「合并」调用 resolve API 并移除该条', async () => {
    setupFetch([CANDIDATE_BOTH])
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <CandidatesPage />
      </MemoryRouter>,
    )
    await screen.findByTestId('candidate-1')
    await user.click(screen.getByRole('button', { name: '合并' }))

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
    render(
      <MemoryRouter>
        <CandidatesPage />
      </MemoryRouter>,
    )
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

  it('xunji_train 为 null 的候选只显示「保持分开」', async () => {
    setupFetch([CANDIDATE_GARMIN_ONLY])
    render(
      <MemoryRouter>
        <CandidatesPage />
      </MemoryRouter>,
    )
    expect(await screen.findByTestId('candidate-2')).toBeInTheDocument()
    expect(screen.getByText('无训记记录')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '合并' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保持分开' })).toBeInTheDocument()
  })
})
