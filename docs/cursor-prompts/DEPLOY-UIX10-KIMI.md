# Kimi Code CLI 生产部署提示词 — UIX-10 增量（复盘详情原型落地）

> 用法：SSH 登录生产服务器 → 启动 kimi code cli → 把下面 ```text 代码块整段粘贴进去。
> 本次为纯前端增量升级，流程与 DEPLOY-V7-KIMI.md 相同，锚点值已更新。

## 本次版本快照（供你核对，不需要替换）

- 服务器当前版本：`ff1e2f2`（UIX-09 部署后状态）
- 目标版本：`origin/main` @ `7d659c3`（2026-09-14 已推送 GitHub）
- 变更范围：`ff1e2f2..7d659c3` 共 1 个提交，**仅 frontend/ 7 个文件**
  - UIX-10：复盘详情按 06-report 原型重构（评分卡头 / h2 分卡 / 追问 CTA / 周月海报）
  - `backend/` 零改动、**无 alembic 迁移**
- 预期重建：**只重建 frontend**，其余容器 StartedAt 不应变化
- 预期数据库回滚：**不需要**

---

```text
你是生产服务器上的部署工程师。任务：把 fitness-app 从 ff1e2f2 安全升级到 origin/main (7d659c3，UIX-10 复盘详情原型)。
硬性原则：不丢任何数据、不动卷、全程可回滚。任何一步失败立即停止并报告，不要自作主张修复后继续。

## 环境
- 项目路径：~/fitness-app（docker compose 项目，运行中的容器：postgres/backend/frontend/backup；caddy 不存在属正常——IP 直连模式）
- 目标版本：origin/main，应为 7d659c3
- 站点：http://118.24.143.172:8080（frontend 容器 8080->80 直达）
- 上一轮的 /tmp/rollback_anchor.txt 已过期，本次重新记录

## 绝对禁止（红线）
1. 禁止 `docker compose down -v`、禁止删除/重建任何 volume
2. 禁止 `git push --force`；禁止 `git reset --hard` 到非 origin/main 的位置
3. 本次无 alembic 迁移：禁止执行任何 `alembic upgrade/downgrade`
4. 禁止 scale backend；禁止修改 .env / docker-compose.override.yml
5. 任何命令报错（非零退出码）→ 立即停止，输出错误，等待我指示

## 第 0 步：记录回滚锚点（必做）
```bash
cd ~/fitness-app
git status --short --branch          # 工作区必须干净
git fetch origin
git log --oneline origin/main -1     # 确认 == 7d659c3；不是就停下报告
CURRENT=$(git rev-parse HEAD)        # 应为 ff1e2f2；不是也停下报告
docker compose exec backend alembic current   # 应为 c8d9e0f1a2b3 (head)
echo "rollback: commit=$CURRENT" > /tmp/rollback_anchor.txt
cat /tmp/rollback_anchor.txt
```

## 第 1 步：部署前备份（必做，失败即中止）
```bash
docker compose exec backup /usr/local/bin/backup.sh
docker compose exec backup ls -la /backups/      # 确认新 dump 存在且非 0 字节
docker compose cp backup:/backups ./backups_predeploy_$(date +%Y%m%d_%H%M)
ls -la ./backups_predeploy_*                     # 确认落到宿主机
```

## 第 2 步：确认变更范围
```bash
git diff --name-only $CURRENT..origin/main
```
预期：仅 frontend/ 下 7 个文件。出现 backend/ 或 alembic/ 任何文件 → 立即停止报告。

## 第 3 步：升级（只重建 frontend）
```bash
git merge --ff-only origin/main      # 不能快进 → 停下报告
docker compose up -d --build frontend
docker compose ps                    # backend/postgres/backup 的 StartedAt 不应变化
```

## 第 4 步：部署后自检（全部通过才算成功）
```bash
curl -s http://localhost:8080/health                       # → ok
docker compose exec frontend ls -la /usr/share/nginx/html/assets/ | head -5   # bundle 必须是刚构建的
docker compose exec backend alembic current                # 必须仍为 c8d9e0f1a2b3 (head)
docker compose logs --tail=30 frontend                     # 无 ERROR
docker compose logs --tail=20 backend                      # 无新 ERROR/Traceback
```
若 bundle 时间是旧的（layer cache 命中）：
`docker compose build --no-cache frontend && docker compose up -d --force-recreate frontend`，然后重跑自检。

## 第 5 步：报告
输出：升级前后 commit、alembic 版本（应不变）、备份路径、自检结果、各容器 StartedAt 对比。
然后等我人工验收：http://118.24.143.172:8080 → 复盘中心 → 周复盘详情，重点看
评分卡头（分数+等级+周期）、正文按章节分卡、底部「就这份复盘追问教练」按钮、分享本周海报按钮。
验收通过前不要做任何清理（保留 backups_predeploy_* 和 /tmp/rollback_anchor.txt）。

## 回滚预案（仅第 4 步失败或我验收不通过时，经我确认后执行）
```bash
git checkout $(grep commit= /tmp/rollback_anchor.txt | cut -d= -f2)   # 回到 ff1e2f2
docker compose up -d --build frontend
curl -s http://localhost:8080/health
git log --oneline -1
# 数据库本次无迁移，用不到恢复；回滚后把日志贴给我
```

现在开始。每一步完成后汇报结果，遇到任何 [FAIL]、非零退出码、diff 与预期不符或日志 ERROR 立即停下。
```

---

## 给使用者（你）的提醒

- 手机端验收若看不到新布局，先清浏览器/App 缓存（上一轮已遇到过），再看 bundle 哈希是否变化。
- 上一轮的 `backups_predeploy_20260914_1646/` 如已验收通过，这次可以让 CLI 一并清理（需你明示）。
- 本提示词已入库 `docs/cursor-prompts/DEPLOY-UIX10-KIMI.md` 并推送 GitHub，服务器 `git fetch` 后可查看。
