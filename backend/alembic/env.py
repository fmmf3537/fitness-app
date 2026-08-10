"""Alembic 环境：URL 优先取 -x/配置覆盖，其次取环境变量 DATABASE_URL，最后取 app.config 默认值。"""
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings, resolve_database_url  # noqa: E402
from app.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    # 与 make_engine 同源锚定：-x/配置覆盖给出的相对 URL 也锚定到项目根目录。
    # -x url=... 优先级最高：可穿透根目录 .env 的 override=True（config.py 会让
    # .env 盖掉 OS 环境变量 DATABASE_URL，测试/运维需要显式指定目标库时使用）
    x_args = context.get_x_argument(as_dictionary=True)
    override = x_args.get("url") or config.get_main_option("sqlalchemy.url")
    if override:
        return resolve_database_url(override)
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
