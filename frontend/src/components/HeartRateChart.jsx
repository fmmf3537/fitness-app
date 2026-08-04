import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

export default function HeartRateChart({ data }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!ref.current) return undefined
    const chart = echarts.init(ref.current)
    chart.setOption({
      title: { text: '心率曲线', textStyle: { fontSize: 14 } },
      tooltip: { trigger: 'axis' },
      grid: { left: 50, right: 20, top: 40, bottom: 30 },
      xAxis: {
        type: 'category',
        data: (data || []).map((p) => p.t),
        name: '时间',
      },
      yAxis: { type: 'value', name: 'bpm' },
      series: [
        {
          type: 'line',
          data: (data || []).map((p) => p.hr),
          smooth: true,
          showSymbol: false,
          lineStyle: { color: '#e11d48' },
          areaStyle: { opacity: 0.1 },
        },
      ],
    })
    const handleResize = () => chart.resize()
    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      chart.dispose()
    }
  }, [data])

  return <div ref={ref} data-testid="hr-chart" className="h-72 w-full" />
}
