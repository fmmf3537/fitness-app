"""V6-9g：限定词一致性 / 史密斯排除 / 夹胸同义展开回归。"""
from __future__ import annotations

import json
from pathlib import Path

from app.services.exercise_mapping_candidates import (
    classify_applicability,
    generate_batch,
    generate_candidates,
)
from app.services.exercise_tokens import CARDIO_ONLY_CATEGORIES

DATA_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "data" / "xunji_movements.json"
)


def _all_names() -> list[str]:
    names = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert len(names) == 1091
    return names


def _top(name: str):
    cands = generate_candidates(name)
    assert cands, f"expected candidates for {name!r}"
    return cands[0]


# ---- 夹胸类（4）----


def test_cable_crossover_not_reverse_fly():
    top = _top("绳索夹胸")
    assert top.garmin_exercise_name == "CABLE_CROSSOVER"


def test_cable_cross_cable_fly():
    top = _top("绳索十字夹胸")
    assert top.garmin_exercise_name == "CABLE_CROSSOVER"


def test_reverse_fly_penalized_without_reverse():
    top = _top("绳索夹胸")
    assert "REVERSE_FLYE" not in top.garmin_exercise_name
    assert "REVERSE" not in top.garmin_exercise_name


def test_reverse_fly_kept_when_reverse_asked():
    top = _top("绳索交叉反向飞鸟")
    assert "REVERSE" in top.garmin_exercise_name


# ---- 单侧限定（4）----


def test_standing_calf_raise_not_single_leg():
    top = _top("站姿自重提踵")
    assert "SINGLE" not in top.garmin_exercise_name


def test_single_arm_kept_when_asked():
    top = _top("单手绳索臂屈伸")
    name = top.garmin_exercise_name
    assert "SINGLE" in name or "ONE_ARM" in name


def test_cable_lateral_raise_not_one_arm():
    """Garmin 目录里**没有**双臂绳索侧平举，只有 ONE_ARM_CABLE_LATERAL_RAISE。

    因此不能要求「换到别的动作」，只能要求 R1 把它的置信度压下来
    （从 high 降到 medium/low），避免把「单臂」当成确定映射直接采纳。
    """
    cands = generate_candidates("绳索侧平举")
    assert cands
    top = cands[0]
    if "ONE_ARM" in (top.garmin_exercise_name or "") or "SINGLE_ARM" in (
        top.garmin_exercise_name or ""
    ):
        assert top.confidence != "high", "中文未要求单臂时不应给出 high 置信度"

def test_seated_kept_when_asked():
    top = _top("坐姿绳索划船")
    name = top.garmin_exercise_name
    if "SEATED" in name:
        return
    assert top.garmin_category == "ROW"
    assert "STANDING" not in name


# ---- 史密斯（3）----


def test_machine_shrug_not_smith():
    cands = generate_candidates("器械耸肩")
    assert cands
    assert all("SMITH" not in c.garmin_exercise_name for c in cands)


def test_smith_kept_when_asked():
    """中文含「史密斯」时，smith 条目不得被 R2 排除。

    注意：不能用「史密斯机推举」验证——Garmin 的 Smith Machine Overhead Press
    写作 "overhead press"，不含 shoulder press 词根，生成器本来就找不到它
    （那条映射是 P3 人工确认的 seed，不是算法结果）。
    改用「史密斯机卧推」：Smith Machine Bench Press 含 bench press，能真正命中。
    """
    cands = generate_candidates("史密斯机卧推")
    assert cands
    assert any("SMITH" in (c.garmin_exercise_name or "") for c in cands), (
        f"含「史密斯」的动作应能命中 smith 条目，实得 "
        f"{[c.garmin_exercise_name for c in cands]}"
    )

def test_smith_excluded_for_hummer():
    cands = generate_candidates("悍马机卧推")
    assert cands
    assert all("SMITH" not in c.garmin_exercise_name for c in cands)


# ---- 姿态与器械保持（3，防回退）----


def test_incline_still_preferred():
    top = _top("上斜哑铃卧推")
    assert "INCLINE" in top.garmin_exercise_name


def test_wrist_curl_still_correct():
    top = _top("正手杠铃手腕弯举")
    assert "WRIST" in top.garmin_exercise_name


def test_leg_abduction_still_correct():
    top = _top("弹力带-腿外展")
    assert "LEG" in top.garmin_exercise_name


# ---- 全量回归（3）----


def test_no_cardio_categories():
    names = _all_names()
    strength = [n for n in names if classify_applicability(n)[0]]
    for n in strength:
        for c in generate_candidates(n):
            assert c.garmin_category not in CARDIO_ONLY_CATEGORIES, (
                f"{n!r} -> {c.garmin_category}"
            )


def test_high_not_collapsed():
    result = generate_batch(_all_names())
    high_count = sum(
        1 for cands in result.values() if any(c.confidence == "high" for c in cands)
    )
    assert high_count >= 250, f"high collapsed: {high_count}"


def test_strength_coverage_not_below_85pct():
    names = _all_names()
    result = generate_batch(names)
    strength = [n for n in names if classify_applicability(n)[0]]
    with_cands = sum(1 for n in strength if result[n])
    ratio = with_cands / len(strength) if strength else 0.0
    assert ratio >= 0.85, f"strength coverage {ratio:.1%} < 85%"
