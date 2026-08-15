import { useState } from 'react'
import { api } from '../api/client'
import { buildPosterData, renderPosterDataUrl } from '../utils/poster'
import { isNativeShare, sharePosterImage } from '../utils/sharePoster'
import PosterPreviewModal from './PosterPreviewModal'

/**
 * V3-5/V3-6 「分享海报」按钮：生成 → 预览弹层 → 分享（原生）/ 下载（浏览器）。
 * props：report（必需）。
 * V3-6：海报数据统一由 GET /api/posters/data?report_id= 一次装配；
 *       report.score 为 null 时提示「重新生成点评可解锁评分海报」（不阻断分享）。
 */
export default function SharePosterButton({ report, testId = 'share-poster-btn' }) {
  const [generating, setGenerating] = useState(false)
  const [dataUrl, setDataUrl] = useState('')
  const [posterDate, setPosterDate] = useState('')
  const [error, setError] = useState('')
  const [sharing, setSharing] = useState(false)
  const [shareError, setShareError] = useState('')

  const handleGenerate = async () => {
    if (generating) return
    setGenerating(true)
    setError('')
    try {
      const payload = await api(`/api/posters/data?report_id=${report.id}`)
      const data = buildPosterData(payload)
      const url = renderPosterDataUrl(data)
      setDataUrl(url)
      setPosterDate(data.date || report?.date || '')
    } catch (err) {
      setError(err.message || '海报生成失败')
    } finally {
      setGenerating(false)
    }
  }

  const handleShare = async () => {
    if (sharing) return
    setSharing(true)
    setShareError('')
    try {
      await sharePosterImage({
        dataUrl,
        filename: `fitness-poster-${posterDate || 'share'}.png`,
        title: '训练分享海报',
      })
    } catch (err) {
      setShareError(err.message || '分享失败')
    } finally {
      setSharing(false)
    }
  }

  return (
    <>
      <span className="inline-flex items-center gap-2">
        <button
          type="button"
          data-testid={testId}
          disabled={generating}
          onClick={handleGenerate}
          className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {generating ? '生成中…' : '分享海报'}
        </button>
        {report?.score == null && (
          <span data-testid="share-poster-hint" className="text-xs text-gray-400">
            重新生成点评可解锁评分海报
          </span>
        )}
        {error && (
          <span data-testid="share-poster-error" className="text-xs text-red-600">
            {error}
          </span>
        )}
      </span>
      {dataUrl && (
        <PosterPreviewModal
          dataUrl={dataUrl}
          sharing={sharing}
          shareError={shareError}
          native={isNativeShare()}
          onShare={handleShare}
          onClose={() => {
            setDataUrl('')
            setShareError('')
          }}
        />
      )}
    </>
  )
}
