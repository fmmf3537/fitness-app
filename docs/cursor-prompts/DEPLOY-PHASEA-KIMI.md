# Kimi Code CLI 生产部署提示词 — Phase A（待确认队列预览 + UI）

> 用法：SSH 登录生产服务器 → 启动 kimi code cli → 把下面 ```text 代码块整段粘贴进去。
> **本次与上两轮不同：后端有代码改动，backend 也要重建。** 无 alembic 迁移。

## 本次版本快照（供你核对，不需要替换）

- 服务器当前版本：`7d659c3`（UIX-10 部署后状态）
- 目标版本：`origin/main` @ `fb39696`（2026-09-15 已推送 GitHub）
- 变更范围：`7d659c3..fb39696`，**frontend + backend + docs**
  - backend：待确认队列新增只读合并预览接口 `GET /api/match-candidates/{id}/preview`（`match_candidates.py` + `services/fuse.py`），**纯新增，无 schema 变更、无 alembic 迁移**
  - frontend：Phase A UI（待确认队列预览相关组件/页面/ hooks）
  - 本地已亲手回归：后端 998 passed/6 skipped/覆盖率 92.35%≥85%；前端 413 passed 全量通过
- 预期重建：**backend + frontend 都重建**；postgres/backup 不动
- 预期数据库回滚：**不需要**（无迁移；容器入口会自动跑 `alembic upgrade head`，属 no-op，版本应保持 `c8d9e0f1a2b3 (head)`）

---

```text
你是生产服务器上的部署工程师。任务：把 fitness-app 从 7d659c3 安全升级到 origin/main (fb39696，Phase A)。
硬性原则：不丢任何数据、不动卷、全程可回滚。任何一步失败立即停止并报告，不要自作主张修复后继续。

## 环境
- 项目路径：~/fitness-app（docker compose 项目，运行中的容器：postgres/backend/frontend/backup；caddy 不存在属正常——IP 直连模式）
- 目标版本：origin/main，应为 fb39696（或其后 docs-only 提交）
- 站点：http://118.24.143.172:8080
- 本次后端有改动：backend 容器需要重建（容器入口自动 alembic upgrade head，本次为 no-op）

## 绝对禁止（红线）
1. 禁止 `docker compose down -v`、禁止删除/重建任何 volume
2. 禁止 `git push --force`；禁止 `git reset --hard` 到非 origin/main 的位置
3. 禁止手动执行任何 `alembic upgrade/downgrade`（容器入口的自动 upgrade 不算）
4. 禁止 scale backend；禁止修改 .env / docker-compose.override.yml
5. 任何命令报错（非零退出码）→ 立即停止，输出错误，等待我指示

## 第 0 步：记录回滚锚点（必做）
```bash
cd ~/fitness-app
git status --short --branch          # 工作区必须干净
git fetch origin
git log --oneline origin/main -1     # 确认 == fb39696 或其后 docs-only 提交；明显不符才停下报告
CURRENT=$(git rev-parse HEAD)        # 应为 7d659c3；不是也停下报告
docker compose exec backend alembic current   # 应为 c8d9e0f1a2b3 (head)，记录输出
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
预期：frontend/、backend/app/api/match_candidates.py、backend/app/services/fuse.py、backend/tests/、docs/。
出现 alembic 迁移文件或其他意外路径 → 立即停止报告。

## 第 3 步：升级（重建 backend + frontend）
```bash
git merge --ff-only origin/main      # 不能快进 → 停下报告
docker compose up -d --build backend frontend
docker compose ps                    # postgres/backup 的 StartedAt 不应变化
```

## 第 4 步：部署后自检（全部通过才算成功）
```bash
curl -s http://localhost:8080/health                       # → ok
docker compose exec backend alembic current                # 必须仍为 c8d9e0f1a2b3 (head)（no-op 验证）
docker compose exec frontend ls -la /usr/share/nginx/html/assets/ | head -5   # bundle 必须是刚构建的
docker compose logs --tail=50 backend                      # 无 ERROR/Traceback；能看到启动完成日志
docker compose logs --tail=30 frontend                     # 无 ERROR
# 新接口冒烟（未处理候选可能不存在，404/空列表属正常，500 属异常）：
curl -s http://localhost:8080/api/match-candidates | head -c 300
```
若 frontend bundle 时间是旧的（layer cache 命中）：
`docker compose build --no-cache frontend && docker compose up -d --force-recreate frontend`，然后重跑自检。
backend 若启动报错：贴出 `docker compose logs --tail=80 backend`，停下等我指示，不要自行修复。

## 第 5 步：报告
输出：升级前后 commit、alembic 版本（应不变）、备份路径、自检结果、各容器 StartedAt 对比。
然后等我人工验收：http://118.24.143.172:8080 → 待确认队列，重点看 Phase A 新 UI 与合并预览。
验收通过前不要做任何清理（保留 backups_predeploy_* 和 /tmp/rollback_anchor.txt）。

## 回滚预案（仅第 4 步失败或我验收不通过时，经我确认后执行）
```bash
git checkout $(grep commit= /tmp/rollback_anchor.txt | cut -d= -f2)   # 回到 7d659c3
docker compose up -d --build backend frontend
curl -s http://localhost:8080/health
docker compose exec backend alembic current   # 应仍为 c8d9e0f1a2b3 (head)
git log --oneline -1
# 数据库本次无迁移，用不到恢复；回滚后把日志贴给我
```

现在开始。每一步完成后汇报结果，遇到任何 [FAIL]、非零退出码、diff 与预期不符或日志 ERROR 立即停下。
```

---

## 给使用者（你）的提醒

- **本次首次涉及 backend 重建**：自检里 `alembic current` 必须保持 `c8d9e0f1a2b3 (head)`——如果变了，说明有意外迁移被执行，立即按回滚预案处理并报告。
- 新接口是**只读预览**，不写库；`/api/match-candidates` 返回空列表或候选 404 都属正常（取决于是否有待处理数据）。
- 手机端看不到新 UI 先清缓存（bundle 哈希验证方法见 DEPLOY.md §12.9 的 V7 踩坑记录）。
- 服务器上累积的 `backups_predeploy_*` 已有 2 份（V7、UIX-10），本次会再加 1 份；全部验收通过后可让 CLI 统一清理（需你明示）。
- 本提示词已入库 `docs/cursor-prompts/DEPLOY-PHASEA-KIMI.md` 并推送 GitHub，服务器 `git fetch` 后可查看。
