import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

export default function TrendChart({ option, testId }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!ref.current) return undefined
    const chart = echarts.init(ref.current)
    if (option) {
      chart.setOption(option)
    }
    const handleResize = () => chart.resize()
    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      chart.dispose()
    }
  }, [option])

  return <div ref={ref} data-testid={testId} className="h-72 w-full" />
}
