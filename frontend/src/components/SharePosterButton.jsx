import { useState } from 'react'
import { api } from '../api/client'
import { buildPosterData, renderPosterDataUrl } from '../utils/poster'
import { isNativeShare, savePosterImage, sharePosterImage } from '../utils/sharePoster'
import PosterPreviewModal from './PosterPreviewModal'

/**
 * V3-5/V3-6 「分享海报」按钮：生成 → 预览弹层 → 分享（原生）/ 下载（浏览器）。
 * props：report（必需）；fallbackTitle / label 可选。
 * V3-6：海报数据统一由 GET /api/posters/data?report_id= 一次装配；
 *       report.score 为 null 时提示「重新生成点评可解锁评分海报」（不阻断分享）。
 * 周复盘无 workout 时 buildPosterData 标题为「训练记录」，传入 fallbackTitle 则覆盖。
 */
export default function SharePosterButton({
  report,
  testId = 'share-poster-btn',
  fallbackTitle,
  label = '分享海报',
}) {
  const [generating, setGenerating] = useState(false)
  const [dataUrl, setDataUrl] = useState('')
  const [posterDate, setPosterDate] = useState('')
  const [error, setError] = useState('')
  const [sharing, setSharing] = useState(false)
  const [shareError, setShareError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [saveMessage, setSaveMessage] = useState('')
  const filename = `${report?.type || 'workout'}-${posterDate || 'share'}.png`

  const handleGenerate = async () => {
    if (generating) return
    setGenerating(true)
    setError('')
    try {
      const payload = await api(`/api/posters/data?report_id=${report.id}`)
      const data = buildPosterData(payload)
      // 无 workout 时标题兜底为「训练记录」；调用方传入 fallbackTitle 则覆盖（文案级，非定制模板）
      if (fallbackTitle && data.title === '训练记录') {
        data.title = fallbackTitle
      }
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
        filename,
        title: report?.type === 'monthly' ? '月度训练成绩单' : report?.type === 'weekly' ? '本周训练战报' : '训练分享海报',
      })
    } catch (err) {
      setShareError(err.message || '分享失败')
    } finally {
      setSharing(false)
    }
  }

  const handleSave = async () => {
    if (saving) return
    setSaving(true)
    setSaveError('')
    setSaveMessage('')
    try {
      const result = await savePosterImage({ dataUrl, filename })
      setSaveMessage(result.mode === 'download' ? '已开始下载 PNG' : '已保存到本地文档目录')
    } catch (err) {
      setSaveError(err.message || '保存失败')
    } finally {
      setSaving(false)
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
          className="min-h-[44px] rounded-xl border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-4 text-sm font-medium text-gray-700 dark:text-gray-300 shadow-sm active:bg-gray-100 dark:active:bg-gray-800 disabled:opacity-50"
        >
          {generating ? '生成中…' : label}
        </button>
        {report?.type === 'session_review' && report?.score == null && (
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
          saving={saving}
          shareError={shareError}
          saveError={saveError}
          saveMessage={saveMessage}
          native={isNativeShare()}
          onShare={handleShare}
          onSave={handleSave}
          onClose={() => {
            setDataUrl('')
            setShareError('')
            setSaveError('')
            setSaveMessage('')
          }}
        />
      )}
    </>
  )
}
