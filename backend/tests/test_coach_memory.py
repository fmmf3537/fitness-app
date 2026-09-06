"""V5-1 AI 教练长期记忆：服务层 CRUD + build_memory_section + API 全链路。"""
import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app
from app.models import CoachMemory, CoachPreference, CoachPreferenceDraft
from app.services import coach_memory as svc


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    from app.config import get_settings

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
def auth_user(client):
    """提示词中的 auth_user；与仓库惯例 auth 等价。"""
    token = client.post("/api/auth/login", json={"password": "test-pass"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


# ---------- 服务层 ----------


class TestCreatePreference:
    def test_create_new(self, session):
        row = svc.create_preference(session, content="深蹲注意右膝", tags="膝盖,伤病")
        assert row.id is not None
        assert row.content == "深蹲注意右膝"
        assert row.category == "manual"
        assert row.tags == "膝盖,伤病"
        assert row.source == "user"
        assert row.active is True

    def test_same_content_idempotent(self, session):
        r1 = svc.create_preference(session, content="同一条须知")
        r2 = svc.create_preference(session, content="同一条须知", tags="ignored")
        assert r1.id == r2.id
        assert session.query(CoachPreference).filter_by(content="同一条须知").count() == 1


class TestUpdatePreference:
    def test_update_content_and_tags(self, session):
        row = svc.create_preference(session, content="旧内容", tags="a")
        updated = svc.update_preference(session, row.id, content="新内容", tags="b,c")
        assert updated.content == "新内容"
        assert updated.tags == "b,c"

    def test_missing_raises(self, session):
        with pytest.raises(ValueError, match="不存在"):
            svc.update_preference(session, 99999, content="x")


class TestDeactivatePreference:
    def test_soft_delete(self, session):
        row = svc.create_preference(session, content="将被软删")
        svc.deactivate_preference(session, row.id)
        session.refresh(row)
        assert row.active is False
        active = svc.list_preferences(session, active_only=True)
        assert all(p.id != row.id for p in active)
        all_rows = svc.list_preferences(session, active_only=False)
        assert any(p.id == row.id for p in all_rows)


class TestAcceptDraft:
    def test_accept_creates_ai_suggested(self, session):
        draft = CoachPreferenceDraft(
            content="AI 建议：注意热身",
            tags="热身",
            source="daily_distill",
            status="pending",
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)

        pref = svc.accept_draft(session, draft.id)
        assert pref.category == "ai_suggested"
        assert pref.content == "AI 建议：注意热身"
        assert pref.source == "daily_distill"
        assert pref.tags == "热身"
        session.refresh(draft)
        assert draft.status == "accepted"
        assert draft.resolved_at is not None

    def test_accept_duplicate_content_merged(self, session):
        first = CoachPreferenceDraft(
            content="重复内容", tags=None, source="sys_prompt", status="pending"
        )
        session.add(first)
        session.commit()
        session.refresh(first)
        pref1 = svc.accept_draft(session, first.id)
        assert pref1.category == "ai_suggested"
        session.refresh(first)
        assert first.status == "accepted"

        second = CoachPreferenceDraft(
            content="重复内容", tags=None, source="weekly_review", status="pending"
        )
        session.add(second)
        session.commit()
        session.refresh(second)
        pref2 = svc.accept_draft(session, second.id)
        assert pref2.id == pref1.id
        session.refresh(second)
        assert second.status == "merged"
        assert second.resolved_at is not None
        assert (
            session.query(CoachPreference)
            .filter_by(content="重复内容", active=True)
            .count()
            == 1
        )


class TestRejectDraft:
    def test_reject_sets_status_and_resolved_at(self, session):
        draft = CoachPreferenceDraft(
            content="不要这条", tags=None, source="daily_distill", status="pending"
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)

        svc.reject_draft(session, draft.id)
        session.refresh(draft)
        assert draft.status == "rejected"
        assert draft.resolved_at is not None


class TestSearchMemory:
    def test_tag_hit_and_limit(self, session):
        for i, tags in enumerate(
            ["膝盖,伤病", "饮食", "膝盖", "恢复", "无关"]
        ):
            session.add(
                CoachMemory(
                    summary=f"记忆{i}",
                    tags=tags,
                    source="coach_chat",
                    active=True,
                )
            )
        session.commit()

        hits = svc.search_memory(session, ["膝盖"], limit=2)
        assert len(hits) == 2
        assert all(_tag_related(h.tags, "膝盖") for h in hits)

    def test_fallback_when_no_tag_hit(self, session):
        for i in range(3):
            session.add(
                CoachMemory(
                    summary=f"兜底{i}",
                    tags="饮食",
                    source="report_chat",
                    active=True,
                )
            )
        session.commit()

        hits = svc.search_memory(session, ["完全不存在的标签"], limit=2)
        assert len(hits) == 2
        assert all(h.active for h in hits)


def _tag_related(memory_tags: str | None, q: str) -> bool:
    if not memory_tags:
        return False
    return any(q == t.strip() or q in t.strip() or t.strip() in q for t in memory_tags.split(","))


class TestBuildMemorySection:
    def test_all_three_sections(self):
        text = svc.build_memory_section(
            ["深蹲注意右膝"],
            ["(最近) 上次聊到饮食"],
            {"训练频率": "每周 4 次"},
        )
        assert text.startswith("## 用户长期记忆（AI 参考）")
        assert "须知：" in text
        assert "- 深蹲注意右膝" in text
        assert "历史对话要点：" in text
        assert "- (最近) 上次聊到饮食" in text
        assert "长期统计：" in text
        assert "- 训练频率：每周 4 次" in text

    def test_only_l1(self):
        text = svc.build_memory_section(["只须知"], [], None)
        assert "须知：" in text
        assert "历史对话要点：" not in text
        assert "长期统计：" not in text

    def test_only_l2(self):
        text = svc.build_memory_section([], ["历史一条"], None)
        assert "历史对话要点：" in text
        assert "须知：" not in text
        assert "长期统计：" not in text

    def test_only_l3(self):
        text = svc.build_memory_section([], [], {"训练频率": "3次/周"})
        assert "长期统计：" in text
        assert "须知：" not in text
        assert "历史对话要点：" not in text

    def test_all_empty_returns_empty_string(self):
        assert svc.build_memory_section([], [], None) == ""
        assert svc.build_memory_section([], [], {}) == ""


# ---------- API 全链路 ----------


class TestCoachMemoryApi:
    def test_preferences_crud_and_drafts(self, client, auth_user, session):
        # POST 新建
        resp = client.post(
            "/api/coach/preferences",
            json={"content": "API 须知", "tags": "api"},
            headers=auth_user,
        )
        assert resp.status_code == 200
        pref = resp.json()
        assert pref["content"] == "API 须知"
        assert pref["category"] == "manual"
        assert pref["tags"] == "api"
        pref_id = pref["id"]

        # GET 列表
        resp = client.get("/api/coach/preferences", headers=auth_user)
        assert resp.status_code == 200
        prefs = resp.json()["preferences"]
        assert any(p["id"] == pref_id for p in prefs)

        # PUT 改
        resp = client.put(
            f"/api/coach/preferences/{pref_id}",
            json={"content": "已改", "tags": "new"},
            headers=auth_user,
        )
        assert resp.status_code == 200
        assert resp.json()["content"] == "已改"
        assert resp.json()["tags"] == "new"

        # DELETE 软删
        resp = client.delete(
            f"/api/coach/preferences/{pref_id}", headers=auth_user
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        resp = client.get("/api/coach/preferences", headers=auth_user)
        assert all(p["id"] != pref_id for p in resp.json()["preferences"])

        # drafts：造 pending → accept / reject
        d_accept = CoachPreferenceDraft(
            content="草稿采纳", tags="d", source="daily_distill", status="pending"
        )
        d_reject = CoachPreferenceDraft(
            content="草稿拒绝", tags=None, source="weekly_review", status="pending"
        )
        session.add_all([d_accept, d_reject])
        session.commit()
        session.refresh(d_accept)
        session.refresh(d_reject)

        resp = client.get("/api/coach/drafts", headers=auth_user)
        assert resp.status_code == 200
        draft_ids = {d["id"] for d in resp.json()["drafts"]}
        assert d_accept.id in draft_ids
        assert d_reject.id in draft_ids

        resp = client.post(
            f"/api/coach/drafts/{d_accept.id}/accept", headers=auth_user
        )
        assert resp.status_code == 200
        assert resp.json()["preference"]["content"] == "草稿采纳"
        assert resp.json()["preference"]["category"] == "ai_suggested"

        resp = client.post(
            f"/api/coach/drafts/{d_reject.id}/reject", headers=auth_user
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_requires_auth(self, client):
        assert client.get("/api/coach/preferences").status_code == 401
        assert client.get("/api/coach/drafts").status_code == 401
