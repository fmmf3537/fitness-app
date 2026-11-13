# 训记 ↔ Garmin 动作匹配方案（全量覆盖版）

> 状态：**已全部实施并验收通过**（2026-11-11）
> 日期：2026-11-11（v3：8 个切片全部完成）
>
> 实施结果：V6-1 / V6-2 / V6-3 / V6-4 / V6-5 / V6-6a / V6-6b / V6-7 / V6-8 全部落地，
> 另有前置 V5-9（Garmin 写入二次确认）。后端 1316 passed / 前端 52 files 474 passed。
> 实测覆盖率见 §2.3。
> 适用范围：训记训练计划 → Garmin Connect Workout 写入链路
> 前置阅读：`docs/GARMIN-PLAN-SYNC-MIGRATION.md` §8.1（动作白名单）、§8.2（组次转换）

## 1. 结论摘要

当前 `EXERCISE_WHITELIST` 只有 **16 个**动作，训记标准动作表 **1091 个**、Garmin 目录
**1527 个 / 47 category**。计划一换动作就 `PLAN_MAPPING_UNSUPPORTED`（422）整日禁止同步。

本方案改为 **全量映射 + 分级激活 + 纠错闭环**：

1. **全量生成**：939 个力量动作全部建立映射记录（另 152 个拉伸/有氧标记为不适用）
2. **分级激活**：全量映射默认 `draft`，只有用户采纳或计划实际用到时才转 `active`，
   避免算法错映射被静默写入 Garmin
3. **纠错闭环**：任何映射都可随时修改，支持从「预览现场」就地修正；
   已同步的历史训练会被标记 `stale` 并提示是否重同步
4. **分级验证**：L1 目录校验全量离线；L2 按 category 抽样真实创建；L3 用户目视

关键结论（已实测/已确认）：

- **重量语义双边一致，不需要换算**：`total`（杠铃/器械）与 `per_hand`（哑铃）两个口径，
  训记与 Garmin **都按原值一致**。证据：P3 远端 `BARBELL_BACK_SQUAT weightValue=67.5`、
  P2 远端 `DUMBBELL_BENCH_PRESS weightValue=15.0/17.5/20.0/22.5` 均为训记原值，
  且用户已目视确认 Connect 与 FR955 显示正确；用户确认「训记哑铃 = 单只，Garmin 也显示单只」。
- **`bodyweight` 已正确**：`weightValue: null`，不伪造 0。
- **`assisted`（`exetype=help`）未支持**：mapper 完全不读 `exetype`。当前 16 条白名单
  无此类动作，但全量映射会引入（辅助引体/辅助双杠等），必须显式拦截。
- **14% 的动作本质不可映射**：拉伸 122 + 有氧 30 = 152，不是力量动作，
  不能写进 `strength_training` workout。

## 2. 现状与全量构成实测

| 项 | 数量 | 位置 |
|---|---|---|
| 训记标准动作表 | 1091 | `backend/app/data/xunji_movements.json` |
| Garmin 动作目录 | 1527 / 47 category | `garminconnect/exercises.py`（**离线静态表**：`EXERCISES` / `BY_NAME` / `CATEGORIES` / `resolve()` / `find()`） |
| 代码内映射 | 16（p0:1 / p2:8 / p3:7） | `garmin_workout_mapper.EXERCISE_WHITELIST` |
| 已覆盖 Garmin category | 9 / 47 | 同上 |
| 部位分类器 | 7 类 | `stats.classify_part` |

### 2.1 1091 个动作的大类构成（本地只读分析）

| 大类 | 数量 | 占比 | 能否映射为 strength workout |
|---|---|---|---|
| **力量类** | **939** | 86.1% | ✅ 可映射（本方案目标） |
| 拉伸/柔韧类 | 122 | 11.2% | ❌ `not_applicable` |
| 有氧类 | 30 | 2.7% | ❌ `not_applicable` |
| 合计 | 1091 | | 无完全重复项（unique = 1091） |

### 2.2 939 个力量动作的匹配难度预估

用约 50 词的临时词表粗测（正式实现会用完整词表，high 比例会更高）：

| 信号强度 | 数量 | 占比 | 预估处理方式 |
|---|---|---|---|
| 器械 + 动作模式都命中 | 376 | 40.0% | 4 级窄化自动命中 |
| 只命中动作模式 | 251 | 26.7% | 4 级窄化 + 候选列表 |
| 只命中器械 | 164 | 17.5% | LLM 兜底 |
| 无信号 | 148 | 15.8% | LLM + 人工复核 |

> 「无信号」不代表不可映射——临时词表缺"抓举/前平举"等词，正式词表会覆盖。

### 2.3 实施后实测覆盖率（V6-7 全量批处理，生产行为）

| 档位 | 数量 | 占比 |
|---|---|---|
| high（器械+动作都命中） | 222 | 20.3% |
| medium（仅动作词根命中） | 264 | 24.2% |
| low（兜底路径） | 206 | 18.9% |
| none（无自动候选，可走 V6-3 LLM） | 235 | 21.5% |
| not_applicable（拉伸/有氧） | 164 | 15.0% |

- 力量类 927 个中 **708 个（76.4%）有自动候选**
- 候选总行数 2038
- 16 条已验证映射保持 `active` / `displayed`，批处理不会降级它们

V6-2 首版实测 empty 曾达 29.3%，根因是 `_norm` 把 `-` 换成空格导致
`"Lat Pull-down"` 无法命中词表里的 `pulldown`；改为剥离全部非字母数字后降至
20.2%，再补 40 个词后为 21.5%（分类口径含 not_applicable 调整）。

## 3. 三个独立问题

| # | 问题 | 表现 | 现状 | 本方案对策 |
|---|---|---|---|---|
| **P1** | 找不到（未映射） | 422 + 清单，整日禁止同步 | 只覆盖 16 个 | 全量映射 + `not_applicable` 跳过 |
| **P2** | 找错了（映射错动作） | 同步成功但 Garmin 显示别的动作 | 仅人工目视 | **分级激活 + 纠错闭环** |
| **P3** | 重量语义错 | 动作对但重量显示错 | ✅ 已确认双边一致 | 存 `weight_strategy` 作声明 |
| **P4** | 辅助动作语义反 | `exetype=help` 被当负荷 | ❌ 未处理 | `assisted` 默认禁用 |

## 4. 总体架构

```
① 全量生成   939 个力量动作 → 4 级窄化候选 → 不足的走 LLM → 全部落 draft
             152 个非力量动作 → status='not_applicable' + 原因
                  ↓
② 分级激活   draft ─┬─ 用户在复核页采纳 ──────────────→ active
                    ├─ 计划里实际用到（预览时提示复核）─→ active
                    └─ 长期未用 ─────────────────────→ 保持 draft
                  ↓
③ 计划写入   只允许 active 映射参与写入；draft 命中时预览弹出待复核引导
                  ↓
④ 纠错闭环   随时改映射（含从预览现场就地改）→ 记录审计 → 标 stale 旧同步
                  ↓
⑤ 分级验证   L1 目录校验（全量离线）/ L2 按 category 抽样真实创建 / L3 用户目视
```

**核心原则**：**全量映射在库里，但只有"被确认过"的才允许写入 Garmin。**

## 5. 数据模型

### 5.1 `exercise_mapping`（正式映射，全量 1091 行）

```sql
exercise_mapping(
    id                    PK,
    xunji_name            TEXT NOT NULL,          -- 训记标准中文名
    garmin_category       VARCHAR(64),            -- 47 之一；not_applicable 时为空
    garmin_exercise_name  VARCHAR(128),           -- 允许空串（Garmin 只显示 category 名）
    garmin_display_name   VARCHAR(200),           -- 预览展示
    weight_strategy       VARCHAR(32),            -- total / per_hand / bodyweight / assisted
    status                VARCHAR(20) NOT NULL,   -- draft / active / disabled / not_applicable
    not_applicable_reason VARCHAR(100),           -- 如 "拉伸动作，非力量训练"
    confidence            VARCHAR(10),            -- high / medium / low
    source                VARCHAR(20),            -- seed / auto / llm / manual
    verified_level        VARCHAR(20),            -- none / catalog / created / displayed
    verified_at           DATETIME,
    mapping_version       INT DEFAULT 1,          -- 每次编辑 +1（供 stale 判定）
    note                  TEXT,
    created_at, updated_at,
    UNIQUE(xunji_name)
)
```

**`weight_strategy` 的定位**：不是换算系数，而是**语义声明 + 安全闸门**。

| 值 | 写入行为 | 当前状态 |
|---|---|---|
| `total` | `weightValue = 训记 weight`（原值） | ✅ P3 已验证 |
| `per_hand` | `weightValue = 训记 weight`（原值） | ✅ P2 已验证（双方都按单只） |
| `bodyweight` | `weightValue = null` | ✅ 现有代码已正确 |
| `assisted` | **拒绝同步**（待专项验证） | ⚠️ 新增，默认 `disabled` |

### 5.2 `exercise_mapping_candidate`（待复核候选）

```sql
exercise_mapping_candidate(
    id                    PK,
    xunji_name            TEXT NOT NULL,
    garmin_category       VARCHAR(64) NOT NULL,
    garmin_exercise_name  VARCHAR(128),
    garmin_display_name   VARCHAR(200),
    confidence            VARCHAR(10),
    reason                TEXT,                   -- 命中依据
    rank                  INT,                    -- 候选排序（1 为主推）
    status                VARCHAR(20) DEFAULT 'pending',  -- pending / accepted / rejected
    created_at, resolved_at
)
```

### 5.3 `exercise_mapping_audit`（纠错留痕）

```sql
exercise_mapping_audit(
    id            PK,
    mapping_id    INT NOT NULL,
    xunji_name    VARCHAR(200) NOT NULL,   -- 冗余存，映射被删也能追溯
    action        VARCHAR(20) NOT NULL,    -- create / update / activate / disable / reactivate
    before_json   TEXT,                     -- 改动前快照（null 表示新建）
    after_json    TEXT,                     -- 改动后快照
    reason        TEXT,                     -- 用户填写的修改原因（可选但推荐）
    actor         VARCHAR(50),              -- 'user' / 'auto' / 'llm'
    created_at    DATETIME
)
```

### 5.4 旧同步的 stale 判定

`garmin_plan_sync` 增加一列：

```sql
garmin_plan_sync.mapping_hash VARCHAR(64)   -- 该次同步所用映射的快照哈希
```

生成方式：把本次同步涉及的所有 `(xunji_name, garmin_category, garmin_exercise_name,
weight_strategy, mapping_version)` 按名称排序后做 sha256。

**用途**：映射被修改后，重新计算当前哈希 ≠ 记录里的 hash → 该同步标记 `stale`，
UI 提示「此训练使用的映射已更新，是否重新同步？」

### 5.5 迁移兼容

现有 16 条硬编码 → seed 进 `exercise_mapping`：
- `status='active'`、`verified_level='displayed'`（已过 P2/P3 目视）
- `source='seed'`、`weight_strategy` 按器械推断（杠铃/器械→`total`，哑铃→`per_hand`）
- 保留 `EXERCISE_WHITELIST` 作为 fallback（DB 未初始化时不至于全面 422）

## 6. 候选生成（4 级窄化）

### 第 1 级：部位 → Garmin category 子集

复用 `stats.classify_part()`（7 类），配一次性人工表：

```python
PART_TO_GARMIN_CATEGORIES = {
    "胸":   ["BENCH_PRESS", "FLYE", "PUSH_UP", "CABLE", "PLYO"],
    "背":   ["ROW", "PULL_UP", "LAT_PULLDOWN", "SHRUG", "OLYMPIC_LIFT"],
    "腿":   ["SQUAT", "DEADLIFT", "LUNGE", "LEG_PRESS", "LEG_CURL",
             "LEG_RAISE", "HIP_RAISE", "PLYO"],
    "肩":   ["SHOULDER_PRESS", "LATERAL_RAISE", "SHOULDER_STABILITY", "FLYE"],
    "臂":   ["TRICEPS_EXTENSION", "CURL"],
    "核心": ["CORE", "CRUNCH", "PLANK", "SIT_UP"],
    "有氧": ["RUN", "RUN_INDOOR", "INDOOR_BIKE", "CARDIO"],
}
```

### 第 2 级：器械识别（中文 → 英文词根）

`杠铃→barbell`、`哑铃→dumbbell`、`史密斯→smith machine`、`绳索/龙门→cable`、
`器械→machine`、`壶铃→kettlebell`、`弹力带→banded`、`自重/徒手→（空）` 等。

### 第 3 级：动作模式识别（中文 → Garmin 英文动作词）

`卧推→bench press`、`飞鸟→flye`、`深蹲→squat`、`硬拉→deadlift`、`腿举→leg press`、
`划船→row`、`下拉→pulldown`、`引体→pull up`、`推举/推肩→shoulder press`、
`侧平举→lateral raise`、`弯举→curl`、`臂屈伸→extension`、`卷腹→crunch`、
`转体→twist`、`平板支撑→plank`、`抓举/挺举→olympic lift` 等。

> 正式实现需要完整词表（预估 100-150 个词），并支持同义词。

### 第 4 级：目录内模糊匹配

组合成候选串（如 `"dumbbell bench press"`），在**第 1 级已缩窄的 category 子集**内，
用 `exercises.find(term)` 或对 `BY_NAME` 做相似度打分，取 top 1-3 存入候选表（带 `rank`）。

### 置信度分级

| 级别 | 条件 |
|---|---|
| `high` | 器械 + 动作模式都命中，且 catalog 内唯一匹配 |
| `medium` | 只命中动作模式，或命中 2-3 个候选 |
| `low` | 仅靠部位兜底，或 LLM 判断 |

### LLM 兜底（全量场景）

- 范围：预估 **400-500 个** medium/low 动作
- 每批 20 个 + **该动作所属部位的 category 候选列表**（不送全部 1527）
- 严格 JSON 输出：`{xunji_name, category, exerciseName, confidence, reason}`
- 落库前用 `exercises.resolve()` 校验存在性，不存在降级 `low` 并标红
- 复用 `adapters/llm.chat`，`purpose='exercise_mapping'` 记账
- 预估成本：25 批 ≈ **¥0.2**（DeepSeek，一次性）

## 7. 复核与纠错 UI

### 7.1 映射管理页 `/exercise-mappings`

```
[筛选] 状态：[全部 / draft / active / disabled / not_applicable]
       置信度：[全部 / high / medium / low]
       搜索：[____________]

[列表]
  哑铃卧推    BENCH_PRESS / DUMBBELL_BENCH_PRESS
              active · displayed · 单只                  [编辑] [停用]
  哑铃上斜卧推 BENCH_PRESS / INCLINE_DUMBBELL_BENCH_PRESS
              draft · catalog · 单只                    [采纳] [改] [忽略]
  跑步        —（拉伸/有氧不适用）                        [改为适用?]
              not_applicable · 「有氧动作，非力量训练」

[批量] 当前筛选结果 N 条 → [批量采纳 high 置信] [批量忽略 low]
```

### 7.2 计划预览内就地纠错（**最重要的入口**）

用户是在"看到错误"的那一刻才有动力修，所以纠错必须能从预览现场直接发起：

```
Garmin 同步预览弹窗
┌────────────────────────────────────────────────┐
│ 哑铃卧推  BENCH_PRESS / DUMBBELL_BENCH_PRESS   │
│           第1组 15 kg（单只）→ 写入 15 kg       │
│           [映射不对？]  ← 点击                  │
│ 上斜哑铃飞鸟  FLYE / INCLINE_DUMBBELL_FLYE     │
│           [映射不对？]                          │
└────────────────────────────────────────────────┘
        ↓ 点「映射不对？」
┌────────────────────────────────────────────────┐
│ 修正「哑铃卧推」的映射                          │
│ 当前：BENCH_PRESS / DUMBBELL_BENCH_PRESS       │
│ 搜索：[bench________]  （默认带原动作词）        │
│ ○ BENCH_PRESS / DUMBBELL_BENCH_PRESS           │
│   （Dumbbell Bench Press）                     │
│ ○ BENCH_PRESS / BARBELL_BENCH_PRESS            │
│   （Barbell Bench Press）                      │
│ ○ FLYE / DUMBBELL_FLYE                         │
│   （Dumbbell Flye）                            │
│ 重量语义：[单只 ▾]                              │
│ 修改原因：[____________________]（可选）         │
│                          [取消]  [保存并重预览]  │
└────────────────────────────────────────────────┘
```

保存后：
1. 写 `exercise_mapping_audit`
2. `mapping_version += 1`
3. 重新加载该日预览（立即看到新映射效果）
4. 若该日此前已同步过 → 标记 `stale` 并提示

### 7.3 draft 命中时的引导（C 方案落地）

计划里遇到 `draft` 映射时：

```
┌────────────────────────────────────────────────┐
│ ⚠ 本训练日有 2 个动作尚未复核映射                │
│   · 哑铃上斜卧推（建议 BENCH_PRESS/…)           │
│   · 绳索面拉（建议 SHOULDER_STABILITY/…)        │
│                                                │
│ 确认映射后即可同步：[去复核]  [取消]             │
└────────────────────────────────────────────────┘
```

不阻断预览（能看），但阻断写入（必须先复核）。

### 7.4 已同步训练的 stale 处理

映射修改后，`garmin_plan_sync.mapping_hash` 不匹配的同步记录标记 `stale`：

```
┌────────────────────────────────────────────────┐
│ ⚠ 此训练已在 Garmin 同步，但使用的映射已更新      │
│   旧：FLYE / INCLINE_DUMBBELL_FLYE             │
│   新：FLYE / DUMBBELL_FLYE                     │
│                                                │
│ [在 Garmin 中保留旧版]  [重新同步]（会覆盖）    │
└────────────────────────────────────────────────┘
```

**默认不自动重写**——重新同步会覆盖 Garmin 里已有对象，必须用户显式确认。

## 8. mapper 改造（保留纯函数性质）

```python
# 现在
mapping = EXERCISE_WHITELIST.get(name)

# 改成：映射表由调用方查好并注入
def map_plan_day(plan_day, *, mappings: dict | None = None, plan_ref=None):
    mappings = mappings if mappings is not None else EXERCISE_WHITELIST
    ...
```

**关键**：`garmin_workout_mapper` 现在不碰 DB、不碰文件、不碰网络。改造必须保持这个性质
——查库在 `garmin_plan_sync` 层做，纯函数只接收映射字典。现有 561 行 mapper 测试
可继续用注入方式跑，不破坏。

**新增校验**：`map_plan_day` 遇到 `status != 'active'` 的映射时，产出
`MAPPING_NOT_APPROVED` issue（区别于 `MAPPING_UNSUPPORTED`），供上层区分
「没映射」和「有映射但未复核」。

## 9. 分级验证

| 级 | 做什么 | 成本 | 覆盖 | 落库标记 |
|---|---|---|---|---|
| **L1 `catalog`** | `exercises.resolve(display_name)` 或按 `(category, exerciseName)` 命中 | 零（离线） | 全量 939 | `verified_level='catalog'` |
| **L2 `created`** | 真实创建测试 Workout，回读确认 `exerciseName` 未被规范化掉 | 每 category 1-2 次写入 | ~60-90 次 | `verified_level='created'` |
| **L3 `displayed`** | 用户目视 Connect + FR955 | 人工 | 实际在用的 | `verified_level='displayed'` |

**L2 的必要性**（§8.1 已记录的真实坑）：Garmin 创建后会把通用 `Bench Press` 与
`Lateral Raise` 的 `exerciseName` **规范化为空串**，`category` 保持。这类行为
**目录校验查不出来**，只能靠真实创建 + 回读发现。

## 10. 切片拆分

| 切片 | 内容 | 文件预算 | 依赖 |
|---|---|---|---|
| **V6-1** | 2 张表 + 1 张审计表 + `garmin_plan_sync.mapping_hash` 列 + 迁移 + seed 16 条 + `map_plan_day` 注入改造 + `MAPPING_NOT_APPROVED` | 6 | — |
| **V6-2** | 4 级窄化候选生成器（纯函数）+ 完整词表 + 单测 | 4 | V6-1 |
| **V6-7** | 全量 1091 批处理（生成 draft + not_applicable 分类）+ 覆盖率看板 API | 4 | V6-2 |
| **V6-4** | 复核/纠错 API（列表 / 采纳 / 改映射 / 停用 / 审计 / stale 判定） | 5 | V6-1 |
| **V6-5** | 映射管理页 + 批量操作 | 4 | V6-4 |
| **V6-6** | 计划预览接入 DB 映射 + draft 引导 + 预览内就地纠错弹窗 | 5 | V6-4 |
| **V6-3** | LLM 兜底候选（批量 + JSON 校验 + 成本记账） | 3 | V6-2 |
| **V6-8** | L2 抽样验证脚本（按 category 选代表动作，真实创建 + 回读） | 2 | V6-7 |

**推荐顺序**：V6-1 → V6-2 → **V6-7（决策点）** → V6-4 → V6-5 → V6-6 → V6-3 → V6-8

**V6-7 是决策点**：跑完 939 全量覆盖率才知道 4 级窄化自动命中多少。
若 ≥70%，V6-3（LLM 兜底）可延后或不做。

## 11. 风险与对策

| 风险 | 对策 |
|---|---|
| LLM/算法给出不存在的 category/exerciseName | 落库前 `exercises.resolve()` 校验；不通过降 `low` 并标红 |
| 同 category 但动作选错 | **分级激活**（draft 不写入）+ 复核 UI 强制展示英文名 + 候选可切换 |
| 939 条映射错得多，用户不知道从哪改 | 优先级排序：`high` 置信批量采纳；`low` 优先复核；且**用到时才强制复核** |
| 修错了映射导致历史更乱 | 每次修改写 `audit`；历史同步标 `stale` 而非自动重写 |
| 辅助动作语义反 | `weight_strategy='assisted'` 默认 `disabled`，显式 422 |
| 映射表变大导致预览慢 | 启动预载内存（1091 条 ≈ 几十 KB）；编辑后失效重载 |
| Garmin 改变 category 枚举 | L2 回读校验发现；`verified_level` 可降级重验 |
| 现有 15 个动作回归 | V6-1 seed 时**必须**加回归测试，断言这 15 条映射与 `support_level` 不变 |
| 破坏 mapper 纯函数性质 | V6-1 明确「查库在 sync 层、mapper 只接收注入字典」 |

## 12. 成本

| 项 | 成本 |
|---|---|
| 4 级窄化（本地计算，939 条） | 0 |
| LLM 兜底（预估 400-500 个，25 批） | **≈ ¥0.2**（DeepSeek 一次性） |
| L2 抽样验证（60-90 次真实写入） | 0 元，消耗 Garmin 写入配额，需分批 + 429 冷却 |
| 开发 | 8 个切片，按现有节奏约 3-4 天 |

## 13. 已确认的决策

| # | 决策 | 结论 |
|---|---|---|
| 1 | **覆盖范围** | **全量**：939 个力量动作全部建立映射；152 个非力量动作标 `not_applicable` |
| 2 | 哑铃重量语义 | 训记 = 单只；Garmin 也显示单只 → **双边一致，无需换算** |
| 3 | 复核入口 | 网页 UI（复用 V5-5 模式，手机可用） |
| 4 | L2 验证深度 | 按 category 抽 1-2 个代表动作 |
| 5 | **默认激活策略** | **C 方案**：全量 draft + 计划用到时主动提示复核；confirmed 后才 `active` |
| 6 | **纠错机制** | 任何映射可改（管理页 + 预览内就地改）；写审计；历史同步标 `stale` 由用户决定是否重同步 |

## 14. 未决问题

| # | 问题 | 建议 |
|---|---|---|
| 1 | 152 个非力量动作是否需要支持？（Garmin 有 RUN/INDOOR_BIKE 等 category，但需要非 strength 的 workout sport type） | 本期只标 `not_applicable` 并提示；若需要写有氧 workout，另开切片 |
| 2 | `assisted`（辅助引体/双杠）语义如何对齐？ | 先用 1 个动作做定向真实验证，再决定写入方式；在此之前 `disabled` |
| 3 | 是否支持「同一训记动作在不同计划里映射不同」（比如你的史密斯机 vs 别人的） | 单用户场景不需要；`UNIQUE(xunji_name)` 够用 |

## 15. 打分规则演进（V6-9a → V6-9h 实战记录）

> 本节记录候选生成器在**真实使用中暴露并逐轮修复**的问题。它不是设计阶段的推演，
> 而是「上线 → 抽查 → 定位 → 收紧 → 再抽查」的实证结果，后续改动请以本节为基线。

### 15.1 四轮演进与各自解决的问题

| 轮次 | 触发问题 | 关键改动 | 副作用/代价 |
|---|---|---|---|
| **V6-9a** | 器械专属分类（SUSPENSION/BANDED_EXERCISES 等）没进候选池，TRX/弹力带动作全落到哑铃条目 | 新增 `EQUIPMENT_TO_GARMIN_CATEGORY`，器械分类排在部位分类之前并入池；命中器械分类 +20 | 部位未知（"其他"）时按器械缩池导致 6 条漏检 → 改为「部位未知不缩窄」 |
| **V6-9c** | 词表只有 74 条，219 个动作无候选 | 扩到 148 条；修 5 条永远 0 命中的死词（`neck curl`→`neck`、`farmer carry`→`farmer` 等）；窄化无果回退全目录 | 力量类覆盖 76.4% → 92.6%，无候选 219 → 70 |
| **V6-9f** | 抽查发现 22% 的 high 是错的：手腕弯举→二头弯举、腿外展→肩外旋、器械划船→有氧划船机、吊环弯举→腿弯举、上斜/下斜丢失 | ① 姿态改「匹配 +20/缺失 −20/**全命中 +40**」② 候选池剔除 `CARDIO_ONLY_CATEGORIES` ③ `PART_ANCHORED_MOVEMENTS` 部位锚词 ④「弯举」未限定腿时禁 hamstring ⑤ `single arm` ↔ `One-arm` 同义展开 | 有氧污染 15 → 0 |
| **V6-9g** | 剩 24 条「家族对、变体错」：绳索夹胸→**反向**飞鸟（练错肌肉方向）、器械耸肩→史密斯机、站姿自重提踵→单腿 | ① `QUALIFIER_CONSISTENCY` 限定词扣分（每项 −20、上限 −40）② 中文无「史密斯」时硬排除 smith 条目 ③ `MOVEMENT_ALIASES` fly→crossover | 器械词**刻意不进**限定词表（见 15.3） |
| **V6-9h** | TRX-后束飞鸟→Chest Fly（后束 vs 前侧胸，方向相反） | ① `_is_inconsistent` 增加「后束/后三角 + chest → 跳过」② 新增 `equipment_mismatch_note()`，把「器械不符」写进 `note` | 见 15.4 |

### 15.2 最终打分公式（V6-9h 定稿）

```
score = 20
      + _equipment_bonus       # 器械词根命中 +40；自重类且无其它器械 +20
      + _posture_bonus         # 匹配 +20/个、缺失 −20/个（各上限 40），全命中再 +40
      + _qualifier_penalty     # 中文没要求的特异性限定词 −20/个（上限 −40）
      + _exact_bonus           # "{器械} {动作}" 完全相等 +20
      + EQUIPMENT_CATEGORY_BONUS  # 命中器械专属分类 +20

置信度：>=60 high / >=40 medium / 其余 low
硬过滤（_is_inconsistent，命中即跳过该候选）：
  · 弯举未限定「腿」→ 禁 hamstring；未限定「手腕」→ 禁 wrist
  · 外展/内收 → 候选名须含该部位锚词（腿: leg/hip；肩/臂: shoulder/arm）
  · 单手/单臂/单边 → 候选名须含 singlearm/onearm
  · 中文无「史密斯」→ 禁 smith
  · 中文含「后束/后三角」→ 禁 chest
```

### 15.3 两条重要的「不做」

**① 器械词不进限定词扣分表**

`dumbbell / barbell / cable / banded / kettlebell` 刻意**不**参与 `QUALIFIER_CONSISTENCY`。
原因：中文没写器械时通常是「不限定器材」，而不是「不是该器材」。若把它们纳入扣分，
大量「深蹲」「卧推」这类未指定器械的动作会被候选名里的器械词扣分，置信度整体下滑、
可用性反而变差。

**② 不对姿态做硬过滤（V6-9f 走过的弯路）**

最初对「上斜/下斜」用硬过滤（候选名必须含 incline/decline），结果：
目录里没有对应变体的动作（如上斜负重颈弯举、下斜杠铃卧推）直接变成「无候选」，
实测**误杀 28 条**。最终改为「全姿态命中 +40」的**强偏好**：
真有对应变体时它胜出；没有时仍降级到近似项并降低置信度，而不是让动作彻底不可用。

### 15.4 最终校准数字（`generate_batch` 全量 1091）

| 档位 | 数量 | 说明 |
|---|---:|---|
| high | 299 | 器械+动作+姿态都对上，可批量采纳 |
| medium | 174 | 有语义缺失（如姿态/器械不符），建议抽查 |
| low | 372 | 仅动作家族命中，需人工复核 |
| 无候选 | 82 | Garmin 目录确实没有对应条目 |
| not_applicable | 164 | 拉伸/有氧，不参与写入 |

- 力量类 927 个中 **845 个（91.2%）有候选**
- 候选落在有氧分类：**0**（V6-9f 前为 15）
- **器械不符标注：159 条**（各档合计，其中 high 47 条）
  例如「下斜杠铃卧推 → Decline Dumbbell Bench Press」——
  Garmin 没有杠铃下斜版，映射到同动作家族并写 note 标注，可同步但名字的器械词不准。

### 15.5 已知限制（不再通过算法改进）

1. **82 条无候选**：Garmin 目录确实不存在（如颈部专项、`扩胸开合`、`火箭推` 等）。
2. **47 条 high 器械不符**：Garmin 没有同器械版本，已在 `note` 标注；
   降级会让这些动作整天无法同步，代价大于"名字不精确"，故保留可同步。
3. **LLM 兜底（V6-3）未实际生效**：代码就绪但从未完整运行——一次 10 条试跑抽到
   10 个最难的颈部动作导致 `accepted=0`；且 `_select_targets` 按名字排序取前 N，
   失败的批次不会被标记，分批调用会卡在同一批失败项上。若将来要用，需先做
   「记录已尝试」的断点推进改造。
