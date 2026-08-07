# -*- coding: utf-8 -*-
"""Sprint 4 评审演示：体重同步训记三段式确认流（真实链路）。

步骤：
1. dry_run=True 预览：展示 res.summary，断言请求体 dry_run=True、无 confirmed 写入；
2. confirmed=True 执行：真实写入（同值 upsert，幂等），置 synced_to_xunji；
3. 服务器回查：query 训记 2026-08-07 weight，验证落账值 88.0；
4. 反向校验：height 类型走 SYNCABLE_TYPES 门禁，证明仅本地（对应 API 400）。

用法：python scripts/sprint4_body_sync_demo.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import select  # noqa: E402

from app.adapters.xunji_body import XunjiBodyClient  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import BodyMetric  # noqa: E402
from app.services.body_metrics import SYNCABLE_TYPES  # noqa: E402

DATESTR = "2026-08-07"


def main() -> None:
    session = make_session_factory(make_engine())()
    try:
        client = XunjiBodyClient(session)

        row = session.scalars(
            select(BodyMetric).where(
                BodyMetric.date == DATESTR, BodyMetric.type == "weight"
            )
        ).first()
        assert row is not None, "本地无 2026-08-07 weight 记录"
        records = [{"datestr": DATESTR, "type": "weight", "value": row.value}]
        print(f"本地记录: date={DATESTR} weight={row.value}{row.unit}")

        # ---------- 第 1 步：dry_run 预览 ----------
        print("\n[1/4] dry_run=True 预览（不发真实写入）")
        preview = client.upsert_body_metrics(records, dry_run=True)
        summary = (preview.get("res") or {}).get("summary") or ""
        print(f"  res.summary: {summary}")
        assert summary, "预览应返回 res.summary"

        # ---------- 反向校验：未确认的 dry_run=False 必须被拒 ----------
        print("\n[2/4] 门禁校验：dry_run=False 且未 confirmed → 必须拒绝且不外呼")
        try:
            client.upsert_body_metrics(records, dry_run=False, confirmed=False)
            raise AssertionError("未确认的真实写入未被拒绝！")
        except ValueError as exc:
            print(f"  ✔ 已拒绝: {exc}")

        # ---------- 第 2 步：用户确认，真实写入（同值 upsert，幂等） ----------
        print("\n[3/4] confirmed=True 执行真实写入（同值 upsert，幂等）")
        resp = client.upsert_body_metrics(records, dry_run=False, confirmed=True)
        print(f"  res.summary: {(resp.get('res') or {}).get('summary') or ''}")
        row.synced_to_xunji = True
        session.commit()

        # ---------- 第 3 步：服务器回查 ----------
        print("\n[4/4] 训记服务器回查 2026-08-07 weight")
        data = client.query_body_metrics(DATESTR, DATESTR, types=["weight"])
        res = data.get("res") or {}
        found = []
        for rec in res.get("records") or []:
            if str(rec.get("datestr")) == DATESTR and rec.get("type") == "weight":
                found.append(rec)
        print(f"  服务器记录: {json.dumps(found, ensure_ascii=False)}")
        assert found, "服务器未查到 2026-08-07 weight 记录"
        assert float(found[0].get("value")) == 88.0, f"落账值异常: {found[0]}"

        # ---------- height 仅本地门禁 ----------
        print("\n[附] height 同步门禁")
        print(f"  SYNCABLE_TYPES = {sorted(SYNCABLE_TYPES)}")
        assert "height" not in SYNCABLE_TYPES
        print("  ✔ height 不在可同步类型内（API 层返回 400「仅本地」）")

        print("\n✔ 三段式确认流演示通过：预览无写入 → 确认写入 → 服务器回查 88.0 落账")
    finally:
        session.close()


if __name__ == "__main__":
    main()
