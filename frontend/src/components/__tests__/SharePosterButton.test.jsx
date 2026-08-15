import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const buildPosterData = vi.fn()
const renderPosterDataUrl = vi.fn()
const sharePosterImage = vi.fn()
const isNativeShare = vi.fn()

vi.mock('../../utils/poster', () => ({
  buildPosterData: (...args) => buildPosterData(...args),
  renderPosterDataUrl: (...args) => renderPosterDataUrl(...args),
}))
vi.mock('../../utils/sharePoster', () => ({
  sharePosterImage: (...args) => sharePosterImage(...args),
  isNativeShare: (...args) => isNativeShare(...args),
}))

const apiMock = vi.fn()
vi.mock('../../api/client', () => ({
  api: (...args) => apiMock(...args),
}))

import SharePosterButton from '../SharePosterButton'

const REPORT = {
  id: 5,
  type: 'session_review',
  workout_id: 10,
  date: '2026-08-12',
  workout_title: '胸部训练',
  score: 88,
  one_liner: '今天状态爆棚！',
  content_md: '刷新 PR。',
}
const WORKOUT = { id: 10, date: '2026-08-12', title: '胸部训练', movements: [] }
const POSTER_PAYLOAD = {
  report: { ...REPORT, subscores: { completion: 90, intensity: 85, recovery_fit: 80 } },
  workout: { id: 10, workout_kind: 'strength', volume_kg: 2220, highlights: [] },
  prs: [],
  week_count: 3,
}
const POSTER_DATA = { title: '胸部训练', score: 88 }
const DATA_URL = 'data:image/png;base64,QUJD'

describe('SharePosterButton', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    buildPosterData.mockReturnValue(POSTER_DATA)
    renderPosterDataUrl.mockReturnValue(DATA_URL)
    isNativeShare.mockReturnValue(false)
    sharePosterImage.mockResolvedValue({ mode: 'download' })
    apiMock.mockResolvedValue(POSTER_PAYLOAD)
  })

  it('按钮流转：生成中 → 预览弹层（图 + 操作按钮）', async () => {
    const user = userEvent.setup()
    render(<SharePosterButton report={REPORT} workout={WORKOUT} />)

    await user.click(screen.getByTestId('share-poster-btn'))

    // 预览弹层出现，图已渲染
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toBeInTheDocument()
    const img = screen.getByTestId('poster-preview-img')
    expect(img).toHaveAttribute('src', DATA_URL)
    // V3-6：数据统一由 /api/posters/data 装配端点提供
    expect(apiMock).toHaveBeenCalledWith('/api/posters/data?report_id=5')
    expect(buildPosterData).toHaveBeenCalledWith(POSTER_PAYLOAD)
    // 浏览器端：主按钮为下载 PNG
    expect(screen.getByTestId('poster-share-btn')).toHaveTextContent('下载 PNG')
  })

  it('预览后点击主按钮触发分享出口并带上文件名', async () => {
    const user = userEvent.setup()
    render(<SharePosterButton report={REPORT} workout={WORKOUT} />)
    await user.click(screen.getByTestId('share-poster-btn'))
    await screen.findByRole('dialog')

    await user.click(screen.getByTestId('poster-share-btn'))
    await waitFor(() =>
      expect(sharePosterImage).toHaveBeenCalledWith(
        expect.objectContaining({
          dataUrl: DATA_URL,
          filename: expect.stringContaining('2026-08-12'),
        }),
      ),
    )
  })

  it('原生端主按钮文案为「分享…」', async () => {
    isNativeShare.mockReturnValue(true)
    const user = userEvent.setup()
    render(<SharePosterButton report={REPORT} workout={WORKOUT} />)
    await user.click(screen.getByTestId('share-poster-btn'))
    await screen.findByRole('dialog')
    expect(screen.getByTestId('poster-share-btn')).toHaveTextContent('分享…')
  })

  it('关闭按钮收起弹层', async () => {
    const user = userEvent.setup()
    render(<SharePosterButton report={REPORT} workout={WORKOUT} />)
    await user.click(screen.getByTestId('share-poster-btn'))
    await screen.findByRole('dialog')
    await user.click(screen.getByTestId('poster-close-btn'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('有评分时不显示解锁提示', () => {
    render(<SharePosterButton report={REPORT} />)
    expect(screen.queryByTestId('share-poster-hint')).not.toBeInTheDocument()
  })

  it('report.score 为 null 时提示「重新生成点评可解锁评分海报」，不阻断分享', async () => {
    const user = userEvent.setup()
    render(<SharePosterButton report={{ ...REPORT, score: null }} />)
    expect(screen.getByTestId('share-poster-hint')).toHaveTextContent('重新生成点评可解锁评分海报')
    // 不阻断：仍可生成并预览
    await user.click(screen.getByTestId('share-poster-btn'))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('生成失败：回到可点击状态并提示错误', async () => {
    renderPosterDataUrl.mockImplementation(() => {
      throw new Error('当前环境不支持 Canvas 2D')
    })
    const user = userEvent.setup()
    render(<SharePosterButton report={REPORT} workout={WORKOUT} />)
    await user.click(screen.getByTestId('share-poster-btn'))

    expect(await screen.findByTestId('share-poster-error')).toHaveTextContent('Canvas')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByTestId('share-poster-btn')).toBeEnabled()
  })

  it('分享出口失败时在弹层内提示', async () => {
    sharePosterImage.mockRejectedValue(new Error('分享被取消'))
    const user = userEvent.setup()
    render(<SharePosterButton report={REPORT} workout={WORKOUT} />)
    await user.click(screen.getByTestId('share-poster-btn'))
    await screen.findByRole('dialog')
    await user.click(screen.getByTestId('poster-share-btn'))
    expect(await screen.findByTestId('poster-share-error')).toHaveTextContent('分享被取消')
  })
})
