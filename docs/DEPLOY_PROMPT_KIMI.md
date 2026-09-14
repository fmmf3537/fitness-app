# Kimi Code CLI 生产部署提示词（配合 docs/DEPLOY.md §12 使用）

> 用法：SSH 登录生产服务器后，启动 kimi code cli，把下面整段提示词粘贴进去。
> 执行前只需替换 3 个占位符：`<项目路径>`（服务器上仓库目录，如 `~/fitness-app`）、
> `<目标版本>`（commit hash / tag / `origin/main`）、`<你的域名>`。

---

```text
你是生产服务器上的部署工程师。任务：把 fitness-app 安全升级到最新版本。
硬性原则：不丢任何数据、不动卷、全程可回滚。任何一步失败立即停止并报告，不要自作主张修复后继续。

## 环境
- 项目路径：<项目路径>（docker compose 项目，5 个服务：postgres/backend/frontend/backup/caddy）
- 目标版本：<目标版本>
- 站点：https://<你的域名>
- 部署手册：仓库内 docs/DEPLOY.md（§12 是增量部署流程，请先阅读再动手）

## 绝对禁止（红线）
1. 禁止 `docker compose down -v`、禁止删除/重建任何 volume（pgdata / backups / garmin_tokens）
2. 禁止 `git push --force`、禁止 `git reset --hard` 到部署前的旧提交以外的位置
3. 禁止 `alembic downgrade` 除非你明确判断迁移失败且已在回滚流程中
4. 禁止 scale backend（内存调度器，必须单副本）
5. 任何命令报错（非零退出码）→ 立即停止，输出错误，等待我指示，不要重试绕过

## 第 0 步：记录回滚锚点（必做）
```bash
cd <项目路径>
git status --short --branch          # 工作区必须干净；有未推送本地 commit 先报告给我
git fetch origin
CURRENT=$(git rev-parse HEAD)        # 记录当前版本 = 代码回滚点
docker compose exec backend alembic current   # 记录当前迁移版本 = 数据库回滚点
echo "rollback: commit=$CURRENT alembic=<上一步输出>" | tee /tmp/rollback_anchor.txt
```
把 rollback_anchor.txt 内容原样展示给我。

## 第 1 步：部署前备份（必做，失败即中止）
```bash
docker compose exec backup /usr/local/bin/backup.sh        # 立即 pg_dump
docker compose exec backup ls -la /backups/                # 确认刚生成的 dump 存在且非 0 字节
docker compose cp backup:/backups ./backups_predeploy_$(date +%Y%m%d_%H%M)   # 拷出到宿主机留档
ls -la ./backups_predeploy_*                               # 再次确认文件在宿主机上
```
确认新备份存在再继续；不存在 → 中止。

## 第 2 步：确认变更范围（决定重建哪些服务）
```bash
git log --oneline $CURRENT..<目标版本>
git diff --name-only $CURRENT..<目标版本>
```
按 DEPLOY.md §12.1 判定：只改 frontend → 只重建 frontend；改 backend 或含 alembic 迁移 → 重建 backend（容器入口自动 alembic upgrade head）。把判定结果告诉我。

## 第 3 步：升级
```bash
git checkout <目标版本>  # 若目标是 origin/main 且工作区干净，可用 git merge --ff-only origin/main
docker compose up -d --build <按第2步判定的服务列表>
docker compose ps       # 5 个容器应全部 running（或按 override 配置）
```

## 第 4 步：部署后自检（全部通过才算成功）
```bash
curl -s http://localhost:8080/health                       # → ok（或按实际暴露端口）
docker compose exec backend alembic current                # 应为最新 head
docker compose exec backend alembic current | grep head    # 验证 == head
docker compose exec frontend ls -la /usr/share/nginx/html/assets/ | head -5   # 确认 bundle 是刚构建的（防 layer cache 旧 dist）
docker compose logs --tail=50 backend                      # 无 ERROR/Traceback
```
若 bundle 时间是旧的：按 DEPLOY.md §12.3 执行 `docker compose build --no-cache frontend && docker compose up -d --force-recreate frontend`。
最后执行 `bash scripts/preflight.sh --post`（若存在）。

## 第 5 步：报告
输出：升级前后 commit、alembic 版本、备份文件路径、自检结果、以及"回滚命令速查"（见下）。

## 回滚预案（仅在第 4 步失败且 15 分钟内无法定位时，经我确认后执行）
```bash
# A. 代码回滚
git checkout $(grep commit= /tmp/rollback_anchor.txt | cut -d= -f2)
docker compose up -d --build backend frontend

# B. 数据库回滚（仅当本次升级执行过 alembic 迁移）
#    优先 downgrade 到部署前记录的版本：
docker compose exec backend alembic downgrade <第0步记录的版本>
#    若 downgrade 报错/无 downgrade 实现 → 用第 1 步的 dump 恢复：
docker compose cp ./backups_predeploy_<时间戳>/fitness_<最新>.dump backup:/tmp/restore.dump
docker compose exec backup sh -c 'pg_restore --clean --if-exists -h postgres -U $PGUSER -d $PGDATABASE /tmp/restore.dump'
docker compose restart backend

# C. 回滚后验证：health + alembic current + 浏览器打开站点登录测试
```

现在开始。每一步完成后汇报结果，遇到任何 [FAIL]、非零退出码或日志 ERROR 立即停下。
```

---

## 给使用者（你）的提醒

- **服务器工作区不干净时先人工处理**：DEPLOY.md §12.7 记录过服务器产生未推送本地 commit 导致分叉的教训，提示词第 0 步会拦住这种情形。
- **手机端验收**：部署成功后手机浏览器/ APK 打开站点各看一遍新功能（DEPLOY.md §12.6 第 6 条）；看不到先清 App 数据，再走 §12.3 的 no-cache 重建。
- **数据库回滚只在"本次有迁移"时才需要**；纯前端升级的回滚只有 A 步。
- 若服务器与既有站点共存（80/443 被占），自检端口用 override 暴露的 `8080`（DEPLOY.md §4）。
