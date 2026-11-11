import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PlansPage from '../PlansPage'
import { ToastProvider } from '../../components/ui/Toast'

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

const GARMIN_SYNC = {
  status: 'synced',
  phase: 'verify',
  source_hash: 'a'.repeat(64),
  synced_hash: 'a'.repeat(64),
  workout_id: 'workout-1',
  workout_schedule_id: 'schedule-1',
  attempt_count: 1,
}

const GARMIN_PREVIEW = {
  source_key: 'xunji-plan:v1:universal:1:2026-08-12',
  source_hash: 'a'.repeat(64),
  preview_only: true,
  remote_write_eligible: false,
  sync: GARMIN_SYNC,
  stats: {
    movements: 2,
    sets: 3,
    warmup_sets: 0,
    working_sets: 3,
    repeat_groups: 1,
    rest_seconds: 240,
  },
  movements: [
    {
      name: '杠铃卧推',
      garmin_display_name: 'Barbell Bench Press',
      support_level: 'p0_verified',
      groups: [
        { source_sets: '1-2', count: 2, set_type: 'working', weight_kg: 32.5, reps: 8, rest_seconds: 90 },
        { source_sets: '3', count: 1, set_type: 'working', weight_kg: 35, reps: 6, rest_seconds: 60 },
      ],
    },
    {
      name: '卷腹',
      garmin_display_name: 'Crunch',
      support_level: 'user_confirmed_catalog_pending_end_to_end',
      groups: [
        { source_sets: '1', count: 1, set_type: 'working', weight_kg: null, reps: 15, rest_seconds: 0 },
      ],
    },
  ],
}

function upcomingWithGarmin(firstStatus = 'update_available', secondStatus = 'synced') {
  return {
    ...UPCOMING,
    days: UPCOMING.days.map((day, index) => ({
      ...day,
      garmin_sync: day.is_rest
        ? null
        : { ...GARMIN_SYNC, status: index === 0 ? firstStatus : secondStatus },
    })),
  }
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

function renderPage(ui = <PlansPage />) {
  return render(<ToastProvider>{ui}</ToastProvider>)
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
    renderPage()

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
    renderPage()

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
    renderPage()
    await screen.findByText('背·二头')

    await user.click(screen.getByTestId('refresh-button'))
    expect(screen.getByTestId('refresh-button')).toBeDisabled()

    await vi.advanceTimersByTimeAsync(3100)
    await vi.advanceTimersByTimeAsync(3100)
    expect(await screen.findByTestId('refresh-button')).not.toBeDisabled()
    expect(screen.getByTestId('toast-container')).toHaveTextContent('计划缓存已刷新')
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
    renderPage()
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
    renderPage()

    expect(await screen.findByTestId('rest-day-2026-08-13')).toHaveTextContent('休息日')
    expect(screen.queryByTestId('review-button-2026-08-13')).not.toBeInTheDocument()
    expect(screen.queryByTestId('modifications-2026-08-13')).not.toBeInTheDocument()
  })

  it('训练日显示 Garmin 状态与预览入口，休息日不显示', async () => {
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', upcomingWithGarmin()],
      ['/api/plans/review/', mockResponse({}, 404)],
    ])
    renderPage()

    expect(await screen.findByText('Garmin · 有更新')).toBeInTheDocument()
    expect(screen.getByText('Garmin · 已同步')).toBeInTheDocument()
    expect(screen.getByTestId('garmin-preview-button-2026-08-11')).toHaveTextContent('预览更新')
    expect(screen.getByTestId('garmin-preview-button-2026-08-12')).toHaveTextContent('查看预览')
    expect(screen.queryByTestId('garmin-preview-button-2026-08-13')).not.toBeInTheDocument()
  })

  it('Garmin 预览展示全部组次和远端关联，只发 GET，Escape 关闭并恢复焦点', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', upcomingWithGarmin()],
      ['/api/plans/2026-08-12/garmin/preview', GARMIN_PREVIEW],
      ['/api/plans/review/', mockResponse({}, 404)],
    ])
    renderPage()
    const trigger = await screen.findByTestId('garmin-preview-button-2026-08-12')

    await user.click(trigger)
    expect(await screen.findByTestId('garmin-preview-modal')).toBeInTheDocument()
    expect(screen.getByTestId('garmin-preview-stats')).toHaveTextContent('总组数')
    expect(screen.getByTestId('garmin-preview-stats')).toHaveTextContent('3')
    expect(screen.getByText('源组 1-2 · 2 组 × 8 次')).toBeInTheDocument()
    expect(screen.getByText('源组 3 · 1 组 × 6 次')).toBeInTheDocument()
    expect(screen.getByText(/32.5 kg/)).toHaveTextContent('休息 90 秒')
    expect(screen.getByText(/35 kg/)).toHaveTextContent('休息 60 秒')
    expect(screen.getByText(/自重/)).toHaveTextContent('无休息')
    expect(screen.getByText(/已关联 Workout workout-1/)).toHaveTextContent('日程 schedule-1')
    expect(screen.getByText(/此版本已同步到 Garmin/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /确认同步|同步训练/ })).not.toBeInTheDocument()
    const garminCalls = globalThis.fetch.mock.calls.filter(([url]) => url.includes('/garmin/'))
    expect(garminCalls).toHaveLength(1)
    expect(garminCalls[0][1]?.method || 'GET').toBe('GET')

    await user.keyboard('{Escape}')
    expect(screen.queryByTestId('garmin-preview-modal')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('422 时完整展示所有不支持动作，不显示跳过或上传入口', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', upcomingWithGarmin()],
      ['/api/plans/2026-08-11/garmin/preview', () => mockResponse({
        detail: {
          code: 'PLAN_MAPPING_UNSUPPORTED',
          issues: [
            { code: 'UNKNOWN_EXERCISE', movement: '未知动作甲', message: '未映射动作：未知动作甲' },
            { code: 'UNKNOWN_EXERCISE', movement: '未知动作乙', message: '未映射动作：未知动作乙' },
          ],
        },
      }, 422)],
      ['/api/plans/review/', mockResponse({}, 404)],
    ])
    renderPage()

    await user.click(await screen.findByTestId('garmin-preview-button-2026-08-11'))
    const issues = await screen.findByTestId('garmin-preview-issues')
    expect(issues).toHaveTextContent('未知动作甲')
    expect(issues).toHaveTextContent('未映射动作：未知动作甲')
    expect(issues).toHaveTextContent('未知动作乙')
    expect(issues).toHaveTextContent('未映射动作：未知动作乙')
    expect(screen.getByText('暂不支持同步此计划')).toBeInTheDocument()
    expect(screen.queryByTestId('garmin-preview-stats')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /跳过|确认同步|同步训练/ })).not.toBeInTheDocument()
  })

  it('预览失败可重试，重试仍为 GET', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    let previewCalls = 0
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', upcomingWithGarmin()],
      ['/api/plans/2026-08-12/garmin/preview', () => {
        previewCalls += 1
        return previewCalls === 1 ? mockResponse({}, 500) : mockResponse(GARMIN_PREVIEW)
      }],
      ['/api/plans/review/', mockResponse({}, 404)],
    ])
    renderPage()

    await user.click(await screen.findByTestId('garmin-preview-button-2026-08-12'))
    expect(await screen.findByText('预览生成失败')).toBeInTheDocument()
    await user.click(screen.getByTestId('garmin-preview-retry'))
    expect(await screen.findByTestId('garmin-preview-stats')).toBeInTheDocument()
    expect(previewCalls).toBe(2)
    const garminCalls = globalThis.fetch.mock.calls.filter(([url]) => url.includes('/garmin/'))
    expect(garminCalls.every(([, options]) => (options?.method || 'GET') === 'GET')).toBe(true)
  })
})
