# UIX-07 切片开发提示词：呈现层收敛 — 元信息折叠 / 日历图例 3 色 / emoji 清理 / SimpleMarkdown 标题层级

> 你是本仓库的前端工程师（React 19 + Tailwind CSS 4 + Vitest）。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（vitest / lint / build 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须 UTF-8 无 BOM、LF 行尾；代码风格无分号、单引号、2 空格、中文注释；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件；**禁加任何新依赖**。

## 需求（UI/UX 审计 · 第三期收尾：信息降噪与视觉收敛）

1. **AI 报告暴露过多工程元信息**：每条报告/消息都显示模型名、tokens、`¥0.000123` 级成本，核心内容被噪音稀释（`AIReportsPage.jsx:59-63`、`AIReportsPage.jsx` 列表卡、`ReviewsPage.jsx` 报告卡、`CoachChatPage.jsx metaLine`）
2. **日历 5 色圆点认知负担重且色盲不友好**：`utils/status.js` STATUS_COLORS 绿/蓝/黄/紫/橙 5 色 → 收敛为 3 色语义
3. **emoji 风格冲突**：`SkinfoldPanel.jsx` SELF_TEST_LABEL 用 ✅⚠️❌，与全站纯文字+图标风格不符
4. **SimpleMarkdown 标题层级错误**：`#`/`##` 都渲染成 `<h3>`，`###`/`####` 与正文同为 text-sm，层级扁平且屏幕阅读器大纲混乱

**本切片不碰**：暗色模式、图表层、表单 inputMode、登录页视觉（UIX-08）。

## 已核实的关键事实（实读代码，可直接采信）

- `utils/status.js`：`STATUS_COLORS`（5 色 bg-* 圆点类）与 `STATUS_LABELS`（5 项中文标签）独立；`statusColor()` 用于 CalendarPage 圆点（testid `dot-{date}-{status}`）；`statusLabel()` 用于 WorkoutListPage/Detail 的 Badge 文案
- `CalendarPage.jsx` 图例区（尾部）：5 个 `<span className="h-2 w-2 rounded-full bg-{color}" />+文字` 项
- `AIReportsPage.jsx`：详情卡行 59-63 `模型：`/`tokens：`/`¥{cost.toFixed(6)}`；`memory_refs` 提示（行 64-74，testid `memory-refs`）保留；列表卡在文件后半部（日期 + `model · prompt+completion tokens` 两行元信息）；UIX-04 已把按钮迁为 Button 原语
- `ReviewsPage.jsx`：报告卡 `mt-1 text-xs text-gray-600` 行 `{r.model} · {r.prompt_tokens}+{r.completion_tokens} tokens`；ScoreBadge 组件存在（`ScoreBadge score testId`）
- `CoachChatPage.jsx`（UIX-05 后）：`metaLine(m, isUser)` 返回 时间 + tokens/成本拼接
- `SkinfoldPanel.jsx`：文件顶部 `SELF_TEST_LABEL`（行 5-9 附近）含 ✅⚠️❌；自测结果展示处有对应渲染
- `SimpleMarkdown.jsx`：行 141-167 标题渲染——`#`（h1）与 `##`（h2）都渲为 `<h3 className="text-lg font-bold text-gray-900">`，`###` 也 h3，`####` 为 h4 且与 ### 同为 `text-sm`；测试 `SimpleMarkdown.test.jsx` 已存在

## 文件预算（共 9 个 + 测试，不得越界）

1. 改 `frontend/src/pages/AIReportsPage.jsx`（详情卡 + 列表卡元信息折叠）
2. 改 `frontend/src/pages/ReviewsPage.jsx`（报告卡去 tokens）
3. 改 `frontend/src/pages/CoachChatPage.jsx`（metaLine 简化）
4. 改 `frontend/src/utils/status.js`（3 色映射）
5. 改 `frontend/src/pages/CalendarPage.jsx`（图例 3 项）
6. 改 `frontend/src/components/SkinfoldPanel.jsx`（emoji → Badge）
7. 改 `frontend/src/components/SimpleMarkdown.jsx`（标题层级修复）
8. 改 `frontend/src/components/__tests__/SimpleMarkdown.test.jsx`
9. 改受影响测试（AIReportsPage/ReviewsPage/CoachChatPage/CalendarPage/SkinfoldPanel 的 test.jsx 按需适配）

## 开发内容

### 1. `AIReportsPage.jsx` 元信息折叠

- 详情卡：`模型：`与`tokens：`两行 → 单个 `<details data-testid="tech-details" className="mt-1">`：`<summary className="min-h-[36px] cursor-pointer text-xs text-gray-600">技术详情（模型 / tokens / 成本）</summary>`，内容 `<p className="mt-1 rounded-lg bg-gray-50 p-2 text-xs text-gray-600">模型：{model} · tokens：{p}/{c} · 成本：{fmtCost(cost_estimate)}</p>`
- 新增工具函数（页内或 `utils/`）：`fmtCost(v)`——`v == null → ''`；`v < 0.01 → '<¥0.01'`；否则 `¥${v.toFixed(2)}`（消灭 `toFixed(6)` 的 ¥0.000123）
- 列表卡：`model · tokens` 元信息行**删除**，保留 日期 + typeLabel + ScoreBadge（卡片降到一行主信息 + 一行日期/类型）

### 2. `ReviewsPage.jsx` 报告卡

- 删除 `{r.model} · {r.prompt_tokens}+{r.completion_tokens} tokens` 行
- 卡片改为：第一行 周期（date ~ period_end），第二行 `flex items-center gap-2`：`<ScoreBadge score={r.score} />` + `text-xs text-gray-600` 的类型文字（周复盘/月复盘）
- 详情区（ReviewDetail）的"模型："行 → 与 AIReportsPage 相同的 `<details>` 折叠（testid `review-tech-details`；tokens 从 report 取，cost 用同一 fmtCost——若两处重复可把 fmtCost 放 `frontend/src/utils/format.js` 新文件，允许 +1 预算）

### 3. `CoachChatPage.jsx` metaLine 简化

- metaLine 只保留：时间（UIX-05 已加）+ assistant 消息追加 `由 AI 教练生成`
- **删除 tokens/成本拼接**（prompt_tokens/completion_tokens/cost_estimate 不再上屏）
- 相关测试断言适配

### 4. `utils/status.js` 3 色收敛

```js
export const STATUS_COLORS = {
  auto_matched: 'bg-green-500',   // 已匹配
  manual_matched: 'bg-green-500', // 已匹配
  xunji_only: 'bg-indigo-500',    // 仅单源（待匹配）
  garmin_only: 'bg-indigo-500',   // 仅单源（待匹配）
  pending: 'bg-amber-500',        // 待确认
}
```
- `STATUS_LABELS`/`statusLabel()` **不动**（详情/列表的 Badge 文案仍是 5 类细分）
- 注释说明：日历圆点 3 色语义（已匹配/仅单源/待确认），label 保持 5 类

### 5. `CalendarPage.jsx` 图例 3 项

图例区改为 3 项（样式不变）：`bg-green-500 已匹配`、`bg-indigo-500 仅单源`、`bg-amber-500 待确认`
- 若有"待确认 N 条"提示条需求（原型 03 有 amber 提示条）：利用 Layout 已有的 pendingCount？——不做，属增量功能，保持本切片纯收敛（见决策点 4）

### 6. `SkinfoldPanel.jsx` emoji 清理

- `SELF_TEST_LABEL` 的 ✅⚠️❌ 删除，改为 Badge 映射渲染：合格→`<Badge variant="green">合格</Badge>`、注意→`<Badge variant="amber">注意</Badge>`、异常→`<Badge variant="red">异常</Badge>`（按现有三档文案映射，保留原文案文字）
- 全文件再检查无其他 emoji

### 7. `SimpleMarkdown.jsx` 标题层级

修复映射（页面已有 h1，报告正文从 h2 起）：
- `#` → `<h2 className="text-lg font-bold text-gray-900">`
- `##` → `<h3 className="text-base font-bold text-gray-900">`
- `###` → `<h4 className="text-sm font-bold text-gray-900">`
- `####` → `<h5 className="text-sm font-semibold text-gray-700">`
形成 text-lg/base/sm/sm(semibold) 梯度；更新 SimpleMarkdown.test.jsx 断言

## 关键决策点（默认方案 + 理由）

1. **折叠用原生 `<details>` 而非自建展开组件**：零 JS、零测试负担、天然可访问；summary 补 min-h-[36px] 热区。
2. **成本显示阈值 <¥0.01**：成本对用户的意义是"量级感知"，分位以下无信息价值。
3. **圆点 3 色但 label 保留 5 类**：颜色是快速扫读通道（收敛），文字是精确语义通道（保留）；两者不矛盾。
4. **不加"待确认提示条"新功能**：原型有但属新增功能而非收敛，避免切片范围蔓延；后续单独评估。
5. **emoji 换 Badge 而非删除自测等级**：等级是有信息量的，Badge 是全站统一的等级载体。

## 验收标准（审核方执行，你不跑）

1. `git status --short`：仅预算内文件
2. `cd frontend && npx vitest run`：全量通过，无回退
3. `cd frontend && npm run lint`：无新增告警
4. `cd frontend && npm run build`：通过
5. 目检抽查：`grep "toFixed(6)" frontend/src` = 0；`grep "✅\|⚠️\|❌\|💬" frontend/src` = 0；`grep "bg-blue-500\|bg-yellow-400\|bg-purple-500\|bg-orange-500" frontend/src` = 0；CoachChatPage `grep "tokens"` 上屏代码 = 0

## 交付报告模板（最终回复必须包含）

1. 完成内容摘要
2. 文件清单（新增/修改，逐个路径）
3. 越界自检
4. 关键决策 5 条逐条确认或说明偏差
5. 测试用例清单（新增/修改用例名）
6. 遗留问题 / 给 UIX-08（第四期打磨）的注意事项
7. 编码红线自查（无 BOM / 无分号风格 / 无新依赖 / 未跑验收命令）
8. 对验收标准 1-5 的预期自评

按本提示词直接执行（headless 无人工确认）：先输出实施计划，然后动手，最终回复给出完整交付报告。
