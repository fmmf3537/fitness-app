"""db.py 辅助路径覆盖：默认引擎建表、get_session 依赖、PRAGMA 容错。"""
from unittest.mock import Mock

from sqlalchemy import inspect, text

from app import db
from app.config import get_settings


def test_init_db_creates_tables_with_default_engine():
    db.init_db()
    names = set(inspect(db.engine).get_table_names())
    assert {"workout", "xunji_train", "garmin_activity"} <= names


def test_get_session_yields_usable_session_then_closes():
    gen = db.get_session()
    session = next(gen)
    assert session.execute(text("SELECT 1")).scalar() == 1
    gen.close()  # 触发 finally 关闭


def test_sqlite_pragma_listener_tolerates_non_sqlite_driver():
    fake_conn = Mock()
    fake_conn.cursor.side_effect = AttributeError("not sqlite")
    db._set_sqlite_pragma(fake_conn, None)  # 不抛异常即通过


def test_relative_sqlite_url_anchored_to_project_root():
    url = get_settings()._resolve_database_url("sqlite:///./backend/data/app.db")
    normalized = url.replace("\\", "/")
    assert "fitness-app" in normalized
    assert normalized.endswith("backend/data/app.db")
