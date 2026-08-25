import os
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

TEST_FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def env_vars(monkeypatch, tmp_path):
    """每个测试使用独立的 FERNET_KEY 与 SQLite 临时库。"""
    # 必须先导入 app.config：其模块级 load_dotenv(override=True) 会用 .env
    # 覆盖 OS 环境变量；若在 setenv 之后才首次导入，测试 DATABASE_URL 会被
    # .env 中的真实库 URL 遮蔽（test_settings_insert_query 曾因此打到 dev 库）。
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("FERNET_KEY", TEST_FERNET_KEY)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")  # 测试中不起调度线程
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------- M4 匹配/融合测试共享夹具构造函数 ----------

import json as _json
from datetime import date as _date, datetime as _datetime, time as _time, timedelta as _timedelta, timezone as _timezone

# 训记 start_ms 是 epoch 毫秒，匹配引擎按固定 +08:00 渲染（matcher.XUNJI_TZ）；
# 夹具编码也必须用同一时区，保证在任何本地时区的机器上往返一致。
_BJ = _timezone(_timedelta(hours=8))


def make_xunji_train(session, day: _date, localid="1", title="训练",
                     start: _time | None = None, end: _time | None = None,
                     movements=None, user_id=1):
    """构造一条训记原始训练并落库；start/end 为 time 对象，默认 10:00-11:00。"""
    from app.models import XunjiTrain

    start = start or _time(10, 0)
    end = end or _time(11, 0)
    start_ms = int(_datetime.combine(day, start, tzinfo=_BJ).timestamp() * 1000)
    end_ms = int(_datetime.combine(day, end, tzinfo=_BJ).timestamp() * 1000)
    raw = {"localid": localid, "title": title, "start": start_ms, "end": end_ms}
    if movements is not None:
        raw["movements"] = movements
    row = XunjiTrain(
        datestr=day.isoformat(), localid=str(localid), title=title,
        start_ms=start_ms, end_ms=end_ms,
        raw_json=_json.dumps(raw, ensure_ascii=False),
        user_id=user_id,
    )
    session.add(row)
    session.commit()
    return row


def make_garmin_activity(session, day: _date, activity_id="g1",
                         activity_type="strength_training", name="佳明活动",
                         start: _time | None = None, end: _time | None = None,
                         duration_s=3600, calories=300, avg_hr=120, max_hr=150,
                         user_id=1):
    """构造一条佳明原始活动并落库；start/end 为 time 对象，默认 10:00-11:00。"""
    from app.models import GarminActivity

    start = start or _time(10, 0)
    end = end or _time(11, 0)
    row = GarminActivity(
        activity_id=str(activity_id), activity_type=activity_type, name=name,
        start_ts=_datetime.combine(day, start), end_ts=_datetime.combine(day, end),
        duration_s=duration_s, calories=calories, avg_hr=avg_hr, max_hr=max_hr,
        user_id=user_id,
    )
    session.add(row)
    session.commit()
    return row


@pytest.fixture
def session(env_vars):
    from app.db import make_engine, make_session_factory
    from app.models import Base
    from app.services import users as user_service

    engine = make_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    s = factory()
    # M2-4：预建固定 id=1 的 alice，使 make_xunji_train/make_garmin_activity
    # 默认的 user_id=1 始终有对应 user（满足外键），且与 auth 登录后的
    # current_user_id 对齐（隔离查询可见）。
    try:
        user_service.create_user(s, username="alice", password="test-pass", role="user")
    except ValueError:
        s.rollback()  # 已存在则忽略（理论上每次新建库不会触发）
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


# ---------- M2-4 多用户认证共享夹具 ----------


@pytest.fixture
def auth_user(client, session):
    """创建测试用户并登录，返回 {"user_id": ..., "headers": {...}}。

    依赖各测试模块自己定义的 client 夹具（TestClient + get_session override）。
    业务数据夹具（make_xunji_train 等）创建行时应传 user_id=auth_user["user_id"]，
    否则 API 按 current_user_id 过滤后不可见。
    """
    from app.services import users as user_service

    try:
        user = user_service.create_user(
            session, username="alice", password="test-pass", role="user"
        )
    except ValueError:
        user = user_service.get_user_by_username(session, "alice")  # 已由 session 预建
    body = client.post(
        "/api/auth/login", json={"username": "alice", "password": "test-pass"}
    ).json()
    assert "token" in body, f"登录失败: {body}"
    return {"user_id": user.id, "headers": {"Authorization": f"Bearer {body['token']}"}}


@pytest.fixture
def auth(auth_user):
    """仅取 Authorization 头（等价旧 auth 夹具的返回值）。"""
    return auth_user["headers"]
