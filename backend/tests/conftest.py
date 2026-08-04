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
    monkeypatch.setenv("FERNET_KEY", TEST_FERNET_KEY)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")  # 测试中不起调度线程
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------- M4 匹配/融合测试共享夹具构造函数 ----------

import json as _json
from datetime import date as _date, datetime as _datetime, time as _time


def make_xunji_train(session, day: _date, localid="1", title="训练",
                     start: _time | None = None, end: _time | None = None,
                     movements=None):
    """构造一条训记原始训练并落库；start/end 为 time 对象，默认 10:00-11:00。"""
    from app.models import XunjiTrain

    start = start or _time(10, 0)
    end = end or _time(11, 0)
    start_ms = int(_datetime.combine(day, start).timestamp() * 1000)
    end_ms = int(_datetime.combine(day, end).timestamp() * 1000)
    raw = {"localid": localid, "title": title, "start": start_ms, "end": end_ms}
    if movements is not None:
        raw["movements"] = movements
    row = XunjiTrain(
        datestr=day.isoformat(), localid=str(localid), title=title,
        start_ms=start_ms, end_ms=end_ms,
        raw_json=_json.dumps(raw, ensure_ascii=False),
    )
    session.add(row)
    session.commit()
    return row


def make_garmin_activity(session, day: _date, activity_id="g1",
                         activity_type="strength_training", name="佳明活动",
                         start: _time | None = None, end: _time | None = None,
                         duration_s=3600, calories=300, avg_hr=120, max_hr=150):
    """构造一条佳明原始活动并落库；start/end 为 time 对象，默认 10:00-11:00。"""
    from app.models import GarminActivity

    start = start or _time(10, 0)
    end = end or _time(11, 0)
    row = GarminActivity(
        activity_id=str(activity_id), activity_type=activity_type, name=name,
        start_ts=_datetime.combine(day, start), end_ts=_datetime.combine(day, end),
        duration_s=duration_s, calories=calories, avg_hr=avg_hr, max_hr=max_hr,
    )
    session.add(row)
    session.commit()
    return row


@pytest.fixture
def session(env_vars):
    from app.db import make_engine, make_session_factory
    from app.models import Base

    engine = make_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    s = factory()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()
