# 备份容器（V2-5）：每日 03:17 pg_dump 到 backups 卷，滚动保留 30 天（PRD §7）
FROM postgres:16-alpine

COPY backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh \
    && echo "17 3 * * * /usr/local/bin/backup.sh >> /backups/cron.log 2>&1" > /etc/crontabs/root

# busybox crond 前台运行
CMD ["crond", "-f", "-l", "2"]
