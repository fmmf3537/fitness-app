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

# Garmin Plan Sync：未设置视为默认 0；开关为 0 不失败；不打印凭据/token
_gps_enabled="${GARMIN_PLAN_SYNC_ENABLED:-0}"
if [ "$_gps_enabled" = "0" ] || [ "$_gps_enabled" = "1" ]; then
  ok "GARMIN_PLAN_SYNC_ENABLED=${_gps_enabled}（未设置视为默认 0；0 为安全默认）"
else
  bad "GARMIN_PLAN_SYNC_ENABLED 必须为 0 或 1（当前：${_gps_enabled}）"
fi
_gps_stale="${GARMIN_PLAN_SYNC_STALE_SECONDS:-900}"
if [[ "$_gps_stale" =~ ^[1-9][0-9]*$ ]]; then
  ok "GARMIN_PLAN_SYNC_STALE_SECONDS=${_gps_stale}（正整数）"
else
  bad "GARMIN_PLAN_SYNC_STALE_SECONDS 必须为正整数（当前：${_gps_stale}）"
fi
# 若显式设置 tokenstore，必须是容器内绝对路径（不以 ~ 或相对路径开头）
if [ -n "${GARMIN_WORKOUT_TOKENSTORE:-}" ]; then
  case "${GARMIN_WORKOUT_TOKENSTORE}" in
    /*) ok "GARMIN_WORKOUT_TOKENSTORE 为绝对容器路径" ;;
    *) bad "GARMIN_WORKOUT_TOKENSTORE 必须是绝对容器路径（当前非绝对）" ;;
  esac
else
  ok "GARMIN_WORKOUT_TOKENSTORE 未显式设置（Compose 默认 /var/lib/fitness/garmin-workout/tokens）"
fi

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

  echo "== 7. Garmin Plan Sync 运行时（Python / 库 / 卷 / 单副本 / 时区）=="
  # 不 dump 环境、不读取 token 文件内容；仅检查键是否存在与路径元数据
  py_ver=$(docker compose exec -T backend python -c 'import sys; print("%d.%d"%sys.version_info[:2])' 2>/dev/null || true)
  if [ -n "$py_ver" ]; then
    major=${py_ver%%.*}
    minor=${py_ver#*.}
    if [ "$major" -gt 3 ] 2>/dev/null || { [ "$major" -eq 3 ] && [ "$minor" -ge 12 ]; }; then
      ok "backend Python ${py_ver}（>=3.12）"
    else
      bad "backend Python ${py_ver}（需要 >=3.12）"
    fi
  else
    bad "无法读取 backend Python 版本"
  fi
  gc_ver=$(docker compose exec -T backend python -c 'from importlib.metadata import version; print(version("garminconnect"))' 2>/dev/null || true)
  if [ "$gc_ver" = "0.3.20" ]; then
    ok "garminconnect==0.3.20"
  else
    bad "garminconnect 版本应为 0.3.20（当前：${gc_ver:-缺失}）"
  fi
  # 三项 Garmin 环境键存在（仅查键名，不打印值）
  for key in GARMIN_PLAN_SYNC_ENABLED GARMIN_PLAN_SYNC_STALE_SECONDS GARMIN_WORKOUT_TOKENSTORE; do
    if docker compose exec -T backend python -c "import os,sys; sys.exit(0 if os.environ.get('$key') is not None else 1)" 2>/dev/null; then
      ok "容器内存在环境键 $key"
    else
      bad "容器内缺少环境键 $key"
    fi
  done
  # tokenstore 父目录存在且可写；旧 garth 挂载仍在；不 cat token
  tokenstore_check=$(docker compose exec -T backend python -c '
import os
from pathlib import Path
ts = os.environ.get("GARMIN_WORKOUT_TOKENSTORE", "/var/lib/fitness/garmin-workout/tokens")
parent = Path(ts).parent
ok_parent = parent.is_dir() and os.access(parent, os.W_OK)
old = Path("/root/.garminconnect")
ok_old = old.exists()
print("PARENT_OK" if ok_parent else "PARENT_BAD")
print("OLD_OK" if ok_old else "OLD_BAD")
' 2>/dev/null || true)
  echo "$tokenstore_check" | grep -q PARENT_OK && ok "GARMIN_WORKOUT_TOKENSTORE 父目录存在且可写" || bad "GARMIN_WORKOUT_TOKENSTORE 父目录不存在或不可写"
  echo "$tokenstore_check" | grep -q OLD_OK && ok "旧 /root/.garminconnect 挂载仍存在" || bad "旧 /root/.garminconnect 挂载缺失"
  # backend 仅 1 个副本（内存 token + 调度器）
  backend_n=$(docker compose ps --status running backend 2>/dev/null | grep -c backend || true)
  if [ "${backend_n:-0}" -eq 1 ]; then
    ok "backend 单副本（n=1）"
  else
    bad "backend 必须单副本（当前 running 计数：${backend_n:-0}）"
  fi
  # 时区核验：输出 date 与 %Z（不 dump 环境）
  tz_out=$(docker compose exec -T backend sh -c 'date; date +%Z' 2>/dev/null || true)
  if [ -n "$tz_out" ]; then
    ok "backend 时区核验：$(echo "$tz_out" | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
  else
    bad "无法读取 backend date/%Z"
  fi
fi

echo
echo "结果：$PASS 通过，$FAIL 失败"
[ "$FAIL" -eq 0 ]
