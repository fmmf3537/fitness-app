# SPLIT-FIX-DIVERGED-MAIN 切片修复提示词：服务器 main 分叉重整（ahead 2, behind 1）

## 0. Cursor CLI 调用方式

服务器上 `cursor` CLI 启动后，直接把**本文件 §2 起的全部内容**作为 prompt 粘贴进 cursor 交互模式。Cursor 会按 §1 → §4 顺序执行。

如果你想先看再决定：先在终端跑 `pwd && git status -sb` 确认当前在 `/home/ubuntu/fitness-app` 且确实是 `[ahead 2, behind 1]`，再把本 prompt 粘给 Cursor。

---

## 1. 你是什么

你是本仓库的 Git 运维操作员。本提示词是唯一任务来源：**只做 git 操作完成分支重整**，不修改任何代码文件，不修改 git config。
红线：禁 `git config` / `git push --force` / `git push --force-with-lease` / `git reset --hard` / 任何会丢失未推送 commit 的命令；不得删除任何文件（包括 `docker-compose.override.yml`）；不得改动 prompt 文件预算之外的任何 git 配置。

## 问题（实读服务器状态）

服务器 `/home/ubuntu/fitness-app` 状态：

```
$ git log --oneline origin/main..HEAD   # 本地 ahead 2
$ git log --oneline HEAD..origin/main   # 远端 behind 1
$ git status -sb
## main...origin/main [ahead 2, behind 1]
?? docker-compose.override.yml
```

- **本地有、远端没有（ahead 2）**：
  - `9eb20a3` merge V5
  - `4fffcfd` 腾讯云 pip
- **远端有、本地没有（behind 1）**：
  - `fe9fb06` fix(V5): 移动端导航补全「教练须知」「跟教练聊聊」入口
- **未推送状态**：本地 2 个 commit 未推到 GitHub
- **未跟踪文件**：`docker-compose.override.yml`（本地 DEPLOY.md §4 共存跳过 caddy 方案，git pull 不影响）

## 已核实的关键事实（基于项目历史，可直接采信）

- 远端 main 最新 2 个 commit（origin/main HEAD）：
  - `9f7594d` docs(DEPLOY): §12 切片流水线开发的增量部署（V5+）
  - `fe9fb06` fix(V5): 移动端导航补全「教练须知」「跟教练聊聊」入口
- 上一轮由 DSH agent 推送到 origin main（commit hash 经 git log origin/main 验证存在）
- 本地 ahead 2 commits：用户历史本地提交（merge V5、腾讯云 pip 适配）
- 本地未推送，不会因为 fast-forward 而丢失（`--no-rebase` merge 保留所有 commit）
- `docker-compose.override.yml` 是 untracked 文件，merge 不会影响它

## 任务范围（只做 git，不做代码改动）

### Step 1：拉取并 merge（推荐 merge 提交策略，保留全部历史）

```bash
cd /home/ubuntu/fitness-app
git fetch origin
git pull --no-rebase origin main
```

**为什么 merge 而不是 rebase**：本地有 2 个 ahead commit（merge V5、腾讯云 pip），用户历史工作。rebase 会改写这 2 个 commit 的 hash，破坏已部署的引用（如果生产服务器运行的是这些 commit 对应的代码）。`--no-rebase` merge 保留所有 commit hash 与历史线性可追溯。

### Step 2：如果有冲突

预期冲突：仅 `docker-compose.override.yml` 这个 **untracked** 文件不会冲突（git pull 不动 untracked）。但若有 tracked 文件冲突：

```bash
git status                    # 列出冲突文件
# 编辑冲突文件 → 删 <<<<<<< / ======= / >>>>>>> 标记
git add <已解决文件>
git commit                    # 完成 merge commit（编辑器预填 message）
```

merge commit message 通常自动生成，如：`Merge branch 'main' of github.com:fmmf3537/fitness-app`

### Step 3：验证重整后状态

```bash
git log --oneline -8                          # 看合并后历史
git status -sb                               # 期望：无 ahead/behind，仅 ?? docker-compose.override.yml
git log origin/main..HEAD                     # 期望：空
git log HEAD..origin/main                     # 期望：空
git remote show origin | grep "HEAD branch"   # 期望：HEAD branch: main
```

### Step 4：（可选）确认 GitHub 同步

```bash
git ls-remote origin main
```

应输出 origin/main 当前 commit hash（合并后最新）。

## 红线

- 禁 `git push --force` / `--force-with-lease` / `-f`（会丢失远端历史）
- 禁 `git config`（修改 push/pull/remote 等配置）
- 禁 `git reset --hard`（会丢本地 untracked 改动）
- 禁删除 `docker-compose.override.yml`（用户本地未跟踪配置）
- 禁修改任何代码文件 / `.env` / Docker 配置 / alembic 迁移

## 自报告要求（必须按格式输出）

1. **执行步骤摘要**（每条命令的 stdout/stderr 关键行）
2. **冲突情况**：是否有冲突？如无写"无冲突"，如有列出冲突文件与解决方式
3. **合并后状态**：`git log --oneline -8` 输出 + `git status -sb` 输出
4. **远端同步验证**：`git ls-remote origin main` 输出 + 与本地 HEAD 对比
5. **确认清单**：
   - [ ] 未跑 `git push --force`
   - [ ] 未跑 `git config`
   - [ ] 未跑 `git reset --hard`
   - [ ] 未删 `docker-compose.override.yml`
   - [ ] 未改代码 / .env / Docker / alembic
6. **下次预防建议**：在 `docs/DEPLOY.md §12.2` 加一段"服务器 commit 后立即 push"提示（如果你想让我做这个，写明"追加 §12.x"，我会另起切片 V5-8 处理）