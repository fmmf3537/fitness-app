"""训记→Garmin 动作映射表 + garmin_plan_sync.mapping_hash（V6-1）

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-11-11
"""
from alembic import op
import sqlalchemy as sa


revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exercise_mapping",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("xunji_name", sa.String(length=200), nullable=False),
        sa.Column("garmin_category", sa.String(length=64), nullable=True),
        sa.Column("garmin_exercise_name", sa.String(length=128), nullable=True),
        sa.Column("garmin_display_name", sa.String(length=200), nullable=True),
        sa.Column("weight_strategy", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("not_applicable_reason", sa.String(length=100), nullable=True),
        sa.Column("confidence", sa.String(length=10), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=True),
        sa.Column("verified_level", sa.String(length=20), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column(
            "mapping_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("xunji_name", name="uq_exercise_mapping_xunji_name"),
    )
    op.create_table(
        "exercise_mapping_candidate",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("xunji_name", sa.String(length=200), nullable=False),
        sa.Column("garmin_category", sa.String(length=64), nullable=False),
        sa.Column("garmin_exercise_name", sa.String(length=128), nullable=True),
        sa.Column("garmin_display_name", sa.String(length=200), nullable=True),
        sa.Column("confidence", sa.String(length=10), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "exercise_mapping_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mapping_id", sa.Integer(), nullable=False),
        sa.Column("xunji_name", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=True),
        sa.Column("after_json", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )
    # SQLite：可空列可直接 add_column，无需 batch
    op.add_column(
        "garmin_plan_sync",
        sa.Column("mapping_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("garmin_plan_sync", "mapping_hash")
    op.drop_table("exercise_mapping_audit")
    op.drop_table("exercise_mapping_candidate")
    op.drop_table("exercise_mapping")
