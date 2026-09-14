# UIX-04 切片开发提示词：原语迁移 B — 数据/AI/设置页（AIReports/Trends/BodyMetrics/CoachPreferences/SkinfoldPanel/NextAdvice/SessionReview/Settings）

> 你是本仓库的前端工程师（React 19 + Tailwind CSS 4 + Vitest）。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（vitest / lint / build 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须 UTF-8 无 BOM、LF 行尾；代码风格无分号、单引号、2 空格、中文注释；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件；**禁加任何新依赖**。

## 需求（UI/UX 审计 · 第二期：数据/AI/设置页接入 UI 原语）

UIX-01 交付了 `frontend/src/components/ui/` 原语层（Button/Card/Badge/PillGroup/Skeleton/SkeletonText/ErrorState/EmptyState/ConfirmDialog，直接路径 import，Button 有 `ariaLabel` prop）；UIX-03 已完成核心训练流页面迁移（可打开 `WorkoutListPage.jsx`/`CandidatesPage.jsx` 参考迁移范式）。本切片对剩余 8 个页面/组件做**同模式迁移**。

**本切片不碰**：CoachChatPage/ReportChatSection（UIX-05）、全部导入页（UIX-05）、Layout/BottomTabs/导航（UIX-06）、tokens/成本元信息折叠（UIX-06）、图表与 SimpleMarkdown（UIX-07）、日历图例收敛（UIX-06）。

## 统一迁移规则（对本组所有文件生效）

R1. **按钮全换 Button 原语**：`bg-indigo-600 …` → `variant="primary"`；`bg-green-600`/`bg-emerald-600` → `variant="primary"`（绿色按钮全灭）；`bg-amber-600` → `variant="secondary"`（amber 不再作按钮底色）；`bg-red-600` 实心 → `variant="danger"`（描边）；`bg-gray-200`/描边类 → `variant="secondary"`；纯文字链接式按钮 → `variant="ghost"`。所有 data-testid、disabled、onClick 原样保留。
R2. **三态**：裸文本"加载中…/加载方案中…" → Skeleton 或 SkeletonText（形状贴近原内容）；顶部一行红字错误 → `<ErrorState message={…} onRetry={对应重新加载函数} testId="<页面前缀>-error" />`（无现成加载函数时抽 useCallback）；整页/整块"暂无…"灰字 → `<EmptyState title={…} description={…} />`，有明确下一步时加 action。
R3. **对比度**：`text-gray-400`/`text-gray-500` → `text-gray-600`（纯装饰性图标、placeholder、已禁用元素除外）。
R4. **window.confirm → ConfirmDialog**：本组共 4 处——`NextAdviceSection.jsx:93`（确认执行写回，danger=false 但文案强调"直接修改训记 App"，用 danger）、`NextAdviceSection.jsx:208`（重新生成下次建议）、`SessionReviewSection.jsx:60`（重新生成点评）、`CoachPreferencesPage.jsx:71`（删除须知，danger）。文案沿用原 confirm 文本。
R5. **卡片归一**：`rounded-lg bg-white p-4 shadow` / `rounded-lg bg-white p-4 shadow-sm` → `<Card>`（Card 已是唯一规格）；带彩色语义的卡片（amber-50 提示条等）保留不动。
R6. **focus ring**：`focus:outline-none` 且无 ring 的输入框 → 追加 `focus:ring-2 focus:ring-indigo-100`。
R7. **不引入 emoji**、不加新依赖、不动业务逻辑与 API 调用。

## 文件预算（共 8 页面/组件 + 对应测试，不得越界）

1. 改 `frontend/src/pages/AIReportsPage.jsx`：R1（重新生成 green→primary、上一篇/下一篇→secondary、类型 pill → PillGroup）、R2（加载中/空报告列表）、R3（`text-xs text-gray-400`/`text-gray-500` 多处）。**元信息折叠（模型/tokens/成本）不做，属 UIX-06**。
2. 改 `frontend/src/pages/TrendsPage.jsx`：周期 pill → PillGroup；R2——**修复 loading 期渲染 4 个空坐标轴问题**：loading 时不渲染 `<TrendChart>`，改渲染 4 个 `<Skeleton className="h-72" />`；loadError → ErrorState（重试）。EMPTY_TRENDS 仅在"加载完成且确实无数据"时使用，且此时每张图表卡片显示 EmptyState（title "暂无趋势数据" description "完成一次训练后即可查看趋势"），不渲染空坐标轴。
3. 改 `frontend/src/pages/BodyMetricsPage.jsx`：R1（图片导入 emerald→primary、皮脂钳 amber→secondary、保存记录→primary、"同步到训记"小按钮→ghost 或 secondary、modal 内按钮→primary/secondary）、R2（"暂无记录"→EmptyState）、R3、R5（记录卡片）；徽标（仅本地/已同步 rounded-full）→ Badge 组件。sync-modal 区块 UIX-02 已改，跳过。
4. 改 `frontend/src/pages/CoachPreferencesPage.jsx`：R1（新建须知、编辑/删除按钮）、R4（删除须知）、R2、R3、R5（须知卡片 `rounded-lg bg-white p-4 shadow-sm` → Card）；标签小 badge（source/category 直角）→ Badge 组件。
5. 改 `frontend/src/components/SkinfoldPanel.jsx`：R1（计算/保存→primary，方案选择卡片保留自定义但补 min-h-[44px]）、R2（"加载方案中…"→Skeleton）、R3、R6（所有输入框）。
6. 改 `frontend/src/components/NextAdviceSection.jsx`：R1（写回预览→primary、确认写回 green→primary、重新生成 amber→secondary）、R4（两处 confirm）、R3（含 `text-gray-500` 多处）；amber-50/green-50/red-50 提示条保留。
7. 改 `frontend/src/components/SessionReviewSection.jsx`：R1（重新生成 amber→secondary）、R4（一处 confirm）、R3；section 卡片 `rounded-lg bg-white p-4 shadow` → Card。
8. 改 `frontend/src/pages/SettingsPage.jsx`：R1（保存→primary、"恢复"按钮→secondary 并补 min-h、amber 按钮→secondary）、R2（设置/用量加载中 → Skeleton；"暂无已删除的训练"→EmptyState）、R3、R5、R6；**API Key 输入框补 label**：现为仅 placeholder（行 236-245 附近），加 `<label htmlFor>` 关联（id `api-key-input`，文案"API Key"）。
9. 改对应测试文件（`AIReportsPage/TrendsPage/BodyMetricsPage/CoachPreferencesPage/SettingsPage.test.jsx`、`SkinfoldPanel/NextAdviceSection/SessionReviewSection.test.jsx`）：适配类名/结构变化（PillGroup 无 tab-* testid，断言改 role=tab + aria-selected）；ConfirmDialog 替换后原 window.confirm mock 相关用例改为断言 dialog 出现 + 点确认；每文件至少保留原有用例语义，可为 ErrorState/EmptyState 各加 1 例。

## 关键决策点（默认方案 + 理由）

1. **amber 按钮 → secondary 而非 ghost**："重新生成"是显性操作但非主行动，描边按钮权重恰当；ghost 过弱。
2. **TrendsPage 空数据用 EmptyState 而非空坐标轴**：空坐标轴让用户误以为功能坏了（审计 P1 衍生）；EMPTY_TRENDS option 构造逻辑保留备查但不用于渲染。
3. **ConfirmDialog 的 danger 判定**： destructive（删除须知、覆盖写回）用 danger；重新生成类不用。
4. **彩色语义提示条（amber-50 等）不迁移 Card/Badge**：它们是横幅语义，不是卡片/徽标。
5. **元信息与 emoji 留给 UIX-06**：本切片只做样式与组件归一，避免和 IA 改动搅在一起。

## 验收标准（审核方执行，你不跑）

1. `git status --short`：仅预算内文件
2. `cd frontend && npx vitest run`：全量通过，无回退
3. `cd frontend && npm run lint`：无新增告警（基线仅 SettingsPage `profile` 一处存量——若你顺手消除该未用变量也算修复，但非必须）
4. `cd frontend && npm run build`：通过
5. 目检抽查：本组 8 文件 `grep "bg-green-600\|bg-emerald-600\|bg-amber-600\|bg-red-600"` 按钮底色应全灭（提示条除外）；`grep "window.confirm"` 本组应为 0

## 交付报告模板（最终回复必须包含）

1. 完成内容摘要（按 8 个文件逐个一句话）
2. 文件清单（新增/修改，逐个路径）
3. 越界自检
4. 关键决策 5 条逐条确认或说明偏差
5. 测试用例清单（新增/修改用例名）
6. 遗留问题 / 给 UIX-05（聊天+导入交互修复）的注意事项
7. 编码红线自查（无 BOM / 无分号风格 / 无新依赖 / 未跑验收命令）
8. 对验收标准 1-5 的预期自评

按本提示词直接执行（headless 无人工确认）：先输出实施计划，然后动手，最终回复给出完整交付报告。
