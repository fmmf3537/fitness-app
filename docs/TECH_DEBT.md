# 技术债与偏差记录

> Sprint 1（M1/M2/M3/M3-FIX）复盘 · 2026-08-04
> Sprint 2（M4/M5/M6/M7，MVP 里程碑）复盘 · 2026-08-06（见第四节起）
> Sprint 3（V1-1/V1-2/V1-3）复盘 · 2026-08-07（见第六节）
> Sprint 4（V1-4/V1-5/V1-6/V1-7，V1 里程碑 v1.0）复盘 · 2026-08-07（见第七节）
> Sprint 5（V2-1 Kimi 与多模型 / V2-2 周期复盘 / V2-3 截图识别）复盘 · 2026-08-10（见第八节）
> Sprint 7（V2-7 手动同步与首日缺陷修复 / V2-8 训练计划页 / V2-9+V2-9b 移动端抽屉）复盘 · 2026-08-11（见第九节）
> Sprint 8（V3-1 Capacitor 打包 / V3-2 安卓原生手感 / V3-3 趋势图移动端 / V3-4 报告渲染与评分 / V3-5 分享海报 / V3-6 海报丰富化）复盘 · 2026-08-15（见第十节）
> 每条注明：来源任务 / 影响 / 建议处理时机。

## 一、实现与 PRD 的偏差

| # | 偏差 | 说明 | 状态 |
|---|------|------|------|
| D1 | 佳明接入未走 PRD 原定的 `garminconnect` 封装库 | 账号在中国区（garmin.cn），全球区登录成功但返回空数据；且 garminconnect 对 CN 区 resume 会话有 bug。已改用底层 `garth` 直连，PRD §6.2 已于 2026-08-04 同步更新 | 已闭环（PRD 已修正） |
| D2 | ~~xunji 集成测试门禁方式与 garmin 不一致~~ | 已于 2026-08-04 修复（T2）：统一改为 `RUN_XUNJI_INTEGRATION=1` 显式门禁，常规全量测试绝不真实外呼 | 已闭环 |
| D3 | token 缓存目录沿用 `~/.garminconnect` | 虽已弃用 garminconnect 库，仍沿用其缓存目录名（PRD §6.2 原文如此），无功能影响 | 保留，符合 PRD |

## 二、技术债清单

| # | 事项 | 来源 | 影响 | 建议处理 |
|---|------|------|------|----------|
| T1 | `garth` 官方已宣布停止维护（import 时 DeprecationWarning） | M3-FIX | 佳明接口变动时无上游修复 | 关注替代方案（如自维护 fork / 直连 HTTP 封装）；adapter 已隔离，替换成本可控。V2 前评估 |
| T2 | ~~xunji 集成测试在配 Key 时自动真实外呼~~ | M2 | ~~CI/日常全量测试会打真实 API，可能触发限频~~ | 已处理（2026-08-04）：`RUN_XUNJI_INTEGRATION=1` 显式门禁，与 garmin 一致 |
| T3 | ~~前端无测试基建~~ | 前端骨架（M6 前置） | ~~P0 要求 Vitest + Testing Library，目前 package.json 无测试脚本~~ | 已闭环（M6）：Vitest + Testing Library 就位，Sprint 2 评审补 @vitest/coverage-v8 |
| T4 | `backend/tests/manual_garmin_check.py` 冒烟脚本残留 | M3 | 非 pytest 用例，功能与集成测试重复 | 功能稳定后删除（其 docstring 已注明"用完可删"） |
| T5 | 本地 venv 仍装有 garminconnect（requirements 已移除） | M3-FIX | 仅开发机环境冗余，不影响代码 | 重建 venv 时自然消除；无需单独处理 |
| T6 | workout/match_candidate/xunji_plan/ai_report 等表已建未用 | M1 | 无（按计划 M4 起启用） | 属设计内超前建表，不处理 |
| T7 | 适配器未覆盖行均为真实网络分支（garmin 96% / xunji 97%） | M2/M3 | 真实异常路径只能靠集成测试验证 | 接受现状，集成测试手动门禁保留 |

## 三、Sprint 1 验收核对结论（存档）

- 测试：后端 75 passed / 1 skipped（garmin 集成测试门禁跳过），整体覆盖率 98.01%（≥80% 达标，新增代码均 ≥85%）；前端尚无测试（M6 才进入前端）。
- M1/M2/M3 验收逐条核对见 Sprint 评审记录，全部达成（M3 验收以 garth 直连路径达成，PRD 已同步）。

---

## 四、Sprint 2（MVP）评审结论 · 2026-08-06

### 4.1 测试与覆盖率

- 后端：`171 passed / 2 skipped`（garmin/xunji 真实集成测试走显式门禁跳过），总覆盖率 **96.52%**；
  融合引擎 matcher.py **100%** + fuse.py **100%**（要求 ≥90%，达标）。
- 前端：`30 passed`，行覆盖 **92.85%** / 语句 90.75%（评审中发现 client.js 覆盖不足，当场补 20 例测试后达标）。
- 全量回归无失败；真实 API 集成测试仍保持手动门禁，不进常规全量。

### 4.2 US-1 ~ US-4 验收标准逐条核对

| AC | 结论 | 证据 / 说明 |
|----|------|-------------|
| US-1 AC1 每日 22:47 定时拉取 | ✅ | `scheduler.py`：22:47 当日 + 22:52 前一日补拉 |
| US-1 AC2 失败重试 3 次指数退避 + 告警 | ⚠️ 部分 | 重试（1s/4s/16s）与失败落 `job_run` ✅；**界面告警未做**，推送按 PRD 属 V2（见 T8） |
| US-1 AC3 同日重复运行幂等 | ✅ | datestr+localid / activity_id upsert，测试与 7 天实跑均验证（8-03 重跑 0 新增） |
| US-1 AC4 佳明 token 过期自动重登 | ✅ | garth resume 失败自动用缓存凭据 login；429 指数退避 |
| US-2 AC1 重叠 ≥60% 自动合并 | ✅ | matcher 第一轮，实跑 3 例力量训练全部 auto_matched |
| US-2 AC2 时间接近入待确认 + 合并/拆分 | ✅ | 第二轮 reason=time_close；前端 CandidatesPage 已实测操作 |
| US-2 AC3 garmin_only 提示 + 一键生成训记草稿 | ⚠️ 部分 | 力量类型 garmin_only 自动入队提示 ✅；**一键草稿依赖写回流，排至 V1-5**（见 T9） |
| US-2 AC4 xunji_only 正常入库 | ✅ | fuse 单边分支 + 测试覆盖 |
| US-2 AC5 一日多练不串扰 | ✅ | 2026-08-04 力量+羽毛球正确拆分两条 workout |
| US-2 AC6 连续 7 天准确率 ≥90% | ✅ | `scripts/match_audit.py`：7-31~8-06 自动匹配 3/3，**100%**，人工纠正 0 |
| US-3 AC1 动作维度取训记 | ✅ | fuse.movements_json 取自训记 raw_json |
| US-3 AC2 时长/热量/心率取佳明 | ✅ | duration_s/calories/avg_hr/max_hr 取佳明 |
| US-3 AC3 详情页三视角切换 | ✅ | WorkoutDetailPage「融合/训记原始/佳明原始」标签，有测试 |
| US-3 AC4 外键可追溯 | ✅ | workout.xunji_train_id / garmin_activity_id |
| US-4 AC1 日历视图 | ✅ | CalendarPage 标记训练日、点击进详情 |
| US-4 AC2 详情卡片（组次表+心率曲线+时长/热量） | ✅ | WorkoutDetailPage + HeartRateChart（ECharts） |
| US-4 AC3 趋势页（4/12 周容量、部位频次） | ➖ 未做 | PRD 标 MVP，但《开发计划》排 V1-6；按计划执行，记偏差 D4 |

### 4.3 MVP 完成标志核对

- 连续 7 天（2026-07-31 ~ 08-06）数据链路全成功：8 条 `daily_sync` job_run 全部 success、每步均 1 次尝试即过、0 失败 0 重试；
- 看板数据正确：5 条 workout 与真实训练一致（3 力量自动匹配 + 2 羽毛球 garmin_only），待确认队列 0 积压；
- **保留项**：7 天 job_run 为 08-06 一次性逐日补跑产生，APScheduler 常驻进程"连续 7 天无人值守"尚未实测（见 T11）。
- 结论：**MVP 达成（带 T11 保留项，V1 期间观察闭环）**，打 tag `sprint-2`。

## 五、Sprint 2 新增偏差与技术债

| # | 事项 | 来源 | 影响 | 建议处理 |
|---|------|------|------|----------|
| D4 | US-4 AC3 趋势页 PRD 标 MVP、开发计划排 V1-6 | 计划间不一致 | 无（以开发计划为准） | V1-6 实现；下次 PRD 修订时把 US-4 AC3 改标 V1 |
| T8 | 同步失败仅有 job_run 日志，界面无告警 | M5/M6 | 失败需人工查库才能发现 | V1 在看板加失败横幅；推送告警随 V2-4 |
| T9 | garmin_only_strength 只有提示，无一键生成训记草稿 | M4 | US-2 AC3 半达成 | 依赖 V1-5 写回确认流，届时闭环 |
| T10 | HeartRateChart 分支覆盖 50%、页面级 83-90% | M6 | ECharts option 构造分支未测 | 后续补 chart option 单测；不阻塞 V1 |
| T11 | 定时任务未做 7 天无人值守实测 | M7 | 调度可靠性未经长期验证 | V1 开发期间本机常驻观察，闭环后销项 |

---

## 六、Sprint 3（V1-1 LLM 适配层 / V1-2 历史导入 / V1-3 AI 点评）评审与复盘 · 2026-08-07

### 6.1 测试与覆盖率

- 后端：`247 passed / 3 skipped`（真实 API 集成测试由环境变量显式门禁放行），整体行覆盖 **94.67%**（≥85% 达标）；
  适配器 llm 89% / xunji 97% / garmin 96%，核心服务 matcher/fuse/models 100%。
- 前端：`35 passed`（6 个测试文件），v8 覆盖：语句 90.95% / 行 92.77%（分支 76.51% 偏弱）。
- 安全回归：backfill 路由补挂统一认证（`[FIX] backfill 路由接入统一认证`），未登录一律 401。

### 6.2 US-5 / US-6 / US-9(AC2) 验收标准逐条核对

| AC | 判定 | 证据 / 缺口 |
|----|------|-------------|
| US-5 AC1 训记逐日回溯（2023-02-01 起 / 15s 限频 / 空日跳过 / 断点续传） | ✅ | `backfill.py` XUNJI_DAY_INTERVAL_S=15.0、done/empty 跳过、failed 次日重试；限频 pacing 有测试断言 |
| US-5 AC2 佳明活动 2017 全量分页 + 每日健康自 2023-02-01 | ✅ | 活动列表无日期过滤全量分页（100/页，页进度落库）；⚠️ `GARMIN_BACKFILL_START_DATE` 配置项定义后无引用，死代码（T16） |
| US-5 AC3 佳明单会话长拉取 + 429 指数退避 | ✅ | 单次 run 单 GarminClient；BACKOFFS_429=(60,300,900)；登录守卫 + token 缓存 resume |
| US-5 AC4 进度可见 + 完成后统一融合 | ⚠️ 部分 | 后端进度 API（百分比/ETA/分阶段）+ 自动融合 ✅；**前端无 backfill 进度页**（T12） |
| US-6 AC1 同步后自动生成点评 | ✅ | sync 四步成功后调 run_daily_reviews，幂等跳过已有，失败不拖垮主流程；⚠️ 注释称"异步"实为同步串行（T17） |
| US-6 AC2 输入=本次+近4周历史+近7天睡眠/HRV/准备度 | ⚠️ 部分 | "同部位"实现为更细的"同动作"（口径偏差，可接受）；**训练准备度显式 None 未接入**（T14） |
| US-6 AC3 四节输出 + 落库可回看 | ✅ | PROMPT_SECTIONS 四节；ai_report 落库含 token/成本；前端 /ai-reports 可回看 |
| US-9 AC2 每次调用记 token/成本 + 月度汇总可见 | ⚠️ 部分 | llm_call 记账完整（token 强制取 API usage，失败也记账）✅；**无月度汇总 API/页面**（T13，属 V2-1 范围，提前登记） |

### 6.3 真实凭据历史导入数据核对（2026-08-07 09:18 完成，断点续跑约 5s 收尾）

| 指标 | 数值 | 合理性核对 |
|------|------|-----------|
| 训记扫描天数 | 1284/1284（2023-02-01 ~ 2026-08-07） | 与区间天数精确一致 ✅ |
| xunji_train | 127 条 / 127 个训练日（2023-02-09 ~ 2026-08-04） | 约每周 0.7 次训练，**待用户确认与主观预期同量级** |
| garmin_activity | 659 条（2017-12-12 起全量） | 覆盖 2017 起 ✅ |
| garmin_daily | 1284 行，逐日无空洞 | 与扫描区间一一对应 ✅ |
| workout | 723 = auto_matched 63 + garmin_only 596 + xunji_only 64 | 交叉校验：63+596=659=活动总数 ✅；63+64=127=训记总数 ✅； garmin_only 偏高因 2017-2023 佳明早于训记启用，合理 |
| match_candidate | 3 条 pending（均为 garmin_only_strength） | 符合 US-2 AC3 提示场景；time_close 候选 0 条 |
| job_run / ai_report / llm_call | 11 / 3 / 3 | 链路贯通 |

### 6.4 AI 点评抽查（3 篇，DeepSeek 真实生成，workout 1/4/2）

**做得好的：**
- 本次训练数据引用 100% 准确（重量/组次/时长/心率/热量与 workout 源记录逐一相符，时长换算正确）；
- 历史**容量数字**引用准确（如 07-24 深蹲 810kg、07-23 划船 540kg 均与库一致）；
- 恢复区能正确处理数据缺失（明确声明"睡眠缺失""体重无记录"，不编造）；
- 建议具体可执行（到动作/重量/组次粒度，含退阶方案）。

**改进点：**
1. 历史**组次级描述**偶有概括失真：如把 07-14 坐姿划船（25/35/30/30 混合四组）概括为"35kg×12"；把 07-24 站姿推举（20×10/25×8/25×6/25×4）错述为"20×8×2"并据此得出"完全一致"的错误结论 → prompt 应要求"逐组列出所引历史，禁止概括单组为代表"（T15）；
2. 输出结构未被严格遵守：3 篇中 1 篇缺独立"完成质量"章节、1 篇多出"训练建议"章节 → system prompt 四节约束需加硬性校验或输出后结构检查（T15）；
3. 个别措辞自相矛盾（"总容量从150kg微降至180kg（+20%）"）→ 属模型生成噪声，可加后处理或降低温度（T15）。

### 6.5 Sprint 3 新增技术债

| # | 事项 | 来源 | 影响 | 建议处理 |
|---|------|------|------|----------|
| T12 | 前端无 backfill 进度页 | US-5 AC4 核对 | 导入进度只能调 API 查看 | V1-6 前端任务顺带补一个简易进度页/弹窗 |
| T13 | llm_call 无月度汇总 API/页面 | US-9 AC2 核对 | 月度成本不可见 | 已属 V2-1 范围，届时实现 |
| T14 | 训练准备度（training_readiness）未接入，显式 None | US-6 AC2 核对 | 点评恢复维度少一个信号 | 佳明 training readiness 端点调研后接入（V2 前可选） |
| T15 | 点评 prompt：历史组次概括失真 + 四节结构不强制 + 偶发自相矛盾措辞 | 6.4 抽查 | 引用可信度受损 | prompt 改结构化历史表 + 输出结构校验，V1-4 前完成 |
| T16 | `GARMIN_BACKFILL_START_DATE` 配置死代码 | US-5 AC2 核对 | 误导读者 | 删除或在活动分页接入起始日期过滤 |
| T17 | sync 内 AI 点评为同步串行，docstring 称"异步" | US-6 AC1 核对 | 措辞误导；同步日 LLM 延迟拉长任务 | 改注释，或 V2 移入后台任务 + 完成通知 |

**评审结论**：Sprint 3 目标（LLM 层、历史导入、AI 点评）核心闭环达成，测试与覆盖率达标；US-5 AC4（前端进度页）、US-6 AC2（准备度）、US-9 AC2（月度汇总）三处部分缺口已登记 T12-T14，不阻塞进入 V1-4。训记 127 条导入量待用户确认后归档。

---

## 七、Sprint 4（V1-4 下次建议 / V1-5 写回 / V1-6 趋势与报告 / V1-7 身体数据）评审与复盘 · 2026-08-07（V1 里程碑，tag v1.0）

### 7.1 测试与覆盖率

- 后端：`426 passed / 3 skipped`（3 条均为显式门禁的真实 API 集成测试），总覆盖率 **94.44%**（≥85% 达标）；
  核心服务 matcher/fuse/stats/models 100%，writeback 88%（未覆盖行均为真实外呼与兜底分支）。
- 前端：Vitest `97 passed`（15 个测试文件）；`npm run build` 通过；oxlint `0 warnings / 0 errors`。
- 与 2026-08-07 实地验收基线逐项一致，无回归。

### 7.2 US-7 / US-8 / US-12 验收标准逐条核对

| AC | 判定 | 证据 / 说明 |
|----|------|-------------|
| US-7 AC1 训记官方计划只读缓存 | ✅ | `sync_plan_cache` job_run 成功留痕；`query_next_plan_day` 只读本地 `xunji_plan`，生成建议时不发网络请求；当前缓存 universal:1（2026-08-07 起新周期） |
| US-7 AC2 建议到动作/重量/组/次粒度 | ✅ | `next_advice_v1` JSON schema 强制校验 + 标准动作名白名单；ai_report #4（DeepSeek，8123+2383 tokens）与训记计划 API 逐条对照一致（实地验收） |
| US-7 AC3 前端两类呈现（可写回带 diff 确认 / 需手动附指引） | ✅ | `classify_suggestions` 分类；NextAdviceSection「生成写回预览」调 preview 渲染 diff 高亮表，11 个前端测试覆盖 |
| US-8 AC1 写回前展示 diff，确认才执行 | ✅ | preview 只读原训练生成本地 diff，结构上不调用写回接口；confirm 是唯一 `dry_run=False` 路径（进程内串行锁） |
| US-8 AC2 保留 localid/start/end/note 元数据 | ✅ | `build_merged_train` 三级深合并（V1-5-FIX 修复整体替换丢数据）；真实写回服务器回查 6 动作 22 组分毫不差 |
| US-8 AC3 服务端返回覆盖本地缓存 | ✅ | `cache_trains` 用服务端标准化 res 覆盖 + 当日融合重跑更新 workout |
| US-8 AC4 45s 写回限频排队 | ✅ | 适配器 write 档 45s（按 datestr 维度）+ confirm 串行锁排队 |
| US-12 AC1 四类指标录入，date+type upsert | ✅ | height/weight/bp_systolic/bp_diastolic/blood_glucose，同日同类型覆盖；前后端测试覆盖 |
| US-12 AC2 趋势曲线 + 体重与容量同屏对照 | ✅ | `/api/stats/trends` 同返 weekly_volume 与 body_metrics；周容量复核 2026-07-20 周 = **22.32 吨**，与手算锚点一致 |
| US-12 AC3 体重同步训记三段式 | ✅ | 真实链路演示见 7.4：预览取 res.summary、未确认拒绝、confirmed 写入、服务器回查落账 |
| US-12 AC4 身高/血压/血糖仅本地，界面标注 | ✅ | `SYNCABLE_TYPES={weight, bodyfat}`，其余类型同步请求 400 拒绝；前端标注「仅本地」 |
| US-12 AC5 首次引导录入身高，按 date 存历史 | ✅ | 前端引导 + date+type upsert 保留历史 |
| US-12 AC6 AI 点评/复盘上下文纳入近 4 周体重趋势 | ✅ | `query_recovery_summary` 输出 weight_trend 进 prompt，测试锁定 |

### 7.3 高危项复查（grep 全仓 + 代码走查）

1. **硬编码密钥**：全仓 grep（`xjbody_`/`Bearer '...'`/`api_key=`/`password=`/`sk-` 等模式）仅命中文档说明与测试占位符，应用代码零硬编码；所有 Key 经 `config.py` 从环境变量读取，LLM Key 经 Fernet 加密入 settings 表。✅
2. **写回默认 dry_run**：`upsert_trains(dry_run=True)` / `upsert_body_metrics(dry_run=True)` 默认预览；全仓仅两处 `dry_run=False`——writeback confirm 与身体数据 confirmed=True 路径；后者未确认时抛 ValueError 且不发请求。✅
3. **限频装饰器覆盖**：所有 `xunjiapp.cn` 请求收敛于 `XunjiClient._post`（`@rate_limited`，读 15s/完整读 30s/写 45s，too frequent 按 retry_after_ms 重试 ≤3 次）；身体数据客户端继承复用，无旁路外呼。✅

### 7.4 真实链路演示记录（2026-08-07 复跑）

**写回确认流 dry_run 预览**（`scripts/preview_writeback_demo.py`，2026-08-03「背·二头·2」，upsert 外呼已被脚本强制禁用双保险）：
- 假设变更「宽距高位下拉 第1组 RPE 8→9」，diff 共 **145 行，changed=true 精确 1 行**（old='8' 即 08-07 真实写回落账值，反向印证写回持久化）；合并后 6 动作 22 组与服务器一致；全程零写回外呼。

**体重同步训记三段式**（`scripts/sprint4_body_sync_demo.py`，真实链路）：
1. dry_run=True 预览：返回 res.summary（体重 88kg），不发真实写入；
2. 门禁校验：dry_run=False 且未 confirmed → ValueError 拒绝且不外呼；
3. confirmed=True 真实写入（同值 upsert，幂等）；
4. 服务器回查：2026-08-07 weight=88 落账（记录 id **13063090**，与实地验收锚点一致）；
5. 附：height 不在 SYNCABLE_TYPES，同步门禁正确。

**数据存量锚点复核**：body_metric 2 条（08-07 weight 88.0 已同步 / height 178 仅本地）✅；ai_report 4 条（#4 next_advice DeepSeek 8123+2383）✅；xunji_train 08-03 六动作 22 组、宽距高位下拉第 1 组 rpe='8' ✅；job_run writeback/health_check 成功留痕 ✅。

### 7.5 Sprint 4 新增技术债（设计内遗留，不阻塞 v1.0）

| # | 事项 | 来源 | 影响 | 建议处理 |
|---|------|------|------|----------|
| T18 | 训记身体数据 API 录入侧真实联调仅覆盖 weight | V1-7 | bodyfat/围度写入路径未实测（代码同构，风险低） | V2 期间补 bodyfat 实测 |
| T19 | 前端 echarts chunk >500kB 构建警告 | V1-6 | 首屏加载体积偏大 | V2-5 部署前做 code splitting / 按需引入 |
| T20 | Kimi Provider 仍为桩实现 | V1-1 | 截图识别（V2-3）依赖 Kimi 视觉模型 | V2-1 用户补申请 Key 后接入 |
| T21 | 写回预览依赖 30s 完整读，连续演示/操作有等待感 | V1-5 演示 | UX 层面可接受，无限频风险 | 可选：预览缓存 diff 基准，确认时复用 |

**评审结论**：US-7 / US-8 / US-12 全部 AC 达成；测试基线（后端 426+3 / 94.44%，前端 97，build/oxlint 通过）与实地验收一致；两项真实链路演示复跑通过，服务器回查与锚点分毫不差；高危项复查全绿。**V1 里程碑达成，打 tag `v1.0`。** 遗留 T18-T21 登记跟踪，不阻塞发布。

---

## 八、Sprint 5（V2-1 Kimi 接入与多模型切换 / V2-2 周月复盘 / V2-3 截图识别）评审与复盘 · 2026-08-10

### 8.1 测试与覆盖率

- 后端：`538 passed / 4 skipped`（4 条均为显式门禁的真实 API 集成测试），总覆盖率 **94.69%**（≥85% 达标），与 2026-08-10 实地验收基线逐项一致；
- 前端：Vitest `113 passed`（**17** 个测试文件；验收锚点记为 16 文件，复核实为 17，测试总数一致，系锚点笔误，无回归）；
- 集成测试单跑注意：`-m integration` 只跑 1 条时会触发 85% 覆盖率门禁导致退出码 1（测试本身 passed），需加 `--no-cov`（见 T26）。

### 8.2 US-9 / US-10 / US-11 验收标准逐条核对

| AC | 判定 | 证据 / 说明 |
|----|------|-------------|
| US-9 AC1 设置页配置三家 Key 并切换默认模型 | ✅ | `adapters/llm.py` 注册表 DeepSeek/MiniMax/Kimi 均 implemented；Key Fernet 加密入 settings；PUT 前 `verify_api_key` 真实 ping 拒绝无效 Key；前端 SettingsPage 配置/切换/徽标 |
| US-9 AC2 每次调用记 token/成本 + 月度汇总可见 | ✅ | `llm_call` 记账（token 强制取 API usage，禁止本地估算，失败也记账）；`/api/settings/llm/usage` 与 `/api/llm/monthly-usage` 两个汇总粒度 + 设置页「本月用量」卡片；Kimi 真实调用记账 17+286 tokens、¥0.0078325 与单价表 6.5/27 手算一致（llm_call #5） |
| US-9 AC3 失败一键切换备用模型重试 | ✅（交互差异见注） | 默认模型连续失败 ≥2 次时设置页出现 banner「切换到 Y 并重试」（`consecutive_failures`/`suggested_fallback`）；注：入口在设置页而非报告页内联，无单条失败「原地重跑」，语义达成 |
| US-10 AC1 每周日 21:13 周复盘（六要素） | ✅ | `weekly_review` cron sun 21:13；WEEKLY_SECTIONS 六节齐全；ai_report #5（2026-08-03~09，DeepSeek 571+1287，¥0.003145）数据逐项核验 100%：3 次训练、总容量 10,710kg、五部位容量自洽、杠铃深蹲 PR 40kg vs 历史 35kg（精确动作名匹配，未与哈克机反向深蹲 70kg 混淆） |
| US-10 AC2 每月 1 日 09:23 月复盘（计划完成率+趋势图） | ✅ | `monthly_review` cron day=1 09:23 复盘上月；MONTHLY_SECTIONS 含计划完成率（精确 0.1%）/体成分/趋势（echarts 围栏块前端渲染） |
| US-10 AC3 导出 Markdown / PDF | ✅ | `/api/ai-reports/{id}/export?format=md\|pdf`；reportlab + STSong-Light CJK，实测 2 页中文正常；样例 `周复盘_2026-08-03_08-09.pdf` 已存仓库根目录（未入库） |
| US-11 AC1 上传截图→多模态→结构化 JSON | ✅ | `POST /api/screenshot/extract`：多图 ≤9、单张 ≤10MB、MIME 白名单；Kimi 视觉强制走 kimi 与默认文本模型无关；schema 校验失败附反馈自动重试 1 次 |
| US-11 AC2 预览确认后入库 | ✅ | extract 不落库，`confirm_import` 唯一入库入口（xunji_train `shot-` 前缀 localid + raw_json source=screenshot 可追溯 + match_day 重跑匹配）；前端预览页全字段可编辑 |
| US-11 AC3 字段识别准确率 ≥95% | ✅ | 评审现场复跑基准图（素材/训记分享报表示例.png）：**53/54 = 98.1%**，唯一未命中「集中弯举第 2 组 weight=15」，与 8-10 实地锚点一致；输出归档 `logs/sprint5_benchmark_rerun.log` |

### 8.3 真实链路锚点复核（2026-08-10 评审复跑）

| 锚点 | 复核结果 |
|------|----------|
| llm_call #5 kimi-k2.6 17+286 / ¥0.0078325 | ✅ 库中一致 |
| llm_call #6 weekly DeepSeek 571+1287 / ¥0.003145 ↔ ai_report #5 | ✅ 库中一致 |
| llm_call #7 vision_extract 4525+1414 / ¥0.0675905（生产路径） | ✅ 库中一致，purpose=vision_extract |
| 周复盘幂等重触发 skipped 且 llm_call 不增 | ✅ 两次 weekly_review job_run（10:39/10:50）均 report_id=5，llm_call 仅 #6 一条 |
| 环境坑：OS 残留 KIMI_API_KEY 遮蔽 .env（abf5229 override=True） | ✅ 修复后 kimi 调用成功且记账精确 |
| 生产服务 11:25 重启、新路由 401 非 404 | ⚠️ 评审时（11:44）发现该实例已退出（进程不在，最后留痕 health_check 11:11）；11:46 重新拉起：`/health` ok、`/api/screenshot/extract` 401（认证生效、新代码在位）；**12:11 health_check 已留痕成功（job_run #27），调度器存活证实**；22:47 daily_sync 待当晚自然产生 |

### 8.4 技术债销项与新增

**销项**（早已实现、本节统一核销）：T9（garmin_only 一键草稿随 V1-5 写回流闭环）、T12（V1-6 已补 BackfillPage）、T13（V2-1 月度汇总 API+页面已上线）、T20（V2-1 Kimi 已真实接入 kimi-k2.6）。

| # | 事项 | 来源 | 影响 | 建议处理 |
|---|------|------|------|----------|
| T22 | 截图识别预览态刷新丢失（前端 state 未持久化） | V2-3 评审 | 识别结果未确认前刷新页面需重新识别（重复计费） | 预览数据 localStorage 暂存或后端暂存草稿态 |
| T23 | 确认入库未做服务端幂等，仅靠前端按钮置灰兜底 | V2-3 评审 | 双击/重试可能重复写 xunji_train | confirm 加 client_request_id / 内容指纹去重 |
| T24 | PDF 导出中 echarts 围栏块以代码文本呈现、不渲染图表 | V2-2 评审 | PDF 保真度逊于页面 | 导出前服务端渲染图片或 PDF 中省略图表块（附说明） |
| T25 | DeepSeek 近期涨价并引入峰谷定价 | V2-1 外部变化 | 默认单价表失真，成本低估 | 新价生效后用 `LLM_PRICES_JSON` 校准（含峰谷口径决策），历史成本不重算 |
| T26 | `-m integration` 单跑触发 85% 覆盖率门禁、退出码 1 | 8.1 复核 | 易误判为测试失败 | pytest.ini 注释说明或集成标记自动 `--no-cov` |

**评审结论**：US-9 / US-10 / US-11 全部 AC 达成；测试基线与实地验收锚点逐项一致（538+4 / 94.69% / 前端 113）；基准识别复跑 98.1% 与锚点分毫不差；记账/幂等/调度锚点全部复核通过。**Sprint 5 目标达成，打 tag `sprint-5`。** 遗留 T22-T26 登记跟踪，不阻塞。

---

## 九、Sprint 7（V2-7 手动同步与首日缺陷修复 / V2-8 训练计划页与 plan_review / V2-9+V2-9b 移动端抽屉）评审与复盘 · 2026-08-11

### 9.1 测试与覆盖率

- 后端：`634 passed / 6 skipped`（2 条 PG testcontainers 环境跳过 + 4 条显式门禁真实 API 集成测试），总覆盖率 **93.67%**（≥85% 达标），与 2026-08-11 实地验收基线逐项一致；
- 前端：Vitest `158 passed`（25 个测试文件）；oxlint **0 error**（1 个 V2-4 既有 warning，见 T28）；`npm run build` 通过。
- 全量回归无失败；与基线不一致项：无。

### 9.2 Sprint 7 背景锚点回归复核（2026-08-11 评审留痕，均已通过实地/真机验收）

| 锚点 | 复核结果 |
|------|----------|
| 缺陷 1：`POST /api/sync/{date}` 裸奔 | ✅ `api/sync.py` 路由级 `dependencies=[Depends(require_auth)]`，未登录 401；有鉴权测试 |
| 缺陷 2：同步阻塞 504 | ✅ 同步后台线程化：POST 立即 202、同日期在跑 409、`GET /api/sync/status` 轮询；`sync_manager.py` 覆盖 100%；nginx `proxy_read_timeout 300s` 兜底已随部署到位 |
| 缺陷 3a：当日缓存拉不到补录组数 | ✅ `sync.py` is_today 分支 `force_refresh=True` 绕过同日缓存；历史日期保持缓存命中不变 |
| 缺陷 3b：重融合不刷新、AI 不重生成 | ✅ `matcher._refresh_stale_workouts`：fetched_at > updated_at 时就地更新 movements_json（复用 fuse._extract_movements，不新建行），删除当日旧 session_review/next_advice 后重生成 |
| 缺陷 4：详情页缺 session_review | ✅ WorkoutDetailPage 挂 SessionReviewSection（有/无报告两态均有测试） |
| 计划页 + plan_review 全链路 | ✅ `api/plans.py` upcoming/refresh(202/409)/review 全端点鉴权；plan_review 覆盖式幂等 + 标准动作名白名单校验；云端真实计划缓存 universal:1 实地联调通过 |
| 移动端抽屉五项真机验收 | ✅ BottomSheet + dvh 兜底链 + min-w-0 + footer shrink-0（V2-9b）、导航汉堡菜单、4 处表格 overflow-x-auto，真机全过 |

### 9.3 技术债销项

- 缺陷 1（sync 裸奔接口）、缺陷 2（504 超时）、缺陷 3（当日缓存 + 重融合不刷新）、缺陷 4（详情页点评缺失）：随 V2-7 全部闭环；
- 移动端报告阅读体验（长滚动问题）：随 V2-9 底部抽屉闭环，V2-9b 修复真机实测三处残留缺陷后验收通过。

### 9.4 Sprint 7 新增技术债

| # | 事项 | 来源 | 影响 | 建议处理 |
|---|------|------|------|----------|
| T27 | jsdom matchMedia 统一 mock 默认桌面（matches=false），移动端用例须自行 `installMatchMedia(true)` 且 afterEach 复位 | V2-9/V2-9b | 新写移动端用例忘记复位会污染同文件后续用例 | 维护注意即可；新增移动端用例时参照 Layout.test.jsx 模式 |
| T28 | `FitImportPage.test.jsx:77` 既有 oxlint warning（未使用变量 `user`） | V2-4 | 无功能影响，lint 输出有噪音 | 下次触碰该文件时顺手删除该变量 |

### 9.5 保留的已知设计内遗留（确认不处理，继续跟踪）

- **T23 保留**：截图确认入库未做服务端幂等，前端按钮置灰兜底（双击/重试理论风险，单机自用可接受）；
- **T24 保留**：PDF 导出中 echarts 围栏块不渲染图表，以代码文本呈现；
- **T25 保留**：DeepSeek 涨价/峰谷定价待校准（`LLM_PRICES_JSON`），历史成本不重算；
- **设计内成本项**：当日强刷/重融合每次触发当日 AI 报告重生成一次（单次成本约几分钱），属预期行为，不做节流。

**评审结论**：Sprint 7 背景锚点七项全部复核通过（与 2026-08-10/11 实地/真机验收一致）；测试基线（后端 634+6 / 93.67%，前端 158 / 25 文件，oxlint 0 error，build 通过）逐项一致无回归。**Sprint 7 目标达成，打 tag `sprint-7`。** 新增 T27/T28 登记跟踪，T23-T25 保留观察，不阻塞。

---

## 十、Sprint 8（V3-1 Capacitor 打包 / V3-2 安卓原生手感 / V3-3 趋势图移动端 / V3-4 报告渲染与评分 / V3-5 分享海报 / V3-6 海报丰富化）评审与复盘 · 2026-08-15

### 10.1 测试与覆盖率

- 后端：`671 passed / 6 skipped`（2 条 PG testcontainers 环境跳过 + 4 条显式门禁真实 API 集成测试），总覆盖率 **93.48%**（≥85% 达标）；
- 前端：Vitest `240 passed`（32 个测试文件）；oxlint **0 error**（1 个存量 warning 为 T28，不动）；`npm run build` 通过（chunk >500kB 警告为 T19 既有项）；`npm run test:capacitor` 通过；
- 与评审基线逐项一致，无回归。注：V3-6 期间全量 vitest 曾出现 1 例偶发 flake，重跑两轮全绿未定位（登记 T29 观察）。

### 10.2 六个任务完成度逐项确认（真机验收 2026-08-15 全过）

| 任务 | 提交 | 完成度 | 验收要点 |
|------|------|--------|----------|
| V3-1 Capacitor 打包安卓 APP | 7e2513f | ✅ | release APK 产出可安装（见附录 A）；服务器直连方案零 CORS 改造，前端更新走 docker 重建不重发 APK |
| V3-2 安卓原生手感打磨 | 48653c8 | ✅ | 底部五 Tab / 返回键三分支（弹层优先/非根返回/根路由最小化）/ 状态栏安全区，真机全过 |
| V3-3 趋势图表移动端适配修复 | 0858b2b | ✅ | 趋势图移动端真机验收通过（2026-08-13 截图确诊问题已修复） |
| V3-4 报告渲染去 AI 味 + session_review 评分体系 | 62791fe | ✅ | 报告渲染 / 评分徽章真机验收通过；AI 符号裸奔问题闭环 |
| V3-5 朋友圈分享海报与原生分享 | 9f9e1ae | ✅ | 海报预览 / 微信朋友圈分享链路真机全过 |
| V3-6 分享海报内容丰富化：装配端点 + 六形态自适应布局 | 305a19b | ✅ | 六形态（力量/有氧/混合/无 PR/无亮点/无评分）demo 留档 `frontend/scripts/poster-demo-*`，真机验收通过 |

抽屉（BottomSheet）与状态栏项随 V2-9b / V3-2 一并复验通过。

### 10.3 技术债销项（Sprint 8 期间发现并已闭环）

| 事项 | 闭环任务 |
|------|----------|
| 报告 AI 符号裸奔（markdown 标记直出） | V3-4 报告渲染重写 |
| 海报内容单薄（仅标题+日期） | V3-6 装配端点 + 内容丰富化 |
| 有氧指标 "-" 占位 | V3-6 有氧形态展示时长/配速/心率实值 |
| 无评分海报大片空白 | V3-6 六形态自适应布局 |

### 10.4 Sprint 8 新增技术债

| # | 事项 | 来源 | 影响 | 建议处理 |
|---|------|------|------|----------|
| T29 | 全量 vitest 出现 1 例偶发 flake（V3-6 期间重跑两轮全绿，未定位） | V3-6 | 偶发误报风险，当前不阻断 | 后续观察，复现即修 |
| T30 | 无 PR/无亮点的有氧海报，点评卡与水印间空白略大 | V3-6 真机验收 | 观感问题，不阻断 | 下次触碰海报布局时微调间距 |

### 10.5 保留项（继续跟踪，维持原判）

- **T23 保留**：截图确认入库未做服务端幂等，前端按钮置灰兜底；
- **T24 保留**：PDF 导出中 echarts 围栏块不渲染图表；
- **T25 保留**：DeepSeek 涨价/峰谷定价待校准（`LLM_PRICES_JSON`）；
- **T28 保留**：`FitImportPage.test.jsx:77` oxlint warning（未使用变量），下次触碰该文件顺手删。

### 附录 A：安卓 APK 信息（2026-08-15 评审记录）

| 项 | 值 |
|----|-----|
| release APK | `frontend/android/app/build/outputs/apk/release/app-release.apk` |
| 体积 | 3,516,850 B ≈ **3.35 MB**（debug 签名，单用户不上架，不做签名加固） |
| 构建时间 | 2026-08-13 17:14（V3-1 产出，V3-2~V3-6 均为 Web 层改动，走 docker 重建生效，未重发 APK） |
| 冷启动耗时 | 真机验收（2026-08-15）反馈秒开、无白屏等待感；**未留精确计时**——后续可用 `adb shell am start -W <package>/.MainActivity` 补录精确值 |
| 安装方式 | 微信文件传输助手 / `adb install -r`（详见 docs/ANDROID.md） |
