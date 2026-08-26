"""fix postgres sequences after import_from_singleuser_sqlite.py.

Reason: import 用 executemany INSERT with id column, but PostgreSQL SERIAL
sequences don't auto-increment when id is explicitly set. So next INSERT
using DEFAULT (id) starts from 1 → conflict with imported ids.

Fix: setval(pg_get_serial_sequence('table', 'id'), max(id))
for every table with serial id column.
"""
import sys
sys.path.insert(0, "/app")

from sqlalchemy import text, inspect
from app.db import engine

insp = inspect(engine)
tables_with_id = []
for t in insp.get_table_names():
    cols = insp.get_columns(t)
    if any(c["name"] == "id" and "int" in str(c["type"]).lower() for c in cols):
        # 排除 alembic_version
        if t == "alembic_version":
            continue
        tables_with_id.append(t)

with engine.begin() as conn:
    for t in tables_with_id:
        # 找 sequence name (PostgreSQL 命名约定: tablename_id_seq)
        seq_sql = text(
            "SELECT pg_get_serial_sequence(:t, 'id')"
        )
        seq = conn.execute(seq_sql, {"t": t}).scalar()
        if not seq:
            print(f"  {t}: no sequence (maybe id not SERIAL?), skip")
            continue
        max_id = conn.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {t}")).scalar()
        # PostgreSQL setval 不接受 0（sequence 最小 1），空表跳过（sequence 默认从 1 开始）
        if max_id < 1:
            print(f"  {t:>30}  sequence={seq}  empty, skip")
            continue
        # setval(seq, max_id) — 下次 nextval 返回 max_id+1
        conn.execute(text(f"SELECT setval(:s, :v)"), {"s": seq, "v": max_id})
        print(f"  {t:>30}  sequence={seq}  setval={max_id}  (next id = {max_id+1})")
