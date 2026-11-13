import { render as renderUI, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ExerciseMappingsPage from '../ExerciseMappingsPage'
import { ToastProvider } from '../../components/ui/Toast'

function response(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  }
}

const COVERAGE = {
  total: 1091,
  by_status: { draft: 911, active: 16, disabled: 0, not_applicable: 164, missing: 0 },
  by_confidence: { high: 222, medium: 264, low: 206, none: 235, not_applicable: 164 },
  by_verified_level: { none: 1075, catalog: 0, created: 0, displayed: 16 },
  coverage: {
    with_candidate: 708,
    with_candidate_pct: 64.9,
    high: 222,
    high_pct: 20.3,
    strength_total: 927,
    strength_with_candidate: 708,
    strength_with_candidate_pct: 76.4,
  },
}

function baseItem(overrides) {
  return {
    id: 1,
    xunji_name: '杠铃卧推',
    garmin_category: 'BENCH_PRESS',
    garmin_exercise_name: 'BENCH_PRESS',
    garmin_display_name: 'Bench Press',
    weight_strategy: 'total',
    status: 'draft',
    confidence: 'high',
    source: 'batch',
    verified_level: 'none',
    mapping_version: 1,
    not_applicable_reason: null,
    note: null,
    candidate_count: 0,
    relation: 'EXACT',
    match_basis: null,
    unmapped_reason: null,
    decision_source: null,
    ...overrides,
  }
}

const LIST_DEFAULT = {
  items: [
    baseItem({ id: 1, xunji_name: '杠铃卧推' }),
    baseItem({ id: 2, xunji_name: '哑铃飞鸟', garmin_category: 'FLY', garmin_exercise_name: 'DUMBBELL_FLY' }),
  ],
  total: 2,
  page: 1,
  page_size: 50,
  pages: 1,
}

const CATALOG = [
  { category: 'BENCH_PRESS', exercise: 'BENCH_PRESS', name: 'Bench Press' },
  { category: 'BENCH_PRESS', exercise: 'NEUTRAL_GRIP_DUMBBELL_BENCH_PRESS', name: 'Neutral Grip DB Bench' },
  { category: 'FLY', exercise: 'DUMBBELL_FLY', name: 'Dumbbell Fly' },
]

function routeFetch(routes) {
  return vi.fn((url, options = {}) => {
    for (const [match, handler] of routes) {
      if (url.startsWith(match)) {
        return Promise.resolve(typeof handler === 'function' ? handler(url, options) : response(handler))
      }
    }
    return Promise.resolve(response({}, 404))
  })
}

function defaultRoutes(overrides = {}) {
  return [
    ['/api/exercise-mappings/coverage', overrides.coverage ?? COVERAGE],
    ['/api/exercise-mappings/stale-syncs', overrides.stale ?? []],
    ['/api/exercise-mappings/catalog', overrides.catalog ?? CATALOG],
    ['/api/exercise-mappings/batch-activate', overrides.batch ?? { activated: 5, skipped: 1 }],
    // reviews 必须排在 review 之前（startsWith 前缀）
    ['/api/exercise-mappings/reviews', overrides.reviews ?? { items: [] }],
    ['/api/exercise-mappings/review', overrides.review ?? { batch_id: 'batch-ai-1', processed: 1 }],
    ['/api/exercise-mappings/1', overrides.detail ?? { ...baseItem(), candidates: [] }],
    ['/api/exercise-mappings/2', overrides.detail2 ?? { ...baseItem({ id: 2, xunji_name: '哑铃飞鸟' }), candidates: [] }],
    ['/api/exercise-mappings', overrides.list ?? LIST_DEFAULT],
  ]
}

function renderPage() {
  return renderUI(
    <MemoryRouter>
      <ToastProvider>
        <ExerciseMappingsPage />
      </ToastProvider>
    </MemoryRouter>,
  )
}

describe('ExerciseMappingsAiReview', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('test_ai_review_button_rendered', async () => {
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    const row1 = await screen.findByTestId('mapping-row-1')
    const row2 = await screen.findByTestId('mapping-row-2')
    expect(within(row1).getByTestId('mapping-ai-review-1')).toHaveTextContent('AI 审核')
    expect(within(row2).getByTestId('mapping-ai-review-2')).toHaveTextContent('AI 审核')
  })

  it('test_click_triggers_review_calls', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes({
      review: { batch_id: 'batch-ai-1', processed: 1 },
      reviews: {
        items: [{
          id: 101,
          xunji_name: '杠铃卧推',
          verdict: 'current_ok',
          suggested_category: null,
          suggested_exercise_name: null,
          reason: '合理',
          model: 'm',
          batch_id: 'batch-ai-1',
          resolved: false,
          created_at: '2026-11-13T00:00:00Z',
        }],
      },
    }))
    renderPage()
    await user.click(await screen.findByTestId('mapping-ai-review-1'))
    await waitFor(() => {
      const reviewCalls = globalThis.fetch.mock.calls.filter(([url, options]) =>
        url.startsWith('/api/exercise-mappings/review?xunji_name=') && options?.method === 'POST')
      expect(reviewCalls.length).toBe(1)
      expect(reviewCalls[0][0]).toContain('xunji_name=')
      expect(decodeURIComponent(reviewCalls[0][0])).toContain('杠铃卧推')
    })
    await waitFor(() => {
      const listCalls = globalThis.fetch.mock.calls.filter(([url]) =>
        url.startsWith('/api/exercise-mappings/reviews?batch_id='))
      expect(listCalls.length).toBe(1)
      expect(listCalls[0][0]).toContain('batch_id=batch-ai-1')
    })
  })

  it('test_result_panel_shown', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes({
      review: { batch_id: 'batch-better', processed: 1 },
      reviews: {
        items: [{
          id: 102,
          xunji_name: '杠铃卧推',
          verdict: 'better_candidate',
          suggested_category: 'BENCH_PRESS',
          suggested_exercise_name: 'NEUTRAL_GRIP_DUMBBELL_BENCH_PRESS',
          reason: '中立握哑铃卧推更贴合',
          model: 'm',
          batch_id: 'batch-better',
          resolved: false,
          created_at: '2026-11-13T00:00:00Z',
        }],
      },
    }))
    renderPage()
    await user.click(await screen.findByTestId('mapping-ai-review-1'))
    const panel = await screen.findByTestId('ai-review-panel')
    expect(panel).toHaveAttribute('data-verdict', 'better_candidate')
    expect(panel).toHaveTextContent('有更优候选')
    expect(panel).toHaveTextContent('BENCH_PRESS/NEUTRAL_GRIP_DUMBBELL_BENCH_PRESS')
    expect(panel).toHaveTextContent('中立握哑铃卧推更贴合')
    expect(within(panel).getByTestId('ai-review-apply')).toBeInTheDocument()
  })

  it('test_current_ok_only_toasts', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes({
      review: { batch_id: 'batch-ok', processed: 1 },
      reviews: {
        items: [{
          id: 103,
          xunji_name: '杠铃卧推',
          verdict: 'current_ok',
          suggested_category: null,
          suggested_exercise_name: null,
          reason: '与目录一致',
          model: 'm',
          batch_id: 'batch-ok',
          resolved: false,
          created_at: '2026-11-13T00:00:00Z',
        }],
      },
    }))
    renderPage()
    await user.click(await screen.findByTestId('mapping-ai-review-1'))
    const panel = await screen.findByTestId('ai-review-panel')
    expect(panel).toHaveTextContent('当前映射合理')
    expect(within(panel).queryByTestId('ai-review-apply')).not.toBeInTheDocument()
    expect(await screen.findByText('AI 认为当前映射合理')).toBeInTheDocument()
  })

  it('test_apply_prefills_edit_form', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes({
      review: { batch_id: 'batch-apply', processed: 1 },
      reviews: {
        items: [{
          id: 104,
          xunji_name: '杠铃卧推',
          verdict: 'better_candidate',
          suggested_category: 'BENCH_PRESS',
          suggested_exercise_name: 'NEUTRAL_GRIP_DUMBBELL_BENCH_PRESS',
          reason: '建议换中立握',
          model: 'm',
          batch_id: 'batch-apply',
          resolved: false,
          created_at: '2026-11-13T00:00:00Z',
        }],
      },
      // 详情故意返回旧值，验证 preset 不会被覆盖
      detail: {
        ...baseItem(),
        garmin_category: 'BENCH_PRESS',
        garmin_exercise_name: 'BENCH_PRESS',
        candidates: [],
      },
    }))
    renderPage()
    await user.click(await screen.findByTestId('mapping-ai-review-1'))
    await user.click(await screen.findByTestId('ai-review-apply'))
    const panel = await screen.findByTestId('edit-panel')
    expect(await screen.findByText('已填入 AI 建议，请确认后保存')).toBeInTheDocument()
    await waitFor(() => {
      expect(panel).toHaveTextContent('NEUTRAL_GRIP_DUMBBELL_BENCH_PRESS')
      expect(screen.getByTestId('edit-category')).toHaveValue('BENCH_PRESS')
    })
  })

  it('test_review_error_shows_toast', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes({
      review: () => response({ detail: '审核配额不足' }, 422),
    }))
    renderPage()
    await screen.findByTestId('mapping-row-1')
    await user.click(screen.getByTestId('mapping-ai-review-1'))
    expect(await screen.findByText('审核配额不足')).toBeInTheDocument()
    expect(screen.queryByTestId('ai-review-panel')).not.toBeInTheDocument()
    // 其它行不受影响
    expect(screen.getByTestId('mapping-ai-review-2')).toBeEnabled()
    expect(screen.getByTestId('mapping-ai-review-2')).toHaveTextContent('AI 审核')
  })
})
