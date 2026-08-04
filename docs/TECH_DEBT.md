# 技术债与偏差记录

> Sprint 1（M1/M2/M3/M3-FIX）复盘 · 2026-08-04
> 每条注明：来源任务 / 影响 / 建议处理时机。

## 一、实现与 PRD 的偏差

| # | 偏差 | 说明 | 状态 |
|---|------|------|------|
| D1 | 佳明接入未走 PRD 原定的 `garminconnect` 封装库 | 账号在中国区（garmin.cn），全球区登录成功但返回空数据；且 garminconnect 对 CN 区 resume 会话有 bug。已改用底层 `garth` 直连，PRD §6.2 已于 2026-08-04 同步更新 | 已闭环（PRD 已修正） |
| D2 | xunji 集成测试门禁方式与 garmin 不一致 | xunji 集成测试以「是否配置 XUNJI_API_KEY」为门禁，会在常规全量测试时真实外呼（消耗 15s 限频额度、依赖网络）；garmin 用 `RUN_GARMIN_INTEGRATION=1` 显式门禁 | 待统一（见 T2） |
| D3 | token 缓存目录沿用 `~/.garminconnect` | 虽已弃用 garminconnect 库，仍沿用其缓存目录名（PRD §6.2 原文如此），无功能影响 | 保留，符合 PRD |

## 二、技术债清单

| # | 事项 | 来源 | 影响 | 建议处理 |
|---|------|------|------|----------|
| T1 | `garth` 官方已宣布停止维护（import 时 DeprecationWarning） | M3-FIX | 佳明接口变动时无上游修复 | 关注替代方案（如自维护 fork / 直连 HTTP 封装）；adapter 已隔离，替换成本可控。V2 前评估 |
| T2 | xunji 集成测试在配 Key 时自动真实外呼 | M2 | CI/日常全量测试会打真实 API，可能触发限频 | 改为 `RUN_XUNJI_INTEGRATION=1` 显式门禁，与 garmin 一致。M4 开工前处理 |
| T3 | 前端无测试基建 | 前端骨架（M6 前置） | P0 要求 Vitest + Testing Library，目前 package.json 无测试脚本 | M6 开工时先搭 Vitest，再写页面（TDD） |
| T4 | `backend/tests/manual_garmin_check.py` 冒烟脚本残留 | M3 | 非 pytest 用例，功能与集成测试重复 | 功能稳定后删除（其 docstring 已注明"用完可删"） |
| T5 | 本地 venv 仍装有 garminconnect（requirements 已移除） | M3-FIX | 仅开发机环境冗余，不影响代码 | 重建 venv 时自然消除；无需单独处理 |
| T6 | workout/match_candidate/xunji_plan/ai_report 等表已建未用 | M1 | 无（按计划 M4 起启用） | 属设计内超前建表，不处理 |
| T7 | 适配器未覆盖行均为真实网络分支（garmin 96% / xunji 97%） | M2/M3 | 真实异常路径只能靠集成测试验证 | 接受现状，集成测试手动门禁保留 |

## 三、Sprint 1 验收核对结论

- 测试：后端 75 passed / 1 skipped（garmin 集成测试门禁跳过），整体覆盖率 98.01%（≥80% 达标，新增代码均 ≥85%）；前端尚无测试（M6 才进入前端）。
- M1/M2/M3 验收逐条核对见 Sprint 评审记录，全部达成（M3 验收以 garth 直连路径达成，PRD 已同步）。
