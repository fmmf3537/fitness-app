"""V1-1 LLM 集成测试（真实外呼，显式门禁）。

运行方式：$env:RUN_LLM_INTEGRATION='1'; pytest -m integration tests/test_llm_integration.py
"""
import os

import pytest
from sqlalchemy import select

from app.adapters.llm import chat
from app.models import LLMCall


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_LLM_INTEGRATION") != "1",
    reason="真实外呼 DeepSeek 消耗额度，默认跳过；手动运行：$env:RUN_LLM_INTEGRATION='1'; pytest -m integration tests/test_llm_integration.py",
)
def test_integration_deepseek_real_call(session):
    """真实调用 DeepSeek 发送"你好"，断言 usage 字段非零且记账落库。"""
    result = chat(
        [{"role": "user", "content": "你好"}],
        purpose="integration_test",
        max_tokens=16,
        session=session,
    )
    assert result["content"].strip()
    assert result["prompt_tokens"] > 0
    assert result["completion_tokens"] > 0
    row = session.scalars(select(LLMCall)).one()
    assert row.provider == "deepseek"
    assert row.prompt_tokens > 0
    assert row.completion_tokens > 0
    assert row.status == "ok"
    assert row.cost_estimate > 0
