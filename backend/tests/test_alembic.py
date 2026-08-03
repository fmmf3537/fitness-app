"""Alembic 初始迁移 upgrade/downgrade 往返测试。"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "settings",
    "xunji_train",
    "garmin_activity",
    "garmin_daily",
    "body_metric",
    "workout",
    "match_candidate",
    "xunji_plan",
    "ai_report",
    "llm_call",
    "job_run",
}


def _make_config(db_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_upgrade_creates_all_tables(tmp_path):
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    assert EXPECTED_TABLES <= set(insp.get_table_names())


def test_upgrade_downgrade_roundtrip(tmp_path):
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    insp = inspect(create_engine(db_url))
    remaining = set(insp.get_table_names()) - {"alembic_version"}
    assert remaining == set()


def test_upgrade_twice_is_stable(tmp_path):
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # 重复执行不报错
    insp = inspect(create_engine(db_url))
    assert EXPECTED_TABLES <= set(insp.get_table_names())
