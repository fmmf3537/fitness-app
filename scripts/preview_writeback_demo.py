"""V1-5-FIX 验证脚本：真实跑一次写回 preview（只读），证明 diff changed 行精确。

场景：给 2026-08-03「宽距高位下拉」第 1 组标 RPE 8。
纪律：preview 路径只做 include_full_data=true 读，绝不调用写回接口；
      本脚本额外把 upsert_trains 替换为直接抛错，双保险禁止任何真实写回外呼。

用法：
    python scripts/preview_writeback_demo.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import select  # noqa: E402

from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import XunjiTrain  # noqa: E402
from app.services.writeback import WritebackService  # noqa: E402

DATESTR = "2026-08-03"
CHANGES = {"movements": [{"name": "宽距高位下拉", "sets": [{"index": 1, "rpe": "8"}]}]}


def main() -> None:
    session = make_session_factory(make_engine())()
    try:
        service = WritebackService(session)

        # 双保险：任何写回外呼直接抛错（preview 本身结构上就不会调用）
        def _forbidden(*args, **kwargs):
            raise RuntimeError("禁止写回外呼：本脚本只允许只读 preview")

        service.xunji.upsert_trains = _forbidden  # type: ignore[method-assign]

        localid = session.scalars(
            select(XunjiTrain.localid).where(XunjiTrain.datestr == DATESTR).limit(1)
        ).first()
        if localid is None:
            # 库里尚无该日缓存，先完整读一次拿到 localid（下一次 preview 会走 30s 限频）
            service.xunji.fetch_trains(DATESTR, include_full_data=True, force_refresh=True)
            localid = session.scalars(
                select(XunjiTrain.localid).where(XunjiTrain.datestr == DATESTR).limit(1)
            ).first()
        if localid is None:
            print(f"训记 {DATESTR} 无训练记录，无法演示")
            return

        print(f"preview: datestr={DATESTR} localid={localid}")
        print(f"changes: {json.dumps(CHANGES, ensure_ascii=False)}")
        result = service.preview(DATESTR, localid, CHANGES)

        diff = result["diff"]
        changed = [r for r in diff if r["changed"]]
        print(f"\ndiff 总行数: {len(diff)}，changed=true 行数: {len(changed)}")
        print("changed 行明细：")
        for r in changed:
            print(f"  {r['field']}: {r['old']!r} -> {r['new']!r}")

        movements = result["train"]["movements"]
        print(f"\n合并后动作数: {len(movements)}")
        for m in movements:
            print(f"  {m.get('index')}. {m.get('name')} ({len(m.get('sets') or [])} 组)")

        assert len(changed) == 1, f"changed 行应精确只有 1 行，实际 {len(changed)}"
        assert changed[0]["field"].endswith("第1组 rpe"), changed[0]
        assert changed[0]["new"] == "8"
        print("\n✔ 验证通过：changed 行精确只有 rpe 一行，全程零写回外呼")
    finally:
        session.close()


if __name__ == "__main__":
    main()
