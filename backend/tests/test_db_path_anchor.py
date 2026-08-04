"""回归测试：make_engine 与 alembic env.py 对相对路径 DATABASE_URL 的锚定必须一致。

Bug 现象：从 backend/ 目录运行时，alembic 建表到 backend/data/app.db，
而 make_engine 建库到 backend/backend/data/app.db（相对路径随 CWD 漂移）。
修复目标：统一锚定到项目根目录，无论从哪个目录启动都指向同一数据库文件。
"""
import os
from pathlib import Path

from app.config import ROOT_DIR, get_settings, resolve_database_url
from app.db import make_engine

BACKEND_DIR = ROOT_DIR / "backend"
EXPECTED_DB = (ROOT_DIR / "backend" / "data" / "app.db").resolve()


def _engine_db_path(engine) -> Path:
    return Path(engine.url.database).resolve()


def test_make_engine_with_explicit_relative_url_anchors_to_root(monkeypatch):
    """显式传相对 URL 给 make_engine，从 backend/ 目录调用也必须锚定到项目根。"""
    monkeypatch.chdir(BACKEND_DIR)
    engine = make_engine("sqlite:///./backend/data/app.db")
    try:
        assert _engine_db_path(engine) == EXPECTED_DB
    finally:
        engine.dispose()


def test_make_engine_and_url_resolver_point_to_same_db_from_backend_dir(monkeypatch):
    """从 backend/ 目录启动：make_engine() 与配置解析（alembic env.py 同源）
    必须解析到同一个数据库文件，且不随 CWD 漂移。"""
    monkeypatch.chdir(BACKEND_DIR)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./backend/data/app.db")
    get_settings.cache_clear()
    try:
        resolved = resolve_database_url(os.environ["DATABASE_URL"])
        engine = make_engine()  # 走 get_settings().database_url，与应用启动路径一致
        try:
            assert _engine_db_path(engine) == EXPECTED_DB
            assert _engine_db_path(engine) == Path(
                resolved.replace("sqlite:///", "", 1)
            ).resolve()
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()


def test_absolute_url_and_memory_db_not_rewritten():
    """绝对路径与内存库不得被锚定逻辑改写。"""
    abs_url = f"sqlite:///{ROOT_DIR}/somewhere/else.db"
    assert resolve_database_url(abs_url) == abs_url
    assert resolve_database_url("sqlite:///:memory:") == "sqlite:///:memory:"
    # None 回退到内置默认库（绝对路径），不随 CWD 漂移
    assert Path(
        resolve_database_url(None).replace("sqlite:///", "", 1)
    ).is_absolute()
