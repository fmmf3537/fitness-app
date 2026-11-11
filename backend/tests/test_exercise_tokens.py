"""exercise_tokens 静态词表契约测试（无 DB）。"""
from __future__ import annotations

from garminconnect import exercises

from app.services.exercise_tokens import (
    CARDIO_KEYWORDS,
    EQUIPMENT_TOKENS,
    FLEXIBILITY_KEYWORDS,
    MOVEMENT_KEYS_BY_LENGTH,
    MOVEMENT_TOKENS,
    PART_TO_GARMIN_CATEGORIES,
    POSTURE_TOKENS,
)


def test_part_categories_only_use_real_garmin_categories():
    real = set(exercises.CATEGORIES)
    for part, cats in PART_TO_GARMIN_CATEGORIES.items():
        for cat in cats:
            assert cat in real, f"{part} 含无效 category: {cat}"


def test_part_categories_covers_all_classify_part_outputs():
    required = {"胸", "背", "腿", "肩", "臂", "核心", "有氧", "其他"}
    assert required <= set(PART_TO_GARMIN_CATEGORIES.keys())


def test_high_frequency_equipment_tokens_present():
    for zh in ("哑铃", "杠铃", "绳索", "器械", "弹力带", "史密斯"):
        assert zh in EQUIPMENT_TOKENS
        assert EQUIPMENT_TOKENS[zh] == EQUIPMENT_TOKENS[zh].lower()


def test_high_frequency_movement_tokens_present():
    for zh in ("弯举", "划船", "深蹲", "卧推", "飞鸟", "臂屈伸", "卷腹", "硬拉"):
        assert zh in MOVEMENT_TOKENS


def test_movement_tokens_sorted_by_length_desc():
    lengths = [len(k) for k in MOVEMENT_KEYS_BY_LENGTH]
    assert lengths == sorted(lengths, reverse=True)
    assert len(MOVEMENT_TOKENS["罗马尼亚硬拉"]) > 0
    assert "硬拉" in MOVEMENT_TOKENS


def test_non_strength_keywords_non_empty():
    assert CARDIO_KEYWORDS
    assert FLEXIBILITY_KEYWORDS
    assert len(CARDIO_KEYWORDS) == len(set(CARDIO_KEYWORDS))
    assert len(FLEXIBILITY_KEYWORDS) == len(set(FLEXIBILITY_KEYWORDS))
    # 姿态/器械表也非空，防退化
    assert POSTURE_TOKENS
    assert EQUIPMENT_TOKENS
