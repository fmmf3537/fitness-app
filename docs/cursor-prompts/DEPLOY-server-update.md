# 服务器端部署更新 · opencode 一键提示词（DEPLOY-update）

> 用途：在**腾讯云 Ubuntu 生产服务器**上用 opencode 执行一次"生产版本更新"（`git pull` + 镜像重建 + 迁移重放 + 全套验证 + 可回滚）。
> 目标架构（DEPLOY.md §0）：`caddy → frontend(nginx) → backend(FastAPI+APScheduler) → postgres` + `backup(每日 pg_dump)`。
> 使用：在服务器项目目录（如 `~/fitness-app`）启动 opencode，把下方整段粘贴进会话触发。任一步 [FAIL] 必须停下报告，禁止带病前进。

---

## 0. 铁律（违反任意一条 = 立即中止并报告）

1. **永不修改 `.env` 里已有的任何值**。尤其 `FERNET_KEY`（加密主密钥，重生成 = 线上全部已存 LLM Key 永久解密失败）、`POSTGRES_PASSWORD`（改了 = 数据库连接断裂）、`APP_PASSWORD`、佳明/训记密钥。
2. **永不把 `.env` 内容、密钥、token 写入日志、回显、临时文件或改动过的文件**。全程可用 `/tmp/deploy_baseline.txt` 存放 .env 指纹，禁止存放明文。
3. **永不 `git push`**、永不 `git rebase`、禁止 `docker compose down -v`（删卷 = 数据丢失）、禁止 `--scale backend=2`。
4. **严禁删除或重建 `garmin_tokens` 卷**；部署后**禁止反复重启 backend / 手动触发佳明登录**（避免触发佳明 IP 级 429）。
5. 工作区出现任何编译器/DB 权限异常时先停下，把现象完整列出，由我确认后再继续。
6. 每个阶段完成必须贴出对应核对清单；任何阶段的输出与预期不符 → 停止并给方案，不要自作主张继续。

---

## 1. 只读侦察（不改任何东西，先摸清现状）

在项目目录执行以下命令并逐条报告结果：

```bash
pwd
# 记录当前提交为 PREV_COMMIT（后续回滚锚点）
git rev-parse HEAD
git status --short          # 工作区必须干净；有未提交改动 → 停在 §0.5
git symbolic-ref --short HEAD   # 必须是 main
docker compose ps --format 'table {{.Service}}\t{{.Status}}\t{{.Image}}'
sha256sum .env              # 记录为 ENV_FINGERPRINT_BEFORE，写入 /tmp/deploy_baseline.txt
docker compose exec -T postgres psql -U fitness -tc "select version_num from alembic_version" | tr -d ' \r'   # 记录为 REV_BEFORE
ls docker-compose.override.yml 2>/dev/null && echo "存在 override（保留，勿删，§4.2 复核）" || echo "无 override"
```

判定分支：
- 若 `docker compose ps` **没有任何本项目容器在运行** → 不是"更新"而是"首次/重建"场景，**立即报告**：需要走 DEPLOY.md §0~§6 全新部署流程，不要在无运行环境上继续本更新流程。
- 若容器已在跑 → 继续。

## 2. 安全快照（必须先做，一步都不得跳）

```bash
# 2.1 .env 双保险（放在 /tmp，绝不进仓库）
cp .env /tmp/env.__DATE__.bak

# 2.2 手动备份数据库（与每日备份形成双副本；备份物放仓库外，防仓库污染）
docker compose exec -T backup /usr/local/bin/backup.sh
mkdir -p ~/deploy-backups
docker compose cp backup:/backups ~/deploy-backups/
ls -la ~/deploy-backups/              # 必须能看到今天的 fitness_<日期>.dump → 记录为 DB_BACKUP
# 校验备份可读性（自定义格式可用 pg_restore --list 列出目录即视为有效）
ls ~/deploy-backups/fitness_*.dump | tail -1 | xargs -I{} docker compose cp - backup:/tmp/check.dump
docker compose exec -T backup pg_restore --list /tmp/check.dump >/dev/null 2>&1 && echo "备份校验 OK" || echo "备份校验失败 → 停止报告"

# 2.3 镜像快照（回滚兜底）
docker compose images --format 'table {{.Service}}\t{{.Repository}}\t{{.Tag}}\t{{.ID}}' | tee /tmp/deploy_images.txt
```

`DB_BACKUP` 与 `PREV_COMMIT` 必须记录在最终报告中。

## 3. 拉取代码（fast-forward 严格模式）

```bash
git fetch origin
git log --oneline origin/main ^HEAD        # 只读查看增量，逐条向主人确认是否符合"更新预期"
git pull --ff-only origin main
git rev-parse HEAD                          # 记录为 NEW_COMMIT
git status --short                          # 应为空
```

- `--ff-only` 失败（历史分叉）→ 停止：说明仓库在服务器上有未同步的本地历史，需主人介入。
- pull 不可触发任何 merge/rebase。

## 4. 静态校验

### 4.1 前置检查
```bash
bash scripts/preflight.sh                    # 全 [OK]、[FAIL]=0 才继续
df -h /                                     # 确认磁盘充足（构建需要 ≥2G 余量；不足→报告）
```

### 4.2 override 复核（若有）
若存在 `docker-compose.override.yml`（历史场景：宿主机已有站点占 80/443，caddy 走 profile / postgres 端口映射用于数据迁移），
**原样保留**，只核对它仍为合理配置，不修改、不删除。

### 4.3 构建设缓存提速（国内服务器）
按 DEPLOY.md §4：backend pip 若极慢，确认 `backend/Dockerfile` 中 pip 是否已加腾讯云内网镜像
`-i https://mirrors.cloud.tencent.com/pypi/simple`；docker 是否配了 registry-mirrors。**仅在确认缺失且主人同意时才改这几行**，改后属代码变更需一并走本流程验证。

## 5. 构建与发布（短停机，可接受）

```bash
docker compose up -d --build backend frontend     # 只重建有代码变更的服务，postgres/backup/caddy 不动
docker compose up -d                              # 补齐因健康依赖未起的其余服务
docker compose ps --format 'table {{.Service}}\t{{.Status}}\t{{.Image}}'
```

后端日志验证（entrypoint 会先自动 `alembic upgrade head` 再起 uvicorn）：

```bash
docker compose logs -T --tail=300 backend | grep -E 'entrypoint|alembic|error|Error|Traceback|shutdown|startup'
```

- **本轮迁移说明**：新增迁移 `b7c8d9e0f1a2_workout_set_hr_table`（新建 `workout_set_hr` 表，**纯新增、无破坏、downgrade 可逆**），由 entrypoint 自动执行，无需手动建表。
- 若日志出现异常：停在本阶段，执行 §8 回滚。
- 部署窗口若恰好撞上调度任务（每小时 :11 health_check、22:47 同步）无需处理：backend 重建期间调度不执行，启动后自行进入正常节奏。

## 6. 部署后全套验证

```bash
bash scripts/preflight.sh --post                  # 5 容器 running + alembic current==head + /health + HTTPS
curl -fsS --max-time 15 https://$(grep '^SITE_ADDRESS=' .env | cut -d= -f2-)/health   # 外网可达
curl -fsS -o /dev/null -w '%{http_code}\n' https://$(grep '^SITE_ADDRESS=' .env | cut -d= -f2-)/   # 登录页 200
docker compose exec -T postgres psql -U fitness -tc "select version_num from alembic_version" | tr -d ' \r'   # 应 == REV_BEFORE 的后继或 head
docker compose logs -T --tail=80 backend | grep -iE 'error|traceback' || echo "backend 日志无异常"
sha256sum .env                                     # 必须 == ENV_FINGERPRINT_BEFORE（.env 未被动过）
```

判定：`preflight --post` 全 [OK] / `/health` 返回 ok / 登录页 200 / 指纹一致 → 部署成功，进入收尾。
不满足任一 → 走 §8 回滚。

## 7. 部署后观察（可选，交给主人）

- 不主动反复重启；可提示主人：下一次 daily_sync（22:47）后查看 `docker compose logs backend` 中 `daily_sync` 是否 success，以及 job_run 表（`select job_name,status from job_run order by id desc limit 5`）。

## 8. 回滚预案（触发即执行）

触发条件：§5 日志异常 / §6 任一 [FAIL] / 打开页面报错。

```bash
# 8.1 打回代码（若证实是新版代码导致）
git reset --hard <PREV_COMMIT>
docker compose up -d --build backend frontend

# 8.2 打回数据库（若迁移损坏/污染数据；用 §2 的手动备份，重复执行安全）
docker compose cp ~/deploy-backups/<DB_BACKUP> backup:/tmp/restore.dump
docker compose exec -T backup sh -c 'pg_restore --clean --if-exists -h postgres -U "$PGUSER" -d "$PGDATABASE" /tmp/restore.dump'

# 8.3 还原 .env（任何情况下 .env 指纹对不上才需要）
cp /tmp/env.__DATE__.bak .env
```

回滚后必须重跑 `bash scripts/preflight.sh --post` 直到全绿，并在报告中记录"已回滚 + 原因"。
> 8.2 使用 `pg_restore --clean --if-exists`，对当前库先删后重建再灌备份——若主机上无手动备份可用，绝不允许仅依赖每日备份且不做校验就开工。

## 9. 结果报告（必须交付）

按此模板贴出：

| 项 | 值 |
|---|---|
| PREV_COMMIT → NEW_COMMIT |  |
| 迁移 | 新增 `b7c8d9e0f1a2` 已重放 / REV_BEFORE→REV_AFTER |
| 手动备份 | `~/deploy-backups/<DB_BACKUP>`（pg_restore --list 校验通过） |
| preflight --post | X 通过 / Y 失败 |
| /health（外网） |  |
| 登录页 HTTP |  |
| backend 日志 | 有无 error/traceback |
| .env 指纹 | 与部署前一致？是/否 |
| 是否触发回滚 | 否 / 是（原因） |
| 观察建议 | daily_sync 明日 22:47 复检 |

**铁律再次强调：所有命令只读不改的环节不要跳；任何异常不要自己绕过；`.env` 一个字都不许动。**