"""add auth_token

multiuser-v2 M2-3：新增 auth_token 登录令牌表（user_id FK→users.id ON DELETE CASCADE，
token 唯一索引，expires_at 过期时间，is_active 软失效标记）。

注意：autogenerate 曾误检 report_chat_message 上 DB 存量的
ix_report_chat_message_report_id 索引（模型未声明）为"待删除"，已手工剔除，
本迁移只含 auth_token 表的建/删，不动其他任何表（同 M1-3 注释约定）。

Revision ID: 55163cf925d2
Revises: a0593c2c6cf2
Create Date: 2026-08-24 12:52:52.860454

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '55163cf925d2'
down_revision: Union[str, None] = 'a0593c2c6cf2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'auth_token',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_auth_token_token'), 'auth_token', ['token'], unique=True)
    op.create_index(op.f('ix_auth_token_user_id'), 'auth_token', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_auth_token_user_id'), table_name='auth_token')
    op.drop_index(op.f('ix_auth_token_token'), table_name='auth_token')
    op.drop_table('auth_token')
