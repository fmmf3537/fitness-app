# 技术债与偏差记录

> Sprint 1（M1/M2/M3/M3-FIX）复盘 · 2026-08-04
> Sprint 2（M4/M5/M6/M7，MVP 里程碑）复盘 · 2026-08-06（见第四节起）
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
