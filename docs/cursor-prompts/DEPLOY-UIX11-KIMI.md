# Kimi Code CLI 生产部署提示词 — UIX-11（移动端 UI/UX 重设计）

> 用法：SSH 登录生产服务器 → 启动 kimi code cli → 把下面 ```text 代码块整段粘贴进去。
> 执行前只需替换 2 个占位符：`<项目路径>` 和 `<服务器IP>`。
> 目标版本已锁定：`origin/main` @ `872a341`（2026-09-22 已推送 GitHub）。
>
> **`<项目路径>` 填法**：服务器上仓库所在的本地目录（如 `/opt/fitness-app` 或 `~/fitness-app`），
> 不是 GitHub 网址——CLI 会在该目录里执行 `git` / `docker compose` 命令。
>
> **`<服务器IP>` 填法**：仅用于标识站点访问入口，所有命令实际走 localhost/容器网络，不依赖域名解析。
> 无域名 IP 访问（DEPLOY.md §6，`SITE_ADDRESS=:80`）就填 `http://1.2.3.4`；
> 若 Caddy 监听非 80 端口则带端口，如 `http://1.2.3.4:8080`；有域名则填 `https://fitness.example.com`。

## 本次版本快照（供你核对，不需要替换）

- 目标 commit：`872a341`
- 变更范围：`e7fbd83..872a341` 共 1 个提交，**纯前端 + 文档**
  - UIX-11：设计令牌 / 基础组件（Card/Button/PillGroup/Icon/IconChip）/ PageHeader 渐变页头 / 8 页面改造 / 图表皮肤 / 设置页 V1
  - `backend/` 零改动、**无 alembic 迁移**、无 scripts/ 变更
- 预期重建：**只重建 frontend**。backend / postgres / backup / caddy 都不该动。
- 预期数据库回滚：**不需要**（无迁移），但备份仍必做。

---

```text
你是生产服务器上的部署工程师。任务：把 fitness-app 安全升级到 origin/main (872a341)。
硬性原则：不丢任何数据、不动卷、全程可回滚。任何一步失败立即停止并报告，不要自作主张修复后继续。

## 环境
- 项目路径：<项目路径>（docker compose 项目，5 个服务：postgres/backend/frontend/backup/caddy）
- 目标版本：origin/main，应为 872a341
- 站点：<服务器IP>（无域名 IP 访问模式，DEPLOY.md §6；仅作验收入口标识，命令全部走 localhost）
- 部署手册：仓库内 docs/DEPLOY.md（§12 是增量部署流程，先读 §12.1/§12.3/§12.6 再动手）

## 绝对禁止（红线）
1. 禁止 `docker compose down -v`、禁止删除/重建任何 volume（pgdata / backups / garmin_tokens）
2. 禁止 `git push --force`；禁止 `git reset --hard` 到非 origin/main 的位置
3. 本次升级无 alembic 迁移：禁止执行任何 `alembic upgrade/downgrade` 命令
4. 禁止 scale backend（内存调度器，必须单副本）
5. 禁止修改 .env / docker-compose.override.yml / Caddyfile
6. 任何命令报错（非零退出码）→ 立即停止，输出错误，等待我指示，不要重试绕过

## 第 0 步：记录回滚锚点（必做）
```bash
cd <项目路径>
git status --short --branch          # 工作区必须干净；有未推送本地 commit 先报告给我（DEPLOY.md §12.7 教训）
git fetch origin
git log --oneline origin/main -1     # 确认 == 872a341；不是就停下报告
CURRENT=$(git rev-parse HEAD)        # 代码回滚点
docker compose exec backend alembic current   # 数据库回滚锚点（本次不应变化）
echo "rollback: commit=$CURRENT" | tee /tmp/rollback_anchor.txt
```
把 rollback_anchor.txt 内容和 alembic current 输出原样展示给我。

## 第 1 步：部署前备份（必做，失败即中止）
```bash
docker compose exec backup /usr/local/bin/backup.sh        # 立即 pg_dump
docker compose exec backup ls -la /backups/                # 确认刚生成的 dump 存在且非 0 字节
docker compose cp backup:/backups ./backups_predeploy_$(date +%Y%m%d_%H%M)
ls -la ./backups_predeploy_*                               # 再次确认文件落到宿主机
```
确认新备份存在再继续；不存在 → 中止。

## 第 2 步：确认变更范围
```bash
git diff --name-only $CURRENT..origin/main
```
预期：只有 frontend/ 和 docs/ 下的文件。如果 diff 里出现 backend/、alembic/ 或根目录配置文件 → 立即停止并报告（与版本快照不符，可能拉错分支）。

## 第 3 步：升级（只重建 frontend）
```bash
git merge --ff-only origin/main      # 工作区干净时必须能快进；不能快进 → 停下报告
docker compose up -d --build frontend
docker compose ps                    # 5 个容器全部 running；backend 的 StartedAt 不应变化
```

## 第 4 步：部署后自检（全部通过才算成功）
```bash
curl -s http://localhost:8080/health                       # → ok（或按 override 实际端口）
docker compose exec frontend ls -la /usr/share/nginx/html/assets/ | head -5   # bundle 必须是刚构建的时间
docker compose exec backend alembic current                # 必须与第 0 步记录完全一致（本次无迁移）
docker compose logs --tail=50 frontend                     # 无 ERROR
docker compose logs --tail=20 backend                      # 无新 ERROR/Traceback
```
若 bundle 时间是旧的（layer cache 命中旧 dist，DEPLOY.md §12.3）：
`docker compose build --no-cache frontend && docker compose up -d --force-recreate frontend`，然后重跑自检。
若存在 scripts/preflight.sh，执行 `bash scripts/preflight.sh --post`。

## 第 5 步：报告
输出：升级前后 commit、alembic 版本（应不变）、备份文件路径、自检结果、容器 StartedAt 对比。
然后等我做浏览器/手机端人工验收（UIX-11 渐变页头 + 设置页 V1 是重点），验收通过前不要做任何清理。

## 回滚预案（仅在第 4 步失败或我验收不通过时，经我确认后执行）
```bash
# A. 代码回滚（纯前端升级只需要这一步）
git checkout $(grep commit= /tmp/rollback_anchor.txt | cut -d= -f2)
docker compose up -d --build frontend
curl -s http://localhost:8080/health
git log --oneline -1   # 确认回到部署前 commit

# B. 数据库：本次无迁移，预期用不到。
#    仅当第 2 步 diff 意外包含迁移且已执行过时，才在我确认后：
#    docker compose cp ./backups_predeploy_<时间戳>/<最新>.dump backup:/tmp/restore.dump
#    docker compose exec backup sh -c 'pg_restore --clean --if-exists -h postgres -U $PGUSER -d $PGDATABASE /tmp/restore.dump'
#    docker compose restart backend

# C. 回滚后把 /tmp/rollback_anchor.txt、相关日志贴给我
```

现在开始。每一步完成后汇报结果，遇到任何 [FAIL]、非零退出码、diff 与预期不符或日志 ERROR 立即停下。
```

---

## 给使用者（你）的提醒

- **本次是纯前端升级**：backend 容器不该重启、数据库不该有任何变化。如果 CLI 报告 backend 被重建或 alembic 版本变了，说明有意外，立即让它停。
- **手机端验收重点**：渐变品牌页头（8 个页面）/ 底部 5Tab 第 5 项改为「设置」/ 设置页 V1（无身份大卡，顶部 3 个数据状态 chip）/ 图表紫系皮肤。手机若看不到新 UI，先清 App/浏览器缓存，再走 §12.3 的 no-cache 重建。
- **备份文件**会留在服务器 `./backups_predeploy_<时间戳>/`，验收通过后再决定保留或清理。
- 本提示词已入库 `docs/cursor-prompts/DEPLOY-UIX11-KIMI.md` 并推送到 GitHub，服务器 `git fetch` 后也能直接查看。
