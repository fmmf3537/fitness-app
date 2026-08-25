"""V2-8 计划级 AI 点评（type='plan_review'）测试。

覆盖：
- 结构化 JSON（plan_review_v1）解析与校验（非法动作名/非法 field 被拒）；
- generate_plan_review：生成落库、无计划日返回 None + 可读原因、
  幂等覆盖（先删旧再生成）、白名单校验失败重试 1 次、重试仍失败抛错不落库；
- 上下文组装：最近一次同类型 workout + 近4周同部位容量 + 恢复指标 + 体重趋势；
- API：POST /api/plans/review/{date}（鉴权/202/409/无计划 404）、
  GET /api/plans/review/{date}（最新一条/404）、status 轮询端点。
全部 mock（fake chat_fn / 注入 runner），零真实外呼。
"""
import json
import threading
import time
from datetime import date, timedelta

import pytest
from tests.conftest import make_garmin_activity, make_xunji_train

import app.main  # noqa: F401  提前触发 app.config 加载（.env override=True），保证测试用 tmp 库
from app.models import AIReport, BodyMetric, GarminDaily, XunjiPlan
from app.services.fuse import fuse_workout

TARGET = date(2026, 8, 12)
PREV = date(2026, 8, 8)

VALID_REVIEW_JSON = {
    "schema": "plan_review_v1",
    "plan_date": TARGET.isoformat(),
    "modifications": [
        {"movement": "杠铃卧推", "field": "weight", "from": "32.5kg", "to": "35kg",
         "reason": "上次完成轻松，渐进超负荷"},
        {"movement": "双杠臂屈伸", "field": "sets", "from": "3组", "to": "4组",
         "reason": "容量不足，补一组"},
    ],
}

VALID_CONTENT = (
    "## 计划点评\n本次胸部计划整体合理，重量可小幅上调。\n\n"
    "```json\n" + json.dumps(VALID_REVIEW_JSON, ensure_ascii=False) + "\n```\n"
)


def _make_plan(session, days=None, *, status=None, date_from=None, date_to=None, user_id=1):
    if days is None:
        days = [
            {"datestr": TARGET.isoformat(), "workout": {"name": "胸·三头·腹", "movements": [
                {"name": "杠铃卧推",
                 "target_sets": [{"weight": 32.5, "unit": "kg", "reps": 6}]},
                {"name": "双杠臂屈伸",
                 "target_sets": [{"weight": 82.5, "unit": "kg", "reps": 10}]},
            ]}},
        ]
    plan = {"plan_ref": "universal:1", "name": "三分化·健身房"}
    if status:
        plan["status"] = status
    row = XunjiPlan(
        plan_ref="universal:1",
        plan_json=json.dumps({"plan": plan, "days": days}, ensure_ascii=False),
        date_from=date_from or (TARGET - timedelta(days=7)),
        date_to=date_to or (TARGET + timedelta(days=30)),
        user_id=user_id,
    )
    session.add(row)
    session.commit()
    return row


def _make_prev_workout(session, title="胸·三头·腹"):
    x = make_xunji_train(
        session, PREV, localid="1", title=title,
        movements=[{"name": "杠铃卧推",
                    "sets": [{"weight": "32.5", "unit": "kg", "reps": "6", "done": True}]}],
    )
    g = make_garmin_activity(session, PREV, activity_id="g1")
    return fuse_workout(session, PREV, xunji=x, garmin=g, match_status="auto_matched")


def _fake_chat(content=VALID_CONTENT, calls=None):
    def chat(messages):
        if calls is not None:
            calls.append(messages)
        return {"content": content, "prompt_tokens": 120, "completion_tokens": 60}
    return chat


# ---------- JSON 解析与校验 ----------


class TestParsePlanReview:
    def test_parses_valid_content(self):
        from app.services.ai import parse_plan_review

        data = parse_plan_review(VALID_CONTENT)
        assert data["schema"] == "plan_review_v1"
        assert data["plan_date"] == TARGET.isoformat()
        assert len(data["modifications"]) == 2

    def test_missing_json_block_rejected(self):
        from app.services.ai import PlanReviewParseError, parse_plan_review

        with pytest.raises(PlanReviewParseError):
            parse_plan_review("## 只有 Markdown")

    def test_wrong_schema_rejected(self):
        from app.services.ai import PlanReviewParseError, parse_plan_review

        bad = dict(VALID_REVIEW_JSON, schema="next_advice_v1")
        content = "```json\n" + json.dumps(bad, ensure_ascii=False) + "\n```"
        with pytest.raises(PlanReviewParseError):
            parse_plan_review(content)

    def test_illegal_movement_name_rejected(self):
        from app.services.ai import PlanReviewParseError, parse_plan_review

        bad = json.loads(json.dumps(VALID_REVIEW_JSON))
        bad["modifications"][0]["movement"] = "深蹲大王"
        content = "```json\n" + json.dumps(bad, ensure_ascii=False) + "\n```"
        with pytest.raises(PlanReviewParseError, match="深蹲大王"):
            parse_plan_review(content)

    def test_illegal_field_rejected(self):
        from app.services.ai import PlanReviewParseError, parse_plan_review

        bad = json.loads(json.dumps(VALID_REVIEW_JSON))
        bad["modifications"][0]["field"] = "whatever"
        content = "```json\n" + json.dumps(bad, ensure_ascii=False) + "\n```"
        with pytest.raises(PlanReviewParseError):
            parse_plan_review(content)

    def test_missing_reason_rejected(self):
        from app.services.ai import PlanReviewParseError, parse_plan_review

        bad = json.loads(json.dumps(VALID_REVIEW_JSON))
        del bad["modifications"][0]["reason"]
        content = "```json\n" + json.dumps(bad, ensure_ascii=False) + "\n```"
        with pytest.raises(PlanReviewParseError):
            parse_plan_review(content)

    def test_empty_modifications_allowed(self):
        from app.services.ai import parse_plan_review

        data = json.loads(json.dumps(VALID_REVIEW_JSON))
        data["modifications"] = []
        content = "```json\n" + json.dumps(data, ensure_ascii=False) + "\n```"
        assert parse_plan_review(content)["modifications"] == []


# ---------- 生成与落库 ----------


class TestGeneratePlanReview:
    def test_generates_and_saves_report(self, session):
        from app.services.ai import generate_plan_review

        _make_plan(session)
        _make_prev_workout(session)
        session.add(GarminDaily(date=TARGET - timedelta(days=1), resting_hr=52,
                                hrv_status="balanced"))
        session.add(BodyMetric(date=TARGET - timedelta(days=2), type="weight",
                               value=72.4, unit="kg"))
        session.commit()

        report = generate_plan_review(session, TARGET, chat_fn=_fake_chat())

        assert report is not None
        assert report.type == "plan_review"
        assert report.workout_id is None
        assert report.period_start == TARGET
        assert report.period_end == TARGET
        assert report.prompt_tokens == 120
        assert report.cost_estimate > 0
        assert "plan_review_v1" in report.content_md

    def test_accepts_date_string(self, session):
        from app.services.ai import generate_plan_review

        _make_plan(session)
        report = generate_plan_review(session, TARGET.isoformat(), chat_fn=_fake_chat())
        assert report is not None
        assert report.period_start == TARGET

    def test_returns_none_without_plan_day(self, session):
        from app.services.ai import generate_plan_review
        from app.services.plans import plan_day_skip_reason

        calls = []
        assert generate_plan_review(session, TARGET, chat_fn=_fake_chat(calls=calls)) is None
        assert calls == []  # 无计划日不调用模型
        assert session.query(AIReport).count() == 0
        assert "缓存为空" in plan_day_skip_reason(session, TARGET)

    def test_idempotent_overwrite(self, session):
        """计划点评允许覆盖：同日已有 plan_review 先删旧再生成（与 next_advice 跳过策略不同）。"""
        from app.services.ai import generate_plan_review

        _make_plan(session)
        generate_plan_review(session, TARGET, chat_fn=_fake_chat())
        r2 = generate_plan_review(session, TARGET, chat_fn=_fake_chat())

        rows = session.query(AIReport).filter_by(type="plan_review").all()
        assert len(rows) == 1  # 旧记录已删除，同日仅保留最新一条
        assert rows[0].id == r2.id

    def test_retry_once_on_invalid_output(self, session):
        """首次输出非法动作名 → 重试 1 次；第二次合规则正常落库。"""
        from app.services.ai import generate_plan_review

        _make_plan(session)
        bad = json.loads(json.dumps(VALID_REVIEW_JSON))
        bad["modifications"][0]["movement"] = "不存在的动作"
        bad_content = "```json\n" + json.dumps(bad, ensure_ascii=False) + "\n```"
        outputs = iter([bad_content, VALID_CONTENT])
        calls = []

        def chat(messages):
            calls.append(messages)
            return {"content": next(outputs), "prompt_tokens": 1, "completion_tokens": 1}

        report = generate_plan_review(session, TARGET, chat_fn=chat)

        assert report is not None
        assert len(calls) == 2
        assert "plan_review_v1" in report.content_md

    def test_raises_after_retry_still_invalid(self, session):
        """重试后仍非法 → 抛错且不落库。"""
        from app.services.ai import PlanReviewParseError, generate_plan_review

        _make_plan(session)
        bad = json.loads(json.dumps(VALID_REVIEW_JSON))
        bad["modifications"][0]["movement"] = "不存在的动作"
        bad_content = "```json\n" + json.dumps(bad, ensure_ascii=False) + "\n```"
        calls = []

        report = None
        with pytest.raises(PlanReviewParseError):
            report = generate_plan_review(session, TARGET,
                                          chat_fn=_fake_chat(bad_content, calls=calls))
        assert report is None
        assert len(calls) == 2  # 首次 + 重试 1 次
        assert session.query(AIReport).count() == 0


# ---------- prompt 组装与上下文 ----------


class TestBuildPlanReviewPrompt:
    def test_injects_plan_context_and_whitelist(self, session):
        from app.movements import load_movement_names
        from app.services import ai as ai_service

        _make_plan(session)
        w = _make_prev_workout(session)
        session.add(BodyMetric(date=TARGET - timedelta(days=2), type="weight",
                               value=72.4, unit="kg"))
        session.commit()

        from app.services.plans import query_plan_day
        plan_day = query_plan_day(session, TARGET)
        last = ai_service.query_last_similar_workout(session, plan_day, TARGET)
        trend = ai_service.query_part_volume_trend(session, plan_day, TARGET)
        recovery = ai_service.query_recovery_summary(session, TARGET)

        messages = ai_service.build_plan_review_prompt(
            plan_day, last, trend, recovery, load_movement_names())

        system = messages[0]["content"]
        assert "plan_review_v1" in system
        assert "杠铃卧推" in system  # 白名单注入
        assert "只读" in system  # 明确禁止修改计划写回

        user = messages[1]["content"]
        assert TARGET.isoformat() in user
        assert "三分化·健身房" in user
        assert "杠铃卧推" in user
        assert PREV.isoformat() in user  # 最近一次同类型 workout
        assert "72.4" in user  # 体重趋势


class TestQueryLastSimilarWorkout:
    def test_title_match_preferred(self, session):
        from app.services import ai as ai_service
        from app.services.plans import query_plan_day

        _make_plan(session)
        _make_prev_workout(session, title="胸·三头·腹")

        plan_day = query_plan_day(session, TARGET)
        last = ai_service.query_last_similar_workout(session, plan_day, TARGET)

        assert last is not None
        assert last["date"] == PREV.isoformat()
        assert last["movements"][0]["name"] == "杠铃卧推"

    def test_movement_overlap_fallback(self, session):
        from app.services import ai as ai_service
        from app.services.plans import query_plan_day

        _make_plan(session)
        _make_prev_workout(session, title="完全不同的标题")  # 标题不匹配，但动作重叠

        plan_day = query_plan_day(session, TARGET)
        last = ai_service.query_last_similar_workout(session, plan_day, TARGET)

        assert last is not None
        assert last["date"] == PREV.isoformat()

    def test_no_history_returns_none(self, session):
        from app.services import ai as ai_service
        from app.services.plans import query_plan_day

        _make_plan(session)
        plan_day = query_plan_day(session, TARGET)
        assert ai_service.query_last_similar_workout(session, plan_day, TARGET) is None


# ---------- API ----------


@pytest.fixture
def client(env_vars, session, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api.plans import PlanReviewManager, get_plan_review_manager
    from app.config import get_settings
    from app.db import get_session
    from app.main import app

    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    get_settings.cache_clear()

    calls = []
    gate = threading.Event()
    gate.set()
    flags = {"fail": False}

    def fake_runner(date_str, user_id=None):
        calls.append(date_str)
        gate.wait(timeout=5)
        if flags["fail"]:
            raise RuntimeError("llm down")

    def override_session():
        yield session

    manager = PlanReviewManager(runner=fake_runner)
    app.dependency_overrides[get_plan_review_manager] = lambda: manager
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as c:
        c.review_calls = calls
        c.gate = gate
        c.flags = flags
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def auth(client, session):
    from app.services import users as _us
    try:
        _us.create_user(session, username="alice", password="test-pass", role="user")
    except ValueError:
        pass  # alice 已由 conftest session 预建（id=1）
    _b = client.post("/api/auth/login", json={"username": "alice", "password": "test-pass"}).json()
    return {"Authorization": f"Bearer {_b['token']}"}


def _wait_review_done(client, auth, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/plans/review/{TARGET.isoformat()}/status",
                          headers=auth).json()
        if not body["running"]:
            return body
        time.sleep(0.02)
    raise AssertionError("后台计划点评未在超时内结束")


class TestPlanReviewAPI:
    def test_requires_auth(self, client):
        assert client.post(f"/api/plans/review/{TARGET.isoformat()}").status_code == 401
        assert client.get(f"/api/plans/review/{TARGET.isoformat()}").status_code == 401
        assert client.get(
            f"/api/plans/review/{TARGET.isoformat()}/status").status_code == 401
        assert client.review_calls == []

    def test_post_starts_background(self, client, auth, session):
        _make_plan(session)
        resp = client.post(f"/api/plans/review/{TARGET.isoformat()}", headers=auth)
        assert resp.status_code == 202
        assert resp.json() == {"status": "started", "date": TARGET.isoformat()}

        body = _wait_review_done(client, auth)
        assert client.review_calls == [TARGET.isoformat()]
        assert body["error"] is None

    def test_post_duplicate_returns_409(self, client, auth, session):
        _make_plan(session)
        client.gate.clear()
        resp = client.post(f"/api/plans/review/{TARGET.isoformat()}", headers=auth)
        assert resp.status_code == 202

        resp2 = client.post(f"/api/plans/review/{TARGET.isoformat()}", headers=auth)
        assert resp2.status_code == 409

        client.gate.set()
        _wait_review_done(client, auth)
        assert client.review_calls == [TARGET.isoformat()]

    def test_post_no_plan_day_returns_404_with_reason(self, client, auth, session):
        resp = client.post(f"/api/plans/review/{TARGET.isoformat()}", headers=auth)
        assert resp.status_code == 404
        assert "缓存为空" in resp.json()["detail"]
        assert client.review_calls == []

    def test_post_failed_status(self, client, auth, session):
        _make_plan(session)
        client.flags["fail"] = True
        client.post(f"/api/plans/review/{TARGET.isoformat()}", headers=auth)

        body = _wait_review_done(client, auth)
        assert "llm down" in body["error"]

    def test_get_latest_review(self, client, auth, session):
        resp = client.get(f"/api/plans/review/{TARGET.isoformat()}", headers=auth)
        assert resp.status_code == 404

        session.add(AIReport(type="plan_review", period_start=TARGET, period_end=TARGET,
                             user_id=1, model="deepseek-chat", prompt_tokens=10,
                             completion_tokens=5, cost_estimate=0.001,
                             content_md=VALID_CONTENT))
        session.commit()

        resp = client.get(f"/api/plans/review/{TARGET.isoformat()}", headers=auth)
        assert resp.status_code == 200
        body = resp.json()
        assert body["type"] == "plan_review"
        assert body["date"] == TARGET.isoformat()
        assert "plan_review_v1" in body["content_md"]

    def test_get_ignores_other_types(self, client, auth, session):
        session.add(AIReport(type="next_advice", period_start=TARGET, period_end=TARGET,
                             user_id=1, content_md=VALID_CONTENT))
        session.commit()
        resp = client.get(f"/api/plans/review/{TARGET.isoformat()}", headers=auth)
        assert resp.status_code == 404
