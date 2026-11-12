"""V6-9d 数据迁移：侧平举改为哑铃专用项 + 器械推胸补说明

2026-11-12 人工逐条复核 16 条 seed 映射时的结论：
- 「侧平举」原先映射到通用 `LATERAL_RAISE`（Garmin 会把 exerciseName 规范化成
  空串，只显示分类名 "Lateral Raise"）；用户确认为**站姿哑铃侧平举**，
  改为哑铃专用项 `DUMBBELL_LATERAL_RAISE`。
  新值尚未真机目视复验，故 verified_level 降为 `catalog`，并 bump
  mapping_version，使此前用旧值同步过的训练被判定为 stale。
- 「器械推胸」用户确认为**坐姿推胸机**；Garmin 目录没有器械推胸条目，
  维持通用 `BENCH_PRESS`，只补一条 note 说明原因。

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1) 侧平举：通用 → 哑铃专用（仅当仍是旧的通用值时改写，避免覆盖用户后来手工改的）
    conn.execute(
        sa.text(
            """
            UPDATE exercise_mapping
               SET garmin_exercise_name = 'DUMBBELL_LATERAL_RAISE',
                   garmin_display_name = 'Dumbbell Lateral Raise',
                   verified_level = 'catalog',
                   mapping_version = COALESCE(mapping_version, 1) + 1,
                   note = '2026-11-12 复核改为哑铃专用项，待真机目视复验'
            WHERE xunji_name = '侧平举'
              AND garmin_category = 'LATERAL_RAISE'
              AND (garmin_exercise_name IS NULL OR garmin_exercise_name = 'LATERAL_RAISE')
            """
        )
    )

    # 2) 器械推胸：维持通用 Bench Press，只补说明
    conn.execute(
        sa.text(
            """
            UPDATE exercise_mapping
               SET note = 'Garmin 无坐姿推胸机条目，用通用 Bench Press 表达（显示为分类名）'
            WHERE xunji_name = '器械推胸'
              AND garmin_category = 'BENCH_PRESS'
              AND (note IS NULL OR note LIKE 'seed from%')
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    # 逆操作：侧平举回通用项
    conn.execute(
        sa.text(
            """
            UPDATE exercise_mapping
               SET garmin_exercise_name = 'LATERAL_RAISE',
                   garmin_display_name = 'Lateral Raise',
                   verified_level = 'displayed',
                   mapping_version = COALESCE(mapping_version, 1) + 1,
                   note = 'seed from EXERCISE_WHITELIST, support_level=p3_verified'
            WHERE xunji_name = '侧平举'
              AND garmin_category = 'LATERAL_RAISE'
              AND garmin_exercise_name = 'DUMBBELL_LATERAL_RAISE'
            """
        )
    )

    conn.execute(
        sa.text(
            """
            UPDATE exercise_mapping
               SET note = 'seed from EXERCISE_WHITELIST, support_level=p2_verified'
            WHERE xunji_name = '器械推胸'
              AND note = 'Garmin 无坐姿推胸机条目，用通用 Bench Press 表达（显示为分类名）'
            """
        )
    )
