"""V6-9e 数据迁移：侧平举真机目视复验通过，verified_level 升回 displayed

2026-11-12：把「侧平举」从通用 `LATERAL_RAISE` 改为哑铃专用项
`DUMBBELL_LATERAL_RAISE` 后，同日真机目视确认 —— Garmin Connect 显示
「哑铃侧平举」（Dumbbell Lateral Raise），端到端验证通过。

因此把该行的 `verified_level` 从 `catalog` 升回 `displayed`。

**不 bump mapping_version**：映射值本身没有变化（仍是 DUMBBELL_LATERAL_RAISE），
只有验证级别提升，不应让历史同步被重新判定为 stale。

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f8a9b0c1d2e3"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None

_NOTE = "2026-11-12 复核改为哑铃专用项；同日真机目视确认 Connect 显示「哑铃侧平举」"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE exercise_mapping
               SET verified_level = 'displayed',
                   verified_at = CURRENT_TIMESTAMP,
                   note = :note
            WHERE xunji_name = '侧平举'
              AND garmin_category = 'LATERAL_RAISE'
              AND garmin_exercise_name = 'DUMBBELL_LATERAL_RAISE'
            """
        ),
        {"note": _NOTE},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE exercise_mapping
               SET verified_level = 'catalog',
                   verified_at = NULL,
                   note = '2026-11-12 复核改为哑铃专用项，待真机目视复验'
            WHERE xunji_name = '侧平举'
              AND garmin_category = 'LATERAL_RAISE'
              AND garmin_exercise_name = 'DUMBBELL_LATERAL_RAISE'
            """
        )
    )
