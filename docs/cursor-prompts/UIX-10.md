# UIX-10 切片开发提示词：复盘详情原型落地 — 06-report（评分卡头 / 正文分卡 / 追问 CTA / 周海报）

> 你是本仓库的前端工程师（React 19 + Tailwind CSS 4 + react-router-dom 7 + Vitest）。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（vitest / lint / build 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须 UTF-8 无 BOM、LF 行尾；代码风格无分号、单引号、2 空格、中文注释；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件；**禁加任何新依赖**；**禁改任何后端文件**。

## 需求（原型 `docs/prototypes/06-report.html` / `06-report.png` 落地到复盘中心）

背景：UIX-01~09 已落地 02-login/03-calendar/04-coach/05-import 四张原型，06-report 是唯一未排期的原型。现状 `/reviews` 复盘详情（`ReviewsPage.jsx` 的 `ReviewDetail`）是"元信息 + 整段 Markdown 直出"，与原型差距：无评分卡头、正文不分卡、追问入口非 CTA 样式、无周复盘海报入口。本切片把详情区按原型重构（**只动详情渲染区，不动列表/生成/Tab 逻辑**）：

- **评分卡头**：ScoreBadge 带等级文字（原型"82 分 · 良好"样式）+ 周期 `M/D – M/D` 紧凑格式 + 已有「技术详情」折叠保留在本卡内
- **正文分卡**：按 Markdown h2（`## `）切分为独立卡片（原型：本周概览一卡、下周建议一卡）；不足 2 个 h2 时回退单卡
- **追问 CTA**：复用 ReportChatSection，折叠入口按钮按原型样式（线性对话图标 + 文案"就这份复盘追问教练"）
- **分享本周海报**：复用 SharePosterButton，周复盘无单次训练时标题兜底为"周复盘 M/D–M/D"
- **导出入口保留**：导出 Markdown / PDF 按钮不收起、不删除，移至评分卡头右侧

**本切片不碰**：复盘列表卡片、生成按钮与轮询、Tab 切换、AI 报告页（/ai-reports）的列表与筛选、移动端底部 Tab / 桌面导航、后端任何接口。

## 已核实的关键事实（实读代码，可直接采信）

- `frontend/src/pages/ReviewsPage.jsx`：`ReviewDetail`（行 26-66）为桌面分栏与移动端 BottomSheet **共用**的详情组件——改它一处两端同时生效；`report` 字段：`date`（周期开始）、`period_end`、`score`、`model`、`prompt_tokens`、`completion_tokens`、`cost_estimate`、`content_md`、`type`（weekly/monthly）
- `ScoreBadge.jsx`：仅渲染 `{score} 分`，色阶 ≥90 绿 / 75-89 indigo / 60-74 黄 / <60 红；`score == null` 不渲染
- `ReviewContent.jsx`：已把 `content_md` 按 ```` ```echarts ```` 围栏切块，md 部分走 `SimpleMarkdown`——**h2 分卡必须在此切块之前做**，否则 echarts 块会被切断（见开发内容 §3）
- `ReportChatSection.jsx`：接受任意 `reportId`，后端 `GET/POST /api/ai-reports/{report_id}/messages`（`backend/app/api/ai_reports.py:400/413`）对类型无限制，**周/月复盘可直接复用**；折叠入口按钮 testid `chat-expand-btn`，当前文案"追问 AI 教练"（AIReportsPage 也在用此组件——样式统一改动对两页同时生效，属预期）
- `SharePosterButton.jsx`：props 仅 `report`；后端 `build_poster_data`（`backend/app/services/poster.py:208-210`）对 `workout_id` 为空的周复盘返回 `workout: null, prs: [], week_count: null`；前端 `buildPosterData`（`frontend/src/utils/poster.js:105-122`）对 null workout 有兜底（标题回退 `'训练记录'`、指标行整格跳过）——**前后端均无崩溃风险，仅需补标题兜底文案**
- 周/月复盘**无重新生成接口**：`POST /api/ai-reports/generate` 幂等（已存在返回 `{"status":"exists"}`，`ai_reports.py:235-247`），regenerate 仅支持 session_review——原型中的「重新生成」按钮本切片**不实现**，登记交付报告遗留
- UIX-09 已全站暗色映射：所有新增/改动的亮色类**必须成对追加 dark: 变体**（映射表见 UIX-09 §A/B）
- 测试惯例：页面测试在 `frontend/src/pages/__tests__/ReviewsPage.test.jsx`，组件测试在 `frontend/src/components/__tests__/`；jsdom 无 canvas/echarts 真渲染，现有测试用 mock 处理

## 文件预算（共 7 个：改 5 + 新增 2，不得越界）

1. 改 `frontend/src/pages/ReviewsPage.jsx`（ReviewDetail 按原型重构；页面其余部分不动）
2. 改 `frontend/src/components/ScoreBadge.jsx`（新增可选 `verdict` prop）
3. ✱ `frontend/src/components/ReviewSections.jsx`（h2 分卡容器）
4. 改 `frontend/src/components/ReportChatSection.jsx`（折叠入口按钮样式 + 文案）
5. 改 `frontend/src/components/SharePosterButton.jsx`（新增可选 `fallbackTitle` prop，透传 buildPosterData）
6. 改 `frontend/src/pages/__tests__/ReviewsPage.test.jsx`（适配详情结构）
7. ✱ `frontend/src/components/__tests__/ReviewSections.test.jsx`

## 开发内容

### 1. `ScoreBadge.jsx`：可选等级文字

- 新增可选 prop `verdict`（boolean，默认 `false`）：`true` 时 badge 文案为 `{score} 分 · {等级}`
- 等级映射（与色阶同阈值）：≥90 `优秀` / 75-89 `良好` / 60-74 `一般` / <60 `待加强`
- 默认 `false` 时渲染与现状**逐字节一致**（AIReportsPage 等既有调用零影响）

### 2. ✱ `ReviewSections.jsx`：h2 分卡容器

- props：`{ text, testId }`；内部按 `/^##\s+/m` 把 `content_md` 切成若干 section（每个 section 含自身 h2 起的全文）
- **切分发生在 ReviewContent 的 echarts 切块之前**：先按 h2 切，再把每个 section 文本交给既有 `<ReviewContent text={...} />` 渲染（echarts 围栏块若出现在某 section 内自然归属该卡）
- section ≥ 2：每 section 一张卡 `<section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5 shadow-sm">`，卡间距 `space-y-3`
- section < 2（LLM 未按模板输出）：回退为单卡包裹 `<ReviewContent text={全文} />`，**不得抛错、不得丢内容**
- 根元素 `data-testid={testId || 'review-sections'}`，每卡 `data-testid="review-section-card"`

### 3. `ReviewsPage.jsx`：ReviewDetail 重构

新结构（自上而下）：

```
┌ 评分卡头（rounded-xl border bg-white p-4 shadow-sm，深色按映射表）
│   左：ScoreBadge verdict={true} + 周期文本「9/8 – 9/14」
│   右：导出 Markdown / 导出 PDF（Button variant="secondary" 原样迁入）
│   下：技术详情 <details>（原 testid review-tech-details 保留，原样迁入）
├ ReviewSections（正文分卡）
├ ReportChatSection reportId={report.id}（追问 CTA，样式见 §4）
└ SharePosterButton report={report} fallbackTitle="周/月复盘标题"（见 §5）
```

- 周期格式：`M/D – M/D`（去前导零，如 `9/8 – 9/14`；`period_end` 缺失时只显示 `M/D`）；本地解析函数放 ReviewsPage 内，注释说明格式来源
- 原元信息行（"周期：…"整段）由评分卡头取代，**旧 testid `report-detail` 保留**在详情根元素
- 移动端 BottomSheet 的 `title` 与 footer 翻页逻辑**不动**
- 「重新生成」按钮**不加**（无后端接口），交付报告登记

### 4. `ReportChatSection.jsx`：折叠入口按原型

- 文案："追问 AI 教练" → **"就这份复盘追问教练"**（两处页面统一生效，预期内）
- 按钮样式改原型：`flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl border border-indigo-200 dark:border-indigo-800 bg-indigo-50/50 dark:bg-indigo-950/50 text-sm font-medium text-indigo-700 dark:text-indigo-300 active:bg-indigo-100`（去 dashed）
- 保留既有 `chat-expand-btn` testid 与全部展开逻辑；仅改折叠态外观与文案

### 5. `SharePosterButton.jsx`：标题兜底

- 新增可选 prop `fallbackTitle`（string）：透传到海报数据装配——`buildPosterData` 调用后若标题为兜底值 `'训练记录'` 且传了 fallbackTitle，则覆盖标题
- 复盘详情传：`周复盘 9/8–9/14` / `月复盘 9月` 形式（复用 §3 的周期格式函数，可从 ReviewsPage 导入或内联——二选一，注释说明）
- 按钮文案按调用方：复盘详情内显示"分享本周海报"（weekly）/"分享本月海报"（monthly）——新增可选 prop `label`，默认保持现文案不变

### 6-7. 测试

- `ReviewsPage.test.jsx`：适配——详情含评分卡头（badge 含等级文字）、周期 `M/D – M/D` 格式断言、追问 CTA 文案断言、海报按钮存在；保留导出按钮断言
- ✱ `ReviewSections.test.jsx`：≥2 个 h2 时渲染多卡（断言卡数与 h2 文本）；无 h2 回退单卡且全文不丢；含 echarts 围栏的 section 归卡正确（可断言围栏文本出现在对应卡内）
- ScoreBadge：`verdict` 开/关两态断言
- 既有全量测试不得回退（重点：AIReportsPage 测试若断言"追问 AI 教练"文案需同步改为新文案——允许为此改 `AIReportsPage.test.jsx`，**这是预算外唯一豁免**，交付报告必须声明）

## 关键决策点（默认方案 + 理由）

1. **h2 分卡先于 echarts 切块**：保证图表不被切散；回退单卡兜住 LLM 自由格式输出。
2. **追问/海报组件全站共用、直接改样式而非加 prop 分叉**：原型风格即全站目标风格，AIReportsPage 同步受益，避免两套样式长期漂移。（fallbackTitle/label 这类数据差异才用 prop。）
3. **周复盘「重新生成」不实现**：后端 generate 幂等且无 regenerate 接口；前端造假入口会破坏信任，登记遗留待后端切片。
4. **导出按钮迁入评分卡头而非原型"..."菜单**： BottomSheet/桌面双端复用同一详情组件，做溢出菜单成本高收益低；保持可见入口不丢功能。
5. **等级文字阈值复用 ScoreBadge 色阶**：评分语义单一来源，避免两套阈值打架。

## 验收标准（审核方执行，你不跑）

1. `git status --short`：仅预算内 7 个文件 + 可能的 AIReportsPage.test.jsx 文案豁免
2. `cd frontend && npx vitest run`：全量通过，无回退
3. `cd frontend && npm run lint`：无新增告警
4. `cd frontend && npm run build`：通过
5. 审核方人工核对：移动端打开 `/reviews` 周复盘详情对照 `06-report.png`——评分卡头（badge+等级+周期+技术详情折叠）、正文按 h2 分卡、追问 CTA 样式与文案、海报按钮；系统深色模式下无未映射的亮色残留
6. `grep -c "dark:" frontend/src/components/ReviewSections.jsx` ≥ 2（新增卡片类必须带暗色变体）

## 交付报告模板（最终回复必须包含）

1. 完成内容摘要
2. 文件清单（新增/修改，含 AIReportsPage.test.jsx 是否动用豁免及原因）
3. 越界自检
4. 关键决策 5 条逐条确认或说明偏差
5. 测试用例清单
6. 遗留问题（必须含：周/月复盘无重新生成接口未做原型入口；海报对无 workout 报告的标题兜底为文案级、非定制模板）
7. 编码红线自查（无 BOM / 无分号风格 / 无新依赖 / 未跑验收命令 / 未改后端）
8. 对验收标准 1-6 的预期自评

按本提示词直接执行（headless 无人工确认）：先输出实施计划，然后动手，最终回复给出完整交付报告。
