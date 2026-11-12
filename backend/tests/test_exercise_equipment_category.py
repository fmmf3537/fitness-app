"""V6-9a：器械专属分类并入候选池（TRX / 弹力带等）。"""
from __future__ import annotations

import json
from pathlib import Path

from garminconnect import exercises

from app.services.exercise_mapping_candidates import (
    generate_batch,
    generate_candidates,
)
from app.services.exercise_tokens import (
    EQUIPMENT_TO_GARMIN_CATEGORY,
    EQUIPMENT_TOKENS,
)

DATA_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "data" / "xunji_movements.json"
)


# ---- 表与断言 ----


def test_equipment_category_values_are_real():
    real = set(exercises.CATEGORIES)
    for root, cat in EQUIPMENT_TO_GARMIN_CATEGORY.items():
        assert cat in real, f"{root} → 无效 category: {cat}"


def test_equipment_category_keys_are_equipment_roots():
    roots = set(EQUIPMENT_TOKENS.values())
    for key in EQUIPMENT_TO_GARMIN_CATEGORY:
        assert key in roots, f"键 {key!r} 不在 EQUIPMENT_TOKENS.values() 中"


def test_suspension_and_banded_present():
    assert EQUIPMENT_TO_GARMIN_CATEGORY["suspension"] == "SUSPENSION"
    assert EQUIPMENT_TO_GARMIN_CATEGORY["banded"] == "BANDED_EXERCISES"


# ---- TRX 修复 ----


def test_trx_biceps_curl_maps_to_suspension():
    cands = generate_candidates("TRX-二头弯举")
    assert cands
    top = cands[0]
    assert top.rank == 1
    assert top.garmin_category == "SUSPENSION"
    assert top.confidence == "high"


def test_trx_pistol_squat_maps_to_suspension():
    cands = generate_candidates("TRX-手枪深蹲")
    assert cands
    assert cands[0].rank == 1
    assert cands[0].garmin_category == "SUSPENSION"


def test_trx_row_maps_to_suspension():
    cands = generate_candidates("TRX-水平划船")
    assert cands
    assert cands[0].rank == 1
    assert cands[0].garmin_category == "SUSPENSION"


def test_ring_equipment_also_uses_suspension():
    cands = generate_candidates("吊环分腿深蹲")
    assert cands
    assert cands[0].rank == 1
    assert cands[0].garmin_category == "SUSPENSION"


# ---- 弹力带修复 ----


def test_banded_squat_maps_to_banded():
    cands = generate_candidates("弹力带-深蹲")
    assert cands
    top = cands[0]
    assert top.rank == 1
    assert top.garmin_category == "BANDED_EXERCISES"
    assert top.garmin_exercise_name == "SQUAT"


def test_banded_lateral_raise_maps_to_banded():
    cands = generate_candidates("弹力带-侧平举")
    assert cands
    assert cands[0].rank == 1
    assert cands[0].garmin_category == "BANDED_EXERCISES"


def test_banded_outranks_part_category():
    cands = generate_candidates("弹力带-深蹲", limit=10)
    banded = [c for c in cands if c.garmin_category == "BANDED_EXERCISES"]
    part = [c for c in cands if c.garmin_category == "SQUAT"]
    assert banded, "应含 BANDED_EXERCISES 候选"
    assert part, "应仍含部位分类 SQUAT 候选"
    assert banded[0].rank < part[0].rank


# ---- 回归 ----


def test_non_equipment_movement_unchanged():
    cands = generate_candidates("杠铃卧推")
    assert cands
    top = cands[0]
    assert top.rank == 1
    assert top.garmin_category == "BENCH_PRESS"
    assert top.garmin_exercise_name == "BARBELL_BENCH_PRESS"


def test_dumbbell_movement_unchanged():
    cands = generate_candidates("哑铃卧推")
    assert cands
    top = cands[0]
    assert top.rank == 1
    assert top.garmin_category == "BENCH_PRESS"
    assert top.garmin_exercise_name == "DUMBBELL_BENCH_PRESS"


def test_not_applicable_still_empty():
    assert generate_candidates("腿部拉伸") == []


def test_blank_still_empty():
    assert generate_candidates("") == []
    assert generate_candidates("   ") == []


# ---- 全量回归 ----


def test_high_coverage_not_decreased():
    names = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert len(names) == 1091
    result = generate_batch(names)
    high_count = sum(
        1 for cands in result.values() if any(c.confidence == "high" for c in cands)
    )
    assert high_count >= 230, f"high 覆盖过低: {high_count}"


def test_known_low_confidence_now_fixed():
    expected = {
        "TRX-二头弯举": "SUSPENSION",
        "TRX-手枪深蹲": "SUSPENSION",
        "弹力带-深蹲": "BANDED_EXERCISES",
        "弹力带-侧平举": "BANDED_EXERCISES",
    }
    for name, cat in expected.items():
        cands = generate_candidates(name)
        assert cands, f"{name} 无候选"
        assert cands[0].garmin_category == cat, (
            f"{name} rank-1 期望 {cat}，实际 {cands[0].garmin_category}"
        )
