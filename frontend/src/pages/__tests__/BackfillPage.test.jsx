import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import BackfillPage from '../BackfillPage'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

function statusBody({ running, phase, percent = 0, eta = 0, overrides = {} }) {
  return {
    running,
    phase,
    started_at: '2026-08-07T10:00:00',
    finished_at: running ? null : '2026-08-07T11:00:00',
    error: null,
    errors: [],
    percent,
    eta_seconds: eta,
    details: {
      xunji: { done: 10, total: 100 },
      garmin_activities: { finished: false, pages: 3, activities: 250 },
      garmin_daily: { done: 5, total: 100 },
      fusion: { done: 0, total: 0 },
      ...overrides,
    },
  }
}

const IDLE_STATUS = statusBody({ running: false, phase: 'idle' })

function installFetch(statusQueue = []) {
  // statusQueue：除首次外的后续 GET /status 依次返回；用完后循环最后一个
  let calls = 0
  globalThis.fetch = vi.fn((url, options = {}) => {
    if (url === '/api/backfill/start' && options.method === 'POST') {
      return Promise.resolve(mockResponse({ started: true, message: 'backfill 已启动' }))
    }
    if (url === '/api/backfill/status') {
      const body = calls === 0 ? IDLE_STATUS : statusQueue[Math.min(calls - 1, statusQueue.length - 1)] || IDLE_STATUS
      calls += 1
      return Promise.resolve(mockResponse(body))
    }
    return Promise.resolve(mockResponse({ detail: 'not found' }, 404))
  })
}

describe('BackfillPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    vi.useFakeTimers({ shouldAdvanceTime: true })
    installFetch()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('进入页面展示当前状态与各 source 进度', async () => {
    render(<BackfillPage />)
    expect(await screen.findByTestId('backfill-status')).toBeInTheDocument()
    expect(screen.getByTestId('progress-xunji')).toBeInTheDocument()
    expect(screen.getByTestId('progress-garmin_activity')).toBeInTheDocument()
    expect(screen.getByTestId('progress-garmin_daily')).toBeInTheDocument()
    expect(screen.getByTestId('progress-fusion')).toBeInTheDocument()
    expect(screen.getByTestId('progress-xunji').textContent).toContain('10 / 100')
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/backfill/status',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
  })

  it('点击开始导入发起 POST 并每 3 秒轮询，running 结束后停止', async () => {
    installFetch([
      statusBody({ running: true, phase: 'xunji', percent: 7.0 }),
      statusBody({ running: false, phase: 'done', percent: 100 }),
    ])
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<BackfillPage />)
    await screen.findByTestId('backfill-status')

    await user.click(screen.getByTestId('backfill-start'))
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/backfill/start',
      expect.objectContaining({ method: 'POST' }),
    )

    const statusCalls = () =>
      globalThis.fetch.mock.calls.filter(([url]) => url === '/api/backfill/status').length

    // 挂载时 1 次 + 启动后 3s 第一次轮询
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    expect(statusCalls()).toBe(2)
    expect(screen.getByTestId('backfill-status').textContent).toContain('运行中')

    // 第二次轮询返回 running=false → 停止轮询
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    expect(statusCalls()).toBe(3)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000)
    })
    expect(statusCalls()).toBe(3)
  })

  it('状态请求失败显示错误提示', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ detail: 'boom' }, 500)))
    render(<BackfillPage />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
