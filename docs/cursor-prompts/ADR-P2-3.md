# ADR-P2-3 前端可见性：relation 维度 + 部分同步缺口 + 有损标记

> 你是本仓库的资深前端工程师（React 19 + Vite + Vitest + Tailwind）。
> 本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（vitest / build 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须无 BOM、UTF-8；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 需求背景

ADR 的多处条款要求「可见」，但后端已交付、前端尚未呈现：

- **§4.1**：`relation` 是独立维度（EXACT/SIMILAR/CATEGORY/UNMAPPED），必须能在管理页看到并筛选；
- **§5.2 / §13**：`SIMILAR` / `CATEGORY` 是**有损映射**，必须持续可见，不能被展示成精确匹配；
- **§6.5**：Garmin 显示为笼统类目是可接受但有损的结果，必须在映射页可见；
- **§7.2**：部分同步的缺口必须在**预览**与**本地记录**中可见，不得只给一条泛化警告；
- **§10.1**：`decision_source='human_policy'` **不得**展示成「用户已逐条语义确认」。

后端已就绪的接口与字段（可直接使用）：

| 接口 | 新增/相关字段 |
|---|---|
| `GET /api/exercise-mappings`（列表） | 每项已含 `relation` / `match_basis` / `unmapped_reason` / `decision_source` |
| `GET /api/exercise-mappings/coverage` | `by_status` / `by_confidence` / `by_verified_level` / `coverage` |
| `GET /api/plans/{day}/garmin/preview` | 成功时含 `excluded`（正常排除）；422 时 `detail` 含 `issues` / `excluded` / `skipped` |
| `GET /api/plans/{day}/garmin/sync` | `status` 可能为 **`partial`**；含 `sync_result: {written, skipped, excluded, skipped_movements}` |
| `POST /api/exercise-mappings/batch-activate` | 响应含 `activated` / `skipped` / `skipped_reasons` / `relation_breakdown` |

## 已核实的关键事实（实读代码，可直接采信）

- `frontend/src/pages/ExerciseMappingsPage.jsx`（约 770 行）：
  - `buildListQuery({ status, confidence, keyword, page, pageSize })` 拼查询串
    （只支持 `status` / `confidence` / `keyword` / `page` / `page_size`）
  - 组件内有 `const [status, setStatus] = useState('')`、`const [confidence, setConfidence] = useState('')`
  - 覆盖率区用 `coverage?.by_status`（约第 361 行）
  - 批量采纳按钮 body 为 `{ confidence: 'high' }`（约第 261 行）
- `frontend/src/components/SyncButton.jsx`：已有 `task.finished_at` 展示，
  状态文案来自 `task.status`
- 前端测试：**52 个文件 / 474 用例全部通过**（基线，改动后不得低于此数）
- `npm run lint` = `oxlint`；`npx vitest run` 跑测试

**后端列表接口的关键约束（先读 `backend/app/api/exercise_mappings.py` 确认，不要臆测）**：
`GET /api/exercise-mappings` 目前**是否支持 `relation` 查询参数**？
- 若不支持 → 本片**不新增后端参数**，前端筛选改为**客户端过滤当前页**，
  并在 UI 上标注「仅筛选当前页」（避免假装是服务端筛选）；
- 若已支持 → 直接用。

## 文件预算（共 5 个，不得越界）

改 2：
1. `frontend/src/pages/ExerciseMappingsPage.jsx`
2. `frontend/src/components/SyncButton.jsx`

新增 3：
3. `frontend/src/components/PartialSyncNotice.jsx`（缺口提示小组件）
4. `frontend/src/pages/__tests__/ExerciseMappingsRelation.test.jsx`
5. `frontend/src/components/__tests__/PartialSyncNotice.test.jsx`

**禁止修改**：任何 `backend/**`、`frontend/src/api/**`、既有测试文件、路由、`.env`。

## 开发内容

### 1. `ExerciseMappingsPage.jsx`：relation 维度可见与可筛

**a. 新增关系徽标**

为每行加一个 `relation` 徽标（取值 → 文案与配色）：

| relation | 文案 | 语义 |
|---|---|---|
| `EXACT` | 精确 | 绿色（`bg-emerald-100 text-emerald-700`） |
| `SIMILAR` | 近似（有损） | 琥珀色（`bg-amber-100 text-amber-800`） |
| `CATEGORY` | 大类（有损） | 橙色（`bg-orange-100 text-orange-800`） |
| `UNMAPPED` | 无对应 | 灰色 |
| 空值 | 未回填 | 浅灰色，`title="relation 尚未回填，可调用 backfill-relations"` |

**b. 新增 relation 筛选**

- 在现有的 status / confidence 筛选旁加一个 `relation` 下拉（选项：全部 / 精确 / 近似 / 大类 / 无对应 / 未回填）
- **按上文核实结果实现**：后端不支持 `relation` 参数时，用 `useMemo` 对**当前页 items** 过滤，
  并在筛选器旁显示小字「仅筛选当前页」
- 不要改动 `buildListQuery` 的既有参数语义

**c. `decision_source` 可见**

- `decision_source === 'human_policy'` 的行显示一个徽标「沿用旧政策」，
  并带 `title="继承旧规则的批量使用政策，非逐条人工语义确认（ADR §10.1）"`
- **严禁**把 `human_policy` 显示成「已确认」「人工确认」等字样

**d. 批量采纳结果显示新的跳过原因**

批量采纳成功后，除现有的 `activated` 数字外，展示 `skipped_reasons` 的分项
（中文映射：`relation_not_exact`→「关系非精确」、`relation_missing`→「未回填关系」、
`target_unverified`→「目标未验证」、`equipment_mismatch`→「器械不符」、
`catalog_missing`→「目录无此组合」），并显示 `relation_breakdown` 的简要分布。

### 2. `PartialSyncNotice.jsx`（新组件）+ `SyncButton.jsx`

```jsx
export default function PartialSyncNotice({ syncResult, className = '' })
```

- `syncResult` 形如 `{ written, skipped, excluded, skipped_movements: [{name, reason, detail}] }`
- `skipped > 0` 时渲染琥珀色提示块：
  - 标题：`部分同步：已写入 {written} 个动作，跳过 {skipped} 个`
  - 列出 `skipped_movements` 的动作名与 `reason`（最多展示 8 条，超出显示「还有 N 个」）
  - 底部小字：`被跳过的动作不会出现在 Garmin 训练里；修复映射后重新同步会补回`
- `skipped === 0` 时返回 `null`
- `excluded > 0` 时另起一行灰字：`另有 {excluded} 个动作按产品定义不写入（拉伸/有氧）`

`SyncButton.jsx`：

- 当 `task.status === 'partial'` 时，状态文案显示「部分成功」而不是「成功」/「失败」
- 若响应里带 `sync_result`，在其下方渲染 `<PartialSyncNotice syncResult={...} />`
- 保持既有 `finished_at` 展示不变

### 3. `ExerciseMappingsRelation.test.jsx`（新，≥8 例）

用既有页面测试的写法（**先读 `frontend/src/pages/__tests__/` 下已有的映射页测试**，
照抄它的 fetch mock 与 render 方式，不要自创）：

1. `test_exact_badge` —— `relation: 'EXACT'` 的行显示「精确」
2. `test_similar_badge_marked_lossy` —— `SIMILAR` 显示「近似（有损）」
3. `test_category_badge_marked_lossy` —— `CATEGORY` 显示「大类（有损）」
4. `test_unmapped_badge` —— `UNMAPPED` 显示「无对应」
5. `test_null_relation_badge` —— `relation: null` 显示「未回填」
6. `test_human_policy_badge_wording` —— `decision_source: 'human_policy'` 显示「沿用旧政策」，
   且页面文本**不含**「逐条人工确认」
7. `test_relation_filter_client_side` —— 选择「近似」后只剩 SIMILAR 行，
   且出现「仅筛选当前页」提示（按核实结果断言，若后端已支持则改为断言请求带参数）
8. `test_batch_activate_shows_skipped_reasons` —— mock 批量采纳响应含
   `skipped_reasons: {relation_not_exact: 3}` → 页面出现「关系非精确」与数字 3

### 4. `PartialSyncNotice.test.jsx`（新，≥5 例）

1. `test_renders_nothing_when_no_skipped` —— `skipped: 0` → 不渲染（`container.firstChild === null`）
2. `test_renders_counts` —— `{written: 2, skipped: 1}` → 含「已写入 2 个动作」「跳过 1 个」
3. `test_lists_skipped_movements` —— 渲染动作名与 reason
4. `test_truncates_after_eight` —— 10 条时只显示 8 条 + 「还有 2 个」
5. `test_shows_excluded_hint` —— `excluded: 3` → 含「按产品定义不写入」与 3

## 自报告要求（交付时必须给出）

1. 改动文件清单（对照预算 5 个），每个文件改动行数与组件/函数名。
2. **后端 `GET /api/exercise-mappings` 是否支持 `relation` 参数**（贴出核实到的代码行），
   以及因此选择的筛选实现方式。
3. **`human_policy` 的最终文案**（贴出 JSX 片段），确认不含「人工确认」类措辞。
4. 设计取舍：
   - 为什么有损映射要用颜色 + 文案双重区分（不能只靠颜色）
   - 为什么客户端筛选中要标注「仅筛选当前页」
   - 为什么 `excluded` 与 `skipped` 在 UI 上必须分开呈现
   - `partial` 为什么不能显示成「成功」
5. 确认清单：
   - 未跑 vitest / build / lint
   - 未执行 git
   - 未改 `backend/**`、`frontend/src/api/**`、既有测试文件、路由、`.env`
   - 文件无 BOM、UTF-8
6. 行为自检清单：
   - [ ] 五种 relation 状态都有可见区别（含空值）
   - [ ] 有损映射（SIMILAR/CATEGORY）明确标注「有损」
   - [ ] `human_policy` 不显示成人工确认
   - [ ] `excluded` 与 `skipped` 分开呈现
   - [ ] `partial` 显示为「部分成功」而非成功
   - [ ] 缺口列表超过 8 条时有「还有 N 个」
   - [ ] 未新增后端改动

## 明确不做

- 不改任何后端代码（含新增查询参数）
- 不改 `frontend/src/api/**`（若已封装好接口，直接复用）
- 不改路由与导航
- 不做 AI 审核结果页面（`/reviews` 接口留给后续）
