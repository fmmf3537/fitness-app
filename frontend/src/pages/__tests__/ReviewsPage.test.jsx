import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReviewsPage from '../ReviewsPage'
import ScoreBadge from '../../components/ScoreBadge'
import { ToastProvider } from '../../components/ui/Toast'
import { installMatchMedia } from '../../test/mockMatchMedia'

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
      score: 82,
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

function renderPage(ui = <ReviewsPage />) {
  return render(<ToastProvider>{ui}</ToastProvider>)
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
    renderPage()
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
    renderPage()
    await screen.findByText(/2026-08-03/)

    const monthlyTab = screen.getByRole('button', { name: '月复盘' })
    expect(screen.getByRole('button', { name: '周复盘' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(monthlyTab)
    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenLastCalledWith(
        '/api/ai-reports?type=monthly&limit=50',
        expect.any(Object),
      )
    })
    expect(monthlyTab).toHaveAttribute('aria-pressed', 'true')
    expect(await screen.findByText(/2026-07-01/)).toBeInTheDocument()
  })

  it('点击报告卡片显示详情与导出按钮，echarts 块渲染为图表', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([['/api/ai-reports?type=weekly', WEEKLY]])
    renderPage()
    await screen.findByText(/2026-08-03/)

    await user.click(screen.getByTestId('report-card-1'))
    expect(await screen.findByRole('heading', { name: '本周概览' })).toBeInTheDocument()
    expect(screen.getByTestId('echarts-block')).toBeInTheDocument()
    expect(screen.getByTestId('export-md')).toBeInTheDocument()
    expect(screen.getByTestId('export-pdf')).toBeInTheDocument()
    expect(screen.getByTestId('review-tech-details')).toBeInTheDocument()
    expect(screen.getByTestId('report-detail').textContent).toContain('模型：deepseek-chat')
    expect(screen.getByTestId('report-detail')).toHaveTextContent('82 分 · 良好')
    expect(screen.getByTestId('report-detail')).toHaveTextContent('8/3 – 8/9')
    expect(screen.getByTestId('chat-expand-btn')).toHaveTextContent(
      '就这份复盘追问教练',
    )
    expect(screen.getByTestId('share-poster-btn')).toHaveTextContent('分享本周海报')
    expect(screen.getAllByTestId('review-section-card')).toHaveLength(2)
    // 列表卡默认 ScoreBadge 不含等级文字
    expect(screen.getByTestId('report-card-1').textContent).toContain('82 分')
    expect(screen.getByTestId('report-card-1').textContent).not.toContain('良好')
    // 列表卡不再展示 tokens 元信息
    expect(screen.getByTestId('report-card-1').textContent).not.toMatch(/tokens/)
    expect(screen.getByTestId('report-card-1').textContent).toContain('周复盘')
  })

  it('导出按钮请求对应格式的导出接口', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([['/api/ai-reports?type=weekly', WEEKLY]])
    renderPage()
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
    renderPage()
    await screen.findByText(/2026-08-03/)

    await user.click(screen.getByTestId('generate-button'))
    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/ai-reports/generate',
        expect.objectContaining({ method: 'POST' }),
      )
    })

    await vi.advanceTimersByTimeAsync(3100)
    expect(await screen.findByTestId('toast-container')).toHaveTextContent('复盘生成完成')
  })

  it('目标周期已存在报告时提示已存在', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([
      ['/api/ai-reports?type=weekly', WEEKLY],
      ['/api/ai-reports/generate', () =>
        mockResponse({ status: 'exists', report: WEEKLY.reports[0] })],
    ])
    renderPage()
    await screen.findByText(/2026-08-03/)

    await user.click(screen.getByTestId('generate-button'))
    expect(await screen.findByTestId('toast-container')).toHaveTextContent('该周期复盘已存在')
  })

  it('每篇复盘可确认后重新生成，完成后保留报告 ID 并刷新内容', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    const updated = { ...WEEKLY.reports[0], content_md: '## 最新周报\n包含周四新增训练' }
    globalThis.fetch = routeFetch([
      ['/api/ai-reports/period/1/regenerate/status', () => mockResponse({
        report_id: 1, running: false, error: null, report: updated,
      })],
      ['/api/ai-reports/period/1/regenerate', (url, options) => {
        expect(options.method).toBe('POST')
        return mockResponse({ status: 'started', report_id: 1, type: 'weekly' })
      }],
      ['/api/ai-reports?type=weekly', WEEKLY],
    ])
    renderPage()
    await screen.findByText(/2026-08-03/)
    await user.click(screen.getByTestId('report-card-1'))
    await user.click(screen.getByTestId('regenerate-review'))
    expect(screen.getByTestId('confirm-dialog')).toHaveTextContent('当前最新的真实数据')
    await user.click(screen.getByTestId('confirm-dialog-confirm'))

    await vi.advanceTimersByTimeAsync(3100)
    expect(await screen.findByRole('heading', { name: '最新周报' })).toBeInTheDocument()
    expect(screen.getByTestId('toast-container')).toHaveTextContent('复盘已按最新数据重新生成')
  })
})

const WEEKLY_TWO = {
  reports: [
    WEEKLY.reports[0],
    {
      ...WEEKLY.reports[0],
      id: 3,
      date: '2026-07-27',
      period_end: '2026-08-02',
      content_md: '## 上周概览\n上周训练 2 次。',
      created_at: '2026-08-02T21:13:00',
    },
  ],
}

describe('ReviewsPage 移动端（底部抽屉）', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date('2026-08-10T12:00:00'))
    URL.createObjectURL = vi.fn(() => 'blob:mock')
    URL.revokeObjectURL = vi.fn()
    HTMLAnchorElement.prototype.click = vi.fn()
    installMatchMedia(true)
  })

  afterEach(() => {
    installMatchMedia(false)
    vi.useRealTimers()
  })

  it('点击卡片弹出抽屉展示详情，导出 Markdown/PDF 按钮在抽屉内可用', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([['/api/ai-reports?type=weekly', WEEKLY]])
    renderPage()
    await screen.findByText(/2026-08-03/)

    await user.click(screen.getByTestId('report-card-1'))

    expect(await screen.findByTestId('bottom-sheet')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '本周概览' })).toBeInTheDocument()
    expect(screen.getByTestId('report-detail')).toHaveTextContent('82 分 · 良好')
    expect(screen.getByTestId('chat-expand-btn')).toHaveTextContent(
      '就这份复盘追问教练',
    )
    expect(screen.getByTestId('share-poster-btn')).toHaveTextContent('分享本周海报')

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

    // 仅一篇时「上一篇/下一篇」均禁用
    expect(screen.getByTestId('sheet-prev')).toBeDisabled()
    expect(screen.getByTestId('sheet-next')).toBeDisabled()
  })

  it('抽屉内「上一篇/下一篇」在当前列表内切换，末篇禁用下一篇', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([['/api/ai-reports?type=weekly', WEEKLY_TWO]])
    renderPage()
    await screen.findByText(/2026-08-03/)

    await user.click(screen.getByTestId('report-card-1'))
    await screen.findByTestId('bottom-sheet')
    expect(screen.getByRole('heading', { name: '本周概览' })).toBeInTheDocument()
    expect(screen.getByTestId('sheet-prev')).toBeDisabled()

    await user.click(screen.getByTestId('sheet-next'))
    expect(screen.getByRole('heading', { name: '上周概览' })).toBeInTheDocument()
    expect(screen.getByTestId('sheet-next')).toBeDisabled()

    await user.click(screen.getByTestId('sheet-prev'))
    expect(screen.getByRole('heading', { name: '本周概览' })).toBeInTheDocument()
  })
})

describe('ScoreBadge verdict', () => {
  it('默认关闭时仅显示分数，与既有调用逐字一致', () => {
    render(<ScoreBadge score={82} />)
    expect(screen.getByText('82 分')).toBeInTheDocument()
    expect(screen.queryByText(/良好/)).not.toBeInTheDocument()
  })

  it('verdict 开启时追加同阈值等级文字', () => {
    const { rerender } = render(<ScoreBadge score={90} verdict />)
    expect(screen.getByText('90 分 · 优秀')).toBeInTheDocument()
    rerender(<ScoreBadge score={82} verdict />)
    expect(screen.getByText('82 分 · 良好')).toBeInTheDocument()
    rerender(<ScoreBadge score={60} verdict />)
    expect(screen.getByText('60 分 · 一般')).toBeInTheDocument()
    rerender(<ScoreBadge score={59} verdict />)
    expect(screen.getByText('59 分 · 待加强')).toBeInTheDocument()
  })
})
