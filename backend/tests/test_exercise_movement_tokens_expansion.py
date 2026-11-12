"""V6-9c：MOVEMENT_TOKENS 扩充 + 死词修复回归（无 DB）。"""
from __future__ import annotations

import json
from pathlib import Path

from garminconnect import exercises as garmin_exercises

from app.services.exercise_mapping_candidates import (
    _norm,
    generate_batch,
    generate_candidates,
)
from app.services.exercise_tokens import (
    MOVEMENT_KEYS_BY_LENGTH,
    MOVEMENT_TOKENS,
)
from app.services.garmin_workout_mapper import EXERCISE_WHITELIST

DATA_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "data" / "xunji_movements.json"
)

# V6-9c 新增 74 条（与提示词措辞完全一致）
NEW_TOKENS: dict[str, str] = {
    "保加利亚蹲": "bulgarian split squat",
    "土耳其起身": "turkish get up",
    "保加利亚": "bulgarian split squat",
    "单腿屈伸": "leg extension",
    "小腿屈伸": "calf",
    "手臂上抬": "raise",
    "直腿上举": "leg raise",
    "站立提膝": "knee raise",
    "螃蟹行走": "lateral walk",
    "青蛙后蹬": "kickback",
    "髋部上抬": "hip raise",
    "髋部环绕": "hip circle",
    "体前屈": "forward bend",
    "倒立撑": "handstand push up",
    "健腹轮": "rollout",
    "分腿蹲": "split squat",
    "剪刀式": "scissor",
    "剪刀腿": "scissor",
    "大剪刀": "scissor",
    "滑冰式": "skater",
    "漫步机": "elliptical",
    "爬楼梯": "stair",
    "相扑蹲": "sumo squat",
    "砸药球": "medicine ball slam",
    "肩绕圈": "shoulder circle",
    "腹斜肌": "oblique",
    "腹肌轮": "rollout",
    "腿屈伸": "leg extension",
    "蝴蝶式": "butterfly",
    "螃式走": "lateral walk",
    "超人式": "superman",
    "髋上抬": "hip raise",
    "髋后伸": "hip extension",
    "上步": "step up",
    "侧压": "side lunge",
    "侧屈": "side bend",
    "侧转": "rotation",
    "倒蹬": "leg press",
    "前蹲": "front squat",
    "后压": "reverse lunge",
    "后蹬": "kickback",
    "外旋": "external rotation",
    "尺蠖": "inchworm",
    "开合": "clamshell",
    "弓步": "lunge",
    "快走": "walk",
    "悬垂": "hang",
    "扩胸": "fly",
    "扭转": "twist",
    "拉穿": "pull through",
    "拳击": "punch",
    "提拉": "upright row",
    "提腿": "leg raise",
    "提膝": "knee raise",
    "提髋": "hip raise",
    "摆腿": "leg swing",
    "旋转": "rotation",
    "早安": "good morning",
    "滚轮": "rollout",
    "猫式": "cat cow",
    "环绕": "circle",
    "画圆": "circle",
    "画圈": "circle",
    "箱式": "box",
    "绕圈": "circle",
    "翻举": "clean",
    "肩胛": "scapular",
    "蛙式": "frog",
    "跨步": "step",
    "转髋": "rotation",
    "顶胯": "hip thrust",
    "颈部": "neck",
    "风车": "windmill",
    "髋推": "hip thrust",
}

# 死词修复后的值（含农夫两条）
FIXED_DEAD_VALUES: dict[str, str] = {
    "颈弯举": "neck",
    "头后仰": "neck",
    "上斜推": "incline bench press",
    "农夫行走": "farmer",
    "农夫": "farmer",
}


# ---- 词表完整性 ----


def test_new_tokens_present():
    sample = [
        "保加利亚蹲",
        "土耳其起身",
        "分腿蹲",
        "猫式",
        "早安",
        "弓步",
        "倒立撑",
        "健腹轮",
        "相扑蹲",
        "风车",
        "髋推",
        "颈部",
    ]
    for zh in sample:
        assert zh in MOVEMENT_TOKENS
        assert MOVEMENT_TOKENS[zh] == NEW_TOKENS[zh]


def test_dead_tokens_removed():
    forbidden = {"neck curl", "neck extension", "incline press", "farmer carry"}
    values = set(MOVEMENT_TOKENS.values())
    assert not (forbidden & values)


def test_farmer_tokens_point_to_farmer():
    assert MOVEMENT_TOKENS["农夫"] == "farmer"
    assert MOVEMENT_TOKENS["农夫行走"] == "farmer"


def test_keys_by_length_includes_new():
    for zh in ("保加利亚蹲", "土耳其起身", "分腿蹲", "猫式"):
        assert zh in MOVEMENT_KEYS_BY_LENGTH
    lengths = [len(k) for k in MOVEMENT_KEYS_BY_LENGTH]
    assert lengths == sorted(lengths, reverse=True)


# ---- 每条新词都有真实命中 ----


def test_every_token_has_catalog_hit():
    roots = set(NEW_TOKENS.values()) | set(FIXED_DEAD_VALUES.values())
    catalog_norms = [_norm(e["name"]) for e in garmin_exercises.EXERCISES]
    for root in roots:
        root_n = _norm(root)
        assert root_n, f"空词根: {root!r}"
        hits = sum(1 for n in catalog_norms if root_n in n)
        assert hits >= 1, f"词根 {root!r} 在 Garmin 目录 0 命中"


# ---- 具体动作能映射 ----


def test_bulgarian_split_squat():
    cands = generate_candidates("保加利亚蹲（负重）")
    assert cands
    top = cands[0]
    assert top.rank == 1
    assert top.garmin_category == "LUNGE"
    assert "BULGARIAN_SPLIT_SQUAT" in top.garmin_exercise_name


def test_farmers_carry():
    cands = generate_candidates("六角杠农夫行走")
    assert cands
    top = cands[0]
    assert top.rank == 1
    assert top.garmin_category == "CARRY"
    assert top.garmin_exercise_name == "FARMERS_CARRY"


def test_cat_cow():
    cands = generate_candidates("俯身猫式")
    assert cands
    top = cands[0]
    assert top.rank == 1
    assert top.garmin_category == "WARM_UP"
    assert "CAT_COW" in top.garmin_exercise_name


def test_neck_exercises():
    cands = generate_candidates("上斜负重颈弯举")
    assert cands
    top = cands[0]
    assert top.rank == 1
    assert top.garmin_category == "WARM_UP"
    assert "NECK" in top.garmin_exercise_name


def test_split_squat():
    cands = generate_candidates("分腿蹲")
    assert cands
    top = cands[0]
    assert top.rank == 1
    assert top.garmin_category == "LUNGE"
    assert "SPLIT_SQUAT" in top.garmin_exercise_name


def test_good_morning():
    cands = generate_candidates("史密斯机早安")
    assert cands
    top = cands[0]
    assert top.rank == 1
    assert "GOOD_MORNING" in top.garmin_exercise_name


# ---- 回归保护 ----


def test_seed_mappings_unchanged():
    for name, item in EXERCISE_WHITELIST.items():
        cands = generate_candidates(name)
        assert cands, f"{name} 无候选"
        top = cands[0]
        assert top.rank == 1
        assert top.garmin_category == item["category"], (
            f"{name}: category {top.garmin_category} != {item['category']}"
        )
        assert top.garmin_exercise_name == item["exerciseName"], (
            f"{name}: exercise {top.garmin_exercise_name} != {item['exerciseName']}"
        )


def test_high_confidence_not_decreased():
    names = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert len(names) == 1091
    result = generate_batch(names)
    high_count = sum(
        1 for cands in result.values() if any(c.confidence == "high" for c in cands)
    )
    assert high_count >= 273, f"high 覆盖过低: {high_count}"


def test_empty_candidate_count_decreased():
    names = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    result = generate_batch(names)
    empty = sum(1 for cands in result.values() if not cands)
    # generate_candidates 对 not_applicable 也返回 []，与「力量类无候选」口径对齐时
    # 用 classify 再滤一次会更严；此处按提示词：完全无候选 <= 219（相对力量类基线）。
    from app.services.exercise_mapping_candidates import classify_applicability

    empty_applicable = sum(
        1
        for n, cands in result.items()
        if classify_applicability(n)[0] and not cands
    )
    assert empty_applicable <= 219, f"无候选过多: {empty_applicable} (all-empty={empty})"


# ---- 死词修复效果 ----


def test_neck_token_now_matches():
    neck_hits = sum(
        1 for e in garmin_exercises.EXERCISES if _norm("neck") in _norm(e["name"])
    )
    assert neck_hits >= 3


def test_farmer_token_matches_apostrophe_form():
    assert _norm("farmer") in _norm("Farmer's Carry")
