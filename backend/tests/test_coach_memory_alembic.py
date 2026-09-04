"""V5-1：coach 记忆表 + settings.memory_default_provider 迁移 roundtrip。"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parents[1]

COACH_TABLES = {
    "coach_preference",
    "coach_preference_draft",
    "coach_memory",
    "coach_chat_message",
}


def _make_config(db_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_coach_memory_tables_and_settings_column_roundtrip(tmp_path):
    """升级 head 后 4 表 + 列存在；显式回退 b7c8d9e0f1a2 后消失；再升级恢复。"""
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    tables = set(insp.get_table_names())
    assert COACH_TABLES <= tables
    settings_cols = {c["name"] for c in insp.get_columns("settings")}
    assert "memory_default_provider" in settings_cols

    command.downgrade(cfg, "b7c8d9e0f1a2")
    insp = inspect(create_engine(db_url))
    tables = set(insp.get_table_names())
    assert COACH_TABLES.isdisjoint(tables)
    settings_cols = {c["name"] for c in insp.get_columns("settings")}
    assert "memory_default_provider" not in settings_cols

    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    tables = set(insp.get_table_names())
    assert COACH_TABLES <= tables
    settings_cols = {c["name"] for c in insp.get_columns("settings")}
    assert "memory_default_provider" in settings_cols
