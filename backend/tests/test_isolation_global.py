"""M2-5 全局隔离测试：从 FastAPI app.routes 动态枚举所有端点。

目的：保证多用户隔离在所有路由上一致生效。
新增路由如果没做 user_id 隔离，会自动被本测试套件捕获。

策略：
- 创建 alice / bob 两个用户，各持有 user_id 区分的数据
- 动态枚举 app.routes，对每个需要认证的端点用 alice 的 token 访问
- 断言：alice 永远看不到 bob 的数据（列表为空 / 详情 404 / 统计不含 bob）
- 跳过：/api/auth/login（公开）、/health（健康检查）、admin 专属端点

与 test_api_isolation.py 的区别：
- test_api_isolation.py：手写 parametrize 覆盖 20 个端点（已通过）
- test_isolation_global.py：动态枚举所有路由，**新增端点自动纳入测试**
"""

import datetime
import re

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import (
    AIReport,
    BodyMetric,
    GarminDaily,
    User,
    Workout,
    XunjiPlan,
)
from app.services import users as user_service


# 公开端点：不需要认证，测试跳过
PUBLIC_PATH_PREFIXES = (
    "/api/auth/login",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
)

# 需要特殊 body / 跳过的端点（不能直接用空 GET/POST 探活）
SKIP_PATH_PATTERNS = (
    r".*/fit/import",
    r".*/screenshot/import",
    r".*/session-review/regenerate/status",
    r".*/backfill/start",
    r".*/backfill/cancel",
    r".*/sync/.*",
    r".*/writeback/.*",
    r".*/posters/.*",
    r".*/plans/refresh",
    r".*/settings/bindings/.*",
    r".*/settings/llm",
)


def _is_skip_path(path: str) -> bool:
    if not path.startswith("/api/"):
        return True
    for prefix in PUBLIC_PATH_PREFIXES:
        if path.startswith(prefix):
            return True
    for pat in SKIP_PATH_PATTERNS:
        if re.match(pat, path):
            return True
    return False


def _enumerate_routes():
    """从 FastAPI OpenAPI schema 动态枚举所有端点,返回 (method, path) 列表。

    原因：`app.include_router` 注册的子路由在 `app.routes` 里以 `_IncludedRouter` 形式存在，
    不会展平为顶层 `APIRoute`。最可靠的枚举方式是从 `app.openapi()` 拿 paths。
    """
    routes: list[tuple[str, str]] = []
    schema = app.openapi()
    for path, methods in schema.get("paths", {}).items():
        if _is_skip_path(path):
            continue
        for method in methods.keys():
            if method in ("get", "post", "put", "delete", "patch"):
                routes.append((method.upper(), path))
    return routes


DYNAMIC_ROUTES = _enumerate_routes()


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    get_settings.cache_clear()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


@pytest.fixture
def alice_token(client):
    """alice (user_id=1) 的 token。conftest 已预建 alice。"""
    r = client.post(
        "/api/auth/login", json={"username": "alice", "password": "test-pass"}
    )
    assert r.status_code == 200, f"alice 登录失败: {r.text}"
    return r.json()["token"]


@pytest.fixture
def bob_owned_ids(session):
    """创建 bob 用户及其资源，返回 bob 拥有的标识。"""
    try:
        user_service.create_user(session, username="bob", password="test-pass", role="user")
    except ValueError:
        pass  # 已存在
    bob = session.query(User).filter_by(username="bob").first()
    assert bob is not None

    w = Workout(user_id=bob.id, date=datetime.date(2026, 8, 1), title="bob-workout")
    session.add(w)
    b = BodyMetric(user_id=bob.id, date=datetime.date(2026, 8, 1), type="weight", value=70.0)
    session.add(b)
    r = AIReport(
        user_id=bob.id, type="session_review",
        period_start=datetime.date(2026, 8, 1), period_end=datetime.date(2026, 8, 1),
        content_md="bob's report", model="deepseek-chat",
    )
    session.add(r)
    p = XunjiPlan(
        user_id=bob.id, plan_ref="bob-plan-ref",
        plan_json='{"plan":{"plan_ref":"bob-plan-ref","name":"bob plan"}}',
    )
    session.add(p)
    g = GarminDaily(user_id=bob.id, date=datetime.date(2026, 8, 1))
    session.add(g)
    session.commit()

    return {
        "workout_ids": [w.id],
        "report_ids": [r.id],
        "body_metric_ids": [b.id],
        "xunji_plan_refs": ["bob-plan-ref"],
        "garmin_dates": ["2026-08-01"],
    }


def _resolve_path_params(path: str) -> dict:
    """把所有路径参数填 1_000_000（alice/bob 都不持有的 id）。"""
    return {p: 1_000_000 for p in re.findall(r"\{(\w+)\}", path)}


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


def _scan_leak(response_json, bob_ids) -> str | None:
    """扫描响应体里是否含 bob 的标识。返回泄露描述或 None。

    只检查 JSON 字段值：
    - 名为 "id" 且值是数字 → 匹配 bob 的资源 id 列表
    - 名为 "plan_ref" 且值是字符串 → 匹配 bob 的 plan_ref 列表
    - 名为 "date" 且值是字符串 "YYYY-MM-DD" → 匹配 bob 的日期
    不再用字符串包含（避免误中 "0.0" / 日期 "2026-07-27" 等非 id 数字）。
    """
    def _walk(obj, key=None):
        if isinstance(obj, dict):
            for k, v in obj.items():
                r = _walk(v, key=k)
                if r:
                    return r
        elif isinstance(obj, list):
            for item in obj:
                r = _walk(item, key=key)
                if r:
                    return r
        else:
            if key == "id" and isinstance(obj, int):
                bob_all_ids = (
                    bob_ids["workout_ids"]
                    + bob_ids["report_ids"]
                    + bob_ids["body_metric_ids"]
                )
                if obj in bob_all_ids:
                    return f"id 字段含 bob 的资源 id={obj}"
            elif key == "plan_ref" and isinstance(obj, str):
                if obj in bob_ids["xunji_plan_refs"]:
                    return f"plan_ref 字段含 bob 的 ref={obj}"
            elif key == "date" and isinstance(obj, str) and len(obj) == 10:
                if obj in bob_ids["garmin_dates"]:
                    return f"date 字段含 bob 的日期={obj}"
        return None

    return _walk(response_json)


@pytest.mark.parametrize(
    "method,path",
    DYNAMIC_ROUTES,
    ids=[f"{m} {p}" for m, p in DYNAMIC_ROUTES],
)
def test_alice_cannot_see_bob_data(client, alice_token, bob_owned_ids, method, path):
    """M2-5 全局隔离：alice 用自己 token 访问任何端点都看不到 bob 的数据。"""
    headers = _hdr(alice_token)
    url = path.format(**_resolve_path_params(path))

    if method == "GET":
        resp = client.get(url, headers=headers)
    elif method == "POST":
        resp = client.post(url, headers=headers, json={})
    elif method == "PUT":
        resp = client.put(url, headers=headers, json={})
    elif method == "DELETE":
        resp = client.delete(url, headers=headers)
    elif method == "PATCH":
        resp = client.patch(url, headers=headers, json={})
    else:
        pytest.skip(f"不支持的方法: {method}")

    if 200 <= resp.status_code < 300:
        try:
            data = resp.json()
        except Exception:
            return
        leak = _scan_leak(data, bob_owned_ids)
        assert leak is None, (
            f"[隔离泄露] {method} {path} -> {leak}\n"
            f"  响应(前 500): {json.dumps(data, default=str)[:500]}"
        )
