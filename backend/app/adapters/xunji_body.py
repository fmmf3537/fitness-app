"""训记身体数据 API 适配器（PRD §6.1b）。

- 独立 Key：XUNJI_BODY_API_KEY（xjbody_ 前缀），与训练 Key 分离；
- 限频：同 key 同 endpoint 15s/次，复用统一限频装饰器（kind="read"，
  query/upsert 为不同 rl_key 维度，互不阻塞）；
- 写接口三段式：dry_run=True 预览取 res.summary → 用户确认 →
  dry_run=False + confirmed=True 执行；未确认的 dry_run=False 直接拒绝；
- 训记类型仅 weight/bodyfat/围度；注意腰围字段固定拼写 weist（勿"修正"）。
"""
from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy.orm import Session

from app.adapters.xunji import XunjiClient
from app.config import get_settings

BODY_QUERY_URL = "https://api.xunjiapp.cn/open/body/query_gzip"
BODY_UPSERT_URL = "https://api.xunjiapp.cn/open/body/upsert_gzip"


class XunjiBodyClient(XunjiClient):
    """训记身体数据客户端：复用 XunjiClient 的限频/gzip/too-frequent 重试。"""

    def __init__(self, session: Session, api_key: str | None = None, **kwargs: Any) -> None:
        if api_key is None:
            api_key = get_settings().xunji_body_api_key
            if not api_key:
                raise RuntimeError(
                    "XUNJI_BODY_API_KEY 未配置：请在环境变量或 .env 中设置"
                )
        super().__init__(session, api_key=api_key, **kwargs)

    # ---------- 查询身体数据（只读） ----------

    def query_body_metrics(
        self,
        start_date: str,
        end_date: str,
        *,
        types: Sequence[str] = ("weight", "bodyfat"),
        include_latest: bool = True,
        include_records: bool = True,
        limit: int = 500,
        offset: int = 0,
    ) -> dict:
        """查询身体数据（gzip 响应），限频维度：body:query。"""
        body = {
            "start_date": start_date,
            "end_date": end_date,
            "types": list(types),
            "include_latest": include_latest,
            "include_records": include_records,
            "limit": limit,
            "offset": offset,
        }
        return self._post(BODY_QUERY_URL, body, kind="read", rl_key="body:query")

    # ---------- 写入身体数据（三段式确认流） ----------

    def upsert_body_metrics(
        self,
        records: list[dict],
        dry_run: bool = True,
        confirmed: bool = False,
    ) -> dict:
        """写入身体数据（按 datestr+type upsert）。

        默认 dry_run=True（预览，返回 res.summary）；真实写入必须
        dry_run=False 且 confirmed=True，否则抛 ValueError 且不发请求。
        """
        if not dry_run and not confirmed:
            raise ValueError(
                "真实写入必须先经 dry_run 预览并由用户确认（confirmed=True）"
            )
        datestrs = sorted(
            {str(r.get("datestr", "")) for r in records if isinstance(r, dict)}
        )
        body = {
            "schema_version": "body_open_api_v1",
            "client_request_id": str(uuid.uuid4()),
            "dry_run": dry_run,
            "confirmed": confirmed,
            "records": records,
        }
        rl_key = "body:upsert:" + (",".join(datestrs) or "unknown")
        return self._post(BODY_UPSERT_URL, body, kind="read", rl_key=rl_key)
