# UIX-01 切片开发提示词：设计地基 — UI 原语层（Button/Card/Badge/PillGroup/Skeleton/Toast/ConfirmDialog/EmptyState/ErrorState）

> 你是本仓库的前端工程师（React 19 + Tailwind CSS 4 + Vitest）。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（vitest / lint / build 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须 UTF-8 无 BOM、LF 行尾；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件；**禁加任何新依赖**。

## 需求（UI/UX 审计 · 第一期：设计地基）

仓库已完成全站 UI/UX 审计（结论：无共享 UI 原语是万恶之源——同一按钮类名复制 30+ 处、卡片 4 种变体、5 种强调色混用、触控热区普遍 28–36px）。本切片建立 `frontend/src/components/ui/` 原语层，**只新增，不改动任何现有页面/组件**（页面迁移在后续切片 UIX-02/03 进行）。

视觉规格参考：`docs/prototypes/01-ui-kit.html`（已审批通过的设计规范原型图，可读取参考，但实现以本提示词的精确类名为准）。

## 已核实的关键事实（实读代码，可直接采信）

- `frontend/src/index.css` 全文仅 1 行：`@import "tailwindcss";`（Tailwind 4.3.3，经 `@tailwindcss/vite` 插件接入，无 tailwind.config 文件）
- 代码风格（`frontend/src/components/BottomTabs.jsx` 等）：**无分号**、单引号、2 空格缩进、中文注释、props 解构、默认导出组件
- 测试约定（`frontend/src/components/__tests__/BottomTabs.test.jsx`）：`import { render, screen } from '@testing-library/react'` + `import { describe, expect, it } from 'vitest'`；jest-dom matchers 可用（`toBeInTheDocument`/`toHaveClass`，setup 在 `src/test/setup.js`）；vitest 配置在 `vite.config.js`（environment jsdom、globals true）
- 既有相关组件：`src/components/BottomSheet.jsx`（底部抽屉：z-50、role="dialog"、背板点击关闭、打开时锁 body 滚动——ConfirmDialog 可参照其模式但为居中弹窗）；`src/components/ScoreBadge.jsx`（评分徽章，保留不动）
- `window.matchMedia` 在 jsdom 需 mock（`src/test/mockMatchMedia.js` 已有 `installMatchMedia`），本切片组件不依赖 matchMedia
- 不存在 `src/components/ui/` 目录

## 文件预算（共 11 个：新增 10 + 修改 1，不得越界）

新增 10：
1. ✱ `frontend/src/components/ui/Button.jsx`
2. ✱ `frontend/src/components/ui/Card.jsx`
3. ✱ `frontend/src/components/ui/Badge.jsx`
4. ✱ `frontend/src/components/ui/PillGroup.jsx`
5. ✱ `frontend/src/components/ui/Skeleton.jsx`
6. ✱ `frontend/src/components/ui/Toast.jsx`（Provider + hook + 容器，单文件）
7. ✱ `frontend/src/components/ui/ConfirmDialog.jsx`
8. ✱ `frontend/src/components/ui/EmptyState.jsx`
9. ✱ `frontend/src/components/ui/ErrorState.jsx`
10. ✱ `frontend/src/components/__tests__/ui-primitives.test.jsx`

修改 1：
11. 改 `frontend/src/index.css`（仅**追加**语义色约定注释块，不动既有 1 行 import；不新增 @theme，见关键决策点 1）

**禁止修改**：`frontend/src/components/ui/index.js` 不做（见关键决策点 2）；任何现有页面/组件/测试一行不动。

## 开发内容（逐文件精确规格）

### 1. `ui/Button.jsx`

props：`{ variant = 'primary', fullWidth = false, type = 'button', disabled = false, onClick, children, testId, className = '' }`

- 基础类（所有变体共享）：`inline-flex items-center justify-center gap-1.5 rounded-lg px-4 text-sm font-medium min-h-[44px] transition disabled:cursor-not-allowed disabled:opacity-50`
- variant 映射：
  - `primary`：`bg-indigo-600 text-white hover:bg-indigo-700 active:bg-indigo-800`
  - `secondary`：`border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 active:bg-gray-100`
  - `danger`：`border border-red-300 bg-white text-red-600 hover:bg-red-50 active:bg-red-100`（描边样式，破坏性操作的默认形态）
  - `dangerSolid`：`bg-red-600 text-white hover:bg-red-700 active:bg-red-800`（仅 ConfirmDialog 确认键用）
  - `ghost`：`px-3 text-indigo-600 hover:bg-indigo-50 active:bg-indigo-100`
- `fullWidth` 时追加 `w-full`；`className` 最后拼接（允许调用方微调）
- 渲染 `<button type={type} disabled={disabled} onClick={onClick} data-testid={testId}>`，未知 variant 回退 primary
- 设计意图注释：min-h-[44px] 是移动端触控热区红线（审计发现全站按钮 28–36px）

### 2. `ui/Card.jsx`

props：`{ children, className = '', testId }`
- 渲染 `<div data-testid={testId} className={合并后类名}>`
- 基础类：`rounded-xl border border-gray-200 bg-white p-4 shadow-sm`（全站唯一卡片规格，淘汰原有 4 种变体）

### 3. `ui/Badge.jsx`

props：`{ variant = 'gray', children, testId }`
- 基础类：`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium`
- variant 映射：`indigo→bg-indigo-100 text-indigo-700`、`green→bg-green-100 text-green-700`、`amber→bg-amber-100 text-amber-800`、`gray→bg-gray-100 text-gray-600`、`red→bg-red-100 text-red-700`
- 未知 variant 回退 gray

### 4. `ui/PillGroup.jsx`

分段/胶囊切换组（用于 TrendsPage 周期切换、AIReportsPage/ReviewsPage 类型切换的后续迁移）。
props：`{ options = [], value, onChange, testId }`，options 元素形如 `{ value: '4', label: '近 4 周' }`
- 容器：`<div data-testid={testId} className="flex flex-wrap gap-1" role="tablist">`
- 每个选项 `<button role="tab" aria-selected={是否激活}>`，类名：
  - 基础：`rounded-md px-3 text-sm font-medium min-h-[44px]`
  - 激活：`bg-indigo-600 text-white`
  - 未激活：`text-gray-700 hover:bg-gray-200 active:bg-gray-300`
- 点击调用 `onChange(option.value)`

### 5. `ui/Skeleton.jsx`

两个具名导出 + 一个默认导出：
- 默认导出 `Skeleton({ className = '', testId })`：`<div data-testid={testId} className={\`animate-pulse rounded bg-gray-200 \${className}\`}>`
- 具名导出 `SkeletonText({ lines = 3, testId })`：渲染 lines 根 `h-3 animate-pulse rounded bg-gray-100`，宽度分别为 `w-full`、末行 `w-2/3`、其余 `w-5/6`，行间 `mt-2`，容器 `data-testid={testId}`
- 用途注释：淘汰全站 15+ 处裸文本"加载中…"

### 6. `ui/Toast.jsx`

单文件包含 `ToastProvider`、`useToast`。
- `ToastProvider({ children })`：内部维护 `toasts` state（`{ id, message, type }`），提供 context 值 `{ toast }`；`toast(message, type = 'success')` 追加一条并 3000ms 后自动移除（setTimeout，组件卸载时 clearTimeout）
- 容器：`<div data-testid="toast-container" className="pointer-events-none fixed inset-x-0 top-0 z-[60] flex flex-col items-center gap-2 px-4 pt-[max(1rem,env(safe-area-inset-top))]">`
- 单条：`<div role="status" className="pointer-events-auto flex items-center gap-2 rounded-xl bg-gray-900 px-4 py-3 text-sm text-white shadow-lg">`，type 为 `success` 时前缀内联 SVG 对勾图标（stroke `#4ade80`），`error` 时前缀红色感叹号圆图标（stroke `#f87171`），`info` 无图标
- `useToast()`：从 context 取 `{ toast }`，未包 Provider 时抛错（Error('useToast must be used within ToastProvider')）
- id 生成：`Date.now() + Math.random()` 即可，不引 uuid 依赖

### 7. `ui/ConfirmDialog.jsx`

居中确认弹窗，替换全站 6 处 `window.confirm`。参照 `BottomSheet.jsx` 的模式（锁 body 滚动、背板关闭）但为居中布局。
props：`{ open, title, description, confirmText = '确认', cancelText = '取消', danger = false, onConfirm, onCancel }`
- `open`  falsy 时返回 null
- 结构：`<div className="fixed inset-0 z-50 flex items-center justify-center p-4">` → 背板 `<div data-testid="confirm-dialog-backdrop" className="absolute inset-0 bg-black/50" onClick={onCancel}>` + 面板 `<div role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title" data-testid="confirm-dialog" className="relative w-full max-w-sm rounded-xl bg-white p-5 shadow-xl mb-[env(safe-area-inset-bottom)]">`
- 面板内：`<h2 id="confirm-dialog-title" className="text-base font-semibold text-gray-900">{title}</h2>` + `<p className="mt-1 text-sm text-gray-600">{description}</p>`（description 可省略则不渲染该 p）+ 按钮行 `mt-4 flex gap-3`
- 按钮：取消用 Button secondary（flex-1），确认用 Button（danger ? 'dangerSolid' : 'primary'，flex-1）——**import 同目录 Button.jsx**
- 打开时锁 body 滚动（useEffect，同 BottomSheet 模式）；Esc 键关闭（useEffect 监听 keydown，`e.key === 'Escape'` 调 onCancel）；打开时焦点落到取消按钮（ref + useEffect focus()）

### 8. `ui/EmptyState.jsx`

props：`{ icon, title, description, action, testId }`
- 容器：`<div data-testid={testId} className="rounded-xl border border-gray-200 bg-white p-6 text-center shadow-sm">`
- icon（可选 node）：`<div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-indigo-50 text-indigo-500">{icon}</div>`
- title：`<p className="mt-3 text-sm font-medium text-gray-900">`；description（可选）：`<p className="mt-1 text-xs text-gray-600">`
- action（可选 node）：`<div className="mt-4 flex justify-center">{action}</div>`

### 9. `ui/ErrorState.jsx`

props：`{ message, onRetry, testId }`
- 容器：`<div role="alert" data-testid={testId} className="rounded-xl border border-red-200 bg-red-50 p-4">`
- 内部 flex 行：`flex items-center justify-between gap-2`；左侧 `<div className="flex items-center gap-2 text-sm text-red-700">`（内联 SVG 感叹号圆图标 + `{message}`）
- `onRetry` 存在时渲染 `<button min-h-[44px] rounded-lg px-3 text-sm font-medium text-red-700 hover:bg-red-100 active:bg-red-200 onClick={onRetry}>重试</button>`
- 设计意图注释：错误态必带恢复入口（审计发现原错误只是一行红字，用户无法恢复）

### 10. `__tests__/ui-primitives.test.jsx`

覆盖（每组件 1-3 个用例，总计 12-16 个）：
- Button：5 个 variant 各自关键类名（primary 含 `bg-indigo-600`/`min-h-[44px]`；danger 含 `border-red-300` 且**不含** `bg-red-600`；dangerSolid 含 `bg-red-600`）；disabled 时 `disabled:opacity-50`；fullWidth 含 `w-full`；未知 variant 回退 primary
- Card：基础四件套类名
- Badge：indigo/amber 变体类名；未知回退 gray
- PillGroup：渲染 options、激活项 `aria-selected="true"` + `bg-indigo-600`、点击触发 onChange 且传出对应 value
- Skeleton / SkeletonText：testId 渲染、lines=3 时 3 根条
- ConfirmDialog：open=false 不渲染；open 时 role="dialog" 且标题正确；点背板调 onCancel；按 Esc 调 onCancel（fireEvent.keyDown(document)）；danger 时确认键含 `bg-red-600`；点确认调 onConfirm
- Toast：包 Provider 后调 toast('已保存') 出现 role="status" 文本；vi.useFakeTimers 前进 3000ms 后消失；useToast 在 Provider 外抛错（用 expect(() => render(...)).toThrow）
- EmptyState：title/description/action 渲染
- ErrorState：role="alert"、点重试触发 onRetry

注意 jsdom 不支持焦点真实行为，ConfirmDialog 焦点逻辑不测试。

### 11. 改 `index.css`（仅追加注释块）

在既有 `@import "tailwindcss";` 之后追加（不新增 @theme、不改 import 行）：

```css
/* ===== 语义色约定（UIX-01 设计地基）=====
 * 主操作色：indigo-600（唯一主按钮色；green/emerald/amber 不再作按钮底色）
 * 危险操作：red-600（默认描边按钮 Button variant="danger"，实心仅 ConfirmDialog 确认键）
 * 成功反馈：green-600/700 仅文字与 Badge，不作按钮底色
 * 警告提示：amber 仅提示条与 Badge
 * 正文辅助文字下限：gray-600（gray-400/500 对比度不达 WCAG AA，仅可用于纯装饰）
 * 组件唯一来源：src/components/ui/（Button/Card/Badge/PillGroup/Skeleton/Toast/ConfirmDialog/EmptyState/ErrorState）
 */
```

## 关键决策点（默认方案 + 理由）

1. **不引入 Tailwind @theme 自定义色**：ui 组件直接使用 indigo/red 等标准色类。理由：组件层本身就是单一事实来源（改色只改 ui/ 目录），引入 @theme 别名会让后续页面迁移时类名与测试断言都变间接，得不偿失。index.css 仅用注释固化语义约定。
2. **不写 ui/index.js barrel**：项目现有代码全部用直接路径 import（如 `import BottomTabs from './BottomTabs'`），保持一致的显式依赖，避免循环依赖风险。
3. **Toast 用 Provider+hook 而非全局事件**：与 React 19 兼容最好、可测试；后续切片在 Layout 挂一次 Provider 即可。
4. **ConfirmDialog 独立实现而非复用 BottomSheet**：移动端语义上"确认"是居中模态（BottomSheet 是内容抽屉）；两者锁滚动/背板模式相同但布局与 aria 不同。
5. **min-h-[44px] 写进 Button/PillGroup 基础类**：审计核心结论——触控热区不能依赖各页面自觉。

## 验收标准（审核方执行，你不跑）

1. `git status --short`：仅出现本提示词文件预算内的 11 个文件（10 新增 + index.css 修改）
2. `cd frontend && npx vitest run`：全量测试通过（既有 331+ 用例不回退 + 新用例全过）
3. `cd frontend && npm run lint`（oxlint）：无新增告警
4. `cd frontend && npm run build`：构建通过
5. 目检：index.css 既有 import 行未动；无 BOM；无分号风格统一

## 交付报告模板（最终回复必须包含）

1. 完成内容摘要（每组件一句话）
2. 文件清单（新增/修改，逐个路径）
3. 越界自检：除预算文件外 0 修改的确认
4. 关键决策的执行情况（5 条逐条确认或说明偏差）
5. 测试用例清单（用例名列表）
6. 遗留问题 / 给后续切片（UIX-02 页面迁移）的注意事项
7. 编码红线自查（无 BOM / 无分号风格 / 无新依赖 / 未跑验收命令）
8. 对验收标准 1-5 的预期自评

按本提示词直接执行（headless 无人工确认）：先输出实施计划，然后动手，最终回复给出完整交付报告。
