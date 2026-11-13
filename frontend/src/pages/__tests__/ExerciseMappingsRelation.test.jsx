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

const LIST_RELATIONS = {
  items: [
    baseItem({ id: 1, xunji_name: '精确动作', relation: 'EXACT' }),
    baseItem({ id: 2, xunji_name: '近似动作', relation: 'SIMILAR', status: 'active' }),
    baseItem({ id: 3, xunji_name: '大类动作', relation: 'CATEGORY' }),
    baseItem({ id: 4, xunji_name: '无对应动作', relation: 'UNMAPPED', garmin_category: null }),
    baseItem({ id: 5, xunji_name: '未回填动作', relation: null }),
    baseItem({
      id: 6,
      xunji_name: '旧政策动作',
      relation: 'EXACT',
      decision_source: 'human_policy',
    }),
  ],
  total: 6,
  page: 1,
  page_size: 50,
  pages: 1,
}

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
    ['/api/exercise-mappings/catalog', overrides.catalog ?? []],
    ['/api/exercise-mappings/batch-activate', overrides.batch ?? { activated: 5, skipped: 1 }],
    ['/api/exercise-mappings', overrides.list ?? LIST_RELATIONS],
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

describe('ExerciseMappingsRelation', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('test_exact_badge', async () => {
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    const row = await screen.findByTestId('mapping-row-1')
    expect(within(row).getByTestId('relation-badge')).toHaveTextContent('精确')
  })

  it('test_similar_badge_marked_lossy', async () => {
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    const row = await screen.findByTestId('mapping-row-2')
    expect(within(row).getByTestId('relation-badge')).toHaveTextContent('近似（有损）')
  })

  it('test_category_badge_marked_lossy', async () => {
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    const row = await screen.findByTestId('mapping-row-3')
    expect(within(row).getByTestId('relation-badge')).toHaveTextContent('大类（有损）')
  })

  it('test_unmapped_badge', async () => {
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    const row = await screen.findByTestId('mapping-row-4')
    expect(within(row).getByTestId('relation-badge')).toHaveTextContent('无对应')
  })

  it('test_null_relation_badge', async () => {
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    const row = await screen.findByTestId('mapping-row-5')
    expect(within(row).getByTestId('relation-badge')).toHaveTextContent('未回填')
  })

  it('test_human_policy_badge_wording', async () => {
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    const row = await screen.findByTestId('mapping-row-6')
    expect(within(row).getByTestId('decision-source-badge')).toHaveTextContent('沿用旧政策')
    expect(screen.queryByText(/逐条人工确认/)).not.toBeInTheDocument()
  })

  it('test_relation_filter_client_side', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await screen.findByTestId('mapping-row-1')
    expect(screen.getByTestId('relation-filter-scope-hint')).toHaveTextContent('仅筛选当前页')
    await user.selectOptions(screen.getByTestId('filter-relation'), 'SIMILAR')
    await waitFor(() => {
      expect(screen.getByTestId('mapping-row-2')).toBeInTheDocument()
      expect(screen.queryByTestId('mapping-row-1')).not.toBeInTheDocument()
      expect(screen.queryByTestId('mapping-row-3')).not.toBeInTheDocument()
    })
    const listCalls = globalThis.fetch.mock.calls.filter(([url]) =>
      url.startsWith('/api/exercise-mappings?') && url.includes('relation='))
    expect(listCalls.length).toBe(0)
  })

  it('test_batch_activate_shows_skipped_reasons', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes({
      batch: {
        activated: 2,
        skipped: 3,
        skipped_reasons: { relation_not_exact: 3 },
        relation_breakdown: { EXACT: 2, SIMILAR: 3 },
      },
    }))
    renderPage()
    await user.click(await screen.findByTestId('batch-activate'))
    const panel = await screen.findByTestId('batch-activate-result')
    expect(panel).toHaveTextContent('关系非精确')
    expect(panel).toHaveTextContent('3')
    expect(screen.getByTestId('batch-skipped-reasons')).toHaveTextContent('关系非精确: 3')
  })
})
