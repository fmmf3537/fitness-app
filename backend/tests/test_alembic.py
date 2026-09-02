"""Alembic 初始迁移 upgrade/downgrade 往返测试。"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "settings",
    "skinfold_record",
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
    "backfill_progress",
    "report_chat_message",
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


def test_workout_soft_delete_columns_roundtrip(tmp_path):
    """V3-11：workout.deleted_at + 两源表 excluded，升级出现、回滚消失、再升级回来。"""
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    assert "deleted_at" in {c["name"] for c in insp.get_columns("workout")}
    assert "excluded" in {c["name"] for c in insp.get_columns("garmin_activity")}
    assert "excluded" in {c["name"] for c in insp.get_columns("xunji_train")}

    command.downgrade(cfg, "e4f5a6b7c8d9")  # 回退到 f5a6b7c8d9e0 之前
    insp = inspect(create_engine(db_url))
    assert "deleted_at" not in {c["name"] for c in insp.get_columns("workout")}
    assert "excluded" not in {c["name"] for c in insp.get_columns("garmin_activity")}
    assert "excluded" not in {c["name"] for c in insp.get_columns("xunji_train")}

    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    assert "deleted_at" in {c["name"] for c in insp.get_columns("workout")}


def test_ai_report_score_columns_roundtrip(tmp_path):
    """V3-4：ai_report 增加 score/one_liner/subscores_json，升级出现、回滚消失。"""
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    cols = {c["name"] for c in insp.get_columns("ai_report")}
    assert {"score", "one_liner", "subscores_json"} <= cols

    command.downgrade(cfg, "c2d3e4f5a6b7")  # 回退一个版本
    insp = inspect(create_engine(db_url))
    cols = {c["name"] for c in insp.get_columns("ai_report")}
    assert {"score", "one_liner", "subscores_json"}.isdisjoint(cols)

    command.upgrade(cfg, "head")  # 再次升级恢复
    insp = inspect(create_engine(db_url))
    cols = {c["name"] for c in insp.get_columns("ai_report")}
    assert {"score", "one_liner", "subscores_json"} <= cols


def test_report_chat_message_table_roundtrip(tmp_path):
    """V3-8：report_chat_message 表随升级出现、回退一个版本消失、再升级恢复。"""
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    assert "report_chat_message" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("report_chat_message")}
    assert {
        "id",
        "report_id",
        "role",
        "content",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "cost_estimate",
        "client_request_id",
        "created_at",
    } == cols

    command.downgrade(cfg, "d3e4f5a6b7c8")  # 回退一个版本
    insp = inspect(create_engine(db_url))
    assert "report_chat_message" not in insp.get_table_names()

    command.upgrade(cfg, "head")  # 再次升级恢复
    insp = inspect(create_engine(db_url))
    assert "report_chat_message" in insp.get_table_names()


def test_upgrade_twice_is_stable(tmp_path):
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # 重复执行不报错
    insp = inspect(create_engine(db_url))
    assert EXPECTED_TABLES <= set(insp.get_table_names())


def test_skinfold_and_settings_profile_roundtrip(tmp_path):
    """V4-3：skinfold_record 表 + settings.gender/birth_date，升级出现、回滚消失、再升级恢复。"""
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    assert "skinfold_record" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("skinfold_record")}
    assert {
        "id",
        "date",
        "method",
        "sites_json",
        "density",
        "bodyfat_result",
        "note",
        "created_at",
        "updated_at",
    } == cols
    settings_cols = {c["name"] for c in insp.get_columns("settings")}
    assert "gender" in settings_cols
    assert "birth_date" in settings_cols

    command.downgrade(cfg, "f5a6b7c8d9e0")  # 回退到 f5a6b7c8d9e0 之前
    insp = inspect(create_engine(db_url))
    assert "skinfold_record" not in insp.get_table_names()
    settings_cols = {c["name"] for c in insp.get_columns("settings")}
    assert "gender" not in settings_cols
    assert "birth_date" not in settings_cols

    command.upgrade(cfg, "head")  # 再次升级恢复
    insp = inspect(create_engine(db_url))
    assert "skinfold_record" in insp.get_table_names()
    settings_cols = {c["name"] for c in insp.get_columns("settings")}
    assert "gender" in settings_cols
    assert "birth_date" in settings_cols
