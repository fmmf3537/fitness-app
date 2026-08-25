"""add user_id to business tables (M1-3)

multiuser-v2 M1-3：11 张业务表新增 user_id（FK→users.id，全部 nullable），
并将相关 UNIQUE 约束调整为包含 user_id 的复合唯一，作为"每用户一份数据"
多租户隔离的地基。

要点：
- user_id 全部 nullable：M1-4（创建默认管理员并回填存量 user_id）尚未执行，
  存量行以 user_id=NULL 平滑升级；是否收紧为 NOT NULL 由 M1-4 决定。
- 不在本迁移中回填存量 user_id（那是 M1-4 的职责）。
- 全部使用 op.batch_alter_table，SQLite 下重建表复制数据，存量不丢；
  PG 下等价于常规 ALTER。
- garmin_activity.activity_id / garmin_daily.date 原为"列级 unique"：
  PG 上自动命名为 <table>_<column>_key，可按名 drop；SQLite 上是无名约束
  （sqlite_autoindex），无法按名 drop，改用"反射 + 剔除该约束后的 copy_from"
  让 batch 重建的新表不再携带它。
- report_chat_message 上 DB 存量的 ix_report_chat_message_report_id 索引
  （模型未声明）保持不变，本迁移不做任何调整。

Revision ID: a0593c2c6cf2
Revises: a7b8c9d0e1f2
Create Date: 2026-08-24 11:14:02.157101

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a0593c2c6cf2'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _reflect_without_single_col_unique(table_name: str, column_name: str) -> sa.Table:
    """SQLite 专用：反射现有表，并剔除指定单列上的 UNIQUE 约束。

    SQLite 的列级 unique 落成无名约束（sqlite_autoindex），batch 的
    drop_constraint 必须有名字，无法按名 drop；把剔除该约束后的反射表
    作为 copy_from 传给 batch_alter_table，重建出的新表即不再携带它。
    按列匹配而非按名匹配：downgrade 回滚重建的是同列命名约束，再次
    upgrade 时同样可以被剔除，保证迁移可反复往返。
    """
    bind = op.get_bind()
    metadata = sa.MetaData()
    reflected = sa.Table(table_name, metadata, autoload_with=bind)
    for const in list(reflected.constraints):
        if (
            isinstance(const, sa.UniqueConstraint)
            and [c.name for c in const.columns] == [column_name]
        ):
            reflected.constraints.discard(const)
    return reflected


def upgrade() -> None:
    is_sqlite = op.get_bind().dialect.name == "sqlite"

    # 1. xunji_train：UNIQUE(datestr, localid) -> UNIQUE(user_id, datestr, localid)
    with op.batch_alter_table('xunji_train') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.drop_constraint('uq_xunji_train_datestr_localid', type_='unique')
        batch_op.create_unique_constraint(
            'uq_xunji_train_user_datestr_localid', ['user_id', 'datestr', 'localid']
        )
        batch_op.create_foreign_key(
            'fk_xunji_train_user_id_users', 'users', ['user_id'], ['id']
        )

    # 2. garmin_activity：列级 unique(activity_id) -> UNIQUE(user_id, activity_id)
    ga_kwargs = {}
    if is_sqlite:
        ga_kwargs['copy_from'] = _reflect_without_single_col_unique('garmin_activity', 'activity_id')
    with op.batch_alter_table('garmin_activity', **ga_kwargs) as batch_op:
        if not is_sqlite:
            batch_op.drop_constraint('garmin_activity_activity_id_key', type_='unique')
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_unique_constraint(
            'uq_garmin_activity_user_activity_id', ['user_id', 'activity_id']
        )
        batch_op.create_foreign_key(
            'fk_garmin_activity_user_id_users', 'users', ['user_id'], ['id']
        )

    # 3. garmin_daily：列级 unique(date) -> UNIQUE(user_id, date)
    gd_kwargs = {}
    if is_sqlite:
        gd_kwargs['copy_from'] = _reflect_without_single_col_unique('garmin_daily', 'date')
    with op.batch_alter_table('garmin_daily', **gd_kwargs) as batch_op:
        if not is_sqlite:
            batch_op.drop_constraint('garmin_daily_date_key', type_='unique')
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_unique_constraint('uq_garmin_daily_user_date', ['user_id', 'date'])
        batch_op.create_foreign_key(
            'fk_garmin_daily_user_id_users', 'users', ['user_id'], ['id']
        )

    # 4. body_metric：UNIQUE(date, type) -> UNIQUE(user_id, date, type)
    with op.batch_alter_table('body_metric') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.drop_constraint('uq_body_metric_date_type', type_='unique')
        batch_op.create_unique_constraint(
            'uq_body_metric_user_date_type', ['user_id', 'date', 'type']
        )
        batch_op.create_foreign_key(
            'fk_body_metric_user_id_users', 'users', ['user_id'], ['id']
        )

    # 5. workout：仅加列 + user_id 索引，无 UNIQUE 变更
    with op.batch_alter_table('workout') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_workout_user_id_users', 'users', ['user_id'], ['id']
        )
        batch_op.create_index('ix_workout_user_id', ['user_id'], unique=False)

    # 6. match_candidate：仅加列
    with op.batch_alter_table('match_candidate') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_match_candidate_user_id_users', 'users', ['user_id'], ['id']
        )

    # 7. xunji_plan：加列 + 新建 UNIQUE(user_id, plan_ref)
    with op.batch_alter_table('xunji_plan') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_unique_constraint(
            'uq_xunji_plan_user_plan_ref', ['user_id', 'plan_ref']
        )
        batch_op.create_foreign_key(
            'fk_xunji_plan_user_id_users', 'users', ['user_id'], ['id']
        )

    # 8. ai_report：加列 + 复合索引 (user_id, type, period_start)
    with op.batch_alter_table('ai_report') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_ai_report_user_id_users', 'users', ['user_id'], ['id']
        )
        batch_op.create_index(
            'ix_ai_report_user_type_period',
            ['user_id', 'type', 'period_start'],
            unique=False,
        )

    # 9. llm_call：仅加列
    with op.batch_alter_table('llm_call') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_llm_call_user_id_users', 'users', ['user_id'], ['id']
        )

    # 10. job_run：仅加列（user_id 为 NULL 表示系统级任务）
    with op.batch_alter_table('job_run') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_job_run_user_id_users', 'users', ['user_id'], ['id']
        )

    # 11. report_chat_message：仅加列，不动既有 uq_report_chat_message_client_request_id
    with op.batch_alter_table('report_chat_message') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_report_chat_message_user_id_users', 'users', ['user_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('report_chat_message') as batch_op:
        batch_op.drop_constraint('fk_report_chat_message_user_id_users', type_='foreignkey')
        batch_op.drop_column('user_id')

    with op.batch_alter_table('job_run') as batch_op:
        batch_op.drop_constraint('fk_job_run_user_id_users', type_='foreignkey')
        batch_op.drop_column('user_id')

    with op.batch_alter_table('llm_call') as batch_op:
        batch_op.drop_constraint('fk_llm_call_user_id_users', type_='foreignkey')
        batch_op.drop_column('user_id')

    with op.batch_alter_table('ai_report') as batch_op:
        batch_op.drop_index('ix_ai_report_user_type_period')
        batch_op.drop_constraint('fk_ai_report_user_id_users', type_='foreignkey')
        batch_op.drop_column('user_id')

    with op.batch_alter_table('xunji_plan') as batch_op:
        batch_op.drop_constraint('fk_xunji_plan_user_id_users', type_='foreignkey')
        batch_op.drop_constraint('uq_xunji_plan_user_plan_ref', type_='unique')
        batch_op.drop_column('user_id')

    with op.batch_alter_table('match_candidate') as batch_op:
        batch_op.drop_constraint('fk_match_candidate_user_id_users', type_='foreignkey')
        batch_op.drop_column('user_id')

    with op.batch_alter_table('workout') as batch_op:
        batch_op.drop_index('ix_workout_user_id')
        batch_op.drop_constraint('fk_workout_user_id_users', type_='foreignkey')
        batch_op.drop_column('user_id')

    with op.batch_alter_table('body_metric') as batch_op:
        batch_op.drop_constraint('fk_body_metric_user_id_users', type_='foreignkey')
        batch_op.drop_constraint('uq_body_metric_user_date_type', type_='unique')
        batch_op.create_unique_constraint('uq_body_metric_date_type', ['date', 'type'])
        batch_op.drop_column('user_id')

    with op.batch_alter_table('garmin_daily') as batch_op:
        batch_op.drop_constraint('fk_garmin_daily_user_id_users', type_='foreignkey')
        batch_op.drop_constraint('uq_garmin_daily_user_date', type_='unique')
        # 恢复单列唯一（沿用 PG 默认命名 <table>_<column>_key，SQLite 下亦可用名）
        batch_op.create_unique_constraint('garmin_daily_date_key', ['date'])
        batch_op.drop_column('user_id')

    with op.batch_alter_table('garmin_activity') as batch_op:
        batch_op.drop_constraint('fk_garmin_activity_user_id_users', type_='foreignkey')
        batch_op.drop_constraint('uq_garmin_activity_user_activity_id', type_='unique')
        batch_op.create_unique_constraint('garmin_activity_activity_id_key', ['activity_id'])
        batch_op.drop_column('user_id')

    with op.batch_alter_table('xunji_train') as batch_op:
        batch_op.drop_constraint('fk_xunji_train_user_id_users', type_='foreignkey')
        batch_op.drop_constraint('uq_xunji_train_user_datestr_localid', type_='unique')
        batch_op.create_unique_constraint('uq_xunji_train_datestr_localid', ['datestr', 'localid'])
        batch_op.drop_column('user_id')
