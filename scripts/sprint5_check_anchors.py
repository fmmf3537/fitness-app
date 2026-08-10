"""Sprint 5 评审核对脚本：job_run 留痕 / 复盘幂等 / 记账锚点核查（用完可删）。

运行：cd backend && ..\\scripts 下脚本需先切到 backend 目录（相对 data/app.db）。
"""
import sqlite3

con = sqlite3.connect("data/app.db")
cur = con.cursor()

print("--- job_run recent 12 ---")
for r in cur.execute(
    "SELECT id, job_name, started_at, status, substr(COALESCE(detail_json,''),1,100) "
    "FROM job_run ORDER BY id DESC LIMIT 12"
):
    print(r)

print("--- review job_runs ---")
for r in cur.execute(
    "SELECT id, job_name, started_at, status, substr(COALESCE(detail_json,''),1,150) "
    "FROM job_run WHERE job_name LIKE '%review%' ORDER BY id"
):
    print(r)

print("--- weekly ai_report idempotency check (period 2026-08-03~09) ---")
for r in cur.execute(
    "SELECT id, type, period_start, period_end, model, created_at FROM ai_report "
    "WHERE type IN ('weekly','monthly') ORDER BY id"
):
    print(r)
