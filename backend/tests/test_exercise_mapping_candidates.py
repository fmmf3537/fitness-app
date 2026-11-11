"""exercise_mapping_candidates 4 级窄化纯函数测试（无 DB）。"""
from __future__ import annotations

import json
from pathlib import Path

from app.services.exercise_mapping_candidates import (
    Candidate,
    classify_applicability,
    extract_tokens,
    generate_batch,
    generate_candidates,
)

DATA_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "data" / "xunji_movements.json"
)
_CONF_RANK = {"high": 3, "medium": 2, "low": 1}


# ---- 适用性 ----


def test_classify_applicability_strength():
    assert classify_applicability("哑铃卧推") == (True, None)


def test_classify_applicability_cardio():
    assert classify_applicability("跑步") == (False, "有氧动作，非力量训练")
    assert classify_applicability("椭圆机") == (False, "有氧动作，非力量训练")


def test_classify_applicability_flexibility():
    ok, reason = classify_applicability("腿部拉伸")
    assert ok is False
    assert reason is not None
    assert "拉伸" in reason


# ---- 词元抽取 ----


def test_extract_tokens_simple():
    tokens = extract_tokens("哑铃卧推")
    assert "dumbbell" in tokens["equipment"]
    assert "bench press" in tokens["movements"]


def test_extract_tokens_multi_posture():
    tokens = extract_tokens("上斜单臂哑铃卧推")
    assert "incline" in tokens["postures"]
    assert "single arm" in tokens["postures"]


def test_extract_tokens_long_key_priority():
    tokens = extract_tokens("罗马尼亚硬拉")
    assert tokens["movements"] == ["romanian deadlift"]
    assert "deadlift" not in tokens["movements"]


# ---- 候选生成 ----


def test_generate_candidates_dumbbell_bench_press():
    cands = generate_candidates("哑铃卧推")
    assert cands
    top = cands[0]
    assert top.rank == 1
    assert top.garmin_category == "BENCH_PRESS"
    assert top.garmin_exercise_name == "DUMBBELL_BENCH_PRESS"
    assert top.confidence == "high"


def test_generate_candidates_barbell_squat():
    cands = generate_candidates("杠铃深蹲")
    assert cands
    top = cands[0]
    assert top.rank == 1
    assert top.garmin_category == "SQUAT"
    name_l = top.garmin_display_name.lower()
    assert "barbell" in name_l and "squat" in name_l
    assert top.garmin_exercise_name == "BARBELL_BACK_SQUAT" or (
        "BARBELL" in top.garmin_exercise_name and "SQUAT" in top.garmin_exercise_name
    )


def test_generate_candidates_respects_limit():
    assert len(generate_candidates("哑铃卧推", limit=1)) == 1
    assert generate_candidates("哑铃卧推", limit=0) == []


def test_generate_candidates_injected_catalog():
    catalog = [
        {
            "name": "Dumbbell Bench Press",
            "category": "BENCH_PRESS",
            "exercise": "DUMBBELL_BENCH_PRESS",
        }
    ]
    cands = generate_candidates("哑铃卧推", catalog=catalog)
    assert len(cands) == 1
    assert cands[0].garmin_exercise_name == "DUMBBELL_BENCH_PRESS"
    assert cands[0].garmin_display_name == "Dumbbell Bench Press"


def test_generate_candidates_no_match_returns_low_or_empty():
    # 不含任何动作词根 → 走兜底路径（基础分 20，判 low）或直接返回空
    cands = generate_candidates("玄幻光子脉冲XYZ")
    assert cands == [] or all(c.confidence == "low" for c in cands)

    # 对照：含「推举」的编造名会命中 shoulder press（器械不匹配 → medium 而非 high）
    matched = generate_candidates("玄幻光子脉冲推举XYZ")
    assert matched
    assert matched[0].confidence in {"medium", "low"}
    assert matched[0].garmin_category == "SHOULDER_PRESS"


def test_generate_candidates_output_is_sorted_and_ranked():
    cands = generate_candidates("哑铃卧推", limit=5)
    assert cands
    assert [c.rank for c in cands] == list(range(1, len(cands) + 1))
    conf_scores = [_CONF_RANK[c.confidence] for c in cands]
    assert conf_scores == sorted(conf_scores, reverse=True)


# ---- 边界与不适用 ----


def test_generate_candidates_not_applicable_returns_empty():
    assert generate_candidates("腿部拉伸") == []


def test_generate_candidates_blank_name():
    assert generate_candidates("") == []
    assert generate_candidates("   ") == []


def test_generate_candidates_dedup():
    catalog = [
        {
            "name": "Dumbbell Bench Press",
            "category": "BENCH_PRESS",
            "exercise": "DUMBBELL_BENCH_PRESS",
        },
        {
            "name": "Dumbbell Bench Press Dup",
            "category": "BENCH_PRESS",
            "exercise": "DUMBBELL_BENCH_PRESS",
        },
    ]
    cands = generate_candidates("哑铃卧推", catalog=catalog)
    keys = {(c.garmin_category, c.garmin_exercise_name) for c in cands}
    assert len(keys) == len(cands)


# ---- 全量冒烟 ----


def test_generate_batch_over_all_1091_does_not_crash():
    names = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert len(names) == 1091
    result = generate_batch(names)
    assert len(result) == 1091
    assert all(isinstance(v, list) for v in result.values())
    assert all(isinstance(c, Candidate) for v in result.values() for c in v)


def test_generate_batch_coverage_floor():
    # 实测（1091 个动作名，阈值 60/40 分档）：
    #   not_applicable 164 / empty 220 / low 210 / medium 267 / high 230
    #   → 力量类 927 个中 707 个（76%）至少有一个候选
    # 阈值取实测 230 的约 80%（180），防止词表退化；若后续提升须同步上调。
    names = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    result = generate_batch(names)
    high_count = sum(
        1
        for cands in result.values()
        if any(c.confidence == "high" for c in cands)
    )
    assert high_count >= 180, f"high 覆盖过低: {high_count}"
