"""V1-5 训记写回确认流测试（TDD）。

覆盖 PRD §5.4 全规则：
- diff 生成保留全部元数据（note.trainColor / note.heartRate / 顶层 heartRate）；
- 预览路径只读不写（spy 验证 upsert 零外呼）；
- 写回 45s 限频排队（连续 3 个确认串行）；
- 写回成功后服务端返回覆盖缓存 + 当日融合重跑；
- 约束拒绝：单日 >4 条 / 单训练 >15 动作 / 单动作 >20 组 / 非标准动作名；
- 每次写回写 job_run 留痕（成功与失败）。
"""
import json
from datetime import date, datetime, time as dtime

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import app
from app.models import JobRun, Workout, XunjiTrain

TRAINS_URL = "https://trains.xunjiapp.cn/api_trains_for_llm_v2"
UPSERT_URL = "https://trains.xunjiapp.cn/api_upsert_trains_for_llm_v2"

DATESTR = "2026-08-03"
DAY = date(2026, 8, 3)

# 含完整元数据的原始训练：note.trainColor / note.heartRate / 顶层 heartRate
ORIGINAL_TRAIN = {
    "localid": 111,
    "title": "背二头2",
    "start": 1754220600000,
    "end": 1754224200000,
    "note": {
        "text": "状态不错",
        "trainColor": "#FF7A00",
        "heartRate": {"avg": 120, "max": 150},
        "customTitle": "我的背部日",
    },
    "heartRate": {"avg": 120, "max": 150},
    "movements": [
        {
            "name": "引体向上",
            "sets": [
                {"weight": "0", "unit": "kg", "reps": "8", "done": True},
                {"weight": "0", "unit": "kg", "reps": "7", "done": True},
            ],
        },
        {
            "name": "杠铃划船",
            "sets": [{"weight": "60", "unit": "kg", "reps": "10", "done": True}],
        },
    ],
}

# 建议变更：给引体向上两组补 RPE
CHANGES = {
    "movements": [
        {
            "name": "引体向上",
            "sets": [
                {"weight": "0", "unit": "kg", "reps": "8", "done": True, "rpe": "8"},
                {"weight": "0", "unit": "kg", "reps": "7", "done": True, "rpe": "8.5"},
            ],
        },
        {
            "name": "杠铃划船",
            "sets": [{"weight": "60", "unit": "kg", "reps": "10", "done": True}],
        },
    ],
}

# 服务端写回后返回的标准化数据
SERVER_TRAIN = {
    **ORIGINAL_TRAIN,
    "movements": CHANGES["movements"],
}


class FakeClock:
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
def xunji(session, clock):
    from app.adapters.xunji import XunjiClient

    return XunjiClient(session, api_key="test-key", sleep=clock.sleep, time_fn=clock.time)


@pytest.fixture
def service(session, xunji):
    from app.services.writeback import WritebackService

    return WritebackService(session, xunji=xunji)


def seed_train(session, train=None):
    train = train or ORIGINAL_TRAIN
    start_ms = train["start"]
    end_ms = train["end"]
    row = XunjiTrain(
        datestr=DATESTR,
        localid=str(train["localid"]),
        title=train["title"],
        start_ms=start_ms,
        end_ms=end_ms,
        note_json=json.dumps(train["note"], ensure_ascii=False),
        raw_json=json.dumps(train, ensure_ascii=False),
        fetched_at=datetime.now(),
    )
    session.add(row)
    session.commit()
    return row


def seed_workout(session, train_row):
    w = Workout(
        date=DAY,
        title=train_row.title,
        xunji_train_id=train_row.id,
        match_status="xunji_only",
        movements_json=json.dumps(ORIGINAL_TRAIN["movements"], ensure_ascii=False),
    )
    session.add(w)
    session.commit()
    return w


# ---------- 纯函数：合并保留元数据 + diff ----------


def test_merge_preserves_all_metadata():
    """diff/合并保留全部元数据：localid/start/end/note（含 trainColor/heartRate/customTitle）原样保留。"""
    from app.services.writeback import build_merged_train

    merged = build_merged_train(ORIGINAL_TRAIN, DATESTR, CHANGES)

    assert merged["localid"] == 111
    assert merged["datestr"] == DATESTR
    assert merged["start"] == ORIGINAL_TRAIN["start"]
    assert merged["end"] == ORIGINAL_TRAIN["end"]
    # note 全量元数据原样保留
    assert merged["note"] == ORIGINAL_TRAIN["note"]
    assert merged["note"]["trainColor"] == "#FF7A00"
    assert merged["note"]["heartRate"] == {"avg": 120, "max": 150}
    assert merged["note"]["customTitle"] == "我的背部日"
    # 顶层 heartRate 等其它元数据不丢失
    assert merged["heartRate"] == {"avg": 120, "max": 150}
    # title 未变更时取原值
    assert merged["title"] == "背二头2"
    # movements 应用新值
    assert merged["movements"][0]["sets"][0]["rpe"] == "8"


def test_merge_title_override():
    from app.services.writeback import build_merged_train

    merged = build_merged_train(ORIGINAL_TRAIN, DATESTR, {"title": "新标题"})
    assert merged["title"] == "新标题"
    assert merged["movements"] == ORIGINAL_TRAIN["movements"]


def test_diff_marks_changed_fields():
    """diff 三要素：字段/原值/新值；变更行 changed=True，未变行 changed=False。"""
    from app.services.writeback import build_diff, build_merged_train

    merged = build_merged_train(ORIGINAL_TRAIN, DATESTR, CHANGES)
    diff = build_diff(ORIGINAL_TRAIN, merged)

    by_field = {row["field"]: row for row in diff}
    rpe_row = by_field["动作1 引体向上 第1组 rpe"]
    assert rpe_row["old"] is None
    assert rpe_row["new"] == "8"
    assert rpe_row["changed"] is True
    weight_row = by_field["动作1 引体向上 第1组 weight"]
    assert weight_row["old"] == "0"
    assert weight_row["new"] == "0"
    assert weight_row["changed"] is False


# ---------- 预览：只读不写 ----------


@respx.mock
def test_preview_reads_full_data_and_never_calls_upsert(service, session):
    """预览：include_full_data=true 读原训练生成 diff；upsert 接口零外呼（spy）。"""
    read_route = respx.post(TRAINS_URL).mock(
        return_value=httpx.Response(200, json={"res": {"trains": [ORIGINAL_TRAIN]}})
    )
    upsert_spy = respx.post(UPSERT_URL).mock(
        return_value=httpx.Response(200, json={"res": {}})
    )

    result = service.preview(DATESTR, 111, CHANGES)

    assert upsert_spy.call_count == 0, "预览路径禁止调用写回接口"
    assert read_route.call_count == 1
    sent = json.loads(read_route.calls[0].request.content)
    assert sent["include_full_data"] is True
    assert result["datestr"] == DATESTR
    assert result["localid"] == "111"
    assert any(r["changed"] for r in result["diff"])
    assert result["train"]["note"] == ORIGINAL_TRAIN["note"]


@respx.mock
def test_preview_unknown_localid_raises(service):
    from app.services.writeback import WritebackNotFoundError

    respx.post(TRAINS_URL).mock(
        return_value=httpx.Response(200, json={"res": {"trains": [ORIGINAL_TRAIN]}})
    )
    with pytest.raises(WritebackNotFoundError):
        service.preview(DATESTR, 999, CHANGES)


# ---------- 确认：真实写回 + 限频排队 ----------


def _mock_upsert_ok():
    return respx.post(UPSERT_URL).mock(
        return_value=httpx.Response(200, json={"res": {"trains": [SERVER_TRAIN]}})
    )


@respx.mock
def test_confirm_sends_dry_run_false(service, session, xunji):
    """确认接口内部调用才传 dry_run=False。"""
    seed_train(session)
    captured = []

    def capture(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"res": {"trains": [SERVER_TRAIN]}})

    respx.post(UPSERT_URL).mock(side_effect=capture)
    service.confirm(DATESTR, 111, CHANGES)

    assert captured[0]["dry_run"] is False
    assert captured[0]["res"][0]["localid"] == 111
    assert captured[0]["res"][0]["note"] == ORIGINAL_TRAIN["note"]


@respx.mock
def test_confirm_rate_limit_queue_45s(service, session, clock):
    """连续 3 个写回确认串行排队，相邻间隔遵守 45s 写回限频。"""
    seed_train(session)
    _mock_upsert_ok()

    service.confirm(DATESTR, 111, CHANGES)
    service.confirm(DATESTR, 111, CHANGES)
    service.confirm(DATESTR, 111, CHANGES)

    waits = [s for s in clock.sleeps if s > 1]
    assert len(waits) == 2
    for w in waits:
        assert 44.0 <= w <= 45.0


@respx.mock
def test_confirm_overwrites_cache_and_refuses(service, session):
    """写回成功：服务端标准化数据覆盖 xunji_train 缓存，当日融合重跑更新 workout。"""
    train_row = seed_train(session)
    workout = seed_workout(session, train_row)
    _mock_upsert_ok()

    result = service.confirm(DATESTR, 111, CHANGES)

    session.expire_all()
    row = session.query(XunjiTrain).filter_by(datestr=DATESTR, localid="111").one()
    raw = json.loads(row.raw_json)
    assert raw["movements"][0]["sets"][0]["rpe"] == "8", "缓存须被服务端返回覆盖"
    # 融合重跑：workout.movements_json 更新为新组次
    w = session.get(Workout, workout.id)
    movements = json.loads(w.movements_json)
    assert movements[0]["sets"][1]["rpe"] == "8.5"
    assert workout.id in result["workouts_updated"]


@respx.mock
def test_confirm_writes_job_run_on_success(service, session):
    seed_train(session)
    _mock_upsert_ok()
    service.confirm(DATESTR, 111, CHANGES)

    run = session.query(JobRun).filter_by(job_name="writeback").one()
    assert run.status == "success"
    detail = json.loads(run.detail_json)
    assert detail["datestr"] == DATESTR
    assert detail["localid"] == "111"
    assert "引体向上" in json.dumps(detail, ensure_ascii=False)  # 请求体摘要含变更字段


@respx.mock
def test_confirm_writes_job_run_on_failure(service, session):
    """写回失败同样留痕 job_run(status=failed)。"""
    seed_train(session)
    respx.post(UPSERT_URL).mock(
        return_value=httpx.Response(200, json={"error": "upsert failed"})
    )

    from app.adapters.xunji import XunjiAPIError

    with pytest.raises(XunjiAPIError):
        service.confirm(DATESTR, 111, CHANGES)

    run = session.query(JobRun).filter_by(job_name="writeback").one()
    assert run.status == "failed"
    assert run.error


# ---------- 约束拒绝 ----------


def test_validate_rejects_more_than_4_trains():
    from app.services.writeback import WritebackValidationError, validate_writeback_trains

    trains = [{"datestr": DATESTR, "localid": i} for i in range(5)]
    with pytest.raises(WritebackValidationError):
        validate_writeback_trains(trains)


def test_validate_rejects_mixed_dates():
    from app.services.writeback import WritebackValidationError, validate_writeback_trains

    trains = [
        {"datestr": DATESTR, "localid": 1},
        {"datestr": "2026-08-04", "localid": 2},
    ]
    with pytest.raises(WritebackValidationError):
        validate_writeback_trains(trains)


@respx.mock
def test_confirm_rejects_more_than_15_movements(service, session):
    from app.services.writeback import WritebackValidationError

    seed_train(session)
    upsert_spy = respx.post(UPSERT_URL).mock(return_value=httpx.Response(200, json={"res": {}}))
    changes = {
        "movements": [
            {"name": "杠铃卧推", "sets": [{"weight": "60", "reps": "10"}]}
            for _ in range(16)
        ]
    }
    with pytest.raises(WritebackValidationError):
        service.confirm(DATESTR, 111, changes)
    assert upsert_spy.call_count == 0


@respx.mock
def test_confirm_rejects_more_than_20_sets(service, session):
    from app.services.writeback import WritebackValidationError

    seed_train(session)
    upsert_spy = respx.post(UPSERT_URL).mock(return_value=httpx.Response(200, json={"res": {}}))
    changes = {
        "movements": [
            {
                "name": "杠铃卧推",
                "sets": [{"weight": "60", "reps": "10"} for _ in range(21)],
            }
        ]
    }
    with pytest.raises(WritebackValidationError):
        service.confirm(DATESTR, 111, changes)
    assert upsert_spy.call_count == 0


@respx.mock
def test_confirm_rejects_nonstandard_movement_name(service, session):
    """PRD §5.4：写回动作名只允许 GitHub 标准中文名表内的名字。"""
    from app.services.writeback import WritebackValidationError

    seed_train(session)
    upsert_spy = respx.post(UPSERT_URL).mock(return_value=httpx.Response(200, json={"res": {}}))
    changes = {"movements": [{"name": "自造动作名xyz", "sets": [{"reps": "10"}]}]}
    with pytest.raises(WritebackValidationError):
        service.confirm(DATESTR, 111, changes)
    assert upsert_spy.call_count == 0


# ---------- API 层 ----------


@pytest.fixture
def api_client(env_vars, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    from app.config import get_settings

    get_settings.cache_clear()
    from app.api.writeback import get_writeback_service

    app.dependency_overrides[get_writeback_service] = lambda: _FakeService()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


class _FakeService:
    def __init__(self):
        self.confirm_calls = 0

    def preview(self, datestr, localid, changes):
        return {
            "datestr": datestr,
            "localid": str(localid),
            "diff": [{"field": "title", "old": "A", "new": "B", "changed": True}],
            "train": {"datestr": datestr, "localid": 111},
        }

    def confirm(self, datestr, localid, changes):
        self.confirm_calls += 1
        return {"status": "written", "datestr": datestr, "localid": str(localid)}


@pytest.fixture
def auth(api_client):
    token = api_client.post("/api/auth/login", json={"password": "test-pass"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_api_preview_requires_auth(api_client):
    resp = api_client.post(
        "/api/writeback/preview",
        json={"datestr": DATESTR, "localid": 111, "changes": CHANGES},
    )
    assert resp.status_code == 401


def test_api_confirm_requires_auth(api_client):
    resp = api_client.post(
        "/api/writeback/confirm",
        json={"datestr": DATESTR, "localid": 111, "changes": CHANGES},
    )
    assert resp.status_code == 401


def test_api_preview_returns_diff(api_client, auth):
    resp = api_client.post(
        "/api/writeback/preview",
        json={"datestr": DATESTR, "localid": 111, "changes": CHANGES},
        headers=auth,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["diff"][0]["field"] == "title"
    assert data["diff"][0]["changed"] is True


def test_api_confirm_returns_written(api_client, auth):
    resp = api_client.post(
        "/api/writeback/confirm",
        json={"datestr": DATESTR, "localid": 111, "changes": CHANGES},
        headers=auth,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "written"


def test_api_validation_error_maps_422(api_client, auth, monkeypatch):
    from app.api import writeback as writeback_api
    from app.services.writeback import WritebackValidationError

    class BadService(_FakeService):
        def confirm(self, datestr, localid, changes):
            raise WritebackValidationError("单次最多 4 条训练")

    app.dependency_overrides[writeback_api.get_writeback_service] = lambda: BadService()
    resp = api_client.post(
        "/api/writeback/confirm",
        json={"datestr": DATESTR, "localid": 111, "changes": CHANGES},
        headers=auth,
    )
    assert resp.status_code == 422


def test_api_not_found_maps_404(api_client, auth):
    from app.api import writeback as writeback_api
    from app.services.writeback import WritebackNotFoundError

    class NotFoundService(_FakeService):
        def preview(self, datestr, localid, changes):
            raise WritebackNotFoundError("训练不存在")

    app.dependency_overrides[writeback_api.get_writeback_service] = lambda: NotFoundService()
    resp = api_client.post(
        "/api/writeback/preview",
        json={"datestr": DATESTR, "localid": 999, "changes": CHANGES},
        headers=auth,
    )
    assert resp.status_code == 404


def test_api_xunji_error_maps_502(api_client, auth):
    from app.adapters.xunji import XunjiAPIError
    from app.api import writeback as writeback_api

    class UpstreamFailService(_FakeService):
        def confirm(self, datestr, localid, changes):
            raise XunjiAPIError("too frequent")

    app.dependency_overrides[writeback_api.get_writeback_service] = lambda: UpstreamFailService()
    resp = api_client.post(
        "/api/writeback/confirm",
        json={"datestr": DATESTR, "localid": 111, "changes": CHANGES},
        headers=auth,
    )
    assert resp.status_code == 502


def test_api_unexpected_error_maps_500(api_client, auth):
    from app.api import writeback as writeback_api

    class BoomService(_FakeService):
        def preview(self, datestr, localid, changes):
            raise RuntimeError("boom")

    app.dependency_overrides[writeback_api.get_writeback_service] = lambda: BoomService()
    resp = api_client.post(
        "/api/writeback/preview",
        json={"datestr": DATESTR, "localid": 111, "changes": CHANGES},
        headers=auth,
    )
    assert resp.status_code == 500


def test_get_writeback_service_default(session):
    """默认依赖工厂返回真实 WritebackService 实例。"""
    from app.api.writeback import get_writeback_service
    from app.services.writeback import WritebackService

    svc = get_writeback_service(session)
    assert isinstance(svc, WritebackService)
