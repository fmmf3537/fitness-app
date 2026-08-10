import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ScreenshotImportPage from '../ScreenshotImportPage'

function renderPage() {
  return render(
    <MemoryRouter>
      <ScreenshotImportPage />
    </MemoryRouter>,
  )
}

const EXTRACTED = {
  datestr: '2026-08-03',
  title: '背·二头·2',
  start_time: '10:05',
  end_time: '10:50',
  duration_s: 2820,
  calories: 186,
  movements: [
    {
      name: '宽距高位下拉',
      sets: [
        { weight: 40, unit: 'kg', reps: 10 },
        { weight: 40, unit: 'kg', reps: 10 },
      ],
    },
  ],
}

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

/** 按 URL 路由的 fetch mock；posts 收集 confirm 的 JSON 请求体。 */
function mockFetch({ extractResults = [{ filename: 'a.png', ok: true, data: EXTRACTED }] } = {}) {
  const posts = []
  globalThis.fetch = vi.fn((url, options = {}) => {
    if (url === '/api/screenshot/extract') {
      return Promise.resolve(mockResponse({ results: extractResults }))
    }
    if (url === '/api/screenshot/confirm') {
      posts.push(JSON.parse(options.body))
      return Promise.resolve(
        mockResponse({ xunji_train_id: 1, localid: 'shot-abcd1234', workout_id: 5, match_status: 'xunji_only' }),
      )
    }
    return Promise.resolve(mockResponse({ detail: 'not found' }, 404))
  })
  return posts
}

async function uploadAndExtract(user, filename = 'a.png') {
  const file = new File(['png'], filename, { type: 'image/png' })
  await user.upload(screen.getByTestId('file-input'), file)
  await user.click(screen.getByTestId('extract-btn'))
  await screen.findByTestId('preview-card-0')
}

describe('ScreenshotImportPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
  })

  it('初始渲染拖拽区与上传控件，未选文件时识别按钮禁用', () => {
    mockFetch()
    renderPage()
    expect(screen.getByTestId('drop-zone')).toBeInTheDocument()
    expect(screen.getByTestId('file-input')).toBeInTheDocument()
    expect(screen.getByTestId('extract-btn')).toBeDisabled()
  })

  it('选择文件后列出文件名并启用识别按钮', async () => {
    mockFetch()
    const user = userEvent.setup()
    renderPage()
    const file = new File(['x'], '截图1.png', { type: 'image/png' })
    await user.upload(screen.getByTestId('file-input'), file)
    expect(screen.getByText('截图1.png')).toBeInTheDocument()
    expect(screen.getByTestId('extract-btn')).toBeEnabled()
  })

  it('识别：以 FormData 调 extract 接口并渲染预览卡片（含置信提示）', async () => {
    mockFetch()
    const user = userEvent.setup()
    renderPage()
    await uploadAndExtract(user)

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/screenshot/extract',
      expect.objectContaining({ method: 'POST', body: expect.any(FormData) }),
    )
    expect(screen.getByTestId('field-title-0')).toHaveValue('背·二头·2')
    expect(screen.getByTestId('field-datestr-0')).toHaveValue('2026-08-03')
    expect(screen.getByTestId('movement-name-0-0')).toHaveValue('宽距高位下拉')
    expect(screen.getByTestId('set-weight-0-0-0')).toHaveValue(40)
    expect(screen.getByTestId('set-reps-0-0-0')).toHaveValue(10)
    expect(screen.getByTestId('confidence-hint-0')).toBeInTheDocument()
  })

  it('编辑修正后确认入库：提交编辑值并展示 match_status', async () => {
    const posts = mockFetch()
    const user = userEvent.setup()
    renderPage()
    await uploadAndExtract(user)

    const titleInput = screen.getByTestId('field-title-0')
    await user.clear(titleInput)
    await user.type(titleInput, '背·二头·修正')
    await user.click(screen.getByTestId('confirm-btn-0'))

    expect(await screen.findByTestId('confirm-result-0')).toHaveTextContent('已入库 · 仅训记数据')
    expect(posts).toHaveLength(1)
    expect(posts[0].title).toBe('背·二头·修正')
    expect(posts[0].datestr).toBe('2026-08-03')
    expect(posts[0].movements[0].sets[0].weight).toBe(40)
  })

  it('可编辑组次重量，确认时提交编辑后的值', async () => {
    const posts = mockFetch()
    const user = userEvent.setup()
    renderPage()
    await uploadAndExtract(user)

    const weightInput = screen.getByTestId('set-weight-0-0-0')
    await user.clear(weightInput)
    await user.type(weightInput, '42.5')
    await user.click(screen.getByTestId('confirm-btn-0'))

    await screen.findByTestId('confirm-result-0')
    expect(posts[0].movements[0].sets[0].weight).toBe(42.5)
  })

  it('识别失败：展示错误信息，不出现确认按钮', async () => {
    mockFetch({ extractResults: [{ filename: 'a.png', ok: false, error: '识别结果两次校验均不合法' }] })
    const user = userEvent.setup()
    renderPage()
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    await user.upload(screen.getByTestId('file-input'), file)
    await user.click(screen.getByTestId('extract-btn'))

    expect(await screen.findByTestId('error-card-0')).toHaveTextContent('识别结果两次校验均不合法')
    expect(screen.queryByTestId('confirm-btn-0')).not.toBeInTheDocument()
  })
})
