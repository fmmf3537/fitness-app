#!/usr/bin/env sh
# 每日 PostgreSQL 备份：pg_dump 自定义格式，保留 ${BACKUP_RETENTION_DAYS:-30} 天。
# 连接参数由环境变量注入（PGHOST/PGUSER/PGPASSWORD/PGDATABASE），密钥不落盘。
set -eu

RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
FILE="/backups/fitness_$(date +%F).dump"

pg_dump --format=custom --no-owner --file="$FILE"

# 滚动清理过期备份（保留最近 30 天，PRD §7）
find /backups -name 'fitness_*.dump' -type f -mtime "+${RETENTION_DAYS}" -delete

echo "[backup] $(date) written $FILE (retention ${RETENTION_DAYS}d)"
