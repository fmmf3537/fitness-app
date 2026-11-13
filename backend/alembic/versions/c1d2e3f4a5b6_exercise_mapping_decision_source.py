"""ADR-P0-4：exercise_mapping 增加 decision_source

记录谁提出/接受了映射决策（rule / ai / human / human_policy）。
与 source（谁生成的候选：seed/auto/llm/manual）是两件事，不可混用（ADR §4.1）。

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "b0c1d2e3f4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exercise_mapping",
        sa.Column("decision_source", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("exercise_mapping", "decision_source")
