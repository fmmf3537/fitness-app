#!/usr/bin/env python
"""V2-5 一次性数据迁移：SQLite（开发库）→ PostgreSQL（生产库）。

前置：目标 PG 已执行 `alembic upgrade head`（空表结构已建好）。
用法（项目根目录）：
    python scripts/migrate_sqlite_to_pg.py \
        --sqlite sqlite:///./backend/data/app.db \
        --pg postgresql+psycopg2://fitness:***@localhost:5432/fitness
幂等：逐表按主键存在即跳过，可重复运行。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import MetaData, Table, create_engine, inspect, select, text

# 按外键依赖顺序迁移（父表在前）
# P0-5 修复：多用户表 users/auth_token/audit_log 必须先于所有业务表迁移
# （auth_token 和 audit_log FK 到 users）
TABLE_ORDER = [
    "users",         # M1-1：多用户父表，最先
    "auth_token",    # M2-3：FK users
    "audit_log",     # M1-1：FK users
    "settings",
    "xunji_train",
    "garmin_activity",
    "garmin_daily",
    "body_metric",
    "xunji_plan",
    "workout",
    "match_candidate",
    "ai_report",
    "llm_call",
    "backfill_progress",
    "job_run",
]


def migrate(sqlite_url: str, pg_url: str) -> None:
    src = create_engine(sqlite_url)
    dst = create_engine(pg_url)
    src_meta = MetaData()
    src_meta.reflect(bind=src)

    with src.connect() as sconn, dst.begin() as dconn:
        for name in TABLE_ORDER:
            if name not in src_meta.tables:
                print(f"[skip] {name} 在 SQLite 中不存在")
                continue
            table: Table = src_meta.tables[name]
            rows = sconn.execute(select(table)).mappings().all()
            if not rows:
                print(f"[skip] {name} 空表")
                continue
            pk_cols = [c.name for c in table.primary_key.columns]
            inserted = skipped = 0
            for row in rows:
                where = " AND ".join(f"{c} = :{c}" for c in pk_cols)
                exists = dconn.execute(
                    text(f'SELECT 1 FROM "{name}" WHERE {where}'),
                    {c: row[c] for c in pk_cols},
                ).first()
                if exists:
                    skipped += 1
                    continue
                cols = ", ".join(f'"{k}"' for k in row.keys())
                params = ", ".join(f":{k}" for k in row.keys())
                dconn.execute(
                    text(f'INSERT INTO "{name}" ({cols}) VALUES ({params})'),
                    dict(row),
                )
                inserted += 1
            print(f"[ok] {name}: 插入 {inserted}，跳过 {skipped}")

        # 重置自增序列，避免后续插入主键冲突
        insp = inspect(dconn)
        for name in TABLE_ORDER:
            if name in insp.get_table_names():
                dconn.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence(:t, 'id'), "
                        "COALESCE((SELECT MAX(id) FROM " + f'"{name}"' + "), 1))"
                    ),
                    {"t": name},
                )
    print("[done] 迁移完成，序列已重置")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SQLite → PostgreSQL 一次性数据迁移")
    parser.add_argument("--sqlite", required=True, help="源 SQLite URL")
    parser.add_argument("--pg", required=True, help="目标 PostgreSQL URL")
    args = parser.parse_args()
    migrate(args.sqlite, args.pg)
