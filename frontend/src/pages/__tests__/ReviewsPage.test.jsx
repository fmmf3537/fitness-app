import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReviewsPage from '../ReviewsPage'

vi.mock('echarts', () => ({
  init: () => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }),
}))

function mockResponse(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
    blob: async () => new Blob(['x']),
  }
}

const WEEKLY = {
  reports: [
    {
      id: 1,
      type: 'weekly',
      workout_id: null,
      date: '2026-08-03',
      period_end: '2026-08-09',
      workout_title: null,
      model: 'deepseek-chat',
      prompt_tokens: 500,
      completion_tokens: 300,
      cost_estimate: 0.002,
      content_md:
        '## 本周概览\n本周训练 3 次，总容量 4520 kg。\n' +
        '```echarts\n{"series":[{"type":"pie"}]}\n```\n' +
        '## 下周建议\n卧推加到 62.5kg',
      created_at: '2026-08-09T21:13:00',
    },
  ],
}

const MONTHLY = {
  reports: [
    {
      id: 2,
      type: 'monthly',
      workout_id: null,
      date: '2026-07-01',
      period_end: '2026-07-31',
      workout_title: null,
      model: 'deepseek-chat',
      prompt_tokens: 600,
      completion_tokens: 400,
      cost_estimate: 0.003,
      content_md: '## 月度概览\n计划完成率 83.3%。',
      created_at: '2026-08-01T09:23:00',
    },
  ],
}

function routeFetch(routes) {
  return vi.fn((url, options = {}) => {
    for (const [match, handler] of routes) {
      if (url.startsWith(match)) {
        return Promise.resolve(
          typeof handler === 'function' ? handler(url, options) : mockResponse(handler),
        )
      }
    }
    return Promise.resolve(mockResponse({ reports: [] }))
  })
}

describe('ReviewsPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date('2026-08-10T12:00:00'))
    URL.createObjectURL = vi.fn(() => 'blob:mock')
    URL.revokeObjectURL = vi.fn()
    HTMLAnchorElement.prototype.click = vi.fn()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('默认加载周复盘列表', async () => {
    globalThis.fetch = routeFetch([['/api/ai-reports?type=weekly', WEEKLY]])
    render(<ReviewsPage />)
    expect(await screen.findByText(/2026-08-03/)).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/ai-reports?type=weekly&limit=50',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
  })

  it('切换到月复盘标签加载月报', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([
      ['/api/ai-reports?type=weekly', WEEKLY],
      ['/api/ai-reports?type=monthly', MONTHLY],
    ])
    render(<ReviewsPage />)
    await screen.findByText(/2026-08-03/)

    await user.click(screen.getByTestId('tab-monthly'))
    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenLastCalledWith(
        '/api/ai-reports?type=monthly&limit=50',
        expect.any(Object),
      )
    })
    expect(await screen.findByText(/2026-07-01/)).toBeInTheDocument()
  })

  it('点击报告卡片显示详情与导出按钮，echarts 块渲染为图表', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([['/api/ai-reports?type=weekly', WEEKLY]])
    render(<ReviewsPage />)
    await screen.findByText(/2026-08-03/)

    await user.click(screen.getByTestId('report-card-1'))
    expect(await screen.findByRole('heading', { name: '本周概览' })).toBeInTheDocument()
    expect(screen.getByTestId('echarts-block')).toBeInTheDocument()
    expect(screen.getByTestId('export-md')).toBeInTheDocument()
    expect(screen.getByTestId('export-pdf')).toBeInTheDocument()
  })

  it('导出按钮请求对应格式的导出接口', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([['/api/ai-reports?type=weekly', WEEKLY]])
    render(<ReviewsPage />)
    await screen.findByText(/2026-08-03/)
    await user.click(screen.getByTestId('report-card-1'))

    await user.click(screen.getByTestId('export-md'))
    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/ai-reports/1/export?format=md',
        expect.any(Object),
      )
    })

    await user.click(screen.getByTestId('export-pdf'))
    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/ai-reports/1/export?format=pdf',
        expect.any(Object),
      )
    })
  })

  it('点击生成后触发 POST，轮询状态直至完成并提示', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([
      ['/api/ai-reports?type=weekly', WEEKLY],
      ['/api/ai-reports/generate/status', () =>
        mockResponse({ type: 'weekly', running: false, error: null, report: WEEKLY.reports[0] })],
      ['/api/ai-reports/generate', (url, options) => {
        expect(options.method).toBe('POST')
        expect(JSON.parse(options.body)).toEqual({ type: 'weekly' })
        return mockResponse({ status: 'started', type: 'weekly' })
      }],
    ])
    render(<ReviewsPage />)
    await screen.findByText(/2026-08-03/)

    await user.click(screen.getByTestId('generate-button'))
    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/ai-reports/generate',
        expect.objectContaining({ method: 'POST' }),
      )
    })

    await vi.advanceTimersByTimeAsync(3100)
    expect(await screen.findByText('复盘生成完成')).toBeInTheDocument()
  })

  it('目标周期已存在报告时提示已存在', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([
      ['/api/ai-reports?type=weekly', WEEKLY],
      ['/api/ai-reports/generate', () =>
        mockResponse({ status: 'exists', report: WEEKLY.reports[0] })],
    ])
    render(<ReviewsPage />)
    await screen.findByText(/2026-08-03/)

    await user.click(screen.getByTestId('generate-button'))
    expect(await screen.findByText('该周期复盘已存在')).toBeInTheDocument()
  })
})
