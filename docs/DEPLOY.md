# DEPLOY —— 生产部署手册（V2-5）

> 从零到可访问的完整步骤。目标架构：`caddy(HTTPS) → frontend(nginx 静态+/api 反代) → backend(FastAPI+APScheduler) → postgres`，外加 `backup`（每日 pg_dump，保留 30 天）。
> 低配云服务器 2C4G 即可；全程密钥只经环境变量注入，不进镜像、不进 Git。

## 0. 前置条件

- 云服务器一台（Ubuntu 22.04+，2C4G），安全组放行 80/443；
- 域名一个，DNS A 记录指向服务器 IP（无域名可先用 `:80` 明文跑通内网，见 §6）；
- 服务器已安装 Docker 与 Compose 插件：
  ```bash
  curl -fsSL https://get.docker.com | bash
  docker compose version
  ```

## 1. 获取代码

```bash
git clone <repo-url> fitness-app && cd fitness-app
```

## 2. 配置环境变量

```bash
cp .env.production.example .env
# 生成两个强随机值（hex 而不是 base64——base64 可能含 / 字符，会把数据库连接串截断，
# 2026-08-10 腾讯云实测踩坑：POSTGRES_PASSWORD 含 / 导致迁移脚本认证失败）：
openssl rand -hex 24           # → POSTGRES_PASSWORD
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # → FERNET_KEY
# 若从旧 SQLite 库迁移数据（§8），FERNET_KEY 必须沿用旧 .env 中的值，
# 否则 settings 表中加密的 LLM Key 将无法解密
```

编辑 `.env`，必填：`SITE_ADDRESS`（域名）、`POSTGRES_PASSWORD`、`APP_PASSWORD`（登录口令，**强制**）、
`FERNET_KEY`、`XUNJI_API_KEY`、`XUNJI_BODY_API_KEY`、`GARMIN_EMAIL`、`GARMIN_PASSWORD`。
LLM Key（KIMI/DEEPSEEK/MINIMAX）与告警（SERVERCHAN/SMTP）可后续补，对应功能暂不可用而已。

> 注意：`GARMIN_DOMAIN` 必须保持 `garmin.cn`（中国区账号；全球区能登录但返回空数据）。

## 3. 部署前检查

```bash
bash scripts/preflight.sh
```
全部 `[OK]`（`[FAIL]` 必须为 0）再继续。检查项：docker、环境变量、80/443 端口、磁盘 ≥5G、compose 配置合法性。

## 4. 构建并启动

国内服务器构建极慢时（pip 下载几 kB/s）：把 `backend/Dockerfile` 的 pip 命令加
`-i https://mirrors.cloud.tencent.com/pypi/simple`（腾讯云内网镜像），并给 docker 配
`{"registry-mirrors":["https://mirror.ccs.tencentyun.com"]}`（snap 版 docker 配置文件在
`/var/snap/docker/current/config/daemon.json`，重启用 `sudo snap restart docker`）。

```bash
docker compose up -d --build
docker compose ps        # 5 个容器应全部 running
```

**与已有站点共存（80/443 被宿主机 nginx 占用时）**：跳过 caddy，用 override 暴露前端端口
并禁用 caddy 默认启动（2026-08-10 实测：宿主机已有招聘系统时的方案）：

```yaml
# docker-compose.override.yml
services:
  frontend:
    ports: ["8080:80"]      # 浏览器经 http://IP:8080 访问（防火墙需放行）
  caddy:
    profiles: ["caddy_optional"]   # 默认不再启动 caddy
```

backend 容器入口会自动执行 `alembic upgrade head`（PostgreSQL 迁移重放），无需手动建表。
首次访问域名时 Caddy 自动签发 Let's Encrypt 证书（约 1 分钟），随后 `https://<域名>` 打开登录页，输入 `APP_PASSWORD` 进入。

部署后复检：

```bash
bash scripts/preflight.sh --post   # 容器健康 + alembic current==head + HTTPS 可达
```

## 5. 佳明 token 首次登录（交互处理）

佳明 token 缓存在 `garmin_tokens` 卷（容器内 `/root/.garminconnect`），**只需首次登录一次**，
之后自动 resume 复用会话（同一进程重复登录会触发佳明 IP 级 429，切勿反复重启试探）。

首次启动后执行一次手动登录验证（GarminClient 需要数据库会话参数）：

```bash
docker compose exec backend python -c "
from app.db import SessionLocal
from app.adapters.garmin_adapter import GarminClient
GarminClient(SessionLocal()).login()
print('garmin login ok')
"
```

- 输出 `garmin login ok` → token 已写入卷，每日 22:47 定时同步会自动拉取；
- 若返回 401/429：确认 `.env` 中账号密码与 `GARMIN_DOMAIN=garmin.cn`，等 30 分钟再试（429 退避）；
- token 失效时应用会自动用缓存凭据重登一次，仍失败则走 V2-4 告警通道推送，并可用
  前端「FIT/TCX 导入」降级入口手动补数据。

## 6. 无域名/内网模式（可选）

`.env` 中 `SITE_ADDRESS=:80`，然后 `docker compose up -d --build`，
用 `http://<服务器IP>` 访问。**仅限可信内网**（明文 HTTP），公网务必用域名 + HTTPS。

## 7. 历史数据（可选）

部署完成后如需回填历史（训记 2023-02 起、佳明活动 2017 起），在前端「历史导入」页触发即可；
后端已内置 15s 限频与断点续传。导入期间禁止重启 backend（避免佳明重复登录）。

## 8. 从旧 SQLite 库迁移数据（可选）

若本机开发库（`backend/data/app.db`）已有数据要带到线上：

```bash
# 1) 把本机 backend/data/app.db 上传到服务器项目目录（scp app.db user@server:~/fitness-app/）
#    建议先用 SQLite 备份 API 做一致性快照再传：sqlite3 的 Connection.backup() 或 .backup 命令
# 2) 在服务器上把 PG 端口映射到宿主机——写入 docker-compose.override.yml（compose 每条命令
#    自动加载；勿用 -f - stdin 方式，后续不带该文件的 compose 命令会把映射收掉，实测踩坑）：
cat >> docker-compose.override.yml <<'EOF'
  postgres:
    ports: ["127.0.0.1:15432:5432"]
EOF
docker compose up -d postgres
sudo ss -tlnp | grep 15432   # 确认监听后再继续
#    注意用 15432 而非 5432：宿主机可能已有其他 PostgreSQL 占用 5432（实测踩坑）
# 3) 在服务器本地执行迁移脚本（幂等，可重复跑）：
python3 -m pip install --quiet --break-system-packages sqlalchemy psycopg2-binary   # Ubuntu 24 PEP 668
cd ~/fitness-app
export PGPW=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)
python3 scripts/migrate_sqlite_to_pg.py \
  --sqlite sqlite:///./backend/data/app.db \
  --pg "postgresql+psycopg2://fitness:${PGPW}@127.0.0.1:15432/fitness"
# 4) 完成后从 override 中删除 postgres 端口段并 docker compose up -d 恢复常态
```

脚本按主键幂等跳过，可重复运行；结束后自动重置自增序列。

## 9. 备份与恢复

- `backup` 容器每日 03:17 `pg_dump` 到 `backups` 卷，滚动保留 30 天（`BACKUP_RETENTION_DAYS` 可调）；
- 手动立即备份：`docker compose exec backup /usr/local/bin/backup.sh`；
- 取出备份文件：`docker compose cp backup:/backups ./backups_local`；
- 恢复：
  ```bash
  docker compose cp ./fitness_2026-08-10.dump backup:/tmp/restore.dump
  docker compose exec backup sh -c 'pg_restore --clean --if-exists -h postgres -U $PGUSER -d $PGDATABASE /tmp/restore.dump'
  ```
- 建议定期把 `backups` 卷文件异地拷贝一份。

## 10. 日常运维

| 操作 | 命令 |
|---|---|
| 看日志 | `docker compose logs -f backend` |
| 更新代码 | `git pull && docker compose up -d --build` |
| 手动迁移 | `docker compose exec backend alembic upgrade head` |
| 重启某服务 | `docker compose restart backend` |
| 进入数据库 | `docker compose exec postgres psql -U fitness` |

**禁止**：`docker compose up --scale backend=2`（内存 token + 内存调度器，必须单副本）。

## 11. 故障速查

| 症状 | 排查 |
|---|---|
| 域名打不开 | DNS 是否生效；`docker compose logs caddy` 看证书签发；安全组 80/443 |
| 登录一直 401 | `APP_PASSWORD` 是否与输入一致；backend 重启后旧 token 失效需重新登录 |
| backend 启动即退出 | `docker compose logs backend`：生产校验缺 `APP_PASSWORD/FERNET_KEY`，或迁移失败 |
| 佳明无数据 | `docker compose logs backend` 找 401/429；按 §5 重登；token 卷是否挂载 |
| 备份没生成 | `docker compose logs backup`；手动跑 `docker compose exec backup backup.sh` |

---

## 12. 切片流水线开发的增量部署（V5+）

切片流水线（V4-V5 验证过的 V5-1~V5-7 + 后续 V6+）的特征：**每周交付 1~2 个 commit，每个 commit 改 1~10 个文件**。部署应与 commit 同步滚动升级，避免积累 5+ 个 commit 再"大批部署"（中途问题难溯源）。

### 12.1 部署粒度判定

每个 commit 自带"改动文件清单"（Cursor 交付报告 §1）。按改动落在 backend / frontend 决定重建范围：

| Commit 类型 | 涉及表 / 迁移 | 涉及前端组件 | 重建范围 | 何时重建 |
|---|---|---|---|---|
| `feat(VN-x)` 改 backend services/api | ✓ alembic 迁移 | — | backend | 必跑 alembic 迁移 |
| `feat(VN-x)` 改 backend services/api | ✗ 无迁移 | — | backend | 仅镜像重启 |
| `feat(VN-x)` 改 frontend pages/components | — | ✓ | **仅 frontend**（不用动 backend） | 当次 |
| `fix(VN)` 改任意文件 | — | — | 视改动落点 | 同上 |

### 12.2 标准部署流程（切片后端有迁移）

```bash
cd /path/to/fitness-app
git pull origin main

# 1. 看 commit 范围，决定重建哪些服务
git log origin/main --oneline | head -5

# 2. 重建（按需）
docker compose up -d --build backend    # 含 alembic 迁移（容器内自动 alembic upgrade head）
docker compose up -d --build frontend   # 仅前端组件改动
# 或一次重建多个：
docker compose up -d --build backend frontend

# 3. 验证（防 layer cache 命中导致 dist 没更新）
docker compose exec frontend ls -la /usr/share/nginx/html/assets/ | head -5
curl -sI http://localhost:8080/ | head -3
curl -s http://localhost:8080/health   # → ok

# 4. 备份前先确认迁移成功（V5+ 已有 alembic roundtrip 测试 CI）
docker compose exec backend alembic current
# 应：c8d9e0f1a2b3 (head)  ← 最近 head

# 5. 如果看到前端新功能但手机还是旧版 → 清 APK 数据或重 build APK
```

### 12.3 前端 Layer Cache 故障排查

如果 `docker compose up -d --build frontend` 后浏览器仍显示旧版：

```bash
# 检查容器内 dist 的 Last-Modified
docker compose exec frontend ls -la /usr/share/nginx/html/assets/

# 对比服务器 bundle MD5 与本机 dist MD5
docker compose exec frontend md5sum /usr/share/nginx/html/assets/index-*.js
md5sum frontend/dist/assets/index-*.js  # 本机

# 如果不同 → layer cache 命中了旧 dist
docker compose build --no-cache frontend
docker compose up -d --force-recreate frontend
```

`--no-cache` 强制重跑所有 Dockerfile 步骤（包括 `npm run build`），耗时约 3-5 分钟。`--force-recreate` 删除旧容器 + 重建 volume。

### 12.4 移动端（Capacitor APK）部署

详见 [§0 / ANDROID.md](ANDROID.md)。要点：

- 本项目 `capacitor.config.ts` 配了 `server.url` 直连生产服务器 → 服务端 `frontend` 容器更新后，**手机无需重新打包 APK**（Capacitor WebView 每次启动从服务器拉最新 bundle）
- 手机 WebView 缓存导致新功能看不到时：清 app 数据（设置 → 应用 → 健身看板 → 存储 → 清除数据）
- 若 APK build 时嵌入的 `server.url` 是旧地址（例如 IP 变了、端口改了），必须重新 build APK：`npm run build && npx cap sync android && gradlew assembleRelease`

### 12.5 移动端导航（V5+ 必看）

**所有新增页面必须同时出现在 3 处**（这是 V5 期间发现的真坑，2026-09 修了 `fe9fb06` commit）：

| 位置 | 文件 | 作用 |
|---|---|---|
| `NAV_LINKS` | `frontend/src/components/Layout.jsx` | **桌面端**顶栏导航（`isMobile=false` 才渲染） |
| `TABS` | `frontend/src/components/BottomTabs.jsx` | **移动端**底部 Tab（`isMobile=true` 才渲染，固定 5-7 个主入口） |
| `SECONDARY_LINKS` | `frontend/src/components/Layout.jsx` | 移动端汉堡菜单（次级入口，如「复盘中心」「待确认队列」） |

**踩坑历史**：V5-5（教练须知）和 V5-6（跟教练聊聊）只改了 `NAV_LINKS`（桌面顶栏），没加 `TABS` 或 `SECONDARY_LINKS`。手机用户 `isMobile=true` → 顶部 nav 隐藏 → 底部 Tab 没有这两条 → 汉堡菜单也没有 → 看上去"新功能消失了"。**实际是提示词疏漏**。

提示词模板红线：每个 `feat(VN-x)` 前端切片必须显式列出 3 处修改：

```
红线：所有新增页面必须同时出现在 3 处（NAV_LINKS / TABS / SECONDARY_LINKS），
否则移动端用户看不到入口（已在 V5 期间踩坑，参考 commit fe9fb06）。
```

### 12.6 部署后自检 checklist

```bash
# 1. 健康检查
curl -s http://localhost:8080/health   # → {"status":"ok"}

# 2. 后端 alembic head
docker compose exec backend alembic current
# 应输出最新 head（V5+ 是 c8d9e0f1a2b3）

# 3. 前端 bundle 是最新
curl -sI http://localhost:8080/assets/index-*.js | grep Last-Modified
# 应是刚才 rebuild 时间（UTC）

# 4. 数据库新表已建（V5+）
docker compose exec backend python -c "
from app.db import SessionLocal
from sqlalchemy import inspect
s = SessionLocal()
insp = inspect(s.bind)
print(sorted(insp.get_table_names()))
" | tr ',' '\n' | grep -E 'coach_|workout_set_hr|body_metric'
# 应输出 coach_preference / coach_preference_draft / coach_memory / coach_chat_message / workout_set_hr

# 5. 生产 lint / type check 不必每次跑（CI 已覆盖）

# 6. 手机端测试（每次发版必做）
#    - 手机 Chrome 进 https://fitness.example.com → 顶栏 + 底部 Tab 都看到新功能
#    - APK 清 app 数据后重开 → 同样看到新功能
#    - 「桌面版网站」切换测试（验证 mobile/responsive 切换无 bug）
```
