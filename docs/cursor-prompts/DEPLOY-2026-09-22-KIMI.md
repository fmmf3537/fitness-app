# Kimi Code CLI 生产部署提示词 — 2026-09-22（教练引用真实数据 + 移动端打磨，一次性执行版）

> 用法：SSH 登录生产服务器 → 启动 kimi code cli → 把下面 ```text 代码块整段粘贴进去。
> **一次性执行版**：CLI 自主跑完全部步骤，只在触发中止条件时停下，最后输出一份完整报告。

## 本次版本快照（供你核对）

- 服务器当前版本：`0abfa21`（代码等同 `fb39696`，Phase A 部署后状态）
- 目标版本：`origin/main` @ `5c2f89d`（2026-09-22 已推送 GitHub）
- 变更范围：3 个提交，72 文件（frontend + backend + docs）
  - `5e4e266` 响应式 UI 打磨、`0fb2568` 移动端 UI 与复盘分享修正、`5c2f89d` 教练回答引用实时训练数据
  - **本次含真实迁移**：`d9e0f1a2b3c4` 给 `coach_chat_message` 加可空列 `context_refs_json`（Text，存回答依据），有完整 downgrade
- 部署前本地已亲手回归：后端 1014 passed/6 skipped/覆盖率 91.67%≥85%；前端 424 passed
- 预期重建：**backend + frontend**；postgres/backup 不动
- 迁移后 alembic 应为 `d9e0f1a2b3c4 (head)`

---

```text
你是生产服务器上的部署工程师。任务：把 fitness-app 从 0abfa21 一次性升级到 origin/main（5c2f89d）。
硬性原则：不丢任何数据、不动卷、全程可回滚。
执行方式：**连续自主执行第 0~5 步，中间不要暂停等我确认**；只有触发下方【中止条件】才停下报告。

## 环境
- 项目路径：~/fitness-app（docker compose：postgres/backend/frontend/backup；caddy 不存在属正常——IP 直连模式）
- 目标版本：origin/main，应为 5c2f89d（或其后 docs-only 提交）
- 站点：http://118.24.143.172:8080
- 本次含 alembic 迁移：d9e0f1a2b3c4（coach_chat_message 加可空列，低风险，有 downgrade）
- 构建耗时长：任何 docker compose build 命令超时必须设 ≥3600s（上轮 60s 超时被杀的教训）

## 绝对禁止（红线）
1. 禁止 `docker compose down -v`、禁止删除/重建任何 volume
2. 禁止 `git push --force`；禁止 `git reset --hard` 到非 origin/main 的位置
3. 禁止手动执行 alembic downgrade（除非进入回滚预案且经判断必要）；容器入口的自动 upgrade 允许
4. 禁止 scale backend；禁止修改 .env / docker-compose.override.yml
5. 禁止清理 backups_predeploy_* 历史备份

## 中止条件（触发任一立即停下报告，不要自行修复）
- 任何命令非零退出码（构建超时被杀除外：该情形先核查容器 StartedAt 未变后以 3600s 超时重跑一次，重跑仍失败才中止）
- 第 2 步 diff 出现预期外路径（预期仅 frontend/、backend/app、backend/alembic/versions/d9e0f1a2b3c4_*、backend/tests/、docs/）
- 迁移后 alembic current ≠ d9e0f1a2b3c4
- /health 不返回 ok，或 backend 日志出现 ERROR/Traceback

## 第 0 步：回滚锚点
```bash
cd ~/fitness-app
git status --short --branch
git fetch origin
git log --oneline origin/main -1     # 记录（应为 5c2f89d 或 docs-only 后续）
CURRENT=$(git rev-parse HEAD)        # 应为 0abfa21；是 fb39696 或其他 docs-only 等价值也可接受，记录实际值
docker compose exec backend alembic current   # 应为 c8d9e0f1a2b3 (head)
echo "rollback: commit=$CURRENT alembic=c8d9e0f1a2b3" > /tmp/rollback_anchor.txt
cat /tmp/rollback_anchor.txt
```

## 第 1 步：部署前备份（失败即中止）
```bash
docker compose exec backup /usr/local/bin/backup.sh
docker compose exec backup ls -la /backups/      # 确认新 dump 存在且非 0 字节
docker compose cp backup:/backups ./backups_predeploy_$(date +%Y%m%d_%H%M)
ls -la ./backups_predeploy_*
```

## 第 2 步：变更范围核对
```bash
git diff --name-only $CURRENT..origin/main
```

## 第 3 步：升级（构建命令超时 ≥3600s）
```bash
git merge --ff-only origin/main
docker compose up -d --build backend frontend
docker compose ps                    # postgres/backup StartedAt 不应变化
```

## 第 4 步：自检
```bash
curl -s http://localhost:8080/health                       # → ok
docker compose exec backend alembic current                # 必须是 d9e0f1a2b3c4 (head)（本次有真迁移）
docker compose exec backend python -c "from app.db import SessionLocal; from sqlalchemy import inspect; cols=[c['name'] for c in inspect(SessionLocal().bind).get_columns('coach_chat_message')]; print('context_refs_json' in cols)"   # 必须 True
docker compose exec frontend ls -la /usr/share/nginx/html/assets/ | head -5   # bundle 必须是刚构建的
docker compose logs --tail=50 backend                      # 无 ERROR/Traceback
docker compose logs --tail=30 frontend                     # 无 ERROR
curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/api/match-candidates   # 401 属正常（鉴权拦截），500 触发中止
```
bundle 时间若是旧的：`docker compose build --no-cache frontend && docker compose up -d --force-recreate frontend` 后重跑自检。

## 第 5 步：输出一份完整报告
包含：升级前后 commit、alembic 前后版本、备份路径、自检全项结果、容器 StartedAt 对比、迁移列验证结果。
报告后停下，等我人工验收（重点：教练聊天是否引用真实训练数据、移动端 UI、复盘分享海报）。

## 回滚预案（仅我验收不通过或中止后我确认时执行）
```bash
# A. 代码 + 迁移回滚（本次迁移有完整 downgrade，优先走这条）
git checkout $(grep commit= /tmp/rollback_anchor.txt | cut -d' ' -f1 | cut -d= -f2)
docker compose exec backend alembic downgrade c8d9e0f1a2b3   # 在旧代码容器里执行
docker compose up -d --build backend frontend
curl -s http://localhost:8080/health
docker compose exec backend alembic current   # 应回到 c8d9e0f1a2b3 (head)

# B. 仅当 downgrade 报错时用 dump 恢复：
# docker compose cp ./backups_predeploy_<时间戳>/<最新>.dump backup:/tmp/restore.dump
# docker compose exec backup sh -c 'pg_restore --clean --if-exists -h postgres -U $PGUSER -d $PGDATABASE /tmp/restore.dump'
# docker compose restart backend

# C. 回滚后把 /tmp/rollback_anchor.txt 与相关日志贴给我
```

现在开始，连续执行到第 5 步报告为止。
```

---

## 给使用者（你）的提醒

- **本次迁移低风险**：仅给 `coach_chat_message` 加可空列，不动存量数据；回滚有 downgrade 实现，不需要动 dump。
- 自检里多了一条**列存在性验证**（`context_refs_json` 必须为 True），这是迁移真正生效的直接证据。
- 验收重点：教练聊天回答应能引用你的真实训练记录；手机端过一遍响应式打磨的页面；复盘分享海报功能。
- 服务器上 `backups_predeploy_*` 已积累 3 份，本次第 4 份；全部验收通过后可统一清理（需你明示）。
- 本提示词已入库 `docs/cursor-prompts/DEPLOY-2026-09-22-KIMI.md` 并推送 GitHub。
