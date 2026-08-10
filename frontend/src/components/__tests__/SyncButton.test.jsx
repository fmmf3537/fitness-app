import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SyncButton from '../SyncButton'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

/** 安装 fetch mock：POST /api/sync/{today} 与 GET /api/sync/status（statusQueue 轮询出队）。 */
function setupFetch({ statusQueue = [], postData = { status: 'started', date: '2026-08-10' }, postStatus = 200 } = {}) {
  const calls = []
  globalThis.fetch = vi.fn((url, options = {}) => {
    calls.push({ url: String(url), method: options.method || 'GET' })
    if (String(url).startsWith('/api/sync/status')) {
      const next = statusQueue.length > 1 ? statusQueue.shift() : statusQueue[0]
      return Promise.resolve(mockResponse(next))
    }
    return Promise.resolve(mockResponse(postData, postStatus))
  })
  return calls
}

const RUNNING = { running: true, status: 'running', date: '2026-08-10', error: null, result: null }
const SUCCESS = {
  running: false, status: 'success', date: '2026-08-10', error: null,
  result: { date: '2026-08-10', status: 'success', error: null, detail: { workouts: 2, candidates: 1 } },
}
const FAILED_429 = {
  running: false, status: 'failed', date: '2026-08-10',
  error: 'RuntimeError: garmin 429 too many requests', result: null,
}

async function clickSync() {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '立即同步' }))
  })
}

async function advance(ms) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe('SyncButton', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-10T12:00:00+08:00'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('点击后立即 POST 当日同步并显示加载文案，同步中防重复点击', async () => {
    const calls = setupFetch({ statusQueue: [RUNNING] })
    render(<SyncButton />)

    await clickSync()

    expect(calls).toEqual([{ url: '/api/sync/2026-08-10', method: 'POST' }])
    expect(screen.getByText('同步中（约 1-2 分钟，含 AI 点评生成）')).toBeInTheDocument()

    const btn = screen.getByRole('button', { name: '立即同步' })
    expect(btn).toBeDisabled()
    await clickSync()
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
  })

  it('每 3s 轮询状态，成功后 toast 摘要并回调刷新', async () => {
    const calls = setupFetch({ statusQueue: [RUNNING, SUCCESS] })
    const onSynced = vi.fn()
    render(<SyncButton onSynced={onSynced} />)

    await clickSync()
    expect(calls.filter((c) => c.url === '/api/sync/status')).toHaveLength(0)

    // 第一次轮询：running → 继续同步中
    await advance(3000)
    expect(calls.filter((c) => c.url === '/api/sync/status')).toHaveLength(1)
    expect(screen.getByText('同步中（约 1-2 分钟，含 AI 点评生成）')).toBeInTheDocument()

    // 第二次轮询：success → toast + 回调
    await advance(3000)
    expect(calls.filter((c) => c.url === '/api/sync/status')).toHaveLength(2)
    expect(screen.getByText('同步完成：训练 2 条，待确认 1 条')).toBeInTheDocument()
    expect(onSynced).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: '立即同步' })).not.toBeDisabled()
  })

  it('同步失败展示错误，佳明 429 给出针对性提示', async () => {
    setupFetch({ statusQueue: [FAILED_429] })
    render(<SyncButton />)

    await clickSync()
    await advance(3000)

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('同步失败')
    expect(alert).toHaveTextContent('佳明接口限频')
    expect(screen.getByRole('button', { name: '立即同步' })).not.toBeDisabled()
  })

  it('POST 返回 409 时提示已有同步进行中', async () => {
    setupFetch({ postStatus: 409, postData: { detail: '已有同步任务进行中' } })
    render(<SyncButton />)

    await clickSync()

    expect(screen.getByRole('alert')).toHaveTextContent('已有同步任务进行中')
    expect(screen.getByRole('button', { name: '立即同步' })).not.toBeDisabled()
  })
})
