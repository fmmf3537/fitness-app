# UIX-06 切片开发提示词：第三期 IA — 底部 5 Tab / 教练中心 / 我的功能菜单 / 数据导入聚合页 / 桌面导航收敛

> 你是本仓库的前端工程师（React 19 + Tailwind CSS 4 + react-router-dom 7 + Vitest）。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（vitest / lint / build 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须 UTF-8 无 BOM、LF 行尾；代码风格无分号、单引号、2 空格、中文注释；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件；**禁加任何新依赖**。

## 需求（UI/UX 审计 · 第三期：信息架构收敛）

审计结论：底部 7 个 Tab 超移动端上限、"教练须知"低频页占一级 Tab、3 个导入页入口分散、桌面端 13 个导航链接拥挤。已审批的 5 Tab 方案（原型图 `docs/prototypes/03-calendar.html`、`04-coach.html`、`05-import.html`）：

- **底部 Tab 7→5**：日历 / 计划 / 趋势 / 教练 / 我的
- **教练中心**：`/coach` 改为带分段切换（聊天 / 教练须知）的聚合页；`/coach-preferences` 301 到 `/coach?tab=prefs`
- **数据导入聚合页**：新增 `/import`，三张卡片链接到既有三个导入页（路由保留）
- **我的（/settings）**：页首加"功能"菜单区，承载被撤下的入口（AI 报告/复盘中心/待确认队列/身体数据/数据导入）
- **桌面端导航 13→8**：撤下 3 个导入页 + 身体数据 + 教练须知（进"我的"菜单）；移动端汉堡菜单同步收敛

**本切片不碰**：元信息折叠、日历图例收敛、emoji 清理（UIX-07）；暗色/图表（UIX-08）。

## 已核实的关键事实（实读代码，可直接采信）

- `App.jsx`：路由全部挂在 `Layout` 下（`/coach` CoachChatPage、`/coach-preferences` CoachPreferencesPage、三个导入页、`/settings` SettingsPage）；`*` → Navigate to "/"
- `Layout.jsx`：`NAV_LINKS`（13 项，桌面 header）、`SECONDARY_LINKS`（6 项，移动端汉堡）；`pendingCount` 徽标逻辑（`/api/match-candidates` 拉取 pending 数，`renderBadge`）；退出登录按钮在 header 右侧
- `BottomTabs.jsx`：`TABS` 7 项（日历/计划/AI报告/趋势/教练须知/聊天/我的），每项 lucide 风格内联 SVG Icon 组件（CalendarIcon/PlansIcon/SparklesIcon/TrendIcon/BookIcon/ChatIcon/UserIcon 已存在可直接复用）；`useIsMobile` 门控；测试 `BottomTabs.test.jsx` 断言 5 个 tab（训练日历/训练计划/AI报告/趋势/我的）——**新方案改为 日历/计划/趋势/教练/我的，测试需更新**
- `CoachChatPage.jsx`（UIX-05 后）：页首 header 含 h1"跟教练聊聊" + 清空对话按钮；`data-testid="coach-chat-page"`，根元素 `mx-auto flex h-full flex-col max-w-2xl/max-w-3xl`
- `CoachPreferencesPage.jsx`（UIX-04 后）：h1"教练须知"（行 133 附近），内容为须知列表 + AI 草稿区 + 新建按钮
- `SettingsPage.jsx`（UIX-04 后）：h1"设置" + 多个 section（profile/provider/usage/已删除的训练）
- `useIsMobile` hook、`PillGroup` 原语（`{options:[{value,label}], value, onChange, testId}`，role=tablist）可用
- 原型 04-coach 的分段控件样式：`flex rounded-lg bg-gray-100 p-1`，激活项 `bg-white shadow-sm rounded-md`，未激活 `text-gray-600`，均 `min-h-[40px] flex-1 text-sm font-medium`——**与 PillGroup 胶囊样式不同**，本切片按原型实现 segmented（见决策点 1）

## 文件预算（共 11 个：改 8 + 新增 1 + 测试 2 改，不得越界）

1. 改 `frontend/src/App.jsx`（路由调整）
2. 改 `frontend/src/components/BottomTabs.jsx`（7→5 Tab）
3. 改 `frontend/src/components/Layout.jsx`（桌面/汉堡导航收敛）
4. ✱ `frontend/src/pages/CoachHubPage.jsx`（教练中心聚合页）
5. 改 `frontend/src/pages/CoachChatPage.jsx`（去页首 h1 区，迁入 hub）
6. 改 `frontend/src/pages/CoachPreferencesPage.jsx`（去 h1，迁入 hub）
7. ✱ `frontend/src/pages/ImportHubPage.jsx`（数据导入聚合页）
8. 改 `frontend/src/pages/SettingsPage.jsx`（页首加功能菜单区）
9. 改 `frontend/src/components/__tests__/BottomTabs.test.jsx`
10. 改 `frontend/src/components/__tests__/Layout.test.jsx`
11. 改受影响的页面测试（CoachChatPage/CoachPreferencesPage/SettingsPage 的 test.jsx，仅适配 h1 结构变化）

## 开发内容

### 1. `App.jsx` 路由

- `/coach` → `<CoachHubPage />`；`/coach-preferences` → `<Navigate to="/coach?tab=prefs" replace />`
- 新增 `/import` → `<ImportHubPage />`
- CoachChatPage/CoachPreferencesPage 的直接路由移除（仅经 hub 渲染）；其余路由不动

### 2. ✱ `CoachHubPage.jsx`

- 结构：根 `<div data-testid="coach-hub" className="flex h-full flex-col">`
- 页首：`<div className="flex items-center justify-between border-b bg-white px-4 py-3">` 内 h1 `text-xl font-bold text-gray-900`"教练中心"——**清空对话按钮保留在聊天视图内**（见 §5）
- 分段控件（页首下方，`px-4 pt-3`）：读 `useSearchParams` 的 `tab`（`chat` 默认 / `prefs`）；切换用 `setSearchParams`（replace: true 避免历史堆积）；样式按原型：`flex rounded-lg bg-gray-100 p-1`，两个 button `min-h-[40px] flex-1 rounded-md text-sm font-medium`，激活 `bg-white shadow-sm` 未激活 `text-gray-600`，`role="tablist"`/`role="tab"`/`aria-selected`，testid `coach-tab-chat`/`coach-tab-prefs`
- 内容区：`tab === 'prefs' ? <CoachPreferencesPage embedded /> : <CoachChatPage embedded />`
- 初始 tab：`searchParams.get('tab') === 'prefs' ? 'prefs' : 'chat'`

### 3-4. CoachChatPage / CoachPreferencesPage 迁入

- 两组件新增可选 prop `embedded = false`
- `embedded` 时：**不渲染自己的页首 h1 区块**（CoachChatPage 的 `border-b bg-white px-4 py-3` header 整个不渲染，但"清空对话"按钮迁移为聊天视图内右上角小按钮——放在消息区上方一行 flex justify-end，Button danger 不变 testid 不变；CoachPreferencesPage 的 h1 不渲染）
- 非 embedded（防御，路由已撤）行为不变
- CoachChatPage 根元素在 embedded 时保持 `flex h-full flex-col`（hub 提供高度上下文）

### 5. ✱ `ImportHubPage.jsx`

- 页首 h1"数据导入" + 副标题 `text-sm text-gray-600`"三种方式把训练数据同步进看板"
- 三张 `<Card>`（原型 05-import）：每张 = 图标（h-10 w-10 rounded-lg bg-indigo-50 text-indigo-600 内联 svg）+ 标题 + 描述 + 右侧 `<Button variant="secondary">进入</Button>`（整卡可点：用 Link 包 Card 内容或 onClick navigate，testid `import-card-screenshot`/`import-card-fit`/`import-card-backfill`）
  1. 截图识别补录 → `/screenshot-import`："拍训记 App 截图，AI 自动识别动作与重量"
  2. 佳明文件导入 → `/fit-import`："导入 .fit/.tcx/.gpx/.kml 原始运动文件"
  3. 历史数据补录 → `/backfill`："按时间段批量拉取训记 / 佳明历史数据"
- 卡片纵向 space-y-3

### 6. `BottomTabs.jsx` 7→5

- TABS 改为：`[{to:'/',label:'日历',end:true,Icon:CalendarIcon},{to:'/plans',label:'计划',Icon:PlansIcon},{to:'/trends',label:'趋势',Icon:TrendIcon},{to:'/coach',label:'教练',Icon:ChatIcon},{to:'/settings',label:'我的',Icon:UserIcon}]`
- 删除 SparklesIcon/BookIcon（如无其他引用）；label 从"训练日历"改"日历"、"训练计划"改"计划"（5 字以内防拥挤）
- 其余（fixed 定位、安全区、激活色）不动

### 7. `Layout.jsx` 导航收敛

- `NAV_LINKS`（桌面）改为 8 项：训练日历（/）、待确认队列（/candidates，badge）、训练计划（/plans）、复盘中心（/reviews）、AI 报告（/ai-reports）、趋势（/trends）、教练（/coach）、我的（/settings）
- `SECONDARY_LINKS`（汉堡）改为 5 项：待确认队列（badge）、复盘中心、AI 报告、身体数据（/body-metrics）、数据导入（/import）
- 退出登录按钮保留

### 8. `SettingsPage.jsx` 功能菜单区

- h1"设置"改为"我的"（页面即"我的"Tab 落地页）；h1 正下方新增 `<Card className="mb-4">`（testid `feature-menu`）：标题 `text-sm font-semibold text-gray-900`"功能"，下方菜单列表 `divide-y divide-gray-100`，每项 `<Link className="flex min-h-[44px] items-center justify-between text-sm text-gray-700">`：左侧文字 + 右侧 `›`（text-gray-400）：
  AI 报告（/ai-reports）、复盘中心（/reviews）、待确认队列（/candidates）、身体数据（/body-metrics）、数据导入（/import）、教练须知（/coach?tab=prefs）
- 其余 section 不动

### 9-11. 测试适配

- `BottomTabs.test.jsx`：5 Tab 断言改为 日历/计划/趋势/教练/我的 及对应 href（/、/plans、/trends、/coach、/settings）
- `Layout.test.jsx`：桌面导航 8 项断言；汉堡 5 项断言
- CoachChatPage/CoachPreferencesPage 测试：embedded prop 相关渲染；h1 断言适配
- SettingsPage 测试：feature-menu 渲染 + 6 个菜单项 href；h1 文案改"我的"适配

## 关键决策点（默认方案 + 理由）

1. **教练中心分段控件按原型实现 segmented 样式，不复用 PillGroup**：PillGroup 是胶囊切换（激活 indigo 实心），分段控件是 iOS 式灰底白卡——视觉语义不同（一个是过滤切换，一个是视图切换）；后续可在原语层沉淀 SegmentedControl，本切片先在页内实现。
2. **/coach-preferences 用 Navigate 重定向而非双路由渲染**：单一事实路径，NavLink 激活态自然正确；`?tab=prefs` 保留深链能力。
3. **被撤入口进"我的"菜单而非汉堡**：汉堡菜单是导航的导航（反模式），"我的"作为功能 hub 是中文 App 主流模式（微信/Keep）。
4. **页面组件加 embedded prop 而非拆分子组件**：改动最小、测试兼容最好；将来若 hub 稳定可再下沉。
5. **AI 报告/复盘中心不进底部 Tab 但保留一级路由**：它们是周期性阅读场景（周/月），不是高频入口；"我的"菜单承载足够。

## 验收标准（审核方执行，你不跑）

1. `git status --short`：仅预算内文件
2. `cd frontend && npx vitest run`：全量通过，无回退
3. `cd frontend && npm run lint`：无新增告警
4. `cd frontend && npm run build`：通过
5. 目检抽查：BottomTabs TABS 长度 5；`/coach-preferences` 重定向；SettingsPage 含 feature-menu；桌面 NAV_LINKS 长度 8

## 交付报告模板（最终回复必须包含）

1. 完成内容摘要
2. 文件清单（新增/修改，逐个路径）
3. 越界自检
4. 关键决策 5 条逐条确认或说明偏差
5. 测试用例清单（新增/修改用例名）
6. 遗留问题 / 给 UIX-07（元信息折叠/图例收敛/emoji 清理）的注意事项
7. 编码红线自查（无 BOM / 无分号风格 / 无新依赖 / 未跑验收命令）
8. 对验收标准 1-5 的预期自评

按本提示词直接执行（headless 无人工确认）：先输出实施计划，然后动手，最终回复给出完整交付报告。
