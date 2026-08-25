"""M3-FIX 佳明适配器测试（TDD，garth 直连中国区版本）。

- garth 库的全部外部调用用 FakeGarth 桩替代，禁止真实外呼（集成测试除外，默认跳过）；
- 时钟与睡眠通过注入假实现控制，验证 0.5s 全局限速与 429 退避而不真实等待；
- 业务侧只应见到 GarminAdapterError，不得泄漏 garth 原始异常。
"""
import json
import os
from datetime import date

import pytest
import requests
from garth.exc import GarthException, GarthHTTPError
from sqlalchemy import select

from app.models import GarminActivity, GarminDaily, Setting

DATESTR = "2026-08-03"

ACTIVITIES_PATH = "/activitylist-service/activities/search/activities"

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


def make_http_error(status: int) -> GarthHTTPError:
    """构造与 garth 真实抛出结构一致的 HTTP 错误（含 response.status_code）。"""
    resp = requests.Response()
    resp.status_code = status
    return GarthHTTPError(f"HTTP {status}", requests.HTTPError(response=resp))


class FakeGarth:
    """garth 模块桩：configure/login/resume/save/connectapi 全部为本地数据，不触网。"""

    def __init__(self):
        self.configured_domains: list = []
        self.login_calls: list[tuple] = []  # (email, password) 凭据全量登录
        self.resume_calls: list[str] = []  # token 缓存恢复
        self.save_calls: list[str] = []  # token 保存
        self.api_calls: list[tuple] = []  # (path, params)
        self.resume_fails = False  # 模拟 token 缓存失效
        self.credential_login_fails = False
        self.summary_auth_fails = 0  # 模拟前 N 次 summary 调用 401
        self.activities_error: Exception | None = None
        self.error_queue: list[Exception] = []  # 接下来 N 次任意 API 调用依次抛出
        self.activities = [ACTIVITY_1, ACTIVITY_2]
        self.details = {"activityId": 9001, "samples": []}
        self.exercise_sets = {"exerciseSets": [{"setType": "ACTIVE", "repetitionCount": 8}]}
        self.summary = dict(SUMMARY)
        self.sleep = SLEEP
        self.hrv = HRV
        self.body_battery = BODY_BATTERY
        # M3-1：login() 成功后会填充这些字段，供 _serialize_garmin_token 读取
        # 真实 garth.Client 也用同样字段名（oauth1_token / oauth2_token / domain）
        self.oauth1_token = {
            "oauth_token": "fake-oauth1",
            "oauth_token_secret": "fake-secret",
            "mfa_token": None,
            "mfa_expiration_timestamp": None,
            "domain": "garmin.cn",
        }
        self.oauth2_token = {
            "scope": "fake",
            "jti": "fake-jti",
            "token_type": "Bearer",
            "access_token": "fake-access",
            "refresh_token": "fake-refresh",
            "expires_in": 3600,
            "expires_at": 9999999999,
            "refresh_token_expires_in": 86400,
            "refresh_token_expires_at": 9999999999,
        }
        self.domain = "garmin.cn"

    # ---- 认证 ----
    def configure(self, domain=None, **kwargs):
        self.configured_domains.append(domain)
        if domain:
            self.domain = domain
            if isinstance(self.oauth1_token, dict):
                self.oauth1_token["domain"] = domain

    def login(self, email, password):
        if self.credential_login_fails:
            raise GarthException("oauth error")
        self.login_calls.append((email, password))

    def resume(self, dir_path):
        self.resume_calls.append(dir_path)
        if self.resume_fails:
            raise GarthException("token expired")

    def save(self, dir_path):
        self.save_calls.append(dir_path)

    # ---- 数据 ----
    def connectapi(self, path, method="GET", **kwargs):
        params = kwargs.get("params") or {}
        self.api_calls.append((path, params))
        if self.error_queue:
            raise self.error_queue.pop(0)
        if path == ACTIVITIES_PATH:
            if self.activities_error:
                raise self.activities_error
            start = int(params.get("start", 0))
            limit = int(params.get("limit", 20))
            return self.activities[start : start + limit]
        if path.startswith("/activity-service/activity/"):
            if path.endswith("/details"):
                return dict(self.details)
            if path.endswith("/exerciseSets"):
                return dict(self.exercise_sets)
        if path == "/userprofile-service/socialProfile":
            return {"displayName": "tester"}
        if path.startswith("/usersummary-service/usersummary/daily/"):
            if self.summary_auth_fails > 0:
                self.summary_auth_fails -= 1
                raise make_http_error(401)
            return dict(self.summary)
        if path.startswith("/wellness-service/wellness/dailySleepData/"):
            return self.sleep
        if path.startswith("/hrv-service/hrv/"):
            return self.hrv
        if path == "/wellness-service/wellness/bodyBattery/reports/daily":
            return self.body_battery
        raise AssertionError(f"FakeGarth 未预期的路径: {path}")


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
def fake_garth():
    return FakeGarth()


@pytest.fixture
def client(session, fake_garth, clock, tmp_path):
    """M3-1：GarminClient 现在用 settings 表 token（按 user_id），不再用磁盘 token_store。
    传 user_id=1（conftest 已预建 alice），让 _resolve_garmin_credentials 走 settings 路径。
    token_store 参数保留为向后兼容（被忽略）。"""
    from app.adapters.garmin_adapter import GarminClient

    return GarminClient(
        session,
        user_id=1,
        email="u@example.com",  # 显式传 email/password 优先于 settings 解析
        password="pw",
        token_store=tmp_path / "tokens",  # noqa: ARG003  # 兼容旧 API
        garth=fake_garth,
        sleep=clock.sleep,
        time_fn=clock.time,
    )


# ---------- 登录与 token 缓存 ----------


def test_login_uses_settings_token(client, fake_garth, session):
    """M3-1：settings.garmin_token_store_enc 已有有效 token 时直接恢复，不走凭据重登。"""
    from app.config import encrypt_value
    from app.models import Setting

    # 预存一个"有效"的 token JSON 到 alice (user_id=1) 的 settings
    fake_token = {
        "oauth1": {
            "oauth_token": "fake-oauth1",
            "oauth_token_secret": "secret",
            "mfa_token": None,
            "mfa_expiration_timestamp": None,
            "domain": "garmin.cn",
        },
        "oauth2": {
            "scope": "...",
            "jti": "...",
            "token_type": "Bearer",
            "access_token": "fake-access",
            "refresh_token": "fake-refresh",
            "expires_in": 3600,
            "expires_at": 9999999999,
            "refresh_token_expires_in": 86400,
            "refresh_token_expires_at": 9999999999,
        },
        "domain": "garmin.cn",
    }
    row = session.scalars(select(Setting).where(Setting.user_id == 1)).first()
    if row is None:
        row = Setting(user_id=1)
        session.add(row)
        session.flush()
    row.garmin_token_store_enc = encrypt_value(json.dumps(fake_token))
    session.commit()

    client.login()

    # 关键：没走凭据登录，token 直接从 settings 恢复
    assert fake_garth.login_calls == []
    # 也没走 save_calls（不再写磁盘）
    assert fake_garth.save_calls == []


def test_login_relogs_with_credentials_when_no_token(client, fake_garth, session):
    """M3-1：settings.garmin_token_store_enc 为空时凭据登录，token 加密存 settings。"""
    # 确保 settings.garmin_token_store_enc 为空
    row = session.scalars(select(Setting).where(Setting.user_id == 1)).first()
    if row is not None:
        row.garmin_token_store_enc = None
        session.commit()

    client.login()

    assert fake_garth.login_calls == [("u@example.com", "pw")]
    # 关键：登录成功后 token 被加密写回 settings
    row = session.scalars(select(Setting).where(Setting.user_id == 1)).first()
    assert row is not None
    assert row.garmin_token_store_enc is not None
    # 也不再写磁盘
    assert fake_garth.save_calls == []


def test_login_falls_back_when_settings_token_invalid(client, fake_garth, session):
    """M3-1：settings.garmin_token_store_enc 内容无效时 fallback 凭据重登。"""
    from app.config import encrypt_value
    from app.models import Setting

    # 预存一个无法被 _restore_garmin_token 解析的 token（缺关键字段）
    bad_token = {"domain": "garmin.cn"}  # 没有 oauth1 / oauth2
    row = session.scalars(select(Setting).where(Setting.user_id == 1)).first()
    if row is None:
        row = Setting(user_id=1)
        session.add(row)
        session.flush()
    row.garmin_token_store_enc = encrypt_value(json.dumps(bad_token))
    session.commit()

    client.login()

    # 关键：fallback 到凭据重登
    assert fake_garth.login_calls == [("u@example.com", "pw")]
    # 登录成功后 token 被刷新到 settings
    assert fake_garth.save_calls == []  # 不写磁盘


def test_login_failure_wrapped(client, fake_garth):
    """凭据重登也失败：包装为 GarminAdapterError，不泄漏原始异常。"""
    from app.adapters.garmin_adapter import GarminAdapterError

    fake_garth.credential_login_fails = True
    with pytest.raises(GarminAdapterError):
        client.login()


def test_login_only_once_per_client(client, fake_garth):
    """同一客户端重复 sync 只登录一次（resume/login 合计仅一次）。"""
    client.login()
    client.login()
    assert len(fake_garth.resume_calls) + len(fake_garth.login_calls) == 1


def test_domain_defaults_to_garmin_cn(client, fake_garth):
    """默认域名为中国区 garmin.cn，登录前完成 configure。"""
    client.login()
    assert fake_garth.configured_domains[0] == "garmin.cn"


def test_domain_from_env(session, monkeypatch, tmp_path, fake_garth):
    """GARMIN_DOMAIN 环境变量可覆盖默认域名，不写死。"""
    from app.adapters.garmin_adapter import GarminClient

    monkeypatch.setenv("GARMIN_DOMAIN", "garmin.com")
    from app.config import get_settings

    get_settings.cache_clear()
    c = GarminClient(
        session,
        email="u@example.com",
        password="pw",
        token_store=tmp_path / "t",
        garth=fake_garth,
    )
    c.login()
    assert fake_garth.configured_domains[0] == "garmin.com"


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


def test_sync_activities_idempotent_upsert(client, session, fake_garth):
    """重复同步同一天：按 activity_id upsert，不产生重复行，字段更新。"""
    client.sync_activities(DATESTR)
    fake_garth.activities = [dict(ACTIVITY_1, calories=500.0), ACTIVITY_2]
    client.sync_activities(DATESTR)

    assert session.query(GarminActivity).count() == 2
    r = session.query(GarminActivity).filter_by(activity_id="9001").one()
    assert r.calories == 500


def test_sync_activities_empty_day(client, session, fake_garth):
    """当日无活动：返回空列表，不写库。"""
    fake_garth.activities = []
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


def test_sync_daily_upsert_by_date(client, session, fake_garth):
    """同一天重复同步：按 date upsert，只一行且字段更新。"""
    client.sync_daily(DATESTR)
    fake_garth.summary = dict(SUMMARY, restingHeartRate=55)
    client.sync_daily(DATESTR)

    assert session.query(GarminDaily).count() == 1
    db = session.query(GarminDaily).filter_by(date=date(2026, 8, 3)).one()
    assert db.resting_hr == 55


def test_sync_daily_body_battery_fallback(client, session, fake_garth):
    """summary 缺 Body Battery 极值时，从 body battery 明细取最大/最小兜底。"""
    fake_garth.summary = {k: v for k, v in SUMMARY.items() if not k.startswith("bodyBattery")}
    row = client.sync_daily(DATESTR)
    assert row.body_battery_high == 95
    assert row.body_battery_low == 20


def test_sync_daily_no_sleep_data(client, session, fake_garth):
    """当日无睡眠数据：sleep_json 为 NULL，其余字段正常。"""
    fake_garth.sleep = None
    row = client.sync_daily(DATESTR)
    assert row.sleep_json is None
    assert row.steps == 12345


# ---------- 全局限速 ----------


def test_rate_limit_half_second_between_calls(client, clock):
    """任意两次佳明 API 调用间隔 ≥ 0.5s（跨不同接口的全局限速）。"""
    client.sync_daily(DATESTR)  # 5 次 API 调用：profile + summary + sleep + hrv + body battery
    assert len(clock.sleeps) == 4
    for wait in clock.sleeps:
        assert 0.49 <= wait <= 0.5


def test_rate_limit_applies_across_methods(client, clock):
    """sync_activities 与 sync_daily 之间同样限速。"""
    client.sync_daily(DATESTR)
    client.sync_activities(DATESTR)  # 活动列表 + 2×(详情+组次) = 5 次调用
    assert len(clock.sleeps) == 4 + 5
    assert all(0.49 <= w <= 0.5 for w in clock.sleeps)


# ---------- 429 指数退避 ----------


def test_429_backoff_and_recovery(client, fake_garth, clock):
    """收到 429 按 60s/300s/900s 指数退避重试，恢复后正常返回。"""
    fake_garth.error_queue = [make_http_error(429) for _ in range(3)]
    row = client.sync_daily(DATESTR)

    assert row.steps == 12345
    assert clock.sleeps[:3] == [60.0, 300.0, 900.0]


def test_429_exhausted_raises_adapter_error(client, fake_garth, clock):
    """429 连续 3 次退避后仍失败：抛 GarminAdapterError。"""
    from app.adapters.garmin_adapter import GarminAdapterError

    fake_garth.error_queue = [make_http_error(429) for _ in range(4)]
    with pytest.raises(GarminAdapterError):
        client.sync_daily(DATESTR)
    assert clock.sleeps == [60.0, 300.0, 900.0]


# ---------- 异常包装 ----------


def test_network_error_wrapped_as_adapter_error(client, fake_garth):
    """garth 任意原始异常统一包装为 GarminAdapterError。"""
    from app.adapters.garmin_adapter import GarminAdapterError

    fake_garth.activities_error = ConnectionError("connection reset")
    with pytest.raises(GarminAdapterError) as excinfo:
        client.sync_activities(DATESTR)
    assert isinstance(excinfo.value.__cause__, ConnectionError)


def test_auth_error_triggers_relogin_and_retry(client, fake_garth, session):
    """M3-1：API 调用中 token 失效（401）：自动凭据重登一次并重试，调用方无感知。
    重登成功后新 token 加密存 settings（不再写磁盘 token_store）。"""
    from app.config import encrypt_value
    fake_token = {
        "oauth1": {
            "oauth_token": "fake-oauth1", "oauth_token_secret": "secret",
            "mfa_token": None, "mfa_expiration_timestamp": None, "domain": "garmin.cn",
        },
        "oauth2": {
            "scope": "...", "jti": "...", "token_type": "Bearer",
            "access_token": "fake-access", "refresh_token": "fake-refresh",
            "expires_in": 3600, "expires_at": 9999999999,
            "refresh_token_expires_in": 86400, "refresh_token_expires_at": 9999999999,
        },
        "domain": "garmin.cn",
    }
    row = session.scalars(select(Setting).where(Setting.user_id == 1)).first()
    if row is None:
        row = Setting(user_id=1)
        session.add(row)
        session.flush()
    row.garmin_token_store_enc = encrypt_value(json.dumps(fake_token))
    session.commit()

    fake_garth.summary_auth_fails = 1
    row_result = client.sync_daily(DATESTR)

    assert row_result.steps == 12345
    # M3-1：先从 settings 恢复，失败后凭据重登；不再调 resume/save
    assert fake_garth.login_calls == [("u@example.com", "pw")]
    assert fake_garth.save_calls == []


def test_auth_error_retry_failure_wrapped(client, fake_garth):
    """重登后重试仍失败：包装为 GarminAdapterError。"""
    from app.adapters.garmin_adapter import GarminAdapterError

    fake_garth.summary_auth_fails = 99
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
    c = GarminClient(session, token_store=tmp_path / "t", garth=FakeGarth())
    assert c._email == "env@example.com"
    assert c._password == "env-pw"


def test_missing_credentials_raises(session, monkeypatch, fake_garth):
    """M3-1：email/password + settings + env 都没有时抛 GarminKeyNotConfiguredError。
    旧版用 RuntimeError，新版用专用异常（继承自 GarminAdapterError）便于上层定向处理。"""
    from app.adapters.garmin_adapter import GarminClient, GarminKeyNotConfiguredError

    monkeypatch.delenv("GARMIN_EMAIL", raising=False)
    monkeypatch.delenv("GARMIN_PASSWORD", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(GarminKeyNotConfiguredError):
        GarminClient(session, user_id=1, garth=fake_garth)
    get_settings.cache_clear()


def test_token_settings_per_user_isolated(session, fake_garth):
    """M3-1：settings.garmin_token_store_enc 按 user_id 隔离（user 2 拿不到 user 1 的 token）。"""
    from app.adapters.garmin_adapter import GarminClient
    from app.config import encrypt_value
    from app.services import users as user_service

    # 预建用户 2
    try:
        user_service.create_user(session, username="bob", password="test-pass", role="user")
    except ValueError:
        session.rollback()
    user_b = user_service.get_user_by_username(session, "bob")

    # 用户 1 存 token
    fake_token_1 = {
        "oauth1": {"oauth_token": "alice-token", "oauth_token_secret": "s", "mfa_token": None, "mfa_expiration_timestamp": None, "domain": "garmin.cn"},
        "oauth2": {"scope": "x", "jti": "x", "token_type": "Bearer", "access_token": "alice-access", "refresh_token": "x", "expires_in": 3600, "expires_at": 9999999999, "refresh_token_expires_in": 86400, "refresh_token_expires_at": 9999999999},
        "domain": "garmin.cn",
    }
    row1 = session.scalars(select(Setting).where(Setting.user_id == 1)).first()
    if row1 is None:
        row1 = Setting(user_id=1)
        session.add(row1)
        session.flush()
    row1.garmin_token_store_enc = encrypt_value(json.dumps(fake_token_1))
    # 用户 2 不存
    row2 = session.scalars(select(Setting).where(Setting.user_id == user_b.id)).first()
    if row2 is not None:
        row2.garmin_token_store_enc = None
    session.commit()

    # 用户 1 login → 直接从 settings 恢复，fake_garth 不应被 login() 调用
    c1 = GarminClient(session, user_id=1, email="u@example.com", password="pw", garth=fake_garth)
    c1.login()
    assert fake_garth.login_calls == []

    # 用户 2 login → settings 没 token，走凭据重登
    fake_garth.login_calls.clear()
    c2 = GarminClient(session, user_id=user_b.id, email="u@example.com", password="pw", garth=fake_garth)
    c2.login()
    assert fake_garth.login_calls == [("u@example.com", "pw")]


# ---------- 集成测试（真实外呼，默认跳过） ----------


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_GARMIN_INTEGRATION") != "1",
    reason="真实外呼佳明易触发 429，默认跳过；手动运行：$env:RUN_GARMIN_INTEGRATION='1'; pytest -m integration",
)
def test_integration_fetch_2026_08_03_strength(session):
    """手动验证：真实凭据拉 2026-08-03，必须包含 strength_training 活动（该日确定有数据）。

    运行方式：pytest -m integration tests/test_garmin_adapter.py
    """
    from app.adapters.garmin_adapter import GarminClient
    from app.api.workouts import extract_heart_rate_series

    client = GarminClient(session)
    rows = client.sync_activities(DATESTR)
    types = {r.activity_type for r in rows}
    assert "strength_training" in types, f"2026-08-03 未拉到力量训练活动，实际类型: {types}"

    # 心率时间序列：真实 details 响应中 heartRateDTOs 可能为 null，
    # 序列在 activityDetailMetrics（描述符字段名 metricsIndex），必须提取出足够点数
    strength = next(r for r in rows if r.activity_type == "strength_training")
    series = extract_heart_rate_series(strength.raw_json)
    assert len(series) > 100, f"2026-08-03 力量活动心率序列点数不足: {len(series)}"
    assert all(0 < p["hr"] < 250 for p in series)

    daily = client.sync_daily(DATESTR)
    assert daily.date == date(2026, 8, 3)



# ---------- V1-2 全量活动分页拉取（历史导入用） ----------


def _make_activities(n: int) -> list[dict]:
    return [
        {
            "activityId": 7000 + i,
            "activityName": f"活动{i}",
            "activityType": {"typeKey": "running"},
            "startTimeLocal": "2020-01-01 08:00:00",
            "duration": 1800.0,
            "calories": 200.0,
            "averageHR": 130.0,
            "maxHR": 160.0,
        }
        for i in range(n)
    ]


def test_sync_all_activities_pages_and_upserts(client, fake_garth, session):
    """全量分页：每页 page_size 条，逐页落库并回调 on_page(start, page_len)。"""
    from app.models import GarminActivity

    fake_garth.activities = _make_activities(5)
    pages: list[tuple[int, int]] = []
    total = client.sync_all_activities(page_size=2, on_page=lambda s, n: pages.append((s, n)))

    assert total == 5
    assert pages == [(0, 2), (2, 2), (4, 1)]
    assert session.query(GarminActivity).count() == 5
    list_calls = [p for p in fake_garth.api_calls if p[0] == ACTIVITIES_PATH]
    assert [c[1]["start"] for c in list_calls] == [0, 2, 4]
    assert all(c[1]["limit"] == 2 for c in list_calls)


def test_sync_all_activities_respects_start_offset_and_skip_ids(client, fake_garth, session):
    """断点续传：start_offset 之后的页才请求；skip_ids 内活动跳过详情拉取。"""
    from app.models import GarminActivity

    fake_garth.activities = _make_activities(4)
    # 模拟 7000 已入库（跳过详情），从 offset 2 继续
    session.add(GarminActivity(activity_id="7000"))
    session.commit()
    pages: list[tuple[int, int]] = []
    total = client.sync_all_activities(
        page_size=2, start_offset=2, skip_ids={"7002"},
        on_page=lambda s, n: pages.append((s, n)),
    )

    list_calls = [p for p in fake_garth.api_calls if p[0] == ACTIVITIES_PATH]
    assert [c[1]["start"] for c in list_calls] == [2, 4]  # 从 offset=2 续拉，空页收尾
    detail_calls = [p for p in fake_garth.api_calls if str(p[0]).endswith("/details")]
    assert len(detail_calls) == 1  # 7002 被跳过，只有 7003 拉详情
    assert total == 1
    assert pages == [(2, 2), (4, 0)]


def test_sync_all_activities_interval_throttled(client, fake_garth, clock):
    """页间调用间隔由全局限速保证（每次 connectapi 前至少间隔 0.5s）。"""
    fake_garth.activities = _make_activities(3)
    client.sync_all_activities(page_size=1)
    # 每个活动 3 次调用（list/details/exerciseSets），除首次外每次间隔 0.5s
    assert clock.sleeps
    assert all(s == pytest.approx(0.5) for s in clock.sleeps)
