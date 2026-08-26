#!/usr/bin/env python
"""M6 / 阶段 3：从单用户版 sqlite 导入 12 张表到 multiuser-v2 postgres。

用法（在主机执行，因为需要读 host 上的 sqlite + 写 docker postgres）：

    docker cp backend/data/app.db fitness-hub-backend-1:/tmp/singleuser.db
    docker cp backend/scripts/import_from_singleuser_sqlite.py fitness-hub-backend-1:/tmp/import.py
    docker compose exec -T backend python /tmp/import.py

行为：
- 跳过 users（multiuser-v2 已有 admin）
- 跳过 settings（阶段 4 单独处理）
- 跳过 backfill_progress / leaderboard_cache（单/多用户版不兼容）
- 跳过 alembic_version / auth_token / audit_log
- 其余 10 张表：TRUNCATE 后 INSERT（user_id 全部设为 admin.id=1）
- 用 COPY 风格批量插入（executemany）

可重入：先 TRUNCATE 再 INSERT，重复跑幂等。
"""
import sqlite3
import os
import sys

# 注入 /app 让 import app.* 生效
sys.path.insert(0, "/app")

from sqlalchemy import create_engine, text, inspect
from app.db import engine  # multiuser-v2 postgres engine

SQLITE_PATH = "/tmp/singleuser.db"
ADMIN_ID = 1  # multiuser-v2 已有 admin id=1

# 同步的 10 张表（单用户版 → multiuser-v2）
# 单/多 schema 完全一致（user_id 列已存在），所以可以列对列复制
TABLES = [
    "xunji_train",
    "garmin_activity",
    "garmin_daily",
    "body_metric",
    "workout",
    "match_candidate",
    "xunji_plan",
    "ai_report",
    "llm_call",
    "report_chat_message",
    "job_run",
]

# 单用户版有但 multiuser-v2 不需要/不兼容
SKIP_TABLES = [
    "users",          # multiuser-v2 已有 admin
    "settings",       # 阶段 4 单独处理（56 行 → 1 行）
    "backfill_progress",  # 旧版同步进度，multiuser-v2 schema 不同
    "leaderboard_cache",  # 新表，旧版没有
    "alembic_version",    # 不同 db，alembic version 不一样
    "auth_token",         # 旧版没启用
    "audit_log",          # 旧版没启用
]


def main() -> int:
    if not os.path.exists(SQLITE_PATH):
        print(f"ERROR: {SQLITE_PATH} not found. Run: docker cp backend/data/app.db <container>:/tmp/singleuser.db", file=sys.stderr)
        return 1

    sconn = sqlite3.connect(SQLITE_PATH)
    sconn.row_factory = sqlite3.Row

    print(f"=== import_from_singleuser_sqlite.py ===")
    print(f"sqlite: {SQLITE_PATH}")
    print(f"target admin_id: {ADMIN_ID}")
    print(f"tables to import: {len(TABLES)}")
    print()

    total_inserted = 0
    insp = inspect(engine)  # 用于查每张表的 column 类型
    # 预计算每张表的 boolean 列名
    bool_cols_per_table = {}
    for t in TABLES:
        bool_cols_per_table[t] = [
            c["name"] for c in insp.get_columns(t)
            if "boolean" in str(c["type"]).lower() or "bool" in str(c["type"]).lower()
        ]

    with engine.begin() as pconn:
        # 先 TRUNCATE（如果表存在），清掉 multiuser-v2 里 0 行数据
        for t in TABLES:
            pconn.execute(text(f"TRUNCATE TABLE {t} RESTART IDENTITY CASCADE"))

        for table in TABLES:
            # 1) 读 sqlite（用原生 sqlite3 cursor，不用 SQLAlchemy text）
            scur = sconn.execute(f"SELECT * FROM {table}")
            cols = [d[0] for d in scur.description]
            rows = scur.fetchall()
            n_sqlite = len(rows)
            if n_sqlite == 0:
                print(f"  [{table}] 0 rows in sqlite, skip")
                continue

            # 2) 把 user_id 改成 admin.id（阶段 5 不再处理这些表）
            # 注意：sqlite 的列名是字符串，转换成 dict 后改 user_id
            bool_cols = bool_cols_per_table[table]
            data = []
            for r in rows:
                d = dict(r)
                d["user_id"] = ADMIN_ID
                # sqlite 用 0/1 表示 boolean，postgres 要 True/False
                for bc in bool_cols:
                    if bc in d and d[bc] is not None:
                        d[bc] = bool(d[bc])
                data.append(d)

            # 3) 写 postgres（executemany）
            col_list = ", ".join(cols)
            placeholders = ", ".join(f":{c}" for c in cols)
            insert_sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
            # 批量，每批 500 行
            BATCH = 500
            for i in range(0, len(data), BATCH):
                pconn.execute(text(insert_sql), data[i:i+BATCH])

            # 4) 验证
            npg = pconn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            total_inserted += npg
            print(f"  [{table}] sqlite={n_sqlite}  postgres={npg}  ✓")

    print()
    print(f"=== 全部完成: {total_inserted} 行导入到 postgres ===")
    sconn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
