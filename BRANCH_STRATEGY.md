# 分支策略 · BRANCH_STRATEGY

> 生效日期: 2026-08-25
> 决策背景: 一次全量审计 (`docs/AUDIT_2026.md`) 后,主分支冻结,所有未来迭代在 `multiuser-v2` 上进行。

## 一、两条线

| 分支 | 角色 | 状态 |
|---|---|---|
| `main` | 生产稳定线(单用户版本) | **冻结** —— 接受 hotfix,其它一律拒 |
| `multiuser-v2` | 活跃开发线(多用户 + 全部 P0/P1 修复) | 当前默认开发分支 |

`origin/main` 是远端生产部署的事实来源。`origin/multiuser-v2` 跟随本地日常 push。

## 二、main 冻结规则

- ✅ 允许:`git switch main` 上做 trivial hotfix —— 拼写错误、文档断链、CI 配置小修、紧急安全补丁
- ❌ 禁止:任何新功能、重构、跨文件改动、P0/P1 修复
- 🚫 严禁:在 main 上直接 `git push` 到 origin/main

合并方向永远是: **multiuser-v2 → main**,反过来不行。

## 三、护栏(Git Hooks)

仓库根 `.githhooks/` 目录包含两个 hook,跟随仓库走,clone 下来自动可用:

- **`.githooks/pre-commit`** —— 在 main 上 commit 时给红字警告,要求显式输入 `hotfix` 才放行(软拦截)
- **`.githooks/pre-push`** —— 推到 `origin/main` 一律拒绝,只能 `SKIP_MAIN_PUSH_GUARD=1 git push` 绕过(硬拦截,仅合并步骤使用)

### 安装

仓库已配 `core.hooksPath = .githhooks`。Clone 下来后 hook 自动生效。如被重置:

```bash
git config core.hooksPath .githhooks
```

Windows PowerShell 同理:

```powershell
git config core.hooksPath .githhooks
```

### 例外步骤(明确允许)

当你判断 multiuser-v2 已经稳定可上线,执行合并:

```bash
git switch main
git merge --no-ff multiuser-v2 -m "release: multiuser-v2 → main"
SKIP_MAIN_PUSH_GUARD=1 git push origin main
```

`--no-ff` 保留合并提交作为审计痕迹,`SKIP_MAIN_PUSH_GUARD=1` 是显式的"我知道我在干什么"信号。

## 四、什么时候可以"释放" multiuser-v2 → main

最低条件(全部满足才合并):

1. `docs/AUDIT_2026.md` 5 个 P0 全部修复并通过测试
2. `.env` 中所有真实凭据完成轮换 + `docs/KEY_ROTATION_RUNBOOK.md` 落地
3. `preflight` 6 阶段自检全部通过
4. 至少一次手机端冒烟通过(见 `docs/ANDROID.md`)
5. `main` 上当前部署保持可用(回滚路径明确)

满足后,在 `docs/RELEASES/` 写 release notes,再走合并流程。

## 五、谁来执行

只有项目 owner(小马哥)可以合并 main。所有其它人(包括将来的 AI 助手)只能:

- 在 multiuser-v2 上 commit / push
- 不得直接修改 main
- 不得绕过 hook(即使看起来"很紧急")

## 六、为什么不是 rebase

考虑过 `multiuser-v2` 持续 rebase main 来保持线性。但拒绝,因为:

- rebase 会改写 multiuser-v2 的 commit hash,如果你在多台机器或 IDE 里有未推送的 commit 会冲突
- merge --no-ff 留下合并节点,更清楚地表达"这是从哪条线来的"
- main 长期不动,rebase 与否关系不大

## 七、未来如果分叉太多

如果 multiuser-v2 在 main 之后累计 > 50 个 commit,或 PRD 大改到 main 难以直接 merge 时,评估 `archive-main-and-fork` 模式:把 main 改名 `legacy-v1`,新开 `main` 指向 multiuser-v2。当前不适用,记录在此供将来参考。
