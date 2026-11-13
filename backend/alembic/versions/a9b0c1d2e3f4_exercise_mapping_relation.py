"""ADR-P0-1：exercise_mapping 增加 relation / match_basis / unmapped_reason

把「映射成什么」与「这个决定有多可靠」拆成独立维度（ADR §4.1）。
本迁移只加可空列，不跑回填；存量回填走应用侧幂等端点
`POST /api/exercise-mappings/backfill-relations`。

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a9b0c1d2e3f4"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exercise_mapping",
        sa.Column("relation", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "exercise_mapping",
        sa.Column("match_basis", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "exercise_mapping",
        sa.Column("unmapped_reason", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("exercise_mapping", "unmapped_reason")
    op.drop_column("exercise_mapping", "match_basis")
    op.drop_column("exercise_mapping", "relation")
