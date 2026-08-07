"""M2 训记适配器测试（TDD）。

- 全部 HTTP 外呼用 respx mock，禁止测试真实外呼（集成测试除外，默认跳过）；
- 时钟与睡眠通过注入假实现控制，验证限频计时而不真实等待。
"""
import gzip
import json
import os
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
import respx

from app.models import XunjiPlan, XunjiTrain

TRAINS_URL = "https://trains.xunjiapp.cn/api_trains_for_llm_v2"
UPSERT_URL = "https://trains.xunjiapp.cn/api_upsert_trains_for_llm_v2"
PLAN_URL = "https://api.xunjiapp.cn/open/plan/query_gzip"

DATESTR = "2026-08-03"

TRAIN_1 = {
    "localid": 111,
    "title": "背二头2",
    "start": 1754220600000,
    "end": 1754224200000,
    "note": {"text": "状态不错"},
    "movements": [
        {"name": "引体向上", "sets": [{"weight": "0", "unit": "kg", "reps": "8", "done": True}]}
    ],
}
TRAIN_2 = {
    "localid": 222,
    "title": "有氧",
    "start": 1754230000000,
    "end": 1754231800000,
    "movements": [],
}


def trains_payload(trains):
    return {"schema_version": "train_open_api_v2", "res": {"trains": trains}}


def gzip_bytes(obj) -> bytes:
    return gzip.compress(json.dumps(obj, ensure_ascii=False).encode())


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
def client(session, clock):
    from app.adapters.xunji import XunjiClient

    return XunjiClient(session, api_key="test-key", sleep=clock.sleep, time_fn=clock.time)


# ---------- 读取训练 ----------


@respx.mock
def test_fetch_trains_stores_rows(client, session):
    """正常读取：res.trains 落库 xunji_train，字段映射正确，raw_json 存原始响应。"""
    respx.post(TRAINS_URL).mock(
        return_value=httpx.Response(200, json=trains_payload([TRAIN_1, TRAIN_2]))
    )
    rows = client.fetch_trains(DATESTR)

    assert len(rows) == 2
    db_rows = session.query(XunjiTrain).filter_by(datestr=DATESTR).all()
    assert len(db_rows) == 2
    r1 = session.query(XunjiTrain).filter_by(datestr=DATESTR, localid="111").one()
    assert r1.title == "背二头2"
    assert r1.start_ms == TRAIN_1["start"]
    assert r1.end_ms == TRAIN_1["end"]
    assert json.loads(r1.note_json)["text"] == "状态不错"
    assert json.loads(r1.raw_json)["movements"] == TRAIN_1["movements"]


@respx.mock
def test_fetch_trains_gzip_response(client, session):
    """gzip 响应（无 Content-Encoding 头、仅 gzip 字节流）也能正确解压解析。"""
    respx.post(TRAINS_URL).mock(
        return_value=httpx.Response(
            200, content=gzip_bytes(trains_payload([TRAIN_1])), headers={"Content-Type": "application/json"}
        )
    )
    rows = client.fetch_trains(DATESTR)
    assert len(rows) == 1
    assert session.query(XunjiTrain).filter_by(localid="111").count() == 1


@respx.mock
def test_fetch_trains_gzip_with_header(client, session):
    """带 Content-Encoding: gzip 头的响应同样解析正确。"""
    respx.post(TRAINS_URL).mock(
        return_value=httpx.Response(
            200,
            content=gzip_bytes(trains_payload([TRAIN_1])),
            headers={"Content-Encoding": "gzip"},
        )
    )
    rows = client.fetch_trains(DATESTR)
    assert len(rows) == 1


@respx.mock
def test_fetch_trains_idempotent_force_refresh(client, session):
    """强制刷新重复拉取：按 (datestr, localid) upsert，不产生重复行。"""
    respx.post(TRAINS_URL).mock(
        return_value=httpx.Response(200, json=trains_payload([TRAIN_1, TRAIN_2]))
    )
    client.fetch_trains(DATESTR)
    client.fetch_trains(DATESTR, force_refresh=True)
    client.fetch_trains(DATESTR, force_refresh=True)
    assert session.query(XunjiTrain).filter_by(datestr=DATESTR).count() == 2


@respx.mock
def test_fetch_trains_updates_existing_row(client, session):
    """重复拉取同 localid 时更新字段而非新增。"""
    respx.post(TRAINS_URL).mock(return_value=httpx.Response(200, json=trains_payload([TRAIN_1])))
    client.fetch_trains(DATESTR)
    changed = dict(TRAIN_1, title="背二头2-改")
    respx.post(TRAINS_URL).mock(return_value=httpx.Response(200, json=trains_payload([changed])))
    client.fetch_trains(DATESTR, force_refresh=True)

    rows = session.query(XunjiTrain).filter_by(datestr=DATESTR, localid="111").all()
    assert len(rows) == 1
    assert rows[0].title == "背二头2-改"


@respx.mock
def test_cache_hit_no_http_request(client, session):
    """同一 datestr 当天已拉过：直接读库，不发第二次请求。"""
    route = respx.post(TRAINS_URL).mock(
        return_value=httpx.Response(200, json=trains_payload([TRAIN_1]))
    )
    first = client.fetch_trains(DATESTR)
    second = client.fetch_trains(DATESTR)

    assert route.call_count == 1
    assert [r.localid for r in second] == [r.localid for r in first]


@respx.mock
def test_force_refresh_bypasses_cache(client):
    """force_refresh=True 时跳过缓存重新请求。"""
    route = respx.post(TRAINS_URL).mock(
        return_value=httpx.Response(200, json=trains_payload([TRAIN_1]))
    )
    client.fetch_trains(DATESTR)
    client.fetch_trains(DATESTR, force_refresh=True)
    assert route.call_count == 2


# ---------- 限频 ----------


@respx.mock
def test_rate_limit_read_15s(client, clock):
    """同一 datestr 普通读 15s 限频：第二次请求前先等待剩余时间。"""
    respx.post(TRAINS_URL).mock(return_value=httpx.Response(200, json=trains_payload([TRAIN_1])))
    client.fetch_trains(DATESTR)
    client.fetch_trains(DATESTR, force_refresh=True)

    waits = [s for s in clock.sleeps if s > 1]
    assert len(waits) == 1
    assert 14.0 <= waits[0] <= 15.0


@respx.mock
def test_rate_limit_full_read_30s(client, clock):
    """include_full_data=True 完整读 30s 限频。"""
    respx.post(TRAINS_URL).mock(return_value=httpx.Response(200, json=trains_payload([TRAIN_1])))
    client.fetch_trains(DATESTR, include_full_data=True)
    client.fetch_trains(DATESTR, include_full_data=True, force_refresh=True)

    waits = [s for s in clock.sleeps if s > 1]
    assert len(waits) == 1
    assert 29.0 <= waits[0] <= 30.0


@respx.mock
def test_rate_limit_is_per_datestr(client, clock):
    """不同 datestr 互不干扰，不触发等待。"""
    respx.post(TRAINS_URL).mock(return_value=httpx.Response(200, json=trains_payload([TRAIN_1])))
    client.fetch_trains(DATESTR)
    client.fetch_trains("2026-08-02")

    assert [s for s in clock.sleeps if s > 1] == []


@respx.mock
def test_rate_limit_upsert_45s(client, clock):
    """写回 45s 限频。"""
    respx.post(UPSERT_URL).mock(return_value=httpx.Response(200, json={"res": []}))
    payload = [{"datestr": DATESTR, "localid": 111}]
    client.upsert_trains(payload)
    client.upsert_trains(payload)

    waits = [s for s in clock.sleeps if s > 1]
    assert len(waits) == 1
    assert 44.0 <= waits[0] <= 45.0


# ---------- too frequent 重试 ----------


@respx.mock
def test_too_frequent_retries_with_retry_after(client, clock):
    """收到 too frequent 时按 retry_after_ms 等待后重试，最终成功。"""
    route = respx.post(TRAINS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"error": "too frequent", "retry_after_ms": 150}),
            httpx.Response(200, json=trains_payload([TRAIN_1])),
        ]
    )
    rows = client.fetch_trains(DATESTR)

    assert len(rows) == 1
    assert route.call_count == 2
    assert pytest.approx(0.15) in clock.sleeps


@respx.mock
def test_too_frequent_gives_up_after_3_retries(client):
    """连续 too frequent 最多重试 3 次后抛错。"""
    from app.adapters.xunji import XunjiRateLimitError

    route = respx.post(TRAINS_URL).mock(
        return_value=httpx.Response(200, json={"error": "too frequent", "retry_after_ms": 10})
    )
    with pytest.raises(XunjiRateLimitError):
        client.fetch_trains(DATESTR)
    assert route.call_count == 3


# ---------- 写回强制 dry_run ----------


@respx.mock
def test_upsert_defaults_dry_run_true(client):
    """V1-5 起解除强制 dry_run，但默认参数仍为 dry_run=True。"""
    captured = []

    def capture(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"res": {"summary": "dry run ok"}})

    respx.post(UPSERT_URL).mock(side_effect=capture)
    result = client.upsert_trains([{"datestr": DATESTR, "localid": 111}])

    body = captured[0]
    assert body["dry_run"] is True
    assert body["schema_version"] == "train_open_api_v2"
    assert body["client_request_id"]
    assert body["res"] == [{"datestr": DATESTR, "localid": 111}]
    assert result["res"]["summary"] == "dry run ok"


@respx.mock
def test_upsert_explicit_dry_run_false_passes_through(client):
    """显式 dry_run=False 透传（仅确认接口内部使用）。"""
    captured = []

    def capture(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"res": {"trains": []}})

    respx.post(UPSERT_URL).mock(side_effect=capture)
    client.upsert_trains([{"datestr": DATESTR, "localid": 111}], dry_run=False)

    assert captured[0]["dry_run"] is False


# ---------- 官方计划 ----------


@respx.mock
def test_fetch_plan_list_stores_plans(client, session):
    plans = [
        {"plan_ref": "platform:155", "name": "增肌计划"},
        {"plan_ref": "universal:155", "name": "通用计划"},
    ]
    respx.post(PLAN_URL).mock(
        return_value=httpx.Response(
            200,
            content=gzip_bytes({"schema_version": "plan_open_api_v1", "res": {"plans": plans}}),
            headers={"Content-Encoding": "gzip"},
        )
    )
    rows = client.fetch_plan_list()

    assert len(rows) == 2
    stored = session.query(XunjiPlan).filter_by(plan_ref="platform:155").all()
    assert len(stored) == 1
    assert json.loads(stored[0].plan_json)["name"] == "增肌计划"


@respx.mock
def test_fetch_plan_stores_detail(client, session):
    res_data = {
        "plan": {"plan_ref": "platform:155", "name": "增肌计划"},
        "date_range": {"start_date": "2026-07-12", "end_date": "2026-08-12"},
        "days": [{"date": "2026-08-03", "movements": []}],
    }
    respx.post(PLAN_URL).mock(
        return_value=httpx.Response(200, json={"schema_version": "plan_open_api_v1", "res": res_data})
    )
    row = client.fetch_plan("platform:155", "2026-07-12", "2026-08-12")

    assert row.plan_ref == "platform:155"
    assert str(row.date_from) == "2026-07-12"
    assert str(row.date_to) == "2026-08-12"
    assert json.loads(row.plan_json)["days"] == res_data["days"]


@respx.mock
def test_fetch_plan_idempotent(client, session):
    """同一 plan_ref 重复拉取覆盖缓存，不产生重复行。"""
    res_data = {
        "plan": {"plan_ref": "platform:155"},
        "date_range": {"start_date": "2026-07-12", "end_date": "2026-08-12"},
        "days": [],
    }
    respx.post(PLAN_URL).mock(
        return_value=httpx.Response(200, json={"schema_version": "plan_open_api_v1", "res": res_data})
    )
    client.fetch_plan("platform:155", "2026-07-12", "2026-08-12")
    client.fetch_plan("platform:155", "2026-07-12", "2026-08-12")
    assert session.query(XunjiPlan).filter_by(plan_ref="platform:155").count() == 1


@respx.mock
def test_plan_rate_limit_15s(client, clock):
    """官方计划接口同 key+action+plan_ref 15s 限频。"""
    respx.post(PLAN_URL).mock(
        return_value=httpx.Response(200, json={"res": {"plans": []}})
    )
    client.fetch_plan_list()
    client.fetch_plan_list()
    waits = [s for s in clock.sleeps if s > 1]
    assert len(waits) == 1
    assert 14.0 <= waits[0] <= 15.0


# ---------- V1-4-FIX 真实结构回归 ----------

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# 真实 API get 响应结构（2026-08-07 抓取整理）：date_range + days，日期为 ISO 字符串
REAL_PLAN_GET = {
    "plan": {"plan_ref": "universal:1", "title": "分化增肌训练计划", "status": "ended"},
    "date_range": {"start_date": "2026-07-30", "end_date": "2026-08-05"},
    "days": [
        {"date": "2026-07-30",
         "movements": [{"name": "杠铃划船", "sets": [{"weight": 60, "reps": 10}]}]},
        {"date": "2026-08-05", "movements": []},
    ],
}


@respx.mock
def test_fetch_plan_list_real_fixture_fills_date_range(client, session):
    """真实 list 响应（gzip 字节流夹具，含 status=ended）：落库须解析出 date_from/date_to。"""
    content = (FIXTURES / "plan_list_real_gzip.bin").read_bytes()
    respx.post(PLAN_URL).mock(return_value=httpx.Response(200, content=content))

    rows = client.fetch_plan_list()

    assert len(rows) == 1
    row = session.query(XunjiPlan).filter_by(plan_ref="universal:1").one()
    assert row.date_from == date(2026, 7, 30)
    assert row.date_to == date(2026, 8, 5)
    assert json.loads(row.plan_json)["status"] == "ended"


@respx.mock
def test_fetch_plan_list_cleans_dirty_null_rows(client, session):
    """历史脏行（date_from/date_to 为 NULL）在刷新列表时被清理。"""
    session.add(XunjiPlan(plan_ref="legacy:dirty", plan_json="{}", fetched_at=datetime.now()))
    session.commit()
    content = (FIXTURES / "plan_list_real_gzip.bin").read_bytes()
    respx.post(PLAN_URL).mock(return_value=httpx.Response(200, content=content))

    client.fetch_plan_list()

    dirty = session.query(XunjiPlan).filter(
        (XunjiPlan.date_from.is_(None)) | (XunjiPlan.date_to.is_(None))
    ).count()
    assert dirty == 0


@respx.mock
def test_fetch_plan_accepts_date_objects(client, session):
    """回归：sync_plan_cache 传 date 对象时请求体必须序列化为 ISO 字符串。"""
    captured = {}

    def capture(request):
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"schema_version": "plan_open_api_v1", "res": REAL_PLAN_GET})

    respx.post(PLAN_URL).mock(side_effect=capture)
    row = client.fetch_plan("universal:1", date(2026, 8, 7), date(2026, 9, 6))

    assert captured["body"]["start_date"] == "2026-08-07"
    assert captured["body"]["end_date"] == "2026-09-06"
    assert row.date_from == date(2026, 7, 30)
    assert row.date_to == date(2026, 8, 5)


# ---------- 密钥来源 ----------


def test_api_key_from_env_not_hardcoded(session, monkeypatch):
    """Key 只从环境变量读取：不传 api_key 时用 XUNJI_API_KEY。"""
    from app.adapters.xunji import XunjiClient

    monkeypatch.setenv("XUNJI_API_KEY", "env-key-123")
    from app.config import get_settings

    get_settings.cache_clear()
    c = XunjiClient(session)
    assert c._api_key == "env-key-123"


def test_missing_api_key_raises(session, monkeypatch):
    from app.adapters.xunji import XunjiClient

    monkeypatch.delenv("XUNJI_API_KEY", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(RuntimeError):
        XunjiClient(session)


# ---------- 集成测试（真实外呼，默认跳过） ----------


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_XUNJI_INTEGRATION") != "1",
    reason="真实外呼训记会消耗限频额度，默认跳过；手动运行：$env:RUN_XUNJI_INTEGRATION='1'; pytest -m integration tests/test_xunji.py",
)
def test_integration_fetch_real_2026_08_03(session):
    """手动验证：用真实 XUNJI_API_KEY 拉 2026-08-03（当日有真实训练"背二头2"）。

    运行方式：$env:RUN_XUNJI_INTEGRATION='1'; pytest -m integration tests/test_xunji.py
    """
    from app.adapters.xunji import XunjiClient

    client = XunjiClient(session)
    rows = client.fetch_trains("2026-08-03")
    assert len(rows) >= 1
    titles = [r.title for r in rows]
    assert any("背" in (t or "") for t in titles), f"未找到预期训练，实际：{titles}"
