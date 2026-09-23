import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import PageHeader from '../components/PageHeader'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'

const LABELS = { sessions_week: '每周训练次数', movement_weight: '重点动作最佳负重', body_weight: '体重趋势' }
const UNITS = { sessions_week: '次/周', movement_weight: 'kg', body_weight: 'kg' }

export default function GoalsPage() {
  const [goals, setGoals] = useState([])
  const [kind, setKind] = useState('sessions_week')
  const [target, setTarget] = useState('')
  const [movement, setMovement] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const load = useCallback(() => api('/api/training/goals').then((data) => setGoals(data.goals || [])).catch((err) => setError(err.message)), [])
  useEffect(() => { load() }, [load])

  const add = async (e) => {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      await api('/api/training/goals', { method: 'POST', body: JSON.stringify({ kind, target: Number(target), movement }) })
      setTarget(''); setMovement(''); await load()
    } catch (err) { setError(err.message) }
    finally { setSaving(false) }
  }

  const remove = async (id) => {
    setError('')
    try { await api(`/api/training/goals/${id}`, { method: 'DELETE' }); await load() }
    catch (err) { setError(err.message) }
  }

  return <div className="space-y-4">
    <PageHeader title="训练目标" subtitle="用已同步的数据观察进步" />
    <Card className="mt-4">
      <h2 className="mb-3 font-bold">添加目标</h2>
      <form onSubmit={add} className="grid gap-3 sm:grid-cols-3">
        <label className="text-sm">类型<select value={kind} onChange={(e) => setKind(e.target.value)} className="mt-1 min-h-11 w-full rounded-lg border border-gray-300 bg-white px-2 dark:bg-gray-900">
          {Object.entries(LABELS).map(([key, label]) => <option value={key} key={key}>{label}</option>)}
        </select></label>
        {kind === 'movement_weight' && <label className="text-sm">动作名称<input value={movement} onChange={(e) => setMovement(e.target.value)} required maxLength={100} className="mt-1 min-h-11 w-full rounded-lg border border-gray-300 bg-white px-3 dark:bg-gray-900" /></label>}
        <label className="text-sm">目标（{UNITS[kind]}）<input type="number" step={kind === 'sessions_week' ? '1' : '0.1'} min="0.1" value={target} onChange={(e) => setTarget(e.target.value)} required className="mt-1 min-h-11 w-full rounded-lg border border-gray-300 bg-white px-3 dark:bg-gray-900" /></label>
        <div className="flex items-end"><Button type="submit" disabled={saving}>添加</Button></div>
      </form>
    </Card>
    {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    <div className="grid gap-3 sm:grid-cols-2">
      {goals.map((goal) => <Card key={goal.id}>
        <div className="flex items-start justify-between gap-3"><div><h2 className="font-bold">{goal.movement ? `${goal.movement} · ` : ''}{LABELS[goal.kind]}</h2>
          <p className="mt-2 text-sm">当前 {goal.current == null ? '暂无数据' : `${goal.current} ${UNITS[goal.kind]}`} / 目标 {goal.target} {UNITS[goal.kind]}</p>
          {!goal.sufficient_data && <p className="mt-1 text-xs text-amber-700">样本较少，暂不判断进度</p>}
          {goal.kind === 'body_weight' && <p className="mt-1 text-xs text-gray-500">当前值采用近 14 天内最多 7 条记录的平均值</p>}
        </div><Button variant="ghost" size="compact" onClick={() => remove(goal.id)}>移除</Button></div>
      </Card>)}
    </div>
    {goals.length === 0 && <p className="text-sm text-gray-600 dark:text-gray-400">还没有目标。添加一个目标后，应用会用训记和身体记录计算当前值。</p>}
  </div>
}
