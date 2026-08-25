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


# =====================================================================
# M3-3：LLM Key 按用户隔离
# =====================================================================


def test_no_key_raises_LLMKeyNotConfiguredError(monkeypatch):
    """M3-3：未配置 Key 时抛专用错误（继承自 LLMError）。"""
    # 清理所有可能的 Key 来源
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    from app.config import get_settings
    get_settings.cache_clear()

    from app.adapters.llm import LLMKeyNotConfiguredError
    with pytest.raises(LLMKeyNotConfiguredError) as exc:
        LLMClient(session=None, provider="deepseek")
    assert "deepseek" in str(exc.value)
    assert "未配置" in str(exc.value)


def test_user_a_key_not_visible_to_user_b(session):
    """M3-3：用户 A 存的 Key，用户 B 拿不到（按 user_id 隔离）。"""
    from app.adapters import llm as llm_module
    from app.services import users as user_service

    # 用户 1 = alice（conftest 预建）
    # 创建用户 2
    try:
        user_service.create_user(session, username="bob", password="test-pass", role="user")
    except ValueError:
        session.rollback()
    user_b = user_service.get_user_by_username(session, "bob")
    assert user_b is not None

    llm_module.save_api_key(session, "deepseek", "sk-user-a-secret", user_id=1)
    llm_module.save_api_key(session, "deepseek", "sk-user-b-secret", user_id=user_b.id)

    keys_a = llm_module.get_stored_keys(session, user_id=1)
    keys_b = llm_module.get_stored_keys(session, user_id=user_b.id)

    assert keys_a.get("deepseek") == "sk-user-a-secret"
    assert keys_b.get("deepseek") == "sk-user-b-secret"
    # 关键：A 拿不到 B 的 key，B 拿不到 A 的
    assert "sk-user-b-secret" not in keys_a.values()
    assert "sk-user-a-secret" not in keys_b.values()


def test_resolve_api_key_user_specific(session, monkeypatch):
    """M3-3：resolve_api_key 必须按 user_id 取 settings 表的 Key，忽略环境变量。"""
    from app.adapters.llm import save_api_key, resolve_api_key
    from app.services import users as user_service

    # 创建用户 2
    try:
        user_service.create_user(session, username="bob2", password="test-pass", role="user")
    except ValueError:
        session.rollback()
    user_b = user_service.get_user_by_username(session, "bob2")

    # 环境变量有 key
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-default")
    from app.config import get_settings
    get_settings.cache_clear()

    # 用户 1 存了自己的 key（覆盖环境变量）
    save_api_key(session, "deepseek", "sk-user-1", user_id=1)

    # 用户 1 拿自己的 key
    assert resolve_api_key(session, "deepseek", user_id=1) == "sk-user-1"
    # 用户 2 没存，回退到环境变量
    assert resolve_api_key(session, "deepseek", user_id=user_b.id) == "sk-env-default"
    # 不传 user_id 也回退到环境变量
    assert resolve_api_key(session, "deepseek") == "sk-env-default"

    get_settings.cache_clear()


def test_LLMClient_uses_user_specific_key(session, monkeypatch, respx_mock):
    """M3-3：LLMClient(user_id=X) 构造时按 X 取 settings 表 Key，发请求时用 X 的 key。"""
    from app.adapters.llm import save_api_key, LLMKeyNotConfiguredError
    from app.config import get_settings

    # 清环境变量避免干扰
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    get_settings.cache_clear()

    # 用户 1 存 deepseek key
    save_api_key(session, "deepseek", "sk-user-1-key", user_id=1)
    # 用户 2 不存（alice 已被 conftest 预建，不另建）

    # mock 远端 deepseek 端点
    route = respx_mock.post(DEEPSEEK_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                "model": "deepseek-chat",
            },
        )
    )

    # 用户 1 能调通
    client1 = LLMClient(session=session, provider="deepseek", user_id=1)
    result = client1.chat([{"role": "user", "content": "hi"}])
    assert result["content"] == "ok"
    # 验证请求头用的是用户 1 的 key
    last_request = route.calls.last.request
    assert last_request.headers["authorization"] == "Bearer sk-user-1-key"

    # 用户 999 不存在 + 没 key，构造应抛 LLMKeyNotConfiguredError
    with pytest.raises(LLMKeyNotConfiguredError):
        LLMClient(session=session, provider="deepseek", user_id=999)
