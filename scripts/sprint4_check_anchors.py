# -*- coding: utf-8 -*-
"""Sprint 4 评审：数据库锚点核对（只读，2026-08-07 实地验收数据作对照）。"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "backend" / "data" / "app.db"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
c = con.cursor()

print("--- body_metric（锚点：2 条，08-07 weight 88.0 已同步 / height 178 仅本地）---")
for r in c.execute(
    "SELECT id,date,type,value,unit,synced_to_xunji FROM body_metric ORDER BY date,type"
):
    print(dict(r))

print("--- ai_report（锚点：4 条，#4 为 next_advice DeepSeek 8123+2383）---")
for r in c.execute(
    "SELECT id,type,workout_id,model,prompt_tokens,completion_tokens,"
    "period_start,period_end,created_at FROM ai_report ORDER BY id"
):
    print(dict(r))

print("--- xunji_train 2026-08-03（锚点：「背二头2」，6 动作 22 组）---")
import json

for r in c.execute(
    "SELECT id,datestr,localid,title,raw_json FROM xunji_train WHERE datestr='2026-08-03'"
):
    d = dict(r)
    raw = json.loads(d.pop("raw_json") or "{}")
    mvs = raw.get("movements") or []
    sets = sum(len(m.get("sets") or []) for m in mvs)
    d["movements_count"] = len(mvs)
    d["sets_count"] = sets
    first = [m for m in mvs if m.get("name") == "宽距高位下拉"]
    if first and first[0].get("sets"):
        d["宽距高位下拉_第1组"] = first[0]["sets"][0]
    print(d)

print("--- job_run 最近 8 条（锚点：writeback/health_check 成功留痕）---")
for r in c.execute(
    "SELECT id,job_name,status,started_at FROM job_run ORDER BY id DESC LIMIT 8"
):
    print(dict(r))

print("--- xunji_plan 最近 5 条（锚点：新周期 2026-08-07~08-13 active）---")
for r in c.execute(
    "SELECT id,plan_ref,date_from,date_to,fetched_at FROM xunji_plan ORDER BY id DESC LIMIT 5"
):
    print(dict(r))

print("--- workout 2026-08-03 ---")
for r in c.execute(
    "SELECT id,date,title,match_status,tags,duration_s,calories,avg_hr,max_hr "
    "FROM workout WHERE date='2026-08-03'"
):
    print(dict(r))
con.close()
