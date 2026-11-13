# ADR-P2-7 编辑弹窗：Garmin 动作改成「列表选择」而非盲输

> 你是本仓库的资深前端工程师（React 19 + Vite + Vitest + Tailwind）。
> 本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（vitest / build / lint 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须无 BOM、UTF-8；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 需求背景

用户反馈：

> 在编辑动作的时候，Garmin Category 那里可以选，但是到具体动作又变成了输入。
> 输入的话，我哪知道 Garmin 里面有哪些动作名称呢？

现状（已核实）：编辑弹窗里**其实有搜索框**（`edit-exercise-search`，
placeholder「搜索英文名或枚举名」），但它有一个致命行为：

```js
const q = exerciseQuery.trim()
if (!q) {
  setExerciseResults([])     // ← 不输入就什么都不显示
  return undefined
}
```

于是用户打开弹窗看到的是一个**空搜索框 + 一个下拉分类**，
完全不像"可以选"，只会以为"要自己手输英文名"，而多数人并不知道
Garmin 的动作叫 `NEUTRAL_GRIP_DUMBBELL_BENCH_PRESS` 这种名字。

**后端早就支持**：`GET /api/exercise-mappings/catalog?category=BENCH_PRESS`
传空 `q` 时会返回**该分类全部条目**（`limit` 上限 100，分类最大 131 条）。

本片把「盲输」改成「列表选择」。

## 已核实的关键事实（实读代码，可直接采信）

- `frontend/src/pages/ExerciseMappingsPage.jsx`
  - 编辑弹窗已有：分类 `<select data-testid="edit-category">`、
    动作搜索 `<input data-testid="edit-exercise-search">`、
    结果列表 `<li><button data-testid={\`edit-exercise-result-${index}\`} onClick={() => pickExercise(row)}>`、
    「当前：<枚举名> · <显示名>」一行 + 「清空动作」按钮、
    `<select data-testid="edit-weight-strategy">`、`<textarea data-testid="edit-reason">`
  - 搜索 effect（约第 250-282 行）：`if (!q) { setExerciseResults([]); return }` 是本次要改的核心；
    请求 `GET /api/exercise-mappings/catalog?q=&limit=30&category=<分类>`，防抖 250ms
  - state：`exerciseQuery` / `exerciseResults` / `exerciseSearching` / `editForm.garmin_category`
  - `pickExercise(row)` 把选中的条目写入 `editForm`
- `GET /api/exercise-mappings/catalog` 返回 `[{"category","exercise","name"}]`，
  `limit` 会被后端钳到 100；不传 `q` 时不按关键词过滤
- Garmin 目录共 1527 条 / 47 分类；最大分类 `PLANK` 131 条、`SQUAT` 98、`LUNGE` 91
- 前端测试基线：**56 文件 / 503 用例全部通过**（改动后不得低于此数）
- `npm run lint` = `oxlint`

## 文件预算（共 2 个，不得越界）

改 1：
1. `frontend/src/pages/ExerciseMappingsPage.jsx`

新增 1：
2. `frontend/src/pages/__tests__/ExerciseMappingsExercisePicker.test.jsx`

**禁止修改**：任何 `backend/**`、`frontend/src/api/**`、其它组件、路由、既有测试文件、`.env`。

## 开发内容

### 1. 打开弹窗即加载该分类的动作列表

把搜索 effect 改为两条路径：

```
只要弹窗打开（editingId != null）且分类非空：
  · q 为空  → 请求 /catalog?limit=100&category=<分类>（列出该分类全部）
  · q 非空  → 请求 /catalog?q=<q>&limit=100&category=<分类>（在分类内搜索）
分类为空 → 清空列表，并展示引导文案（见下）
```

要点：

- `limit` 用 **100**（后端上限），分类最大 131 条 → 超出的在列表底部提示
  「已显示前 100 条，可用搜索缩小范围」
- 防抖保留 250ms；`q` 为空时也走同一 effect（不要提前 return）
- 切换分类自动重新加载（effect 依赖里已有 `editForm?.garmin_category`）
- `exerciseSearching` 期间列表区显示「加载中…」而不是空白

### 2. 列表区改造

**标题与引导**（放在搜索框上方或列表上方，任选一处即可）：

```
Garmin 动作（{count} 条）        ← 数量；搜索时为「搜索结果（N 条）」
从下面点选即可，不需要手输英文名
```

**每个条目**显示：`name`（英文显示名）为主，`exercise`（枚举名）用 `font-mono text-xs` 作副标题。
**当前已选中的条目**加高亮（`bg-brand-50 dark:bg-brand-950/40`）+ 右侧「当前」小标签，
且点击它仍然允许（幂等，无害）。

**空态处理**：

| 情况 | 展示 |
|---|---|
| 分类为空 | 「请先选择 Garmin Category，下面会列出该分类下的全部动作」 |
| 分类有值、加载中 | 「加载中…」 |
| 分类有值、结果为空（搜索无匹配） | 「该分类下没有匹配的动作，试试更短的关键词或清空搜索」 |

**保留**现有「当前：<枚举名> · <显示名>」一行与「清空动作」按钮不变。

### 3. 搜索框提示语调整

placeholder 改为：`可按英文名/枚举名筛选（留空则列出该分类全部）`。
`data-testid="edit-exercise-search"` **保持不变**（既有测试依赖它）。

### 4. `ExerciseMappingsExercisePicker.test.jsx`（新，≥8 例）

**照抄 `frontend/src/pages/__tests__/ExerciseMappingsPage.test.jsx` 的
`routeFetch` / `defaultRoutes` / `renderPage` 写法**（先读它，不要自创另一套）：

1. `test_lists_category_actions_without_typing` —— 打开编辑（不输入任何搜索词）→
   请求了 `/catalog?` 且带 `category=`，列表渲染出条目（不是空态）
2. `test_shows_count_and_hint` —— 出现「Garmin 动作（N 条）」与「不需要手输英文名」
3. `test_typing_filters_within_category` —— 输入关键词后请求带 `q=` 且仍带 `category=`
4. `test_click_item_fills_exercise` —— 点列表条目后「当前：」一行显示该枚举名
5. `test_current_item_highlighted` —— 与当前 `garmin_exercise_name` 相同的条目带「当前」标记
6. `test_empty_category_shows_guidance` —— 分类为空时显示「请先选择 Garmin Category」
7. `test_changing_category_reloads` —— 切换分类后重新发起 `/catalog?` 请求且 `category=` 为新值
8. `test_truncation_hint_when_full_page` —— mock 返回 100 条时出现
   「已显示前 100 条，可用搜索缩小范围」

## 自报告要求（交付时必须给出）

1. 改动文件清单（对照预算 2 个），每个文件改动行数与函数/组件名。
2. **改后的搜索 effect 全文**（贴出来，便于确认 `q` 为空时不再提前 return）。
3. **四种空态的实测**：分别截图或贴出文本 —— 分类为空 / 加载中 / 搜索无匹配 / 正常列表。
4. 一次完整交互：打开某 draft 动作 → 不输入 → 列表出现 N 条 → 点一条 →「当前：」变化。
5. 设计取舍：
   - 为什么 `q` 为空也要请求（而不是靠前端缓存全量）
   - 为什么 `limit` 用 100 且要显示截断提示
   - 为什么当前项仍可点击
   - 为什么保留既有的 `data-testid`（不重命名）
6. 确认清单：
   - 未跑 vitest / build / lint
   - 未执行 git
   - 未改 `backend/**`、`frontend/src/api/**`、其它组件、路由、既有测试文件、`.env`
   - 文件无 BOM、UTF-8
7. 行为自检清单：
   - [ ] 打开弹窗、不输入任何东西也能看到该分类的动作列表
   - [ ] 列表显示数量与「不需要手输」的引导
   - [ ] 搜索在分类内过滤，不会串到别的分类
   - [ ] 当前选中项有「当前」标记
   - [ ] 分类为空 / 加载中 / 无匹配 三种空态都有明确文案
   - [ ] 切换分类自动刷新列表
   - [ ] 未改动后端

## 明确不做

- 不改后端（`/catalog` 已支持空 `q` + `category`）
- 不做中文/拼音搜索（需要额外的语义映射，另议）
- 不做分页（用搜索缩小范围即可，配合截断提示）
- 不改列表页与其它弹窗
