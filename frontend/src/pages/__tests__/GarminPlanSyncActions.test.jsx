import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PlansPage from '../PlansPage'
import { ToastProvider } from '../../components/ui/Toast'

vi.mock('echarts', () => ({
  init: () => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }),
}))

const DATE = '2026-08-12'
const HASH_A = 'a'.repeat(64)
const HASH_B = 'b'.repeat(64)

function response(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
    blob: async () => new Blob(['x']),
  }
}

function makeSync(overrides = {}) {
  return {
    status: 'not_synced', phase: null, source_hash: HASH_A, synced_hash: null,
    workout_id: null, workout_schedule_id: null, attempt_count: 0,
    error_code: null, last_error: null, ...overrides,
  }
}

function makePreview(overrides = {}) {
  return {
    source_key: `xunji-plan:v1:universal:1:${DATE}`,
    source_hash: HASH_A, preview_only: true, remote_write_eligible: true,
    sync: makeSync(),
    stats: { movements: 1, sets: 2, warmup_sets: 0, working_sets: 2, repeat_groups: 1, rest_seconds: 120 },
    movements: [{
      name: '杠铃卧推', garmin_display_name: 'Barbell Bench Press', support_level: 'p0_verified',
      groups: [{ source_sets: '1-2', count: 2, set_type: 'working', weight_kg: 20, reps: 8, rest_seconds: 60 }],
    }],
    ...overrides,
  }
}

function makeUpcoming(sync = makeSync()) {
  return {
    from: DATE, to: DATE,
    days: [{
      date: DATE, is_rest: false, plan_ref: 'universal:1', plan_name: '测试计划', title: '胸部训练',
      movements: [{ name: '杠铃卧推', target_sets: [{ weight: 20, unit: 'kg', reps: 8 }] }],
      garmin_sync: sync,
    }],
  }
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

function renderPage() {
  return render(<ToastProvider><PlansPage /></ToastProvider>)
}

describe('Garmin 计划确认同步交互', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('预览阶段零写入，确认仅 POST 一次并轮询到已同步', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    let statusCalls = 0
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', makeUpcoming()],
      [`/api/plans/${DATE}/garmin/preview`, makePreview()],
      [`/api/plans/${DATE}/garmin/sync`, (url, options) => {
        if (options.method === 'POST') {
          return response({ started: true, sync: makeSync({ status: 'syncing', phase: 'create', attempt_count: 1 }) }, 202)
        }
        statusCalls += 1
        return response(makeSync(statusCalls < 2
          ? { status: 'syncing', phase: 'verify', attempt_count: 1 }
          : {
              status: 'synced', phase: 'verify', synced_hash: HASH_A,
              workout_id: 'w1', workout_schedule_id: 's1', attempt_count: 1,
            }))
      }],
      ['/api/plans/review/', response({}, 404)],
    ])
    renderPage()
    await user.click(await screen.findByTestId(`garmin-preview-button-${DATE}`))
    await screen.findByTestId('garmin-confirm-sync')

    let writes = globalThis.fetch.mock.calls.filter(([, options]) => options.method === 'POST' && !options?.url?.includes('/auth/'))
    expect(writes).toHaveLength(0)
    await user.click(screen.getByTestId('garmin-confirm-sync'))
    await user.click(await screen.findByTestId('confirm-dialog-confirm'))
    expect(screen.getAllByText('Garmin · 同步中')).not.toHaveLength(0)

    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })
    expect(await screen.findAllByText('Garmin · 已同步')).not.toHaveLength(0)
    expect(screen.queryByTestId('garmin-confirm-sync')).not.toBeInTheDocument()
    expect(screen.getByText(/已关联 Workout w1/)).toHaveTextContent('日程 s1')

    writes = globalThis.fetch.mock.calls.filter(([url, options]) => url.includes('/garmin/') && options.method === 'POST')
    expect(writes).toHaveLength(1)
    expect(JSON.parse(writes[0][1].body)).toEqual({ source_hash: HASH_A })
    expect(statusCalls).toBe(2)
  })

  it('更新和失败状态分别显示覆盖确认与恢复入口', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', makeUpcoming(makeSync({ status: 'update_available', synced_hash: 'old', workout_id: 'w1', workout_schedule_id: 's1' }))],
      [`/api/plans/${DATE}/garmin/preview`, makePreview({
        sync: makeSync({
          status: 'update_available', synced_hash: 'old', workout_id: 'w1', workout_schedule_id: 's1',
        }),
      })],
      ['/api/plans/review/', response({}, 404)],
    ])
    renderPage()
    await user.click(await screen.findByTestId(`garmin-preview-button-${DATE}`))
    expect(await screen.findByTestId('garmin-confirm-sync')).toHaveTextContent('确认覆盖更新')
    expect(screen.getByTestId('garmin-write-confirmation')).toHaveTextContent('保留原训练与日程关联')
  })

  it('计划变化时作废旧确认并重新加载预览，不重复 POST', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    let previewCalls = 0
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', makeUpcoming()],
      [`/api/plans/${DATE}/garmin/preview`, () => {
        previewCalls += 1
        return response(makePreview(previewCalls === 1 ? {} : {
          source_hash: HASH_B, sync: makeSync({ source_hash: HASH_B }),
        }))
      }],
      [`/api/plans/${DATE}/garmin/sync`, () => response({
        detail: { code: 'PLAN_CHANGED', message: '训记计划已变化，请重新生成预览后再确认' },
      }, 409)],
      ['/api/plans/review/', response({}, 404)],
    ])
    renderPage()
    await user.click(await screen.findByTestId(`garmin-preview-button-${DATE}`))
    await user.click(await screen.findByTestId('garmin-confirm-sync'))
    await user.click(await screen.findByTestId('confirm-dialog-confirm'))

    await screen.findByTestId('garmin-confirm-sync')
    expect(screen.getByText(new RegExp(HASH_B))).toBeInTheDocument()
    expect(previewCalls).toBe(2)
    const writes = globalThis.fetch.mock.calls.filter(([url, options]) => url.includes('/garmin/') && options.method === 'POST')
    expect(writes).toHaveLength(1)
  })

  it('失败恢复显示脱敏错误，冲突响应可阅读且不自动重试', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    const failed = makeSync({
      status: 'failed', phase: 'schedule', workout_id: 'w1', attempt_count: 1,
      error_code: 'GARMIN_RATE_LIMITED', last_error: 'Garmin 请求受限：schedule_workout（HTTP 429）',
    })
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', makeUpcoming(failed)],
      [`/api/plans/${DATE}/garmin/preview`, makePreview({ sync: failed })],
      [`/api/plans/${DATE}/garmin/sync`, () => response({
        detail: { code: 'GARMIN_SYNC_CONFLICT', message: 'Garmin 同步存在冲突，请先人工核对' },
      }, 409)],
      ['/api/plans/review/', response({}, 404)],
    ])
    renderPage()
    await user.click(await screen.findByTestId(`garmin-preview-button-${DATE}`))
    expect(screen.getByText(/Garmin 请求受限/)).toBeInTheDocument()
    await user.click(await screen.findByTestId('garmin-confirm-sync'))
    await user.click(await screen.findByTestId('confirm-dialog-confirm'))

    expect(await screen.findByText('Garmin 同步存在冲突，请先人工核对')).toBeInTheDocument()
    const writes = globalThis.fetch.mock.calls.filter(([url, options]) => url.includes('/garmin/') && options.method === 'POST')
    expect(writes).toHaveLength(1)
  })

  it('P2/P3 已验证动作不再显示待远端验收', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    const groups = [{ source_sets: '1', count: 1, set_type: 'working', weight_kg: 20, reps: 8, rest_seconds: 60 }]
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', makeUpcoming()],
      [`/api/plans/${DATE}/garmin/preview`, makePreview({
        stats: { movements: 3, sets: 3, warmup_sets: 0, working_sets: 3, repeat_groups: 3, rest_seconds: 180 },
        movements: [
          { name: '哑铃卧推', garmin_display_name: 'Dumbbell Bench Press', support_level: 'p2_verified', groups },
          { name: '腿举', garmin_display_name: 'Leg Press', support_level: 'p3_verified', groups },
          { name: '候选动作', garmin_display_name: 'Candidate', support_level: 'user_confirmed_catalog_pending_end_to_end', groups },
        ],
      })],
      ['/api/plans/review/', response({}, 404)],
    ])
    renderPage()
    await user.click(await screen.findByTestId(`garmin-preview-button-${DATE}`))

    expect(await screen.findByTestId('garmin-preview-movement-0')).toHaveTextContent('已端到端验证')
    expect(screen.getByTestId('garmin-preview-movement-0')).not.toHaveTextContent('待远端验收')
    expect(screen.getByTestId('garmin-preview-movement-1')).toHaveTextContent('已端到端验证')
    expect(screen.getByTestId('garmin-preview-movement-1')).not.toHaveTextContent('待远端验收')
    expect(screen.getByTestId('garmin-preview-movement-2')).toHaveTextContent('目录映射已确认 · 待远端验收')
  })

  it('test_confirm_sync_requires_second_confirmation', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', makeUpcoming()],
      [`/api/plans/${DATE}/garmin/preview`, makePreview()],
      [`/api/plans/${DATE}/garmin/sync`, () => response({
        started: true, sync: makeSync({ status: 'syncing', phase: 'create', attempt_count: 1 }),
      }, 202)],
      ['/api/plans/review/', response({}, 404)],
    ])
    renderPage()
    await user.click(await screen.findByTestId(`garmin-preview-button-${DATE}`))
    await user.click(await screen.findByTestId('garmin-confirm-sync'))

    expect(await screen.findByTestId('confirm-dialog')).toBeInTheDocument()
    const writes = globalThis.fetch.mock.calls.filter(([url, options]) => url.includes('/garmin/sync') && options.method === 'POST')
    expect(writes).toHaveLength(0)
  })

  it('test_confirm_sync_cancel_does_not_write', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', makeUpcoming()],
      [`/api/plans/${DATE}/garmin/preview`, makePreview()],
      [`/api/plans/${DATE}/garmin/sync`, () => response({
        started: true, sync: makeSync({ status: 'syncing', phase: 'create', attempt_count: 1 }),
      }, 202)],
      ['/api/plans/review/', response({}, 404)],
    ])
    renderPage()
    await user.click(await screen.findByTestId(`garmin-preview-button-${DATE}`))
    await user.click(await screen.findByTestId('garmin-confirm-sync'))
    await user.click(await screen.findByTestId('confirm-dialog-cancel'))

    expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument()
    expect(screen.getByTestId('garmin-confirm-sync')).toBeInTheDocument()
    const writes = globalThis.fetch.mock.calls.filter(([url, options]) => url.includes('/garmin/sync') && options.method === 'POST')
    expect(writes).toHaveLength(0)
  })

  it('test_confirm_dialog_mentions_garmin_and_date', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', makeUpcoming()],
      [`/api/plans/${DATE}/garmin/preview`, makePreview()],
      ['/api/plans/review/', response({}, 404)],
    ])
    renderPage()
    await user.click(await screen.findByTestId(`garmin-preview-button-${DATE}`))
    await user.click(await screen.findByTestId('garmin-confirm-sync'))

    const dialog = await screen.findByTestId('confirm-dialog')
    expect(dialog).toHaveTextContent('Garmin')
    expect(dialog).toHaveTextContent(DATE)
  })
})
