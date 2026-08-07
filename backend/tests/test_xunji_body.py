"""V1-7 训记身体数据 API 适配器测试（TDD，PRD §6.1b）。

- Key 从 XUNJI_BODY_API_KEY 读取（与训练 Key 分离）；
- 同 key 同 endpoint 15s 限频（复用统一限频装饰器）；
- 写接口默认 dry_run=True；dry_run=False 必须 confirmed=True，否则拒绝（防绕过）；
- 响应支持裸 gzip 字节流。
"""
import gzip
import json

import httpx
import pytest
import respx

QUERY_URL = "https://api.xunjiapp.cn/open/body/query_gzip"
UPSERT_URL = "https://api.xunjiapp.cn/open/body/upsert_gzip"


def gzip_bytes(obj) -> bytes:
    return gzip.compress(json.dumps(obj, ensure_ascii=False).encode())


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
def client(session, clock):
    from app.adapters.xunji_body import XunjiBodyClient

    return XunjiBodyClient(session, api_key="body-key", sleep=clock.sleep, time_fn=clock.time)


class TestKeyConfig:
    def test_reads_body_api_key_from_settings(self, session, monkeypatch):
        """api_key 缺省时读 XUNJI_BODY_API_KEY，而不是 XUNJI_API_KEY。"""
        from app.adapters.xunji_body import XunjiBodyClient

        monkeypatch.setenv("XUNJI_BODY_API_KEY", "xjbody_test")
        monkeypatch.setenv("XUNJI_API_KEY", "train_key_should_not_be_used")
        from app.config import get_settings

        get_settings.cache_clear()
        c = XunjiBodyClient(session)
        assert c._api_key == "xjbody_test"

    def test_missing_key_raises(self, session, monkeypatch):
        from app.adapters.xunji_body import XunjiBodyClient

        monkeypatch.delenv("XUNJI_BODY_API_KEY", raising=False)
        from app.config import get_settings

        get_settings.cache_clear()
        with pytest.raises(RuntimeError, match="XUNJI_BODY_API_KEY"):
            XunjiBodyClient(session)


class TestQuery:
    @respx.mock
    def test_query_posts_correct_body_and_auth(self, client):
        route = respx.post(QUERY_URL).mock(
            return_value=httpx.Response(200, json={"res": {"records": []}})
        )
        client.query_body_metrics("2026-01-01", "2026-08-03", types=["weight", "bodyfat"])

        request = route.calls.last.request
        assert request.headers["Authorization"] == "Bearer body-key"
        body = json.loads(request.content)
        assert body["start_date"] == "2026-01-01"
        assert body["end_date"] == "2026-08-03"
        assert body["types"] == ["weight", "bodyfat"]
        assert body["include_latest"] is True
        assert body["include_records"] is True

    @respx.mock
    def test_query_parses_gzip_response(self, client):
        payload = {"res": {"records": [{"datestr": "2026-08-03", "type": "weight", "value": 72.4}]}}
        respx.post(QUERY_URL).mock(
            return_value=httpx.Response(200, content=gzip_bytes(payload))
        )
        data = client.query_body_metrics("2026-01-01", "2026-08-03")
        assert data["res"]["records"][0]["value"] == 72.4


class TestUpsert:
    RECORDS = [{"datestr": "2026-08-03", "type": "weight", "value": 72.4}]

    @respx.mock
    def test_dry_run_default_true(self, client):
        """默认 dry_run=True 且不携带 confirmed=True（预览绝不产生真实写入）。"""
        route = respx.post(UPSERT_URL).mock(
            return_value=httpx.Response(200, json={"res": {"summary": "将更新 1 条"}})
        )
        data = client.upsert_body_metrics(self.RECORDS)

        body = json.loads(route.calls.last.request.content)
        assert body["schema_version"] == "body_open_api_v1"
        assert body["dry_run"] is True
        assert body["confirmed"] is not True
        assert body["records"] == self.RECORDS
        assert body["client_request_id"]
        assert data["res"]["summary"] == "将更新 1 条"

    def test_real_write_without_confirmed_rejected(self, client):
        """dry_run=False 但未 confirmed 直接抛错，且绝不发出 HTTP 请求。"""
        with pytest.raises(ValueError, match="confirmed"):
            client.upsert_body_metrics(self.RECORDS, dry_run=False)

    @respx.mock
    def test_confirmed_real_write(self, client):
        route = respx.post(UPSERT_URL).mock(
            return_value=httpx.Response(200, json={"res": {"summary": "已更新 1 条"}})
        )
        client.upsert_body_metrics(self.RECORDS, dry_run=False, confirmed=True)

        body = json.loads(route.calls.last.request.content)
        assert body["dry_run"] is False
        assert body["confirmed"] is True


class TestRateLimit:
    @respx.mock
    def test_same_endpoint_throttled_15s(self, client, clock):
        """同 endpoint 15s 内第二次调用先等待（读/写维度分离）。"""
        respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json={"res": {}}))
        client.query_body_metrics("2026-01-01", "2026-08-03")
        client.query_body_metrics("2026-01-01", "2026-08-04")
        assert clock.sleeps == [pytest.approx(15.0)]

    @respx.mock
    def test_query_and_upsert_dimensions_independent(self, client, clock):
        """query 与 upsert 为不同限频维度，互不阻塞。"""
        respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json={"res": {}}))
        respx.post(UPSERT_URL).mock(return_value=httpx.Response(200, json={"res": {}}))
        client.query_body_metrics("2026-01-01", "2026-08-03")
        client.upsert_body_metrics([{"datestr": "2026-08-03", "type": "weight", "value": 72.4}])
        assert clock.sleeps == []
