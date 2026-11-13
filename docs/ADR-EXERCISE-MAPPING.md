# ADR：训记与 Garmin 动作映射治理、降级与恢复

> 状态：**Proposed（待 owner 接受；接受前不代表代码已实现）**  
> 日期：2026-11-13  
> 适用范围：训记训练计划 → Garmin Connect Strength Workout 写入链路  
> 相关文档：`docs/EXERCISE-MAPPING-PLAN.md`、`docs/GARMIN-PLAN-SYNC-MIGRATION.md`

## 0. 评审修订记录（2026-11-13，reviewer 直接修订）

> 状态保持 **Proposed**。以下修订均基于对现有代码的逐条核对，非架构分歧；目的是避免文档里的一句话引导出错误实现。

| # | 位置 | 修订内容 | 依据 |
|---|---|---|---|
| R1 | §7.2 | 明确**不得复用 `payload_json`** 保存同步结果，改为新增独立字段 | 该字段有两个既有消费方：`run_plan_sync()` 用作期望结构做回读比对；`_extract_xunji_names_from_payload()` 遍历 `workoutSegments` 提取动作名供 stale 判定。混入结果会破坏后者并静默失效 |
| R2 | §5.1 | 把「无风险标记」收敛为**只检查器械不符 note**，并声明其余三类无需检查 | 方向相反、部位冲突、跨有氧/力量三类在**候选生成期已硬过滤**（`_is_inconsistent` 后束规则、`PART_ANCHORED_MOVEMENTS`、`CARDIO_ONLY_CATEGORIES`），落库行不含此类候选，表里没有对应标记字段 |
| R3 | §4.2 | 补充「仅去掉 `not_applicable` 过滤会做错」及 mapper 必须满足的三条 | 实测把 `status='not_applicable'` 交给 mapper 会产出 `MAPPING_NOT_APPROVED`，该 code 属映射缺口并触发 `partial`，与本节要求冲突 |
| R4 | §10.1 | 增加 `relation` 回填的**确定性判据**（复用器械不符/限定词/姿态三项判定）与幂等要求 | 原文只说"回填"未给判据，导致「约 245 / 约 47」不可复现，§15 的"以实测替换估算"无法执行 |
| R5 | §2 | 标注 82 与 97 两个数字的口径差异 | 82 为 `generate_batch` 口径；数据库 `confidence IS NULL` 为 97（含 16 条 seed 未填值） |
| R6 | §7.2 | 明确「全不可写」判定必须发生在**任何远端写操作之前** | 避免先建空 Workout 再删除；删除不可逆且消耗写入配额 |
| R7 | §9 | 补充仅改 `weight_strategy` 等非目标字段时**不重置** `verified_level` | 防止实现时把非目标变更误归入"映射变更" |
| R8 | §10.1 | **修正 R4 判据的两处实现错误**（对方复核指出，已逐条实测确认）：① 不能以「`_posture_bonus` 未触发 +40」反推姿态不符——无姿态词时该函数返回 0，会把「哑铃卧推」这类动作全部误判为 SIMILAR，改为 `bool(postures) and any(...)`；② `_qualifier_penalty()` 第二个参数是 `name_norm`，传原始显示名会因大小写/连字符**使整个限定词检查静默失效**（同一行传原文得 0、传 `_norm()` 得 -20）。另补充输入范围、CATEGORY 断言与"可复现基线≠语义真值"的效力边界 | 实测复现两处 |
| R9 | §2 | **修正 R5 的数字解释**：`82 + 16 ≠ 97` 的解释不成立。实测构成是「16 条 seed + 81 条 draft 无候选 = 97」，而 `generate_batch` 的 82 = 81 + `绳索Pallof推`；该动作同时是 seed 之一（算法无候选但已人工映射），两组集合**重叠 1 条** | 实测：`generate_batch empty - DB draft无候选 = ['绳索Pallof推']`，反向差集为空 |
| R10 | §5.1 | 按对方建议调整措辞：「不在激活层重复推断这些风险」而非「这些错误不可能存在」，并说明生成期过滤是保障、不是语义正确的绝对证明 | 措辞严谨性 |

以下内容经代码核对确认**准确无误**，未作修改：§2 全部 9 条现状描述（含两个现存缺陷）、§7.3 四项既有机制、§4.1 维度与现有列的对应关系。

## 1. 决策摘要

继续沿用现有静态 `exercise_mapping` 主表，日常同步只查表，不在请求路径中调用 AI，也不全量推倒重算。下一阶段优先修复映射语义和同步降级，而不是追求表面上的“100% 已映射”或 `UNMAPPED = 0`。

本 ADR 作出以下决策：

1. 将动作语义关系、匹配置信度、决策来源、启用状态和真实验证等级分开；`ALIAS` 是匹配依据，不是语义关系。
2. `not_applicable` 是产品定义上的正常排除，必须进入映射结果；它不计入同步缺口，不触发 `partial`，更不得因加载时漏掉该行而使整日返回 422。
3. 默认采用“跳过无法写入的动作 + 其余动作部分同步 + 明确报告缺口”，不再让单个映射缺口阻塞整天。
4. `CATEGORY` 只在大类归属可靠时使用；佳明存在通用类目不等于所有动作都能合理归类。
5. 存量旧规则下已激活的有损映射采用 **B：继承既有使用政策**，保持可同步但明确标为 `SIMILAR`，不得伪装成逐条人工语义确认。
6. 训记动作全集来自静态 JSON，新增、删除和改名在文件变更时做解析后的集合 diff，不建设运行时扫描机制。
7. Garmin 目标变化时必须重新评估 `verified_level`，不得把旧目标的真机验证记录继承给新目标。
8. 现有 `source_key`、远端认领、原地更新和回读比对继续复用；`partial → 补全` 的内容级恢复必须通过专项端到端验收。

### 建议实施顺序

- **P0**：`relation` 与启用策略；`not_applicable` 正常排除；部分同步、缺口记录及存量迁移。
- **P1**：静态 JSON diff 与改名继承；Garmin 目标变化后的验证等级重置。
- **P2**：AI 只读审核、审核视图完善和更多真实错例回归。

逻辑维度可以先定义清楚，但不得因此一次性建设复杂别名系统、多租户式治理后台或全量人工确认流程。

## 2. 背景与当前事实

以下现状来自本轮评审对现有代码、文档和真实链路的核对；本 ADR 将其作为设计输入，不把“目标行为”误写成“已经完成”。

- 训记标准动作共 1091 个，已有 `exercise_mapping` 全量主表；同步路径当前不调用 AI。
- 当前规则结果口径为 high 299、medium 174、low 372、无候选 82、`not_applicable` 164（**均为候选生成器 `generate_batch` 口径**）。

  > **两个口径不要混用、也不能相加**：数据库当前 `confidence IS NULL`（排除 `not_applicable`）实测为 **97**，构成为
  > **16 条 seed（未填 confidence）+ 81 条 draft 无候选**。
  > 而 `generate_batch` 的「无候选 82」= 上述 81 条 **+ `绳索Pallof推`**。
  > `绳索Pallof推` 同时属于 16 条 seed 之一（算法给不出候选，但已人工映射为 `CORE/CABLE_CORE_PRESS`），因此两组集合**重叠 1 条**，`82 + 16 ≠ 97` 是正常的。最终数量以 SQL 分组结果为准。

  置信度目前同时承担“算法把握”和“能否批量启用”两种职责。
- 器械不符标注共 159 条，其中 high 47 条；这些动作可能只是同动作家族或不同器械的近似映射，不能因 high 就被视为语义等价。
- 旧规则下已有 292 条 active 映射。评审估算其中约 245 条将回填为 `EXACT`、约 47 条为 `SIMILAR`；最终数量以迁移回填结果为准。
- 训记动作全集是仓库中的 `backend/app/data/xunji_movements.json`，动作载荷没有外部稳定模板 ID；当前以 `xunji_name` 为唯一外部键。
- Garmin 侧使用 `category + exerciseName` 枚举键，已有真实创建、Connect 与 FR955 显示验证链路。
- `source_key`、本地 `workout_id`、按来源键认领远端 Workout、完整 JSON 原地更新及回读结构比对已有实现和验收基础。
- 当前 `load_all_mappings()` 排除 `status='not_applicable'` 的行，导致 mapper 将拉伸等动作误报为 `UNKNOWN_EXERCISE`，可能使整天同步返回 422。
- 当前修改 Garmin 目标只递增 `mapping_version`，没有重置 `verified_level`，可能错误继承旧目标的验证等级。

## 3. 目标与非目标

### 3.1 目标

- 每个训记动作都有明确、可查询的处理决策，包括正常排除和明确无法映射。
- 映射的语义保真度、算法置信度和技术验证程度不再互相替代。
- 单个动作缺口不再阻塞其他可写动作。
- 部分同步的结果可见、可恢复，恢复后不重复创建 Workout 或重复动作步骤。
- 静态动作文件更新后，新增、删除和改名都有可执行的处理入口。
- AI 可以压缩人工审核队列，但不能静默覆盖已确认决策。

### 3.2 非目标

- 不要求 1091 个动作全部由人工逐条确认。
- 不以 `UNMAPPED = 0` 或笼统“100% 已映射”为目标。
- 不在同步请求中实时调用 AI，也不在每次同步时重新生成映射。
- 不建设运行时训记动作接口扫描或定时差集任务。
- 不在本期支持拉伸、有氧等非力量 Workout 写入。
- 不一次性建设复杂别名管理、多角色审批或完整数据治理平台。

## 4. 核心领域模型

### 4.1 字段维度

| 逻辑维度 | 建议取值 | 回答的问题 | 物理实现决策 |
|---|---|---|---|
| `relation` | `EXACT / SIMILAR / CATEGORY / UNMAPPED` | Garmin 能在多大程度上表达训记动作 | 新增；不得再出现 `relation='ALIAS'` |
| `match_basis` | `same_name / alias / translation / semantic_review / rule_features / other` | 凭什么认为双方对应 | 新增简单字段或原因信息；首期不建设复杂界面 |
| `decision_source` | `rule / ai / human / human_policy` | 谁提出或接受了决策 | 逻辑名称；可沿用现有 `source` 并做枚举映射 |
| `status` | `draft / active / disabled / not_applicable` | 当前处理决策是否生效 | 沿用现有状态，降低迁移成本 |
| `confidence` | `high / medium / low / null` | 对未确认提议的算法把握 | 保留现有字段，不再单独充当启用闸门 |
| `verified_level` | `none / catalog / created / displayed` | 当前 Garmin 目标验证到哪一步 | 保留现有字段和 `verified_at` |
| `unmapped_reason` | `no_equivalent / no_safe_category / ambiguous / other` | 为什么适用但仍无法映射 | 新增；与 `not_applicable_reason` 分开 |
| `weight_strategy` | `total / per_hand / bodyweight / assisted` | 重量语义如何处理 | 保持现有正交设计，不在本 ADR 改规则 |

补充约束：

- `ALIAS` 只属于 `match_basis`。通过别名或翻译确认的映射，语义关系仍然可以是 `EXACT`。
- 人工确认的 `CATEGORY` 可以有高把握，但它仍是有损映射；`confidence` 不得改写这一事实。
- `verified_level='catalog'` 只证明 Garmin 目录目标存在，不证明动作语义正确。
- `active` 表示该处理决策生效。对于有 Garmin 目标的关系表示允许按策略写入；对于 `UNMAPPED` 表示已接受按缺口跳过。
- `UNMAPPED` 是合法、明确的处理结果，不等同于“映射行缺失”。

### 4.2 `not_applicable` 与 `UNMAPPED` 必须分离

| 类型 | 产品含义 | 是否写入 | 是否计入缺口 | 是否触发 `partial` |
|---|---|---:|---:|---:|
| `not_applicable` | 按当前产品定义本就不写入力量 Workout，如拉伸、有氧 | 否 | 否 | 否 |
| `UNMAPPED` | 本应写入，但没有可靠 Garmin 表达 | 否 | 是 | 是 |
| 映射缺失、draft、disabled | 本应写入，但当前决策不可用 | 否 | 是 | 是 |

首期物理存储可继续使用 `status='not_applicable'`，不强制新增 `applicability` 字段；但 mapper 的输入和输出必须在逻辑上区分“正常排除”与“无法写入”。

`load_all_mappings()` 必须把 `not_applicable` 行以明确处理决策提供给 mapper，而不是过滤后让其变成未知动作。mapper 仍保持纯函数，不直接访问数据库、文件或网络。

**仅去掉过滤是不够的，会做错。** 实测：把 `status='not_applicable'` 的行交给 mapper 后，现有状态检查（`status not in (None, 'active')`）会把它判成 `MAPPING_NOT_APPROVED`，而该 code 属于 §7.1 的映射缺口，会触发 `partial`——正好违反本节「不触发 partial」的要求。

因此 mapper 必须满足：

1. 遇到 `status == 'not_applicable'` 时**显式跳过**，且**不产出任何 issue**（既不是 `UNKNOWN_EXERCISE`，也不是 `MAPPING_NOT_APPROVED`）；
2. 在预览结果里把这批动作作为 `excluded` 单独呈现，与 `skipped`（映射缺口）分列；
3. 判定发生在状态检查**之前**，不能依赖「查不到映射」的路径兜底。

§12.2 的验收用例若只去掉过滤而未实现上述三条，会以 `partial` 而非 `excluded` 通过，属于假通过。

## 5. 启用与审核策略

### 5.1 批量自动确认

只有同时满足以下条件的 draft 提议才允许批量转为 active：

- `relation = EXACT`；
- `confidence = high`；
- Garmin 目标通过有效性检查，即 `verified_level` 至少为 `catalog`；
- 没有器械不符标记，即 `note` 不以「器械不符」开头；
- 不属于已知需要人工判断的动作或回归黑名单。

> **风险标记只需检查器械不符一项。** 方向相反、部位冲突、跨有氧/力量三类**不需要在激活层重复推断**——生成期的硬过滤（`_is_inconsistent()` 的「后束/后三角 + chest」规则、`PART_ANCHORED_MOVEMENTS` 部位锚词、`CARDIO_ONLY_CATEGORIES` 池过滤）与 golden regression（§11）已保证这类候选不会落库，表里也没有对应标记字段可查，开发时不要去找不存在的字段。
>
> 措辞注意：这是「不在激活层重复推断」，而不是「这些错误不可能存在」。生成期过滤是保障，不是语义正确的绝对证明——新增错例一旦确认，应先补进回归清单，再评估是否需要新增标记。

该条件只定义“自动确认提议”，不定义所有映射的可用性。

### 5.2 正式启用

- `EXACT` 可按上述自动策略或人工确认启用。
- `SIMILAR` 不得仅凭 high 自动确认；经人工或明确使用政策接受后可保持 active，并始终保留有损属性。
- `CATEGORY` 必须具有可靠的大类归属，并经人工或明确政策接受。
- `UNMAPPED` 不得为了满足覆盖率而伪造 Garmin 目标。
- Garmin 目标无效时不得保持 active。
- 人工确认及 `human_policy` 锁定的记录不得被后续 AI 重算静默覆盖；再次修改必须留下审计记录。

## 6. CATEGORY 降级

Garmin 分类存在通用条目，只提供技术降级能力，不提供动作归类依据。

采用以下规则：

1. 只有大类归属可靠时才允许建立 `relation='CATEGORY'` 的映射。
2. 大类本身不确定时保持 `UNMAPPED`，`unmapped_reason` 可记为 `no_safe_category` 或 `ambiguous`。
3. 同步时不得临时猜测类目，也不得把任意无候选动作自动塞进看似接近的通用类目。
4. 提供 `category_fallback_enabled` 配置，默认 **false**。关闭时，CATEGORY 映射保留但不写入，按缺口处理；开启后，只有 active 且目标有效的 CATEGORY 映射才可写入。
5. Garmin 显示为笼统类目是可接受但有损的结果，必须在预览、映射页和统计中可见。

默认策略是“跳过 + 部分同步”，配置项只决定是否额外接受有损 CATEGORY 写入，不再提供“一个缺口阻塞整天”的默认行为。

## 7. 部分同步与结果模型

### 7.1 适用边界

只有可定位到具体动作的映射缺口允许进入部分同步，例如：

- 未找到映射行；
- `MAPPING_NOT_APPROVED`；
- active 的 `UNMAPPED`；
- 被策略禁用的映射；
- CATEGORY 降级未开启。

以下错误不得包装成部分成功：

- Garmin 鉴权、限流、网络或服务异常；
- 来源冲突、远端对象冲突；
- 非法字段或无法安全生成 Workout；
- 回读结构不符；
- 其他无法明确隔离到单个动作的系统错误。

### 7.2 同步状态与缺口记录

同步结果至少区分：

- `synced`：所有适用且应写入的动作均已写入；`not_applicable` 正常排除不影响该状态。
- `partial`：至少一个适用动作被跳过，且其余可写动作已成功写入并回读通过。
- `failed`：未形成可接受的部分同步结果，或发生系统级错误。

同步记录必须保存结构化信息：

```json
{
  "written_movements": ["哑铃卧推"],
  "skipped_movements": [
    {"name": "颈弯举", "reason": "UNMAPPED", "detail": "no_safe_category"}
  ],
  "excluded_movements": [
    {"name": "腿部拉伸", "reason": "not_applicable"}
  ]
}
```

具体字段**不得复用现有 `payload_json`**。该字段存的是「期望 Workout payload」，有两个既有消费方，混入同步结果会破坏它们：

- `run_plan_sync()` 用 `json.loads(record.payload_json)` 作为期望结构，与远端回读做等价比较；
- `_extract_xunji_names_from_payload()` 遍历 `workoutSegments[].workoutSteps[].description` 提取训记动作名，供 `mapping_hash` 与 stale 判定使用。结构被破坏时该函数返回 `None`，stale 判定会**静默失效**。

应新增独立字段（如 `sync_result_json`），语义与 `JobRun.detail_json` 一致：记录本次运行的结构化结果，不参与期望 payload 的重放与对账。三类动作不得混成一个警告列表。

边界行为：

- 一天只有 `not_applicable` 动作时，按正常无操作处理，不创建空 Workout，不记为缺口。
- 一天有适用动作但没有任何动作可写时，不创建空 Workout，返回带缺口清单的失败结果。**该判定必须发生在任何远端写操作之前**（`claim_plan_sync` 内、`create_workout` 之前）：不得先创建空 Workout 再删除——删除不可逆，且会白白消耗一次写入配额。
- Workout 名称可以追加“（缺 N 个动作）”作为远端辅助提示；N 只统计真正跳过的适用动作。本地结构化记录仍是事实来源。
- 补全后必须移除缺口标题标记，并恢复 `synced`；不得让历史标题永久误报不完整。

### 7.3 幂等与恢复

继续沿用现有机制：

1. 本地有 `workout_id` 时，核对来源后走完整 JSON 原地更新，不新建 Workout。
2. 本地无 ID 或创建响应丢失时，先通过 `source_key` 对账并认领唯一远端 Workout；不明确时进入冲突，不直接重发创建请求。
3. 更新后回读远端，展开为“动作 + 逐组”序列，与期望结构做等价比较；失败时报告 `GARMIN_WORKOUT_READBACK_INVALID`。
4. 映射补齐后的再次同步使用同一条同步记录和同一来源键，并基于最新完整计划重新生成期望 payload。

“已有 Workout 级和崩溃恢复级幂等”与“部分内容补全已验证”是两个结论。后者必须通过本 ADR §12.3 的专项验收后才能关闭。

## 8. 静态 JSON 的新增、删除与改名

不建设运行时扫描。`xunji_movements.json` 发生变更时，由部署或 CI 检查执行：

1. 解析变更前后的 JSON，比较动作名称集合，而非直接依赖文本行 diff。
2. 输出新增名称、消失名称和未变化名称。
3. 对“消失 + 新增”生成疑似改名候选，可结合字面相似度、器械和动作词根，但不得自动继承映射。
4. 人工选择“改名 / 新动作 / 删除”：
   - **改名**：保留内部 `exercise_mapping.id`，更新 `xunji_name`，在审计快照中记录旧名；Garmin 目标未变时不重置 `verified_level`。
   - **新动作**：创建新的 draft 或明确处理行，进入正常匹配与审核流程。
   - **删除**：保留历史映射和审计，不再作为当前动作参与同步；不得物理删除历史依据。
5. 文件变更检查必须产生明确失败或必须确认的待办，不能只生成无人处理的报告。

第一期复用内部数据库 `id` 和 `exercise_mapping_audit` 保存改名前后名称即可，不建设独立别名管理模块。若未来需要按旧名称持续查询，再增加别名存储。

## 9. Garmin 目标变化与验证等级

修改 `garmin_category` 或 `garmin_exercise_name` 时：

1. `mapping_version` 递增并记录审计；
2. 旧 `verified_level` 和旧 `verified_at` 不得直接继承；
3. 新目标通过目录校验后设为 `catalog`，未通过时设为 `none`，且不得保持 active；
4. 后续真实创建或目视验证完成后，再分别升级为 `created` 或 `displayed`；
5. 只修改训记名称且 Garmin 目标不变时，不重置目标验证等级；
6. 已有同步是否重发仍沿用 `mapping_hash/stale` 和用户显式确认机制，不自动覆盖历史 Garmin 对象。
7. 仅修改 `weight_strategy`、`confirmed` 备注、`relation`、`match_basis` 或 `unmapped_reason` 时，Garmin 目标未变，**不重置** `verified_level`（`weight_strategy` 只决定写入时的重量语义，与目标身份无关）。

## 10. 存量迁移策略

采用 **B：继承既有使用政策**，但不伪造逐条人工确认。

### 10.1 迁移规则

**`relation` 回填必须使用确定性判据**（否则「约 245 / 约 47」无法复现，§15 也无从用实测值替换估算）。判据复用候选生成器已有的判定函数，保证可复现、可回归：

**输入范围**：仅本次存量迁移的 292 条 active 行（全部已有具体 Garmin 目标）。该判据**不**用于判定 `UNMAPPED` 与 `CATEGORY`；执行前应断言这批记录中不存在需要判为 `CATEGORY` 的行（存在则单列并人工处理，不得落入 `EXACT`）。

```python
tokens = extract_tokens(name)
postures = [p for p in tokens["postures"] if p]
display_norm = _norm(garmin_display_name or "")

posture_mismatch = bool(postures) and any(
    _norm(posture) not in display_norm
    for posture in postures
)

is_similar = (
    equipment_mismatch_note(name, garmin_display_name) is not None  # 内部自行归一化，传原始名
    or _qualifier_penalty(name, display_norm) < 0                   # 必须传归一化串
    or posture_mismatch
)
relation = "SIMILAR" if is_similar else "EXACT"
```

> **两个必须避开的实现陷阱（均已实测）**：
>
> 1. `_qualifier_penalty()` 的第二个参数是 `name_norm` 而不是原始显示名。传入原始串时，因大小写与连字符差异，**全部限定词都会漏判**——同一行「Behind-the-Back Smith Machine Shrug」传原文得 `0`、传 `_norm()` 得 `-20`。整个限定词检查会静默失效。
> 2. **不能用「`_posture_bonus()` 是否触发 +40」反推姿态不符**。该函数在 `postures` 为空时直接返回 `0` 且不触发 +40，而「哑铃卧推」「杠铃卧推」「深蹲」这类动作本来就没有姿态词——按此反推会把它们全部误判为 `SIMILAR`。必须先用 `bool(postures)` 作前提。

**该判据的效力边界**：它给出的是**可复现的存量初始回填基线**，不代表语义真值。已知误配（§11 的回归清单）与人工复核结论优先于脚本结果；脚本应固定输入范围并输出异常清单；后续规则函数发生变化时，**不得静默重写历史迁移结论**，只能生成待复核差异。

- 对旧规则下 292 条 active 映射回填 `relation`。
- 回填为 `EXACT` 且目标有效的记录保持 active，保留原有来源和验证信息。
- 回填为 `SIMILAR` 的存量 active 记录保持 active，标记为有损，决策来源记为 `human_policy`，含义是“继承此前宁可名称不精确也保持可同步的批量使用政策”。
- `human_policy` 不等于 `human`，不得展示为“用户已逐条语义确认”。
- 已确认存在实际误配的记录不受 B 保护，必须修正或退回审核；B 只继承可用性政策，不豁免已知错误。
- Garmin 目标无效的记录不得继续保持 active。
- 迁移后 AI 审核可以提出更优候选，但不得自动覆盖这些记录。
- 后续新增的 SIMILAR 提议不得援引 B 批量自动激活；B 仅适用于本次存量迁移。
- 回填脚本必须幂等：重复执行不改变已有 `relation`；且只处理 `relation IS NULL` 的行，不得覆盖人工调整过的值。

### 10.2 迁移报告

迁移完成后输出实际数量，不预先写死估算值：

- EXACT / SIMILAR / CATEGORY / UNMAPPED 各多少；
- active / draft / disabled / not_applicable 各多少；
- `human_policy` 继承多少；
- 因目标无效或已知误配而退出 active 的明细；
- 仍需人工审核的高风险清单。

覆盖率必须按适用性和语义关系分项展示，不得只报 high 占比或笼统“已映射率”。

## 11. AI 审核与回归资产

AI 只作为只读审核员或候选提议者，不直接改变 active 映射。输出至少支持：

- 当前映射合理；
- 存在更贴切候选；
- 当前映射疑似错误；
- 可能没有 Garmin 对应；
- 信息不足，需要人工判断。

所有候选必须来自真实 Garmin 目录并经过结构校验。AI 结果应保存理由和版本信息，人工或规则确认后才进入正式映射。

已确认的真实错例必须固化为回归用例，至少覆盖：

- 力量器械划船不得进入有氧划船机分类；
- 绳索夹胸不得映射为训练后束的反向飞鸟；
- 吊环弯举不得映射为腿弯举；
- 上斜、下斜等姿态不得被静默当作完全等价；
- TRX 后束飞鸟不得映射为 Chest Fly；
- 其他后续确认错例持续加入，不得只修改提示词而不留测试。

## 12. 最低验收清单

### 12.1 映射与迁移

- [ ] `ALIAS` 只作为 `match_basis`，不存在 `relation='ALIAS'`。
- [ ] high + SIMILAR 不会被批量自动确认。
- [ ] high + EXACT + 目标有效 + 无风险标记才允许批量自动确认。
- [ ] 人工或政策接受的 SIMILAR 可保持 active，且有损标记清晰可见。
- [ ] CATEGORY 经确认且开关开启时可写入；开关关闭时按缺口处理。
- [ ] 存量迁移实际数量与报告一致，`human_policy` 不被展示成逐条人工确认。
- [ ] Garmin 目标改变后验证等级按 §9 重置，目标无效时不得保持 active。

### 12.2 正常排除与部分同步

- [ ] 力量动作 + 腿部拉伸：力量动作正常写入，拉伸进入 excluded，不触发 partial。
- [ ] 只有拉伸等 not_applicable 动作：正常无操作，不创建空 Workout，不报告映射缺口。
- [ ] 可写动作 A + 无映射动作 B：A 写入，结果为 partial，B 进入 skipped，标题和本地记录均可见缺口。
- [ ] 鉴权、限流、网络、非法字段和回读错误不得被记为 partial 成功。
- [ ] 所有适用动作均不可写时，不创建空 Workout，并返回完整缺口清单。

### 12.3 部分同步补全

必须完成以下端到端用例：

1. 首次同步缺少动作 A，其余动作写入成功，结果为 partial；
2. 保存 skipped 清单和远端 `workout_id`；
3. 补齐 A 的映射并再次确认同步；
4. 仍使用同一个 `workout_id`；
5. 回读确认 A 恰好出现一次，其他动作和组次没有重复或残留；
6. 状态从 partial 恢复为 synced；
7. Workout 名称中的缺口标记被移除；
8. 最新完整 payload 与远端结构等价比对通过。

### 12.4 静态文件变化

- [ ] 新增动作被识别并建立待处理行。
- [ ] 消失 + 新增只生成疑似改名候选，不自动继承。
- [ ] 人工确认改名后内部 mapping id 不变，旧名进入审计。
- [ ] 删除动作保留历史映射和审计。
- [ ] JSON 仅排序或格式化变化时不产生动作集合误报。

## 13. 后果

### 正面影响

- 单个新动作、无候选动作或拉伸动作不再阻塞整天训练。
- “算法很确定”“动作完全等价”“目录目标存在”“真机显示正确”成为四个可独立判断的事实。
- 存量有损映射可以继续使用，同时保留真实语义和审计口径。
- 部分同步具备明确恢复路径，不需要重建幂等体系。
- AI 的价值集中在压缩审核队列，风险被限制在提议层。

### 代价与约束

- `SIMILAR` 和 `CATEGORY` 会让 Garmin 中的动作名称或统计粒度变粗，必须持续可见。
- 部分同步需要维护缺口、标题标记和恢复状态，结果模型比二值成功/失败复杂。
- 静态 JSON 变更仍需人工处理疑似改名，只是处理频率低，并非完全自动化。
- 存量 B 策略意味着部分有损映射会继续 active，需要后续按实际使用和 AI 审核结果逐步精确化。

## 14. 与既有文档的关系

本 ADR 被接受后，取代或调整 `docs/EXERCISE-MAPPING-PLAN.md` 中以下旧决策：

- “只有 active 才能写入”补充为：active 决策仍受 relation 和 CATEGORY 开关约束；无法写入的动作进入部分同步，而非整日阻塞。
- §7.3 中“draft 命中阻断写入”调整为：draft 动作本身不写入，其余动作按本 ADR 部分同步。
- 任何仅凭 `confidence='high'` 批量激活的旧规则，由本 ADR §5 取代。
- 仅按 confidence 报告覆盖质量的方式，由按 relation、status、verified_level 和适用性分项报告取代。

以下既有决策保持不变：

- 静态映射主表和 mapper 纯函数边界；
- Garmin 枚举键、重量语义及 assisted 的独立安全约束；
- `source_key`、远端认领、更新、回读和冲突处理；
- 映射修改后的审计、`mapping_hash/stale` 和用户显式重同步确认；
- 非力量动作本期不写入力量 Workout。

## 15. 定稿前核对项

以下不再属于架构分歧，而是实现核对与验收事项：

- 逐项核对本 ADR 对现有代码的事实描述，发现不一致时修正文档或登记偏差，不得把目标行为写成已实现。
- 以实际迁移结果替换 292、约 245、约 47 等评审口径数量。
- 验证 `partial → 补全` 专项用例后，才能宣称内容级恢复闭环。
- 将 P0/P1/P2 拆为具体切片时，保持本 ADR 的字段语义和默认策略，不再引入 `relation='ALIAS'` 或以 verified_level 代替语义审核。
