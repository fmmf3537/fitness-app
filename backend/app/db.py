"""SQLAlchemy 2.x 引擎与 Session。"""
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):  # SQLite 开启外键约束
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:  # 非 SQLite 驱动直接跳过
        pass


def make_engine(url: str | None = None) -> Engine:
    url = url or get_settings().database_url
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
