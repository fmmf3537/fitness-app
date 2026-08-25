"""settings per-user (multiuser-v2 M1-2)

settings 由「单用户单行」改为「每用户一行」：
- alter_column 改名 garmin_token_store -> garmin_token_store_enc（保留已有数据）
- 新增列 user_id(nullable+unique 索引)/garmin_email_enc/garmin_password_enc/
  xunji_body_api_key_enc/leaderboard_opt_out_json/updated_at
- user_id 允许 NULL：M1-4 才创建默认管理员并回填存量行

Revision ID: a7b8c9d0e1f2
Revises: 1f0d04e38eb5
Create Date: 2026-08-24 10:04:07.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = '1f0d04e38eb5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch 模式兼容 SQLite（重建表复制数据，已有 settings 行不丢失），PG 下等价于常规 ALTER
    with op.batch_alter_table('settings') as batch_op:
        batch_op.alter_column('garmin_token_store', new_column_name='garmin_token_store_enc')
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('garmin_email_enc', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('garmin_password_enc', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('xunji_body_api_key_enc', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('leaderboard_opt_out_json', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(),
                                      server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False))
        batch_op.create_foreign_key('fk_settings_user_id_users', 'users', ['user_id'], ['id'])
        batch_op.create_index('ix_settings_user_id', ['user_id'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('settings') as batch_op:
        batch_op.drop_index('ix_settings_user_id')
        batch_op.drop_constraint('fk_settings_user_id_users', type_='foreignkey')
        batch_op.drop_column('updated_at')
        batch_op.drop_column('leaderboard_opt_out_json')
        batch_op.drop_column('xunji_body_api_key_enc')
        batch_op.drop_column('garmin_password_enc')
        batch_op.drop_column('garmin_email_enc')
        batch_op.drop_column('user_id')
        batch_op.alter_column('garmin_token_store_enc', new_column_name='garmin_token_store')
