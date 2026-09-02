"""workout_set_hr 表（V4-7 逐组心率）

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa


revision = "b7c8d9e0f1a2"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workout_set_hr",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workout_id", sa.Integer(), sa.ForeignKey("workout.id"), nullable=False),
        sa.Column("movement_name", sa.String(length=100), nullable=False),
        sa.Column("set_index", sa.Integer(), nullable=False),
        sa.Column("hr_avg", sa.Integer(), nullable=True),
        sa.Column("hr_max", sa.Integer(), nullable=True),
        sa.Column("hr_min", sa.Integer(), nullable=True),
        sa.Column("hr_recovery_30s", sa.Integer(), nullable=True),
        sa.Column("set_start", sa.DateTime(), nullable=True),
        sa.Column("set_end", sa.DateTime(), nullable=True),
        sa.Column("confidence", sa.String(length=10), nullable=False),
        sa.Column("match_method", sa.String(length=30), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "workout_id", "movement_name", "set_index",
            name="uq_workout_set_hr_wms",
        ),
    )


def downgrade() -> None:
    op.drop_table("workout_set_hr")