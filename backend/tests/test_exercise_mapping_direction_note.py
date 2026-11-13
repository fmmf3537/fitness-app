"""V6-9h：方向一致性（后束≠胸）+ 器械不符 note 标注。"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.models import ExerciseMapping
from app.services import exercise_mapping_batch as batch_svc
from app.services.exercise_mapping import build_seed_rows
from app.services.exercise_mapping_candidates import (
    equipment_mismatch_note,
    generate_batch,
    generate_candidates,
)

DATA_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "data" / "xunji_movements.json"
)


def _all_names() -> list[str]:
    names = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert len(names) == 1091
    return names


# ---- 方向一致性（3）----


def test_rear_delt_not_chest_fly():
    cands = generate_candidates("TRX-后束飞鸟")
    assert cands
    assert all(c.garmin_exercise_name != "CHEST_FLY" for c in cands)
    assert all("CHEST" not in (c.garmin_exercise_name or "") for c in cands)


def test_rear_delt_gets_suspension_candidate():
    cands = generate_candidates("TRX-后束飞鸟")
    assert cands
    assert cands[0].garmin_category == "SUSPENSION"


def test_reverse_fly_unaffected():
    cands = generate_candidates("绳索交叉反向飞鸟")
    assert cands
    assert any("REVERSE" in (c.garmin_exercise_name or "") for c in cands)


# ---- 器械不符标注（4）----


def test_note_for_equipment_mismatch():
    note = equipment_mismatch_note(
        "下斜杠铃卧推", "Decline Dumbbell Bench Press"
    )
    assert note is not None
    assert "器械不符" in note


def test_note_none_when_equipment_matches():
    assert (
        equipment_mismatch_note("哑铃卧推", "Dumbbell Bench Press") is None
    )


def test_note_none_when_equipment_unspecified():
    assert equipment_mismatch_note("深蹲", "Barbell Back Squat") is None


def test_note_handles_synonyms():
    assert equipment_mismatch_note("绳索夹胸", "Cable Crossover") is None
    assert equipment_mismatch_note("龙门夹胸", "Cable Crossover") is None


# ---- 批处理落库（2）----


def test_batch_writes_mismatch_note(session, monkeypatch):
    monkeypatch.setattr(
        batch_svc, "_load_movement_names", lambda: ["下斜杠铃卧推"]
    )
    batch_svc.generate_all(session)
    row = session.scalars(
        select(ExerciseMapping).where(
            ExerciseMapping.xunji_name == "下斜杠铃卧推"
        )
    ).one()
    assert row.note is not None
    assert "器械不符" in row.note


def test_batch_clears_note_for_clean_mapping(session, monkeypatch):
    """器械相符的动作，note 必须为 None（不能误标「器械不符」）。

    注意：不能用「哑铃卧推」——它是 V6-1 的 16 条 seed 之一，`generate_all` 会
    跳过 active 行（note 保留 seed 文案）。改用「弹力带-深蹲」：非 seed，
    且 Garmin 条目 Banded Squat 的器械与中文一致。
    """
    monkeypatch.setattr(batch_svc, "_load_movement_names", lambda: ["弹力带-深蹲"])
    batch_svc.generate_all(session)
    row = session.scalars(
        select(ExerciseMapping).where(ExerciseMapping.xunji_name == "弹力带-深蹲")
    ).first()
    assert row is not None
    assert row.note is None, f"器械相符时不应有 note，实得 {row.note!r}"

def test_high_confidence_unchanged():
    result = generate_batch(_all_names())
    high_count = sum(
        1 for cands in result.values() if any(c.confidence == "high" for c in cands)
    )
    assert high_count >= 290, f"high collapsed: {high_count}"


def test_seed_rows_intact():
    rows = build_seed_rows()
    assert len(rows) == 16
    assert all(r["status"] == "active" for r in rows)
    assert all(r["verified_level"] == "displayed" for r in rows)


class TestEquipmentSynonyms:
    """两类器械判定假阳性（2026-11-13 P0-1 审核时实测发现并修复）。"""

    def test_ring_and_suspension_are_equivalent(self):
        """训记「吊环」→ ring，Garmin 写作 Suspension，是同一器械，不得判不符。

        修复前实测 12 条吊环动作被误标「器械不符」。
        """
        assert equipment_mismatch_note("吊环弯举", "Suspension Curl") is None
        assert equipment_mismatch_note("吊环反向飞鸟", "Suspension Chest Fly") is None

    def test_generic_root_inside_specific_root_is_not_mismatch(self):
        """`machine` 是 `smith machine` 的子串，不得把史密斯机条目误报为 machine。

        修复前实测 5 条史密斯动作被误标「器械不符：条目为 machine」。
        """
        assert equipment_mismatch_note("史密斯机卧推", "Smith Machine Bench Press") is None

    def test_genuine_mismatch_still_reported(self):
        """真器械不符必须保留标注（修复不得把真误判一起吞掉）。"""
        note = equipment_mismatch_note("下斜杠铃卧推", "Decline Dumbbell Bench Press")
        assert note is not None and "器械不符" in note
        note2 = equipment_mismatch_note("器械耸肩", "Barbell Jump Shrug")
        assert note2 is not None and "barbell" in note2
