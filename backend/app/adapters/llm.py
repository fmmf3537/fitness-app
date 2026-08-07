"""多模型统一适配层（PRD §6.3，2026-08-07 V2-1 版）。

纪律：
- 统一接口 chat(messages, model_override=None, **opts) ->
  {content, prompt_tokens, completion_tokens}，OpenAI 兼容协议；
- Provider 注册表按 PRD 三行：DeepSeek（首发默认）、MiniMax（MiniMax-M2，
  输出含 <think> 块，content 落库前必须剥离）、Kimi（V2-1 接入，默认 kimi-k2.6）；
- kimi-k2.6 默认开思考模式：reasoning_tokens 计入 completion_tokens，调用时
  max_tokens 默认留足 2048；响应可能带 reasoning_content 字段，落库只取 content
  （与 MiniMax <think> 剥离并列处理）；
- 截图识别走 vision_extract(image_bytes, prompt)：固定 Kimi 多模态，
  OpenAI 兼容 image_url + base64 消息格式；
- Key 只从 settings 表（Fernet 加密）或环境变量读取，禁止硬编码；
- 每次调用写 llm_call 记账：token 数必须取自 API 响应 usage 字段，禁止本地估算；
- 成本按可配置单价表（环境变量 LLM_PRICES_JSON 覆盖默认表）计算；
- 调用失败重试 2 次（共 3 次尝试），仍失败抛 LLMError。
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import decrypt_value, encrypt_value, get_settings
from app.models import LLMCall, Setting

# ---------- Provider 注册表（PRD §6.3） ----------

PROVIDERS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "implemented": True,
    },
    "minimax": {
        "base_url": "https://api.minimaxi.com/v1",
        "default_model": "MiniMax-M2",
        "implemented": True,
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        # 2026-08-07 GET /v1/models 实测在列；k2/k2.5/moonshot-v1 全系列已下线或 8/31 下线，禁用
        "default_model": "kimi-k2.6",
        "fallback_model": "kimi-k3",
        "implemented": True,  # V2-1 接入
    },
}

# kimi-k2.6 默认开思考模式：reasoning_tokens 计入 completion_tokens，
# 实测 max_tokens=100 时 99 个全被推理吃光、正文为空 → 默认留足 2048
KIMI_DEFAULT_MAX_TOKENS = 2048
# 视觉抽取输出为结构化 JSON，余量加大
VISION_DEFAULT_MAX_TOKENS = 4096
DEFAULT_PROVIDER = "deepseek"

# 默认单价表（元 / 1M tokens，2026-08-07 按各平台定价页校准）；
# 可用环境变量 LLM_PRICES_JSON 覆盖，如 {"deepseek": {"prompt": 1.0, "completion": 2.0}}
_DEFAULT_PRICES: dict[str, dict[str, float]] = {
    # deepseek-chat → v4 系列：输入（缓存未命中）1 元 / 输出 2 元（api-docs.deepseek.com）
    "deepseek": {"prompt": 1.0, "completion": 2.0},
    # MiniMax-M2：输入 2.1 元 / 输出 8.4 元（platform.minimaxi.com/docs/guides/pricing-paygo）
    "minimax": {"prompt": 2.1, "completion": 8.4},
    # kimi-k2.6：输入 6.5 元 / 输出 27 元（platform.kimi.com/docs/pricing）
    "kimi": {"prompt": 6.5, "completion": 27.0},
}

MAX_RETRIES = 2  # 失败后重试 2 次，共 3 次尝试
RETRY_BACKOFF_S = 1.0


class LLMError(Exception):
    """LLM 调用失败（含重试耗尽、响应畸形、Key 缺失等）。"""


# ---------- <think> 剥离 ----------

_THINK_CLOSED = re.compile(r"<think>.*?</think>", re.S | re.I)
_THINK_UNCLOSED = re.compile(r"<think>.*$", re.S | re.I)


def strip_think(content: str | None) -> str:
    """剥离 MiniMax-M2 等推理模型输出中的 <think> 块（含无闭合标签的异常输入）。"""
    if not content:
        return ""
    text = _THINK_CLOSED.sub("", content)
    text = _THINK_UNCLOSED.sub("", text)  # 无闭合标签：截断到结尾
    return text.strip()


# ---------- 成本 ----------

def get_prices() -> dict[str, dict[str, float]]:
    """读取单价表：环境变量 LLM_PRICES_JSON 覆盖默认表。"""
    raw = os.getenv("LLM_PRICES_JSON")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                merged = {k: dict(v) for k, v in _DEFAULT_PRICES.items()}
                for name, price in data.items():
                    if isinstance(price, dict):
                        merged.setdefault(name, {}).update(
                            {k: float(v) for k, v in price.items() if k in ("prompt", "completion")}
                        )
                return merged
        except (ValueError, TypeError):
            pass  # 配置畸形时回退默认表
    return {k: dict(v) for k, v in _DEFAULT_PRICES.items()}


def compute_cost(provider: str, prompt_tokens: int, completion_tokens: int) -> float:
    """按单价表估算成本（元）。"""
    price = get_prices().get(provider, {})
    return (
        prompt_tokens / 1_000_000 * price.get("prompt", 0.0)
        + completion_tokens / 1_000_000 * price.get("completion", 0.0)
    )


# ---------- settings 表 Key 存取（Fernet 加密） ----------

def _get_or_create_settings(session: Session) -> Setting:
    row = session.scalars(select(Setting)).first()
    if row is None:
        row = Setting()
        session.add(row)
        session.flush()
    return row


def get_stored_keys(session: Session) -> dict[str, str]:
    """从 settings 表读取并解密全部 LLM Key。"""
    row = session.scalars(select(Setting)).first()
    if row is None or not row.llm_keys_json_enc:
        return {}
    try:
        data = json.loads(decrypt_value(row.llm_keys_json_enc))
    except (ValueError, TypeError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str) and v}


def save_api_key(session: Session, provider: str, api_key: str) -> None:
    """加密保存某厂商 Key 到 settings 表。"""
    keys = get_stored_keys(session)
    keys[provider] = api_key
    row = _get_or_create_settings(session)
    row.llm_keys_json_enc = encrypt_value(json.dumps(keys, ensure_ascii=False))
    session.commit()


def get_default_provider(session: Session) -> str:
    row = session.scalars(select(Setting)).first()
    if row is not None and row.default_llm in PROVIDERS:
        return row.default_llm
    return DEFAULT_PROVIDER


def set_default_provider(session: Session, provider: str) -> None:
    if provider not in PROVIDERS:
        raise LLMError(f"未知 provider：{provider}")
    row = _get_or_create_settings(session)
    row.default_llm = provider
    session.commit()


def resolve_api_key(session: Session | None, provider: str) -> str:
    """Key 解析优先级：settings 表（加密存储）→ 环境变量。找不到返回空串。"""
    if session is not None:
        key = get_stored_keys(session).get(provider)
        if key:
            return key
    settings = get_settings()
    env_keys = {
        "deepseek": settings.deepseek_api_key,
        "minimax": settings.minimax_api_key,
        "kimi": settings.kimi_api_key,
    }
    return env_keys.get(provider, "")


# ---------- Key 有效性验证（PUT 设置时调用） ----------

def verify_api_key(provider: str, api_key: str, *, http: httpx.Client | None = None) -> bool:
    """调一次该厂商轻量 chat 接口验证 Key 有效（不产生记账）。"""
    if provider not in PROVIDERS:
        raise LLMError(f"未知 provider：{provider}")
    if not PROVIDERS[provider]["implemented"]:
        raise NotImplementedError(f"provider {provider} 尚未接入")
    client = http or httpx.Client(timeout=30.0)
    try:
        resp = client.post(
            f"{PROVIDERS[provider]['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": PROVIDERS[provider]["default_model"],
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
        )
    except httpx.HTTPError:
        return False
    finally:
        if http is None:
            client.close()
    return resp.status_code == 200


# ---------- 客户端 ----------

class LLMClient:
    """统一 chat 客户端。sleep/http 可注入以便测试。"""

    def __init__(
        self,
        session: Session | None = None,
        provider: str | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        http: httpx.Client | None = None,
    ) -> None:
        self._session = session
        self.provider = provider or (
            get_default_provider(session) if session is not None else DEFAULT_PROVIDER
        )
        if self.provider not in PROVIDERS:
            raise LLMError(f"未知 provider：{self.provider}")
        if not PROVIDERS[self.provider]["implemented"]:
            raise NotImplementedError(f"provider {self.provider} 尚未接入")
        self._api_key = resolve_api_key(session, self.provider)
        if not self._api_key:
            raise LLMError(f"provider {self.provider} 的 API Key 未配置（settings 表或环境变量）")
        self._sleep = sleep
        self._http = http or httpx.Client(timeout=60.0)

    def chat(
        self,
        messages: list[dict],
        model_override: str | None = None,
        purpose: str | None = None,
        **opts: Any,
    ) -> dict:
        """统一接口：返回 {content, prompt_tokens, completion_tokens}。"""
        model = model_override or PROVIDERS[self.provider]["default_model"]
        if self.provider == "kimi" and "max_tokens" not in opts:
            # kimi-k2.6 思考模式会吞 completion_tokens，必须留足推理余量
            opts["max_tokens"] = KIMI_DEFAULT_MAX_TOKENS
        body = {"model": model, "messages": messages, **opts}
        url = f"{PROVIDERS[self.provider]['base_url']}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        data = self._post_with_retry(url, body, headers, purpose, model)
        return self._parse_and_record(data, purpose, model)

    def vision_extract(
        self,
        image_bytes: bytes,
        prompt: str,
        *,
        model_override: str | None = None,
        max_tokens: int = VISION_DEFAULT_MAX_TOKENS,
        mime: str = "image/png",
    ) -> dict:
        """截图识别（V2-1）：Kimi 多模态，OpenAI 兼容 image_url + base64 消息格式。

        仅 kimi provider 支持（kimi-k2.6/k3 原生视觉）；推理内容不入库，只取 content。
        """
        if self.provider != "kimi":
            raise LLMError("vision_extract 仅支持 kimi provider（多模态）")
        b64 = base64.b64encode(image_bytes).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }
        ]
        return self.chat(
            messages,
            model_override=model_override,
            purpose="vision_extract",
            max_tokens=max_tokens,
        )

    def _post_with_retry(
        self, url: str, body: dict, headers: dict, purpose: str | None, model: str
    ) -> dict:
        last_error = ""
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self._http.post(url, json=body, headers=headers)
            except httpx.HTTPError as exc:  # 网络层错误：可重试
                last_error = f"网络错误：{exc}"
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        raise LLMError("响应不是合法 JSON") from None
                if 400 <= resp.status_code < 500 and resp.status_code != 429:
                    raise LLMError(f"HTTP {resp.status_code}：{resp.text[:200]}") from None
                last_error = f"HTTP {resp.status_code}"
            if attempt < MAX_RETRIES:
                self._sleep(RETRY_BACKOFF_S * (attempt + 1))
        self._record(purpose, model, None, None, None, status="error")
        raise LLMError(f"重试 {MAX_RETRIES} 次后仍失败：{last_error}")

    def _parse_and_record(self, data: Any, purpose: str | None, model: str) -> dict:
        try:
            content = data["choices"][0]["message"]["content"]
            usage = data["usage"]
            prompt_tokens = int(usage["prompt_tokens"])
            completion_tokens = int(usage["completion_tokens"])
        except (KeyError, IndexError, TypeError, ValueError):
            self._record(purpose, model, None, None, None, status="error")
            raise LLMError("响应缺少 choices/usage 字段（禁止本地估算 token）") from None
        cost = compute_cost(self.provider, prompt_tokens, completion_tokens)
        self._record(purpose, model, prompt_tokens, completion_tokens, cost, status="ok")
        return {
            "content": strip_think(content),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }

    def _record(
        self,
        purpose: str | None,
        model: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        cost: float | None,
        *,
        status: str,
    ) -> None:
        if self._session is None:
            return
        self._session.add(
            LLMCall(
                provider=self.provider,
                model=model,
                purpose=purpose,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_estimate=cost,
                status=status,
            )
        )
        self._session.commit()


def chat(
    messages: list[dict],
    model_override: str | None = None,
    *,
    session: Session | None = None,
    provider: str | None = None,
    purpose: str | None = None,
    **opts: Any,
) -> dict:
    """模块级统一接口（PRD §6.3）。session 为空时自动创建短会话。"""
    if session is not None:
        return LLMClient(session, provider).chat(
            messages, model_override=model_override, purpose=purpose, **opts
        )
    from app.db import SessionLocal

    own_session = SessionLocal()
    try:
        return LLMClient(own_session, provider).chat(
            messages, model_override=model_override, purpose=purpose, **opts
        )
    finally:
        own_session.close()


def vision_extract(
    image_bytes: bytes,
    prompt: str,
    *,
    session: Session | None = None,
    model_override: str | None = None,
    max_tokens: int = VISION_DEFAULT_MAX_TOKENS,
    mime: str = "image/png",
) -> dict:
    """模块级截图识别接口：固定走 Kimi 多模态（与默认文本模型无关）。"""
    if session is not None:
        return LLMClient(session, "kimi").vision_extract(
            image_bytes, prompt, model_override=model_override, max_tokens=max_tokens, mime=mime
        )
    from app.db import SessionLocal

    own_session = SessionLocal()
    try:
        return LLMClient(own_session, "kimi").vision_extract(
            image_bytes, prompt, model_override=model_override, max_tokens=max_tokens, mime=mime
        )
    finally:
        own_session.close()


def get_consecutive_failures(session: Session, provider: str) -> int:
    """该 provider 最近连续失败次数（llm_call 表尾部 status=error 的条数）。"""
    rows = session.scalars(
        select(LLMCall).where(LLMCall.provider == provider).order_by(LLMCall.id.desc())
    ).all()
    n = 0
    for row in rows:
        if row.status == "error":
            n += 1
        else:
            break
    return n
