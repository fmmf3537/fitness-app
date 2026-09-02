"""skinfold_record 表 + settings 性别 / 出生日期字段（V4-3 皮脂钳体脂率）

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa


revision = "a6b7c8d9e0f1"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skinfold_record",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("sites_json", sa.Text(), nullable=False),
        sa.Column("density", sa.Float(), nullable=False),
        sa.Column("bodyfat_result", sa.Float(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("date", "method", name="uq_skinfold_record_date_method"),
    )
    op.add_column(
        "settings",
        sa.Column("gender", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "settings",
        sa.Column("birth_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("settings", "birth_date")
    op.drop_column("settings", "gender")
    op.drop_table("skinfold_record")