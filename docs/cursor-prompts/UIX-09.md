# UIX-09 切片开发提示词：第四期打磨 B — 暗色模式（class 策略 · 跟随系统 · 全站机械映射）

> 你是本仓库的前端工程师（React 19 + Tailwind CSS 4 + Vitest）。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（vitest / lint / build 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须 UTF-8 无 BOM、LF 行尾；代码风格无分号、单引号、2 空格、中文注释；不得修改 `.env` / `.env.*`；不得删除任何既有文件；**禁加任何新依赖**。

## 需求（UI/UX 审计 · 第四期：暗色模式）

审计发现全站 0 处 `dark:`/`prefers-color-scheme`——健身用户大量在夜间/弱光使用，暗色是原生 App 的底线能力。本切片落地暗色：

- **策略**：class 型 dark variant（`@custom-variant`），`<html>` 挂 `.dark`；`main.jsx` 用 matchMedia 监听 `prefers-color-scheme: dark` 自动切换（不做手动开关，为后续设置页开关留好结构）
- **覆盖**：`index.css` variant 定义 + main.jsx 监听 + `frontend/src/**` 全部 jsx 的机械映射（规则见下，无一例外文件）

## 已核实的关键事实（实读代码，可直接采信）

- `frontend/src/index.css`：仅 `@import "tailwindcss";` + UIX-01 语义色注释块；Tailwind 4.3.3（`dark:` 默认媒体查询型，本切片用 `@custom-variant` 改为 class 型）
- `frontend/src/main.jsx`：仅挂载 `<App />`（239B，全文 239 字节）
- Tailwind 4 class 型暗色写法：`@custom-variant dark (&:where(.dark, .dark *));` 放在 index.css 的 import 之后
- 全站色板使用情况（grep 已扫）：页面底色 `bg-gray-50`；卡片/表面 `bg-white`；文字 `text-gray-900/800/700/600`；边框 `border-gray-200/300/100`；次级表面 `bg-gray-100/50`；语义色 `indigo-600/red-600/green-*/amber-*`；既有测试大量断言亮色类名（`toHaveClass`/`className).toMatch`）——**追加 dark: 类不影响既有断言**（类 token 仍在）
- 既有组件层级：Card/Button/Badge/EmptyState/ErrorState/Toast/ConfirmDialog/BottomSheet/BottomTabs/Layout 原语已收口（UIX-01~05），页面内仍有直接书写的 bg-white/text-gray-* 元素

## 映射规则（全站统一，逐文件执行）

### A. 基础映射（所有 jsx，机械追加 dark: 变体，不删除原类）

| 亮色类 | 追加 |
|--------|------|
| `bg-gray-50`（页面底色） | `dark:bg-gray-950` |
| `bg-white`（卡片/表面/输入框/气泡） | `dark:bg-gray-900` |
| `bg-gray-100`（次级表面/休息日/AI气泡） | `dark:bg-gray-800` |
| `text-gray-900` | `dark:text-gray-100` |
| `text-gray-800` | `dark:text-gray-200` |
| `text-gray-700` | `dark:text-gray-300` |
| `text-gray-600` | `dark:text-gray-400` |
| `border-gray-100` | `dark:border-gray-800` |
| `border-gray-200` | `dark:border-gray-700` |
| `border-gray-300` | `dark:border-gray-600` |
| `bg-indigo-50` / `bg-indigo-50/50` | `dark:bg-indigo-950/50` |
| `bg-red-50` | `dark:bg-red-950/50` |
| `bg-amber-50` | `dark:bg-amber-950/50` |
| `bg-green-50` | `dark:bg-green-950/50` |

### B. 特殊规则

B1. **主色按钮/徽标不动**：`bg-indigo-600 text-white`、`bg-red-600`、`bg-gray-900`（Toast）在暗色下可读性不变，不加 dark 变体
B2. **hover/active 配对**：原类有 `hover:bg-gray-100` → 追加 `dark:hover:bg-gray-800`；`hover:bg-gray-50` → `dark:hover:bg-gray-800`；`hover:bg-gray-200` → `dark:hover:bg-gray-700`；`hover:bg-red-50` → `dark:hover:bg-red-950/50`；`hover:bg-indigo-50/100` → `dark:hover:bg-indigo-950/50`
B3. **focus ring**：`focus:ring-indigo-100` → 追加 `dark:focus:ring-indigo-900`
B4. **语义文字**：`text-red-600/700`、`text-amber-800`、`text-green-600/700`、`text-indigo-600/700` 在暗色语义底上保持不动（950/50 底 + 600/700 字对比可接受）
B5. **阴影**：`shadow-sm/shadow` 不动（暗色下阴影自然弱化，可接受）
B6. **日历格子 `bg-indigo-50`（有训练日）**：按 A 表映射；`text-gray-800` 日期数字按 A 表
B7. **RawJson 深灰块 `bg-gray-900 text-gray-100`**：暗色下改 `dark:bg-black dark:text-gray-300`（保持反差）
B8. **Skeleton `bg-gray-200/bg-gray-100`**：追加 `dark:bg-gray-800`/`dark:bg-gray-700`
B9. **ECharts 图表**：`setOption` 文字色目前多为默认黑——本切片**不改图表 option**（图表暗色属已知遗留，记入交付报告）
B10. **友元类不存在时跳过**：某元素没有匹配规则中的亮色类则不加

## 文件预算（不得越界）

1. 改 `frontend/src/index.css`（import 后加 `@custom-variant dark (&:where(.dark, .dark *));` + 注释）
2. 改 `frontend/src/main.jsx`（matchMedia 监听：初始 + change 事件切换 `document.documentElement.classList` 的 `dark` 类；3-5 行 + cleanup）
3. 改 `frontend/src/components/**/*.jsx` 与 `frontend/src/pages/**/*.jsx`（**全部**，按 A/B 规则机械追加；ui/ 原语优先保证正确）
4. 改 `frontend/index.html`（`<html>` 加 `class="dark"`？——**不加**：默认亮色，由 main.jsx 按系统偏好切换，避免无 JS 时闪 dark）
5. 改 `frontend/src/components/__tests__/darkMode.test.jsx`（✱ 新文件）：
   - `main.jsx` 的监听逻辑抽成 `frontend/src/utils/darkMode.js`（✱ 新文件：`applyDarkClass(isDark)` + `initDarkModeListener()` 返回 cleanup——main.jsx 只调它，便于测试）
   - 测试：matchMedia dark=true 时 html 有 dark 类；切换后移除；cleanup 移除监听
   - 抽查映射：Card 渲染含 `dark:bg-gray-900`；Layout 根含 `dark:bg-gray-950`；BottomTabs 含 `dark:bg-gray-900`
   - （测试总数预算：新文件 2 个——`utils/darkMode.js` + 测试；jsx 修改不限个数但仅限 dark: 追加）

## 关键决策点（默认方案 + 理由）

1. **class 型而非媒体查询型 dark variant**：可用 jsdom/截图 deterministic 验证（html.dark 一加即验），且为后续设置页手动开关留好结构；代价仅 index.css 一行。
2. **不当前做手动开关**：跟随系统是原生 App 主流默认；设置项属增量功能，留到用户提需求。
3. **机械追加而非语义重构**：暗色是呈现层正交关注点，不动任何布局/逻辑；`dark:` 追加对既有亮色断言零影响。
4. **图表 option 不改**：ECharts 文字色需 JS 感知主题（getComputedStyle 或 context），属独立小工程；先在交付报告登记遗留，不与 CSS 层混在一起。
5. **950/50 半透明语义底**：暗色下用 950 色 + 50% 透明度而非纯 900，保留语义色相的同时避免过亮斑块。

## 验收标准（审核方执行，你不跑）

1. `git status --short`：index.css/main.jsx/index.html(未改)/utils/darkMode.js/测试 + jsx 文件（仅 dark: 追加 diff）
2. `cd frontend && npx vitest run`：全量通过，无回退（重点：既有类名断言不因追加破坏）
3. `cd frontend && npm run lint`：无新增告警
4. `cd frontend && npm run build`：通过
5. 审核方抽查：`grep -c "dark:" frontend/src/components/ui/Card.jsx` ≥ 2；`grep "custom-variant" index.css` = 1；既有亮色类**零删除**（git diff 中不允许出现删除 class token 的行，除 B7 特例外）

## 交付报告模板（最终回复必须包含）

1. 完成内容摘要（映射文件数统计）
2. 文件清单（新增/修改）
3. 越界自检
4. 关键决策 5 条逐条确认或说明偏差
5. 测试用例清单
6. 遗留问题（必须含：ECharts 图表暗色未做、手动开关未做）
7. 编码红线自查（无 BOM / 无分号风格 / 无新依赖 / 未跑验收命令 / 未删亮色类）
8. 对验收标准 1-5 的预期自评

按本提示词直接执行（headless 无人工确认）：先输出实施计划，然后动手，最终回复给出完整交付报告。
