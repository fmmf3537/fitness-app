"""ADR §11：AI 只读审核员——判断既有映射是否合理，不改映射只落审核表。"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Callable

from garminconnect import exercises as garmin_exercises
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters import llm
from app.adapters.llm import strip_think
from app.models import ExerciseMapping, ExerciseMappingReview
from app.services.exercise_mapping_llm import (
    _catalog_by_category,
    _lookup_display_name,
    validate_candidate,
)
from app.services.exercise_tokens import PART_TO_GARMIN_CATEGORIES
from app.services.stats import classify_part

logger = logging.getLogger(__name__)

VERDICT_CURRENT_OK = "current_ok"
VERDICT_BETTER = "better_candidate"
VERDICT_SUSPECTED_ERROR = "suspected_error"
VERDICT_LIKELY_UNMAPPED = "likely_unmapped"
VERDICT_NEEDS_HUMAN = "needs_human"
VERDICTS = (
    VERDICT_CURRENT_OK,
    VERDICT_BETTER,
    VERDICT_SUSPECTED_ERROR,
    VERDICT_LIKELY_UNMAPPED,
    VERDICT_NEEDS_HUMAN,
)

REVIEW_BATCH_SIZE = 20
REVIEW_MAX_BATCHES = 10
REVIEW_MAX_EXERCISES_PER_CATEGORY = 40

_SYSTEM_PROMPT = (
    "你是训记→Garmin 动作映射的只读审核员。"
    "判断给定的「训记动作 → 当前 Garmin 映射」是否合理。\n"
    "【本系统的既定策略，请勿试图纠正】\n"
    "1. 姿态优先于器械：当 Garmin 没有「同器械 + 同姿态」的条目时，本系统**有意保留姿态**\n"
    "   （上斜/下斜/侧躺/坐姿/俯身/支撑/单侧等）而舍弃器械，而不是反过来。\n"
    "   器械不符已经由 relation=SIMILAR 与 note='器械不符…' 显式标注，\n"
    "   **不要仅因为「器械不一致」就判为 better_candidate**。\n"
    "2. 只有当建议项比当前项**同时匹配更多维度**（器械 + 姿态 + 握法 + 单双侧）时，\n"
    "   才判为 better_candidate；若只是「换一个维度对、丢掉另一个维度」，属于等价取舍，\n"
    "   应判 current_ok。\n"
    "3. 判 better_candidate 时，reason 必须明确写出**当前项丢了什么维度、建议项丢了什么维度**，\n"
    "   让人类判断这个取舍是否值得。\n"
    "4. 允许并鼓励判 likely_unmapped 与 needs_human —— 「不知道」比「猜一个」更有价值。\n"
    "硬性要求：\n"
    "1. 只输出 JSON 数组，不要 Markdown 围栏以外的解释。\n"
    "2. 每个元素必须含字段：name, verdict, suggested, reason。\n"
    "3. verdict 只能是以下之一："
    "current_ok / better_candidate / suspected_error / likely_unmapped / needs_human。\n"
    "4. 若 verdict 为 better_candidate，suggested 必须为 "
    '{"category": "...", "exerciseName": "..."}，'
    "且两者都必须来自该动作给出的候选列表；其他 verdict 时 suggested 为 null。\n"
    "5. 只在给定候选列表里选择，不得发明目录外的 category 或 exerciseName。\n"
    "6. 拿不准时返回 needs_human；若判断可能没有 Garmin 对应项，"
    "返回 likely_unmapped（这是合法结论，不是失败）。\n"
    "7. reason 用中文，不超过 80 字。"
)

_ZERO_STATS = {
    "requested": 0,
    "processed": 0,
    "batches": 0,
    "by_verdict": {
        VERDICT_CURRENT_OK: 0,
        VERDICT_BETTER: 0,
        VERDICT_SUSPECTED_ERROR: 0,
        VERDICT_LIKELY_UNMAPPED: 0,
        VERDICT_NEEDS_HUMAN: 0,
    },
    "rejected_suggestions": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "batch_id": "",
}


def build_prompt(items: list[dict]) -> list[dict]:
    """构造审核 messages。items 含当前映射字段；候选来自真实 Garmin 目录。"""
    by_cat = _catalog_by_category()
    all_categories = list(garmin_exercises.CATEGORIES)

    parts: list[str] = []
    for item in items:
        name = item.get("xunji_name") or ""
        part = classify_part(name)
        categories = list(PART_TO_GARMIN_CATEGORIES.get(part) or [])
        block = [
            f"动作: {name}",
            f"部位: {part}",
            (
                "当前映射: "
                f"category={item.get('garmin_category') or ''} / "
                f"exerciseName={item.get('garmin_exercise_name') or ''} / "
                f"display_name={item.get('garmin_display_name') or ''}"
            ),
            f"relation: {item.get('relation') or ''}",
            f"note: {item.get('note') or ''}",
        ]
        if not categories:
            block.append("可用候选（全部 category，无条目示例）:")
            block.append(", ".join(all_categories))
        else:
            block.append("可用候选（只可从下列选择）:")
            for cat in categories:
                rows = by_cat.get(cat) or []
                total = len(rows)
                capped = rows[:REVIEW_MAX_EXERCISES_PER_CATEGORY]
                suffix = (
                    f"（共 {total} 条，已截断至 {REVIEW_MAX_EXERCISES_PER_CATEGORY}）"
                    if total > REVIEW_MAX_EXERCISES_PER_CATEGORY
                    else f"（共 {total} 条）"
                )
                block.append(f"  [{cat}] {suffix}")
                for entry in capped:
                    ex = entry.get("exercise") or ""
                    disp = entry.get("name") or ""
                    block.append(f"    {cat} / {ex} / {disp}")
        parts.append("\n".join(block))

    user = (
        "请审核下列映射，输出 JSON 数组（每项含 name/verdict/suggested/reason）：\n\n"
        + "\n\n".join(parts)
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def parse_review_response(content: str) -> list[dict]:
    """解析审核 JSON 数组；失败返回 []，非法项丢弃。"""
    if not content or not str(content).strip():
        return []

    text = strip_think(str(content).strip())
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < 0 or end < start:
        return []
    snippet = text[start : end + 1]

    try:
        data = json.loads(snippet)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []

    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        verdict = item.get("verdict")
        if not isinstance(verdict, str) or verdict not in VERDICTS:
            continue
        suggested = item.get("suggested")
        if suggested is not None and not isinstance(suggested, dict):
            continue
        reason = item.get("reason", "")
        if reason is None:
            reason = ""
        if not isinstance(reason, str):
            reason = str(reason)
        out.append(
            {
                "name": name.strip(),
                "verdict": verdict,
                "suggested": suggested,
                "reason": reason,
            }
        )
    return out


def validate_suggestion(
    category: str | None,
    exercise_name: str | None,
) -> bool:
    """审核建议必须是真实目录对；空串 exerciseName 一律无效。"""
    if exercise_name is None or not isinstance(exercise_name, str):
        return False
    if exercise_name == "":
        return False
    if not category or not isinstance(category, str):
        return False
    return validate_candidate(category, exercise_name)


def _select_targets(
    session: Session,
    *,
    limit: int,
    only_active: bool,
) -> list[ExerciseMapping]:
    stmt = select(ExerciseMapping).order_by(ExerciseMapping.id)
    if only_active:
        stmt = stmt.where(ExerciseMapping.status == "active")
    if limit > 0:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


def _mapping_to_item(row: ExerciseMapping) -> dict:
    return {
        "xunji_name": row.xunji_name,
        "garmin_category": row.garmin_category,
        "garmin_exercise_name": row.garmin_exercise_name,
        "garmin_display_name": row.garmin_display_name,
        "relation": row.relation,
        "note": row.note,
    }


def _downgrade_reason(reason: str, detail: str) -> str:
    base = (reason or "").strip()
    if not base:
        return detail
    return f"{base}；{detail}"


def _persist_review(
    session: Session,
    *,
    mapping: ExerciseMapping,
    verdict: str,
    suggested_category: str | None,
    suggested_exercise_name: str | None,
    suggested_display_name: str | None,
    reason: str,
    model: str | None,
    batch_id: str,
    stats: dict,
) -> None:
    session.add(
        ExerciseMappingReview(
            mapping_id=mapping.id,
            xunji_name=mapping.xunji_name,
            verdict=verdict,
            suggested_category=suggested_category,
            suggested_exercise_name=suggested_exercise_name,
            suggested_display_name=suggested_display_name,
            reason=reason or None,
            model=model,
            batch_id=batch_id,
            resolved=False,
        )
    )
    stats["by_verdict"][verdict] = stats["by_verdict"].get(verdict, 0) + 1


def _handle_parsed_item(
    session: Session,
    item: dict,
    *,
    mapping_by_name: dict[str, ExerciseMapping],
    model: str | None,
    batch_id: str,
    stats: dict,
) -> None:
    mapping = mapping_by_name.get(item["name"])
    if mapping is None:
        return

    verdict = item["verdict"]
    reason = item.get("reason") or ""
    suggested = item.get("suggested")
    sug_cat: str | None = None
    sug_ex: str | None = None
    sug_disp: str | None = None

    if verdict == VERDICT_BETTER:
        if not isinstance(suggested, dict):
            verdict = VERDICT_NEEDS_HUMAN
            reason = _downgrade_reason(reason, "建议缺失，降级为 needs_human")
            stats["rejected_suggestions"] += 1
        else:
            cat = suggested.get("category")
            ex = suggested.get("exerciseName")
            if not validate_suggestion(cat, ex):
                verdict = VERDICT_NEEDS_HUMAN
                reason = _downgrade_reason(
                    reason, "建议未通过目录校验，降级为 needs_human"
                )
                stats["rejected_suggestions"] += 1
            else:
                sug_cat = str(cat)
                sug_ex = str(ex)
                sug_disp = _lookup_display_name(sug_cat, sug_ex) or None
    elif isinstance(suggested, dict):
        cat = suggested.get("category")
        ex = suggested.get("exerciseName")
        if validate_suggestion(cat, ex):
            sug_cat = str(cat)
            sug_ex = str(ex)
            sug_disp = _lookup_display_name(sug_cat, sug_ex) or None
        else:
            verdict = VERDICT_NEEDS_HUMAN
            reason = _downgrade_reason(
                reason, "建议未通过目录校验，降级为 needs_human"
            )
            stats["rejected_suggestions"] += 1

    _persist_review(
        session,
        mapping=mapping,
        verdict=verdict,
        suggested_category=sug_cat,
        suggested_exercise_name=sug_ex,
        suggested_display_name=sug_disp,
        reason=reason,
        model=model,
        batch_id=batch_id,
        stats=stats,
    )


def review_mappings(
    session: Session,
    *,
    limit: int = 200,
    max_batches: int = REVIEW_MAX_BATCHES,
    chat_fn: Callable[[list[dict]], dict] | None = None,
    only_active: bool = True,
) -> dict:
    """ADR §11：对既有映射做只读审核，结果写入 exercise_mapping_review。

    - **绝不修改** ExerciseMapping 的任何字段（status/relation/verified_level 全不动）
    - 每个 verdict 都落库，同一 xunji_name 以最新一条为准（旧记录保留）
    - suggested 未通过 validate_suggestion 时降级为 needs_human，并把原因写进 reason
    """
    batch_id = uuid.uuid4().hex
    stats = {
        **{k: (dict(v) if isinstance(v, dict) else v) for k, v in _ZERO_STATS.items()},
        "batch_id": batch_id,
    }
    if limit <= 0:
        session.commit()
        return stats

    targets = _select_targets(session, limit=limit, only_active=only_active)
    stats["requested"] = len(targets)
    if not targets:
        session.commit()
        return stats

    if chat_fn is None:
        chat_fn = lambda msgs: llm.chat(
            msgs, session=session, purpose="exercise_mapping_review"
        )

    mapping_by_name = {row.xunji_name: row for row in targets}
    consecutive_failures = 0
    batch_cap = max(1, int(max_batches))
    batches_attempted = 0

    for batch_idx in range(0, len(targets), REVIEW_BATCH_SIZE):
        if batches_attempted >= batch_cap:
            break
        batches_attempted += 1
        batch = targets[batch_idx : batch_idx + REVIEW_BATCH_SIZE]
        items = [_mapping_to_item(row) for row in batch]
        try:
            result = chat_fn(build_prompt(items))
            consecutive_failures = 0
        except Exception:
            logger.exception(
                "review LLM batch failed (batch starting at %s)", batch_idx
            )
            consecutive_failures += 1
            if consecutive_failures >= 2:
                break
            continue

        stats["batches"] += 1
        stats["processed"] += len(batch)
        stats["prompt_tokens"] += int(result.get("prompt_tokens") or 0)
        stats["completion_tokens"] += int(result.get("completion_tokens") or 0)
        model = result.get("model")
        if model is not None:
            model = str(model)

        content = strip_think(result.get("content", ""))
        parsed = parse_review_response(content)
        for item in parsed:
            _handle_parsed_item(
                session,
                item,
                mapping_by_name=mapping_by_name,
                model=model,
                batch_id=batch_id,
                stats=stats,
            )

    session.commit()
    return stats


def list_reviews(
    session: Session,
    *,
    batch_id: str | None = None,
    verdict: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """返回审核结果列表（新的在前）。"""
    stmt = select(ExerciseMappingReview).order_by(
        ExerciseMappingReview.created_at.desc(),
        ExerciseMappingReview.id.desc(),
    )
    if batch_id:
        stmt = stmt.where(ExerciseMappingReview.batch_id == batch_id)
    if verdict:
        stmt = stmt.where(ExerciseMappingReview.verdict == verdict)
    if limit > 0:
        stmt = stmt.limit(limit)

    rows = list(session.scalars(stmt).all())
    out: list[dict] = []
    for row in rows:
        out.append(
            {
                "id": row.id,
                "xunji_name": row.xunji_name,
                "verdict": row.verdict,
                "suggested_category": row.suggested_category,
                "suggested_exercise_name": row.suggested_exercise_name,
                "reason": row.reason,
                "model": row.model,
                "batch_id": row.batch_id,
                "resolved": bool(row.resolved),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return out
