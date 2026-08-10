"""SQLAlchemy 2.x 引擎与 Session。"""
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings, resolve_database_url
from app.models import Base


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):  # SQLite 开启外键约束
    # 仅对 SQLite 驱动执行：psycopg2 等驱动执行 PRAGMA 会报错并把连接事务
    # 置入 aborted 状态（V2-5 PG 迁移实测踩坑），即使 catch 掉异常连接也已不可用
    if type(dbapi_connection).__module__ != "sqlite3":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(url: str | None = None) -> Engine:
    # 显式传入的相对 URL 同样锚定到项目根目录，保证与 alembic 解析结果一致
    url = resolve_database_url(url) if url else get_settings().database_url
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        db_path = url.replace("sqlite:///", "", 1)
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, connect_args=connect_args)


def make_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine or make_engine(), autoflush=False, expire_on_commit=False)


engine = make_engine()
SessionLocal = make_session_factory(engine)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_session():
    """FastAPI 依赖注入用 Session。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
