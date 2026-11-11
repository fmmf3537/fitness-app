"""训记→Garmin 动作映射：seed 与 DB 加载（查库在此，mapper 仍为纯函数）。"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ExerciseMapping
from app.services.garmin_workout_mapper import EXERCISE_WHITELIST


def _infer_weight_strategy(xunji_name: str, display_name: str) -> str:
    """按器械名推断重量语义声明（本切片不做换算）。"""
    if "Dumbbell" in display_name or "哑铃" in xunji_name:
        return "per_hand"
    if any(token in xunji_name for token in ("卷腹", "转体", "平板")):
        return "bodyweight"
    return "total"


def build_seed_rows() -> list[dict[str, Any]]:
    """把 EXERCISE_WHITELIST 转成 exercise_mapping 行。"""
    rows: list[dict[str, Any]] = []
    for xunji_name, item in EXERCISE_WHITELIST.items():
        display_name = item["display_name"]
        support_level = item["support_level"]
        rows.append(
            {
                "xunji_name": xunji_name,
                "garmin_category": item["category"],
                "garmin_exercise_name": item["exerciseName"],
                "garmin_display_name": display_name,
                "weight_strategy": _infer_weight_strategy(xunji_name, display_name),
                "status": "active",
                "source": "seed",
                "verified_level": "displayed",
                "mapping_version": 1,
                "note": (
                    f"seed from EXERCISE_WHITELIST, support_level={support_level}"
                ),
            }
        )
    return rows


SEED_MAPPINGS: list[dict[str, Any]] = build_seed_rows()


# 前端按 support_level 决定「已端到端验证 / 待远端验收」文案
# （GarminPlanPreviewModal.jsx:124 判断 p0_verified/p2_verified/p3_verified）。
# DB 侧存的是 verified_level（none/catalog/created/displayed），这里派生为 UI 语义：
# created/displayed = 已真实创建或已目视确认 → 端到端已验证
# 其余（none/catalog）→ 仅目录映射，待远端验收
_END_TO_END_VERIFIED = "p3_verified"
_PENDING_REMOTE = "user_confirmed_catalog_pending_end_to_end"


def _support_level_for(verified_level: str | None) -> str:
    """verified_level → 前端可读的 support_level（仅影响展示文案）。"""
    if (verified_level or "").lower() in {"created", "displayed"}:
        return _END_TO_END_VERIFIED
    return _PENDING_REMOTE


def _row_to_mapping_dict(row: ExerciseMapping) -> dict[str, Any]:
    return {
        "category": row.garmin_category,
        "exerciseName": row.garmin_exercise_name,
        "display_name": row.garmin_display_name,
        # mapper 的预览段会读 support_level（garmin_workout_mapper.py 预览组装）
        "support_level": _support_level_for(row.verified_level),
        "weight_strategy": row.weight_strategy,
        "status": row.status,
    }


def _whitelist_as_mappings() -> dict[str, dict[str, Any]]:
    """EXERCISE_WHITELIST 派生的等价字典，形状可直接喂给 map_plan_day。"""
    result: dict[str, dict[str, Any]] = {}
    for seed in SEED_MAPPINGS:
        result[seed["xunji_name"]] = {
            "category": seed["garmin_category"],
            "exerciseName": seed["garmin_exercise_name"],
            "display_name": seed["garmin_display_name"],
            # seed 的 16 条全部是 p0/p2/p3_verified（都已端到端验收），
            # 前端只判断是否属于这三者，故统一给等价常量即可。
            "support_level": _END_TO_END_VERIFIED,
            "weight_strategy": seed["weight_strategy"],
            "status": seed["status"],
        }
    return result


def seed_mappings(session: Session) -> dict[str, int]:
    """幂等写入 seed：按 xunji_name 已存在则跳过（不覆盖用户改过的行）。"""
    existing = {
        name
        for name in session.scalars(select(ExerciseMapping.xunji_name)).all()
    }
    inserted = 0
    skipped = 0
    for seed in build_seed_rows():
        if seed["xunji_name"] in existing:
            skipped += 1
            continue
        session.add(ExerciseMapping(**seed))
        inserted += 1
    session.commit()
    return {"inserted": inserted, "skipped": skipped}


def load_active_mappings(session: Session) -> dict[str, dict[str, Any]]:
    """返回 active 映射；表为空（未 seed）时回退 EXERCISE_WHITELIST 等价字典。"""
    total = session.scalar(select(func.count()).select_from(ExerciseMapping)) or 0
    if total == 0:
        return _whitelist_as_mappings()
    rows = session.scalars(
        select(ExerciseMapping).where(ExerciseMapping.status == "active")
    ).all()
    return {row.xunji_name: _row_to_mapping_dict(row) for row in rows}


def load_mapping_snapshot_hash(session: Session, xunji_names: list[str]) -> str:
    """对给定动作名集合的 active 映射做稳定 sha256 快照。

    缺失映射按 (name, None, None, None, 0) 参与哈希。
    """
    if not xunji_names:
        return hashlib.sha256(b"[]").hexdigest()

    rows = session.scalars(
        select(ExerciseMapping).where(
            ExerciseMapping.xunji_name.in_(xunji_names),
            ExerciseMapping.status == "active",
        )
    ).all()
    by_name = {row.xunji_name: row for row in rows}

    snapshot: list[list[Any]] = []
    for name in sorted(xunji_names):
        row = by_name.get(name)
        if row is None:
            snapshot.append([name, None, None, None, 0])
        else:
            snapshot.append(
                [
                    name,
                    row.garmin_category,
                    row.garmin_exercise_name,
                    row.weight_strategy,
                    row.mapping_version,
                ]
            )
    blob = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
