# ADR-P2-6 前端接入 AI 审核（行内「AI 审核」按钮 + 结果面板）

> 你是本仓库的资深前端工程师（React 19 + Vite + Vitest + Tailwind）。
> 本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（vitest / build / lint 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须无 BOM、UTF-8；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 需求背景

AI 只读审核（ADR-P2-2 / P2-5）已验证可用且不会幻觉，但**只有 API，没有界面**——
用户遇到不确定的映射时必须开终端跑 `curl`，实际用不起来。

本片把「问 AI」变成**行内一个按钮**：点一下 → 后端审这一条 → 结果就地展开，
有更优建议时一键预填编辑表单。

**后端接口（已就绪，直接用）**：

```
POST /api/exercise-mappings/review?xunji_name=<动作名>
  → {requested, processed, batches, by_verdict, rejected_suggestions,
     prompt_tokens, completion_tokens, batch_id}

GET /api/exercise-mappings/reviews?batch_id=<batch_id>
  → {items: [{id, xunji_name, verdict, suggested_category, suggested_exercise_name,
              reason, model, batch_id, resolved, created_at}]}
```

`verdict` 五种取值：
`current_ok` / `better_candidate` / `suspected_error` / `likely_unmapped` / `needs_human`

## 已核实的关键事实（实读代码，可直接采信）

- `frontend/src/api/client.js` 导出 `api(path, options)`（返回解析后的 JSON）、
  `ApiError`（含 `.status` / `.detail`）
- `frontend/src/pages/ExerciseMappingsPage.jsx`（约 800 行）
  - 行操作按钮区（约第 690-720 行）现有三个：`编辑` / `采纳` / `停用`，
    都用共享 `Button` 组件，带 `testId` 属性（如 `mapping-edit-${row.id}`）
  - `setBusy(id, busy)` + `rowBusy` state 控制单行 loading
  - `toast(message, type)` 与 `errorMessage(err)`（第 110 行）用于反馈
  - `openEdit(row)` 打开编辑弹窗，`setEditForm({xunji_name, garmin_category,
    garmin_exercise_name, garmin_display_name, weight_strategy, reason})`
  - `loadList()` / `loadCoverage()` 刷新数据
- 前端测试基线：**54 文件 / 487 用例全部通过**（改动后不得低于此数）
- `npm run lint` = `oxlint`

## 文件预算（共 4 个，不得越界）

改 1：
1. `frontend/src/pages/ExerciseMappingsPage.jsx`

新增 3：
2. `frontend/src/components/AiReviewPanel.jsx`
3. `frontend/src/components/__tests__/AiReviewPanel.test.jsx`
4. `frontend/src/pages/__tests__/ExerciseMappingsAiReview.test.jsx`

**禁止修改**：任何 `backend/**`、`frontend/src/api/**`、路由、既有测试文件、`.env`。

## 开发内容

### 1. `AiReviewPanel.jsx`（新组件）

```jsx
export default function AiReviewPanel({ review, onApply, busy = false })
```

`review` 为 `GET /reviews` 返回的单条 item。渲染规则：

| verdict | 徽标文案 | 配色 | 额外内容 |
|---|---|---|---|
| `current_ok` | 当前映射合理 | 绿 `bg-emerald-100 text-emerald-700` | 只显示理由（若有） |
| `better_candidate` | 有更优候选 | 蓝 `bg-sky-100 text-sky-800` | 显示 `当前 → 建议`（建议显示为 `category/exercise_name`），加「应用建议」按钮 |
| `suspected_error` | 疑似错误 | 红 `bg-rose-100 text-rose-700` | 若有建议同样显示 `→ 建议` + 「应用建议」 |
| `likely_unmapped` | 可能无对应 | 琥珀 `bg-amber-100 text-amber-800` | 只显示理由 |
| `needs_human` | 需要你判断 | 灰 `bg-gray-100 text-gray-700` | 只显示理由 |

要求：

- 建议内容用等宽小字（`font-mono text-xs`）显示，便于核对
- 「应用建议」按钮：`testId="ai-review-apply"`，点击调 `onApply({category, exercise_name})`；
  **仅当 `suggested_exercise_name` 非空时渲染**
- 理由用 `<p>` 展示，过长时不做截断（让用户能看全）
- 组件根节点带 `data-testid="ai-review-panel"` 与 `data-verdict={verdict}`
- **不引入任何请求**（纯展示组件），所有数据由父组件传入

### 2. `ExerciseMappingsPage.jsx` 集成

#### 2.1 行内按钮

在「编辑」按钮**之前**插入：

```jsx
<Button
  variant="secondary"
  size="compact"
  testId={`mapping-ai-review-${row.id}`}
  disabled={busy || reviewBusy[row.id]}
  onClick={() => handleAiReview(row)}
>
  {reviewBusy[row.id] ? '审核中…' : 'AI 审核'}
</Button>
```

#### 2.2 状态与处理函数

```jsx
const [reviewBusy, setReviewBusy] = useState({})   // id -> bool
const [reviewsByRow, setReviewsByRow] = useState({})  // id -> review item
```

```jsx
const handleAiReview = async (row) => {
  const id = row.id
  setReviewBusy((prev) => ({ ...prev, [id]: true }))
  try {
    const started = await api(
      `/api/exercise-mappings/review?xunji_name=${encodeURIComponent(row.xunji_name)}`,
      { method: 'POST' },
    )
    const batchId = started?.batch_id
    if (!batchId) {
      toast('审核未产生结果', 'error')
      return
    }
    const payload = await api(`/api/exercise-mappings/reviews?batch_id=${batchId}`)
    const item = (payload?.items || []).find((it) => it.xunji_name === row.xunji_name)
    if (!item) {
      toast('审核未返回该动作的结果', 'error')
      return
    }
    setReviewsByRow((prev) => ({ ...prev, [id]: item }))
    if (item.verdict === 'current_ok') {
      toast('AI 认为当前映射合理')
    }
  } catch (err) {
    toast(errorMessage(err), 'error')
  } finally {
    setReviewBusy((prev) => ({ ...prev, [id]: false }))
  }
}
```

#### 2.3 应用建议

```jsx
const handleApplyReview = (row, suggestion) => {
  openEdit(row)
  setEditForm((prev) => prev && ({
    ...prev,
    garmin_category: suggestion.category || prev.garmin_category,
    garmin_exercise_name: suggestion.exercise_name || prev.garmin_exercise_name,
  }))
  toast('已填入 AI 建议，请确认后保存')
}
```

> 注意：`openEdit` 是异步加载详情的（内部会覆盖 `editForm`）。
> **必须确认覆盖顺序**：如果 `openEdit` 内部 `await api(...)` 后再 `setEditForm(...)`，
> 上面的同步预填会被详情响应覆盖。**先读 `openEdit` 的实现**再决定写法——
> 可选方案：给 `openEdit` 加一个可选的 `preset` 参数，在它自己的 `setEditForm` 之后应用；
> 或把建议暂存到 state，在 `editForm` 就绪后再填。**不要留下"看起来填了但被覆盖"的 bug。**

#### 2.4 行内展示

在该行内容区（现有的徽标/文案之后、操作按钮之前或之后均可，选一个不破坏现有布局的位置）
渲染：

```jsx
{reviewsByRow[row.id] && (
  <AiReviewPanel
    review={reviewsByRow[row.id]}
    busy={busy}
    onApply={(sug) => handleApplyReview(row, sug)}
  />
)}
```

布局要求：占满该行宽度、与既有内容有明确间距、不挤压操作按钮。

### 3. `AiReviewPanel.test.jsx`（新，≥8 例）

纯组件测试（不需要 mock 请求）：

1. `test_current_ok_badge` —— `current_ok` 显示「当前映射合理」，**不渲染**「应用建议」按钮
2. `test_better_candidate_shows_suggestion` —— 显示「有更优候选」与
   `BENCH_PRESS/NEUTRAL_GRIP_DUMBBELL_BENCH_PRESS`
3. `test_better_candidate_apply_calls_back` —— 点「应用建议」→ `onApply` 收到
   `{category, exercise_name}`
4. `test_suspected_error_badge` —— 「疑似错误」
5. `test_likely_unmapped_badge` —— 「可能无对应」
6. `test_needs_human_badge` —— 「需要你判断」
7. `test_reason_rendered` —— 理由文本出现在页面上
8. `test_apply_button_hidden_without_suggestion` —— `suggested_exercise_name` 为空时不渲染按钮

### 4. `ExerciseMappingsAiReview.test.jsx`（新，≥6 例）

走页面测试，**照抄 `frontend/src/pages/__tests__/ExerciseMappingsRelation.test.jsx`
的 fetch mock 与 render 方式**（先读它，不要自创）：

1. `test_ai_review_button_rendered` —— 每行有「AI 审核」按钮
2. `test_click_triggers_review_calls` —— 点击后依次请求了
   `/review?xunji_name=` 与 `/reviews?batch_id=`
3. `test_result_panel_shown` —— mock 返回 `better_candidate` → 行内出现面板与建议
4. `test_current_ok_only_toasts` —— mock 返回 `current_ok` → 不渲染面板外的建议按钮
   （或断言面板显示「当前映射合理」且无「应用建议」）
5. `test_apply_prefills_edit_form` —— 点「应用建议」后编辑弹窗里
   `garmin_exercise_name` 被填成建议值
6. `test_review_error_shows_toast` —— `/review` 返回 422/500 → 出现错误提示，
   且不影响其它行

## 自报告要求（交付时必须给出）

1. 改动文件清单（对照预算 4 个），每个文件改动行数与组件/函数名。
2. **`openEdit` 的原始实现**（贴出来）以及你如何避免「预填被详情响应覆盖」。
3. **verdict → 文案/配色对照表**（贴出实现里的映射对象）。
4. **一次完整交互的实测**：贴出点击「AI 审核」后发出的两个请求的 URL，
   以及面板渲染出的 verdict / 建议 / 理由。
5. 设计取舍：
   - 为什么 `AiReviewPanel` 保持纯展示、不发请求
   - 为什么 `current_ok` 只弹 toast 但仍渲染面板
   - 为什么「应用建议」只预填、不自动保存
   - 请求失败时为什么不回滚该行状态
6. 确认清单：
   - 未跑 vitest / build / lint
   - 未执行 git
   - 未改 `backend/**`、`frontend/src/api/**`、路由、既有测试文件、`.env`
   - 文件无 BOM、UTF-8
7. 行为自检清单：
   - [ ] 每行有「AI 审核」按钮，点击期间该行显示「审核中…」且按钮禁用
   - [ ] 请求只带当前行的 `xunji_name`（不是整表）
   - [ ] 五种 verdict 都有明确不同的呈现
   - [ ] 无建议时「应用建议」按钮不渲染
   - [ ] 点「应用建议」能把值填进编辑弹窗（且不被详情响应覆盖）
   - [ ] 出错时只 toast，不影响其它行
   - [ ] 未改动后端与既有测试

## 明确不做

- 不改后端（接口已就绪）
- 不做批量 AI 审核按钮（一次审一行，避免误点产生大量花费）
- 不自动采纳 AI 建议（必须人工确认后保存）
- 不做审核历史列表页（`GET /reviews` 已有的查询留给以后）
- 不改路由
