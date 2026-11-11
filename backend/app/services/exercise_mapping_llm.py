"""用 LLM 为「无自动候选」的动作补候选。

只写 exercise_mapping_candidate（status=pending）并回填 mapping 的
garmin_* / confidence='low'；绝不改 mapping.status、绝不自动激活。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Callable

from garminconnect import exercises as garmin_exercises
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.adapters import llm
from app.adapters.llm import strip_think
from app.models import ExerciseMapping, ExerciseMappingCandidate
from app.services.exercise_tokens import PART_TO_GARMIN_CATEGORIES
from app.services.stats import classify_part

logger = logging.getLogger(__name__)

LLM_BATCH_SIZE = 20
LLM_MAX_BATCHES = 30
LLM_MAX_EXERCISES_PER_CATEGORY = 25

_MOVEMENTS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "xunji_movements.json"
)

_ZERO_STATS = {
    "requested": 0,
    "processed": 0,
    "batches": 0,
    "accepted": 0,
    "rejected": 0,
    "skipped_no_candidate_list": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
}


def _load_movement_names() -> list[str]:
    with open(_MOVEMENTS_PATH, encoding="utf-8") as f:
        names = json.load(f)
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ValueError(f"动作名表格式非法: {_MOVEMENTS_PATH}")
    return list(names)


def _catalog_by_category(
    catalog: list[dict] | None = None,
) -> dict[str, list[dict]]:
    source = catalog if catalog is not None else garmin_exercises.EXERCISES
    by_cat: dict[str, list[dict]] = {}
    for entry in source:
        cat = entry.get("category") or ""
        by_cat.setdefault(cat, []).append(entry)
    return by_cat


def _lookup_display_name(
    category: str,
    exercise_name: str,
    *,
    by_cat: dict[str, list[dict]] | None = None,
) -> str:
    rows = (by_cat or _catalog_by_category()).get(category) or []
    ex = exercise_name or ""
    for entry in rows:
        if (entry.get("exercise") or "") == ex:
            return entry.get("name") or ""
    return ex or category


def build_prompt(movements: list[str]) -> list[dict]:
    """构造 OpenAI 风格 messages。纯函数，可单测。

    对每个动作给出：部位（stats.classify_part）、该部位可用的 Garmin category 列表、
    以及这些 category 下最多 LLM_MAX_EXERCISES_PER_CATEGORY 个代表条目
    （格式 "CATEGORY / EXERCISE_NAME / Display Name"）。
    「其他」部位（categories 为空）时给全部 47 个 category 名但不给条目示例
    （避免 prompt 过长）。

    要求模型只输出 JSON 数组，元素形如：
      {"xunji_name": "...", "category": "...", "exercise_name": "...", "reason": "..."}
    并明确要求：category 必须来自给定列表；exercise_name 必须是该 category 下
    真实条目（可为空串）；不确定时把 exercise_name 设为空串并在 reason 说明。
    """
    by_cat = _catalog_by_category()
    all_categories = list(garmin_exercises.CATEGORIES)

    system = (
        "你是训记→Garmin 动作映射助手。根据给定的训记动作名与可用 Garmin 目录子集，"
        "为每个动作挑选最合适的 Garmin category 与 exercise_name。\n"
        "硬性要求：\n"
        "1. 只输出 JSON 数组，不要 Markdown 围栏以外的解释。\n"
        "2. 每个元素必须含字段："
        'xunji_name, category, exercise_name, reason。\n'
        "3. category 必须来自该动作给出的可用列表。\n"
        "4. exercise_name 必须是该 category 下的真实条目（可为空字符串 \"\"）；"
        "不确定时把 exercise_name 设为 \"\" 并在 reason 说明。\n"
        "5. 不要编造列表外的动作名或 category。"
    )

    parts: list[str] = []
    for name in movements:
        part = classify_part(name)
        categories = list(PART_TO_GARMIN_CATEGORIES.get(part) or [])
        block = [f"动作: {name}", f"部位: {part}"]
        if not categories:
            block.append("可用 category（全部，无条目示例）:")
            block.append(", ".join(all_categories))
        else:
            block.append("可用 category 与代表条目:")
            for cat in categories:
                block.append(f"  [{cat}]")
                examples = (by_cat.get(cat) or [])[:LLM_MAX_EXERCISES_PER_CATEGORY]
                for entry in examples:
                    ex = entry.get("exercise") or ""
                    disp = entry.get("name") or ""
                    block.append(f"    {cat} / {ex} / {disp}")
        parts.append("\n".join(block))

    user = (
        "请为下列动作生成映射候选，输出 JSON 数组：\n\n"
        + "\n\n".join(parts)
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_response(content: str) -> list[dict]:
    """从模型输出里抠出 JSON 数组并校验。纯函数，可单测。

    容错要求：
    - 剥离 ```json ... ``` 代码块围栏
    - 允许前后有解释文字（截取第一个 '[' 到最后一个 ']'）
    - 解析失败返回 []
    - 逐条校验字段齐全（xunji_name/category 必填），不合法条目跳过
    """
    if not content or not str(content).strip():
        return []

    text = str(content).strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

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
        xunji_name = item.get("xunji_name")
        category = item.get("category")
        if not isinstance(xunji_name, str) or not xunji_name.strip():
            continue
        if not isinstance(category, str) or not category.strip():
            continue
        exercise_name = item.get("exercise_name", "")
        if exercise_name is None:
            exercise_name = ""
        if not isinstance(exercise_name, str):
            continue
        reason = item.get("reason", "")
        if reason is None:
            reason = ""
        if not isinstance(reason, str):
            reason = str(reason)
        out.append(
            {
                "xunji_name": xunji_name.strip(),
                "category": category.strip(),
                "exercise_name": exercise_name,
                "reason": reason,
            }
        )
    return out


def validate_candidate(
    category: str | None,
    exercise_name: str | None,
    *,
    catalog: list[dict] | None = None,
) -> bool:
    """校验 (category, exercise_name) 是否真实存在于 Garmin 目录。

    - category 必须在 exercises.CATEGORIES
    - exercise_name 为空串时只要 category 合法即通过
    - 非空时要求 ((category, exercise)) 在目录中（大小写严格）
    """
    if not category or not isinstance(category, str):
        return False

    if catalog is None:
        if category not in garmin_exercises.CATEGORIES:
            return False
        source = garmin_exercises.EXERCISES
    else:
        categories = {e.get("category") for e in catalog}
        if category not in categories:
            return False
        source = catalog

    ex = "" if exercise_name is None else exercise_name
    if ex == "":
        return True
    return any(
        e.get("category") == category and (e.get("exercise") or "") == ex
        for e in source
    )


def _select_targets(
    session: Session,
    names: list[str],
    *,
    only_without_candidate: bool,
) -> list[str]:
    existing = {
        row.xunji_name: row
        for row in session.scalars(select(ExerciseMapping)).all()
    }
    selected: list[str] = []
    for name in names:
        row = existing.get(name)
        if row is None:
            selected.append(name)
            continue
        if row.status == "not_applicable":
            continue
        if only_without_candidate and row.garmin_category is not None:
            continue
        selected.append(name)
    selected.sort()
    return selected


def _replace_pending_candidate(
    session: Session,
    *,
    xunji_name: str,
    category: str,
    exercise_name: str,
    display_name: str,
    reason: str,
) -> None:
    session.execute(
        delete(ExerciseMappingCandidate).where(
            ExerciseMappingCandidate.xunji_name == xunji_name,
            ExerciseMappingCandidate.status == "pending",
        )
    )
    session.add(
        ExerciseMappingCandidate(
            xunji_name=xunji_name,
            garmin_category=category,
            garmin_exercise_name=exercise_name,
            garmin_display_name=display_name,
            confidence="low",
            reason=reason,
            rank=1,
            status="pending",
        )
    )


def suggest_candidates_with_llm(
    session: Session,
    *,
    limit: int = 200,
    max_batches: int = LLM_MAX_BATCHES,
    chat_fn: Callable[[list[dict]], dict] | None = None,
    only_without_candidate: bool = True,
) -> dict:
    """主入口。返回统计字典：
        {"requested", "processed", "batches", "accepted", "rejected",
         "skipped_no_candidate_list", "prompt_tokens", "completion_tokens"}
    """
    stats = dict(_ZERO_STATS)
    if limit <= 0:
        return stats

    names = _load_movement_names()
    targets = _select_targets(
        session, names, only_without_candidate=only_without_candidate
    )
    targets = targets[:limit]
    stats["requested"] = len(targets)
    if not targets:
        session.commit()
        return stats

    if chat_fn is None:
        chat_fn = lambda msgs: llm.chat(
            msgs, session=session, purpose="exercise_mapping"
        )

    mappings = {
        row.xunji_name: row
        for row in session.scalars(select(ExerciseMapping)).all()
    }
    by_cat = _catalog_by_category()

    consecutive_failures = 0
    batch_cap = max(1, int(max_batches))
    batches_attempted = 0
    for batch_idx in range(0, len(targets), LLM_BATCH_SIZE):
        if batches_attempted >= batch_cap:
            break
        batches_attempted += 1
        batch = targets[batch_idx : batch_idx + LLM_BATCH_SIZE]
        try:
            result = chat_fn(build_prompt(batch))
            consecutive_failures = 0
        except Exception:
            logger.exception("LLM batch failed (batch starting at %s)", batch_idx)
            consecutive_failures += 1
            if consecutive_failures >= 2:
                break
            continue

        stats["batches"] += 1
        stats["processed"] += len(batch)
        stats["prompt_tokens"] += int(result.get("prompt_tokens") or 0)
        stats["completion_tokens"] += int(result.get("completion_tokens") or 0)

        content = strip_think(result.get("content", ""))
        parsed = parse_response(content)
        if not parsed:
            stats["rejected"] += len(batch)
            continue

        batch_set = set(batch)
        seen_in_response: set[str] = set()

        for item in parsed:
            name = item["xunji_name"]
            seen_in_response.add(name)
            if name not in batch_set:
                stats["rejected"] += 1
                continue
            category = item["category"]
            exercise_name = item["exercise_name"]
            if not validate_candidate(category, exercise_name):
                stats["rejected"] += 1
                continue
            row = mappings.get(name)
            if row is None:
                stats["rejected"] += 1
                continue

            raw_reason = (item.get("reason") or "").strip()
            reason = f"LLM: {raw_reason}" if raw_reason else "LLM 兜底候选"
            display_name = _lookup_display_name(
                category, exercise_name, by_cat=by_cat
            )
            _replace_pending_candidate(
                session,
                xunji_name=name,
                category=category,
                exercise_name=exercise_name,
                display_name=display_name,
                reason=reason,
            )
            row.garmin_category = category
            row.garmin_exercise_name = exercise_name
            row.garmin_display_name = display_name
            row.confidence = "low"
            # status 保持 draft（或现有非 not_applicable 状态），绝不自动激活
            stats["accepted"] += 1

        for name in batch:
            if name not in seen_in_response:
                stats["skipped_no_candidate_list"] += 1

    session.commit()
    return stats
