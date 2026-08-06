"""backfill_progress 表（V1-2 历史导入断点续传）

Revision ID: c2d3e4f5a6b7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa

revision = "c2d3e4f5a6b7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backfill_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("date", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", "date", name="uq_backfill_progress_source_date"),
    )


def downgrade() -> None:
    op.drop_table("backfill_progress")
