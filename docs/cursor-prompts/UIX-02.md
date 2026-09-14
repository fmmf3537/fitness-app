# UIX-02 切片开发提示词：P0 修复包 — 登录深链接 / 401 统一拦截 / 安全区收口 / 日历错误态

> 你是本仓库的前端工程师（React 19 + Tailwind CSS 4 + Vitest）。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（vitest / lint / build 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须 UTF-8 无 BOM、LF 行尾；代码风格无分号、单引号、2 空格、中文注释；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件；**禁加任何新依赖**。

## 需求（UI/UX 审计 · 第二期 P0 组）

审计发现的两个 P0 与一个 P1 信任缺陷，本切片修复：
1. **登录后丢深链接**：`RequireAuth.jsx:7` 已传 `state={{ from: location }}`，但 `LoginPage.jsx:18` 硬编码 `navigate('/')`，分享链接用户登录后回不到原页
2. **401 无统一处理**：token 过期后全站各页只显示"未登录"，不跳转登录页
3. **安全区只做了壳层**：聊天输入区、PosterPreviewModal、BottomSheet footer、两个自制 modal 全部缺 `env(safe-area-inset-bottom)`；LoginPage 用 `min-h-screen` 非 `min-h-dvh`
4. **日历错误态误导**（P1 信任伤害）：`CalendarPage.jsx:95-130` 加载失败时只显示一行红字、下方仍渲染全空日历网格，用户会误以为整月无数据，且无重试入口

UIX-01 已交付 UI 原语层 `frontend/src/components/ui/`（Button/Card/Badge/PillGroup/Skeleton/Toast/ConfirmDialog/EmptyState/ErrorState），本切片开始消费其中 ErrorState/Skeleton。

## 已核实的关键事实（实读代码，可直接采信）

- `frontend/src/api/client.js`：`api()`/`apiForm()`/`download()` 三个函数的 401 分支均为 `clearToken(); throw new ApiError(401, 'unauthorized')`（行 44-47、65-68、80-83）；`login()` 的 401 抛 `ApiError(401, '口令错误')`（行 102-104，**不可改动其行为**）
- `frontend/src/components/RequireAuth.jsx:7`：`<Navigate to="/login" replace state={{ from: location }} />`（from 是 location 对象）
- `frontend/src/pages/LoginPage.jsx:18`：`navigate('/', { replace: true })`；行 27 `min-h-screen`；行 41 输入框 `px-3 py-2 focus:border-indigo-500 focus:outline-none`；行 53 按钮 `py-2`
- `frontend/src/pages/CalendarPage.jsx`：行 95 `{error && <p role="alert" …>加载失败：{error}</p>}`；行 96 `{loading && <p …>加载中…</p>}`；行 98-130 网格与图例**无条件渲染**；`load` 是 useCallback 包装的加载函数（行 27-34）
- `frontend/src/pages/CoachChatPage.jsx:204`：输入区容器 `<div className="flex items-end gap-2 border-t bg-white p-3">`
- `frontend/src/components/PosterPreviewModal.jsx:13`：面板 `<div className="flex max-h-full w-full max-w-sm flex-col rounded-xl bg-white p-4 shadow-xl">`
- `frontend/src/components/BottomSheet.jsx:53`：footer `<div data-testid="bottom-sheet-footer" className="shrink-0 border-t border-gray-100 px-4 py-3">`
- `frontend/src/pages/BodyMetricsPage.jsx:394-423`：sync-modal 容器 `z-10 flex items-center justify-center bg-black/30`（无 p-4），面板 `w-96 rounded-lg bg-white p-4 shadow-lg`（w-96=384px，360px 窄屏溢出），无 role="dialog"
- `frontend/src/pages/CoachPreferencesPage.jsx:266-324`：preference-modal 容器同样 `z-10 ... bg-black/30`（有 role="dialog" aria-modal），面板 form `w-full max-w-md rounded-lg bg-white p-4 shadow-lg`
- jsdom 限制：`window.location.assign()` 在 jsdom 会抛 "Not implemented: navigation"；对 `window.location.href` 赋值只输出告警不抛异常
- 现有测试：`src/api/__tests__/client.test.js` 含用例「401 清除 token 并抛 ApiError(401)」（jsdom 环境，fetch 被 mock）；`src/pages/__tests__/CalendarPage.test.jsx` 5 个用例（无错误态用例）；无 LoginPage 测试
- UI 原语 import 方式：`import ErrorState from '../../components/ui/ErrorState'`（无 barrel，直接路径）
- `ErrorState` props：`{ message, onRetry, testId }`；`Skeleton` 默认导出 `{ className, testId }`，另有具名 `SkeletonText({ lines, testId })`

## 文件预算（共 11 个：改 10 + 新增 1，不得越界）

1. 改 `frontend/src/api/client.js`（401 统一跳登录）
2. 改 `frontend/src/pages/LoginPage.jsx`（深链接回跳 + dvh + 44px + focus ring）
3. 改 `frontend/src/pages/CalendarPage.jsx`（错误态/加载态重构）
4. 改 `frontend/src/pages/CoachChatPage.jsx`（**仅**输入区容器一行安全区类名，其余不动）
5. 改 `frontend/src/components/PosterPreviewModal.jsx`（面板安全区）
6. 改 `frontend/src/components/BottomSheet.jsx`（footer 安全区）
7. 改 `frontend/src/pages/BodyMetricsPage.jsx`（**仅** sync-modal 区块，其余不动）
8. 改 `frontend/src/pages/CoachPreferencesPage.jsx`（**仅** preference-modal 区块，其余不动）
9. 改 `frontend/src/api/__tests__/client.test.js`（适配 401 跳转 + 新增用例）
10. 改 `frontend/src/pages/__tests__/CalendarPage.test.jsx`（新增错误态用例）
11. ✱ `frontend/src/pages/__tests__/LoginPage.test.jsx`（新）

## 开发内容

### 1. `api/client.js` — 401 统一跳登录

在文件底部（`login` 之前）新增内部函数并改造三个 401 分支：

```js
/** UIX-02：401 统一处理——清 token、记住当前路径、跳登录页（login 自身除外） */
function redirectToLogin() {
  if (typeof window === 'undefined' || !window.location) return
  if (window.location.pathname.startsWith('/login')) return
  try {
    sessionStorage.setItem('fh_auth_from', window.location.pathname + window.location.search)
  } catch {
    // sessionStorage 不可用（隐私模式等）时静默跳过，仅跳转
  }
  // 用 href 赋值而非 assign()：jsdom 下 assign 会抛 Not implemented
  window.location.href = '/login'
}
```

- `api()`/`apiForm()`/`download()` 的 401 分支改为：`clearToken()` → `redirectToLogin()` → `throw new ApiError(401, 'unauthorized')`（保持抛出，页面层兼容）
- `login()` 的 401 分支**不动**（口令错误不该跳转）

### 2. `pages/LoginPage.jsx` — 深链接回跳 + 移动端基线

- 顶部 import 增加 `useLocation`（react-router-dom）
- 组件内 `const location = useLocation()`
- `handleSubmit` 成功分支的跳转逻辑改为：
  1. 优先 `location.state?.from?.pathname`（RequireAuth 传的 location 对象，取 pathname + search 拼接）
  2. 其次 `sessionStorage.getItem('fh_auth_from')`（client.js 401 拦截存的），读取后 `sessionStorage.removeItem('fh_auth_from')`
  3. 都没有则 `'/'`
  统一 `navigate(target, { replace: true })`
- 行 27：`min-h-screen` → `min-h-dvh`（移动端浏览器工具栏伸缩时不再跳动）
- 输入框（行 41）：追加 `min-h-[44px]`，focus 改 `focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 focus:outline-none`（原 focus:outline-none 后键盘焦点不可见）
- 按钮（行 53）：`py-2` → `min-h-[44px]`，追加 `text-sm font-medium active:bg-indigo-800`

### 3. `pages/CalendarPage.jsx` — 错误态不再渲染空网格

- import 增加：`import ErrorState from '../components/ui/ErrorState'` 和 `import Skeleton from '../components/ui/Skeleton'`
- 行 95-96 及网格/图例区块重构为三分支（保持现有 grid 代码原样内嵌）：
  - `error`：渲染 `<ErrorState testId="calendar-error" message={\`加载失败：${error}\`} onRetry={load} />`，**不渲染**星期头、日历网格、图例
  - `loading`：渲染 5 行 7 列的 Skeleton 网格（`<div className="grid grid-cols-7 gap-1">` 内 35 个 `<Skeleton className="h-16" />`），**不渲染**真实网格和图例；保留顶部月份导航可交互
  - 正常：渲染现有星期头 + 网格 + 图例（原样保留）
- 保留 `role="alert"` 语义：ErrorState 内部已带 `role="alert"`，删除原裸文本错误行

### 4. `pages/CoachChatPage.jsx` — 仅输入区安全区（一行）

行 204 容器类名：`"flex items-end gap-2 border-t bg-white p-3"` → `"flex items-end gap-2 border-t bg-white px-3 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"`
（其余聊天体验问题——乐观上屏/失败重试/时间戳——属 UIX-05，本切片一律不碰）

### 5. `components/PosterPreviewModal.jsx` — 面板安全区

行 13 面板类名追加 `mb-[env(safe-area-inset-bottom)]`（底部按钮不再被 Home 手势条遮挡）

### 6. `components/BottomSheet.jsx` — footer 安全区

行 53 footer 类名：`"shrink-0 border-t border-gray-100 px-4 py-3"` → `"shrink-0 border-t border-gray-100 px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"`

### 7. `pages/BodyMetricsPage.jsx` — 仅 sync-modal 区块（394-423）

- 容器：`z-10` → `z-50`，追加 `p-4`，追加 `role="dialog" aria-modal="true"`
- 面板：`w-96 rounded-lg bg-white p-4 shadow-lg` → `w-full max-w-sm rounded-xl bg-white p-4 shadow-xl mb-[env(safe-area-inset-bottom)]`
- data-testid 全部保留不变（sync-modal/sync-summary/sync-cancel/sync-confirm）

### 8. `pages/CoachPreferencesPage.jsx` — 仅 preference-modal 区块（266-324）

- 容器：`z-10` → `z-50`，追加 `p-4`（role/aria 已有，保留）
- 面板 form：类名追加 `mb-[env(safe-area-inset-bottom)]`
- data-testid 全部保留不变

### 9. `api/__tests__/client.test.js` — 适配 + 新增

- 现有「401 清除 token 并抛 ApiError(401)」用例会触发 `redirectToLogin`：jsdom 下 href 赋值不抛异常但输出 "Not implemented" 告警，用例应仍通过；为消除噪音并断言新行为，在该 describe 的 beforeEach 中 stub：`vi.stubGlobal('location', { pathname: '/settings', search: '', href: '' })` 不合适——jsdom 的 window.location 不可直接替换。推荐做法：用 `Object.defineProperty(window, 'location', { writable: true, value: { pathname:'/settings', search:'', href:'' } })` 或用 `vi.spyOn` 不可行时直接静默。由你选稳妥方案，但必须新增断言：
  - 401 后 `sessionStorage.getItem('fh_auth_from')` 为调用时的 pathname+search（mock location pathname 为 '/settings'）
  - `window.location.href` 被赋值为 '/login'
  - pathname 已是 '/login' 时不写 sessionStorage
- 测试后恢复 location（afterEach restore）
- `login()` 的 401 用例断言不变（口令错误、不写 fh_auth_from）

### 10. `pages/__tests__/CalendarPage.test.jsx` — 新增错误态用例

新增：
- 「加载失败显示 ErrorState 且不渲染日历网格」：mock api reject → 出现 `calendar-error` testId、`role="alert"`；`day-` 开头的 testId 数量为 0；图例文字"自动匹配"不存在
- 「错误态点击重试重新发起请求」：点击 ErrorState 的"重试"按钮后 api 被再次调用
- 既有 5 个用例保持通过（注意：loading 期现在渲染 Skeleton 网格而非"加载中…"，若有断言涉及请适配）

### 11. ✱ `pages/__tests__/LoginPage.test.jsx`

- 渲染：口令 label + 输入框 + 登录按钮
- 无 state 无 sessionStorage 时登录成功跳 '/'（mock `login` 返回 `{token:'t'}`，用 MemoryRouter + Routes 断言路由变化，或 mock useNavigate）
- `location.state.from = { pathname: '/trends', search: '' }` 时登录成功跳 '/trends'（MemoryRouter initialEntries 带 state）
- sessionStorage 有 'fh_auth_from' = '/body-metrics' 且无 state 时跳 '/body-metrics'，且 sessionStorage 键被清除
- 401（login reject ApiError(401)）显示"口令错误"且不跳转
- 按钮含 `min-h-[44px]`、输入框含 `min-h-[44px]`、根容器含 `min-h-dvh`

## 关键决策点（默认方案 + 理由）

1. **401 跳转用 `window.location.href` 硬跳转而非 React navigate**：client.js 是非 React 模块，硬跳转简单可靠（整页刷新清状态）；jsdom 兼容（href 赋值不抛异常）。sessionStorage 传递回跳目标（硬跳转丢不了 storage，React state 会丢）。
2. **日历 loading 用骨架网格而非 Spinner**：保持布局稳定（原实现加载时日历消失重排）；35 格 Skeleton 直观预示日历形态。
3. **安全区用 `pb-[max(0.75rem,env(safe-area-inset-bottom))]` 而非纯 env 值**：无安全区设备上保持原 12px padding，全面屏设备取较大值。
4. **modal 只修 z-index/宽度/安全区/role**：不迁移到 ConfirmDialog（sync-modal 有异步确认逻辑、preference-modal 是表单，语义都不是"确认对话"；统一模态基建留待后续切片评估）。
5. **`login()` 的 401 不走统一拦截**：口令错误是表单校验反馈，跳转会形成死循环。

## 验收标准（审核方执行，你不跑）

1. `git status --short`：仅预算内 11 个文件
2. `cd frontend && npx vitest run`：全量通过（347 基线 + 新增用例，不回退）
3. `cd frontend && npm run lint`：无新增告警（基线仅 SettingsPage 一处存量）
4. `cd frontend && npm run build`：通过
5. 目检：sync-modal/preference-modal 的 data-testid 未变；`login()` 401 行为未动

## 交付报告模板（最终回复必须包含）

1. 完成内容摘要
2. 文件清单（新增/修改，逐个路径）
3. 越界自检
4. 关键决策 5 条逐条确认或说明偏差
5. 测试用例清单（新增/修改的用例名）
6. 遗留问题 / 给 UIX-03（页面迁移）的注意事项
7. 编码红线自查（无 BOM / 无分号风格 / 无新依赖 / 未跑验收命令 / 未动 login() 401）
8. 对验收标准 1-5 的预期自评

按本提示词直接执行（headless 无人工确认）：先输出实施计划，然后动手，最终回复给出完整交付报告。
