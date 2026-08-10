#!/usr/bin/env bash
# V2-5 部署前检查清单：端口 / 环境变量 / 迁移状态 / 磁盘。
# 用法（项目根目录，.env 已就位后）：
#   bash scripts/preflight.sh            # 部署前检查（不依赖容器运行）
#   bash scripts/preflight.sh --post     # 部署后检查（含容器健康与 alembic 迁移状态）
set -u
cd "$(dirname "$0")/.."

PASS=0; FAIL=0
ok()   { echo "  [OK]   $1"; PASS=$((PASS+1)); }
bad()  { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }
warn() { echo "  [WARN] $1"; }

echo "== 1. 依赖工具 =="
command -v docker >/dev/null 2>&1 && ok "docker 已安装 ($(docker --version | head -c 40))" || bad "docker 未安装"
if docker compose version >/dev/null 2>&1; then ok "docker compose 可用"; else bad "docker compose 不可用"; fi
docker info >/dev/null 2>&1 && ok "docker daemon 运行中" || bad "docker daemon 未运行"

echo "== 2. 环境变量（.env）=="
if [ -f .env ]; then
  ok ".env 存在"
  set -a; . ./.env; set +a
else
  bad ".env 不存在（cp .env.production.example .env 后填写）"
fi
for var in SITE_ADDRESS APP_PASSWORD FERNET_KEY POSTGRES_PASSWORD \
           XUNJI_API_KEY XUNJI_BODY_API_KEY GARMIN_EMAIL GARMIN_PASSWORD; do
  val="${!var:-}"
  if [ -n "$val" ]; then ok "$var 已配置"; else bad "$var 未配置"; fi
done
for var in KIMI_API_KEY DEEPSEEK_API_KEY MINIMAX_API_KEY SERVERCHAN_SENDKEY SMTP_HOST; do
  [ -n "${!var:-}" ] && ok "$var 已配置" || warn "$var 未配置（对应功能不可用，可后续补）"
done
if [ "${APP_ENV:-}" = "production" ]; then ok "APP_ENV=production"; else warn "APP_ENV 非 production（当前：${APP_ENV:-未设置}）"; fi
if [ "${GARMIN_DOMAIN:-garmin.cn}" = "garmin.cn" ]; then ok "GARMIN_DOMAIN=garmin.cn（中国区）"; else bad "GARMIN_DOMAIN=${GARMIN_DOMAIN}，中国区账号必须为 garmin.cn"; fi

echo "== 3. 端口占用（80/443 需空闲）=="
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3>&- 3<&-; return 0; } || return 1; }
for p in 80 443; do
  if port_busy "$p"; then
    if docker ps --format '{{.Ports}}' 2>/dev/null | grep -q ":$p->"; then
      ok "端口 $p 已被本项目 caddy 占用（重复部署正常）"
    else
      bad "端口 $p 被其他进程占用"
    fi
  else
    ok "端口 $p 空闲"
  fi
done

echo "== 4. 磁盘空间（/ 需 ≥ 5G 可用）=="
avail_kb=$(df -k / | awk 'NR==2 {print $4}')
if [ "${avail_kb:-0}" -ge 5242880 ]; then
  ok "磁盘可用 $((avail_kb/1024/1024))G"
else
  bad "磁盘可用不足 5G（当前 $((avail_kb/1024))M）"
fi

echo "== 5. 部署文件完整性 =="
for f in docker-compose.yml backend/Dockerfile backend/docker-entrypoint.sh \
         frontend/Dockerfile frontend/nginx.conf deploy/Caddyfile \
         deploy/backup/Dockerfile deploy/backup/backup.sh; do
  [ -f "$f" ] && ok "$f" || bad "$f 缺失"
done
docker compose config -q >/dev/null 2>&1 && ok "docker compose config 校验通过" || bad "docker compose config 校验失败（检查 .env 必填项）"

if [ "${1:-}" = "--post" ]; then
  echo "== 6. 部署后检查（容器健康 / 迁移状态 / HTTPS）=="
  for svc in postgres backend frontend backup caddy; do
    if docker compose ps --status running "$svc" 2>/dev/null | grep -q "$svc"; then
      ok "容器 $svc 运行中"
    else
      bad "容器 $svc 未运行"
    fi
  done
  # Alembic 迁移状态：current 必须等于 head
  current=$(docker compose exec -T backend alembic current 2>/dev/null | awk '{print $1}' | head -1)
  head_rev=$(docker compose exec -T backend alembic heads 2>/dev/null | awk '{print $1}' | head -1)
  if [ -n "$current" ] && [ -n "$head_rev" ] && [ "$current" = "$head_rev" ]; then
    ok "alembic 迁移已到 head（$current）"
  else
    bad "alembic 迁移未对齐（current=$current head=$head_rev），执行：docker compose exec backend alembic upgrade head"
  fi
  # 应用健康
  if docker compose exec -T frontend wget -qO- http://backend:8000/health 2>/dev/null | grep -q ok; then
    ok "backend /health 正常"
  else
    bad "backend /health 无响应"
  fi
  # HTTPS 外网可达
  if [ -n "${SITE_ADDRESS:-}" ] && [ "$SITE_ADDRESS" != ":80" ]; then
    if curl -fsS -o /dev/null --max-time 10 "https://${SITE_ADDRESS}/health"; then
      ok "https://${SITE_ADDRESS}/health 可达"
    else
      warn "https://${SITE_ADDRESS} 暂不可达（DNS 生效/证书签发可能需要几分钟）"
    fi
  fi
fi

echo
echo "结果：$PASS 通过，$FAIL 失败"
[ "$FAIL" -eq 0 ]
