"""ADR-P2-2：新增 exercise_mapping_review（AI 只读审核结果表）

AI 只作为只读审核员，不直接改变 active 映射；结果单独落表，
供人工/规则确认后再进入正式映射（ADR §11）。

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exercise_mapping_review",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mapping_id", sa.Integer(), nullable=True),
        sa.Column("xunji_name", sa.String(length=200), nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("suggested_category", sa.String(length=64), nullable=True),
        sa.Column("suggested_exercise_name", sa.String(length=128), nullable=True),
        sa.Column("suggested_display_name", sa.String(length=200), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("batch_id", sa.String(length=64), nullable=True),
        sa.Column(
            "resolved",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_exercise_mapping_review_mapping_id",
        "exercise_mapping_review",
        ["mapping_id"],
    )
    op.create_index(
        "ix_exercise_mapping_review_xunji_name",
        "exercise_mapping_review",
        ["xunji_name"],
    )
    op.create_index(
        "ix_exercise_mapping_review_batch_id",
        "exercise_mapping_review",
        ["batch_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_exercise_mapping_review_batch_id",
        table_name="exercise_mapping_review",
    )
    op.drop_index(
        "ix_exercise_mapping_review_xunji_name",
        table_name="exercise_mapping_review",
    )
    op.drop_index(
        "ix_exercise_mapping_review_mapping_id",
        table_name="exercise_mapping_review",
    )
    op.drop_table("exercise_mapping_review")
