"""coach 长期记忆 4 表 + settings.memory_default_provider（V5-1）

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa


revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coach_preference",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=True),
        sa.Column("tags", sa.String(length=200), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=True),
        sa.Column(
            "active", sa.Boolean(), server_default="1", nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "coach_preference_draft",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags", sa.String(length=200), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "coach_memory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("tags", sa.String(length=200), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=True),
        sa.Column("ref_report_id", sa.Integer(), nullable=True),
        sa.Column("ref_chat_id", sa.Integer(), nullable=True),
        sa.Column(
            "active", sa.Boolean(), server_default="1", nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "coach_chat_message",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_estimate", sa.Float(), nullable=True),
        sa.Column("client_request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "client_request_id", name="uq_coach_chat_message_crid"
        ),
    )
    op.add_column(
        "settings",
        sa.Column("memory_default_provider", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("settings", "memory_default_provider")
    op.drop_table("coach_chat_message")
    op.drop_table("coach_memory")
    op.drop_table("coach_preference_draft")
    op.drop_table("coach_preference")
