"""V1-1 多模型统一适配层测试（PRD §6.3，2026-08-06 版）。

覆盖：统一接口返回结构、<think> 剥离（含无闭合标签异常输入）、
记账字段取自 usage、重试逻辑、成本计算。Kimi 行为见 test_llm_kimi.py（V2-1）。
"""
import json
import os

import httpx
import pytest
import respx
from sqlalchemy import select

from app.adapters.llm import (
    DEFAULT_PROVIDER,
    LLMClient,
    LLMError,
    chat,
    compute_cost,
    get_prices,
    strip_think,
)
from app.models import LLMCall

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
MINIMAX_URL = "https://api.minimaxi.com/v1/chat/completions"


def _resp(content="你好", model="deepseek-chat", prompt_tokens=11, completion_tokens=7):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
            "model": model,
        },
    )


@pytest.fixture
def deepseek_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek")
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-test-minimax")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------- <think> 剥离 ----------

class TestStripThink:
    def test_no_think_block(self):
        assert strip_think("正常正文") == "正常正文"

    def test_closed_block_stripped(self):
        assert strip_think("<think>推理过程</think>正文内容") == "正文内容"

    def test_multiline_block_stripped(self):
        assert strip_think("<think>第一行\n第二行</think>答案") == "答案"

    def test_unclosed_block_stripped(self):
        """无闭合标签的异常输入：从 <think> 截断到结尾。"""
        assert strip_think("<think>没有闭合的推理...") == ""

    def test_unclosed_block_preserves_prefix(self):
        assert strip_think("前文<think>未闭合") == "前文"

    def test_text_after_block_kept(self):
        assert strip_think("<think>想</think>第一段\n\n第二段") == "第一段\n\n第二段"

    def test_empty_and_none(self):
        assert strip_think("") == ""
        assert strip_think(None) == ""


# ---------- 统一接口 ----------

class TestChat:
    @respx.mock
    def test_unified_return_structure(self, session, deepseek_key):
        respx.post(DEEPSEEK_URL).mock(return_value=_resp("回复正文"))
        result = chat([{"role": "user", "content": "你好"}], session=session)
        assert result == {"content": "回复正文", "prompt_tokens": 11, "completion_tokens": 7}

    @respx.mock
    def test_default_provider_is_deepseek(self, session, deepseek_key):
        route = respx.post(DEEPSEEK_URL).mock(return_value=_resp())
        assert DEFAULT_PROVIDER == "deepseek"
        chat([{"role": "user", "content": "hi"}], session=session)
        assert route.called
        req = json.loads(route.calls.last.request.content)
        assert req["model"] == "deepseek-chat"

    @respx.mock
    def test_minimax_think_block_stripped_before_return(self, session, deepseek_key):
        content = "<think>用户说你好，应礼貌回应</think>你好！有什么可以帮你？"
        respx.post(MINIMAX_URL).mock(return_value=_resp(content, model="MiniMax-M2"))
        result = chat(
            [{"role": "user", "content": "你好"}],
            provider="minimax",
            session=session,
        )
        assert "<think>" not in result["content"]
        assert result["content"] == "你好！有什么可以帮你？"

    @respx.mock
    def test_model_override(self, session, deepseek_key):
        route = respx.post(DEEPSEEK_URL).mock(return_value=_resp())
        chat([{"role": "user", "content": "hi"}], model_override="deepseek-reasoner", session=session)
        req = json.loads(route.calls.last.request.content)
        assert req["model"] == "deepseek-reasoner"

    def test_unknown_provider_raises(self, session, deepseek_key):
        with pytest.raises(LLMError):
            chat([{"role": "user", "content": "hi"}], provider="no-such", session=session)

    def test_missing_key_raises(self, session, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        from app.config import get_settings

        get_settings.cache_clear()
        try:
            with pytest.raises(LLMError):
                chat([{"role": "user", "content": "hi"}], session=session)
        finally:
            get_settings.cache_clear()


# ---------- 记账（usage 字段 + 成本） ----------

class TestAccounting:
    @respx.mock
    def test_tokens_taken_from_usage_field(self, session, deepseek_key):
        """prompt/completion_tokens 必须等于 API usage 字段（禁止本地估算）。"""
        respx.post(DEEPSEEK_URL).mock(
            return_value=_resp(prompt_tokens=123, completion_tokens=45)
        )
        result = chat([{"role": "user", "content": "你好"}], purpose="test", session=session)
        assert result["prompt_tokens"] == 123
        assert result["completion_tokens"] == 45
        row = session.scalars(select(LLMCall)).one()
        assert row.provider == "deepseek"
        assert row.model == "deepseek-chat"
        assert row.purpose == "test"
        assert row.prompt_tokens == 123
        assert row.completion_tokens == 45
        assert row.status == "ok"

    @respx.mock
    def test_cost_estimate_from_price_table(self, session, deepseek_key):
        respx.post(DEEPSEEK_URL).mock(
            return_value=_resp(prompt_tokens=1_000_000, completion_tokens=500_000)
        )
        chat([{"role": "user", "content": "hi"}], session=session)
        row = session.scalars(select(LLMCall)).one()
        prices = get_prices()["deepseek"]
        expected = 1.0 * prices["prompt"] + 0.5 * prices["completion"]
        assert row.cost_estimate == pytest.approx(expected)

    def test_compute_cost_configurable_via_env(self, monkeypatch):
        """单价表可配置：LLM_PRICES_JSON 环境变量覆盖。"""
        monkeypatch.setenv(
            "LLM_PRICES_JSON",
            json.dumps({"deepseek": {"prompt": 10.0, "completion": 20.0}}),
        )
        assert compute_cost("deepseek", 1_000_000, 1_000_000) == pytest.approx(30.0)

    def test_compute_cost_default_table(self, monkeypatch):
        monkeypatch.delenv("LLM_PRICES_JSON", raising=False)
        prices = get_prices()["deepseek"]
        assert compute_cost("deepseek", 2_000_000, 0) == pytest.approx(2 * prices["prompt"])
        assert compute_cost("deepseek", 0, 0) == 0.0

    @respx.mock
    def test_missing_usage_raises_llm_error(self, session, deepseek_key):
        """响应无 usage 字段时禁止估算，直接报错。"""
        respx.post(DEEPSEEK_URL).mock(
            return_value=httpx.Response(
                200, json={"choices": [{"message": {"content": "hi"}}]}
            )
        )
        with pytest.raises(LLMError):
            chat([{"role": "user", "content": "hi"}], session=session)


# ---------- 重试 ----------

class TestRetry:
    @respx.mock
    def test_retry_twice_then_success(self, session, deepseek_key):
        route = respx.post(DEEPSEEK_URL).mock(
            side_effect=[
                httpx.Response(500, json={"error": "boom"}),
                httpx.Response(500, json={"error": "boom"}),
                _resp("成功了"),
            ]
        )
        client = LLMClient(session, sleep=lambda _: None)
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result["content"] == "成功了"
        assert route.call_count == 3

    @respx.mock
    def test_retry_exhausted_raises_and_records_failure(self, session, deepseek_key):
        route = respx.post(DEEPSEEK_URL).mock(return_value=httpx.Response(500, json={}))
        client = LLMClient(session, sleep=lambda _: None)
        with pytest.raises(LLMError):
            client.chat([{"role": "user", "content": "hi"}], purpose="test")
        assert route.call_count == 3  # 首次 + 重试 2 次
        row = session.scalars(select(LLMCall)).one()
        assert row.status == "error"

    @respx.mock
    def test_client_error_4xx_no_retry(self, session, deepseek_key):
        route = respx.post(DEEPSEEK_URL).mock(
            return_value=httpx.Response(400, json={"error": "bad request"})
        )
        client = LLMClient(session, sleep=lambda _: None)
        with pytest.raises(LLMError):
            client.chat([{"role": "user", "content": "hi"}])
        assert route.call_count == 1

    @respx.mock
    def test_transport_error_retried(self, session, deepseek_key):
        route = respx.post(DEEPSEEK_URL).mock(
            side_effect=[httpx.ConnectError("net down"), _resp("ok")]
        )
        client = LLMClient(session, sleep=lambda _: None)
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result["content"] == "ok"
        assert route.call_count == 2
