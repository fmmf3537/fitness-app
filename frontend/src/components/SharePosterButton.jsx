import { useState } from 'react'
import { api } from '../api/client'
import { buildPosterData, renderPosterDataUrl } from '../utils/poster'
import { isNativeShare, sharePosterImage } from '../utils/sharePoster'
import PosterPreviewModal from './PosterPreviewModal'

/**
 * V3-5 「分享海报」按钮：生成 → 预览弹层 → 分享（原生）/ 下载（浏览器）。
 * props：report（必需，取 score/one_liner/标题/日期）；
 *       workout（可选；缺省时按 report.workout_id 拉取，用于总容量/时长/热量指标）。
 */
export default function SharePosterButton({ report, workout = null, testId = 'share-poster-btn' }) {
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
      let w = workout
      if (!w && report?.workout_id) {
        w = await api(`/api/workouts/${report.workout_id}`)
      }
      const data = buildPosterData({ report, workout: w })
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
