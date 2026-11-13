"""ADR §11 golden regression：已确认真实错例的固定回归集。

每一条都来自线上真实抽查或用户目视确认，**不是构造的假想错误**。
无论后续修改规则、词表、候选池、提示词或 AI 模型，这些断言都必须继续通过。

维护约定：
- 新增确认错例时，在这里追加一条断言（并在文件头注释里写明来源与日期），
  而不是只改提示词或只调规则；
- 断言分两层：
    1. **排除断言**：这次错配的形态绝不能再出现（如「绳索夹胸 → REVERSE_FLY」）；
    2. **正向断言**：应当选中什么（允许随目录演进调整，但要写明理由）。

五类之外第 6 条：侧躺腿外展应命中 Leg Raise（2026-11-13 AI 审核发现）。
"""

from __future__ import annotations

import pytest

from app.services.exercise_mapping_candidates import (
    CARDIO_ONLY_CATEGORIES,
    generate_candidates,
)
from app.services.exercise_mapping_relation import RELATION_EXACT, classify_relation
from types import SimpleNamespace


def _ex_names(name: str) -> list[str]:
    return [c.garmin_exercise_name or "" for c in generate_candidates(name)]


def _categories(name: str) -> list[str]:
    return [c.garmin_category or "" for c in generate_candidates(name)]


def _top(name: str):
    cands = generate_candidates(name)
    assert cands, f"{name} 应至少有一个候选"
    return cands[0]


class TestGoldenRegressions:
    """ADR §11 列出的五类已确认错例。"""

    def test_case1_strength_row_never_maps_to_cardio_rower(self):
        """① 力量器械划船不得进入有氧划船机分类（2026-11-12 线上抽查）。

        历史错配：器械划船1 → ROW/INDOOR_ROW（Rowing Machine 是有氧器械）。
        """
        assert "INDOOR_ROW" not in _ex_names("器械划船1")
        # 更强的全局断言：任何力量动作的候选都不得落在有氧分类里
        for cat in _categories("器械划船1"):
            assert cat not in CARDIO_ONLY_CATEGORIES

    def test_case2_cable_chest_fly_never_maps_to_reverse_fly(self):
        """② 绳索夹胸不得映射为训练后束的反向飞鸟（2026-11-13 修复）。

        历史错配：绳索夹胸 → FLYE/SINGLE_ARM_STANDING_CABLE_REVERSE_FLYE。
        reverse fly 练后束、夹胸练胸，是方向相反的两个动作。
        """
        assert not any("REVERSE_FLYE" in ex for ex in _ex_names("绳索夹胸"))
        assert _top("绳索夹胸").garmin_exercise_name == "CABLE_CROSSOVER"

    def test_case3_ring_curl_never_maps_to_hamstring_curl(self):
        """③ 吊环弯举不得映射为腿弯举（2026-11-13 修复）。

        历史错配：吊环弯举 → SUSPENSION/HAMSTRING_CURL。
        """
        assert not any("HAMSTRING" in ex for ex in _ex_names("吊环弯举"))

    @pytest.mark.parametrize(
        ("name", "expected_token"),
        [
            ("上斜哑铃卧推", "INCLINE"),
            ("下斜杠铃卧推", "DECLINE"),
        ],
    )
    def test_case4_posture_never_silently_dropped(self, name, expected_token):
        """④ 上斜/下斜等姿态不得被静默当作完全等价（2026-11-13 修复）。

        历史错配：上斜哑铃卧推 → DUMBBELL_BENCH_PRESS（丢了 incline）；
        下斜杠铃卧推 → BARBELL_BENCH_PRESS（丢了 decline）。
        """
        assert expected_token in _top(name).garmin_exercise_name

    def test_case5_rear_delt_fly_never_maps_to_chest_fly(self):
        """⑤ TRX 后束飞鸟不得映射为 Chest Fly（2026-11-13 修复）。

        历史错配：TRX-后束飞鸟 → SUSPENSION/CHEST_FLY。
        后束在背侧，Chest Fly 打前侧胸肌，方向相反。
        """
        assert not any("CHEST_FLY" in ex for ex in _ex_names("TRX-后束飞鸟"))
        assert _top("TRX-后束飞鸟").garmin_category == "SUSPENSION"

    def test_case6_side_lying_leg_abduction_uses_leg_raise(self):
        """⑥ 弹力带侧躺腿外展须能命中 Band Side-lying Leg Raise（2026-11-13 AI 审核）。

        结构缺口：Garmin 叫 Leg Raise 不叫 Abduction；仅靠「外展→abduction」永远找不到。
        断言「候选里存在」而非 rank-1，避免被同名条目排序影响。
        """
        assert "BAND_SIDE_LYING_LEG_RAISE" in _ex_names("弹力带侧躺腿外展")

    def test_case6_regression_plain_leg_abduction_unchanged(self):
        """⑥ 回归：无「侧躺」的腿外展不得被复合词条污染为 SIDE_LYING。"""
        top = _top("弹力带-腿外展")
        assert "LEG" in top.garmin_exercise_name
        assert "SIDE_LYING" not in top.garmin_exercise_name


class TestRegressionAdjacentCoverage:
    """与 golden 错例同源、容易一起回归的邻近场景。"""

    def test_reverse_fly_still_available_when_asked(self):
        """中文明确写「反向」时必须仍能命中 reverse fly——修复不得矫枉过正。"""
        assert any("REVERSE_FLYE" in ex for ex in _ex_names("绳索交叉反向飞鸟"))

    def test_wrist_curl_not_biceps_curl(self):
        """手腕弯举 ≠ 二头弯举（V6-9f 修复）。"""
        top = _top("正手杠铃手腕弯举")
        assert "WRIST" in top.garmin_exercise_name
        assert "BICEPS" not in top.garmin_exercise_name

    def test_leg_abduction_not_shoulder_rotation(self):
        """腿外展 ≠ 肩外旋（V6-9f 修复）。"""
        top = _top("弹力带-腿外展")
        assert "LEG" in top.garmin_exercise_name or "HIP" in top.garmin_exercise_name
        assert "EXTERNAL_ROTATION" not in top.garmin_exercise_name

    def test_pull_down_hyphen_normalisation(self):
        """`_norm` 必须抹掉连字符，否则 "Lat Pull-down" 永远匹配不到 pulldown（V6-9c 教训）。"""
        assert any("PULLDOWN" in ex for ex in _ex_names("宽距高位下拉"))

    def test_no_candidate_returns_empty_not_wrong_guess(self):
        """确实无对应的动作应返回空列表，而不是硬塞一个近似项。"""
        assert generate_candidates("腿部拉伸") == []


class TestRelationClassificationGolden:
    """relation 分类的 golden 断言（ADR §10.1 判据，两个陷阱各一条）。"""

    def _row(self, name: str, top, source: str = "auto"):
        return SimpleNamespace(
            xunji_name=name,
            status="draft",
            garmin_category=top.garmin_category,
            garmin_exercise_name=top.garmin_exercise_name,
            garmin_display_name=top.garmin_display_name,
            source=source,
        )

    def test_equipment_mismatch_is_similar(self):
        """器械不符 → SIMILAR（下斜杠铃卧推只有哑铃版可选）。"""
        name = "下斜杠铃卧推"
        assert classify_relation(self._row(name, _top(name)))[0] == "SIMILAR"

    def test_no_posture_words_is_not_similar(self):
        """陷阱①：没有姿态词的动作不得因为「没触发全命中 +40」被判 SIMILAR。"""
        name = "哑铃卧推"
        assert classify_relation(self._row(name, _top(name)))[0] == RELATION_EXACT

    def test_ring_and_suspension_are_same_equipment(self):
        """陷阱②：吊环(ring) 与 Suspension 是同一器械，不得被判器械不符。"""
        name = "吊环弯举"
        row = self._row(name, _top(name))
        assert classify_relation(row)[0] == RELATION_EXACT, (
            "吊环→ring 与 Garmin 的 Suspension 是同一器械，判成 SIMILAR 会让"
            "正确的吊环动作被标为有损映射"
        )
