"""V2-1 Kimi provider 测试（PRD §6.3，2026-08-07 版）。

覆盖：Kimi 路由与默认模型 kimi-k3.1-pro、思考模式 max_tokens 默认 2048、
reasoning_content 不入库（只取 content）、切换默认模型后路由、
vision_extract 请求体格式（base64 + image_url）、连续失败计数。
"""
import base64
import json

import httpx
import pytest
import respx
from sqlalchemy import select

from app.adapters.llm import (
    LLMClient,
    LLMError,
    chat,
    compute_cost,
    get_consecutive_failures,
    set_default_provider,
    set_selected_model,
    vision_extract,
)
from app.models import LLMCall

KIMI_URL = "https://api.moonshot.cn/v1/chat/completions"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"


@pytest.fixture
def kimi_key(monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "sk-test-kimi")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _kimi_resp(content="你好", reasoning=None, prompt_tokens=11, completion_tokens=7):
    message = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return httpx.Response(
        200,
        json={
            "choices": [{"message": message}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
            "model": "kimi-k3.1-pro",
        },
    )


class TestKimiChat:
    @respx.mock
    def test_kimi_routes_to_moonshot_with_default_model(self, session, kimi_key):
        route = respx.post(KIMI_URL).mock(return_value=_kimi_resp("回复"))
        result = chat([{"role": "user", "content": "hi"}], provider="kimi", session=session)
        assert route.called
        req = json.loads(route.calls.last.request.content)
        assert req["model"] == "kimi-k3.1-pro"
        assert result["content"] == "回复"
        assert result["prompt_tokens"] == 11
        assert result["completion_tokens"] == 7

    @respx.mock
    def test_kimi_default_max_completion_tokens_2048(self, session, kimi_key):
        """K3 使用 max_completion_tokens，并给推理与正文保留余量。"""
        route = respx.post(KIMI_URL).mock(return_value=_kimi_resp())
        chat([{"role": "user", "content": "hi"}], provider="kimi", session=session)
        req = json.loads(route.calls.last.request.content)
        assert req["max_completion_tokens"] == 2048
        assert "max_tokens" not in req

    @respx.mock
    def test_kimi_legacy_max_tokens_caller_override_is_upgraded(self, session, kimi_key):
        route = respx.post(KIMI_URL).mock(return_value=_kimi_resp())
        chat(
            [{"role": "user", "content": "hi"}],
            provider="kimi",
            session=session,
            max_tokens=8192,
        )
        req = json.loads(route.calls.last.request.content)
        assert req["max_completion_tokens"] == 8192
        assert "max_tokens" not in req

    @respx.mock
    def test_non_kimi_provider_no_default_max_tokens(self, session, kimi_key):
        """DeepSeek 不受 Kimi max_tokens 默认逻辑影响。"""
        route = respx.post(DEEPSEEK_URL).mock(return_value=_kimi_resp())
        chat([{"role": "user", "content": "hi"}], provider="deepseek", session=session)
        req = json.loads(route.calls.last.request.content)
        assert "max_tokens" not in req

    @respx.mock
    def test_reasoning_content_not_returned_nor_stored(self, session, kimi_key):
        """响应带 reasoning_content 时落库只取 content（与 MiniMax <think> 剥离并列）。"""
        respx.post(KIMI_URL).mock(
            return_value=_kimi_resp("正文结论", reasoning="大段推理过程")
        )
        result = chat([{"role": "user", "content": "hi"}], provider="kimi", session=session)
        assert result["content"] == "正文结论"
        assert "推理" not in result["content"]
        row = session.scalars(select(LLMCall)).one()
        assert row.provider == "kimi"
        assert row.status == "ok"

    @respx.mock
    def test_empty_content_when_reasoning_exhausts_tokens(self, session, kimi_key):
        """推理耗尽输出额度时必须明确报错，不能把空正文当成功结果。"""
        respx.post(KIMI_URL).mock(return_value=httpx.Response(200, json={
            "choices": [{
                "message": {"role": "assistant", "content": "", "reasoning_content": "..."},
                "finish_reason": "length",
            }],
            "usage": {"prompt_tokens": 11, "completion_tokens": 99},
        }))
        with pytest.raises(LLMError, match="输出额度已被推理消耗"):
            chat([{"role": "user", "content": "hi"}], provider="kimi", session=session)
        row = session.scalars(select(LLMCall)).one()
        assert row.status == "error"


class TestModelSelectionAndCost:
    @respx.mock
    def test_selected_kimi_model_is_used_and_recorded(self, session, kimi_key):
        set_selected_model(session, "kimi", "kimi-k3")
        route = respx.post(KIMI_URL).mock(return_value=_kimi_resp("K3 回复"))
        result = chat([{"role": "user", "content": "hi"}], provider="kimi", session=session)
        req = json.loads(route.calls.last.request.content)
        assert req["model"] == "kimi-k3"
        assert result["model"] == "kimi-k3"
        row = session.scalars(select(LLMCall)).one()
        assert row.model == "kimi-k3"
        assert row.cost_estimate == pytest.approx(
            compute_cost("kimi", 11, 7, model="kimi-k3")
        )

    @respx.mock
    def test_cache_details_are_used_for_k31_cost(self, session, kimi_key):
        respx.post(KIMI_URL).mock(return_value=httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "正文"}}],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "prompt_tokens_details": {
                    "cached_tokens": 200, "cache_write_tokens": 300,
                },
            },
            "model": "kimi-k3.1-pro",
        }))
        result = chat([{"role": "user", "content": "hi"}], provider="kimi", session=session)
        expected = compute_cost(
            "kimi", 1000, 500, model="kimi-k3.1-pro",
            cached_tokens=200, cache_write_tokens=300,
        )
        assert result["cached_tokens"] == 200
        assert result["cache_write_tokens"] == 300
        assert result["cost_estimate"] == pytest.approx(expected)
        row = session.scalars(select(LLMCall)).one()
        assert row.cost_estimate == pytest.approx(expected)


class TestDefaultProviderSwitch:
    @respx.mock
    def test_switch_default_to_kimi_routes_correctly(self, session, kimi_key):
        """设置默认模型为 kimi 后，模块级 chat 不带 provider 也路由到 moonshot。"""
        set_default_provider(session, "kimi")
        kimi_route = respx.post(KIMI_URL).mock(return_value=_kimi_resp("k 回复"))
        deepseek_route = respx.post(DEEPSEEK_URL).mock(return_value=_kimi_resp("d 回复"))
        result = chat([{"role": "user", "content": "hi"}], session=session)
        assert kimi_route.called
        assert not deepseek_route.called
        assert result["content"] == "k 回复"


class TestVisionExtract:
    @respx.mock
    def test_request_body_format_and_base64(self, session, kimi_key):
        """vision_extract 走 OpenAI 兼容 image_url 消息格式，base64 编码正确。"""
        route = respx.post(KIMI_URL).mock(return_value=_kimi_resp('{"a": 1}'))
        image_bytes = b"\x89PNG\r\n\x1a\nfake-pixels"
        result = vision_extract(image_bytes, "识别这张训记截图", session=session)
        assert route.called
        req = json.loads(route.calls.last.request.content)
        assert req["model"] == "kimi-k3.1-pro"
        assert req["max_completion_tokens"] >= 2048  # 视觉抽取同样要留推理余量
        assert "max_tokens" not in req
        content = req["messages"][0]["content"]
        assert isinstance(content, list)
        assert content[0] == {"type": "text", "text": "识别这张训记截图"}
        assert content[1]["type"] == "image_url"
        url = content[1]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        b64 = url.split(",", 1)[1]
        assert base64.b64decode(b64) == image_bytes  # base64 编码正确
        assert result["content"] == '{"a": 1}'

    @respx.mock
    def test_vision_extract_forces_kimi_even_when_default_deepseek(self, session, kimi_key):
        """截图识别固定走 Kimi 多模态，与默认文本模型无关。"""
        kimi_route = respx.post(KIMI_URL).mock(return_value=_kimi_resp("{}"))
        deepseek_route = respx.post(DEEPSEEK_URL).mock(return_value=_kimi_resp("{}"))
        vision_extract(b"img", "prompt", session=session)
        assert kimi_route.called
        assert not deepseek_route.called

    @respx.mock
    def test_vision_extract_records_purpose(self, session, kimi_key):
        respx.post(KIMI_URL).mock(return_value=_kimi_resp("{}"))
        vision_extract(b"img", "prompt", session=session)
        row = session.scalars(select(LLMCall)).one()
        assert row.provider == "kimi"
        assert row.purpose == "vision_extract"

    def test_vision_extract_on_non_kimi_client_raises(self, session, kimi_key):
        client = LLMClient(session, provider="deepseek")
        with pytest.raises(LLMError):
            client.vision_extract(b"img", "prompt")


class TestConsecutiveFailures:
    def test_no_calls_returns_zero(self, session):
        assert get_consecutive_failures(session, "deepseek") == 0

    def test_trailing_errors_counted(self, session):
        session.add_all([
            LLMCall(provider="deepseek", model="m", status="ok"),
            LLMCall(provider="deepseek", model="m", status="error"),
            LLMCall(provider="deepseek", model="m", status="error"),
        ])
        session.commit()
        assert get_consecutive_failures(session, "deepseek") == 2

    def test_success_resets_count(self, session):
        session.add_all([
            LLMCall(provider="deepseek", model="m", status="error"),
            LLMCall(provider="deepseek", model="m", status="ok"),
        ])
        session.commit()
        assert get_consecutive_failures(session, "deepseek") == 0

    def test_other_provider_not_counted(self, session):
        session.add_all([
            LLMCall(provider="minimax", model="m", status="error"),
            LLMCall(provider="minimax", model="m", status="error"),
        ])
        session.commit()
        assert get_consecutive_failures(session, "deepseek") == 0
