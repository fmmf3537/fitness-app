# 部署提示词 — 健身看板 V6（含完整回滚）

> 适用工具：Kimi Code / OpenCode / Cursor Agent / 任一 AI Coding CLI
> 使用方式：将本提示词完整粘贴给 AI 工具，让它执行每一步

---

## 部署目标

- 仓库：D:\kimi\fitness-app（本地）→ 部署到服务器 `/opt/fitness-app/`（路径以服务器实际为准）
- 分支：`main`，最新 commit：`d43a5a8`（UIX-09 暗色模式）
- 内容：后端 FastAPI + 前端 React/Vite 构建物
- 要求：**不动数据、不动 .env、不动数据库**

---

## 部署前准备（必须按顺序执行）

### 第 0 步：确认服务器环境

在服务器上执行，截图或复制输出给我看：

```bash
# 1. 确认目录结构
ls /opt/fitness-app/
# 预期：backend/  frontend/  docker-compose.yml  .env 等文件

# 2. 确认正在运行的服务
docker ps
# 预期：backend（FastAPI/uvicorn）+ frontend（可选，静态文件由 nginx serve）

# 3. 确认数据库没有被误删
psql --version 2>/dev/null || echo "No psql"
# 如果用 Docker：docker exec <container> psql --version

# 4. 确认 .env 存在且没被动过
cat /opt/fitness-app/.env | head -5
# 预期：DATABASE_URL=... 等配置，勿输出敏感值

# 5. 确认 git 分支和最新 commit
cd /opt/fitness-app && git log --oneline -3
# 预期：d43a5a8 在内
```

### 第 1 步：服务器全量备份（在部署前必须完成）

```bash
cd /opt/fitness-app

# 备份数据库（必须！用 --data-only 防止结构被覆盖）
docker exec <your-postgres-container> pg_dump -U <user> -d <dbname> --data-only > /opt/backup/fitness_db_$(date +%Y%m%d_%H%M%S).sql
echo "数据库备份完成"

# 备份 .env 和配置文件
cp /opt/fitness-app/.env /opt/backup/.env.$(date +%Y%m%d)
cp /opt/fitness-app/backend/llm_config.json /opt/backup/llm_config.json.$(date +%Y%m%d) 2>/dev/null

# 备份当前运行的代码
cp -r /opt/fitness-app/backend /opt/backup/backend.$(date +%Y%m%d_%H%M%S)

# 验证备份存在
ls -lh /opt/backup/fitness_db_*.sql | tail -3
echo "备份验证 OK"
```

> ⚠️ 如果没有 Docker 数据库，用 `python -c "from backend.database import engine; print(engine.url)"` 找到数据库连接方式后备份。

### 第 2 步：在本地生成部署包

在**本地机器**执行（不要在服务器上 git pull，防止版本漂移）：

```bash
cd D:\kimi\fitness-app

# 确认没有未提交的修改
git status --short
# 预期：仅有 docs/ 或其他无关文件

# 确认最新 commit 是 d43a5a8
git log --oneline -3
# 预期：
# d43a5a8 feat(frontend): UIX-09 暗色模式
# af62f7a feat(frontend): UIX-08 图表层打磨A
# 4dac2c7 refactor(frontend): UIX-07 呈现收敛包

# 确认前端能构建
cd frontend && npm run build
# 预期：dist/ 目录生成，build 成功

# 打包（排除 node_modules/.git/测试文件等）
cd ..
tar -czf fitness_app_V6.tar.gz \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='frontend/dist' \
  --exclude='logs' \
  --exclude='*.log' \
  --exclude='.env*' \
  backend/ frontend/ pnpm-workspace.yaml docker-compose.yml docker-compose.prod.yml 2>/dev/null || \
  zip -r fitness_app_V6.zip backend/ frontend/ pnpm-workspace.yaml docker-compose.yml docker-compose.prod.yml \
    -x "*/node_modules/*" -x "*/.git/*" -x "*/__pycache__/*" -x "*/.env*"

echo "打包完成"
```

---

## 部署执行（服务器端）

### 第 3 步：上传部署包到服务器

```bash
# 方法 A：如果本地和服务器之间可以直接传文件
scp D:\kimi\fitness-app\fitness_app_V6.tar.gz user@your-server:/opt/
# 方法 B：如果 AI 工具在服务器上直接运行，直接 cd 到本地目录打包后复制

# 验证
ls -lh /opt/fitness_app_V6.tar.gz
```

### 第 4 步：停止当前服务（不停数据库）

```bash
cd /opt/fitness-app

# 方法 A：docker-compose 部署
docker-compose down
# 不加 -v（-v 会删数据！）

# 方法 B：systemd 管理
sudo systemctl stop fitness-backend
sudo systemctl stop fitness-frontend  # 如果有

# 方法 C：直接杀进程
pkill -f "uvicorn"  # 停止后端
pkill -f "vite"  # 停止前端热更新（如果前端不是纯静态）
```

### 第 5 步：解压部署

```bash
cd /opt/
tar -xzf fitness_app_V6.tar.gz
# 检查解压出来的目录结构
ls fitness-app/
# 预期：backend/  frontend/  pnpm-workspace.yaml  docker-compose.yml
```

### 第 6 步：恢复 .env（不改动服务器现有配置）

```bash
# 服务器 .env 已经存在于 /opt/fitness-app/.env，不覆盖它
# 但要确认 docker-compose.yml 里引用了正确的 .env 路径
cat /opt/fitness-app/docker-compose.yml | grep -i env
# 预期：env_file 或 environment 相关配置存在

# 如果 docker-compose.yml 里有默认 .env.sample，创建它但不覆盖真实 .env
ls /opt/fitness-app/.env || echo "警告：.env 不存在！"
```

### 第 7 步：重新构建并启动（数据库不动）

```bash
cd /opt/fitness-app

# 方法 A：docker-compose（推荐）
docker-compose build backend
docker-compose up -d backend
# 不跑 frontend（nginx 直接 serve 静态文件）

# 方法 B：systemd
sudo systemctl start fitness-backend

# 验证后端启动
curl -s http://localhost:8000/api/health || curl -s http://localhost:8000/
# 预期：返回 200 或 JSON 健康检查响应

# 查看日志确认没有报错
docker logs fitness-app_backend_1 --tail 20
# 或
journalctl -u fitness-backend --no-pager -n 20
```

### 第 8 步：构建前端静态文件（nginx serve）

```bash
cd /opt/fitness-app/frontend

# 安装依赖（如果 node_modules 没有被打包）
npm install
# 或
pnpm install

# 构建生产文件
npm run build
# 预期：dist/ 目录生成

# 把 dist 复制到 nginx 静态目录
sudo cp -r dist/* /var/www/fitness-app/
# 或者按服务器实际的 nginx root 路径
```

---

## 验证（部署完成后必须执行）

### 第 9 步：功能验证

```bash
# 1. 后端 API 健康检查
curl -s http://localhost:8000/api/health | python3 -m json.tool

# 2. 登录流程
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"test"}' | python3 -m json.tool
# 预期：返回 token

# 3. 前端页面可访问
curl -s -o /dev/null -w "%{http_code}" http://localhost/
# 预期：200

# 4. 日历页（核心页面之一）
curl -s -o /dev/null -w "%{http_code}" http://localhost/calendar
# 或实际路由

# 5. 检查数据库数据完整性
docker exec <postgres-container> psql -U <user> -d <dbname> -c "SELECT COUNT(*) FROM workouts;"
# 预期：数量 > 0（数据未丢失）
```

---

## 回滚方案（如果部署后出问题）

### 回滚到部署前状态

```bash
cd /opt/fitness-app

# 步骤 1：停止当前版本
docker-compose down  # 或 systemctl stop

# 步骤 2：恢复数据库（如果需要）
docker exec -i <postgres-container> psql -U <user> -d <dbname> < /opt/backup/fitness_db_<日期>.sql
echo "数据库已恢复"

# 步骤 3：恢复代码
# 找到上一个备份目录
ls -d /opt/backup/backend.* | sort | tail -1
# 例如：/opt/backup/backend.20260914_120000

cp -r /opt/backup/backend.20260914_120000/* /opt/fitness-app/backend/

# 步骤 4：重启服务
docker-compose up -d backend
# 或
sudo systemctl start fitness-backend

# 步骤 5：验证回滚成功
curl -s http://localhost:8000/api/health
git -C /opt/fitness-app log --oneline -3
# 确认 commit 回到了部署前的版本

echo "回滚完成"
```

### Git 回滚（如果代码层面需要回退）

```bash
cd /opt/fitness-app

# 确认当前 commit
git log --oneline -3
# d43a5a8（要回滚的版本）

# 回滚到上一个稳定版本（af62f7a）
git revert --no-commit d43a5a8
git commit -m "revert: rollback UIX-09 dark mode deployment"

# 如果 revert 有冲突且无法快速解决，可以直接强制 checkout
git checkout af62f7a -- backend/ frontend/
git commit -m "revert: reset to pre-UIX-09 (af62f7a)"

# 重启服务
docker-compose restart backend
```

---

## 快速检查清单（部署完成后复制粘贴执行）

```bash
echo "=== 部署检查清单 ==="
echo "1. 数据库记录数:"
docker exec <postgres> psql -U <user> -d <db> -c "SELECT COUNT(*) FROM workouts;" 2>/dev/null || echo "无法查询"
echo "2. 后端健康:"
curl -s http://localhost:8000/api/health && echo ""
echo "3. 前端状态码:"
curl -s -o /dev/null -w "%{http_code}" http://localhost/ && echo ""
echo "4. 最新 commit:"
git -C /opt/fitness-app log --oneline -1
echo "5. 后端日志（最近 5 行）:"
docker logs fitness-app_backend_1 --tail 5 2>/dev/null || echo "无法获取"
echo "=== 检查完成 ==="
```

---

## 重要红线（任何 AI 部署工具都必须遵守）

| 禁止操作 | 原因 |
|---------|------|
| ❌ 禁止执行 `docker-compose down -v` 或任何带 `-v` 的清理命令 | 会删除数据库数据 |
| ❌ 禁止修改 `.env` 或 `.env.*` 文件 | 服务器配置可能与本地不同 |
| ❌ 禁止执行 `DROP TABLE` 或 `TRUNCATE` | 数据会被清空 |
| ❌ 禁止执行 `git push --force` | 会覆盖远程历史 |
| ❌ 禁止删除 `/opt/backup/` 目录 | 备份是回滚的唯一保障 |
| ✅ 必须先备份再部署 | 备份永远在部署之前 |
| ✅ 数据库操作只做 SELECT/INSERT/UPDATE | 禁止 DDL 变更 |
| ✅ 部署完成后立即验证功能 | 早发现早回滚 |

---

## 交付给 AI 工具的部署指令模板

将以下内容完整复制给 Kimi Code / OpenCode：

```
请帮我执行以下部署任务：

1. 连接到服务器 /opt/fitness-app/
2. 执行第 0 步环境确认，截图给我看输出
3. 执行第 1 步全量备份，确认备份文件生成
4. 在本地（D:\kimi\fitness-app）执行第 2 步打包
5. 上传打包文件到服务器 /opt/
6. 执行第 4 步停止服务（不要停数据库！）
7. 执行第 5 步解压部署包
8. 执行第 7 步构建并启动后端
9. 执行第 8-9 步验证功能
10. 验证通过后报告完成

如果任何步骤出现错误（包括 HTTP 500、数据库连接失败、前端白屏），
立即停止并执行回滚方案（第 10 步），
回滚后重新截图给我，我来评估是否继续。
```
