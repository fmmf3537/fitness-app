import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import useModalAccessibility from '../hooks/useModalAccessibility'
import Button from './ui/Button'

const STORAGE_KEY = 'fh_onboarding_v1_done'
const STEPS = [
  { title: '先连接 AI 教练', description: '在“我的”页面配置你使用的 LLM Provider 和 API Key。', action: '去配置', to: '/settings' },
  { title: '同步真实训练', description: '回到训练日历点击“同步今日”，任务状态来自服务器。', action: '看日历', to: '/' },
  { title: '查看报告与趋势', description: '同步完成后，复盘、AI 报告和趋势会使用你的真实数据。', action: '查看趋势', to: '/trends' },
]

export default function Onboarding() {
  const navigate = useNavigate()
  const dialogRef = useRef(null)
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState(0)

  useEffect(() => {
    try { setOpen(localStorage.getItem(STORAGE_KEY) !== '1') } catch { setOpen(false) }
  }, [])

  const finish = (target) => {
    try { localStorage.setItem(STORAGE_KEY, '1') } catch { /* ignore */ }
    setOpen(false)
    if (target) navigate(target)
  }

  useModalAccessibility({ open, containerRef: dialogRef, onClose: finish })

  if (!open) return null
  const item = STEPS[step]
  return (
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/55 p-4 backdrop-blur-sm sm:items-center" role="dialog" aria-modal="true" aria-labelledby="onboarding-title">
      <div ref={dialogRef} tabIndex={-1} className="w-full max-w-md rounded-3xl bg-white p-6 shadow-2xl dark:bg-gray-900">
        <div className="mb-5 flex gap-1" aria-label={`第 ${step + 1} 步，共 ${STEPS.length} 步`}>
          {STEPS.map((_, index) => <span key={index} className={`h-1.5 flex-1 rounded-full ${index <= step ? 'bg-indigo-600' : 'bg-gray-200 dark:bg-gray-700'}`} />)}
        </div>
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-600 text-xl font-black text-white">{step + 1}</div>
        <h2 id="onboarding-title" className="text-xl font-black text-gray-950 dark:text-white">{item.title}</h2>
        <p className="mt-2 text-sm leading-6 text-gray-600 dark:text-gray-300">{item.description}</p>
        <div className="mt-6 flex gap-2">
          <Button variant="ghost" onClick={() => finish()} className="mr-auto">跳过</Button>
          {step > 0 && <Button variant="secondary" onClick={() => setStep((value) => value - 1)}>上一步</Button>}
          {step < STEPS.length - 1
            ? <Button onClick={() => setStep((value) => value + 1)}>下一步</Button>
            : <Button onClick={() => finish(item.to)}>{item.action}</Button>}
        </div>
      </div>
    </div>
  )
}
