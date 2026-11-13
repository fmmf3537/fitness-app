"""CI/部署检查：训记动作全集与映射表差异（ADR §8）。

比较解析后的动作名称集合；有新增或消失时以退出码 1 失败，
迫使人工确认改名 / 新动作 / 删除（不得只生成无人处理的报告）。

用法：
    容器内执行（推荐，镜像里已有依赖与 .env）：
        docker compose exec backend python scripts/check_xunji_catalog.py
        docker compose exec backend python scripts/check_xunji_catalog.py --json

    本机执行（需自行装好 backend 依赖并配置 DATABASE_URL）：
        backend/.venv/Scripts/python.exe backend/scripts/check_xunji_catalog.py

退出码：
    0  无差异（added/removed 皆空）
    1  有差异，需要人工确认
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal  # noqa: E402
from app.services.exercise_mapping_catalog import catalog_diff  # noqa: E402


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="检查训记动作全集与 exercise_mapping 的差异"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出 catalog_diff 原始 JSON 报告",
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        report = catalog_diff(session)
    finally:
        session.close()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        added_n = len(report["added"])
        removed_n = len(report["removed"])
        cand_n = len(report["rename_candidates"])
        print(
            f"训记全集检查: 新增 {added_n} / 消失 {removed_n} / 疑似改名 {cand_n}"
            f"（JSON={report['current_total']}, DB={report['db_total']}, "
            f"unchanged={report['unchanged']}）"
        )
        if report["needs_confirmation"]:
            if report["added"]:
                preview = ", ".join(report["added"][:5])
                more = "…" if added_n > 5 else ""
                print(f"  新增: {preview}{more}")
            if report["removed"]:
                preview = ", ".join(report["removed"][:5])
                more = "…" if removed_n > 5 else ""
                print(f"  消失: {preview}{more}")
            if report["rename_candidates"]:
                top = report["rename_candidates"][0]
                print(
                    f"  疑似改名示例: {top['from']!r} → {top['to']!r} "
                    f"(score={top['score']}, reasons={top['reasons']})"
                )
            print("需要人工确认（rename / new / delete）。")
        else:
            print("OK：动作全集与映射表一致。")

    return 1 if report["needs_confirmation"] else 0


if __name__ == "__main__":
    sys.exit(main())
