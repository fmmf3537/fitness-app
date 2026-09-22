"""coach_chat_message 保存回答依据

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa


revision = "d9e0f1a2b3c4"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("coach_chat_message") as batch_op:
        batch_op.add_column(sa.Column("context_refs_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("coach_chat_message") as batch_op:
        batch_op.drop_column("context_refs_json")
