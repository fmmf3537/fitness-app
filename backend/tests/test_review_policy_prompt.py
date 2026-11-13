"""ADR-P2-4：审核 prompt 的政策约束与 user 段字段回归。"""
from __future__ import annotations

import re

from garminconnect import exercises as garmin_exercises

from app.services.exercise_mapping_review import build_prompt


def _system_content(items: list[dict] | None = None) -> str:
    msgs = build_prompt(items or [{"xunji_name": "哑铃卧推"}])
    assert msgs and msgs[0]["role"] == "system"
    return msgs[0]["content"]


def _user_content(items: list[dict]) -> str:
    msgs = build_prompt(items)
    assert len(msgs) >= 2 and msgs[1]["role"] == "user"
    return msgs[1]["content"]


def test_system_prompt_contains_policy():
    content = _system_content()
    assert "姿态优先于器械" in content
    assert "不要仅因为「器械不一致」" in content


def test_system_prompt_requires_tradeoff_reason():
    assert "当前项丢了什么维度" in _system_content()


def test_system_prompt_encourages_unknown():
    assert "允许并鼓励判 likely_unmapped" in _system_content()


def test_user_prompt_includes_relation_and_note():
    note = "器械不符：当前为哑铃版，无同姿态史密斯条目"
    user = _user_content(
        [
            {
                "xunji_name": "下斜史密斯机卧推",
                "garmin_category": "BENCH_PRESS",
                "garmin_exercise_name": "DECLINE_DUMBBELL_BENCH_PRESS",
                "garmin_display_name": "Decline Dumbbell Bench Press",
                "relation": "SIMILAR",
                "note": note,
            }
        ]
    )
    assert "relation: SIMILAR" in user
    assert f"note: {note}" in user


def test_prompt_lists_only_catalog_candidates():
    user = _user_content(
        [
            {
                "xunji_name": "弹力带侧躺腿外展",
                "garmin_category": "BANDED_EXERCISES",
                "garmin_exercise_name": "LEG_ABDUCTION",
                "garmin_display_name": "Banded Leg Abduction",
                "relation": "SIMILAR",
                "note": "器械不符：…",
            }
        ]
    )
    catalog = {
        (e.get("category") or "", e.get("exercise") or "")
        for e in garmin_exercises.EXERCISES
        if e.get("category") and e.get("exercise")
    }
    # user 段候选行形如：    CAT / EXERCISE_NAME / Display Name
    for cat, ex in re.findall(
        r"^\s{4}([A-Z0-9_]+)\s*/\s*([A-Z0-9_]+)\s*/",
        user,
        flags=re.MULTILINE,
    ):
        assert (cat, ex) in catalog, f"prompt 含目录外候选: {cat}/{ex}"
