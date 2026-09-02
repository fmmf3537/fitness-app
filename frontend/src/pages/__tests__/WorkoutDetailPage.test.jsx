import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WorkoutDetailPage from '../WorkoutDetailPage'

vi.mock('echarts', () => ({
  init: vi.fn(() => ({
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  })),
}))

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const WORKOUT = {
  id: 1,
  date: '2026-08-03',
  title: '胸部训练',
  match_status: 'auto_matched',
  tags: 'strength_training',
  duration_s: 3600,
  calories: 350,
  avg_hr: 120,
  max_hr: 158,
  movements: [
    {
      name: '卧推',
      sets: [{ weight: 60, unit: 'kg', reps: 10, time: 0, done: true, rpe: 8 }],
    },
  ],
  heart_rate: [
    { t: 1754, hr: 118 },
    { t: 1755, hr: 122 },
  ],
  xunji_raw: { source: 'xunji', foo: 'bar' },
  garmin_raw: { source: 'garmin', activity_id: 'g1' },
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/workouts/1']}>
      <Routes>
        <Route path="/workouts/:id" element={<WorkoutDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('WorkoutDetailPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse(WORKOUT)))
  })

  it('渲染摘要数据', async () => {
    renderPage()
    expect(await screen.findByText('胸部训练')).toBeInTheDocument()
    expect(screen.getByText('1 小时')).toBeInTheDocument()
    expect(screen.getByText('350 千卡')).toBeInTheDocument()
    expect(screen.getByText('120 bpm')).toBeInTheDocument()
    expect(screen.getByText('158 bpm')).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/workouts/1',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
  })

  it('融合标签页显示组次表和心率图', async () => {
    renderPage()
    expect(await screen.findByText('卧推')).toBeInTheDocument()
    expect(screen.getByText(/60\s*kg\s*×\s*10/)).toBeInTheDocument()
    expect(screen.getByText('RPE 8')).toBeInTheDocument()
    expect(screen.getByTestId('hr-chart')).toBeInTheDocument()
    // 窄屏可横向滚动：组次表外层包 overflow-x-auto 容器
    const table = screen.getByRole('table')
    expect(table.parentElement).toHaveClass('overflow-x-auto')
  })

  it('切换到训记原始 / 佳明原始标签', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('卧推')

    await user.click(screen.getByRole('tab', { name: '训记原始' }))
    expect(screen.getByTestId('xunji-raw').textContent).toContain('"foo"')
    expect(screen.queryByText('卧推')).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '佳明原始' }))
    expect(screen.getByTestId('garmin-raw').textContent).toContain('"g1"')

    await user.click(screen.getByRole('tab', { name: '融合' }))
    expect(screen.getByText('卧推')).toBeInTheDocument()
  })

  it('无心率数据时显示提示', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(mockResponse({ ...WORKOUT, heart_rate: null })),
    )
    renderPage()
    expect(await screen.findByText('无心率数据')).toBeInTheDocument()
  })

  describe('逐组心率列（V4-8）', () => {
    it('有 set_hr 数据时显示心率列', async () => {
      globalThis.fetch = vi.fn(() =>
        Promise.resolve(
          mockResponse({
            ...WORKOUT,
            set_hr: [
              {
                movement_name: '卧推',
                set_index: 1,
                hr_avg: 102,
                hr_max: 104,
                hr_min: 100,
                hr_recovery_30s: 88,
                confidence: 'high',
              },
            ],
          }),
        ),
      )
      renderPage()
      expect(await screen.findByText('心率 均/峰/恢复')).toBeInTheDocument()
      expect(screen.getByText('102/104/88')).toBeInTheDocument()
    })

    it('低置信度行加 ~ 前缀', async () => {
      globalThis.fetch = vi.fn(() =>
        Promise.resolve(
          mockResponse({
            ...WORKOUT,
            set_hr: [
              {
                movement_name: '卧推',
                set_index: 1,
                hr_avg: 102,
                hr_max: 104,
                hr_min: 100,
                hr_recovery_30s: 88,
                confidence: 'low',
              },
            ],
          }),
        ),
      )
      renderPage()
      expect(await screen.findByText('~102/104/88')).toBeInTheDocument()
    })

    it('hr_recovery_30s 为 null 时该槽位降级为 -', async () => {
      globalThis.fetch = vi.fn(() =>
        Promise.resolve(
          mockResponse({
            ...WORKOUT,
            set_hr: [
              {
                movement_name: '卧推',
                set_index: 1,
                hr_avg: 102,
                hr_max: 104,
                hr_min: 100,
                hr_recovery_30s: null,
                confidence: 'high',
              },
            ],
          }),
        ),
      )
      renderPage()
      expect(await screen.findByText('102/104/-')).toBeInTheDocument()
    })

    it('workout 无 set_hr 字段时整列不显示', async () => {
      renderPage()
      await screen.findByText('卧推')
      expect(screen.queryByText('心率 均/峰/恢复')).toBeNull()
      expect(screen.queryAllByTestId('set-hr-cell')).toHaveLength(0)
    })

    it('set_hr 为空数组时同 undefined，整列不显示', async () => {
      globalThis.fetch = vi.fn(() =>
        Promise.resolve(mockResponse({ ...WORKOUT, set_hr: [] })),
      )
      renderPage()
      await screen.findByText('卧推')
      expect(screen.queryByText('心率 均/峰/恢复')).toBeNull()
      expect(screen.queryAllByTestId('set-hr-cell')).toHaveLength(0)
    })

    it('多组部分匹配：未匹配组显示 -，匹配组显示数值', async () => {
      globalThis.fetch = vi.fn(() =>
        Promise.resolve(
          mockResponse({
            ...WORKOUT,
            movements: [
              {
                name: '卧推',
                sets: [
                  { weight: 60, unit: 'kg', reps: 10, time: 0, done: true, rpe: 8 },
                  { weight: 60, unit: 'kg', reps: 8, time: 0, done: true, rpe: 9 },
                ],
              },
            ],
            set_hr: [
              {
                movement_name: '卧推',
                set_index: 2,
                hr_avg: 130,
                hr_max: 140,
                hr_min: 125,
                hr_recovery_30s: 110,
                confidence: 'high',
              },
            ],
          }),
        ),
      )
      renderPage()
      await screen.findByText('卧推')
      const cells = screen.getAllByTestId('set-hr-cell')
      expect(cells).toHaveLength(2)
      expect(cells[0]).toHaveTextContent('-')
      expect(cells[1]).toHaveTextContent('130/140/110')
    })
  })

  describe('删除训练（V3-11）', () => {
    function renderWithHome() {
      return render(
        <MemoryRouter initialEntries={['/workouts/1']}>
          <Routes>
            <Route path="/workouts/:id" element={<WorkoutDetailPage />} />
            <Route path="/" element={<div>日历首页</div>} />
          </Routes>
        </MemoryRouter>,
      )
    }

    it('确认删除后调用 DELETE 并返回日历', async () => {
      const user = userEvent.setup()
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
      globalThis.fetch = vi.fn((url, options = {}) => {
        if (options.method === 'DELETE') {
          return Promise.resolve(mockResponse({ ok: true, id: 1 }))
        }
        return Promise.resolve(mockResponse(WORKOUT))
      })
      renderWithHome()
      await screen.findByText('胸部训练')

      await user.click(screen.getByTestId('delete-workout'))

      // 确认文案写明 AI 点评一并删除、可在“已删除”里恢复
      expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('AI 点评'))
      expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('恢复'))
      await screen.findByText('日历首页')
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/workouts/1',
        expect.objectContaining({ method: 'DELETE' }),
      )
    })

    it('取消确认则不发送 DELETE，停留在详情页', async () => {
      const user = userEvent.setup()
      vi.spyOn(window, 'confirm').mockReturnValue(false)
      renderWithHome()
      await screen.findByText('胸部训练')

      await user.click(screen.getByTestId('delete-workout'))

      expect(globalThis.fetch).not.toHaveBeenCalledWith(
        '/api/workouts/1',
        expect.objectContaining({ method: 'DELETE' }),
      )
      expect(screen.getByText('胸部训练')).toBeInTheDocument()
    })
  })
})
