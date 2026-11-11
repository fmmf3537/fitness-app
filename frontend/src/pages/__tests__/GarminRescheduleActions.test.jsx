import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PlansPage from '../PlansPage'
import { ToastProvider } from '../../components/ui/Toast'

vi.mock('echarts', () => ({
  init: () => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }),
}))

const FROM_DATE = '2026-08-11'
const TARGET_DATE = '2026-08-12'
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
    status: 'reschedule_pending',
    phase: 'reschedule',
    source_hash: HASH_A,
    synced_hash: 'old-hash',
    workout_id: 'workout-old',
    workout_schedule_id: 'schedule-old',
    reschedule_from_date: FROM_DATE,
    reschedule_to_date: TARGET_DATE,
    attempt_count: 2,
    error_code: null,
    last_error: null,
    ...overrides,
  }
}

function makePreview(overrides = {}) {
  return {
    from_date: FROM_DATE,
    to_date: TARGET_DATE,
    source_key: `xunji-plan:v1:universal:1:${TARGET_DATE}`,
    source_hash: HASH_A,
    preview_only: true,
    remote_write_eligible: true,
    sync: makeSync(),
    reschedule: {
      from_date: FROM_DATE,
      to_date: TARGET_DATE,
      workout_id: 'workout-old',
      workout_schedule_id: 'schedule-old',
    },
    stats: { movements: 1, sets: 2, warmup_sets: 0, working_sets: 2, repeat_groups: 1, rest_seconds: 120 },
    movements: [{
      name: '杠铃卧推',
      garmin_display_name: 'Barbell Bench Press',
      support_level: 'p0_verified',
      groups: [{ source_sets: '1-2', count: 2, set_type: 'working', weight_kg: 22.5, reps: 8, rest_seconds: 60 }],
    }],
    ...overrides,
  }
}

function makeUpcoming(sync = makeSync()) {
  return {
    from: TARGET_DATE,
    to: TARGET_DATE,
    days: [{
      date: TARGET_DATE,
      is_rest: false,
      plan_ref: 'universal:1',
      plan_name: '测试计划',
      title: '胸部训练',
      movements: [{ name: '杠铃卧推', target_sets: [{ weight: 22.5, unit: 'kg', reps: 8 }] }],
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

function rescheduleWrites() {
  return globalThis.fetch.mock.calls.filter(([url, options]) => (
    url.includes('/garmin/reschedule') && options.method === 'POST'
  ))
}

describe('Garmin 顺延确认交互', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('展示日期和原 ID，确认仅 POST 一次并轮询目标日到已同步', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    let statusCalls = 0
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', makeUpcoming()],
      [`/api/plans/${FROM_DATE}/garmin/reschedule`, (url, options) => {
        if (options.method === 'POST') {
          return response({
            started: true,
            sync: makeSync({ status: 'syncing', attempt_count: 3 }),
          }, 202)
        }
        expect(url).toContain(`to_date=${TARGET_DATE}`)
        return response(makePreview())
      }],
      [`/api/plans/${TARGET_DATE}/garmin/sync`, () => {
        statusCalls += 1
        return response(makeSync({
          status: 'synced',
          phase: 'verify',
          synced_hash: HASH_A,
          attempt_count: 3,
        }))
      }],
      ['/api/plans/review/', response({}, 404)],
    ])
    renderPage()

    const trigger = await screen.findByTestId(`garmin-preview-button-${TARGET_DATE}`)
    expect(trigger).toHaveTextContent('确认顺延')
    expect(screen.getByText('Garmin · 顺延待确认')).toBeInTheDocument()
    await user.click(trigger)
    await screen.findByTestId('garmin-confirm-reschedule')

    expect(screen.getByTestId('garmin-reschedule-from')).toHaveTextContent(FROM_DATE)
    expect(screen.getByTestId('garmin-reschedule-to')).toHaveTextContent(TARGET_DATE)
    expect(screen.getByTestId('garmin-write-confirmation')).toHaveTextContent('workout-old')
    expect(screen.getByTestId('garmin-write-confirmation')).toHaveTextContent('schedule-old')
    expect(screen.getByText('源组 1-2 · 2 组 × 8 次').closest('li')).toHaveTextContent('22.5 kg')
    expect(rescheduleWrites()).toHaveLength(0)

    await user.click(screen.getByTestId('garmin-confirm-reschedule'))
    await user.click(await screen.findByTestId('confirm-dialog-confirm'))
    expect(screen.getAllByText('Garmin · 同步中')).not.toHaveLength(0)
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

    expect(await screen.findAllByText('Garmin · 已同步')).not.toHaveLength(0)
    expect(screen.queryByTestId('garmin-confirm-reschedule')).not.toBeInTheDocument()
    expect(screen.getByTestId('garmin-reschedule-comparison')).toHaveTextContent('改期已完成')
    expect(rescheduleWrites()).toHaveLength(1)
    expect(JSON.parse(rescheduleWrites()[0][1].body)).toEqual({
      to_date: TARGET_DATE,
      source_hash: HASH_A,
    })
    expect(statusCalls).toBe(1)
  })

  it('失败顺延展示脱敏错误和恢复确认，冲突响应不自动重试', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    const failed = makeSync({
      status: 'failed',
      error_code: 'GARMIN_RATE_LIMITED',
      last_error: 'Garmin 请求受限：reschedule_schedule（HTTP 429）',
      attempt_count: 3,
    })
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', makeUpcoming(failed)],
      [`/api/plans/${FROM_DATE}/garmin/reschedule`, (url, options) => (
        options.method === 'POST'
          ? response({ detail: { code: 'GARMIN_WORKOUT_SOURCE_MISMATCH', message: '已关联的 Garmin 训练不属于原顺延来源' } }, 409)
          : response(makePreview({ sync: failed }))
      )],
      ['/api/plans/review/', response({}, 404)],
    ])
    renderPage()

    expect(await screen.findByTestId(`garmin-preview-button-${TARGET_DATE}`)).toHaveTextContent('恢复顺延')
    await user.click(screen.getByTestId(`garmin-preview-button-${TARGET_DATE}`))
    expect(await screen.findByText(/Garmin 请求受限/)).toBeInTheDocument()
    expect(screen.getByTestId('garmin-write-confirmation')).toHaveTextContent('先回读原 Workout 和日程')
    await user.click(screen.getByTestId('garmin-confirm-reschedule'))
    await user.click(await screen.findByTestId('confirm-dialog-confirm'))

    expect(await screen.findByText('已关联的 Garmin 训练不属于原顺延来源')).toBeInTheDocument()
    expect(rescheduleWrites()).toHaveLength(1)
  })

  it('计划变化时作废旧顺延确认并重新预览，不重复 POST', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    let previewCalls = 0
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', makeUpcoming()],
      [`/api/plans/${FROM_DATE}/garmin/reschedule`, (url, options) => {
        if (options.method === 'POST') {
          return response({ detail: { code: 'PLAN_CHANGED', message: '训记计划已变化，请重新生成顺延预览' } }, 409)
        }
        previewCalls += 1
        return response(makePreview(previewCalls === 1 ? {} : {
          source_hash: HASH_B,
          sync: makeSync({ source_hash: HASH_B }),
        }))
      }],
      ['/api/plans/review/', response({}, 404)],
    ])
    renderPage()
    await user.click(await screen.findByTestId(`garmin-preview-button-${TARGET_DATE}`))
    await user.click(await screen.findByTestId('garmin-confirm-reschedule'))
    await user.click(await screen.findByTestId('confirm-dialog-confirm'))

    await screen.findByTestId('garmin-confirm-reschedule')
    expect(screen.getByText(new RegExp(HASH_B))).toBeInTheDocument()
    expect(previewCalls).toBe(2)
    expect(rescheduleWrites()).toHaveLength(1)
  })

  it('轮询失败可手动重新获取，随后完成顺延', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    let statusCalls = 0
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', makeUpcoming()],
      [`/api/plans/${FROM_DATE}/garmin/reschedule`, (url, options) => (
        options.method === 'POST'
          ? response({ started: true, sync: makeSync({ status: 'syncing' }) }, 202)
          : response(makePreview())
      )],
      [`/api/plans/${TARGET_DATE}/garmin/sync`, () => {
        statusCalls += 1
        return statusCalls === 1
          ? response({ detail: { message: '临时状态错误' } }, 500)
          : response(makeSync({ status: 'synced', phase: 'verify', synced_hash: HASH_A }))
      }],
      ['/api/plans/review/', response({}, 404)],
    ])
    renderPage()
    await user.click(await screen.findByTestId(`garmin-preview-button-${TARGET_DATE}`))
    await user.click(await screen.findByTestId('garmin-confirm-reschedule'))
    await user.click(await screen.findByTestId('confirm-dialog-confirm'))
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

    expect(await screen.findByText('临时状态错误')).toBeInTheDocument()
    await user.click(screen.getByTestId('garmin-sync-poll-retry'))
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

    expect(await screen.findAllByText('Garmin · 已同步')).not.toHaveLength(0)
    expect(statusCalls).toBe(2)
    expect(rescheduleWrites()).toHaveLength(1)
  })

  it('冲突预览和写入关闭状态均不提供确认按钮', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    const conflict = makeSync({
      status: 'conflict',
      error_code: 'RESCHEDULE_TARGET_CONFLICT',
      last_error: '目标日期已有其他同步记录，未自动覆盖或改期',
    })
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', makeUpcoming(conflict)],
      [`/api/plans/${FROM_DATE}/garmin/reschedule`, makePreview({
        remote_write_eligible: false,
        sync: conflict,
      })],
      ['/api/plans/review/', response({}, 404)],
    ])
    renderPage()
    await user.click(await screen.findByTestId(`garmin-preview-button-${TARGET_DATE}`))

    expect(await screen.findByText('目标日期已有其他同步记录，未自动覆盖或改期')).toBeInTheDocument()
    expect(screen.getByText(/Garmin 写入当前未启用/)).toBeInTheDocument()
    expect(screen.queryByTestId('garmin-confirm-reschedule')).not.toBeInTheDocument()
    expect(rescheduleWrites()).toHaveLength(0)
  })

  it('test_confirm_reschedule_requires_second_confirmation', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', makeUpcoming()],
      [`/api/plans/${FROM_DATE}/garmin/reschedule`, (url, options) => (
        options.method === 'POST'
          ? response({ started: true, sync: makeSync({ status: 'syncing' }) }, 202)
          : response(makePreview())
      )],
      ['/api/plans/review/', response({}, 404)],
    ])
    renderPage()
    await user.click(await screen.findByTestId(`garmin-preview-button-${TARGET_DATE}`))
    await user.click(await screen.findByTestId('garmin-confirm-reschedule'))

    expect(await screen.findByTestId('confirm-dialog')).toBeInTheDocument()
    expect(rescheduleWrites()).toHaveLength(0)
  })

  it('test_confirm_reschedule_cancel_does_not_write', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch([
      ['/api/plans/upcoming', makeUpcoming()],
      [`/api/plans/${FROM_DATE}/garmin/reschedule`, (url, options) => (
        options.method === 'POST'
          ? response({ started: true, sync: makeSync({ status: 'syncing' }) }, 202)
          : response(makePreview())
      )],
      ['/api/plans/review/', response({}, 404)],
    ])
    renderPage()
    await user.click(await screen.findByTestId(`garmin-preview-button-${TARGET_DATE}`))
    await user.click(await screen.findByTestId('garmin-confirm-reschedule'))
    await user.click(await screen.findByTestId('confirm-dialog-cancel'))

    expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument()
    expect(screen.getByTestId('garmin-confirm-reschedule')).toBeInTheDocument()
    expect(rescheduleWrites()).toHaveLength(0)
  })
})
