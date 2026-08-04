import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CalendarPage from '../CalendarPage'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const CALENDAR_AUG = {
  month: '2026-08',
  days: [
    {
      date: '2026-08-03',
      workouts: [
        { id: 1, title: '胸部训练', match_status: 'auto_matched', tags: 'strength_training' },
      ],
    },
    {
      date: '2026-08-10',
      workouts: [
        { id: 2, title: '跑步', match_status: 'pending', tags: 'running' },
      ],
    },
  ],
}

const CALENDAR_SEP = { month: '2026-09', days: [] }

describe('CalendarPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    globalThis.fetch = vi.fn((url) => {
      if (String(url).includes('month=2026-09')) return Promise.resolve(mockResponse(CALENDAR_SEP))
      return Promise.resolve(mockResponse(CALENDAR_AUG))
    })
  })

  it('标记有训练的日期', async () => {
    render(
      <MemoryRouter>
        <CalendarPage initialMonth="2026-08" />
      </MemoryRouter>,
    )

    await screen.findByTestId('day-2026-08-03')
    expect(screen.getByTestId('dot-2026-08-03-auto_matched')).toBeInTheDocument()
    expect(screen.getByTestId('dot-2026-08-10-pending')).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/workouts/calendar?month=2026-08',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
  })

  it('翻月按钮触发新月份请求', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <CalendarPage initialMonth="2026-08" />
      </MemoryRouter>,
    )

    await screen.findByTestId('day-2026-08-03')
    await user.click(screen.getByRole('button', { name: '下个月' }))

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/workouts/calendar?month=2026-09',
        expect.anything(),
      )
    })
    expect(screen.getByTestId('current-month')).toHaveTextContent('2026-09')
  })
})
