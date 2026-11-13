# ADR-P2-8 编辑弹窗支持中文搜索（训记动作名 → Garmin 候选）

> 你是本仓库的资深全栈工程师（FastAPI + SQLAlchemy 2.x + React 19 + Vitest）。
> 本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest / vitest / build 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须无 BOM、UTF-8；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 需求背景

上一切片（ADR-P2-7）已让编辑弹窗「打开即列出该分类全部动作」，解决了"不知道英文名"的问题。
但还差一步：用户想找的是 **「上斜哑铃卧推」对应的那条**，而现在只能先猜分类、再在英文列表里翻。

本片加**中文搜索**：输入中文 → 先匹配「训记动作名」，再对每个匹配项跑既有的候选算法 →
直接给出 `训记动作 → Garmin 条目（含置信度）`，点一条即填入。

**为什么这样做而不是直接对中文分词**：训记动作名是既有的 1091 条权威集合，
`generate_candidates()` 本来就是为它们设计的（含器械/姿态/部位窄化、有氧排除、限定词扣分）。
用「子串匹配训记动作名 → 复用候选算法」既准确又零新增算法逻辑。

## 已核实的关键事实（实读代码，可直接采信）

- `backend/app/services/exercise_mapping.py`
  - `search_catalog(*, q="", category=None, limit=30) -> list[dict]`：
    在 Garmin 离线目录里按 `garmin_exercises.find(term)` 搜索，返回
    `[{"category","exercise","name"}]`，`limit` 钳到 100
  - 已有 `_norm()`（在 candidates 模块）与 `EXT` 等等价物，**本片不新增去重逻辑之外的算法**
- `backend/app/services/exercise_mapping_candidates.py`
  - `generate_candidates(xunji_name, *, limit=3, catalog=None) -> list[Candidate]`
  - `Candidate` 字段：`xunji_name / garmin_category / garmin_exercise_name /
    garmin_display_name / confidence / rank / reason`
- `backend/app/services/exercise_mapping_batch.py` 的 `_load_movement_names()` 读
  `app/data/xunji_movements.json`（1091 条训记动作名）
- `frontend/src/pages/ExerciseMappingsPage.jsx`（ADR-P2-7 之后）：
  - 编辑弹窗里有 `<input data-testid="edit-exercise-search">`，effect 依据
    `q` 是否为空决定"列出分类全部"还是"分类内筛选"，请求
    `GET /api/exercise-mappings/catalog?limit=100&category=<分类>[&q=<q>]`
  - 列表条目按钮 `data-testid={\`edit-exercise-result-${index}\`}`，
    点击调 `pickExercise(row)`，`row` 形如 `{category, exercise, name}`
  - 已有「当前：<枚举名> · <显示名>」一行、空态文案、截断提示
- 前端测试基线：**57 文件 / 511 用例全部通过**（改动后不得低于此数）
- 后端测试基线：**1623 passed**

## 文件预算（共 5 个，不得越界）

改 3：
1. `backend/app/services/exercise_mapping.py`（新增中文搜索函数）
2. `backend/app/api/exercise_mappings.py`（新增 1 个固定路径端点）
3. `frontend/src/pages/ExerciseMappingsPage.jsx`（按查询语言分流）

新增 2：
4. `backend/tests/test_catalog_xunji_search.py`
5. `frontend/src/pages/__tests__/ExerciseMappingsChineseSearch.test.jsx`

**禁止修改**：`exercise_mapping_candidates.py`、`exercise_mapping_batch.py`、
`exercise_mapping_relation.py`、`exercise_mapping_review.py`、`models.py`、任何迁移、
`frontend/src/api/**`、其它组件、路由、既有测试文件、`.env`。

## 开发内容

### 1. 后端：`exercise_mapping.py` 新增

```python
def search_by_xunji_name(
    q: str,
    *,
    limit: int = 20,
    candidates_per_movement: int = 2,
) -> list[dict]:
    """按中文（或任意）片段匹配训记动作名，再给出各自的 Garmin 候选。

    做的是「子串匹配训记动作名 → 复用 generate_candidates」，
    不新增任何打分逻辑。

    返回（按匹配质量排序，长度越接近 q 越靠前）：
    [
      {"xunji_name": "上斜哑铃卧推", "match_rank": 0,
       "category": "BENCH_PRESS", "exercise": "INCLINE_DUMBBELL_BENCH_PRESS",
       "name": "Incline Dumbbell Bench Press",
       "confidence": "high", "rank": 1, "reason": "..."},
      ...
    ]

    规则：
    - q 去空白后为空 → 返回 []
    - 只在 `_load_movement_names()` 的全集里做**子串**匹配（大小写不敏感，
      直接 str 包含即可；中文不需要 casefold）
    - 匹配到的动作按「长度升序」排序（短名更可能是用户想精确找的那个），
      再按名字排序保证稳定
    - 每个动作最多取 `candidates_per_movement` 条候选（默认 2）
    - 候选为空的动作**跳过**（不回空行）
    - 总条数不超过 `limit`
    - 没有任何匹配 → []
    """
```

实现要点：

- 复用 `from app.services.exercise_mapping_batch import _load_movement_names`（只 import）
- 复用 `from app.services.exercise_mapping_candidates import generate_candidates`
- `match_rank` 是该动作在匹配序列里的下标（0 起）
- **不要**改动 `search_catalog`（英文搜索保持原样）

### 2. 后端：`api/exercise_mappings.py` 新增端点

**注册位置**：与其它固定路径一起，放在 `/{mapping_id}` **之前**。

```python
@router.get("/catalog-search-xunji")
def get_catalog_search_xunji(
    q: str = Query(min_length=1, max_length=50),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """中文搜索：按训记动作名匹配并给出各自的 Garmin 候选（只读）。"""
    return {"items": mapping_svc.search_by_xunji_name(q, limit=limit)}
```

### 3. 前端：按查询语言分流

在 `ExerciseMappingsPage.jsx` 的搜索 effect 里：

```js
const hasCJK = /[\u4e00-\u9fff]/.test(q)
```

- **q 含中文** → 请求 `GET /api/exercise-mappings/catalog-search-xunji?q=<q>&limit=20`，
  结果转成列表行（`{category, exercise, name, xunji_name, confidence, rank, reason}`）
- **其余**（空 q 或纯 ASCII）→ 保持 ADR-P2-7 的行为不变
  （空 q 列出分类全部；ASCII 在分类内筛选 `catalog?q=`）

列表渲染差异（**仅中文搜索结果有额外字段时**）：

- 每条主行显示：`name`（英文显示名）
- 副行显示：`<xunji_name> → <exercise 枚举名>`（枚举名用 `font-mono text-xs`）
- 右侧显示置信度小徽标：`high` 绿 / `medium` 琥珀 / `low` 灰
- 点击仍走 `pickExercise({category, exercise, name})`（**字段名必须对齐**，
  注意后端中文接口返回的是 `exercise` 而不是 `garmin_exercise_name`）

空态：

| 情况 | 文案 |
|---|---|
| 中文搜索无匹配 | 「没有匹配到训记动作，换个关键词试试」 |
| 中文搜索有匹配但候选全空 | 同上（因为后端会跳过无候选的动作，等价于空） |

搜索框 placeholder 改为：
`可输入中文动作名（如「上斜哑铃卧推」）或英文关键词筛选`

### 4. `backend/tests/test_catalog_xunji_search.py`（新，≥8 例）

1. `test_substring_match_returns_candidates` —— `q="上斜哑铃"` → 返回非空，
   且包含 `xunji_name` 以「上斜哑铃」开头的条目
2. `test_result_shape` —— 每条含 `xunji_name / match_rank / category / exercise /
   name / confidence / rank / reason` 八个键
3. `test_short_name_first` —— 造两个名字长度不同的匹配（用真实数据里存在的组合），
   断言 `match_rank` 递增且短名在前
4. `test_skips_movements_without_candidates` —— 结果里不存在 `exercise` 为空的项
5. `test_respects_candidates_per_movement` —— `candidates_per_movement=1` 时
   同一 `xunji_name` 只出现一次
6. `test_respects_limit` —— `limit=1` → 长度 1
7. `test_blank_query_returns_empty` —— `q="   "` → `[]`
8. `test_no_match_returns_empty` —— `q="完全不存在的动作xyz"` → `[]`

### 5. `frontend/src/pages/__tests__/ExerciseMappingsChineseSearch.test.jsx`（新，≥6 例）

**照抄 `frontend/src/pages/__tests__/ExerciseMappingsExercisePicker.test.jsx`
的 routeFetch / renderPage 写法**（先读它）：

1. `test_chinese_query_calls_xunji_endpoint` —— 输入「上斜哑铃」→ 请求
   `/api/exercise-mappings/catalog-search-xunji?q=`，且**不**请求 `/catalog?`
2. `test_english_query_still_uses_catalog` —— 输入 `incline` → 仍请求 `/catalog?`
3. `test_chinese_result_shows_xunji_and_confidence` —— 结果行显示
   `xunji_name` 与置信度徽标
4. `test_click_chinese_result_fills_exercise` —— 点击后「当前：」显示该枚举名
5. `test_chinese_no_match_empty_state` —— 返回 `items: []` → 显示
   「没有匹配到训记动作，换个关键词试试」
6. `test_placeholder_mentions_chinese` —— 搜索框 placeholder 含「中文」

## 自报告要求（交付时必须给出）

1. 改动文件清单（对照预算 5 个），每个文件改动行数与函数/组件名。
2. **`search_by_xunji_name` 的最终实现全文**（贴出来）。
3. **实测 5 组**（用真实数据）：

   | q | 匹配动作数 | 返回条数 | 首条 xunji_name → exercise（confidence） |
   |---|---|---|---|
   | 上斜哑铃 | ? | ? | ? |
   | 哑铃卧推 | ? | ? | ? |
   | 绳索夹胸 | ? | ? | ? |
   | 侧平举 | ? | ? | ? |
   | 完全不存在xyz | ? | ? | ? |

4. 前端一次完整交互：输入「上斜哑铃」→ 请求 URL → 列表内容 → 点一条 → 「当前：」变化。
5. 设计取舍：
   - 为什么先匹配训记动作名再跑候选算法，而不是对中文分词
   - 为什么按名称长度排序
   - 为什么跳过无候选的动作而不是给空行
   - 后端中文接口为什么返回 `exercise` 而不是 `garmin_exercise_name`（与既有 catalog 字段对齐）
6. 确认清单：
   - 未跑 pytest / vitest / build
   - 未执行 git
   - 未改 `.env` 系列
   - 未改 `exercise_mapping_candidates.py` / batch / relation / review / models / 迁移 /
     `frontend/src/api/**` / 其它组件 / 路由 / 任何既有测试文件
   - 文件无 BOM、UTF-8
7. 行为自检清单：
   - [ ] 中文查询走新接口，英文/空查询走原接口（互不干扰）
   - [ ] 中文结果含 `xunji_name` 与置信度徽标
   - [ ] 点击中文结果能正确填入编辑表单（字段名对齐）
   - [ ] 无匹配时有明确空态文案
   - [ ] 后端跳过无候选动作，不返回空行
   - [ ] 既有 511 个前端用例不受影响

## 明确不做

- 不做拼音搜索 / 模糊纠错（子串匹配足够）
- 不做 AI 调用（这是"找条目"，不是"判断对错"；AI 审核已有独立入口）
- 不改 `search_catalog`（英文搜索行为不变）
- 不改列表页与其它弹窗
