# UIX-05 切片开发提示词：交互修复包 — 聊天乐观上屏 / 上传过程反馈 / 截图防误清 / Toast 统一接入

> 你是本仓库的前端工程师（React 19 + Tailwind CSS 4 + Vitest）。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（vitest / lint / build 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须 UTF-8 无 BOM、LF 行尾；代码风格无分号、单引号、2 空格、中文注释；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件；**禁加任何新依赖**。

## 需求（UI/UX 审计 · 第二期 P1 交互组）

UIX-01 原语层、UIX-03/04 页面迁移已完成（Button/Card/ErrorState/EmptyState/ConfirmDialog/Toast 可用，`useToast` 在 `frontend/src/components/ui/useToast.js`）。本切片修复四个 P1 交互缺陷 + 落地 Toast：

1. **聊天发送失败后消息不回显**（`CoachChatPage.jsx:54-64`、`ReportChatSection.jsx:58-71`）：`doSend` 仅成功时上屏用户气泡，失败时线程无痕迹，只有一行红字 + 22px 重试按钮
2. **上传/AI 识别零过程反馈**（`ScreenshotImportPage.jsx:336-343`、`FitImportPage.jsx:100-107`、`BodyImageImport.jsx`）：只有按钮文字变"识别中…"，AI 识别 10s+ 用户易误判卡死
3. **重新选图静默清空已编辑卡片**（`ScreenshotImportPage.jsx:230-235`）：`addFiles` 无条件 `setCards([])`，补传图即丢全部校对成果
4. **成功反馈四种形态并存**：本地 `role=status` 绿字有的常驻有的 3s 消失 → 统一 Toast

同时顺手清：聊天无时间戳、输入框固定行高、清空对话 window.confirm、`💬` emoji、"拖拽到此处"移动端文案、`text-gray-400/500` 对比度（仅本组文件）。

**本切片不碰**：导航/底部 Tab（UIX-06）、tokens/成本元信息折叠（UIX-06）、导入三页聚合 IA（UIX-06）、图表（UIX-07）。

## 已核实的关键事实（实读代码，可直接采信）

- `CoachChatPage.jsx`：`doSend(text, requestId)` 成功 `setMessages(prev => [...prev, data.user_message, data.assistant_message])`、失败 `setFailed({ text, requestId })`（行 47-64）；`failed` 态渲染在行 187-202（裸 `rounded border px-2 py-0.5` 重试按钮，testid `chat-retry`）；`metaLine(m)`（行 96-107）只拼 tokens/成本，**消息对象有 `created_at` 字段未展示**（行 26 sort 用了 created_at）；输入区行 204-224（UIX-02 已加安全区 pb）；textarea `rows={3}`（行 210）；发送按钮 green-600（行 220，testid `chat-send`）；清空按钮 `bg-red-600` 实心（行 116-123，testid `chat-clear-btn`）+ `window.confirm`（行 78）；`chat-empty` 行 132-139；服务端幂等靠 `client_request_id`（重试复用同一 id 不会重复调 LLM，见文件头注释）
- `ReportChatSection.jsx`：同构（行 54-71 doSend、行 169-184 error+retry、行 192 rows={2}、行 202 green-600 testid `chat-send`、行 99-102 展开按钮含 `💬` emoji testid `chat-expand-btn`、行 128 `text-xs text-gray-400` memory-hint）；无清空功能
- `ScreenshotImportPage.jsx`：行 230-235 `addFiles` 无条件 `setCards([])`；卡片有 `confirmed`/`confirming`/`data`（行 244-252）——"已编辑"指 `cards.length > 0`；行 303-323 drop-zone 文案"拖拽截图到此处…"（testid `drop-zone`）；行 336-343 识别按钮（testid `extract-btn`）；识别结果卡片失败态（ok=false）在行 355-364 附近无操作入口；files 列表行 325-334 无单项删除；`useIsMobile` hook 存在（`src/hooks/useIsMobile.js`）
- `FitImportPage.jsx`：行 73-92 drop-zone "拖拽 FIT/TCX/GPX/KML 文件到此处…"（testid `drop-zone`）；行 100-107 导入按钮（testid `import-btn`）；成功结果卡 green-50 保留
- `BodyImageImport.jsx`：行 102/305 附近 drop-zone、行 120-122 识别按钮、行 146 指标表格无 `overflow-x-auto`（对比 SettingsPage 有）；上传反馈同样只有按钮文字
- `BackfillPage.jsx`：已有进度条（行 121-139）保留；行 95 按钮；状态行"整体状态/阶段"重复展示同一 phase（行 107-149）
- `Layout.jsx`：行 76-138 结构已知（`min-h-screen bg-gray-50` + header + main + BottomTabs），挂 ToastProvider 的注入点；`useToast()` 返回 `{ toast(message, type) }`，type `'success'|'error'|'info'`，3s 自动消失
- 本地成功消息三处：`SyncButton.jsx:85`（同步完成绿字常驻）、`ReviewsPage.jsx:187-191`（复盘生成完成/已存在绿字常驻）、`PlansPage.jsx:202`（计划缓存已刷新 role=status 常驻）
- `LoginPage` 品牌视觉属第四期，本切片不做

## 文件预算（共 11 个 + 测试，不得越界）

1. 改 `frontend/src/pages/CoachChatPage.jsx`
2. 改 `frontend/src/components/ReportChatSection.jsx`
3. 改 `frontend/src/pages/ScreenshotImportPage.jsx`
4. 改 `frontend/src/pages/FitImportPage.jsx`
5. 改 `frontend/src/components/BodyImageImport.jsx`
6. 改 `frontend/src/pages/BackfillPage.jsx`（仅按钮→Button、状态行去重）
7. 改 `frontend/src/components/Layout.jsx`（仅挂 ToastProvider）
8. 改 `frontend/src/components/SyncButton.jsx`（成功消息→toast）
9. 改 `frontend/src/pages/ReviewsPage.jsx`（成功消息→toast）
10. 改 `frontend/src/pages/PlansPage.jsx`（refreshMsg 成功→toast）
11. 改对应测试文件（CoachChatPage/ReportChatSection/ScreenshotImportPage/FitImportPage/BackfillPage/Layout/SyncButton/ReviewsPage/PlansPage 的既有 test.jsx）

## 开发内容

### 1-2. 聊天乐观上屏（CoachChatPage + ReportChatSection 同模式）

**乐观上屏协议**（两边一致）：
- `handleSend` 时构造临时消息 `{ id: \`pending-${requestId}\`, role: 'user', content: text, pending: true }` 立即 append 到 messages，并清空输入框（原文保留在变量里供失败重试）
- 成功：用服务端 `user_message` + `assistant_message` **替换**该临时消息（按 id 匹配）
- 失败：临时消息标记为 `{ ...msg, pending: false, failed: true }` 保留在线程中，同时 `setFailed({ text, requestId, tempId })`
- 失败气泡样式：用户气泡改 `border-2 border-red-300 bg-indigo-600/70`，气泡正下方一行 `flex items-center justify-end gap-1.5 text-xs text-red-600`：感叹号 svg + "发送失败" + `<button data-testid="chat-retry" className="min-h-[36px] rounded-lg px-2 font-medium underline">重试</button>`（重试走 `doSend(failed.text, failed.requestId)` 并把该 tempId 恢复 pending）
- 线程底部的全局 error 红字（行 187-202 / 169-184）**删除**，失败信息完全由气泡承担；非发送类错误（加载历史失败）保留 error state 但用 ErrorState 组件渲染
- pending 气泡样式：`opacity-70`，不加其他标识

**时间戳**：`metaLine(m)` 改为 `metaLine(m, isUser)`——前缀加时间：`created_at` 存在时格式化为"今天 HH:mm"（当天）或"MM-dd HH:mm"（非当天），与 tokens/成本用 ` · ` 连接；无 created_at 时行为同今。**tokens/成本展示保留不动**（UIX-06 统一折叠）。`text-gray-400` → `text-gray-600`（两处 meta 行 + memory-hint）。

**输入框自适应高度**：textarea `rows={3}`/`rows={2}` 改自适应：`onInput` 中 `e.target.style.height = 'auto'; e.target.style.height = Math.min(e.target.scrollHeight, 6 * 24) + 'px'`，初始 `rows={1}`，类名加 `max-h-36 min-h-[44px]`（发送成功后重置 height）。

**CoachChatPage 独有**：
- 清空对话：`window.confirm` → ConfirmDialog（danger，title "清空所有对话？"，description "此操作不可恢复，与教练的聊天记录将被删除。"）；清空按钮 → `<Button variant="danger" testId="chat-clear-btn">`
- 发送按钮 green-600 → `<Button variant="primary" testId="chat-send">`（ReportChatSection 同）
- `chat-empty` → `<EmptyState title="跟教练说点什么吧" description="比如「我深蹲时膝盖疼，下周训练怎么调？」" />` 居中（保留 testid `chat-empty` 在 EmptyState 上）
- 加载中 → 3 个气泡状 Skeleton

**ReportChatSection 独有**：
- 展开按钮去 `💬` emoji → 内联线性 svg 对话图标（stroke currentColor，参照 BottomTabs 的 ChatIcon path）+ "追问 AI 教练"，样式保留 indigo dashed 但补 `min-h-[44px]`

### 3. `ScreenshotImportPage.jsx`

- **防误清**：`addFiles` 中若 `cards.length > 0` → 先打开 ConfirmDialog（danger，title "重新选择图片？"，description `已有 ${cards.length} 张截图的识别结果，其中已确认的进度不会保留。` confirmText "丢弃并重选"），确认后才执行原逻辑（含 setCards([])）；取消则不动。用 `pendingFilesRef` 暂存 fileList
- **识别过程反馈**：`extracting` 时在识别按钮下方渲染进度区块（testid `extract-progress`）：`rounded-xl bg-gray-50 p-3` 内含 ① 一行 `text-xs font-medium text-gray-700`："正在识别 N 张截图…" ② 不定态进度条（`h-2 w-full overflow-hidden rounded-full bg-gray-200` 内 `<div className="h-full w-1/3 animate-pulse rounded-full bg-indigo-600">`）③ `text-xs text-gray-600`："AI 识别中，通常需要 10–20 秒，请耐心等待"
- **分端文案**：drop-zone 文案用 `useIsMobile()`：移动端"点击选择截图（可多选，最多 N 张）"，桌面端保留"拖拽截图到此处，或点击选择文件（可多选，最多 N 张）"
- 识别按钮 → `<Button variant="primary" testId="extract-btn">`
- 失败卡片（ok=false）行 355-364：加 `<Button variant="ghost" onClick={移除该卡片}>移除</Button>`
- files 列表每项加"移除"小按钮（`min-h-[36px] text-red-600`），仅移除该文件
- `text-gray-400`（KB 数）→ `text-gray-600`；drop-zone `text-gray-500` → `text-gray-600`

### 4. `FitImportPage.jsx`

- 导入中反馈：同 §3 的不定态进度区块（testid `import-progress`，文案"正在解析并导入文件…""通常需要几秒到几十秒"）
- 分端文案：移动端"点击选择 FIT/TCX/GPX/KML 文件"，桌面端保留原文案
- 导入按钮 → `<Button variant="primary" testId="import-btn">`；drop-zone `text-gray-500` → `text-gray-600`

### 5. `BodyImageImport.jsx`

- 识别按钮 ×2 → Button primary；上传过程反馈同 §3 模式（文案"AI 识别中…"）
- 分端文案同 §3
- 行 146 指标表格容器加 `overflow-x-auto`（窄屏溢出修复）
- `text-gray-400`/`text-gray-500` → `text-gray-600`

### 6. `BackfillPage.jsx`

- 按钮 → Button primary（行 95）
- 状态行去重："整体状态"与"阶段"展示同一 phase 时，合并为一行"阶段：{phase}"（保留 testid 不破坏测试）

### 7-10. Toast 统一接入

- `Layout.jsx`：`<ToastProvider>` 包住 `<Outlet />`（main 内或整个 layout 内层均可，保证 useToast 在页面组件可用）；import 路径 `../components/ui/Toast`（Provider）——注意 Provider 与 hook 分文件：`import { ToastProvider } from './ui/Toast'`（Layout 在 components 目录，路径 `./ui/Toast`）
- `SyncButton.jsx`：成功 `setToast(...)` → `const { toast } = useToast()` + `toast(\`同步完成：训练 X 条，待确认 Y 条\`)`；删除本地 toast state 与行 85 渲染；error 保留 role=alert 行内（错误要持久可见）
- `ReviewsPage.jsx`：`'复盘生成完成'`/`'该周期复盘已存在'` → toast（后者 type 'info'）；删除本地 toast state 与渲染
- `PlansPage.jsx`：`'计划缓存已刷新'` → toast；refreshMsg 的错误文案保留行内 role=status 不动

### 11. 测试适配

- CoachChatPage/ReportChatSection 测试：发送失败用例改断言"失败气泡出现（border-red-300）+ chat-retry 在气泡旁"；乐观上屏断言"发送后输入框立即清空 + pending 气泡 opacity-70"；既有 testid（chat-msg-user-*、chat-send、chat-retry 等）保持可用
- ScreenshotImportPage 测试：新增"已有卡片时重选文件弹确认框，取消则卡片保留"用例
- Layout 测试：渲染含 ToastProvider 不破坏既有断言（toast-container 在文档中）
- SyncButton/ReviewsPage/PlansPage 测试：成功路径断言 toast-container 内出现对应文案（需包 ToastProvider 渲染或在 Layout 内渲染，按各测试现状选最简方式）

## 关键决策点（默认方案 + 理由）

1. **乐观上屏用临时消息 + 幂等 id 替换**：服务端已有 client_request_id 幂等机制，重试天然安全；临时消息 id 前缀 `pending-` 便于匹配替换，不回退服务端契约。
2. **失败重试入口放气泡旁而非线程底部**：审计核心——失败的消息必须可见可重发；全局 error 条删除避免双份噪音。
3. **进度反馈用不定态动画条**：后端无分阶段进度 API，不定态（indeterminate）+ 预期时长文案是当前契约下的最优解；不编造百分比。
4. **错误行内、成功上 Toast**：错误需要持久可见+重试入口；成功是瞬时确认——这是全站统一原则（写入 index.css 约定的延伸）。
5. **防误清阈值是 cards.length > 0 而非"有已确认"**：识别结果本身就是用户劳动（哪怕未确认），一律确认后再清。

## 验收标准（审核方执行，你不跑）

1. `git status --short`：仅预算内文件
2. `cd frontend && npx vitest run`：全量通过，无回退
3. `cd frontend && npm run lint`：无新增告警
4. `cd frontend && npm run build`：通过
5. 目检抽查：本组文件 `grep "window.confirm"` = 0；`grep "💬"` = 0；`grep "bg-green-600"` 按钮 = 0；`grep "text-gray-400"` 本组 = 0

## 交付报告模板（最终回复必须包含）

1. 完成内容摘要
2. 文件清单（新增/修改，逐个路径）
3. 越界自检
4. 关键决策 5 条逐条确认或说明偏差
5. 测试用例清单（新增/修改用例名）
6. 遗留问题 / 给 UIX-06（第三期 IA）的注意事项
7. 编码红线自查（无 BOM / 无分号风格 / 无新依赖 / 未跑验收命令）
8. 对验收标准 1-5 的预期自评

按本提示词直接执行（headless 无人工确认）：先输出实施计划，然后动手，最终回复给出完整交付报告。
