import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, apiForm } from '../api/client'

const MAX_FILES = 9

const STATUS_LABEL = {
  auto_matched: '自动匹配（已融合佳明数据）',
  manual_matched: '人工匹配',
  xunji_only: '仅训记数据',
  garmin_only: '仅佳明数据',
  pending: '已入待确认队列',
  unmatched: '未匹配',
}

function toNumber(value) {
  if (value === '' || value === null || value === undefined) return null
  const n = Number(value)
  return Number.isNaN(n) ? null : n
}

/** 单张图的识别预览卡片：字段可编辑，确认后入库。 */
function PreviewCard({ card, index, onChange, onConfirm }) {
  const d = card.data
  const setField = (key, value) => onChange(index, { ...d, [key]: value })
  const setMovement = (mi, movement) => {
    const movements = d.movements.map((m, i) => (i === mi ? movement : m))
    setField('movements', movements)
  }
  const setSet = (mi, si, patch) => {
    const movement = d.movements[mi]
    setMovement(mi, { ...movement, sets: movement.sets.map((s, i) => (i === si ? { ...s, ...patch } : s)) })
  }

  return (
    <div data-testid={`preview-card-${index}`} className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-500">{card.filename}</span>
        {card.confirmed && (
          <span data-testid={`confirm-result-${index}`} className="text-sm font-medium text-green-700">
            已入库 · {STATUS_LABEL[card.matchStatus] || card.matchStatus}
            {card.workoutId && (
              <Link to={`/workouts/${card.workoutId}`} className="ml-2 text-indigo-600 underline">
                查看训练
              </Link>
            )}
          </span>
        )}
      </div>
      <p data-testid={`confidence-hint-${index}`} className="mb-3 rounded bg-amber-50 px-3 py-2 text-xs text-amber-700">
        以下为 AI 识别结果（未落库），请逐项核对，重点检查动作名 / 重量 / 次数，修正后再确认入库。
      </p>

      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
        <label className="text-xs text-gray-500">
          日期
          <input
            data-testid={`field-datestr-${index}`}
            type="date"
            className="mt-1 w-full rounded border px-2 py-1 text-sm"
            value={d.datestr || ''}
            onChange={(e) => setField('datestr', e.target.value)}
            disabled={card.confirmed}
          />
        </label>
        <label className="text-xs text-gray-500">
          标题
          <input
            data-testid={`field-title-${index}`}
            type="text"
            className="mt-1 w-full rounded border px-2 py-1 text-sm"
            value={d.title || ''}
            onChange={(e) => setField('title', e.target.value)}
            disabled={card.confirmed}
          />
        </label>
        <label className="text-xs text-gray-500">
          热量（千卡）
          <input
            data-testid={`field-calories-${index}`}
            type="number"
            className="mt-1 w-full rounded border px-2 py-1 text-sm"
            value={d.calories ?? ''}
            onChange={(e) => setField('calories', toNumber(e.target.value))}
            disabled={card.confirmed}
          />
        </label>
        <label className="text-xs text-gray-500">
          开始时间（选填，用于匹配佳明）
          <input
            data-testid={`field-start-${index}`}
            type="time"
            className="mt-1 w-full rounded border px-2 py-1 text-sm"
            value={d.start_time || ''}
            onChange={(e) => setField('start_time', e.target.value || null)}
            disabled={card.confirmed}
          />
        </label>
        <label className="text-xs text-gray-500">
          结束时间（选填）
          <input
            data-testid={`field-end-${index}`}
            type="time"
            className="mt-1 w-full rounded border px-2 py-1 text-sm"
            value={d.end_time || ''}
            onChange={(e) => setField('end_time', e.target.value || null)}
            disabled={card.confirmed}
          />
        </label>
        <label className="text-xs text-gray-500">
          时长（秒）
          <input
            data-testid={`field-duration-${index}`}
            type="number"
            className="mt-1 w-full rounded border px-2 py-1 text-sm"
            value={d.duration_s ?? ''}
            onChange={(e) => setField('duration_s', toNumber(e.target.value))}
            disabled={card.confirmed}
          />
        </label>
      </div>

      {d.movements.map((mv, mi) => (
        <div key={mi} className="mb-3 rounded border border-gray-100 bg-gray-50 p-3">
          <div className="mb-2 flex items-center gap-2">
            <input
              data-testid={`movement-name-${index}-${mi}`}
              type="text"
              className="flex-1 rounded border px-2 py-1 text-sm font-medium"
              value={mv.name}
              onChange={(e) => setMovement(mi, { ...mv, name: e.target.value })}
              disabled={card.confirmed}
            />
            {!card.confirmed && (
              <button
                data-testid={`del-movement-${index}-${mi}`}
                className="text-xs text-red-600"
                onClick={() => setField('movements', d.movements.filter((_, i) => i !== mi))}
              >
                删除动作
              </button>
            )}
          </div>
          {mv.sets.map((s, si) => (
            <div key={si} className="mb-1 flex items-center gap-2 text-sm">
              <span className="w-8 text-gray-400">{si + 1}</span>
              <input
                data-testid={`set-weight-${index}-${mi}-${si}`}
                type="number"
                step="0.5"
                className="w-20 rounded border px-2 py-1"
                value={s.weight ?? ''}
                onChange={(e) => setSet(mi, si, { weight: toNumber(e.target.value) })}
                disabled={card.confirmed}
              />
              <span className="text-gray-500">kg ×</span>
              <input
                data-testid={`set-reps-${index}-${mi}-${si}`}
                type="number"
                className="w-16 rounded border px-2 py-1"
                value={s.reps ?? ''}
                onChange={(e) => setSet(mi, si, { reps: toNumber(e.target.value) })}
                disabled={card.confirmed}
              />
              <span className="text-gray-500">次</span>
              {!card.confirmed && (
                <button
                  data-testid={`del-set-${index}-${mi}-${si}`}
                  className="text-xs text-red-600"
                  onClick={() =>
                    setMovement(mi, { ...mv, sets: mv.sets.filter((_, i) => i !== si) })
                  }
                >
                  删除
                </button>
              )}
            </div>
          ))}
          {!card.confirmed && (
            <button
              data-testid={`add-set-${index}-${mi}`}
              className="mt-1 text-xs text-indigo-600"
              onClick={() =>
                setMovement(mi, { ...mv, sets: [...mv.sets, { weight: 0, unit: 'kg', reps: 1 }] })
              }
            >
              + 添加一组
            </button>
          )}
        </div>
      ))}

      {!card.confirmed && (
        <div className="flex items-center gap-3">
          <button
            data-testid={`add-movement-${index}`}
            className="text-sm text-indigo-600"
            onClick={() =>
              setField('movements', [...d.movements, { name: '', sets: [{ weight: 0, unit: 'kg', reps: 1 }] }])
            }
          >
            + 添加动作
          </button>
          <button
            data-testid={`confirm-btn-${index}`}
            className="ml-auto rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            onClick={() => onConfirm(index)}
            disabled={card.confirming}
          >
            {card.confirming ? '入库中…' : '确认入库'}
          </button>
        </div>
      )}
      {card.confirmError && (
        <p data-testid={`confirm-error-${index}`} className="mt-2 text-sm text-red-600">
          {card.confirmError}
        </p>
      )}
    </div>
  )
}

export default function ScreenshotImportPage() {
  const [files, setFiles] = useState([])
  const [extracting, setExtracting] = useState(false)
  const [cards, setCards] = useState([])
  const [globalError, setGlobalError] = useState('')
  const inputRef = useRef(null)

  const addFiles = (fileList) => {
    const images = Array.from(fileList).filter((f) => f.type.startsWith('image/'))
    setFiles((prev) => [...prev, ...images].slice(0, MAX_FILES))
    setCards([])
    setGlobalError('')
  }

  const handleExtract = async () => {
    setExtracting(true)
    setGlobalError('')
    try {
      const fd = new FormData()
      files.forEach((f) => fd.append('files', f))
      const resp = await apiForm('/api/screenshot/extract', fd)
      setCards(
        resp.results.map((r) => ({
          filename: r.filename,
          ok: r.ok,
          error: r.error,
          data: r.ok ? { start_time: null, end_time: null, duration_s: null, calories: null, ...r.data } : null,
          confirmed: false,
          confirming: false,
        })),
      )
    } catch (err) {
      setGlobalError(`识别请求失败：${err.message}`)
    } finally {
      setExtracting(false)
    }
  }

  const updateCard = (index, data) => {
    setCards((prev) => prev.map((c, i) => (i === index ? { ...c, data } : c)))
  }

  const handleConfirm = async (index) => {
    const card = cards[index]
    setCards((prev) => prev.map((c, i) => (i === index ? { ...c, confirming: true, confirmError: '' } : c)))
    try {
      const d = card.data
      const resp = await api('/api/screenshot/confirm', {
        method: 'POST',
        body: JSON.stringify({
          datestr: d.datestr,
          title: d.title,
          movements: d.movements,
          start_time: d.start_time || null,
          end_time: d.end_time || null,
          duration_s: d.duration_s ?? null,
          calories: d.calories ?? null,
        }),
      })
      setCards((prev) =>
        prev.map((c, i) =>
          i === index
            ? { ...c, confirming: false, confirmed: true, matchStatus: resp.match_status, workoutId: resp.workout_id }
            : c,
        ),
      )
    } catch (err) {
      setCards((prev) =>
        prev.map((c, i) => (i === index ? { ...c, confirming: false, confirmError: `入库失败：${err.message}` } : c)),
      )
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-gray-900">截图识别补录</h1>
      <p className="text-sm text-gray-500">
        上传训记/佳明截图，AI 识别为结构化数据，核对确认后写入训练档案并重跑当日匹配。识别阶段不落库。
      </p>

      <div
        data-testid="drop-zone"
        className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-white p-8 text-gray-500 hover:border-indigo-400"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault()
          addFiles(e.dataTransfer.files)
        }}
        onClick={() => inputRef.current?.click()}
      >
        <p>拖拽截图到此处，或点击选择文件（可多选，最多 {MAX_FILES} 张）</p>
        <input
          data-testid="file-input"
          ref={inputRef}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={(e) => addFiles(e.target.files)}
        />
      </div>

      {files.length > 0 && (
        <ul className="rounded-lg border border-gray-200 bg-white p-3 text-sm">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex justify-between py-1">
              <span>{f.name}</span>
              <span className="text-gray-400">{(f.size / 1024).toFixed(0)} KB</span>
            </li>
          ))}
        </ul>
      )}

      <button
        data-testid="extract-btn"
        className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        disabled={files.length === 0 || extracting}
        onClick={handleExtract}
      >
        {extracting ? '识别中…' : '开始识别'}
      </button>

      {globalError && (
        <p data-testid="global-error" className="text-sm text-red-600">
          {globalError}
        </p>
      )}

      <div className="space-y-4">
        {cards.map((card, i) =>
          card.ok ? (
            <PreviewCard key={i} card={card} index={i} onChange={updateCard} onConfirm={handleConfirm} />
          ) : (
            <div
              key={i}
              data-testid={`error-card-${i}`}
              className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
            >
              <span className="font-medium">{card.filename}：</span>
              {card.error}
            </div>
          ),
        )}
      </div>
    </div>
  )
}
