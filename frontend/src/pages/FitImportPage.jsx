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

const ALLOWED_EXT = ['.fit', '.tcx']

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
      setError('仅支持 .fit / .tcx 文件（从 Garmin Connect 活动详情页导出）')
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
      setError(`导入失败：${err.message}`)
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-gray-900">佳明文件导入</h1>
      <p className="text-sm text-gray-500">
        佳明接口不可用时的降级通道：在 Garmin Connect 网页端打开活动 → 导出 FIT/TCX 文件，
        在此处上传。系统会解析并写入训练档案，自动触发当日匹配融合。
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
        <p>拖拽 FIT/TCX 文件到此处，或点击选择文件</p>
        <input
          data-testid="file-input"
          ref={inputRef}
          type="file"
          accept=".fit,.tcx"
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
