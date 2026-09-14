# UIX-08 切片开发提示词：第四期打磨 A — 图表层收敛 / 图表无障碍 / 表单 inputMode / 登录页品牌视觉

> 你是本仓库的前端工程师（React 19 + Tailwind CSS 4 + ECharts 6 + Vitest）。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（vitest / lint / build 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须 UTF-8 无 BOM、LF 行尾；代码风格无分号、单引号、2 空格、中文注释；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件；**禁加任何新依赖**。

## 需求（UI/UX 审计 · 第四期：图表层与细节打磨）

1. **图表双轨适配矛盾**：`utils/trends.js` 的 `applyMobile`（删 y 轴 name、rotate 45°、grid 无 containLabel）与 `utils/echartsMobile.js` 的 `mergeMobileOption`（保留 y 轴 name 缩小、rotate 30°、grid containLabel）规则互相矛盾；`HeartRateChart` 完全不做移动端适配（固定 title 14px、grid left:50 bottom:30）
2. **图表无统一色板**：柱状 `#4f46e5`、散点 `#0ea5e9`、心率 `#e11d48`、堆叠图用默认色，三个孤立色值
3. **散点触摸点 12px**：`symbolSize: 12` + `tooltip trigger: 'item'`，移动端几乎点不中
4. **图表无无障碍**：容器裸 div，ECharts `aria.enabled` 未开
5. **数字输入无 inputMode**：`BodyMetricsPage.jsx`（3 处 `w-28` number 输入）、`SkinfoldPanel.jsx`（多处 `type="number"`），部分安卓键盘不弹数字面板
6. **登录页无品牌感**：纯灰底+白卡片（原型 `docs/prototypes/02-login.html` 已审批：渐变 hero + Logo + 底部圆角卡片）

**本切片不碰**：暗色模式（UIX-09）；页面组件迁移（已完成）。

## 已核实的关键事实（实读代码，可直接采信）

- `utils/echartsMobile.js`：`mergeMobileOption(option)` 深合并——`MOBILE_GRID = { top:56, left:8, right:8, bottom:44, containLabel:true }`、title 居中 13px、legend 底部 scroll 10px、xAxis 标签 10px + 类目轴 rotate 30、yAxis nameTextStyle 10px（保留 name）、series label **fontSize 9**（过小，本切片改 10）
- `utils/trends.js`：`applyMobile(option, overrides)`（grid MOBILE_GRID 无 containLabel、xAxis rotate 45 + time 轴 `'{MM}-{dd}'` 或 shortDateLabel formatter、删 y 轴 name、legend scroll 10px）；4 个 builder：`buildWeeklyVolumeOption`（bar `#4f46e5`）、`buildBodyPartOption`（堆叠无指定色）、`buildBodyMetricOption`（双折线无指定色）、`buildSleepVolumeOption`（scatter `#0ea5e9` symbolSize 12 trigger item）
- `components/HeartRateChart.jsx`：固定 option（title 14px、grid left:50/right:20/top:40/bottom:30、xAxis name '时间' category、yAxis name 'bpm'、line `#e11d48` smooth areaStyle 0.1）；容器 `h-72 w-full` testid `hr-chart`；**不接收 mobile prop**
- `components/TrendChart.jsx`：通用挂载器 `{ option, testId }`，容器 `h-72 w-full`
- `hooks/useIsMobile.js`：`(max-width: 767px)` matchMedia hook
- `pages/LoginPage.jsx`（UIX-02 后）：`min-h-dvh` 灰底居中表单卡，含 44px 输入框/按钮、focus ring、深链接回跳逻辑（**逻辑全部保留，只改视觉结构**）；测试 `LoginPage.test.jsx` 断言 `min-h-dvh`/`min-h-[44px]` 等
- `pages/BodyMetricsPage.jsx`：3 处 `type="number"` 输入（`w-28`）
- `components/SkinfoldPanel.jsx`：多处 `type="number"` 输入（`px-2 py-1`）

## 文件预算（共 10 个 + 测试，不得越界）

1. 改 `frontend/src/utils/echartsMobile.js`（统一规则 + 色板导出 + 标签字号 10）
2. 改 `frontend/src/utils/trends.js`（applyMobile 委托统一 helper + 色板 + 散点 16px + aria）
3. 改 `frontend/src/components/HeartRateChart.jsx`（mobile 适配 + 色板 + aria + role）
4. 改 `frontend/src/components/TrendChart.jsx`（容器 role/aria-label）
5. 改 `frontend/src/pages/BodyMetricsPage.jsx`（inputMode）
6. 改 `frontend/src/components/SkinfoldPanel.jsx`（inputMode）
7. 改 `frontend/src/pages/LoginPage.jsx`（品牌视觉重构）
8. 改 `frontend/src/pages/__tests__/LoginPage.test.jsx`（视觉结构适配）
9. 改图表相关测试（`utils/__tests__/` 下 trends/echartsMobile 既有测试按需适配）
10. ✱ `frontend/src/utils/__tests__/chartTheme.test.js`（如色板独立文件则建；否则并入既有测试文件）

## 开发内容

### 1. `utils/echartsMobile.js` — 唯一适配 helper + 色板

- 新增导出：`export const CHART_PALETTE = ['#4f46e5', '#0ea5e9', '#f59e0b', '#e11d48', '#10b981']`（indigo/sky/amber/rose/emerald 定序，注释说明语义：主系列/次系列/对比/心率或警示/正向）
- `mergeSeries` 的 label fontSize **9 → 10**（9px 低于可读下限）
- `mergeMobileOption(option, overrides = {})` 增加第二参：`overrides.grid` 存在时深合并覆盖 MOBILE_GRID 对应键（兼容 trends 双 y 轴图需求）；`overrides.xAxisLabel` 存在时整体替换 xAxis axisLabel（兼容 time 轴 formatter 特化）
- 规则注释更新：本 helper 是全站唯一移动端图表适配入口

### 2. `utils/trends.js` — applyMobile 委托 + 色板 + 散点 + aria

- `applyMobile(option, overrides)` 重构为薄 wrapper：先 `mergeMobileOption(option, { grid: overrides.grid, xAxisLabel: 按 time/category 生成 { rotate:30, fontSize:10, formatter } })`——xAxis formatter 特化逻辑（time→`'{MM}-{dd}'`、category→shortDateLabel）保留在 wrapper 内；**删除自己的 MOBILE_GRID/删 y 轴 name/rotate 45 规则**（统一到 mergeMobileOption：y 轴 name 保留缩小、rotate 30、containLabel）
- 4 个 builder：
  - 顶部 option 统一加 `aria: { enabled: true }`
  - `buildWeeklyVolumeOption`：bar 色 `#4f46e5` → `CHART_PALETTE[0]`（引用，不硬编码）
  - `buildBodyPartOption`：option 加 `color: CHART_PALETTE`（堆叠系列按色板循环，弃默认色）
  - `buildBodyMetricOption`：series 分别 `itemStyle: { color: CHART_PALETTE[0] }` / `CHART_PALETTE[1]`
  - `buildSleepVolumeOption`：`symbolSize: 12 → 16`，`itemStyle.color` → `CHART_PALETTE[1]`
- import CHART_PALETTE from './echartsMobile'

### 3. `components/HeartRateChart.jsx`

- 接 `useIsMobile()`：`const isMobile = useIsMobile()`，option 构造后 `isMobile ? mergeMobileOption(base) : base`
- line color `#e11d48` → `CHART_PALETTE[3]`（同色值，改引用）
- option 加 `aria: { enabled: true }`
- 容器 div 加 `role="img" aria-label="心率曲线图"`（保留 data-testid）

### 4. `components/TrendChart.jsx`

- 容器 div 加 `role="img"`，`aria-label` 由新 prop `ariaLabel` 透传（默认 '趋势图表'）
- TrendsPage 调用处若方便可传具体 label（如"每周容量柱状图"），不方便则用默认——允许顺手改 `TrendsPage.jsx` 调用处传 ariaLabel（预算 +1）

### 5-6. inputMode

- `BodyMetricsPage.jsx` / `SkinfoldPanel.jsx`：所有 `type="number"` 的 `<input>` 追加 `inputMode="decimal"`（属性小写 inputmode 也可，React 用 inputMode）

### 7. `pages/LoginPage.jsx` 品牌视觉（按原型 02-login.html）

- 根结构改为上下两段（保留 `min-h-dvh`）：
  - 上半：`bg-gradient-to-b from-indigo-600 via-indigo-700 to-indigo-900` flex-1 居中——Logo（`h-20 w-20 rounded-3xl bg-white/15` 容器 + 内联哑铃 svg，直接复制 `docs/prototypes/02-login.html` 中的 svg）、h1 `mt-5 text-3xl font-bold tracking-wide text-white`"健身看板"、副标题 `mt-2 text-sm text-indigo-200`"训练数据整合 · AI 教练点评 · 趋势洞察"
  - 下半：`rounded-t-3xl bg-white px-6 pb-[max(2rem,env(safe-area-inset-bottom))] pt-8 shadow-2xl` 内含原表单（label/输入框/错误提示/按钮全部保留，含 min-h-[44px]、focus ring、data-testid、回跳逻辑）；表单上方加 h2 `text-lg font-bold text-gray-900`"登录" + `mt-1 text-sm text-gray-600`"输入访问口令继续"
  - 表单底部加 `mt-6 text-center text-xs text-gray-600`"登录后自动返回你之前打开的页面"
- 深链接回跳逻辑、login() 调用、错误处理一行不动
- `LoginPage.test.jsx` 适配：根容器断言 `min-h-dvh` 保留；新增 Logo svg 存在、品牌标题"健身看板"存在断言

## 关键决策点（默认方案 + 理由）

1. **mergeMobileOption 为唯一 helper，applyMobile 退化为特化 wrapper**：mergeMobileOption 规则更完整（containLabel 防标签裁切、y 轴 name 保留单位信息）；trends 的 time 轴 formatter 是业务特化不属于通用层。
2. **色板 5 色定序数组而非语义命名**：图表系列数量不定（堆叠图部位动态），定序循环是唯一可扩展方式；语义由注释承载。
3. **心率保留 rose（色板第 4 位）**：心率=红色有领域语义，统一到色板引用而非消灭个性。
4. **登录页原型直接落地但不加状态栏模拟**：原型中的 iOS 状态栏是截图装饰，真实 App 不需要。
5. **散点只加 symbolSize 不改 trigger**：axis 触发对散点语义不符；16px（+tooltip 已有格式化）是当前契约下的够用好解。

## 验收标准（审核方执行，你不跑）

1. `git status --short`：仅预算内文件
2. `cd frontend && npx vitest run`：全量通过，无回退
3. `cd frontend && npm run lint`：无新增告警
4. `cd frontend && npm run build`：通过
5. 目检抽查：`grep "symbolSize" trends.js` = 16；`grep "fontSize: 9" echartsMobile.js` = 0；`grep "inputMode" BodyMetricsPage/SkinfoldPanel` ≥ 3；LoginPage 渲染含渐变与 Logo；`grep "applyMobile" trends.js` 内不再有独立 grid/rotate 规则

## 交付报告模板（最终回复必须包含）

1. 完成内容摘要
2. 文件清单（新增/修改，逐个路径）
3. 越界自检
4. 关键决策 5 条逐条确认或说明偏差
5. 测试用例清单（新增/修改用例名）
6. 遗留问题 / 给 UIX-09（暗色模式）的注意事项
7. 编码红线自查（无 BOM / 无分号风格 / 无新依赖 / 未跑验收命令）
8. 对验收标准 1-5 的预期自评

按本提示词直接执行（headless 无人工确认）：先输出实施计划，然后动手，最终回复给出完整交付报告。
