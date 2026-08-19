import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiForm } from '../api/client'

const STATUS_LABEL = {
  auto_matched: '自动匹配（已融合训记数据）',
  manual_matched: '人工匹配',
  xunji_only: '仅训记数据',
  garmin_only: '仅佳明数据',
  pending: '已入待确认队列',
}

const ALLOWED_EXT = ['.fit', '.tcx', '.gpx', '.kml']
const ALLOWED_EXT_LABEL = '.fit / .tcx / .gpx / .kml'
// V3-10b：accept 只是体验层（扩展名校验 + 服务端 422 双层把关）。
// 安卓选择器按 MIME 过滤，微信/QQ 下载到 Download/WeiXin 的文件未被 MediaStore
// 索引对应 MIME（多标为 application/octet-stream），纯扩展名 accept 会导致文件不可见，
// 故混入常见 MIME 兑底。
const ACCEPT =
  '.fit,.tcx,.gpx,.kml,application/gpx+xml,application/octet-stream,text/xml,application/xml'

export default function FitImportPage() {
  const [file, setFile] = useState(null)
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const inputRef = useRef(null)

  const pickFile = (fileList) => {
    const f = fileList?.[0]
    setResult(null)
    setError('')
    if (!f) {
      setFile(null)
      return
    }
    const ext = f.name.slice(f.name.lastIndexOf('.')).toLowerCase()
    if (!ALLOWED_EXT.includes(ext)) {
      setFile(null)
      setError(`仅支持 ${ALLOWED_EXT_LABEL} 文件（佳明/Strava/华为/咕咚等平台导出）`)
      return
    }
    setFile(f)
  }

  const handleImport = async () => {
    setImporting(true)
    setError('')
    setResult(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const resp = await apiForm('/api/import/fit', fd)
      setResult(resp)
    } catch (err) {
      // 优先展示服务端 detail 友好文案（如“GPX 文件不含轨迹（trk）”），其次裸 message
      setError(`导入失败：${err.detail || err.message}`)
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-gray-900">佳明文件导入</h1>
      <p className="text-sm text-gray-500">
        佳明接口不可用时的降级通道，也支持 Strava/华为/咕咚/两步路等平台导出的通用格式：
        上传 FIT / TCX / GPX / KML 文件（KML 需含 gx:Track 时间戳轨迹）。
        系统会解析并写入训练档案，自动触发当日匹配融合。
        选择器里看不到文件时，可先把文件移到 Download 根目录再选。
      </p>

      <div
        data-testid="drop-zone"
        className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-white p-8 text-gray-500 hover:border-indigo-400"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault()
          pickFile(e.dataTransfer.files)
        }}
        onClick={() => inputRef.current?.click()}
      >
        <p>拖拽 FIT/TCX/GPX/KML 文件到此处，或点击选择文件</p>
        <input
          data-testid="file-input"
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => pickFile(e.target.files)}
        />
      </div>

      {file && (
        <p data-testid="file-info" className="text-sm text-gray-600">
          已选择：{file.name}（{(file.size / 1024).toFixed(0)} KB）
        </p>
      )}

      <button
        data-testid="import-btn"
        className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        disabled={!file || importing}
        onClick={handleImport}
      >
        {importing ? '导入中…' : '开始导入'}
      </button>

      {error && (
        <p data-testid="import-error" className="text-sm text-red-600">
          {error}
        </p>
      )}

      {result && (
        <div
          data-testid="import-result"
          className="rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-800"
        >
          <p className="font-medium">导入成功</p>
          <p className="mt-1">
            活动日期：{result.date} · 类型：{result.activity_type || '未知'} · 匹配结果：
            {STATUS_LABEL[result.match_status] || '未匹配'}
            {result.workout_id && (
              <Link
                data-testid="workout-link"
                to={`/workouts/${result.workout_id}`}
                className="ml-2 text-indigo-600 underline"
              >
                查看训练
              </Link>
            )}
          </p>
        </div>
      )}
    </div>
  )
}
