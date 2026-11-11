# 训记训练计划同步 Garmin Connect：正式迁移与开发方案

> 日期：2026-11-10  
> 状态：主后端已切换 Python 3.12；P2/P3 完整真实训练日及 Connect/FR955 目视验收均通过；当前计划 15 个动作全部完成端到端验证；D2 阶段 1 的顺延后端、计划页前端及 FakeGarmin/模拟浏览器验收已完成；独立 P4 真实改期及 P5 真实连续两次改期均已完整通过；`syncing` 15 分钟超时自动恢复已完成本地/API/FakeGarmin 验证；P6 真实进程杀死、独立恢复、远端唯一性 API/ID 回读及 Connect/FR955 目视均已通过；功能开关默认关闭；生产镜像、Compose、CI 与服务器灰度适配 P7–P9 待完成  
> 适用范围：个人自托管、单用户、中国区 Garmin Connect（`garmin.cn`）

## 1. 结论与推荐行动

推荐采用 **`garminconnect 0.3.20` + 原始 Workout JSON 映射 + 本地同步状态表**，实现训记计划到 Garmin Connect 的单向同步。

MVP 采用 **逐训练日“预览 → 确认同步”**，不默认开启自动批量同步。首个版本只支持已明确映射的力量动作，遇到未知动作或不明确的重量语义时阻止同步并列出原因，绝不静默丢弃动作或组次。

长期将现有 Garmin 读取链路也迁移到 `garminconnect 0.3.20`，最终移除对停止维护的 `garth` 的依赖。迁移期间保留旧代码和旧 token 作为回滚手段，但不让新旧两套客户端同时向 Garmin 写入。

### 1.1 已确定的技术决策

| 决策项 | 选择 |
|---|---|
| 接入方式 | 非官方 `garminconnect 0.3.20`，不使用 Tredict，不依赖 Garmin 官方 API 审批 |
| Python | 升级到 Python 3.12；新版库要求 `Requires-Python: >=3.12` |
| Workout 构造 | 项目内显式构造并校验原始 JSON，暂不依赖新版库的 typed workout 构建器 |
| 同步方向 | 训记计划 → Garmin；不把 Garmin 上的修改反向写回训记 |
| 触发方式 | MVP 每个训练日手动预览并确认；自动同步作为后续可选项 |
| 更新策略 | 同一训练日原地更新 Workout，保留 `workoutId` 和已有日程 |
| 未训练顺延 | 已同步训练跨日顺延复用同步记录、`workoutId` 和原日程 ID，必须经用户确认后改期；阶段 1 后端、计划页前端与模拟验收已完成，P4 真实 API 与 ID 回读已通过，Connect/FR955 目视验收已通过，见 7.2 |
| 删除策略 | 不自动删除训练或日程；若 Garmin 不支持原日程改期，替换旧日程必须单独明确确认 |
| 未映射动作 | 整次同步失败并列出动作，不使用猜测枚举，不跳过动作 |
| 凭据 | 密码继续只放 `.env`；新版 token 使用独立目录，不与旧 garth token 混用 |
| 依赖移除 | 新版读取、写入、token 持久化和回归全部通过后，再移除 garth |

## 2. 已完成的 P0 证据与剩余未知项

### 2.1 已实测通过

| 验证项 | 结果 |
|---|---|
| 旧 garth 0.8.0 中国区 token 恢复 | 通过 |
| 创建力量训练 | 通过，测试 `workoutId=38210859` |
| 安排到日历 | 通过，`workoutScheduleId=34827528`，日期 `2026-11-11` |
| 训练结构 | 杠铃卧推 2 组 × 8 次，休息 60 秒 |
| 新版 garminconnect 0.3.20 中国区密码登录 | 更新密码后通过，未要求 MFA |
| 新版读取 Workout | 通过 |
| 新版原地更新完整 Workout JSON | 通过，训练 ID 保持不变 |
| 新版按日程 ID 回读 | 通过，原日程保留 |
| 重量单位 | `weightValue=20.0` + `weightUnit.unitKey=kilogram` 正确；`20000.0` 会显示为 20,000 kg |
| Connect / FR955 显示 | 用户已于 2026-11-10 11:20 确认 20 kg 显示正常 |

P0 产物：`scripts/p0_garmin_workout_probe.py`、`scripts/p0_garmin_weight_fix.py`、`outputs/garmin_p0/weight_fix_result.json`。

### 2.2 P1 新版写入实测（2026-11-10）

使用独立 Python 3.12.14 环境和 `garminconnect 0.3.20`，通过 `scripts/p1_garmin_workout_write.py` 对中国区账号完成真实写入：

| 验证项 | 结果 |
|---|---|
| 新版创建力量训练 | 通过，`workoutId=38212646` |
| 新版创建日程 | 通过，`workoutScheduleId=34829391`，日期 `2026-11-12` |
| 来源与名称 | `xunji-plan:p1:manual:2026-11-12`；`P1-XUNJI-STRENGTH-20261112` |
| 训练结构 | 杠铃卧推 2 组 × 8 次，初始重量 20 kg |
| 原地更新 | 重量由 20 kg 更新为 22.5 kg，Workout 和日程 ID 均不变 |
| token 持久化与重启恢复 | 通过；不提供密码的新进程仅凭已保存 token 恢复成功 |
| 远端删除 | 未执行；P0 对象 `38210859 / 34827528` 也未被修改 |

P1 报告：`outputs/garmin_p1/workout_write_result.json`。真实 token 位于本地隔离目录，不属于交付物，不应读取、打印或提交。

### 2.3 P2 完整真实训练日实测（2026-11-10）

主后端 `backend/.venv` 已切换为 **Python 3.12.14 + garminconnect 0.3.20**，旧环境保留在 `backend/.venv-py311-backup`，未删除。通过 `scripts/p2_garmin_full_day_sync.py` 和正式同步状态机完成：

| 验证项 | 结果 |
|---|---|
| 真实来源 | `universal:1`，2026-11-10「胸·三头·腹肌·2」 |
| 完整结构 | 8 个动作、27 组，其中热身 2 组、正式组 25 组，7 个 RepeatGroup |
| Workout | `workoutId=38213123` |
| 日程 | `workoutScheduleId=34829874`，日期与 Workout 关联回读通过 |
| 逐组语义对账 | 动作、组序、组类型、kg 重量、次数和休息与训记源 27 组逐项一致 |
| 真实冲突与恢复 | 首次创建后 Garmin 将通用 Bench Press 的 `exerciseName` 规范化为空串，状态机在排程前进入 `conflict`；增加精确回读别名和回归测试后，复用原 Workout 恢复，没有重复创建 |
| 功能开关 | P2 为显式专用脚本执行，未修改应用配置，`GARMIN_PLAN_SYNC_ENABLED` 仍默认关闭 |
| 目视验收 | 用户已于 2026-11-10 15:32 确认 Connect 与 FR955 显示正常 |
| 远端删除 | 未执行；P0/P1 对象未被删除 |

P2 报告：`outputs/garmin_p2/full_day_sync_result.json`；专用回读样本：`outputs/garmin_p2/remote_workout_38213123.json`。

### 2.4 P3「腿·肩」完整真实训练日实测（2026-11-10）

通过 `scripts/p3_garmin_full_day_sync.py` 和正式同步状态机完成：

| 验证项 | 结果 |
|---|---|
| 真实来源 | `universal:1`，2026-11-11「腿·肩」 |
| 完整结构 | 7 个动作、24 组，全部为正式组，7 个 RepeatGroup |
| Workout | `workoutId=38213537` |
| 日程 | `workoutScheduleId=34830266`，日期与 Workout 关联回读通过 |
| 逐组语义对账 | 动作、组序、组类型、kg 重量、次数和休息与训记源 24 组逐项一致 |
| 真实冲突与恢复 | 首次创建后 Garmin 将两个 Lateral Raise 步骤的 `exerciseName` 规范化为空串，状态机在排程前进入 `conflict`；增加精确回读别名和回归测试后，复用原 Workout 恢复，没有重复创建 |
| 自动化回归 | `tests/test_garmin_workout_mapper.py`：22 passed |
| 功能开关 | P3 为显式专用脚本执行，未修改应用配置，`GARMIN_PLAN_SYNC_ENABLED` 仍默认关闭 |
| 目视验收 | 用户已于 2026-11-10 15:58 确认 Connect 与 FR955 显示正常，7 个动作升级为 `p3_verified` |
| 远端删除 | 未执行；P0/P1/P2 对象未被删除 |

P3 报告：`outputs/garmin_p3/full_day_sync_result.json`；专用回读样本：`outputs/garmin_p3/remote_workout_38213537.json`。

### 2.5 真实前端与幂等 POST 验收（2026-11-10）

本地计划只有已验收的 2026-11-10 和 2026-11-11，没有第三个未同步训练日，因此使用 P3 做正式前端预览和幂等 POST 验收，不制造重复训练。通过 `scripts/validate_garmin_real_ui.mjs` 启动临时真实后端、Vite 和无头 Chrome；后端只在验收进程内开启写入开关并关闭调度器，未修改 `.env`，持久开关仍为关闭。

| 验证项 | 结果 |
|---|---|
| 真实页面与数据 | `/plans` 显示「腿·肩」和「Garmin · 已同步」；预览为真实 API 数据，无响应 Mock |
| 预览内容 | 7 个动作均显示「已端到端验证」、0 个「待远端验收」，24 组及原 Workout/日程 ID 正确 |
| 预览写入边界 | 幂等 POST 前 Garmin 非 GET 请求为 0，已同步状态不显示确认写入按钮 |
| 幂等 POST | HTTP 200、`started=false`、`status=synced`；`attempt_count` 前后均为 2 |
| ID 保持 | Workout `38213537`、日程 `34830266` 在 POST 前后不变 |
| 远端复核 | 再次只读回读 Workout 和日程，24 组语义、日期及关联全部通过；未创建或删除远端对象 |
| 桌面与移动端 | 均无横向溢出，移动端弹层适配，Escape 关闭后焦点恢复，运行时异常 0 |
| 全量回归 | 前端 437 passed（49 个文件），lint 0，生产构建通过 |
| 清理 | Chrome、Vite、后端均停止；7100、8000、9228 端口确认关闭 |

报告：`outputs/garmin_real_ui_validation/real-ui-validation.json` 和 `remote-readback.json`；桌面/移动端截图位于同目录。

### 2.6 顺延前端与模拟浏览器验收（2026-11-10）

复用现有 `GarminPlanPreviewModal` 完成顺延闭环：计划页显示“顺延待确认 / 确认顺延 / 恢复顺延 / 查看顺延”，弹层展示原日期、目标日期、完整组次和原 Workout/日程 ID；确认只调用专用改期 POST，随后轮询目标日状态。失败可恢复，轮询失败可手动重新获取；旧哈希或运行中响应会重新加载预览，冲突、已同步、源移除和写入关闭状态不提供写入按钮。404 与其他错误均保留并展示结构化 detail。

| 验证项 | 结果 |
|---|---|
| 前端定向回归 | 顺延、普通同步、计划页和 API 共 33 passed；新增顺延交互 5 项 |
| 前端全量回归 | **442 passed（50 个文件）**，lint 0，生产构建及 Capacitor 配置校验通过 |
| 模拟浏览器写入边界 | 桌面与移动端确认前写入均为 0；桌面确认 POST 恰好 1 次，body 为 `to_date + source_hash`，目标日轮询 1 次后完成 |
| 桌面与移动端 | 原/目标日期、完整组次、保留 ID 和“不创建或删除”语义正确；弹层完整位于视口内，无横向溢出，移动端确认/关闭触控高度不低于 44 px |
| 可访问性与稳定性 | Escape 关闭并恢复焦点，滚动锁定正常，运行时异常 0 |
| 首屏定位修复 | 弹层通过 Portal 挂到 `document.body`，避免页面进入动画的 transform 影响 fixed 定位；桌面首屏 top=36 px、bottom=864 px（900 px 视口） |
| 验收边界 | 仅模拟 API 和浏览器，不调用真实 Garmin，不修改真实同步记录，不创建或删除远端对象；临时 Vite/Chrome 已停止，7100/9229 端口关闭 |

报告：`outputs/garmin_reschedule_ui_validation/browser-validation.json`；桌面、完成态和移动端截图位于同目录，脚本为 `scripts/validate_garmin_reschedule_browser.mjs`。

### 2.7 P4 独立真实原日程改期验收（2026-11-10 API 与 ID 回读通过，2026-11-11 目视通过）

通过 `scripts/p4_garmin_reschedule.py` 在中国区创建唯一 P4 专用 Workout 和原日期日程，再使用正式 `detect_reschedule_candidates → claim_reschedule → run_reschedule` 状态机完成改期。本地状态使用隔离的 `outputs/garmin_p4/p4-validation.db`，未使用正式 `backend/data/app.db`。

| 验证项 | 实测结果 |
|---|---|
| 独立来源与日期 | `xunji-plan:v1:p4:manual:2026-11-14` → `xunji-plan:v1:p4:manual:2026-11-15`；2026-11-14 → 2026-11-15 |
| Workout | `workoutId=38217702`，改期前后保持不变；名称为 `训记｜P4-XUNJI-RESCHEDULE｜2026-11-15` |
| 日程 | `workoutScheduleId=34834456`，改期前后保持不变；原日程回读日期为 2026-11-14，最终为 2026-11-15 |
| 旧/新日期日程 | 改期后原日期日程 0 个，目标日期日程 1 个，且关联原 Workout ID |
| 训练语义 | 杠铃卧推 2 组 × 8 次、20 kg、休息 60 秒；完整回读、目标来源键及目标哈希一致 |
| 正式 runner 写入 | Workout 原地更新 1 次、原日程改期 1 次；runner 内创建 Workout 0 次、创建日程 0 次 |
| 本地状态 | `reschedule_pending` 唯一候选 1 个；最终 `synced`，日期与来源键切换到目标日，`reschedule_from/to` 审计字段保留 |
| 安全边界 | 未写入 P0/P1/P2/P3 保护对象，未删除任何远端对象；功能开关未修改 |
| 目视验收 | 用户已于 2026-11-11 05:37 确认 Connect 与 FR955 显示正常，完整 P4 已关闭 |

报告：`outputs/garmin_p4/reschedule_result.json`；最终远端样本为同目录 `remote_workout_38217702.json` 和 `remote_schedule_34834456.json`。

### 2.8 尚未验证或尚未实现，不能视为已完成

- refresh token 自动续期；已验证的是保存 token 后的进程重启恢复。
- 新版库下现有活动、睡眠、HRV、Body Battery 等读取链路的完全等价性，旧 garth 读取尚未平移。
- MFA 完整流程；当前账号本次登录没有触发 MFA，实现会直接停止并要求人工处理。
- 计时动作、单边动作、AMRAP、超级组及非 kg 单位。
- 首次自动关联仍要求跨日 `content_hash` 相同；只有已建立顺延关联后，目标日内容继续变化才保留候选并等待确认。首次“日期与内容同时变化”的自动关联尚未开放。
- `source_removed` 目前只有状态视图。FakeGarmin 已覆盖更新/改期响应丢失、超时恢复及旧 runner 隔离；P6 真实进程杀死、独立恢复、远端唯一性 API/ID 回读及 Connect/FR955 目视均已通过，见 2.12。

### 2.9 连续顺延增强（2026-11-11，本地/API/FakeGarmin 通过）

首次改期成功后，`reschedule_from_date` 会保留上一轮审计来源。旧实现生成第二轮候选和状态视图时误用该审计日期，而同步记录已经移动到上一轮目标日期，导致第二轮确认可能按最早日期查不到记录。现将**活动顺延**的来源日期统一改为当前 `training_date`；完成态仍保留审计日期用于最新一轮旧地址幂等，不改变首轮检测、`content_hash`、确认、远端写入或恢复规则。

- 新增完整两轮改期测试：2026-11-10 → 2026-11-11 → 2026-11-12；第二轮候选、状态、预览和确认均以上一轮目标日为来源，Workout `workout-old`、日程 `schedule-old` 始终不变。
- 两轮 runner 各更新原 Workout 和原日程一次；创建 Workout 0 次、创建日程 0 次，本地同步记录始终 1 条，JobRun 2 条；第二轮成功后的旧地址重放 `started=false`，attempt 和远端调用不增加。
- 新增第二轮候选 API 合约测试，确认 `/api/plans/garmin/reschedules` 和目标日 `/garmin/sync` 均返回当前来源日期，检测及 GET 零 Garmin 外呼。
- 顺延专项结果：**26 passed**。前端全量 **442 passed（50 个文件）**，lint 0 错误、生产构建和 Capacitor 校验通过。
- 后端全量结果：**1143 passed、6 skipped、1 failed，覆盖率 90.69%**。唯一失败为既有 `TestDailyRegenLimit.test_real_closed_loop_5_ok_then_429`：本地清晨运行时，SQLite `func.now()` 的 UTC 日期与 `date.today()` 的本地日期跨日，导致 AI 点评每日重生成限流未按测试预期触发；该测试单独运行同样失败，与本次 Garmin 文件改动无关，本轮未扩大范围修改。
- 验收边界：只使用临时 SQLite 和 FakeGarmin，未读取正式 `backend/data/app.db`，未访问真实 Garmin，未创建、修改或删除任何远端对象；真实连续改期由 2.10 的 P5 单独验收。

### 2.10 P5 真实连续两次原日程改期验收（2026-11-11，完整通过）

通过 `scripts/p5_garmin_consecutive_reschedule.py` 在中国区创建唯一 P5 专用 Workout 和原日期日程，再连续执行两轮正式 `detect_reschedule_candidates → claim_reschedule → run_reschedule` 状态机。隔离数据库为 `outputs/garmin_p5/p5-validation.db`，未使用正式 `backend/data/app.db`。

| 验证项 | 实测结果 |
|---|---|
| 日期链 | 2026-11-16 → 2026-11-17 → 2026-11-18；来源键同步逐轮切换 |
| Workout | `workoutId=38222333`，两轮前后均保持；最终名称为 `训记｜P5-XUNJI-CONSECUTIVE｜2026-11-18` |
| 日程 | `workoutScheduleId=34839305`，两轮前后均保持；初始日期 2026-11-16，最终日期 2026-11-18 |
| 第一轮 | 候选来源 2026-11-16、目标 2026-11-17；原 Workout 更新 1 次、原日程改期 1 次，创建均为 0；审计来源 16 日 |
| 第二轮 | 候选来源 2026-11-17、目标 2026-11-18；原 Workout 更新 1 次、原日程改期 1 次，创建均为 0；审计来源更新为 17 日 |
| 最终日程数量 | 2026-11-16 为 0、2026-11-17 为 0、2026-11-18 为 1，且关联原 Workout |
| 训练语义 | 杠铃卧推 2 组 × 8 次、20 kg、休息 60 秒；每轮及最终完整回读均一致 |
| 本地状态 | 最终 `synced`，同步记录 1 条、JobRun 2 条、attempt 3，最终来源键和哈希正确 |
| 安全边界 | 初始化仅创建 P5 Workout/日程各 1 个；未写入 P0/P1/P2/P3/P4 保护对象，未删除任何远端对象，功能开关未修改 |
| 目视验收 | 用户已于 2026-11-11 06:25 确认 Connect 与 FR955 显示正常，完整 P5 通过 |

报告：`outputs/garmin_p5/consecutive_reschedule_result.json`；最终远端样本为同目录 `remote_workout_38222333.json` 和 `remote_schedule_34839305.json`。

### 2.11 `syncing` 超时自动恢复（2026-11-11，本地/API/FakeGarmin 通过）

- 默认阈值 **900 秒（15 分钟）**，可通过 `GARMIN_PLAN_SYNC_STALE_SECONDS` 调整。状态查询、upcoming、顺延列表/预览及再次确认会惰性检查超时记录；超时只把本地 `syncing` 原子转为 `failed`，错误码为 `GARMIN_SYNC_INTERRUPTED`，不会自动调用 Garmin。
- 恢复保留 phase、payload、已保存 Workout/日程 ID、目标日期及顺延审计字段。用户重新确认后才沿用既有对账状态机继续，首次创建响应不确定时仍先按来源键对账，也不创建替代对象。
- 条件更新同时匹配 `updated_at + attempt_count`；先刷新数据库当前快照，CAS 失败最多再重检一次。恢复写入独立 JobRun，包含 `recovery=stale_syncing`、原 attempt 和脱敏远端 ID。
- 普通同步和顺延 runner 的完成写入均校验 attempt；旧 runner 即使较晚返回，也不能把已恢复或重新抢占的记录覆盖为 `synced/failed/conflict`。新抢占显式使用与超时判断一致的本地 naive 时间，避免数据库 UTC 默认值造成误判。
- 新增普通同步超时恢复、顺延超时恢复、API 状态转失败及重新确认、两个旧 runner 隔离测试。相关四文件 **35 passed**，Garmin 全量 **121 passed、1 skipped**。
- 后端全量 **1148 passed、6 skipped、1 failed，覆盖率 90.71%**；唯一失败仍为 2.9 记录的既有 AI 限流 UTC 跨日问题，本轮未扩大范围修复。
- 本轮只用临时 SQLite 和 FakeGarmin，未读取正式 `backend/data/app.db`，未访问真实 Garmin，未创建、修改或删除任何远端对象；真实进程杀死由 2.12 的 P6 独立验收。

### 2.12 P6 真实进程杀死与独立恢复验收（2026-11-11，完整通过）

通过 `scripts/p6_garmin_process_kill.py` 使用三个独立 Python 子进程生命周期，在真实 Workout 创建成功后、日程创建成功后分别强制终止进程；父进程只把隔离记录的 `updated_at` 快进到超过 900 秒，再由新进程经过正式超时恢复、重新确认和既有对账状态机继续。隔离数据库为 `outputs/garmin_p6/p6-validation.db`，未使用正式 `backend/data/app.db`。

| 验证项 | 实测结果 |
|---|---|
| Workout | `workoutId=38224225`；最终名称为 `训记｜P6-XUNJI-PROCESS-KILL｜2026-11-19` |
| 日程 | `workoutScheduleId=34841221`；日期 2026-11-19，关联原 Workout |
| 第一次真实杀死 | Workout 创建接口已返回远端 ID、marker 已原子落盘，但返回值尚未交给状态机时终止子进程；本地保持 `syncing`、attempt 1、Workout/日程 ID 均为空 |
| 第二次真实杀死 | attempt 2 按来源键认领原 Workout；日程创建接口返回后、状态机收到返回值前再次终止子进程；本地保留 Workout ID、日程 ID 为空 |
| 最终恢复 | attempt 3 再次按来源键复用原 Workout，并按 Workout+日期认领原日程，最终 `synced`；两次 `recovery=stale_syncing` JobRun 分别对应 attempt 1、2 |
| 创建与唯一性 | 全链路 Workout 创建成功 1 次、日程创建成功 1 次；最终来源候选 Workout 1 个、目标日日程 1 个、本地同步记录 1 条 |
| 训练语义 | 杠铃卧推 2 组 × 8 次、20 kg、休息 60 秒；独立父进程回读的名称、来源键/哈希、组次、重量、次数、休息、日程日期及关联全部一致 |
| 安全边界 | 只创建 P6 专用对象；未写入 P0–P5 保护对象，未删除任何远端对象，功能开关未修改 |
| 目视验收 | 用户已于 2026-11-11 09:46 确认 Connect 与 FR955 显示正常，完整 P6 通过 |

报告：`outputs/garmin_p6/process_kill_result.json`；最终远端样本为同目录 `remote_workout_38224225.json` 和 `remote_schedule_34841221.json`。

## 3. 现状与改造边界

### 3.1 当前可复用能力

- `backend/app/services/plans.py` 已能从 `xunji_plan` 本地缓存解析训练日，并将 `target_sets` 归一化为 `sets`。
- `backend/app/api/plans.py` 已有计划查询、缓存刷新、后台任务和状态轮询模式。
- `frontend/src/pages/PlansPage.jsx` 已展示未来 30 天训练计划。
- `backend/app/adapters/garmin_adapter.py` 已封装中国区登录、0.5 秒限速、429 退避、401/403 重登和统一异常。
- `backend/tests/fixtures/plan_get_real.json` 提供真实计划数据，包含逐组重量、次数、休息时间等字段。
- `job_run` 可记录同步留痕，现有 FIT/TCX/GPX/KML 手动导入仍可作为活动读取的降级通道。

### 3.2 当前不足

- 现有 `garmin_adapter.py` 活动与健康读取仍绑定 garth；新版写入由独立的 `garmin_workout_adapter.py` 承担，读取平移尚未完成。
- `source_removed` 只有状态视图。`syncing` 超时自动恢复已完成，P6 真实进程杀死及独立恢复 API/ID 回读已通过，Connect/FR955 目视已通过，见 2.11、2.12。
- 普通同步遇到已有日程日期或 Workout 关联不符仍进入 `conflict`；只有专用顺延确认端点可以改期。
- `settings.garmin_token_store` 未用于新版写入认证；新版独立使用 `GARMIN_WORKOUT_TOKENSTORE`。

## 4. MVP 功能范围

### 4.1 包含

1. 在训练计划的非休息日显示 Garmin 同步状态和“同步到 Garmin”入口。
2. 本地生成完整预览：每个动作、每一组、重量、次数/时长、休息和热身信息。
3. 用户确认后创建或原地更新一个力量训练，并安排到对应日期。
4. 重复点击保持幂等，不重复创建 Workout 或日程。
5. 训记计划变化后显示“有更新”，确认后原地更新远端训练。
6. 训记未训练自动顺延时，识别同一训练的跨日移动，显示“顺延待确认”，确认后保留 Workout ID 完成改期；连续顺延和歧义候选不得重复创建。
7. 上传或改期后回读 Workout 和日程，进行语义与日期校验，再标记成功。
8. 显示未映射、失败、冲突、顺延和可重试状态，提供不含敏感信息的错误原因。
9. 保留现有 Garmin 活动和健康数据同步行为。

### 4.2 明确不包含

- 不自动同步全部未来计划。
- 不自动删除或取消 Garmin 训练/日程。
- 不做 Garmin → 训记的反向同步。
- 不同步已完成活动，只同步计划 Workout 与日历安排。
- 不在首个版本支持未知动作、复杂课程、非力量运动或任意单位。
- 不把 Garmin 密码迁入数据库或前端设置页。

## 5. 总体架构

```text
训记计划缓存 xunji_plan
        │
        ▼
services/plans.py：选择并归一化计划日
        │
        ▼
garmin_workout_mapper.py（新增，纯函数）
  动作映射 / 逐组转换 / 校验 / canonical JSON / source_hash
        │
        ├── 预览 API：只读本地，零 Garmin 网络请求
        │
        ▼
garmin_plan_sync.py（状态视图与写入编排均已实现）
  状态查询 / 哈希比较 / 防重 / 对账 / 创建或更新
  分阶段落库 / 回读验证 / 失败恢复 / JobRun 留痕
        │
        ▼
adapters/garmin_workout_adapter.py（新版独立写入适配器）
  garminconnect 0.3.20 中国区认证 / 限速 / 异常 / Workout 与日程 API
        │
        ▼
Garmin Connect 中国区 + Garmin 日历 + FR955
```

### 5.1 模块职责

| 模块 | 责任 |
|---|---|
| `garmin_workout_mapper.py` | 纯本地转换、白名单映射、单位与组次校验、源哈希；不访问网络/数据库 |
| `garmin_plan_sync.py` | 普通同步状态机、幂等、远端对账、分阶段持久化、回读验证、活动顺延门禁和状态视图 |
| `garmin_reschedule.py` | 顺延候选、目标预览、确认抢占、原 Workout/日程改期、回读核验、审计幂等和恢复 JobRun |
| `garmin_workout_adapter.py` | 新版 Workout/日程写入窄接口、独立 token、限速、原日程改期和脱敏异常 |
| `garmin_adapter.py` | 既有 garth 活动与健康读取；保持现状，待后续平移 |
| `models.py` + Alembic | 计划同步记录及顺延审计字段，不改现有训练/活动表语义 |
| `api/plans.py` | 普通/顺延预览与状态 GET、普通/顺延确认 POST，沿用鉴权和后台任务模式 |
| `PlansPage.jsx` + `GarminPlanPreviewModal.jsx` | 状态徽标、完整预览、确认、轮询、更新确认和错误恢复 |

新版写入适配器对业务层提供窄接口：

```text
create_workout(payload) -> workout_id
get_workout(workout_id) -> dict
update_workout(workout_id, complete_payload) -> None
schedule_workout(workout_id, date) -> schedule_id
get_schedule(schedule_id) -> dict
find_schedules(workout_id, date) -> list[dict]
find_workouts_by_source_key(source_key) -> list[dict]
reschedule_schedule(schedule_id, date) -> None  # FakeGarmin 与真实 P4 API 已验证，Connect/FR955 目视验收已通过
delete_schedule(schedule_id) -> None  # 未实现；仅限未来明确确认的替换路径
```

`find_workouts_by_source_key` 和 `find_schedules` 只用于异常恢复和对账，不作为正常重复创建前的替代品；正常路径始终以本地 ID 为准。普通同步不自动改期，日期或关联不符进入 `conflict`。D2 适配器调用本机 `garminconnect 0.3.20` 已核实的 `reschedule_workout()`：库内回读完整日程、保留对象并仅替换 `calendarDate` 后 PUT；FakeGarmin 与独立 P4 真实 API 均已覆盖，Connect/FR955 目视验收已通过。`delete_schedule` 不得进入通用自动清理流程。

## 6. 认证与 token 安全方案

### 6.1 依赖与环境

- 新建 Python 3.12 虚拟环境，不在原 Python 3.11 环境内强行安装。
- 首个正式版本固定 `garminconnect==0.3.20`，避免未经验证的自动升级。
- 先共存 `garth` 和新库；读取回归与 token 重启测试通过后再删除 `garth` 及旧测试桩。
- 更新部署文档、CI Python 版本和生产依赖安装流程。

### 6.2 token 存储

- 新版写入适配器默认使用工作区 `outputs/garmin_p1/tokens/`，库实际保存为 `garminconnect-cn.json`；可用 `GARMIN_WORKOUT_TOKENSTORE` 覆盖路径。
- 旧目录 `~/.garminconnect` 保持不动，供迁移期回滚；禁止把旧 garth token 当作新版 token 使用。
- 调用 `Garmin(..., is_cn=True, return_on_mfa=True, retry_attempts=0)` 和 `login(tokenstore=...)`；P1 已验证 token 落盘及新进程无密码恢复，自动 refresh 仍待长期观察。
- token 文件只允许当前操作系统用户读写；不得进入 Git、日志、前端响应、JobRun 或普通数据库备份。
- `settings.garmin_token_store` 不参与该写入链路；独立路径只保存位置，不保存 token JSON 到配置或数据库。
- 密码继续从 `GARMIN_EMAIL` / `GARMIN_PASSWORD` 读取，默认 `GARMIN_DOMAIN=garmin.cn`。
- 认证成功后的客户端只在本进程复用；后台任务不共享 SQLAlchemy Session。

### 6.3 MFA 与密码变化

- `needs_mfa` 时直接停止同步并要求账号所有者人工处理，不自动循环登录；当前不持久化或返回 MFA `client_state`。
- 密码修改后优先尝试已保存 token；被拒绝时才重新凭据登录。
- GET/PUT 在 401、403、429 下最多进行一次有限恢复；创建 Workout/日程的 POST 不自动重发。仍失败则进入 `failed`，禁止暴力重试。

## 7. 数据模型与状态机

新增 `garmin_plan_sync` 表，采用增量、可回滚的 Alembic 迁移：

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `plan_ref` | 训记计划引用 |
| `training_date` | 计划训练日期 |
| `source_key` | 稳定来源标识，例如 `xunji-plan:v1:{plan_ref}:{date}`，唯一 |
| `source_hash` | 本次期望同步的规范化计划哈希，包含日期；跨日顺延后必须变化 |
| `content_hash` | 阶段 D2 新增：不包含日期、包含标题和完整训练处方的哈希，用于识别同一训练跨日移动 |
| `synced_hash` | 最后一次远端回读验证成功的哈希 |
| `payload_json` | 本次期望上传的 Workout JSON，不含凭据/token |
| `workout_id` | Garmin Workout ID，创建/对账成功后立即保存；顺延时保持不变 |
| `workout_schedule_id` | Garmin 日程 ID，安排成功后立即保存；优先改期保留，替换路径可能变化 |
| `reschedule_to_date` | 待确认、恢复中及已成功顺延的目标日期；成功前 `training_date` 保持原日期，成功后保留作审计 |
| `reschedule_from_date` | 阶段 1 新增：确认时的原日期；成功后用于旧 URL 幂等重放 |
| `reschedule_source_key` | 阶段 1 新增：确认时的原来源键；恢复时接受原/目标来源键并防止覆盖他人对象 |
| `previous_workout_schedule_id` | 替换日程降级路径的旧日程 ID，用于审计和崩溃恢复；阶段 1 不使用 |
| `status` | `pending/syncing/synced/reschedule_pending/failed/conflict/source_removed`；`update_available` 仅作为状态视图，不作为数据库持久状态 |
| `phase` | 最近执行阶段：`create/update/schedule/reschedule/verify` |
| `error_code` | 稳定的机器可读错误码 |
| `last_error` | 脱敏后的可读错误 |
| `attempt_count` | 尝试次数，不用于无限自动重试 |
| `created_at/updated_at/synced_at` | 审计时间 |

约束：`source_key` 唯一；`(plan_ref, training_date)` 唯一；ID 字段允许为空以覆盖首次创建失败，但不允许一条记录无来源键。迁移 `b4c5d6e7f8a9` 添加检测字段，`c5d6e7f8a9b0` 添加原日期/原来源审计字段，均不重写已有记录。顺延确认前保留原 `(plan_ref, training_date)` 和 `source_key`，目标日期已有其他记录时禁止覆盖；成功后才切换当前日期/来源键，并保留审计字段支持从旧 URL 重放返回 200。

### 7.1 状态判定

- 无记录且 `source_hash` 有效：未同步。
- `status=syncing`：同步中，重复请求返回 409。
- `synced_hash == source_hash` 且 ID 齐全：已同步。
- 已同步记录出现新的 `source_hash` 且日期不变：有更新，保留原 ID，等待确认更新。
- `status=reschedule_pending`：同一训练从原日期移动到 `reschedule_to_date`，等待用户确认；不得按新来源再次创建 Workout。
- `failed`：允许从已保存阶段继续，不盲目从头创建；顺延失败时保留目标日期和已保存远端 ID。
- `conflict`：远端对象与来源不匹配、目标日期冲突或存在多个候选，必须人工处理。
- 计划消失/结束且没有可唯一匹配的顺延候选：`source_removed`，保留远端对象，不自动删除。

### 7.2 训记未训练自动顺延（阶段 D2，阶段 1、P4 与连续顺延增强已完成，P5 完整通过）

2026-11-10 已完成本地检测以及阶段 1 闭环：顺延预览、确认 POST、原 Workout 更新、原日程改期、回读核验、失败恢复和成功后的旧地址幂等；计划页顺延弹层、日期对比、目标日轮询、冲突门禁和失败恢复也已完成。独立 P4 已进一步证明真实中国区原日程改期可用，API 回读、两个 ID 保持及 Connect/FR955 目视验收均通过。2026-11-11 连续顺延增强完成本地/API/FakeGarmin 验证：每一轮都从当前 `training_date` 重新识别和确认，上一轮审计日期不再误作新一轮来源；P5 真实连续两轮改期、逐轮来源及 ID 回读也已通过，Connect/FR955 目视验收均已通过。首次跨日关联仍只接受内容相同。

#### 7.2.1 场景边界

| 场景 | 目标行为 |
|---|---|
| 原日期尚未同步，训记顺延 | 新日期按普通未同步训练处理；无旧 Garmin 对象，不进入改期流程 |
| 原日期已同步但未完成，训记顺延一天 | 原记录进入 `reschedule_pending`，确认后复用 Workout 并调整日程 |
| 训练内容不变、仅日期变化 | 用 `content_hash` 识别顺延，不作为新训练创建 |
| 日期与内容同时变化 | 允许进入顺延待确认；确认后同时更新内容和日期，仍保留 Workout ID |
| 同一天内容变化但日期不变 | 仍走 `update_available`，不得误判为顺延 |
| 连续多天未做、连续顺延 | 每次基于当前记录重新识别和确认，始终复用同一 Workout ID |
| 多个相同候选、目标日期已有记录或远端关联不明 | 进入 `conflict`，不做任何写入 |
| 已完成活动 | 只跟随训记仍保留的计划状态，不根据 Garmin 活动自行推断完成或自动顺延 |

#### 7.2.2 顺延识别规则

1. 在训记计划缓存刷新时比较刷新前后的完整计划，不仅检查未来 30 天页面数据。
2. 候选必须满足：同一 `plan_ref`、原计划日从缓存消失、新计划日出现、两边 `content_hash` 相同，并且旧候选和新候选均唯一。
3. 自动提示优先限制为相邻一天顺延；跨更多日期或不符合唯一条件时只提示人工处理，不自动建立关联。
4. `content_hash` 只排除 `date`，保留计划引用、标题、动作顺序、逐组重量、次数、休息和组类型；`source_hash` 继续包含日期，不承担顺延识别职责。
5. 目标日期已有不同同步记录、Workout 或日程时返回 `RESCHEDULE_TARGET_CONFLICT`；存在多个等价候选时返回 `RESCHEDULE_CANDIDATE_AMBIGUOUS`，均不得写入。
6. 顺延识别只做本地检测和状态展示，不访问 Garmin，也不自动改期。

#### 7.2.3 状态与写入顺序

1. 当前检测通过时复用原同步记录：`training_date/source_key/source_hash/payload_json` 均暂保原值，`reschedule_to_date` 保存目标日期，状态改为 `reschedule_pending`；候选 API 根据目标计划动态计算目标 `source_hash`，不伪装已完成改期。
2. 用户确认时重新校验目标日期、唯一目标计划和完整 `source_hash` 并生成目标 payload；过期预览返回 409。原子 claim 保存 `reschedule_from_date/reschedule_source_key`，`pending/failed` 可启动，未超时的 `syncing/conflict` 返回 409；超时 `syncing` 先按 2.11 转为可恢复 `failed`。
3. 先回读原 Workout 和日程，核对原 ID、来源标记和关联；恢复时 Workout 来源可已经是原来源键或目标来源键，远端属于其他来源则进入 `conflict`。
4. 内容、名称、目标来源键或哈希不同时，使用完整 Workout JSON 原地 PUT，**保持 `workoutId` 不变**；随后回读完整组次与来源。不得调用创建 Workout。
5. 调用 `reschedule_schedule(schedule_id, target_date)` 保留原日程 ID，随后回读目标日期和 Workout 关联；若回读已在目标日期则不重复 PUT。阶段 1 不创建、替换或删除日程。
6. 真实 P4 已证明 Garmin 支持原日程改期，当前版本不开发替换降级路径，也不会隐式降级；若未来真实能力变化，只有后续用户明确确认“替换日程”及具体旧日程 ID 后才允许单独设计。
7. 全部回读通过后，才将本地 `training_date/source_key` 切换为目标值，写入 `synced_hash=source_hash`、`status=synced`，并在 JobRun 记录原/目标日期及所有相关 ID。`reschedule_from_date/reschedule_to_date/reschedule_source_key` 保留作审计；从旧 URL 以相同目标和哈希重放返回 200、`started=false`，不增加 attempt。
8. 任一步失败都保留目标日期、原/目标来源信息和已保存远端 ID；恢复先回读，已完成的 Workout PUT 或日程 PUT 不重复执行。进程崩溃遗留的永久 `syncing` 已支持 15 分钟超时自动恢复，旧 runner 完成写入受 attempt 隔离，详见 2.11。

#### 7.2.4 改期能力实测门禁

- 已完成：专用 P4 对象证明 Garmin 中国区支持原日程原地改期，未修改或删除 P0/P1/P2/P3 对象。
- API 与目视均已通过：Workout ID `38217702`、日程 ID `34834456` 均保持，旧日期日程为 0，新日期日程为 1；用户已于 2026-11-11 05:37 确认 Connect 和 FR955 显示正常。
- 本次支持原日程改期，因此不启动替换日程降级路径；若后续其他账号/设备实测不支持，必须单独展示旧日程 ID 并获得明确确认。
- FakeGarmin 已模拟 Workout 更新后和日程改期后的响应丢失，恢复不会产生第二个 Workout；P6 又在普通创建链路的 Workout/日程创建后分别真实杀死进程，独立恢复后两个远端对象均唯一，API/ID 回读通过，Connect/FR955 目视已通过，见 2.12。

## 8. 训记到 Garmin 的逐组映射

### 8.1 动作白名单

建立独立映射表：

```text
训记标准中文名 → { category, exerciseName, weight_strategy, support_level }
```

P0 已实测项（不属于当前 15 个计划动作）：

| 训记动作 | category | exerciseName | 重量策略 |
|---|---|---|---|
| 杠铃卧推 | `BENCH_PRESS` | `BARBELL_BENCH_PRESS` | 训记 `weight` 按 kg 原值传递 |

当前计划 15 个动作已形成用户确认白名单：`outputs/garmin_p0/garmin_exercise_whitelist.json` 保留当时的 `user_confirmed_catalog_pending_end_to_end` 历史状态。P2 目视验收后，代码中的 8 个当日动作已升级为 `p2_verified`；P3 目视验收后，其余 7 个动作已升级为 `p3_verified`，当前计划动作全部完成端到端验证。其中用户明确选择了站姿哑铃过头臂屈伸、通用 Bench Press、Cable Core Press 和 Incline Reverse Fly；完整逐组预览位于 `outputs/garmin_p0/daily_sync_preview.md`。

动作映射采用以下流程：

1. 汇总当前真实计划的动作覆盖率，优先映射用户实际使用动作。
2. 先检索 `garminconnect` 自带的 Garmin Connect Workout 编辑器动作字典，并只读提取现有 Workout 枚举；字典候选和现有 Workout 证据必须分开标记。
3. 对器械、姿势或显示名称有歧义的候选由用户选择；只有字典与现有 Workout 都无法消除歧义时，才建立单个手工样例，不再要求所有动作各建一次。
4. 明确重量是总重量、单只哑铃重量、每侧重量还是辅助重量。
5. 用小组数测试训练和完整真实训练验证 Connect 与 FR955 显示后，才将对应映射升级为端到端 `verified`。
6. 映射不完整时，预览返回完整未支持动作列表，整次禁止上传。

### 8.2 组次转换规则

- `set_type=working` 映射为力量工作步骤；热身步骤在新版创建链路实测后开放。
- 有 `reps` 时使用 `endCondition=reps`；`duration_seconds` 不得误作组间休息。
- 无次数但为计时动作时，后续经实测后使用 `endCondition=time`；首版可标记不支持。
- 组间休息优先级：组级 `rest_seconds` → 动作级 `rest_seconds`；热身休息使用对应热身字段。
- 重量单位为 kg 时：`weightValue=float(weight)`，并保留 `weightUnit={unitId:8, unitKey:kilogram, factor:1000.0}`；**不得乘 1000**。
- 自重动作不伪造 0 kg；没有重量的步骤使用 `weightValue=null`。
- `left_weight` 不参与计算，直至其语义和具体动作重量策略被实测确认。
- `single_side=true`、`amrap=true`、非空 `rounds`、非 kg 单位首版标记不支持。
- 不使用页面摘要的“第一组”代表全部组次。

### 8.3 重复组合并

Garmin `RepeatGroupDTO` 只适合完全相同的处方。仅合并 **同一动作内、连续且重量/次数/休息/组类型完全一致** 的组。

例如三组重量为 `82.5、82.5、77.5 kg`，必须转换为：

```text
2 组 × 10 次 × 82.5 kg
1 组 × 10 次 × 77.5 kg
```

不得合并成三组 82.5 kg，也不得只保留第一组。映射器需提供反向展开能力，测试确保展开后的组序列与训记源逐项一致。

### 8.4 Workout 命名与来源标记

- 名称建议：`训记｜{训练标题}｜YYYY-MM-DD`，按 Garmin 限制确定性截断。
- 描述中包含机器可读的 `source_key` 和短哈希，用于崩溃后的唯一对账。
- 一个计划日对应一个 Workout、一个日程，不按动作拆分 Workout。

## 9. API 设计

### 9.1 本地预览

```http
GET /api/plans/{day}/garmin/preview
```

- 只读本地计划缓存和同步记录，零 Garmin 网络请求。
- 返回完整逐组预览、映射错误/警告、`source_hash`、当前状态和已有远端 ID。
- 计划已变化时，任何旧预览自动失效。

### 9.2 确认同步

```http
POST /api/plans/{day}/garmin/sync
Content-Type: application/json

{"source_hash": "..."}
```

- 重新读取本地计划并计算哈希；不一致返回 `409 PLAN_CHANGED`，要求重新预览。
- 成功启动返回 202；同日已有任务返回 409。
- 只有确认同步和 9.4 的确认顺延端点能触发写入；预览、顺延检测和普通计划查询绝不写 Garmin。

### 9.3 状态查询

```http
GET /api/plans/{day}/garmin/sync
```

返回状态、阶段、ID、哈希、脱敏错误和最近完成时间。现有 `/api/plans/upcoming` 增加每日 `garmin_sync` 摘要，供列表徽标使用，但不返回完整 payload；顺延候选额外返回 `reschedule={from_date,to_date,content_hash}`。

不提供通用删除/取消日程端点；顺延降级替换只允许通过 9.4 的二次明确确认完成。

### 9.4 顺延候选与确认改期（阶段 D2）

已实现，只读候选与目标预览：

```http
GET /api/plans/garmin/reschedules
GET /api/plans/{from_day}/garmin/reschedule?to_date=2026-11-12
```

候选 GET 返回 `reschedule_pending/syncing/failed/conflict` 活动顺延的原日期、目标日期、原/目标来源哈希、内容哈希、Workout ID、日程 ID 和脱敏错误，便于失败恢复；只读本地数据，零 Garmin 请求。目标预览返回完整 `map_plan_day()` 结果、原/目标日期、当前 ID、状态和 `remote_write_eligible`，不创建或修改同步记录。

已实现，确认改期：

```http
POST /api/plans/{from_day}/garmin/reschedule
Content-Type: application/json

{"to_date":"2026-11-12","source_hash":"..."}
```

- 重新读取原记录和目标计划，重新计算 `content_hash/source_hash`；不一致返回 409，禁止按旧预览改期。
- 成功启动返回 202；已完成且原日期、目标日期、哈希和 ID 均一致时，从旧 URL 重放返回 200 `started=false`；运行中返回 409。
- 多候选、目标记录冲突或远端来源不符分别返回稳定的错误码，不做不安全写入。
- 只更新原 Workout 和原日程，不要求前端提供创建替代日程或删除权限。

阶段 1 尚未实现替换日程降级，因此没有 `replace_schedule/old_schedule_id` 请求字段，也不会返回“允许替换”的确认令牌。真实 P4 已证明支持原日程改期，当前无需该降级路径；若未来真实能力变化，适配器/编排应落脱敏失败并保持原记录，后续必须单独设计 `409 GARMIN_SCHEDULE_RESCHEDULE_UNSUPPORTED` 和带具体旧日程 ID 的二次确认，不得在当前端点中隐式创建或删除。

## 10. 幂等、写入顺序与失败恢复

### 10.1 正常写入流程

1. 重新计算源哈希并以数据库条件更新抢占任务，避免跨请求/跨进程重复执行。
2. 本地生成 payload 和 `source_key`，保存 `pending` 记录后提交。
3. 登录；若已有 `workout_id`，先读取并核对来源标记。
4. 无 ID 时先按来源标记对账：唯一匹配则认领，多个或不明确则 `conflict`，只有无匹配才创建。
5. 创建成功立即保存 `workout_id` 并提交；更新则使用完整远端 JSON 原地 PUT。
6. 回读 Workout，逐动作、逐组语义校验，不只检查 HTTP 200。
7. 无日程 ID 时先按 Workout+日期对账，无匹配才创建并立即保存；已有 ID 时核对 Workout 与日期，不符则进入 `conflict`，当前不自动改期。
8. 回读日程并确认关联正确，最后写入 `synced_hash=source_hash`、`status=synced` 和 JobRun。

数据库事务不得跨越整段 Garmin 网络调用；每个远端 ID 获取后都要独立、立即落库。

### 10.2 重试原则

- 当前实现对 GET、已确定 ID 的 PUT 仅在 401、403、429 下有限恢复一次，不将其扩大为通用自动重试。
- 创建 Workout/日程的 POST 结果不确定时：**不得直接重发**，先按 `source_key`、Workout+日期和本地 ID 对账；适配器已关闭库内自动重试。
- 映射错误、源哈希变化、权限冲突不重试，不形成紧密循环。
- 可重试失败再次确认后，从已保存 ID 和对账阶段恢复，而非直接新建；进程崩溃导致的永久 `syncing` 超过阈值后自动转为 `failed`，仍须用户再次确认才会发起恢复写入。
- 顺延请求必须同时校验原日期、目标日期和新 `source_hash`；恢复以原记录、`reschedule_to_date` 和已保存远端 ID 为准，禁止生成第二个 Workout。替换日程 POST 结果不确定时同样先对账，不得直接重发。

### 10.3 远端手工修改

训记是同步源，但用户再次确认更新前，预览需明确“将覆盖此应用管理的 Garmin 训练”。如果远端 ID 指向其他来源、来源标记不匹配或同日出现多个候选，进入 `conflict`，不得强行覆盖。顺延确认前还需明确“保留 Workout、调整日程日期”；远端日程已被手工改期或关联其他训练时，不得擅自接管。

## 11. 前端交互方案

在现有 `PlansPage.jsx` 的非休息日卡片增加：

- 状态：`未同步 / 同步中 / 已同步 / 有更新 / 顺延待确认 / 同步失败 / 待处理冲突 / 不支持`。
- 主按钮：首次为“预览并同步”，已同步为“查看”，源变化后为“同步更新”，顺延候选为“确认顺延”。
- 预览弹层：完整列出动作和每一组，而非只显示第一组；展示日期、动作数、总组数、休息、重量策略及所有警告。
- 顺延弹层并排显示原日期和目标日期，明确“保留原 Workout ID”；首选保留日程 ID，若需替换必须在第二次确认中展示具体旧日程 ID 和影响。
- 确认按钮携带本次 `source_hash`，顺延还需携带 `to_date`；计划刷新导致哈希或候选变化时关闭旧确认并重新预览。
- 202 后按现有模式轮询；成功后显示 Workout 和日程关联信息，失败时提供“重新预览/恢复同步”。
- 连续顺延只处理当前唯一候选；多候选、目标冲突或新旧日程同时存在时显示明确原因，不提供强行覆盖按钮。
- 对不支持动作显示具体中文动作名和原因，不提供“跳过不支持动作后继续”按钮。

首个版本不改变现有计划刷新和 AI 点评主流程，也不增加 Garmin 账号登录墙。

## 12. 分阶段开发计划

以下工作量按个人项目、包含测试和验收估算，不包含等待 Garmin 风控冷却的时间。

### 阶段 A：运行环境与新版认证闭环（1～1.5 天，主环境与重启恢复已完成）

- 主后端 `backend/.venv` 已切换 Python 3.12.14，安装并验证 `garminconnect 0.3.20`；`pip check` 和应用导入通过。
- 原 Python 3.11 环境完整保留为 `backend/.venv-py311-backup`，旧 garth 与旧 token 暂不移除。
- 新版写入适配器支持客户端工厂注入和独立 token；P1 已验证无密码进程重启恢复，P2 已在主环境真实复用。
- Python 3.12 下全量后端回归通过；refresh token 自动续期仍待长期观察。

**出口条件**：连续两次进程启动均无需重复密码登录；第二次使用保存 token；日志和数据库无 token/密码/MFA state。已满足，自动 refresh 不属于本次已验证范围。

### 阶段 B：现有读取链路平移（1～1.5 天）

- 把现有活动列表、详情、exerciseSets、每日健康读取迁移到新版公开方法或同一 `connectapi` 路径。
- 将 FakeGarth 测试改为 FakeGarmin，保留 0.5 秒限速、429、401/403 和幂等测试。
- 对同一历史日期做旧/新只读对比，核对原始摘要和落库字段。

**出口条件**：现有 Garmin 单元测试全部通过；只读样本字段一致；FIT 文件降级导入不受影响。

### 阶段 C：映射器与本地预览（1.5～2 天，已完成）

本地映射、状态表、只读 API 和只读前端已于 2026-11-10 完成：

- `backend/app/services/garmin_workout_mapper.py` 实现规范化、来源哈希、完整错误收集、kg 原值、变重组、热身/休息、RepeatGroupDTO 和反向展开。
- 新增 `garmin_plan_sync` 表及迁移 `a3b4c5d6e7f8`；本地库已核验 17 个字段和 2 个唯一约束，版本为 head。应用 metadata 先自动建表导致首次 upgrade 冲突，确认表为空且结构一致后使用 stamp 对齐，未删除或重写数据。
- `GET /api/plans/{day}/garmin/preview` 返回完整 payload、逐组预览、统计和状态，不创建同步记录；`GET /api/plans/{day}/garmin/sync` 返回当前状态；`/api/plans/upcoming` 批量附加 `garmin_sync` 摘要。
- 未映射动作返回 `422 PLAN_MAPPING_UNSUPPORTED` 和全部 issues。阶段 C 当时同步 POST 尚未注册并返回 405、预览没有写入按钮；该历史状态已由阶段 D/E 取代。
- `PlansPage.jsx` 在非休息日显示 Garmin 状态徽标和预览入口；`GarminPlanPreviewModal.jsx` 展示全部组次、重量、次数、休息、来源哈希和已有远端 ID，不允许跳过不支持动作。
- 前端保留结构化 FastAPI detail，完整展示 422 issues；弹层支持焦点锁定、Escape 关闭、焦点恢复、滚动锁定和移动端布局。
- 两个真实训练日共 51 组全部通过反向展开对账，报告为 `outputs/garmin_p0/mapper_validation.md`；完整 payload 只保存在本地预览文件中。
- 当前 15 个动作的白名单和用户选择已落地，未知动作在零网络请求下整日拒绝。

**出口条件**：支持范围内反向展开与训记源 100% 一致；任何未知动作均在零网络请求下被拦截。已满足。

### 阶段 D：写入编排与恢复（2～3 天，代码与专用实测已完成）

- `garmin_workout_adapter.py` 实现新版创建、读取、更新、日程创建/读取及两种对账；普通同步不自动改期，专用顺延适配器见阶段 D2。
- `garmin_plan_sync.py` 实现来源对账、ID 分阶段落库、语义回读、状态机、JobRun 和冲突处理；网络调用不跨数据库事务；包含 `syncing` 超时本地恢复与 attempt 隔离。
- `POST /api/plans/{day}/garmin/sync` 已实现：启动 202、已同步 200、旧哈希/运行中/冲突 409、映射不支持 422、功能关闭 503。
- 故障注入和并发测试覆盖创建后、日程前等中断恢复、重复请求、来源不符、多候选、日程日期或关联冲突；创建 POST 绝不自动重发。
- 专用 P1 真实训练已完成新版创建、回读、20 → 22.5 kg 原地更新、日程和 token 重启恢复，ID 见 2.2。
- P2 还覆盖了真实回读冲突：精确兼容 Garmin 对通用 Bench Press 的空 `exerciseName` 规范化后，复用 `38213123` 恢复并排程，没有重复创建。
- P3 覆盖了 Lateral Raise 的同类真实规范化：精确兼容后复用 `38213537` 完成排程和 24 组回读，没有重复创建。
- P6 已在 Workout/日程创建成功后分别真实杀死子进程，再由独立进程超时恢复；attempt 1 → 2 → 3，最终两个创建接口各成功 1 次、远端对象各 1 个，API/ID 回读通过，Connect/FR955 目视已通过，详见 2.12。
- 当前限制：普通同步遇到计划改期进入 `conflict`，`source_removed` 只有状态视图。

**出口条件**：同一来源重复执行及已覆盖的故障点恢复后不重复创建。自动测试、P1、P2、P3 及 P6 真实 API/ID 回读满足；P6 的 Connect/FR955 目视出口也已满足，阶段 D 完整通过。

### 阶段 D2：训记未训练顺延与改期闭环（阶段 1 后端、前端、模拟验收及 P4 完整验收均通过）

已完成（2026-11-10）：

- 映射器新增仅排除日期的 `content_hash`，`source_hash/source_key` 语义不变；本地检测、候选查询和普通同步防绕过门禁保持通过。
- 迁移 `b4c5d6e7f8a9` 新增检测字段；阶段 1 迁移 `c5d6e7f8a9b0` 新增 `reschedule_from_date/reschedule_source_key`，保存确认时原日期和原来源键。临时 SQLite 的升级、单步回滚、再升级及全量 Alembic 往返通过。
- 本机实际数据库 `backend/data/app.db` 已升级到 `c5d6e7f8a9b0` 并核验 22 个字段；升级前的 `outputs/garmin_d2/app-before-b4c5d6e7f8a9.db` 完整备份仍保留，升级后另存 `outputs/garmin_d2/app-after-c5d6e7f8a9b0.db`（509624320 字节）。本切片未对真实记录执行顺延检测或远端写入。
- 新增顺延预览和确认 POST；确认时保存目标 payload/哈希及原日期/来源审计，成功后保留审计字段。旧 URL 以相同目标和哈希重放返回 200、`started=false`，attempt 不变，不依赖 JobRun JSON 反查。
- runner 只使用已关联 Workout/日程 ID：回读来源，必要时完整 PUT 原 Workout，再调用本机库已核实的 `reschedule_workout()` 改原日程，最终回读完整组次、来源、日期和关联。没有创建、替换或删除路径。
- Workout 更新或日程改期响应丢失后，恢复通过回读跳过已成功 PUT；活动顺延的 `failed/conflict` 会继续出现在候选和目标日状态中，普通同步不能绕过。
- FakeGarmin/API 测试覆盖同内容、已关联后内容变化、两个响应丢失故障点、来源冲突、旧哈希、目标冲突、运行中、开关关闭、成功幂等和默认零 Garmin 外呼。
- 前端已完成顺延状态入口、原/目标日期对比、完整组次、保留 ID 语义、单次确认、目标日轮询、失败恢复、脱敏错误和旧哈希重新预览；新增 5 项顺延交互测试和桌面/移动端模拟浏览器验收，详见 2.6。
- 独立 P4 真实改期 API、ID 回读及 Connect/FR955 目视验收均已通过：Workout `38217702`、日程 `34834456` 均保持，日程从 2026-11-14 移至 2026-11-15；旧日期日程 0 个、目标日期日程 1 个。用户于 2026-11-11 05:37 确认显示正常。使用隔离数据库，未修改或删除 P0/P1/P2/P3 对象，详见 2.7。
- 2026-11-11 连续顺延增强已完成：活动候选和状态使用当前 `training_date`，不再误用上一轮审计来源；两轮改期及第二轮 API 合约测试通过，两个远端 ID 保持且零创建，详见 2.9。
- P5 真实连续改期已完整通过：Workout `38222333`、日程 `34839305` 始终保留，完成 2026-11-16 → 2026-11-17 → 2026-11-18 两轮改期；每轮更新/改期各 1 次、创建均为 0，16/17 日最终日程均为 0、18 日为 1，Connect/FR955 目视验收均已通过，详见 2.10。
- `syncing` 超时自动恢复已完成本地/API/FakeGarmin 验证：普通同步和顺延均保留原 ID，重新确认不重复创建，旧 runner 不得覆盖新 attempt，详见 2.11。
- P6 普通创建链路的两次真实进程杀死、独立恢复及远端唯一性 API/ID 回读已通过；只使用隔离数据库，未写入 P0–P5 保护对象，Connect/FR955 目视已通过，详见 2.12。

待开发：

- 首次“日期与内容同时变化”的自动关联。

**出口条件**：阶段 1 后端、前端和 FakeGarmin/模拟浏览器出口已满足：确认改期保留两个远端 ID，已覆盖故障点恢复不重复 PUT/创建，旧地址重放幂等，确认前零写入且单次确认只发一次 POST。P4 真实 API、ID 回读和 Connect/FR955 目视出口均已满足；连续顺延本地/API/FakeGarmin 及 P5 真实 API/ID 回读出口均已满足，P5 Connect/FR955 目视均已通过；`syncing` 超时恢复及旧 runner 隔离出口已满足；P6 真实进程杀死 API/ID 回读出口已满足，目视已通过。P6 目视出口也已满足；完整 D2 出口仅剩首次“日期与内容同时变化”的自动关联，该增强不影响当前已定义顺延流程部署。

### 阶段 E：前端与端到端验收（1～1.5 天，P2/P3 已完成）

- 已实现状态徽标、完整预览、首次确认、覆盖更新确认、轮询、失败恢复、脱敏错误和旧哈希重新预览。
- 已覆盖计划变化、已同步、更新、失败、运行中和不支持状态；预览未确认时零写入，确认只发送一次 POST。
- 后端阶段 1 完成后，Python 3.12 后端全量测试：**1142 passed、6 skipped，覆盖率 90.69%**（含 D2 顺延确认和故障恢复）；当时前端历史结果为 437 passed（49 个文件）。
- Chrome 真实浏览器模拟 API 验收通过：确认前写入 0、确认 POST 恰好 1、状态轮询 1、桌面/移动端、Escape 焦点恢复和 422 完整错误均通过，运行时异常 0。报告与截图位于 `outputs/garmin_ui_validation/`。
- 顺延前端切片最终全量回归为 **442 passed（50 个文件）**；顺延模拟浏览器验收、Portal 首屏定位修复及移动端触控检查均通过，详见 2.6。
- P2 完整真实训练日已在 Connect 中国区创建并排程：8 个动作、27 组、日期和日程关联 API 回读全部一致，详见 2.3。
- 用户已于 2026-11-10 15:32 确认 P2 的 Connect 与 FR955 显示正常，8 个动作映射升级为 `p2_verified`。
- P3「腿·肩」已创建并排程：7 个动作、24 组、日期和日程关联 API 回读全部一致，映射器定向回归 22 passed；用户已于 2026-11-10 15:58 确认 Connect 与 FR955 显示正常，7 个动作升级为 `p3_verified`，详见 2.4。
- 真实后端与无头 Chrome 正式前端验收通过：P3 预览的 7 个验证标签、24 组和 ID 正确，幂等 POST 返回 200 且 `started=false`，尝试次数与远端 ID 不变；详见 2.5。

**出口条件**：用户无需查看数据库即可理解状态并完成同步；腕表显示与确认预览一致。P2/P3、真实前端预览及幂等 POST 均已满足，当前计划 15 个动作全部完成端到端验证。

### 阶段 F：切换与清理（0.5～1 天）

- 默认启用新版读取，观察现有每日同步和健康检查。
- 删除 garth 依赖、旧认证分支和旧测试桩，更新 PRD 中已过时的 garth 说明。
- 保留旧 token 一段时间作为只读回滚资产，不主动删除远端测试对象。

**出口条件**：生产依赖不再包含 garth；现有读取和新增写入均使用同一新版认证栈。

**MVP 总计：约 7～10 个开发日。** 若当前计划动作种类较多，动作枚举与重量语义确认是最大浮动项。新增阶段 D2 顺延与改期闭环另需 **1～1.5 天**，不包含等待 Garmin 风控冷却或真实计划自然顺延的时间。

## 13. 测试清单

### 13.1 映射器单元测试（零网络）

- 真实 fixture 全量动作与组次解析。
- 相同连续组正确合并，变重组不被合并，顺序不变。
- kg 原值传递：20 kg 始终生成 `weightValue=20.0`，不是 20000。
- 有次数时优先 reps，`duration_seconds` 不被误作休息。
- 组级/动作级休息优先级、热身休息、最后一组休息策略。
- 自重、未知动作、非 kg、单边、AMRAP、rounds、缺失次数/时长。
- canonical JSON 键序稳定；无意义字段顺序变化不改变哈希，真实计划变化必须改变哈希。
- `content_hash` 仅忽略日期：同日同内容相同、跨日同内容相同，标题、动作或任一组处方变化必须不同；`source_hash` 跨日仍必须变化。
- 反向展开后与源组次逐项一致。

### 13.2 适配器测试（FakeGarmin，零网络）

- 中国区参数、token 恢复、凭据重登、token 保存、refresh、MFA 分支。
- 同进程只登录一次，0.5 秒全局限速，429 退避，401/403 只恢复一次。
- Workout 创建、读取、完整更新、日程创建/读取，以及按来源键和 Workout+日期对账；当前普通同步遇到日期不符仍进入 `conflict`，不自动改期。
- D2 阶段 1 已完成：`reschedule_schedule` 调用库内原日程改期方法，FakeGarmin 验证只改变目标日期并保留 Workout ID、日程 ID；编排回读目标日期、来源关联和 Workout 关联，三者一致才算成功。
- D2 阶段 1 已完成：更新/改期响应丢失时保留原记录，恢复先按 ID 回读，不盲目重发，不新建第二个 Workout 或日程。其他 HTTP 状态仍由适配器统一脱敏包装。
- D2 阶段 1 不含替换路径：常规创建、更新、顺延检测和改期均不调用 `delete_schedule`；真实 P4 已证明支持原日程改期，当前无需设计替换路径。若未来真实能力变化，明确错误及独立二次确认必须另行设计。
- 原始异常统一包装，错误文本不包含密码、token、Cookie 或 MFA state。
- 活动/健康读取字段与旧实现一致仍属后续 garth 平移测试，不在本轮新版写入适配器中标为完成。

### 13.3 编排与数据库测试

- 首次创建、重复同步、源变化后原地更新、相同哈希无重复写。
- 创建成功后的已覆盖故障点均可恢复，不盲发 POST。
- 日程 ID 保留；日程 404 时可恢复；当前普通同步遇到日期或关联变化进入 `conflict`，不重复安排、不自动改期。D2 只允许专用顺延确认端点执行改期，不能放宽普通同步的这一约束。
- D2 本地检测已完成：未同步记录不进入改期流程；已同步记录进入 `reschedule_pending`，确认前保留旧日期、旧来源键、原 payload、原哈希和全部远端 ID，重复检测幂等且零 Garmin 请求。
- D2 已完成：跨日同内容产生唯一候选；同日内容变化仍走普通更新；首次跨日且内容不同不关联；已关联后目标内容变化保留候选，确认预览包含完整目标内容和改期影响。
- D2 已完成：重复候选、目标已有记录进入本地 `conflict`，候选消失/恢复及旧计划返回有确定行为；远端来源不符进入 `conflict`。
- D2 连续顺延增强已完成本地验证：第二轮候选与目标日状态返回当前来源日期；连续两轮确认保留同一 Workout/日程 ID，零创建，第二轮旧地址重放幂等。
- P5 真实连续改期已完整完成：第二轮候选来源为上一轮目标日，两个远端 ID 保持，每轮更新/改期各 1 次且创建均为 0，16/17 日最终日程为 0、18 日为 1；Connect/FR955 目视验收均已通过。
- D2 阶段 1 已完成：旧 `source_hash`、旧目标日期和运行中重复确认不得重复改期；成功重试返回原结果，Workout ID、日程 ID 和尝试次数符合幂等约定。
- D2 阶段 1 已完成：分别模拟 Workout 更新后、原日程改期后的响应丢失；恢复先按来源键和 ID 回读，不重复 PUT 或创建。替换日程故障点不属于本切片。
- P6 真实进程杀死 API/ID 回读已完成：Workout 创建后、日程创建后分别杀死独立子进程，两次超时恢复后 attempt 为 3；两个创建接口各成功 1 次，最终远端 Workout/日程及本地记录各 1 个，Connect/FR955 目视已通过。
- 来源标记不匹配、多候选、远端被替换时进入 `conflict`。
- 计划结束/删除只呈现 `source_removed` 状态，不调用删除接口；顺延替换旧日程不属于计划删除，必须另走二次明确确认。
- 两个并发确认只有一个获得执行权；永久 `syncing` 的 15 分钟超时自动恢复已完成，普通同步和顺延均验证重新确认不重复创建、旧 runner 不覆盖新 attempt，恢复 JobRun 脱敏留痕。
- JobRun 与同步表状态一致，敏感信息不落库。

### 13.4 API 与前端测试

- 未认证 401；预览零外呼；确认 202；运行中/哈希过期 409。
- D2 阶段 1 已完成：顺延候选/预览 GET、upcoming 和单日状态只读本地数据，零 Garmin 外呼；普通同步 POST 被活动顺延以 409 阻止。确认改期首次 202、幂等重试 200 且 `started=false` 已通过 API 测试。
- D2 阶段 1 已完成：旧哈希、目标冲突、运行中和开关关闭返回对应 409/503，不暗中替换或删除。真实 P4 已证明支持原日程改期，当前无需实现 `GARMIN_SCHEDULE_RESCHEDULE_UNSUPPORTED`；若未来真实能力变化再单独设计。
- D2 前端已完成：顺延弹层显示原日期、目标日期、完整目标内容和保留 ID 语义，重复点击只发送一次请求；冲突与写入关闭时无确认按钮。未来替换路径必须出现第二次明确确认并列出具体旧日程 ID，当前未实现也未开放。
- 列表正确显示全部状态；预览展示全部组而非第一组。
- 轮询结束、失败重试、计划变化使旧预览失效。
- 不支持动作不能被绕过；确认前清楚显示覆盖语义。

### 13.5 显式真实集成测试

真实写入不读取 `RUN_GARMIN_INTEGRATION`，而是在 Python 3.12 环境中由账号所有者显式手动运行 `scripts/p1_garmin_workout_write.py`、`scripts/p2_garmin_full_day_sync.py`、`scripts/p3_garmin_full_day_sync.py`、`scripts/p4_garmin_reschedule.py`、`scripts/p5_garmin_consecutive_reschedule.py` 或 `scripts/p6_garmin_process_kill.py`；默认 pytest 和前端测试均零 Garmin 外呼。P6 另提供 `--preflight` 零网络预检；正式报告、marker 或隔离数据库已存在时拒绝盲目重跑。

1. 已完成：新版 token 落盘与无密码重启恢复；refresh 自动续期仍待观察。
2. 已完成：新版创建单动作训练、读取、20 → 22.5 kg 原地更新、安排和日程回读，报告为 `outputs/garmin_p1/workout_write_result.json`。
3. 已完成：P2 完整真实训练日的变重组、热身、不同休息、创建、排程和 27 组远端语义对账，报告为 `outputs/garmin_p2/full_day_sync_result.json`。
4. 已完成：用户确认 P2 在 Connect 与 FR955 显示正常。
5. 已完成：P3「腿·肩」创建、排程、24 组远端语义对账及 Connect/FR955 目视验收，报告为 `outputs/garmin_p3/full_day_sync_result.json`。
6. 已完成：真实前端预览和幂等 POST，报告为 `outputs/garmin_real_ui_validation/real-ui-validation.json`；只在临时验收进程开启开关，未创建新 Garmin 对象。
7. 待完成：旧/新读取同一历史日期的数据对比。
8. 已完成：独立 P4 使用专用 Workout `38217702` 和日程 `34834456`，从 2026-11-14 原日程改期到 2026-11-15；两个 ID 均保持，旧日期日程 0 个、目标日期日程 1 个，来源关联及完整内容回读通过。用户已于 2026-11-11 05:37 确认 Connect 与 FR955 显示正常，报告为 `outputs/garmin_p4/reschedule_result.json`；未修改或删除 P0/P1/P2/P3 对象，未删除任何远端对象。
9. 已完成：独立 P5 使用专用 Workout `38222333` 和日程 `34839305`，连续完成 2026-11-16 → 2026-11-17 → 2026-11-18 两轮改期；两个 ID 均保持，每轮更新/改期各 1 次且创建均为 0，16/17 日最终日程为 0、18 日为 1，报告为 `outputs/garmin_p5/consecutive_reschedule_result.json`。用户已于 2026-11-11 06:25 确认 Connect 与 FR955 显示正常；未写入 P0–P4 保护对象，未删除任何远端对象。
10. 已完整完成：独立 P6 使用专用 Workout `38224225` 和日程 `34841221`，在 Workout/日程创建成功后分别真实杀死子进程，再由独立进程恢复；最终 attempt 3，两个创建接口各成功 1 次，远端 Workout/日程和本地记录各 1 个，完整训练语义及 2026-11-19 日程关联回读通过。报告为 `outputs/garmin_p6/process_kill_result.json`；未写入 P0–P5 保护对象，未删除任何远端对象。用户已于 2026-11-11 09:46 确认 Connect 与 FR955 显示正常。

真实测试使用唯一来源键和明确日期；专用 P0/P1 对象带对应前缀，P2/P3 使用真实计划来源键，P4–P6 使用各自独立来源键和隔离数据库。结束先输出全部远端 ID，另行获得批准后才删除。本轮没有删除任何远端对象。

## 14. MVP 验收标准

必须全部满足：

- [ ] 支持范围内的每个动作、每一组、重量、次数和休息与确认预览一致。
- [ ] 不支持内容在上传前被完整列出，零静默丢弃、零猜测映射。
- [ ] 20 kg 在 Connect 和 FR955 均显示 20 kg。
- [ ] 重复确认和失败恢复不产生重复 Workout 或日程。
- [ ] 计划更新原地保留 Workout ID；只改内容时日程 ID 保留。
- [ ] 进程重启后可使用已保存 token，不反复密码登录。
- [ ] 现有活动、健康同步和文件导入回归通过。
- [ ] 日志、API、JobRun、Git 中无密码、token、Cookie 或 MFA state。
- [ ] 自动测试默认零 Garmin 外呼，真实测试只能显式开启。
- [ ] 不自动删除任何远端训练或日程。
- [ ] （阶段 D2）未训练顺延复用原同步记录和 Workout ID；原日程支持改期时同时保留日程 ID，目标日期回读及 Connect/FR955 显示一致。
- [ ] （阶段 D2）重复顺延、连续顺延和崩溃恢复不产生未说明的重复 Workout 或日程；多候选、目标冲突和远端手改均停止并进入 `conflict`。
- [ ] （阶段 D2）只有不支持原日程改期时才允许二次确认替换；旧日程 ID 留痕，任何失败不得新建第二个 Workout。

## 15. 上线、回滚与后续自动同步

### 15.1 上线策略

- 新增 `GARMIN_PLAN_SYNC_ENABLED`，MVP 默认关闭，仅在本机验收后打开；`GARMIN_PLAN_SYNC_STALE_SECONDS` 默认 900，仅控制本地超时状态恢复，不会自动开放或触发远端写入。
- 数据库迁移只新增表，可向后兼容；回滚代码不要求删表。
- 初期只手动同步一个测试日，再同步一个完整真实训练日，最后开放未来 30 天逐日使用。
- 每次真实写入保留来源键和远端 ID，便于审计和人工清理。
- D2 顺延入口与普通写入共用默认关闭的功能开关；服务器开放所需的本地迁移、FakeGarmin、API/前端、故障恢复测试及独立 P4–P6 真实验收均已完成。P6 已于 2026-11-11 09:46 完整通过；功能开关仍默认关闭，服务器实际开放仍需按部署流程单独执行。

### 15.1.1 服务器上线前必须完成的 P7–P9（2026-11-11 核对）

当前阻塞不在 Garmin 功能本身，而在生产运行环境：`backend/Dockerfile` 仍为 `python:3.11-slim`，CI 两个 Python 任务仍为 3.11；`docker-compose.yml` 尚未传递写入开关、超时阈值和新版 token 路径，也没有新版 token 的独立持久卷。直接推送现有制品不会得到可用的 Garmin 写入能力。

| 工作包 | 必须完成的开发/配置 | 出口条件 |
|---|---|---|
| P7 生产运行环境适配 | 后端镜像和 CI 升级到 Python 3.12，同步修改部署静态测试；Compose 传递 `GARMIN_PLAN_SYNC_ENABLED`、`GARMIN_PLAN_SYNC_STALE_SECONDS`、`GARMIN_WORKOUT_TOKENSTORE`，新增独立 `garmin_workout_tokens` 卷，不与旧 garth token 混用；核对生产环境模板、部署文档和 preflight；显式核验容器时区及 APScheduler 时间 | Linux 镜像内 Python ≥3.12、`garminconnect==0.3.20` 可导入；开关默认 0；token 路径可写且重建后保留；旧读取 token 路径不变 |
| P8 PostgreSQL 与发布回归 | 扩充 `test_alembic_postgres.py`：当前 `ALL_TABLES` 尚未显式包含 `garmin_plan_sync`，需验证 22 个字段、2 个唯一约束及 head；用 PostgreSQL + FakeGarmin 覆盖并发 claim、超时 CAS、旧 runner attempt 隔离和原日程改期；独立修复既有每日 AI 重生成限流 UTC/本地日期跨日失败 | PostgreSQL 迁移和 Garmin 状态机测试通过；默认零 Garmin 外呼；后端、前端、lint、构建恢复全绿，不再带着当前 1 个既有失败发布 |
| P9 部署灰度与真实验收 | 先备份，单 backend 副本、开关 0 部署并执行迁移；分别验证旧 garth 读取和新版适配器登录/只读回读；预览确认零写入后再打开开关；由用户确认一个真实训练日，检查幂等、Connect/FR955、日志和重启后的 token 恢复 | `alembic current==c5d6e7f8a9b0`；健康检查和现有读取正常；新版 token 可持久化；真实训练仅一套对象，重复 POST 不新增；异常时关闭开关即可停止新增写入 |

上线后的行为保持不变：每日计划缓存会自动检测顺延候选，但普通同步和改期都必须由用户在页面确认，不会在服务器上自动批量写 Garmin。

以下项目**不阻塞本次上线**：首次“日期与内容同时变化”的自动关联、`source_removed` 自动处置、garth 读取链路平移、refresh token 长期续期观察、MFA 通用流程和全自动批量同步。它们应作为后续独立增强，不得为赶上线放宽当前冲突门禁。

预计 P7–P9 需要 **1.5～2.5 个开发日**，另需预留 Garmin 429 风控冷却和服务器目视验收时间。

### 15.2 回滚

- 关闭功能开关即停止新增写入，不影响现有训练查询和 Garmin 活动读取。
- 读取迁移异常时恢复上一版本代码和依赖；旧 garth token 在迁移期保持不动。
- 已创建的 Garmin 对象不因代码回滚而自动删除；通过同步表列出 ID 后人工决定。
- 回滚或关闭 D2 只停止新的改期/替换写入；保留 `reschedule_to_date`、当前及旧日程 ID、目标哈希和错误阶段供恢复审计，不自动清理新旧日程，也不把记录强行标为成功。
- 数据库新增表可保留，避免 destructive down migration。

### 15.3 后续可选自动化

手动模式稳定运行至少一周后，再增加默认关闭的自动同步：

- 计划缓存每日刷新后，只处理未来 14 天且哈希变化的训练日。
- 批量任务串行、全局限速、单日失败不阻塞其他日期。
- 自动创建/更新仍需白名单全覆盖；任何冲突都暂停该日并通知。
- 计划移除仍不自动删除；自动取消日程必须作为单独功能再次评估。
- D2 可自动检测并生成顺延待确认候选，但检测只读本地数据；自动任务不得替用户确认改期，更不得自动替换或删除旧日程。

## 16. 主要风险与控制

| 风险 | 影响 | 控制 |
|---|---|---|
| 非官方接口变化 | 登录或 Workout 写入失效 | 固定版本、适配器隔离、真实集成手动门禁、保留文件导入 |
| IP 级 429 / SSO 风控 | 同步失败或账号临时受限 | token 复用、主动 refresh、0.5 秒限速、退避、禁止紧密重试 |
| 动作枚举或重量语义错误 | 腕表执行错误训练 | 白名单、Garmin 样例反查、逐动作实测、未知即拒绝 |
| POST 成功但响应/落库失败 | 重复训练或日程 | source_key 对账、ID 立即落库、不确定 POST 不直接重试 |
| 计划更新覆盖 Garmin 手改 | 用户修改丢失 | 单向源声明、确认预览、来源不符即 conflict |
| 顺延误判或目标日期冲突 | 正确日程被改到错误日期 | content_hash 加完整来源校验、唯一候选、目标冲突即 conflict、确认前展示日期差异 |
| 新旧日程切换中断 | 同日重复日程或无法判断应保留哪一个 | 优先原日程改期；替换需二次确认；保存新旧 ID 和阶段，恢复先回读，不自动清理 |
| token/MFA state 泄漏 | 账号被接管 | 独立 token 路径、MFA 直接停止且不持久化 state、日志脱敏、禁止入库/前端 |
| Python 升级引入兼容问题 | 整个后端无法启动 | 独立 3.12 环境先跑全量测试，再切换部署 |
| 自动删除误清远端数据 | 难以恢复 | MVP 禁止自动删除，清理始终单独确认 |

## 17. 本轮主要变更文件

### 新增核心实现与验证

- `backend/app/adapters/garmin_workout_adapter.py`：新版独立 Workout/日程写入适配器。
- `backend/app/services/garmin_workout_mapper.py`、`backend/app/services/garmin_plan_sync.py`：映射、状态视图和写入编排；包含 P2/P3 实测确认的通用 Bench Press 与 Lateral Raise 精确回读别名；连续顺延活动状态使用当前来源日期；支持 `syncing` 超时 CAS 恢复、JobRun 留痕及 attempt 完成隔离。
- `backend/alembic/versions/a3b4c5d6e7f8_garmin_plan_sync.py`：同步表迁移。
- `backend/app/services/garmin_reschedule.py`：D2 本地检测、顺延预览、确认改期、原对象更新、审计幂等和故障恢复；连续候选使用当前 `training_date`；支持超时恢复和旧 runner attempt 隔离。
- `backend/alembic/versions/b4c5d6e7f8a9_garmin_plan_reschedule.py`、`c5d6e7f8a9b0_garmin_reschedule_audit.py`：检测字段及原日期/原来源审计字段迁移。
- `backend/tests/test_garmin_reschedule_detection.py`：顺延哈希关联、候选、冲突、第二轮 API 来源日期和零 Garmin 外呼测试。
- `backend/tests/test_garmin_reschedule_write.py`、`test_garmin_reschedule_api.py`：原 Workout/日程更新、响应丢失恢复、连续两轮改期、旧地址幂等、超时恢复、旧 runner 隔离和 HTTP 契约测试。
- `backend/tests/test_garmin_workout_adapter.py`、`test_garmin_plan_sync_write.py`、`test_garmin_plan_sync_api_write.py`：新版写入、响应丢失、超时自动恢复、重试幂等及旧 runner 隔离测试。
- `frontend/src/components/GarminPlanPreviewModal.jsx`、`frontend/src/pages/__tests__/GarminPlanSyncActions.test.jsx`：确认同步界面、P0/P2/P3 验证标签与交互测试。
- `frontend/src/pages/__tests__/GarminRescheduleActions.test.jsx`：顺延确认、恢复、旧哈希、轮询失败和冲突门禁 5 项交互测试。
- `scripts/p1_garmin_workout_write.py`、`scripts/p2_garmin_full_day_sync.py`、`scripts/p3_garmin_full_day_sync.py`、`scripts/validate_garmin_preview_browser.mjs`、`scripts/validate_garmin_real_ui.mjs`：单动作、完整训练日、模拟浏览器和真实前端验收。
- `scripts/p4_garmin_reschedule.py`：独立 P4 真实原日程改期、隔离数据库、远端语义回读及脱敏报告。
- `scripts/p5_garmin_consecutive_reschedule.py`：独立 P5 真实连续两轮原日程改期、逐轮来源核验、隔离数据库、远端语义回读及脱敏报告。
- `scripts/p6_garmin_process_kill.py`：独立 P6 两次真实进程杀死、三 attempt 独立恢复、历史对象写入保护、隔离数据库、最终父进程远端唯一性与语义回读；报告及样本位于 `outputs/garmin_p6/`。
- `scripts/validate_garmin_reschedule_browser.mjs`：顺延桌面/移动端模拟 API 浏览器验收，报告与截图输出到 `outputs/garmin_reschedule_ui_validation/`。

### 修改

- `backend/requirements.txt`：Python 3.12 环境下固定 `garminconnect==0.3.20`；主 `backend/.venv` 已完成升级，旧环境备份保留。
- `backend/app/config.py`、`.env.example`：默认关闭的写入开关、900 秒 `syncing` 本地恢复阈值和独立 token 路径示例。
- `backend/app/models.py`、`backend/app/api/plans.py`：同步表、预览、确认和状态接口。
- `frontend/src/pages/PlansPage.jsx`、`frontend/src/api/client.js`：同步交互与结构化错误。
- `docs/GARMIN-PLAN-SYNC-MIGRATION.md`：实施设计和实测进度基线。

### 不修改其核心语义

- `backend/app/services/plans.py` 的计划选择规则。
- 现有 `garmin_adapter.py` 的活动与健康读取链路；garth 平移留待后续。
- 现有活动融合、匹配和训练档案表。
- 训记官方计划的只读性质。

---

本文同时作为实施设计与进度基线。主后端已切换 Python 3.12；普通同步、前端交互、中国区 P1 单动作及 P2/P3 完整真实训练日均已完成，当前计划 15 个动作全部完成端到端验证。D2 阶段 1 已于 2026-11-10 完成：顺延预览、确认 POST、原 Workout/日程更新、回读核验、审计幂等及 FakeGarmin 响应丢失恢复。本机实际数据库已迁移至 `c5d6e7f8a9b0`，保留升级前的 b4 完整备份并新增迁移后备份。计划页顺延弹层、日期对比、单次确认、目标日轮询、失败恢复及桌面/移动端模拟浏览器验收随后完成。独立 P4 真实改期及独立 P5 连续两轮真实改期的 API、ID 回读和 Connect/FR955 目视均已完整通过；P5 使用隔离数据库，未使用正式数据库，未写入 P0–P4 保护对象，未删除任何远端对象。2026-11-11 又完成 `syncing` 15 分钟超时自动恢复：普通同步和顺延均保留原 ID，重新确认不重复创建，旧 runner 不得覆盖新 attempt，恢复 JobRun 脱敏留痕。本轮相关四文件 **35 passed**，Garmin 全量 **121 passed、1 skipped**，后端全量 **1148 passed、6 skipped、1 failed，覆盖率 90.71%**；唯一失败仍为 2.9 记录的既有 AI 限流 UTC 跨日问题。上述超时恢复切片未读取正式数据库、未访问真实 Garmin。随后独立 P6 已在中国区完成 Workout 创建后和日程创建后的两次真实进程杀死，再由独立进程按 900 秒超时恢复；attempt 1 → 2 → 3，Workout `38224225`、日程 `34841221` 全链路各只创建 1 次，最终远端对象及本地记录均唯一，完整训练语义和 2026-11-19 日程关联回读通过。P6 使用隔离数据库，未读取正式 `backend/data/app.db`，未写入 P0–P5 保护对象，未删除任何远端对象；用户已于 2026-11-11 09:46 确认 Connect/FR955 显示正常，完整 P6 通过，功能开关默认关闭。服务器上线仍需完成 15.1.1 的 P7 生产环境适配、P8 PostgreSQL/发布回归和 P9 部署灰度，当前不应直接把现有 Python 3.11 生产镜像用于 Garmin 写入。
