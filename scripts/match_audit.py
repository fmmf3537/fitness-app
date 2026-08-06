"""M7 真机联调：匹配准确率审计脚本（只读，不修改任何数据）。

用法：
    python scripts/match_audit.py [--days 7]

输出：
    1. 近 N 天 workout 表各 match_status 分布；
    2. 全部人工纠正过的匹配（match_candidate 中 status 为 merged/split 的记录）；
    3. 自动匹配准确率 = 自动匹配且未被人工纠正 / 自动匹配总数。

口径假设（与当前产品流程一致）：
    - 人工纠正 = match_candidate 中已被人工处置（merged/split）的记录；
    - “被人工纠正的自动匹配” = 人工 split 的候选，其 (xunji_train_id, garmin_activity_id)
      组合对应一条仍为 auto_matched 的 workout（当前 UI 无撤销自动匹配入口，正常为 0）；
    - 无自动匹配记录时准确率为 None，报告中标注“样本不足”。
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import GarminActivity, MatchCandidate, Workout, XunjiTrain  # noqa: E402

ACCURACY_TARGET = 0.90


def compute_accuracy(auto_matched: int, auto_corrected: int) -> float | None:
    """自动匹配准确率 = 未被纠正的自动匹配 / 自动匹配总数；无样本返回 None。"""
    total = auto_matched + auto_corrected
    if total == 0:
        return None
    return (total - auto_corrected) / total


def collect_audit(session, days: int = 7, today: date | None = None) -> dict:
    """汇总近 days 天匹配审计数据（纯查询，可单测）。"""
    today = today or date.today()
    since = today - timedelta(days=days - 1)

    workouts = (
        session.query(Workout)
        .filter(Workout.date >= since, Workout.date <= today)
        .order_by(Workout.date, Workout.id)
        .all()
    )
    status_dist: dict[str, int] = {}
    for w in workouts:
        status_dist[w.match_status] = status_dist.get(w.match_status, 0) + 1

    resolved = (
        session.query(MatchCandidate)
        .filter(MatchCandidate.status.in_(["merged", "split"]))
        .order_by(MatchCandidate.id)
        .all()
    )
    corrections = []
    for c in resolved:
        train = session.get(XunjiTrain, c.xunji_train_id) if c.xunji_train_id else None
        activity = (
            session.query(GarminActivity)
            .filter(GarminActivity.id == c.garmin_activity_id)
            .first()
            if c.garmin_activity_id
            else None
        )
        corrections.append(
            {
                "id": c.id,
                "reason": c.reason,
                "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
                "xunji": (
                    {"datestr": train.datestr, "title": train.title} if train else None
                ),
                "garmin": (
                    {
                        "activity_id": activity.activity_id,
                        "type": activity.activity_type,
                        "name": activity.name,
                    }
                    if activity
                    else None
                ),
                "undid_auto_match": bool(
                    c.status == "split"
                    and c.xunji_train_id
                    and c.garmin_activity_id
                    and any(
                        w.match_status == "auto_matched"
                        and w.xunji_train_id == c.xunji_train_id
                        and w.garmin_activity_id == c.garmin_activity_id
                        for w in workouts
                    )
                ),
            }
        )

    auto_matched = status_dist.get("auto_matched", 0)
    auto_corrected = sum(1 for c in corrections if c["undid_auto_match"])
    pending_count = (
        session.query(MatchCandidate)
        .filter(MatchCandidate.status == "pending")
        .count()
    )
    return {
        "window": {"since": since.isoformat(), "until": today.isoformat(), "days": days},
        "workout_total": len(workouts),
        "status_dist": status_dist,
        "corrections": corrections,
        "pending_candidates": pending_count,
        "auto_matched": auto_matched,
        "auto_corrected": auto_corrected,
        "accuracy": compute_accuracy(auto_matched, auto_corrected),
    }


def render_report(result: dict) -> str:
    """渲染中文审计报告。"""
    w = result["window"]
    lines = [
        f"=== 匹配准确率审计（{w['since']} ~ {w['until']}，近 {w['days']} 天）===",
        f"workout 总数: {result['workout_total']}",
        "match_status 分布: "
        + (
            ", ".join(f"{k}={v}" for k, v in sorted(result["status_dist"].items()))
            or "（无记录）"
        ),
        f"待确认队列未处理: {result['pending_candidates']} 条",
        "",
        f"人工纠正过的匹配（共 {len(result['corrections'])} 条）:",
    ]
    for c in result["corrections"]:
        x = c["xunji"] or {}
        g = c["garmin"] or {}
        lines.append(
            f"  - #{c['id']} [{c['reason']} -> {c['status']}] "
            f"训记({x.get('datestr', '-')}, {x.get('title', '-')}) <-> "
            f"佳明({g.get('activity_id', '-')}, {g.get('type', '-')}, {g.get('name', '-')})"
            + ("  ※撤销了自动匹配" if c["undid_auto_match"] else "")
        )
    if not result["corrections"]:
        lines.append("  （无）")

    lines += [
        "",
        f"自动匹配总数: {result['auto_matched'] + result['auto_corrected']}"
        f"（当前 auto_matched={result['auto_matched']}，被人工纠正={result['auto_corrected']}）",
    ]
    acc = result["accuracy"]
    if acc is None:
        lines.append("自动匹配准确率: 样本不足（窗口内无自动匹配记录）")
        lines.append("结论: 无法判定")
    else:
        lines.append(f"自动匹配准确率: {acc:.1%}")
        lines.append(
            "结论: " + ("达标（≥90%）" if acc >= ACCURACY_TARGET else "未达标（<90%）")
        )
    return "\n".join(lines)


def main() -> None:
    # Windows GBK 控制台下保证中文报告可读
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="M7 匹配准确率审计")
    parser.add_argument("--days", type=int, default=7, help="统计窗口天数（默认 7）")
    args = parser.parse_args()

    session = make_session_factory(make_engine())()
    try:
        result = collect_audit(session, days=args.days)
    finally:
        session.close()
    print(render_report(result))


if __name__ == "__main__":
    main()
