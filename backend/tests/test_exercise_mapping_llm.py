"""V6-3：LLM 兜底候选服务层测试（全部注入 chat_fn，不联网）。"""
from __future__ import annotations

import json

from garminconnect import exercises as garmin_exercises
from sqlalchemy import func, select

from app.models import ExerciseMapping, ExerciseMappingCandidate
from app.services import exercise_mapping_llm as llm_svc
from app.services.exercise_mapping_llm import (
    LLM_MAX_EXERCISES_PER_CATEGORY,
    build_prompt,
    parse_response,
    suggest_candidates_with_llm,
    validate_candidate,
)
from app.services.exercise_tokens import PART_TO_GARMIN_CATEGORIES
from app.services.stats import classify_part


def _real_pair() -> tuple[str, str, str]:
    for entry in garmin_exercises.EXERCISES:
        cat = entry.get("category") or ""
        ex = entry.get("exercise") or ""
        if cat and ex:
            return cat, ex, entry.get("name") or ""
    raise RuntimeError("Garmin catalog empty")


def _count_pending(session, name: str) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(ExerciseMappingCandidate)
            .where(
                ExerciseMappingCandidate.xunji_name == name,
                ExerciseMappingCandidate.status == "pending",
            )
        )
        or 0
    )


def _add_draft(session, name: str, *, category: str | None = None) -> ExerciseMapping:
    row = ExerciseMapping(
        xunji_name=name,
        garmin_category=category,
        garmin_exercise_name=None,
        garmin_display_name=None,
        status="draft",
        confidence=None,
        source="test",
        verified_level="none",
        mapping_version=1,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _fake_chat_for(name: str, category: str, exercise_name: str, reason: str = "match"):
    payload = [
        {
            "xunji_name": name,
            "category": category,
            "exercise_name": exercise_name,
            "reason": reason,
        }
    ]

    def fake(messages):
        return {
            "content": json.dumps(payload, ensure_ascii=False),
            "prompt_tokens": 10,
            "completion_tokens": 5,
        }

    return fake


# ---- build_prompt ----


def test_build_prompt_shape():
    msgs = build_prompt(["哑铃卧推", "杠铃深蹲"])
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    user = msgs[1]["content"]
    assert "哑铃卧推" in user
    assert "杠铃深蹲" in user


def test_build_prompt_includes_categories():
    name = "哑铃卧推"
    part = classify_part(name)
    cats = PART_TO_GARMIN_CATEGORIES[part]
    assert cats
    user = build_prompt([name])[1]["content"]
    for cat in cats:
        assert cat in user


def test_build_prompt_other_part_lists_all_categories():
    name = "未知器械XYZ"
    assert classify_part(name) == "其他"
    user = build_prompt([name])[1]["content"]
    assert len(garmin_exercises.CATEGORIES) == 47
    for cat in garmin_exercises.CATEGORIES:
        assert cat in user
    # 「其他」不给条目示例：不应出现 " / " 三段式代表行
    assert " / " not in user


def test_build_prompt_respects_exercise_cap():
    name = "哑铃卧推"
    part = classify_part(name)
    cats = PART_TO_GARMIN_CATEGORIES[part]
    user = build_prompt([name])[1]["content"]
    for cat in cats:
        # 统计该 category 下的示例行（缩进后的三段式）
        lines = [
            line
            for line in user.splitlines()
            if line.strip().startswith(f"{cat} / ")
        ]
        assert len(lines) <= LLM_MAX_EXERCISES_PER_CATEGORY


# ---- parse_response ----


def test_parse_response_plain_json():
    raw = json.dumps(
        [
            {
                "xunji_name": "哑铃卧推",
                "category": "BENCH_PRESS",
                "exercise_name": "DUMBBELL_BENCH_PRESS",
                "reason": "ok",
            }
        ]
    )
    items = parse_response(raw)
    assert len(items) == 1
    assert items[0]["xunji_name"] == "哑铃卧推"
    assert items[0]["category"] == "BENCH_PRESS"


def test_parse_response_strips_code_fence():
    raw = (
        "```json\n"
        '[{"xunji_name":"哑铃卧推","category":"BENCH_PRESS",'
        '"exercise_name":"DUMBBELL_BENCH_PRESS","reason":"ok"}]\n'
        "```"
    )
    items = parse_response(raw)
    assert len(items) == 1
    assert items[0]["category"] == "BENCH_PRESS"


def test_parse_response_extracts_from_prose():
    raw = (
        "下面是结果：\n"
        '[{"xunji_name":"杠铃深蹲","category":"SQUAT",'
        '"exercise_name":"BARBELL_BACK_SQUAT","reason":"leg"}]\n'
        "完毕。"
    )
    items = parse_response(raw)
    assert len(items) == 1
    assert items[0]["xunji_name"] == "杠铃深蹲"


def test_parse_response_invalid_returns_empty():
    assert parse_response("这不是 JSON") == []
    assert parse_response("") == []
    assert parse_response("<<<>>>") == []


def test_parse_response_skips_items_missing_fields():
    raw = json.dumps(
        [
            {"category": "BENCH_PRESS", "exercise_name": "X"},
            {
                "xunji_name": "哑铃卧推",
                "category": "BENCH_PRESS",
                "exercise_name": "DUMBBELL_BENCH_PRESS",
                "reason": "ok",
            },
            {"xunji_name": "无分类", "exercise_name": ""},
        ]
    )
    items = parse_response(raw)
    assert len(items) == 1
    assert items[0]["xunji_name"] == "哑铃卧推"


# ---- validate_candidate ----


def test_validate_candidate_accepts_real_pair():
    cat, ex, _ = _real_pair()
    assert validate_candidate(cat, ex) is True


def test_validate_candidate_rejects_unknown_category():
    assert validate_candidate("NOT_A_REAL_CATEGORY", "ANYTHING") is False


def test_validate_candidate_rejects_unknown_exercise():
    cat, _, _ = _real_pair()
    assert validate_candidate(cat, "TOTALLY_FAKE_EXERCISE_NAME") is False


def test_validate_candidate_accepts_empty_exercise_name():
    cat, _, _ = _real_pair()
    assert validate_candidate(cat, "") is True
    assert validate_candidate(cat, None) is True


# ---- suggest_candidates_with_llm ----


def test_suggest_writes_candidate_and_fills_mapping(session, monkeypatch):
    name = "LLM测试动作甲"
    cat, ex, _ = _real_pair()
    row = _add_draft(session, name)
    monkeypatch.setattr(llm_svc, "_load_movement_names", lambda: [name])
    stats = suggest_candidates_with_llm(
        session, limit=10, max_batches=1, chat_fn=_fake_chat_for(name, cat, ex, "相似")
    )
    assert stats["accepted"] == 1
    session.refresh(row)
    assert row.garmin_category == cat
    assert row.garmin_exercise_name == ex
    assert row.confidence == "low"

    cand = session.scalars(
        select(ExerciseMappingCandidate).where(
            ExerciseMappingCandidate.xunji_name == name
        )
    ).one()
    assert cand.status == "pending"
    assert cand.confidence == "low"
    assert cand.reason.startswith("LLM:")


def test_suggest_never_activates_mapping(session, monkeypatch):
    name = "LLM测试不激活"
    cat, ex, _ = _real_pair()
    row = _add_draft(session, name)
    monkeypatch.setattr(llm_svc, "_load_movement_names", lambda: [name])
    suggest_candidates_with_llm(
        session, limit=10, max_batches=1, chat_fn=_fake_chat_for(name, cat, ex)
    )
    session.refresh(row)
    assert row.status == "draft"


def test_suggest_rejects_hallucinated_movement(session, monkeypatch):
    name = "LLM真实动作"
    cat, ex, _ = _real_pair()
    _add_draft(session, name)
    monkeypatch.setattr(llm_svc, "_load_movement_names", lambda: [name])

    def fake(messages):
        return {
            "content": json.dumps(
                [
                    {
                        "xunji_name": "臆造动作名",
                        "category": cat,
                        "exercise_name": ex,
                        "reason": "hallucination",
                    }
                ]
            ),
            "prompt_tokens": 1,
            "completion_tokens": 1,
        }

    stats = suggest_candidates_with_llm(
        session, limit=10, max_batches=1, chat_fn=fake
    )
    assert stats["accepted"] == 0
    assert stats["rejected"] >= 1
    assert _count_pending(session, name) == 0


def test_suggest_rejects_invalid_category(session, monkeypatch):
    name = "LLM非法分类"
    _add_draft(session, name)
    monkeypatch.setattr(llm_svc, "_load_movement_names", lambda: [name])
    stats = suggest_candidates_with_llm(
        session,
        limit=10,
        max_batches=1,
        chat_fn=_fake_chat_for(name, "NOT_IN_47", "X"),
    )
    assert stats["accepted"] == 0
    assert stats["rejected"] >= 1


def test_suggest_skips_not_applicable(session, monkeypatch):
    na = "LLM有氧跳过"
    ok = "LLM力量保留"
    cat, ex, _ = _real_pair()
    session.add(
        ExerciseMapping(
            xunji_name=na,
            status="not_applicable",
            not_applicable_reason="有氧",
            source="test",
            verified_level="none",
            mapping_version=1,
        )
    )
    _add_draft(session, ok)
    monkeypatch.setattr(llm_svc, "_load_movement_names", lambda: [na, ok])

    calls: list[list[dict]] = []

    def fake(messages):
        calls.append(messages)
        return {
            "content": json.dumps(
                [
                    {
                        "xunji_name": ok,
                        "category": cat,
                        "exercise_name": ex,
                        "reason": "ok",
                    }
                ]
            ),
            "prompt_tokens": 1,
            "completion_tokens": 1,
        }

    stats = suggest_candidates_with_llm(
        session, limit=10, max_batches=1, chat_fn=fake
    )
    assert stats["requested"] == 1
    assert len(calls) == 1
    assert ok in calls[0][1]["content"]
    assert na not in calls[0][1]["content"]


def test_suggest_limit_zero_makes_no_call(session):
    calls = {"n": 0}

    def fake(messages):
        calls["n"] += 1
        return {"content": "[]", "prompt_tokens": 0, "completion_tokens": 0}

    stats = suggest_candidates_with_llm(
        session, limit=0, max_batches=1, chat_fn=fake
    )
    assert calls["n"] == 0
    assert stats == {
        "requested": 0,
        "processed": 0,
        "batches": 0,
        "accepted": 0,
        "rejected": 0,
        "skipped_no_candidate_list": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }


def test_suggest_idempotent_pending(session, monkeypatch):
    name = "LLM幂等动作"
    cat, ex, _ = _real_pair()
    _add_draft(session, name)
    monkeypatch.setattr(llm_svc, "_load_movement_names", lambda: [name])
    chat = _fake_chat_for(name, cat, ex)
    suggest_candidates_with_llm(session, limit=10, max_batches=1, chat_fn=chat)
    # 第二次需 only_without_candidate=False：首次已回填 garmin_category
    suggest_candidates_with_llm(
        session,
        limit=10,
        max_batches=1,
        chat_fn=chat,
        only_without_candidate=False,
    )
    assert _count_pending(session, name) == 1


def test_suggest_keeps_accepted_candidate(session, monkeypatch):
    name = "LLM保留已采纳"
    cat, ex, _ = _real_pair()
    _add_draft(session, name)
    kept = ExerciseMappingCandidate(
        xunji_name=name,
        garmin_category=cat,
        garmin_exercise_name=ex,
        garmin_display_name="kept",
        confidence="high",
        reason="manual accept",
        rank=1,
        status="accepted",
    )
    session.add(kept)
    session.commit()
    kept_id = kept.id

    monkeypatch.setattr(llm_svc, "_load_movement_names", lambda: [name])
    suggest_candidates_with_llm(
        session, limit=10, max_batches=1, chat_fn=_fake_chat_for(name, cat, ex)
    )
    still = session.get(ExerciseMappingCandidate, kept_id)
    assert still is not None
    assert still.status == "accepted"
    assert _count_pending(session, name) == 1


def test_suggest_tolerates_one_failing_batch(session, monkeypatch):
    a, b = "LLM批次甲", "LLM批次乙"
    cat, ex, _ = _real_pair()
    _add_draft(session, a)
    _add_draft(session, b)
    monkeypatch.setattr(llm_svc, "_load_movement_names", lambda: [a, b])
    monkeypatch.setattr(llm_svc, "LLM_BATCH_SIZE", 1)

    state = {"n": 0}

    def flaky(messages):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("transient LLM error")
        # 第二批：处理排序后的第二个名字
        user = messages[1]["content"]
        target = a if a in user else b
        return {
            "content": json.dumps(
                [
                    {
                        "xunji_name": target,
                        "category": cat,
                        "exercise_name": ex,
                        "reason": "recovered",
                    }
                ]
            ),
            "prompt_tokens": 2,
            "completion_tokens": 2,
        }

    stats = suggest_candidates_with_llm(
        session, limit=10, max_batches=2, chat_fn=flaky
    )
    assert state["n"] == 2
    assert stats["accepted"] == 1
    assert stats["batches"] == 1
    pending_total = (
        session.scalar(
            select(func.count())
            .select_from(ExerciseMappingCandidate)
            .where(ExerciseMappingCandidate.status == "pending")
        )
        or 0
    )
    assert pending_total == 1
