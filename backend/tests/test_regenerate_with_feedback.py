"""V4-5 F3：对话驱动重新生成端点测试。

覆盖 6 类场景：
1. prompt 注入（build_session_review_prompt / build_next_advice_prompt）
2. session_review 重生成（含对话注入 + 删旧 + 落库）
3. 无对话重生成（feedback 为空）
4. 日限 5 次
5. next_advice 重生成（含反馈注入 / 无报告 404 / 无计划缓存 422）
6. API 鉴权/边界（未登录 401 / 不存在 workout 404）
"""
import json
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.adapters import llm
from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AIReport, LLMCall, ReportChatMessage, Workout
from app.services import ai as ai_service
from tests.test_ai import _recovery_dict, _workout_dict

DAY = date(2026, 8, 3)


# ---------- 共享夹具 ----------


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
def auth(client):
    token = client.post("/api/auth/login", json={"password": "test-pass"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _plan_day() -> dict:
    """构造一个最小可用的训记计划日（供 build_next_advice_prompt 调用）。"""
    return {
        "plan_ref": "p1",
        "plan_name": "测试计划",
        "date": "2026-08-05",
        "movements": [
            {
                "name": "杠铃划船",
                "sets": [{"weight": 60, "unit": "kg", "reps": 10}],
            }
        ],
    }


def _plan_day_movement_names() -> list[str]:
    """next_advice prompt 用的标准动作名表（含 build_next_advice_prompt 注入的动作）。"""
    return ["杠铃划船", "引体向上", "卧推"]


def _session_review_content() -> str:
    """合法的 session_review 输出（含评分 JSON 块）。"""
    return (
        "## 完成质量\n不错\n## 与历史对比\n持平\n"
        '```json\n{"schema":"session_review_v1","score":82,'
        '"subscores":{"completion":85,"intensity":80,"recovery_fit":82},'
        '"one_liner":"稳定发挥"}\n```'
    )


def _next_advice_content() -> str:
    """合法的 next_advice 输出（含 next_advice_v1 JSON 块，动作名在白名单内）。"""
    return (
        "## 计划对照\n按计划执行\n"
        '```json\n{"schema":"next_advice_v1","next_plan_date":"2026-08-05",'
        '"suggestions":[{"movement":"杠铃划船","category":"auto_writable",'
        '"original":{"weight":60,"reps":10},"suggested":{"weight":62,"reps":10},'
        '"reason":"渐进超负荷"}]}\n```'
    )


def _make_workout(session, day=DAY, **overrides) -> Workout:
    defaults = {
        "date": day,
        "title": "背部训练",
        "match_status": "auto_matched",
        "duration_s": 3600,
        "calories": 400,
        "avg_hr": 118,
        "max_hr": 152,
    }
    defaults.update(overrides)
    w = Workout(**defaults)
    session.add(w)
    session.commit()
    return w


def _make_report(
    session,
    workout_id: int,
    rtype: str = "session_review",
    day: date | None = None,
    created_at: datetime | None = None,
) -> AIReport:
    """构造一条 AIReport（默认 created_at=now 本地）。"""
    report = AIReport(
        type=rtype,
        workout_id=workout_id,
        period_start=day or DAY,
        period_end=day or DAY,
        model="deepseek-chat",
        prompt_tokens=100,
        completion_tokens=20,
        cost_estimate=0.0001,
        content_md="旧报告",
    )
    if created_at is not None:
        report.created_at = created_at
    session.add(report)
    session.commit()
    return report


def _make_regen_llm_call(
    session,
    workout_id: int,
    rtype: str = "session_review",
    created_at: datetime | None = None,
) -> LLMCall:
    """构造一条 llm_call 记账行（purpose=「{rtype}_regen:w{id}」），模拟真实重生成路径。"""
    call = LLMCall(
        provider="deepseek",
        model="deepseek-chat",
        purpose=f"{rtype}_regen:w{workout_id}",
        prompt_tokens=100,
        completion_tokens=20,
        cost_estimate=0.0001,
        status="ok",
    )
    if created_at is not None:
        call.created_at = created_at
    session.add(call)
    session.commit()
    return call


# ---------- 1. prompt 注入 ----------


class TestPromptInjection:
    """build_session_review_prompt / build_next_advice_prompt 注入 feedback。"""

    def test_session_review_with_feedback_injects_section_and_appends_system(self):
        feedback = ["用户：那天我感冒", "教练：注意休息"]
        messages = ai_service.build_session_review_prompt(
            _workout_dict(), {}, _recovery_dict(), feedback=feedback
        )
        assert len(messages) == 2
        user = messages[1]["content"]
        # 用户反馈段标题
        assert "# 用户反馈（来自本次训练后的讨论，请结合进点评/建议）" in user
        # 两条内容按调用方前缀渲染
        assert "- 用户：那天我感冒" in user
        assert "- 教练：注意休息" in user
        # system 末追加附加要求
        assert "须与之相符，不得与之矛盾" in messages[0]["content"]
        # 顺序：历史段 → 用户反馈段 → 恢复段
        history_idx = user.find("近4周同动作历史")
        feedback_idx = user.find("# 用户反馈")
        recovery_idx = user.find("# 近7天恢复数据")
        assert history_idx >= 0
        assert feedback_idx > history_idx
        assert recovery_idx > feedback_idx

    def test_session_review_without_feedback_byte_identical(self):
        """回归红线：feedback 为 None 时输出与原版逐字节一致。"""
        from app.services.ai import build_session_review_prompt

        base = build_session_review_prompt(_workout_dict(), {}, _recovery_dict())
        with_kwarg = build_session_review_prompt(
            _workout_dict(), {}, _recovery_dict(), feedback=None
        )
        assert base == with_kwarg
        # 也不应含「用户反馈」段或附加要求
        assert "用户反馈" not in base[1]["content"]
        assert "须与之相符" not in base[0]["content"]

    def test_session_review_with_empty_feedback_list_unchanged(self):
        """回归红线：feedback=[]（空列表）视为无反馈。"""
        from app.services.ai import build_session_review_prompt

        base = build_session_review_prompt(_workout_dict(), {}, _recovery_dict())
        with_empty = build_session_review_prompt(
            _workout_dict(), {}, _recovery_dict(), feedback=[]
        )
        assert base == with_empty

    def test_next_advice_with_feedback_injects_section_and_appends_system(self):
        from app.services.ai import build_next_advice_prompt

        feedback = ["用户：今天肩膀酸", "教练：降低肩推重量"]
        messages = build_next_advice_prompt(
            _workout_dict(), _plan_day(), _recovery_dict(),
            _plan_day_movement_names(), feedback=feedback,
        )
        user = messages[1]["content"]
        assert "# 用户反馈（来自本次训练后的讨论，请结合进建议）" in user
        assert "- 用户：今天肩膀酸" in user
        assert "- 教练：降低肩推重量" in user
        assert "须与之相符，不得与之矛盾" in messages[0]["content"]
        # 顺序：计划日段 → 用户反馈段 → 恢复指标段
        plan_idx = user.find("# 训记官方计划")
        feedback_idx = user.find("# 用户反馈")
        recovery_idx = user.find("# 近7天恢复指标")
        assert plan_idx >= 0
        assert feedback_idx > plan_idx
        assert recovery_idx > feedback_idx

    def test_next_advice_without_feedback_byte_identical(self):
        from app.services.ai import build_next_advice_prompt

        base = build_next_advice_prompt(
            _workout_dict(), _plan_day(), _recovery_dict(),
            _plan_day_movement_names(),
        )
        with_kwarg = build_next_advice_prompt(
            _workout_dict(), _plan_day(), _recovery_dict(),
            _plan_day_movement_names(), feedback=None,
        )
        assert base == with_kwarg
        assert "用户反馈" not in base[1]["content"]
        assert "须与之相符" not in base[0]["content"]


# ---------- 2. session_review 重生成（含对话注入 + 删旧 + 落库） ----------


class TestRegenerateSessionReview:
    def test_regenerates_with_chat_feedback(self, session):
        w = _make_workout(session)
        old = _make_report(session, w.id, "session_review")
        # 3 条对话（user/assistant/user，按 id 正序取尾部）
        for i, (role, content) in enumerate([
            ("user", "那天我感冒了"),
            ("assistant", "建议降重量"),
            ("user", "已减到 50kg"),
        ]):
            session.add(ReportChatMessage(
                report_id=old.id, role=role, content=content,
            ))
        session.commit()

        captured = []

        def fake_chat(messages):
            captured.append(messages)
            return {
                "content": _session_review_content(),
                "prompt_tokens": 100, "completion_tokens": 20,
                "model": "deepseek-chat",
            }

        new_report = ai_service.regenerate_session_review_with_feedback(
            session, w.id, chat_fn=fake_chat
        )

        assert len(captured) == 1
        msgs = captured[0]
        user_msg = msgs[1]["content"]
        # user 段含「用户反馈」标题 + 3 行内容（按 id 正序）
        assert "# 用户反馈（来自本次训练后的讨论，请结合进点评/建议）" in user_msg
        assert "- 用户：那天我感冒了" in user_msg
        assert "- 教练：建议降重量" in user_msg
        assert "- 用户：已减到 50kg" in user_msg
        # system 末追加附加要求
        assert "须与之相符，不得与之矛盾" in msgs[0]["content"]

        # 旧报告被删，新报告落库且 workout_id/type 正确（remaining 计数断言见下方）
        persisted = session.get(AIReport, new_report.id)
        assert persisted is not None
        assert persisted.workout_id == w.id
        assert persisted.type == "session_review"
        # 同 type 该 workout 仅剩新报告
        remaining = session.query(AIReport).filter(
            AIReport.workout_id == w.id, AIReport.type == "session_review",
        ).all()
        assert len(remaining) == 1
        assert remaining[0].id == new_report.id

    def test_regenerates_without_chat_feedback(self, session):
        """旧报告无 chat → feedback 为空，仍成功重生成。"""
        w = _make_workout(session)
        old = _make_report(session, w.id, "session_review")

        captured = []

        def fake_chat(messages):
            captured.append(messages)
            return {
                "content": _session_review_content(),
                "prompt_tokens": 10, "completion_tokens": 5,
                "model": "deepseek-chat",
            }

        new_report = ai_service.regenerate_session_review_with_feedback(
            session, w.id, chat_fn=fake_chat
        )

        # prompt 不含「用户反馈」段、不含附加要求
        msgs = captured[0]
        assert "用户反馈" not in msgs[1]["content"]
        assert "须与之相符" not in msgs[0]["content"]

        # 同 type 该 workout 仅剩新报告
        remaining = session.query(AIReport).filter(
            AIReport.workout_id == w.id, AIReport.type == "session_review",
        ).all()
        assert len(remaining) == 1
        assert remaining[0].id == new_report.id
        assert new_report.workout_id == w.id

    def test_raises_when_workout_missing(self, session):
        with pytest.raises(ValueError, match="workout 9999 不存在"):
            ai_service.regenerate_session_review_with_feedback(session, 9999)

    def test_collect_feedback_respects_window(self, session):
        """REGEN_FEEDBACK_WINDOW=10：超过 10 条时只取尾部 10 条。"""
        w = _make_workout(session)
        old = _make_report(session, w.id, "session_review")
        # 12 条对话（user/assistant 交替）
        for i in range(12):
            role = "user" if i % 2 == 0 else "assistant"
            session.add(ReportChatMessage(
                report_id=old.id, role=role, content=f"消息{i}",
            ))
        session.commit()

        captured = []

        def fake_chat(messages):
            captured.append(messages)
            return {
                "content": _session_review_content(),
                "prompt_tokens": 1, "completion_tokens": 1,
                "model": "deepseek-chat",
            }

        ai_service.regenerate_session_review_with_feedback(
            session, w.id, chat_fn=fake_chat
        )
        user = captured[0][1]["content"]
        # 只取尾部 10 条（消息 2..11），即 id 较大的 10 条
        lines = user.splitlines()
        assert "- 用户：消息0" not in lines
        assert "- 教练：消息1" not in lines
        assert "- 用户：消息2" in lines
        assert "- 教练：消息11" in lines
        # 计数：恰好 10 条（5 user + 5 assistant）
        feedback_block = user[user.find("# 用户反馈"):user.find("# 近7天恢复数据")]
        feedback_lines = [ln for ln in feedback_block.splitlines() if ln.startswith("- ")]
        assert len(feedback_lines) == 10


# ---------- 4. 日限 5 次 ----------


class TestDailyRegenLimit:
    def test_service_raises_when_count_at_limit(self, session):
        """V4-5 fix1：造 5 条当日 llm_call(purpose=session_review_regen:w{id})
        → 第 6 次抛 RegenerateLimitError。"""
        w = _make_workout(session)
        now = datetime.now()
        for i in range(5):
            _make_regen_llm_call(session, w.id, "session_review", created_at=now)

        def fake_chat(messages):
            return {"content": "x", "prompt_tokens": 1, "completion_tokens": 1}

        with pytest.raises(ai_service.RegenerateLimitError) as exc_info:
            ai_service.regenerate_session_review_with_feedback(
                session, w.id, chat_fn=fake_chat
            )
        assert "每日重生成上限 5 次" in str(exc_info.value)

    def test_api_returns_429_with_chinese_detail(self, client, auth, session):
        w = _make_workout(session)
        now = datetime.now()
        for i in range(5):
            _make_regen_llm_call(session, w.id, "session_review", created_at=now)

        resp = client.post(
            f"/api/ai-reports/session_review/{w.id}/regenerate_with_feedback",
            headers=auth,
        )
        assert resp.status_code == 429
        assert "每日重生成上限 5 次" in resp.json()["detail"]

    def test_count_only_for_today(self, session):
        """V4-5 fix1：昨日的 llm_call 行不计入日限（仅当日 created_at 计入）。"""
        w = _make_workout(session)
        # 5 条昨日
        yesterday = datetime(2026, 8, 2, 10, 0, 0)
        for i in range(5):
            _make_regen_llm_call(session, w.id, "session_review", created_at=yesterday)

        def fake_chat(messages):
            return {"content": "x", "prompt_tokens": 1, "completion_tokens": 1}

        # 应正常通过限检（昨日 5 条不算今日）
        new = ai_service.regenerate_session_review_with_feedback(
            session, w.id, chat_fn=fake_chat
        )
        assert new is not None

    def test_other_workouts_do_not_count(self, session):
        """V4-5 fix1：其他 workout 的同 purpose 行不计入日限。"""
        w1 = _make_workout(session)
        w2 = _make_workout(session)
        now = datetime.now()
        # w2 今日已用满 5 次，但 w1 不应受影响
        for i in range(5):
            _make_regen_llm_call(session, w2.id, "session_review", created_at=now)

        def fake_chat(messages):
            return {"content": "x", "prompt_tokens": 1, "completion_tokens": 1}

        new = ai_service.regenerate_session_review_with_feedback(
            session, w1.id, chat_fn=fake_chat
        )
        assert new is not None

    def test_real_closed_loop_5_ok_then_429(self, session, monkeypatch):
        """V4-5 fix1 真实闭环：不注入 chat_fn，monkeypatch llm.chat 模拟真实
        LLMCall 记账——连续重生成 5 次成功、第 6 次抛 RegenerateLimitError。

        fake 模拟 llm.chat 行为：手动写一条 LLMCall(purpose=入参 purpose, ...) 并
        commit，返回合法 content。证明护栏在真实路径生效（无 chat_fn 注入时
        generate_session_review 的默认闭包仍会透传 purpose 到 llm.chat）。
        """
        from app.services import ai as ai_module

        w = _make_workout(session)
        # 造一条旧 session_review 让 regenerate 能删旧 + 走 generate_session_review 完整路径
        _make_report(session, w.id, "session_review")

        recorded_purposes: list[str | None] = []

        def fake_chat(messages, *, session=None, purpose=None, **opts):
            recorded_purposes.append(purpose)
            session.add(LLMCall(
                provider="deepseek",
                model="deepseek-chat",
                purpose=purpose,
                prompt_tokens=10,
                completion_tokens=20,
                cost_estimate=0.0001,
                status="ok",
            ))
            session.commit()
            return {
                "content": _session_review_content(),
                "prompt_tokens": 10, "completion_tokens": 20,
                "model": "deepseek-chat",
            }

        monkeypatch.setattr(ai_module.llm, "chat", fake_chat)

        # 连续 5 次成功
        for i in range(5):
            report = ai_service.regenerate_session_review_with_feedback(
                session, w.id
            )
            assert report is not None
            assert report.type == "session_review"

        # 第 6 次触发护栏
        with pytest.raises(ai_service.RegenerateLimitError) as exc_info:
            ai_service.regenerate_session_review_with_feedback(session, w.id)
        assert "每日重生成上限 5 次" in str(exc_info.value)

        # 真实闭环：每次 generate_session_review 闭包传入的 purpose 都是 regen 串
        expected_purpose = f"session_review_regen:w{w.id}"
        assert recorded_purposes[:5] == [expected_purpose] * 5


# ---------- 5. next_advice 重生成 ----------


class TestRegenerateNextAdvice:
    def test_regenerates_with_feedback(self, session):
        """有对话的 next_advice 重生成注入反馈成功。"""
        from app.models import XunjiPlan

        w = _make_workout(session)
        old = _make_report(session, w.id, "next_advice")
        for role, content in [
            ("user", "明天想加重量"),
            ("assistant", "可以尝试 +2.5kg"),
        ]:
            session.add(ReportChatMessage(
                report_id=old.id, role=role, content=content,
            ))
        # 造一个最小的训记计划缓存（供 query_next_plan_day 命中）
        plan_json = json.dumps({
            "plan": {"name": "测试计划"},
            "days": [{
                "date": "2026-08-05",
                "movements": [{"name": "杠铃划船",
                                "sets": [{"weight": 60, "unit": "kg", "reps": 10}]}],
            }],
        })
        session.add(XunjiPlan(
            plan_ref="p1", plan_json=plan_json,
            date_from=date(2026, 8, 1), date_to=date(2026, 8, 31),
        ))
        session.commit()

        captured = []

        def fake_chat(messages):
            captured.append(messages)
            return {"content": _next_advice_content(), "prompt_tokens": 1, "completion_tokens": 1}

        new_report = ai_service.regenerate_next_advice_with_feedback(
            session, w.id, chat_fn=fake_chat
        )

        assert new_report is not None
        assert len(captured) == 1
        user = captured[0][1]["content"]
        assert "# 用户反馈（来自本次训练后的讨论，请结合进建议）" in user
        assert "- 用户：明天想加重量" in user
        assert "- 教练：可以尝试 +2.5kg" in user
        # 同 type 该 workout 仅剩新报告
        remaining = session.query(AIReport).filter(
            AIReport.workout_id == w.id, AIReport.type == "next_advice",
        ).all()
        assert len(remaining) == 1
        assert remaining[0].id == new_report.id
        assert new_report.workout_id == w.id
        assert new_report.type == "next_advice"

    def test_service_raises_when_no_next_advice_report(self, session):
        """该 workout 当前无 next_advice 报告 → ValueError（API 层转 404）。"""
        w = _make_workout(session)
        with pytest.raises(ValueError, match="该训练暂无下次建议"):
            ai_service.regenerate_next_advice_with_feedback(session, w.id)

    def test_service_returns_none_when_no_plan_cache(self, session, monkeypatch):
        """无计划缓存（mock generate_next_advice 返回 None 路径）→ API 422。"""
        # 间接通过 API 测：构造一个 next_advice 报告让 _check_regen_limit/404 通过，
        # 然后 mock generate_next_advice 让其返回 None（模拟无计划缓存）。
        w = _make_workout(session)
        old = _make_report(session, w.id, "next_advice")

        monkeypatch.setattr(
            ai_service, "generate_next_advice",
            lambda *a, **kw: None,
        )

        result = ai_service.regenerate_next_advice_with_feedback(session, w.id)
        assert result is None
        # 旧报告已删（删旧先生成的约定）
        assert session.get(AIReport, old.id) is None

    def test_api_404_when_no_next_advice_report(self, client, auth, session):
        w = _make_workout(session)
        resp = client.post(
            f"/api/ai-reports/next_advice/{w.id}/regenerate_with_feedback",
            headers=auth,
        )
        assert resp.status_code == 404
        assert "该训练暂无下次建议" in resp.json()["detail"]

    def test_api_422_when_no_plan_cache(self, client, auth, session, monkeypatch):
        w = _make_workout(session)
        _make_report(session, w.id, "next_advice")
        monkeypatch.setattr(
            ai_service, "generate_next_advice",
            lambda *a, **kw: None,
        )
        resp = client.post(
            f"/api/ai-reports/next_advice/{w.id}/regenerate_with_feedback",
            headers=auth,
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "无训记计划缓存，无法生成下次建议"


# ---------- 6. API 鉴权/边界 ----------


class TestApiAuthAndBoundaries:
    def test_session_review_requires_auth(self, client):
        resp = client.post("/api/ai-reports/session_review/1/regenerate_with_feedback")
        assert resp.status_code == 401

    def test_next_advice_requires_auth(self, client):
        resp = client.post("/api/ai-reports/next_advice/1/regenerate_with_feedback")
        assert resp.status_code == 401

    def test_session_review_404_when_workout_missing(self, client, auth):
        resp = client.post(
            "/api/ai-reports/session_review/9999/regenerate_with_feedback",
            headers=auth,
        )
        assert resp.status_code == 404
        assert "workout 9999 不存在" in resp.json()["detail"]

    def test_next_advice_404_when_workout_missing(self, client, auth):
        resp = client.post(
            "/api/ai-reports/next_advice/9999/regenerate_with_feedback",
            headers=auth,
        )
        assert resp.status_code == 404

    def test_session_review_success_returns_serialized_report(self, client, auth, session):
        w = _make_workout(session)
        _make_report(session, w.id, "session_review")

        def fake_chat(messages, **kwargs):
            assert kwargs.get("purpose") == f"session_review_regen:w{w.id}"
            return {
                "content": _session_review_content(),
                "prompt_tokens": 10, "completion_tokens": 5,
                "model": "deepseek-chat",
            }
        monkeypatch_llm = pytest.MonkeyPatch()
        monkeypatch_llm.setattr(llm, "chat", fake_chat)
        try:
            resp = client.post(
                f"/api/ai-reports/session_review/{w.id}/regenerate_with_feedback",
                headers=auth,
            )
        finally:
            monkeypatch_llm.undo()

        assert resp.status_code == 200
        data = resp.json()
        assert "report" in data
        report = data["report"]
        assert report["type"] == "session_review"
        assert report["workout_id"] == w.id
        assert report["workout_title"] == w.title
