import { useEffect, useState } from 'react'
import { api } from '../api/client'
import Button from './ui/Button'
import Card from './ui/Card'

const COMPARISON_LABEL = { matched: '按计划', less: '少于计划', more: '多于计划',
  unmatched: '未找到同名动作', extra: '计划外动作' }

export default function TrainingContextSection({ workout }) {
  const [comparison, setComparison] = useState(null)
  const [feedback, setFeedback] = useState({ fatigue: '', soreness: '', discomfort: '', note: '' })
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let active = true
    api(`/api/training/plan-comparison/${workout.date}`)
      .then((data) => { if (active) setComparison(data) })
      .catch(() => { if (active) setComparison(null) })
    api(`/api/training/feedback/${workout.id}`)
      .then((data) => { if (active && data.feedback) setFeedback({
        fatigue: data.feedback.fatigue ?? '', soreness: data.feedback.soreness ?? '',
        discomfort: data.feedback.discomfort || '', note: data.feedback.note || '',
      }) })
      .catch(() => {})
    return () => { active = false }
  }, [workout.date, workout.id])

  const save = async () => {
    setSaving(true)
    setMessage('')
    try {
      await api(`/api/training/feedback/${workout.id}`, { method: 'PUT', body: JSON.stringify({
        fatigue: feedback.fatigue === '' ? null : Number(feedback.fatigue),
        soreness: feedback.soreness === '' ? null : Number(feedback.soreness),
        discomfort: feedback.discomfort, note: feedback.note,
      }) })
      setMessage('已保存。重新生成点评后，AI 会参考这份主观反馈。')
    } catch (err) { setMessage(`保存失败：${err.message}`) }
    finally { setSaving(false) }
  }

  const remove = async () => {
    setSaving(true)
    setMessage('')
    try {
      await api(`/api/training/feedback/${workout.id}`, { method: 'DELETE' })
      setFeedback({ fatigue: '', soreness: '', discomfort: '', note: '' })
      setMessage('已删除训练后反馈')
    } catch (err) { setMessage(`删除失败：${err.message}`) }
    finally { setSaving(false) }
  }

  return <div className="mt-4 space-y-4">
    <Card>
      <h3 className="mb-2 font-bold text-gray-900 dark:text-gray-100">数据依据</h3>
      <p className="text-sm text-gray-600 dark:text-gray-300">
        训练组次：{workout.xunji_raw ? '训记' : '缺失'} · 心率：{workout.avg_hr != null || workout.heart_rate?.length ? '佳明' : '缺失'} · 融合状态：{workout.match_status || '未知'}
      </p>
      {(!workout.xunji_raw || (workout.avg_hr == null && !workout.heart_rate?.length) || workout.match_status === 'pending') &&
        <p className="mt-1 text-xs text-amber-700">数据不完整或待确认，AI 分析和计划对照仅供参考。</p>}
    </Card>
    <Card>
      <h3 className="mb-2 font-bold text-gray-900 dark:text-gray-100">计划与实际</h3>
      {comparison?.status === 'compared' ? <ul className="space-y-1 text-sm">
        {comparison.movements.map((item, i) => <li key={`${item.name}-${i}`} className="flex flex-wrap justify-between gap-2 border-b border-gray-100 py-1 dark:border-gray-800">
          <span>{item.name}</span><span>{item.planned_sets} 组计划 / {item.completed_sets} 组完成 · {COMPARISON_LABEL[item.status] || '无法判定'}</span>
        </li>)}
      </ul> : <p className="text-sm text-gray-600 dark:text-gray-400">{
        comparison?.status === 'rest_day' ? '训记计划显示这天是休息日。' :
        comparison?.status === 'no_workout_data' ? '尚无已同步训练，无法判定完成情况。' :
        comparison?.status === 'no_movement_data' ? '已同步训练缺少动作组次，无法判定计划完成情况。' :
        '没有训练当时的计划快照，无法可靠地对照历史计划。'
      }</p>}
      {comparison?.status === 'compared' && <p className="mt-2 text-xs text-gray-500">按同名动作和完成组数对照；换动作或训练数据缺失需人工判断。</p>}
    </Card>
    <Card>
      <h3 className="mb-1 font-bold text-gray-900 dark:text-gray-100">训练后感受</h3>
      <p className="mb-3 text-xs text-gray-600 dark:text-gray-400">可选填写；重量和次数仍只在训记记录。</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {[["fatigue", "疲劳"], ["soreness", "酸痛"]].map(([key, label]) => <label key={key} className="text-sm">{label}（1–5）
          <select value={feedback[key]} onChange={(e) => setFeedback((v) => ({ ...v, [key]: e.target.value }))} className="mt-1 block min-h-11 w-full rounded-lg border border-gray-300 bg-white px-2 dark:border-gray-700 dark:bg-gray-900">
            <option value="">未填写</option>{[1, 2, 3, 4, 5].map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>)}
      </div>
      <label className="mt-3 block text-sm">动作不适
        <input value={feedback.discomfort} onChange={(e) => setFeedback((v) => ({ ...v, discomfort: e.target.value }))} maxLength={200} className="mt-1 min-h-11 w-full rounded-lg border border-gray-300 bg-white px-3 dark:border-gray-700 dark:bg-gray-900" placeholder="例如：深蹲时右膝不适" />
      </label>
      <label className="mt-3 block text-sm">备注
        <textarea value={feedback.note} onChange={(e) => setFeedback((v) => ({ ...v, note: e.target.value }))} maxLength={1000} rows={2} className="mt-1 w-full rounded-lg border border-gray-300 bg-white p-3 dark:border-gray-700 dark:bg-gray-900" />
      </label>
      <div className="mt-3 flex gap-2"><Button onClick={save} disabled={saving}>保存感受</Button><Button variant="secondary" onClick={remove} disabled={saving}>删除</Button></div>
      {message && <p role="status" className="mt-2 text-xs text-gray-600 dark:text-gray-400">{message}</p>}
    </Card>
  </div>
}
