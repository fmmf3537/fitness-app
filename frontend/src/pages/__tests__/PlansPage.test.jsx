import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PlansPage from '../PlansPage'

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

const UPCOMING = {
  from: '2026-08-11',
  to: '2026-08-13',
  days: [
    {
      date: '2026-08-11',
      is_rest: false,
      plan_ref: 'universal:1',
      plan_name: '三分化·健身房',
      title: '背·二头',
      movements: [
        { name: '杠铃划船', target_sets: [{ weight: 60, unit: 'kg', reps: 10 }] },
        { name: '高位下拉', target_sets: [{ weight: 50, unit: 'kg', reps: 12 }] },
      ],
    },
    {
      date: '2026-08-12',
      is_rest: false,
      plan_ref: 'universal:1',
      plan_name: '三分化·健身房',
      title: '胸·三头·腹',
      movements: [
        { name: '杠铃卧推', target_sets: [{ weight: 32.5, unit: 'kg', reps: 6 }] },
      ],
    },
    { date: '2026-08-13', is_rest: true, plan_ref: null, plan_name: null, title: null, movements: [] },
  ],
}

const REVIEW = {
  id: 9,
  type: 'plan_review',
  date: '2026-08-12',
  model: 'deepseek-chat',
  prompt_tokens: 100,
  completion_tokens: 50,
  cost_estimate: 0.001,
  content_md:
    '## 计划点评\n本次胸部计划整体合理，重量可小幅上调。\n' +
    '```json\n{"schema":"plan_review_v1","plan_date":"2026-08-12","modifications":[' +
    '{"movement":"杠铃卧推","field":"weight","from":"32.5kg","to":"35kg","reason":"上次完成轻松，渐进超负荷"}' +
    ']}\n```\n',
  created_at: '2026-08-11T10:00:00',
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
    return Promise.resolve(mockResponse({}, 404))
  })
}

describe('PlansPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('渲染未来计划列表：训练日卡片含计划名/标题/动作目标组数，休息日弱化展示', async () => {
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', UPCOMING],
      ['/api/plans/review/', mockResponse({}, 404)],
    ])
    render(<PlansPage />)

    // 训练日卡片
    expect((await screen.findAllByText(/三分化·健身房/)).length).toBe(2)
    expect(screen.getByText('背·二头')).toBeInTheDocument()
    expect(screen.getByText(/杠铃划船/)).toBeInTheDocument()
    expect(screen.getByText(/杠铃卧推/)).toBeInTheDocument()
    // 目标组数展示
    expect(screen.getByTestId('movement-2026-08-11-0')).toHaveTextContent('目标 1 组')
    // 休息日弱化展示，且无 AI 点评按钮
    expect(screen.getByTestId('rest-day-2026-08-13')).toHaveTextContent('休息日')
    expect(screen.queryByTestId('review-button-2026-08-13')).not.toBeInTheDocument()
  })

  it('已有 plan_review 的计划日进入页面即加载并展示修改建议表格', async () => {
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', UPCOMING],
      ['/api/plans/review/2026-08-12', REVIEW],
      ['/api/plans/review/', mockResponse({}, 404)],
    ])
    render(<PlansPage />)

    const block = await screen.findByTestId('review-2026-08-12')
    expect(block).toHaveTextContent('计划点评')
    const table = await screen.findByTestId('modifications-2026-08-12')
    expect(table).toHaveTextContent('杠铃卧推')
    expect(table).toHaveTextContent('重量')
    expect(table).toHaveTextContent('32.5kg')
    expect(table).toHaveTextContent('35kg')
    expect(table).toHaveTextContent('渐进超负荷')
    // 窄屏可横向滚动：表格外层包 overflow-x-auto 容器
    expect(table.parentElement).toHaveClass('overflow-x-auto')
    // 醒目提示计划接口只读
    expect(block).toHaveTextContent('计划接口只读，请在训记 App 中手动调整')
  })

  it('点击刷新计划：POST refresh 后轮询状态，完成刷新列表', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    let refreshStatusCalls = 0
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', UPCOMING],
      ['/api/plans/review/', mockResponse({}, 404)],
      ['/api/plans/refresh/status', () => {
        refreshStatusCalls += 1
        return mockResponse({ running: refreshStatusCalls < 2, status: 'success', error: null })
      }],
      ['/api/plans/refresh', (url, options) => {
        expect(options.method).toBe('POST')
        return mockResponse({ status: 'started', job: 'plan_refresh' }, 202)
      }],
    ])
    render(<PlansPage />)
    await screen.findByText('背·二头')

    await user.click(screen.getByTestId('refresh-button'))
    expect(screen.getByTestId('refresh-button')).toBeDisabled()

    await vi.advanceTimersByTimeAsync(3100)
    await vi.advanceTimersByTimeAsync(3100)
    expect(await screen.findByTestId('refresh-button')).not.toBeDisabled()
    expect(screen.getByText(/计划缓存已刷新/)).toBeInTheDocument()
  })

  it('点击 AI 点评：POST 后按钮 loading，轮询完成后展示点评', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    let reviewStatusCalls = 0
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', UPCOMING],
      ['/api/plans/review/2026-08-12/status', () => {
        reviewStatusCalls += 1
        return mockResponse({ date: '2026-08-12', running: reviewStatusCalls < 2, error: null })
      }],
      ['/api/plans/review/2026-08-12', (url, options) =>
        options.method === 'POST'
          ? mockResponse({ status: 'started', date: '2026-08-12' }, 202)
          : mockResponse(REVIEW)],
      ['/api/plans/review/', mockResponse({}, 404)],
    ])
    render(<PlansPage />)
    await screen.findByText('胸·三头·腹')

    await user.click(screen.getByTestId('review-button-2026-08-12'))
    expect(screen.getByTestId('review-button-2026-08-12')).toHaveTextContent('生成中')

    await vi.advanceTimersByTimeAsync(3100)
    await vi.advanceTimersByTimeAsync(3100)
    expect(await screen.findByTestId('review-2026-08-12')).toHaveTextContent('计划点评')
    expect(screen.getByTestId('modifications-2026-08-12')).toHaveTextContent('杠铃卧推')
  })

  it('无计划日（休息日）不展示点评按钮与修改建议', async () => {
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', {
        from: '2026-08-13', to: '2026-08-13',
        days: [UPCOMING.days[2]],
      }],
      ['/api/plans/review/', mockResponse({}, 404)],
    ])
    render(<PlansPage />)

    expect(await screen.findByTestId('rest-day-2026-08-13')).toHaveTextContent('休息日')
    expect(screen.queryByTestId('review-button-2026-08-13')).not.toBeInTheDocument()
    expect(screen.queryByTestId('modifications-2026-08-13')).not.toBeInTheDocument()
  })
})
