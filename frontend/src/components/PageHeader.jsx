import { useNavigate } from 'react-router-dom'
import Icon from './ui/Icon'

/**
 * UIX-11 渐变品牌页头（方向B）：页标题 + 副标题 + 右侧操作槽。
 * 移动端 sticky 吸顶并承载安全区；桌面端为内容区顶部的圆角横幅。
 * 返回上一级：传 back（渲染 ← 按钮）。
 */
function BackButton() {
  const navigate = useNavigate()
  return (
    <button
      type="button"
      aria-label="返回"
      onClick={() => navigate(-1)}
      className="mr-1 -ml-1.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/15 text-white backdrop-blur transition hover:bg-white/25"
    >
      <Icon name="back" size={18} />
    </button>
  )
}

export default function PageHeader({ title, subtitle, right, back = false, testId }) {
  return (
    <header
      data-testid={testId}
      className="bg-gradient-banner shadow-glow-lg max-md:sticky max-md:top-0 max-md:z-30 max-md:-mx-3 max-md:rounded-b-[28px] md:rounded-[24px] md:shadow-glow"
    >
      <div className="relative z-10 flex items-start justify-between gap-3 px-5 pb-5 pt-[max(1.25rem,env(safe-area-inset-top))] md:items-center md:pb-6 md:pt-6">
        <div className="flex min-w-0 items-center gap-2">
          {back && <BackButton />}
          <div className="min-w-0">
            <h1 className="text-xl font-black tracking-wide text-white">{title}</h1>
            {subtitle && (
              <p className="mt-1 truncate text-xs font-normal text-white/85">{subtitle}</p>
            )}
          </div>
        </div>
        {right && <div className="shrink-0 pt-0.5 md:pt-0">{right}</div>}
      </div>
    </header>
  )
}
