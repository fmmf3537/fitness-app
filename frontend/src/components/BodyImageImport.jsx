// V3-9 体脂秤「身体测量报告」图片导入面板：上传 → 识别 → 确认入库（不落库直到确认）。
import { useRef, useState } from 'react'
import { api, apiForm } from '../api/client'
import { METRIC_DEFS } from '../utils/bodyMetrics'

const SYNCABLE = new Set(['weight', 'bodyfat'])

function defOf(type) {
  return METRIC_DEFS.find((d) => d.type === type)
}

function toNumber(value) {
  const n = Number(value)
  return Number.isNaN(n) ? null : n
}

/**
 * props:
 *  - onImported(summaryText): 入库成功回调（父组件刷新记录并 toast）
 */
export default function BodyImageImport({ onImported }) {
  const [file, setFile] = useState(null)
  const [extracting, setExtracting] = useState(false)
  const [error, setError] = useState('')
  // result: { date, metrics: [{type, value, selected, warning?}] } | null
  const [result, setResult] = useState(null)
  const [syncXunji, setSyncXunji] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const inputRef = useRef(null)

  const handleFile = (fileList) => {
    const f = Array.from(fileList || []).find((x) => x.type.startsWith('image/'))
    setFile(f || null)
    setResult(null)
    setError('')
  }

  const handleExtract = async () => {
    if (!file) return
    setExtracting(true)
    setError('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      const data = await apiForm('/api/body-metrics/extract-image', fd)
      setResult({
        date: data.date,
        metrics: (data.metrics || []).map((m) => ({ ...m, selected: true })),
      })
      setSyncXunji(false)
    } catch (err) {
      setError(`识别失败：${err.message}`)
    } finally {
      setExtracting(false)
    }
  }

  const updateMetric = (index, patch) => {
    setResult((r) => ({
      ...r,
      metrics: r.metrics.map((m, i) => (i === index ? { ...m, ...patch } : m)),
    }))
  }

  const hasSyncableSelected =
    result?.metrics.some((m) => m.selected && SYNCABLE.has(m.type)) ?? false

  const handleConfirm = async () => {
    if (!result) return
    setConfirming(true)
    setError('')
    try {
      const resp = await api('/api/body-metrics/confirm-import', {
        method: 'POST',
        body: JSON.stringify({
          date: result.date,
          metrics: result.metrics.map((m) => ({
            type: m.type,
            value: toNumber(m.value),
            selected: Boolean(m.selected),
          })),
          sync_xunji: syncXunji,
        }),
      })
      const syncNote = resp.sync?.status === 'synced' ? '，已同步体重/体脂到训记' : ''
      onImported?.(`已入库 ${resp.count} 项指标${syncNote}`)
      setResult(null)
      setFile(null)
    } catch (err) {
      setError(`入库失败：${err.message}`)
    } finally {
      setConfirming(false)
    }
  }

  return (
    <div data-testid="image-import-panel" className="space-y-3">
      {!result && (
        <>
          <div
            data-testid="scale-drop-zone"
            className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-gray-50 p-6 text-sm text-gray-500 hover:border-indigo-400"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault()
              handleFile(e.dataTransfer.files)
            }}
            onClick={() => inputRef.current?.click()}
          >
            <p>{file ? file.name : '点击选择或拖拽体脂秤报告图片（jpg/png，≤10MB）'}</p>
            <input
              data-testid="scale-file-input"
              ref={inputRef}
              type="file"
              accept="image/jpeg,image/png"
              className="hidden"
              onChange={(e) => handleFile(e.target.files)}
            />
          </div>
          <button
            data-testid="extract-image-btn"
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            disabled={!file || extracting}
            onClick={handleExtract}
          >
            {extracting ? '识别中…' : '开始识别'}
          </button>
        </>
      )}

      {result && (
        <div data-testid="import-preview" className="space-y-3">
          <p className="rounded bg-amber-50 px-3 py-2 text-xs text-amber-700">
            以下为 AI 识别结果（未落库），请逐项核对修正后再确认入库。
          </p>
          <label className="block text-xs text-gray-500">
            测量日期
            <input
              data-testid="import-date"
              type="date"
              className="mt-1 w-44 rounded border px-2 py-1 text-sm"
              value={result.date || ''}
              onChange={(e) => setResult((r) => ({ ...r, date: e.target.value }))}
            />
          </label>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-400">
                <th className="py-1">入库</th>
                <th>指标</th>
                <th>数值</th>
                <th>单位</th>
              </tr>
            </thead>
            <tbody>
              {result.metrics.map((m, i) => {
                const def = defOf(m.type)
                return (
                  <tr key={m.type} data-testid={`import-row-${m.type}`} className="border-t border-gray-100">
                    <td className="py-1">
                      <input
                        data-testid={`import-select-${m.type}`}
                        type="checkbox"
                        checked={Boolean(m.selected)}
                        onChange={(e) => updateMetric(i, { selected: e.target.checked })}
                      />
                    </td>
                    <td>{def?.label || m.type}</td>
                    <td>
                      <input
                        data-testid={`import-value-${m.type}`}
                        type="number"
                        step="0.1"
                        className="w-24 rounded border px-2 py-1"
                        value={m.value ?? ''}
                        onChange={(e) => updateMetric(i, { value: e.target.value })}
                      />
                      {m.warning && (
                        <span data-testid={`import-warning-${m.type}`} className="ml-2 text-xs text-amber-600">
                          {m.warning}
                        </span>
                      )}
                    </td>
                    <td className="text-gray-500">{def?.unit || ''}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              data-testid="import-sync-xunji"
              type="checkbox"
              checked={syncXunji}
              disabled={!hasSyncableSelected}
              onChange={(e) => setSyncXunji(e.target.checked)}
            />
            同步体重/体脂到训记（仅体重与体脂率会同步）
          </label>
          <div className="flex items-center gap-3">
            <button
              data-testid="confirm-import-btn"
              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              disabled={confirming || !result.metrics.some((m) => m.selected)}
              onClick={handleConfirm}
            >
              {confirming ? '入库中…' : '确认入库'}
            </button>
            <button
              data-testid="import-reset-btn"
              className="text-sm text-gray-500 hover:text-gray-700"
              onClick={() => {
                setResult(null)
                setFile(null)
              }}
            >
              重新选择图片
            </button>
          </div>
        </div>
      )}

      {error && (
        <p data-testid="import-error" className="text-sm text-red-600">
          {error}
        </p>
      )}
    </div>
  )
}
