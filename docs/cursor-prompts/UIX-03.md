# UIX-03 切片开发提示词：原语迁移 A — 核心训练流页面（WorkoutList/WorkoutDetail/Candidates/Plans/Reviews/SyncButton/Calendar 按钮）

> 你是本仓库的前端工程师（React 19 + Tailwind CSS 4 + Vitest）。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（vitest / lint / build 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须 UTF-8 无 BOM、LF 行尾；代码风格无分号、单引号、2 空格、中文注释；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件；**禁加任何新依赖**。

## 需求（UI/UX 审计 · 第二期：页面接入 UI 原语）

UIX-01 已交付 `frontend/src/components/ui/` 原语层（直接路径 import，无 barrel）：
- `Button`：`{ variant: 'primary'|'secondary'|'danger'|'dangerSolid'|'ghost', fullWidth, type, disabled, onClick, children, testId, className }`，基础含 `min-h-[44px]`
- `Card`：`{ children, className, testId }`，`rounded-xl border border-gray-200 bg-white p-4 shadow-sm`
- `Badge`：`{ variant: 'indigo'|'green'|'amber'|'gray'|'red', children, testId }`
- `PillGroup`：`{ options: [{value,label}], value, onChange, testId }`（role=tablist/tab，含 min-h-[44px]）
- `Skeleton` 默认导出 `{ className, testId }` + 具名 `SkeletonText({ lines, testId })`
- `ErrorState`：`{ message, onRetry, testId }`（role=alert，带"重试"按钮）
- `EmptyState`：`{ icon, title, description, action, testId }`
- `ConfirmDialog`：`{ open, title, description, confirmText, cancelText, danger, onConfirm, onCancel }`

本切片把 7 个核心训练流页面/组件迁移到这些原语，并顺手修复审计发现的本组问题：
- **强调色混乱**：所有"AI 点评/立即生成"绿色按钮（green-600）→ Button primary（indigo）
- **触控热区**：所有按钮经 Button 获得 min-h-[44px]（原 py-1/py-1.5 仅 28-36px）
- **加载/错误/空三态**：裸文本"加载中…"→ Skeleton；一行红字无重试 → ErrorState；灰字"暂无"→ EmptyState（带 CTA）
- **对比度**：辅助文字 `text-gray-400`/`text-gray-500` → `text-gray-600`（仅本组文件）
- **window.confirm**：WorkoutDetailPage 删除确认 → ConfirmDialog
- **WorkoutListPage 无 date 参数兜底**：渲染"{date} 训练列表"空标题（P2）

**本切片不碰**：元信息折叠（UIX-06）、toast 系统替换（UIX-05）、底部 Tab/导航（UIX-06）、Layout.jsx、图表（UIX-07）、CoachChatPage/ReportChatSection（UIX-05）、AIReportsPage/TrendsPage/BodyMetricsPage/CoachPreferencesPage/SettingsPage/各导入页（UIX-04）。

## 已核实的关键事实（实读代码，可直接采信）

- `WorkoutListPage.jsx`（59 行全量已读）：行 8 `date` 可能为空串；行 37 裸红字错误；行 39 裸"加载中…"；行 41 "当日没有训练记录"；行 48 列表项 `rounded-md border border-gray-200 bg-white px-4 py-3 shadow-sm hover:border-indigo-400`；行 51 `text-gray-500` 状态文字；**无对应测试文件**
- `WorkoutDetailPage.jsx`（216 行全量已读）：行 25/46/190 卡片 `rounded-lg bg-white p-4 shadow`；行 132 `window.confirm` 删除确认；行 147-148 加载/错误早退裸文本；行 167-183 下划线 Tab（`px-4 py-2`，无 min-h）；行 205-212 删除按钮 `border-red-300 px-3 py-1.5`（testid `delete-workout`）；行 26/36/51/159 等 `text-gray-500`；测试文件 `__tests__/WorkoutDetailPage.test.jsx` 已存在
- `CandidatesPage.jsx`（119 行全量已读）：行 39 卡片 `rounded-lg bg-white p-4 shadow`（testid `candidate-{id}`）；行 46 `⇄` 箭头在移动端竖排（flex-col）时方向语义错误；行 67 合并按钮 `bg-indigo-600 px-4 py-1.5`、行 75 保持分开 `bg-gray-200 px-4 py-1.5`；行 8/56 `text-gray-500`；测试已存在
- `PlansPage.jsx`（267 行全量已读）：行 198 刷新按钮 `bg-indigo-600 px-3 py-1.5 shadow hover:bg-indigo-500`（testid `refresh-button`）；行 218 休息日 `bg-gray-100 text-gray-400`（对比度 2.8:1 不达标，testid `rest-day-{date}`）；行 236 AI 点评按钮 `bg-green-600 px-3 py-1.5 text-xs`（testid `review-button-{date}`）；行 207 裸"加载中…"、行 209 空态；行 229/249 `text-gray-500`；测试已存在
- `ReviewsPage.jsx`（250 行全量已读）：行 126-129 `pillClass`（`px-3 py-2`）；行 180 立即生成 `bg-green-600`（testid `generate-button`）；行 30/37 导出按钮 `px-3 py-1`（testid `export-md`/`export-pdf`）；行 140/152 上一篇/下一篇 `px-3 py-1.5`（testid `sheet-prev`/`sheet-next`）；行 144 `text-gray-400` 页码；行 192 裸"加载中…"、行 200 空态、行 187-191 本地 toast 文本（保留不动，UIX-05 处理）；行 219-221 报告卡 tokens 元信息（保留不动，UIX-06 折叠）；测试已存在
- `SyncButton.jsx`（89 行全量已读）：行 76 按钮 `bg-indigo-600 px-3 py-1.5 shadow hover:bg-indigo-500`（aria-label 立即同步）；行 81 `text-gray-500`；测试已存在
- `CalendarPage.jsx`：UIX-02 刚改过错误态/加载态（ErrorState/Skeleton 已接入），本切片**只迁移翻月按钮**：`← 上个月`/`下个月 →` 两个按钮 `rounded-md bg-white px-3 py-1.5 shadow hover:bg-gray-100`（aria-label 上个月/下个月）；测试已存在
- 现有测试约定：mock `../api/client` 的 `api`；用 `data-testid` 断言

## 文件预算（共 14 个：改 12 + 新增 1 + 测试适配，不得越界）

页面/组件（改 7）：
1. 改 `frontend/src/pages/WorkoutListPage.jsx`
2. 改 `frontend/src/pages/WorkoutDetailPage.jsx`
3. 改 `frontend/src/pages/CandidatesPage.jsx`
4. 改 `frontend/src/pages/PlansPage.jsx`
5. 改 `frontend/src/pages/ReviewsPage.jsx`
6. 改 `frontend/src/components/SyncButton.jsx`
7. 改 `frontend/src/pages/CalendarPage.jsx`（仅两个翻月按钮）

测试（改 5 + 新增 1）：
8. 改 `frontend/src/pages/__tests__/WorkoutDetailPage.test.jsx`
9. 改 `frontend/src/pages/__tests__/CandidatesPage.test.jsx`
10. 改 `frontend/src/pages/__tests__/PlansPage.test.jsx`
11. 改 `frontend/src/pages/__tests__/ReviewsPage.test.jsx`
12. 改 `frontend/src/components/__tests__/SyncButton.test.jsx`
13. 改 `frontend/src/pages/__tests__/CalendarPage.test.jsx`（若翻月按钮类名断言受影响）
14. ✱ `frontend/src/pages/__tests__/WorkoutListPage.test.jsx`

## 开发内容（逐文件）

### 1. `WorkoutListPage.jsx`

- import：Button 不需要；import Skeleton、ErrorState、EmptyState、Badge
- **date 兜底**：`date` 为空时不发请求（现有逻辑已有），渲染 `<EmptyState testId="no-date" title="未指定日期" description="请从训练日历选择一天查看" action={<Link to="/">…返回日历…</Link>} />`（action 用 Link 包 Button ghost 或直接文字链接样式 `text-indigo-600 min-h-[44px] inline-flex items-center`）
- error：`<ErrorState message={\`加载失败：${error}\`} onRetry={重新加载} testId="list-error" />`（需把加载逻辑抽成 useCallback 以便重试）
- loading：3 个 `<Skeleton className="h-12" />` 的 space-y-2 列表骨架
- 空结果：`<EmptyState title="当日没有训练记录" description="换个日期看看，或回到日历同步数据" />`
- 列表项类名统一为 Card 规格变体：`flex items-center justify-between rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm hover:border-indigo-400`（rounded-md→rounded-xl）
- 状态文字 `text-gray-500` → Badge：match_status 映射（`auto_matched→green`、`manual_matched→indigo`、`pending→amber`、其他→gray；映射失败兜底 gray），仍显示 statusLabel 文案
- `statusLabel` 前的 `<span className="text-sm text-gray-500">` 删除

### 2. `WorkoutDetailPage.jsx`

- import：Card、Button、ErrorState、SkeletonText、ConfirmDialog、Badge
- SummaryCard/MovementsTable/心率卡片（行 25/46/190）：`rounded-lg bg-white p-4 shadow` → `<Card>`（MovementsTable 的 map 内用 `<Card key={...}>`）
- 行 36/101/194 "无动作数据/无原始数据/无心率数据"：`text-gray-500` → `text-gray-600`（保持简单文本即可，不用 EmptyState——区块内联空态）
- loading 早退（行 147）：改为 `<div className="space-y-3"><SkeletonText lines={4} testId="detail-skeleton" /></div>` 外包装
- error 早退（行 148）：`<ErrorState message={error} onRetry={重新加载} testId="detail-error" />`（加载逻辑抽 useCallback）
- 下划线 Tab（行 167-183）：`px-4 py-2` → `px-4 min-h-[44px]`（保留 border-b-2 视觉样式不动，仅补热区）
- 删除按钮（行 205-212）：→ `<Button variant="danger" testId="delete-workout" disabled={deleting} onClick={openConfirm}>`（testId 不变）
- `window.confirm`（行 132-136）→ ConfirmDialog：新增 `const [confirmOpen, setConfirmOpen] = useState(false)`；点删除打开；`onConfirm` 执行原删除逻辑并关闭；`danger`；title "确定删除这次训练吗？"；description "关联的 AI 点评与下次建议会一并删除，原始数据保留，之后可在「设置 → 已删除的训练」中恢复。"
- 标题行 match_status（行 159-161）：`text-gray-500` → Badge（同 WorkoutListPage 的映射）+ `text-gray-600` 日期文字

### 3. `CandidatesPage.jsx`

- import：Card、Button、Skeleton、ErrorState、EmptyState
- 卡片（行 39）：→ `<Card testId={\`candidate-${candidate.id}\`}>`（testId 保留）
- 合并按钮 → `<Button variant="primary" onClick={...} disabled={resolving}>`；保持分开 → `<Button variant="secondary">`
- `⇄` 箭头（行 46）：加 `sm:rotate-0 rotate-90`（移动端竖排时箭头变上下方向）+ `text-gray-400` → `text-gray-500`（纯装饰图标允许 gray-500）
- 行 8/56 `text-gray-500` → `text-gray-600`
- loading：2 个 `<Skeleton className="h-28" />` 骨架
- error：`<ErrorState message={\`加载失败：${error}\`} onRetry={重试} testId="candidates-error" />`（抽 useCallback）
- 空：`<EmptyState title="没有待确认的候选" description="训记与佳明记录已全部匹配完成" />`

### 4. `PlansPage.jsx`

- import：Button、Skeleton、ErrorState、EmptyState
- 刷新按钮（行 198）→ `<Button variant="primary" testId="refresh-button" disabled={refreshing}>`（去掉 shadow hover:bg-indigo-500，统一 primary 样式）
- AI 点评按钮（行 236）→ `<Button variant="primary" testId={\`review-button-${day.date}\`} disabled={...} className="shrink-0">`（green-600 → indigo，text-xs → 统一 text-sm）
- 休息日（行 218）：`bg-gray-100 text-gray-400` → `bg-gray-50 text-gray-600`（对比度达标）
- loadError（行 206）→ `<ErrorState message={loadError} onRetry={loadPlans} testId="plans-error" />`
- 加载中（行 207）→ 3 个 `<Skeleton className="h-24" />`
- 空（行 208-210）→ `<EmptyState title="暂无计划数据" description="点击下方按钮拉取训记官方计划" action={<Button variant="primary" onClick={handleRefresh} disabled={refreshing}>刷新计划</Button>} />`
- 行 229/249 `text-gray-500` → `text-gray-600`
- refreshMsg/genErrors 的 role=status/role=alert 保留不动

### 5. `ReviewsPage.jsx`

- import：Button、PillGroup、Skeleton、ErrorState、EmptyState
- TABS pill（行 126-129 + 164-175）→ `<PillGroup options={TABS.map(t => ({ value: t.key, label: t.label }))} value={tab} onChange={setTab} testId="review-tabs" />`（删除 pillClass；保留各 tab 的 data-testid 需求——PillGroup 不生成 `tab-weekly` testid，测试断言改为检查 role=tab + aria-selected，见 §11）
- 立即生成（行 180）→ `<Button variant="primary" testId="generate-button" disabled={generating}>`（green → indigo）
- 导出按钮（行 30/37）→ `<Button variant="secondary" testId="export-md"/"export-pdf" onClick={...}>`（testId 保留）
- 上一篇/下一篇（行 140/152）→ `<Button variant="secondary" testId="sheet-prev"/"sheet-next" disabled={...}>`（testId 保留）
- 页码（行 144）`text-gray-400` → `text-gray-600`
- loading（行 192）→ 2 个 `<Skeleton className="h-20" />`
- error（行 193-197）→ `<ErrorState message={error} onRetry={() => load(tab)} testId="reviews-error" />`
- 空（行 199-201）→ `<EmptyState title="暂无复盘报告" description="点击「立即生成」创建本周期复盘" action={<Button variant="primary" onClick={handleGenerate} disabled={generating}>立即生成</Button>} />`
- 本地 toast 文本（行 187-191）、tokens 元信息（行 219-221）、报告卡样式（行 210-214）：**不动**

### 6. `SyncButton.jsx`

- 按钮（行 76）→ `<Button variant="primary" aria-label="立即同步" onClick={start} disabled={syncing}>`（Button 需透传 aria-label——查 UIX-01 的 Button 实现：props 列表无 ariaLabel。处理：Button 已支持 `className`，不支持 aria-label。**给 Button.jsx 加 `ariaLabel` prop 是本切片允许的例外**——改 `frontend/src/components/ui/Button.jsx`：新增 prop `ariaLabel`，渲染时 `aria-label={ariaLabel}`。文件预算随之 +1）
- 行 81 `text-gray-500` → `text-gray-600`

### 7. `CalendarPage.jsx`（仅翻月按钮）

- `← 上个月`/`下个月 →` 两按钮 → `<Button variant="secondary" ariaLabel="上个月"/"下个月" onClick={...}>`（文案保持 `← 上个月`/`下个月 →`；移动端 order 类 `max-md:order-1` 通过 className 保留）
- 其余（UIX-02 已改的 ErrorState/Skeleton/网格/图例）不动

### 8. `ui/Button.jsx`（+1 例外文件）

新增 `ariaLabel` prop（透传 `aria-label`），更新 `__tests__/ui-primitives.test.jsx` 加 1 个断言用例（文件预算 +1，共 15 个）

## 关键决策点（默认方案 + 理由）

1. **状态文字用 Badge 而非纯文字**：Badge 是统一的状态标签载体；颜色映射复用日历图例语义（green=已匹配/indigo=手动/amber=待确认），与 UIX-06 的 3 色收敛对齐。
2. **下划线 Tab（WorkoutDetailPage）不迁移 PillGroup**：下划线是另一种合理的 tab 视觉（PillGroup 是胶囊式），只补 44px 热区；避免全站视觉同质化。
3. **green 按钮全灭**：包括"AI 点评/立即生成"这类"创造"语义按钮——审计结论是没有第二种主色，创造语义由文案承担。
4. **EmptyState 仅在整页/整块为空时用**：区块内联空态（无心率数据）保持简单文本（gray-600），避免空态嵌套噪音。
5. **Button 加 ariaLabel 是原语层最小演进**：比类名 hack 或包 span 干净；后续切片都受益。

## 验收标准（审核方执行，你不跑）

1. `git status --short`：仅预算内文件（15 个）
2. `cd frontend && npx vitest run`：全量通过，无回退
3. `cd frontend && npm run lint`：无新增告警
4. `cd frontend && npm run build`：通过
5. 目检抽查：全组文件 `grep -n "green-600"` 应为 0 处按钮底色；`grep -n "text-gray-400\|text-gray-500"` 在本组 7 个页面文件应仅剩装饰性残留（需逐条说明）

## 交付报告模板（最终回复必须包含）

1. 完成内容摘要
2. 文件清单（新增/修改，逐个路径）
3. 越界自检
4. 关键决策 5 条逐条确认或说明偏差
5. 测试用例清单（新增/修改用例名 + 适配说明）
6. 遗留问题 / 给 UIX-04（数据/AI/导入/设置页迁移）的注意事项
7. 编码红线自查（无 BOM / 无分号风格 / 无新依赖 / 未跑验收命令）
8. 对验收标准 1-5 的预期自评

按本提示词直接执行（headless 无人工确认）：先输出实施计划，然后动手，最终回复给出完整交付报告。
