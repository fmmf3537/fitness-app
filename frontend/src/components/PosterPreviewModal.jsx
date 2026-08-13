/**
 * V3-5 海报预览弹层：海报图 + 操作按钮（分享/下载 + 关闭）。
 * 桌面与移动端通用的居中弹层。
 */
export default function PosterPreviewModal({ dataUrl, sharing, shareError, native, onShare, onClose }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="分享海报预览"
    >
      <div className="flex max-h-full w-full max-w-sm flex-col rounded-xl bg-white p-4 shadow-xl">
        <div className="min-h-0 flex-1 overflow-auto">
          <img
            data-testid="poster-preview-img"
            src={dataUrl}
            alt="训练分享海报预览"
            className="mx-auto w-full rounded-lg border border-gray-200"
          />
        </div>
        {shareError && (
          <p data-testid="poster-share-error" className="mt-2 text-center text-xs text-red-600">
            {shareError}
          </p>
        )}
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            data-testid="poster-close-btn"
            onClick={onClose}
            className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100"
          >
            关闭
          </button>
          <button
            type="button"
            data-testid="poster-share-btn"
            disabled={sharing}
            onClick={onShare}
            className="flex-1 rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {sharing ? '处理中…' : native ? '分享…' : '下载 PNG'}
          </button>
        </div>
      </div>
    </div>
  )
}
