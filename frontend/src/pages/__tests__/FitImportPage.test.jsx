import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FitImportPage from '../FitImportPage'

function renderPage() {
  return render(
    <MemoryRouter>
      <FitImportPage />
    </MemoryRouter>,
  )
}

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const IMPORT_OK = {
  ok: true,
  activity_id: 'file_abcd1234',
  date: '2026-08-05',
  activity_type: 'strength_training',
  match_status: 'auto_matched',
  workout_id: 7,
}

describe('FitImportPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
  })

  it('accept 为扩展名 + MIME 兜底混合（V3-10b：覆盖微信/QQ 下载的未索引文件）', () => {
    globalThis.fetch = vi.fn()
    renderPage()
    expect(screen.getByTestId('file-input')).toHaveAttribute(
      'accept',
      '.fit,.tcx,.gpx,.kml,application/gpx+xml,application/octet-stream,text/xml,application/xml',
    )
  })

  it('提示文案含“看不到文件时移到 Download 根目录”指引（V3-10b）', () => {
    globalThis.fetch = vi.fn()
    renderPage()
    expect(screen.getByText(/看不到文件/)).toHaveTextContent(/Download 根目录/)
  })

  it('初始渲染上传控件，未选文件时导入按钮禁用', () => {
    globalThis.fetch = vi.fn()
    renderPage()
    expect(screen.getByTestId('file-input')).toBeInTheDocument()
    expect(screen.getByTestId('import-btn')).toBeDisabled()
  })

  it('选择 .fit 文件后启用按钮，导入成功展示匹配结果与训练链接', async () => {
    globalThis.fetch = vi.fn((url, options = {}) => {
      expect(url).toBe('/api/import/fit')
      expect(options.body).toBeInstanceOf(FormData)
      return Promise.resolve(mockResponse(IMPORT_OK))
    })
    const user = userEvent.setup()
    renderPage()

    const file = new File(['fit-bytes'], 'morning.fit', { type: 'application/octet-stream' })
    await user.upload(screen.getByTestId('file-input'), file)
    expect(screen.getByTestId('import-btn')).toBeEnabled()

    await user.click(screen.getByTestId('import-btn'))
    const result = await screen.findByTestId('import-result')
    expect(result).toHaveTextContent('2026-08-05')
    expect(result).toHaveTextContent('自动匹配')
    expect(screen.getByTestId('workout-link')).toHaveAttribute('href', '/workouts/7')
  })

  it('导入失败展示后端错误信息', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(mockResponse({ detail: 'FIT 文件解析失败' }, 422)),
    )
    const user = userEvent.setup()
    renderPage()

    const file = new File(['bad'], 'broken.fit', { type: 'application/octet-stream' })
    await user.upload(screen.getByTestId('file-input'), file)
    await user.click(screen.getByTestId('import-btn'))

    const error = await screen.findByTestId('import-error')
    expect(error).toHaveTextContent('导入失败')
  })

  it('导入失败优先展示服务端 detail 文案（V3-10c），不再丢成 request failed: 422', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(mockResponse({ detail: 'GPX 文件不含轨迹（trk）' }, 422)),
    )
    const user = userEvent.setup()
    renderPage()

    const file = new File(['bad'], 'track.gpx', { type: 'application/gpx+xml' })
    await user.upload(screen.getByTestId('file-input'), file)
    await user.click(screen.getByTestId('import-btn'))

    const error = await screen.findByTestId('import-error')
    expect(error).toHaveTextContent('GPX 文件不含轨迹（trk）')
    expect(error).not.toHaveTextContent('request failed')
  })

  it('接受 .gpx / .kml 扩展名文件', async () => {
    globalThis.fetch = vi.fn()
    renderPage()

    for (const name of ['run.gpx', 'ride.kml']) {
      const file = new File(['<xml/>'], name, { type: 'application/xml' })
      fireEvent.change(screen.getByTestId('file-input'), { target: { files: [file] } })
      expect(screen.getByTestId('import-btn')).toBeEnabled()
      expect(screen.queryByTestId('import-error')).not.toBeInTheDocument()
    }
  })

  it('拒绝非 .fit/.tcx/.gpx/.kml 文件', async () => {
    globalThis.fetch = vi.fn()
    renderPage()

    const file = new File(['hello'], 'notes.txt', { type: 'text/plain' })
    // userEvent.upload 会遵守 input accept 过滤，这里用 fireEvent 模拟绕过场景
    fireEvent.change(screen.getByTestId('file-input'), { target: { files: [file] } })
    expect(screen.getByTestId('import-btn')).toBeDisabled()
    expect(screen.getByTestId('import-error')).toHaveTextContent('仅支持 .fit / .tcx / .gpx / .kml')
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })
})
