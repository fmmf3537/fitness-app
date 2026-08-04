"""M3 佳明适配器测试（TDD）。

- garminconnect 库的全部外部调用用 FakeGarmin 桩替代，禁止真实外呼（集成测试除外，默认跳过）；
- 时钟与睡眠通过注入假实现控制，验证 0.5s 全局限速而不真实等待；
- 业务侧只应见到 GarminAdapterError，不得泄漏 garminconnect 原始异常。
"""
import json
import os
from datetime import date

import pytest
from garminconnect.exceptions import GarminConnectAuthenticationError

from app.models import GarminActivity, GarminDaily

DATESTR = "2026-08-03"

ACTIVITY_1 = {
    "activityId": 9001,
    "activityName": "力量训练",
    "activityType": {"typeKey": "strength_training"},
    "startTimeLocal": "2026-08-03 18:30:00",
    "duration": 3600.0,
    "calories": 420.0,
    "averageHR": 120.0,
    "maxHR": 160.0,
}
ACTIVITY_2 = {
    "activityId": 9002,
    "activityName": "晨跑",
    "activityType": {"typeKey": "running"},
    "startTimeLocal": "2026-08-03 07:00:00",
    "duration": 1800.0,
    "calories": 300.0,
    "averageHR": 145.0,
    "maxHR": 170.0,
}

SUMMARY = {
    "totalSteps": 12345,
    "restingHeartRate": 52,
    "averageStressLevel": 30,
    "bodyBatteryHighestValue": 95,
    "bodyBatteryLowestValue": 20,
}
SLEEP = {"dailySleepDTO": {"sleepTimeSeconds": 27000}}
HRV = {"hrvSummary": {"status": "BALANCED", "weeklyAvg": 65}}
BODY_BATTERY = [
    {
        "date": "2026-08-03",
        "charged": 75,
        "drained": 55,
        "bodyBatteryValuesArray": [[1754200000000, 95], [1754240000000, 20]],
    }
]


class FakeGarth:
    """garth 客户端桩：仅记录 dump 调用。"""

    def __init__(self):
        self.dumps: list[str] = []

    def dump(self, path):
        self.dumps.append(path)


class FakeGarmin:
    """garminconnect.Garmin 桩：全部方法为本地数据，不触网。"""

    def __init__(self):
        self.garth = FakeGarth()
        self.login_calls: list = []
        self.token_login_fails = False  # 模拟 token 过期
        self.credential_login_fails = False
        self.summary_auth_fails = 0  # 模拟前 N 次 get_user_summary 认证失败
        self.activities_error: Exception | None = None
        self.activities = [ACTIVITY_1, ACTIVITY_2]
        self.details = {"activityId": 9001, "samples": []}
        self.exercise_sets = {"exerciseSets": [{"setType": "ACTIVE", "repetitionCount": 8}]}
        self.summary = dict(SUMMARY)
        self.sleep = SLEEP
        self.hrv = HRV
        self.body_battery = BODY_BATTERY

    # ---- 认证 ----
    def login(self, tokenstore=None):
        self.login_calls.append(tokenstore)
        if tokenstore and self.token_login_fails:
            raise GarminConnectAuthenticationError("token expired")
        if not tokenstore and self.credential_login_fails:
            raise RuntimeError("oauth error")
        return None, None

    # ---- 活动 ----
    def get_activities_by_date(self, startdate, enddate=None, activitytype=None):
        if self.activities_error:
            raise self.activities_error
        return list(self.activities)

    def get_activity_details(self, activity_id):
        return dict(self.details, activityId=int(activity_id))

    def get_activity_exercise_sets(self, activity_id):
        return dict(self.exercise_sets)

    # ---- 每日健康 ----
    def get_user_summary(self, cdate):
        if self.summary_auth_fails > 0:
            self.summary_auth_fails -= 1
            raise GarminConnectAuthenticationError("401")
        return dict(self.summary)

    def get_sleep_data(self, cdate):
        return self.sleep

    def get_hrv_data(self, cdate):
        return self.hrv

    def get_body_battery(self, startdate, enddate=None):
        return self.body_battery


class FakeClock:
    """可注入的假时钟：sleep 只推进时钟不真正等待。"""

    def __init__(self):
        self.t = 1000.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def fake_garmin():
    return FakeGarmin()


@pytest.fixture
def client(session, fake_garmin, clock, tmp_path):
    from app.adapters.garmin_adapter import GarminClient

    return GarminClient(
        session,
        email="u@example.com",
        password="pw",
        token_store=tmp_path / "tokens",
        garmin=fake_garmin,
        sleep=clock.sleep,
        time_fn=clock.time,
    )


# ---------- 登录与 token 缓存 ----------


def test_login_uses_cached_token_store(client, fake_garmin, tmp_path):
    """token 缓存目录存在时直接用缓存恢复会话，不走凭据重登。"""
    (tmp_path / "tokens").mkdir()
    client.login()

    assert fake_garmin.login_calls == [str(tmp_path / "tokens")]
    assert fake_garmin.garth.dumps == []


def test_login_relogs_with_credentials_when_no_cache(client, fake_garmin, tmp_path):
    """无缓存时：凭据全量登录并把 token dump 到缓存目录。"""
    client.login()

    assert fake_garmin.login_calls == [None]
    assert fake_garmin.garth.dumps == [str(tmp_path / "tokens")]
    assert (tmp_path / "tokens").is_dir()


def test_login_falls_back_when_cached_token_expired(client, fake_garmin, tmp_path):
    """缓存 token 过期：自动用 GARMIN_EMAIL/GARMIN_PASSWORD 重登并刷新缓存。"""
    (tmp_path / "tokens").mkdir()
    fake_garmin.token_login_fails = True
    client.login()

    assert fake_garmin.login_calls == [str(tmp_path / "tokens"), None]
    assert fake_garmin.garth.dumps == [str(tmp_path / "tokens")]


def test_login_failure_wrapped(client, fake_garmin):
    """凭据重登也失败：包装为 GarminAdapterError，不泄漏原始异常。"""
    from app.adapters.garmin_adapter import GarminAdapterError

    fake_garmin.credential_login_fails = True
    with pytest.raises(GarminAdapterError):
        client.login()


def test_login_only_once_per_client(client, fake_garmin):
    """同一客户端重复 sync 只登录一次。"""
    client.login()
    client.login()
    assert len(fake_garmin.login_calls) == 1


# ---------- 活动同步 ----------


def test_sync_activities_stores_and_maps_fields(client, session):
    """活动落库 garmin_activity：字段映射正确，起止时间由 startTimeLocal+duration 推导。"""
    rows = client.sync_activities(DATESTR)

    assert len(rows) == 2
    r = session.query(GarminActivity).filter_by(activity_id="9001").one()
    assert r.activity_type == "strength_training"
    assert r.name == "力量训练"
    assert str(r.start_ts) == "2026-08-03 18:30:00"
    assert str(r.end_ts) == "2026-08-03 19:30:00"
    assert r.duration_s == 3600
    assert r.calories == 420
    assert r.avg_hr == 120
    assert r.max_hr == 160
    raw = json.loads(r.raw_json)
    assert raw["summary"]["activityId"] == 9001
    assert raw["exercise_sets"]["exerciseSets"][0]["repetitionCount"] == 8


def test_sync_activities_idempotent_upsert(client, session, fake_garmin):
    """重复同步同一天：按 activity_id upsert，不产生重复行，字段更新。"""
    client.sync_activities(DATESTR)
    fake_garmin.activities = [dict(ACTIVITY_1, calories=500.0), ACTIVITY_2]
    client.sync_activities(DATESTR)

    assert session.query(GarminActivity).count() == 2
    r = session.query(GarminActivity).filter_by(activity_id="9001").one()
    assert r.calories == 500


def test_sync_activities_empty_day(client, session, fake_garmin):
    """当日无活动：返回空列表，不写库。"""
    fake_garmin.activities = []
    rows = client.sync_activities(DATESTR)
    assert rows == []
    assert session.query(GarminActivity).count() == 0


# ---------- 每日健康同步 ----------


def test_sync_daily_stores_fields(client, session):
    """每日健康落库 garmin_daily：步数/静息心率/压力/Body Battery/HRV/睡眠。"""
    row = client.sync_daily(DATESTR)

    db = session.query(GarminDaily).filter_by(date=date(2026, 8, 3)).one()
    assert db.id == row.id
    assert db.steps == 12345
    assert db.resting_hr == 52
    assert db.stress_avg == 30
    assert db.body_battery_high == 95
    assert db.body_battery_low == 20
    assert db.hrv_status == "BALANCED"
    assert json.loads(db.sleep_json)["dailySleepDTO"]["sleepTimeSeconds"] == 27000
    raw = json.loads(db.raw_json)
    assert raw["summary"]["totalSteps"] == 12345
    assert raw["hrv"]["hrvSummary"]["weeklyAvg"] == 65


def test_sync_daily_upsert_by_date(client, session, fake_garmin):
    """同一天重复同步：按 date upsert，只一行且字段更新。"""
    client.sync_daily(DATESTR)
    fake_garmin.summary = dict(SUMMARY, restingHeartRate=55)
    client.sync_daily(DATESTR)

    assert session.query(GarminDaily).count() == 1
    db = session.query(GarminDaily).filter_by(date=date(2026, 8, 3)).one()
    assert db.resting_hr == 55


def test_sync_daily_body_battery_fallback(client, session, fake_garmin):
    """summary 缺 Body Battery 极值时，从 get_body_battery 明细取最大/最小兜底。"""
    fake_garmin.summary = {k: v for k, v in SUMMARY.items() if not k.startswith("bodyBattery")}
    row = client.sync_daily(DATESTR)
    assert row.body_battery_high == 95
    assert row.body_battery_low == 20


def test_sync_daily_no_sleep_data(client, session, fake_garmin):
    """当日无睡眠数据：sleep_json 为 NULL，其余字段正常。"""
    fake_garmin.sleep = None
    row = client.sync_daily(DATESTR)
    assert row.sleep_json is None
    assert row.steps == 12345


# ---------- 全局限速 ----------


def test_rate_limit_half_second_between_calls(client, clock):
    """任意两次佳明 API 调用间隔 ≥ 0.5s（跨不同接口的全局限速）。"""
    client.sync_daily(DATESTR)  # 4 次 API 调用
    assert len(clock.sleeps) == 3
    for wait in clock.sleeps:
        assert 0.49 <= wait <= 0.5


def test_rate_limit_applies_across_methods(client, clock):
    """sync_activities 与 sync_daily 之间同样限速。"""
    client.sync_daily(DATESTR)
    client.sync_activities(DATESTR)  # 活动列表 + 2×(详情+组次) = 5 次调用
    assert len(clock.sleeps) == 3 + 5
    assert all(0.49 <= w <= 0.5 for w in clock.sleeps)


# ---------- 异常包装 ----------


def test_network_error_wrapped_as_adapter_error(client, fake_garmin):
    """garminconnect 任意原始异常统一包装为 GarminAdapterError。"""
    from app.adapters.garmin_adapter import GarminAdapterError

    fake_garmin.activities_error = ConnectionError("connection reset")
    with pytest.raises(GarminAdapterError) as excinfo:
        client.sync_activities(DATESTR)
    assert isinstance(excinfo.value.__cause__, ConnectionError)


def test_auth_error_triggers_relogin_and_retry(client, fake_garmin):
    """API 调用中 token 失效（401）：自动凭据重登一次并重试，调用方无感知。"""
    (client._token_store).mkdir()
    fake_garmin.summary_auth_fails = 1
    row = client.sync_daily(DATESTR)

    assert row.steps == 12345
    # 缓存登录 1 次 + 失效后凭据重登 1 次
    assert fake_garmin.login_calls == [str(client._token_store), None]
    assert fake_garmin.garth.dumps == [str(client._token_store)]


def test_auth_error_retry_failure_wrapped(client, fake_garmin):
    """重登后重试仍失败：包装为 GarminAdapterError。"""
    from app.adapters.garmin_adapter import GarminAdapterError

    fake_garmin.summary_auth_fails = 99
    with pytest.raises(GarminAdapterError):
        client.sync_daily(DATESTR)


# ---------- 凭据来源 ----------


def test_credentials_from_env_not_hardcoded(session, monkeypatch, tmp_path):
    """凭据只从环境变量读取：未显式传参时用 GARMIN_EMAIL/GARMIN_PASSWORD。"""
    from app.adapters.garmin_adapter import GarminClient

    monkeypatch.setenv("GARMIN_EMAIL", "env@example.com")
    monkeypatch.setenv("GARMIN_PASSWORD", "env-pw")
    from app.config import get_settings

    get_settings.cache_clear()
    c = GarminClient(session, token_store=tmp_path / "t", garmin=FakeGarmin())
    assert c._email == "env@example.com"
    assert c._password == "env-pw"


def test_missing_credentials_raises(session, monkeypatch, tmp_path):
    from app.adapters.garmin_adapter import GarminClient

    monkeypatch.delenv("GARMIN_EMAIL", raising=False)
    monkeypatch.delenv("GARMIN_PASSWORD", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(RuntimeError):
        GarminClient(session, token_store=tmp_path / "t", garmin=FakeGarmin())


def test_default_token_store_is_home_dir(session, fake_garmin):
    """默认 token 缓存目录为 ~/.garminconnect。"""
    from pathlib import Path

    from app.adapters.garmin_adapter import GarminClient

    c = GarminClient(session, email="u@example.com", password="pw", garmin=fake_garmin)
    assert c._token_store == Path.home() / ".garminconnect"


# ---------- FIT 导入占位 ----------


def test_import_fit_file_not_implemented(client):
    """import_fit_file 仅预留签名（V2-4 实现）。"""
    with pytest.raises(NotImplementedError):
        client.import_fit_file("some.fit")


# ---------- 集成测试（真实外呼，默认跳过） ----------


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_GARMIN_INTEGRATION") != "1",
    reason="真实外呼佳明易触发 429，默认跳过；手动运行：$env:RUN_GARMIN_INTEGRATION='1'; pytest -m integration",
)
def test_integration_fetch_last_3_days(session):
    """手动验证：真实凭据拉近 3 天活动与健康数据。

    运行方式：pytest -m integration tests/test_garmin_adapter.py
    """
    from datetime import timedelta

    from app.adapters.garmin_adapter import GarminClient

    client = GarminClient(session)
    today = date.today()
    for i in range(3):
        datestr = (today - timedelta(days=i)).isoformat()
        client.sync_activities(datestr)
        client.sync_daily(datestr)
    assert session.query(GarminDaily).count() >= 1
